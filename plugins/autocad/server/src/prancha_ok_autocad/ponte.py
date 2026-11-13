"""A ponte com o desenho profissional (0.7.0, contrato C4): o autocad-mcp-pro 1.6.0 (MIT, Umutcan Edizsalan) como
processo filho do conector, por stdio, no ambiente fixo de desenho_pro/ (projeto em docs: proxy.md).

    p = obter()                                  # a ponte do conector (uma por processo)
    p.preparar_em_segundo_plano()                # na subida do conector: só o `uv sync` (nunca o filho)
    await p.chamar_async(nome, args, prazo_s)    # das ferramentas async do servidor (não trava o loop dele)
    p.chamar(nome, args, prazo_s)                # das ferramentas síncronas (o gerar_planta)
    p.situacao(); p.fim_do_log(); p.encerrar()

Como funciona:
- o filho é o Python do .venv de desenho_pro rodando o lançador (`python -I -X utf8 desenho_pro/lancador.py`), com o
  ambiente do contrato do lançador (o topo do lancador.py): AUTOCAD_MCP_BACKEND, PRANCHA_OK_DESENHO_PASTAS (a pasta
  do desenho aberto e a nossa de saída), _BASE, _LOG, _BLOQUEADAS e os prazos;
- sobe na 1ª chamada (preguiçoso) e fica de pé (sessão persistente) numa thread com loop asyncio próprio; as pastas
  permitidas são lidas pelo lançador só na subida, então pasta nova (outro desenho aberto) sobe outro filho;
- o ambiente (81 pacotes, ~50 MB na 1ª vez) se instala em segundo plano na subida do conector, com o uv que roda o
  conector;
- antes de cada chamada, um ping: filho morto antes da chamada sobe de novo e a chamada segue (é seguro); morto
  DURANTE a chamada, sobe de novo na próxima e esta NÃO se repete (pode ter desenhado metade);
- prazo por chamada (45 s; 15 s na busca); estourou: avisa o filho (notifications/cancelled, para ele desfazer a
  transação), espera um pouco e o derruba; a próxima sobe outro. A chamada que o cliente cancela (Esc) tem o mesmo
  fim, e o canal com o AutoCAD só se solta com o filho derrubado; cancelada na subida, o filho que subia cai também;
- 3 quedas em 5 min (prazos estourados contam): desliga até o conector reiniciar, com o fim do log na mensagem;
- uma chamada por vez, e no COM com o `autocad.canal_autocad` pego: o AutoCAD recusa COM com um comando LISP em
  andamento, e o pedido do LISP entraria numa linha de comando ocupada;
- resultado repassado como CallToolResult: texto até 60 mil caracteres, imagem até ~1 MB; o structuredContent sai
  (é o mesmo JSON do texto). `meta["pranchaOk"]["enviada"]` diz se a chamada chegou a sair para o filho (o gerar_planta
  só cai no desenho do Prancha Ok quando nada foi desenhado);
- logs em %USERPROFILE%\\.prancha-ok\\logs: desenho-pro.log (o do filho, rotativo, 512 KB + 1 cópia, pelo lançador),
  desenho-pro.stderr.log (truncado a cada subida) e desenho-pro.instalacao.log (o último `uv sync`).

Variáveis do conector: PRANCHA_OK_DESENHO_PRO=0 desliga tudo; PRANCHA_OK_DESENHO_BACKEND ("ezdxf" nos testes, fora
do Windows; "com" é o padrão no Windows) força o backend do filho; PRANCHA_OK_DESENHO_SAIDA troca a pasta de saída.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import McpError

# O ClientSession avisa, a cada chamada, que a ferramenta não está na lista (no modo search o filho só lista
# search_tools e call_tool; as outras se chamam pelo nome). É esperado: o aviso não vai ao log do assistente.
logging.getLogger("client").addFilter(lambda r: "not listed by server" not in r.getMessage())

#: desenho_pro/ fica ao lado de src/ nos três artefatos (.mcpb, plugin, zip): o mesmo parents[2] de instalacao.ORIGEM.
PASTA_AMBIENTE = Path(__file__).resolve().parents[2] / "desenho_pro"

# Limites do que volta ao assistente. O Claude Code recusa resposta de MCP acima de ~25 mil tokens
# (MAX_MCP_OUTPUT_TOKENS); o Claude Desktop, perto de 1 MB.
MAX_TEXTO = 60_000          # caracteres de texto por resposta (~15 mil tokens)
MAX_IMAGEM_B64 = 1_400_000  # ~1 MB de PNG (base64: 4 caracteres a cada 3 bytes)
MAX_ARGUMENTOS = 200_000    # caracteres do JSON dos argumentos (o spec de uma planta grande cabe com folga)

#: Sempre fora (o lançador também tira): o system_launch liga ou ABRE o AutoCAD; o system_set_variable muda variável do
#: AutoCAD (D24=a: o Claude não muda variável nenhuma pelo pro). As outras ferramentas ficam como vêm (D22=c).
BLOQUEADAS_SEMPRE = ("system_launch", "system_set_variable")
PRAZO_BUSCA_S = 15.0
PRAZO_CHAMADA_S = 45.0
#: Onde vai a marca de "chegou a sair para o filho" no CallToolResult.
META = "pranchaOk"

MSG_SO_WINDOWS = ("O desenho profissional (planta por especificação, paredes, portas, janelas, cotas, quadros) só "
                  "funciona no Windows, com o AutoCAD completo aberto.")
MSG_DESLIGADO = ("O desenho profissional está desligado neste computador (PRANCHA_OK_DESENHO_PRO=0). As outras "
                 "ferramentas do conector continuam, e a planta gerada sai no desenho do Prancha Ok (gerar_planta).")


class DesenhoIndisponivel(RuntimeError):
    """Não deu para falar com o desenho profissional; a mensagem é para o assistente repassar."""


def _casa() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def pasta_de_saida() -> Path:
    """A pasta nossa onde o desenho profissional pode gravar (PDF, PNG, DWG exportado), além da do desenho aberto. Fora
    de qualquer `.prancha-ok` (o lançador recusa tudo ali: o LISP confiável e a troca com o AutoCAD) e fora de AppData
    (o MSIX do Claude Desktop desviaria o caminho, e o AutoCAD, que é quem grava no COM, não acharia)."""
    escolhida = (os.environ.get("PRANCHA_OK_DESENHO_SAIDA") or "").strip()
    return Path(escolhida) if escolhida else _casa() / "Documents" / "Prancha Ok"


@dataclass
class Config:
    pasta_ambiente: Path                 # desenho_pro/ (pyproject.toml + uv.lock + .python-version + lançador)
    lancador: Path                       # desenho_pro/lancador.py
    pasta_log: Path                      # %USERPROFILE%\.prancha-ok\logs
    base: Path | None = None             # PRANCHA_OK_DESENHO_BASE do lançador (None: o padrão dele)
    backend: str = "com"                 # "com" (Windows, AutoCAD ao vivo) ou "ezdxf" (testes no Linux)
    bloqueadas: tuple[str, ...] = BLOQUEADAS_SEMPRE
    prazo_subida_s: float = 30.0         # spawn + initialize (com o ambiente já instalado; medido 1,3 s)
    prazo_sync_s: float = 600.0          # 1ª instalação do ambiente (download de ~50 MB)
    prazo_busca_s: float = PRAZO_BUSCA_S
    prazo_chamada_s: float = PRAZO_CHAMADA_S  # abaixo dos ~60 s em que o cliente MCP corta
    folga_cancelar_s: float = 3.0        # entre o cancelled e o kill: o filho desfaz a transação
    max_quedas: int = 3
    janela_quedas_s: float = 300.0
    uv: str | None = None                # None: o UV do `uv run` que subiu o conector, depois o PATH
    extra_env: dict[str, str] = field(default_factory=dict)
    #: A recusa (texto para a pessoa) antes de usar uma ferramenta, ou None: pode (AutoCAD aberto, COM, não LT).
    verificar_autocad: Callable[[], str | None] | None = None
    #: As pastas onde o filho pode ler e gravar (a do desenho aberto e a de saída), conferidas antes de cada chamada.
    pastas: Callable[[], list[Path]] | None = None
    #: O lock do canal com o AutoCAD (autocad.canal_autocad), pego durante cada chamada no COM.
    canal: threading.Lock | None = None


def achar_uv(preferido: str | None = None) -> str | None:
    """O uv: o que rodou o conector (o `uv run` põe o caminho em UV), o do PATH, os lugares do instalador."""
    candidatos = [preferido, os.environ.get("UV"), shutil.which("uv")]
    casa = _casa()
    nome = "uv.exe" if os.name == "nt" else "uv"
    candidatos += [str(casa / ".local" / "bin" / nome), str(casa / ".cargo" / "bin" / nome)]
    return next((c for c in candidatos if c and Path(c).is_file()), None)


def python_do_ambiente(pasta: Path) -> Path:
    return pasta / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# Do ambiente do conector para o filho, só o proxy e os certificados (o lançador apaga o resto de qualquer jeito).
_PASSAM = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
           "TMP", "TEMP", "COMPUTERNAME", "LANG", "LC_ALL")


#: Das variáveis do uv, só o cache e o TLS do sistema (proxy de empresa) passam: UV_PYTHON, UV_INDEX_URL,
#: UV_NO_BINARY... trocariam o Python e as opções do ambiente fixo (seguranca.md §3).
_UV_PASSAM = ("UV_CACHE_DIR", "UV_NATIVE_TLS")


def _ambiente_do_uv() -> dict[str, str]:
    """O ambiente do conector para o `uv sync`, sem as variáveis do uv (fora as de `_UV_PASSAM`) e sem o que apontaria
    para o ambiente do próprio conector."""
    return {k: v for k, v in os.environ.items()
            if k.upper() not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX")
            and (not k.upper().startswith("UV_") or k.upper() in _UV_PASSAM)}


def comando_do_sync(uv: str, pasta: Path, offline: bool) -> list[str]:
    """O `uv sync` do ambiente fixo: pelo lock (`--frozen`), sem o `uv.toml` da pessoa (`--no-config`), no Python do
    `.python-version` (dito no comando: nada de fora o troca) e, com o ambiente já instalado, sem rede (`--offline`)."""
    versao = (pasta / ".python-version").read_text(encoding="utf-8").strip()
    return [uv, "sync", "--frozen", "--no-dev", "--compile-bytecode", "--no-config", "--python", versao,
            *(["--offline"] if offline else []), "--project", str(pasta)]


def recusa_do_autocad(janela: bool, com: bool, lt: bool | None) -> str | None:
    """Pode chamar o desenho profissional? Decide pelo que o conector já sabe ver: a janela do acad.exe, o COM
    (GetActiveObject("AutoCAD.Application") do próprio conector) e, quando o COM falha, se é o LT (o `lt` do `info`
    do LISP: PROGRAM "acadlt"). None: pode. O texto: o que dizer à pessoa."""
    if not janela:
        return ("O AutoCAD não está aberto. Abra o AutoCAD com o desenho e peça de novo: o conector nunca abre o "
                "AutoCAD sozinho.")
    if com:
        return None
    if lt:
        return ("O desenho profissional (planta por especificação, paredes, portas, janelas, cotas, quadros) precisa "
                "do AutoCAD completo: o AutoCAD LT não tem a automação (COM/ActiveX) de que ele depende. No LT, o "
                "conector continua enviando a prancha, marcando o parecer e desenhando o terreno do zero "
                "(desenhar_terreno) e a planta gerada (gerar_planta), no desenho do Prancha Ok.")
    return ("O AutoCAD está aberto, mas não aceitou a automação (COM). Se ele foi aberto como administrador, feche e "
            "abra de novo sem ser administrador (o assistente e o AutoCAD precisam rodar como o mesmo usuário); se "
            "continuar, chame `diagnosticar`.")


def converter_resultado(r: types.CallToolResult) -> types.CallToolResult:
    """O resultado do filho, pronto para o assistente: texto (cortado no limite) e imagens (as grandes viram aviso);
    o structuredContent sai (é o mesmo JSON do texto e dobraria o tamanho). Marcado como enviado."""
    blocos: list = []
    usado = 0
    cortado = 0
    for c in r.content:
        if isinstance(c, types.TextContent):
            resta = MAX_TEXTO - usado
            if len(c.text) > resta:
                cortado += len(c.text) - max(resta, 0)
                if resta > 0:
                    blocos.append(types.TextContent(type="text", text=c.text[:resta]))
                    usado += resta
                continue
            blocos.append(c)
            usado += len(c.text)
        elif isinstance(c, types.ImageContent):
            if len(c.data) > MAX_IMAGEM_B64:
                blocos.append(types.TextContent(type="text", text=(
                    f"[imagem de {len(c.data) * 3 // 4 // 1024} KB omitida: passa do limite de "
                    f"{MAX_IMAGEM_B64 * 3 // 4 // 1024} KB; aproxime a vista (zoom) e capture de novo]")))
            else:
                blocos.append(c)
        else:
            blocos.append(c)
    if not any(isinstance(b, types.TextContent) for b in blocos) and r.structuredContent is not None:
        texto = json.dumps(r.structuredContent, ensure_ascii=False)
        if len(texto) > MAX_TEXTO:
            cortado += len(texto) - MAX_TEXTO
            texto = texto[:MAX_TEXTO]
        blocos.insert(0, types.TextContent(type="text", text=texto))
    if cortado:
        blocos.append(types.TextContent(type="text", text=(
            f"[resposta cortada: faltaram {cortado} caracteres. Peça menos de uma vez (limit, um andar por vez) "
            "ou use uma ferramenta de leitura mais específica.]")))
    return types.CallToolResult(content=blocos, isError=r.isError, _meta={META: {"enviada": True}})


def erro(texto: str, enviada: bool = False, interrompida: bool = False) -> types.CallToolResult:
    """Uma recusa para o assistente. `enviada`: a chamada chegou a sair para o filho; `interrompida`: ela não terminou
    (prazo estourado, filho que caiu): pode ter desenhado parte."""
    return types.CallToolResult(content=[types.TextContent(type="text", text=texto)], isError=True,
                                _meta={META: {"enviada": enviada or interrompida, "interrompida": interrompida}})


def _marca(r: types.CallToolResult) -> dict:
    return (r.meta or {}).get(META) or {}


def foi_enviada(r: types.CallToolResult) -> bool:
    """A chamada chegou ao filho? (False: recusada antes, nada pode ter sido desenhado.)"""
    return bool(_marca(r).get("enviada"))


def foi_interrompida(r: types.CallToolResult) -> bool:
    """A chamada saiu e não terminou (prazo, queda): o desenho pode ter ficado pela metade."""
    return bool(_marca(r).get("interrompida"))


def texto_de(r: types.CallToolResult) -> str:
    return "\n".join(c.text for c in r.content if isinstance(c, types.TextContent))


class _Filho:
    """Um filho vivo: a sessão e o dono dela (a task que entrou no stdio_client e é a única que pode sair)."""

    def __init__(self, pastas: tuple[str, ...]) -> None:
        self.sessao: ClientSession | None = None
        self.parar = asyncio.Event()
        self.pronto = asyncio.Event()
        self.falha: BaseException | None = None
        self.task: asyncio.Task | None = None
        self.info: dict = {}
        self.pastas = pastas


class Ponte:
    def __init__(self, config: Config) -> None:
        self.c = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._iniciar = threading.Lock()
        self._filho: _Filho | None = None
        self._fila: asyncio.Lock | None = None
        self._quedas: list[float] = []
        self._subidas = 0
        self._sync_estado = "nao_iniciado"   # nao_iniciado | instalando | pronto | falhou
        self._sync_erro: str | None = None
        self._sync_pronto = threading.Event()
        self._sync_lock = threading.Lock()
        self._ultimo_erro: str | None = None

    # ------------------------------------------------------------ caminhos e log

    @property
    def log_filho(self) -> Path:
        return self.c.pasta_log / "desenho-pro.log"

    @property
    def log_stderr(self) -> Path:
        return self.c.pasta_log / "desenho-pro.stderr.log"

    @property
    def log_sync(self) -> Path:
        return self.c.pasta_log / "desenho-pro.instalacao.log"

    def fim_do_log(self, linhas: int = 15) -> str:
        partes = []
        for caminho in (self.log_stderr, self.log_filho):
            try:
                texto = caminho.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]
            except OSError:
                continue
            if texto:
                partes.append(f"--- {caminho.name}\n" + "\n".join(texto))
        return "\n".join(partes)[-4000:]

    # ------------------------------------------------------------ ambiente (uv sync)

    def ambiente_pronto(self) -> bool:
        return self._sync_estado == "pronto"

    def preparar(self) -> str:
        """`uv sync --frozen` no ambiente de desenho_pro (bloqueia). Idempotente e barato quando já está instalado; a
        1ª vez baixa ~50 MB. Devolve o estado ("pronto" ou "falhou")."""
        with self._sync_lock:
            if self._sync_estado == "pronto":
                return self._sync_estado
            self._sync_estado = "instalando"
            self._sync_pronto.clear()
            try:
                uv = achar_uv(self.c.uv)
                if uv is None:
                    raise DesenhoIndisponivel(
                        "O uv não foi encontrado (o conector roda com ele: instale de https://docs.astral.sh/uv "
                        "e reinicie o assistente).")
                self.c.pasta_log.mkdir(parents=True, exist_ok=True)
                # Já instalado: sem rede. Se o offline falha (o lock mudou numa atualização no lugar), com a rede.
                tentativas = [True, False] if python_do_ambiente(self.c.pasta_ambiente).is_file() else [False]
                with open(self.log_sync, "w", encoding="utf-8") as log:
                    for offline in tentativas:
                        log.flush()
                        feito = subprocess.run(
                            comando_do_sync(uv, self.c.pasta_ambiente, offline),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=_ambiente_do_uv(),
                            timeout=self.c.prazo_sync_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if feito.returncode == 0:
                            break
                if feito.returncode != 0 or not python_do_ambiente(self.c.pasta_ambiente).is_file():
                    fim = self.log_sync.read_text(encoding="utf-8", errors="replace")[-1500:]
                    raise DesenhoIndisponivel(f"A instalação do desenho profissional falhou (uv sync, código "
                                              f"{feito.returncode}). Fim do log:\n{fim}")
                self._sync_estado, self._sync_erro = "pronto", None
            except subprocess.TimeoutExpired:
                self._sync_estado = "falhou"
                self._sync_erro = (f"A instalação do desenho profissional passou de {self.c.prazo_sync_s:.0f} s "
                                   "(rede lenta?). Tente de novo; o que já baixou fica guardado.")
            except DesenhoIndisponivel as e:
                self._sync_estado, self._sync_erro = "falhou", str(e)
            except Exception as e:  # noqa: BLE001 - o motivo vai para a mensagem
                self._sync_estado, self._sync_erro = "falhou", f"A instalação do desenho profissional falhou: {e}"
            finally:
                self._sync_pronto.set()
            return self._sync_estado

    def preparar_em_segundo_plano(self) -> threading.Thread:
        t = threading.Thread(target=self.preparar, name="desenho-pro-sync", daemon=True)
        t.start()
        return t

    def _esperar_ambiente(self, prazo_s: float) -> None:
        if self._sync_estado == "pronto":
            return
        if self._sync_estado in ("nao_iniciado", "falhou"):
            self._sync_pronto.clear()
            self.preparar_em_segundo_plano()  # falhou antes: tenta de novo (a rede pode ter voltado)
        if not self._sync_pronto.wait(prazo_s) or self._sync_estado == "instalando":
            raise DesenhoIndisponivel(
                "O desenho profissional ainda está sendo instalado neste computador (a primeira vez baixa ~50 MB; "
                "leva de 1 a 3 minutos). Diga isso à pessoa e tente de novo daqui a pouco.")
        if self._sync_estado != "pronto":
            raise DesenhoIndisponivel(self._sync_erro or "A instalação do desenho profissional falhou.")

    # ------------------------------------------------------------ o loop da ponte

    def _garantir_loop(self) -> asyncio.AbstractEventLoop:
        with self._iniciar:
            if self._loop is None:
                pronto = threading.Event()

                def rodar():
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)
                    self._fila = asyncio.Lock()
                    pronto.set()
                    self._loop.run_forever()

                self._thread = threading.Thread(target=rodar, name="desenho-pro", daemon=True)
                self._thread.start()
                pronto.wait()
            return self._loop

    def _submeter(self, coro) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self._garantir_loop())

    # ------------------------------------------------------------ o filho

    def _pastas_agora(self) -> tuple[str, ...]:
        if self.c.pastas is None:
            return ()
        vistas: list[str] = []
        for p in self.c.pastas():
            texto = str(Path(p).resolve())
            if texto not in vistas:
                vistas.append(texto)
        return tuple(vistas)

    def _parametros(self, pastas: tuple[str, ...]) -> StdioServerParameters:
        """O comando e o ambiente do filho: o contrato de entrada do lançador (topo do desenho_pro/lancador.py)."""
        prazo_filho = str(max(5.0, self.c.prazo_chamada_s - 10))  # o filho desiste antes de nós
        env = {
            "AUTOCAD_MCP_BACKEND": self.c.backend,
            "DISCOVERY_MODE": "search",
            "TOOL_PACKS": "core,arch",
            "PRANCHA_OK_DESENHO_PASTAS": json.dumps(list(pastas)),
            "PRANCHA_OK_DESENHO_LOG": str(self.log_filho),
            "PRANCHA_OK_DESENHO_BLOQUEADAS": json.dumps(list(self.c.bloqueadas)),
            "COM_CALL_TIMEOUT": prazo_filho,
            "EZDXF_CALL_TIMEOUT": prazo_filho,
        }
        if self.c.base is not None:
            env["PRANCHA_OK_DESENHO_BASE"] = str(self.c.base)
        env.update({k: v for k, v in os.environ.items() if k in _PASSAM})
        env.update(self.c.extra_env)
        return StdioServerParameters(command=str(python_do_ambiente(self.c.pasta_ambiente)),
                                     args=["-I", "-X", "utf8", str(self.c.lancador)], env=env,
                                     cwd=str(self.c.pasta_log))

    async def _dono(self, filho: _Filho) -> None:
        try:
            self.c.pasta_log.mkdir(parents=True, exist_ok=True)
            for p in filho.pastas:
                Path(p).mkdir(parents=True, exist_ok=True)
            with open(self.log_stderr, "w", encoding="utf-8", errors="replace") as errlog:
                async with stdio_client(self._parametros(filho.pastas), errlog=errlog) as (leitura, escrita):
                    async with ClientSession(leitura, escrita) as sessao:
                        inicio = await sessao.initialize()
                        filho.info = {"servidor": inicio.serverInfo.name, "versao": inicio.serverInfo.version}
                        filho.sessao = sessao
                        filho.pronto.set()
                        await filho.parar.wait()
        except BaseException as e:  # noqa: BLE001 - o motivo vai para quem esperava a subida
            filho.falha = e
        finally:
            filho.sessao = None
            filho.pronto.set()

    async def _subir(self, pastas: tuple[str, ...]) -> _Filho:
        filho = _Filho(pastas)
        filho.task = asyncio.get_running_loop().create_task(self._dono(filho))
        try:
            await asyncio.wait_for(filho.pronto.wait(), self.c.prazo_subida_s)
        except asyncio.CancelledError:
            # Cancelado no meio da subida (o cliente cancelou a ferramenta): o filho que subia não fica órfão.
            await self._derrubar(filho)
            raise
        except asyncio.TimeoutError:
            await self._derrubar(filho)
            raise DesenhoIndisponivel(f"O desenho profissional não respondeu em {self.c.prazo_subida_s:.0f} s ao "
                                      f"subir.\n{self.fim_do_log()}") from None
        if filho.sessao is None:
            await self._derrubar(filho)
            self._anotar_queda(f"não subiu ({filho.falha!r})")
            raise DesenhoIndisponivel(f"O desenho profissional não subiu ({filho.falha!r}).\n{self.fim_do_log()}")
        self._subidas += 1
        return filho

    async def _derrubar(self, filho: _Filho | None) -> None:
        if filho is None:
            return
        filho.parar.set()
        if filho.task is not None:
            if filho.sessao is None:  # ainda subindo: o dono não espera o `parar`, só sai cancelado
                filho.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(filho.task), 5)
            except (asyncio.TimeoutError, Exception):
                filho.task.cancel()
        if self._filho is filho:
            self._filho = None

    def _anotar_queda(self, motivo: str) -> None:
        agora = time.monotonic()
        self._quedas = [t for t in self._quedas if agora - t < self.c.janela_quedas_s] + [agora]
        self._ultimo_erro = motivo

    def _quedas_recentes(self) -> int:
        agora = time.monotonic()
        return len([t for t in self._quedas if agora - t < self.c.janela_quedas_s])

    def desligado(self) -> bool:
        """Caiu `max_quedas` vezes na janela: fica desligado até o conector reiniciar (ou a janela passar)."""
        return self._quedas_recentes() >= self.c.max_quedas

    def _msg_desligado(self) -> str:
        return (f"O desenho profissional caiu {self.c.max_quedas} vezes em {self.c.janela_quedas_s / 60:.0f} min e "
                f"foi desligado até o assistente reiniciar. Último erro: {self._ultimo_erro}\n{self.fim_do_log()}")

    async def _filho_vivo(self, pastas: tuple[str, ...]) -> _Filho:
        """O filho de pé, com as pastas certas e respondendo (ping); morto, sobe outro. É aqui que a chamada seguinte
        fica segura: ela ainda não saiu."""
        if self.desligado():
            raise DesenhoIndisponivel(self._msg_desligado())
        f = self._filho
        if f is not None and f.sessao is not None and not f.task.done():
            if f.pastas != pastas:  # outro desenho aberto: o lançador lê as pastas só na subida
                await self._derrubar(f)
            else:
                try:
                    await asyncio.wait_for(f.sessao.send_ping(), 5)
                    return f
                except Exception as e:  # noqa: BLE001
                    self._anotar_queda(f"sem resposta ao ping ({e!r})")
                    await self._derrubar(f)
        elif f is not None:
            self._anotar_queda(f"o processo terminou ({f.falha!r})")
            await self._derrubar(f)
        if self.desligado():
            raise DesenhoIndisponivel(self._msg_desligado())
        self._filho = await self._subir(pastas)
        return self._filho

    async def _pegar_canal(self, ate: float) -> bool:
        """O canal com o AutoCAD, sem travar o loop (tentativas curtas: um acquire numa thread que fosse cancelado
        no prazo podia pegar o lock depois e nunca soltar)."""
        while not self.c.canal.acquire(blocking=False):
            if time.monotonic() >= ate:
                return False
            await asyncio.sleep(0.05)
        return True

    async def _chamar(self, nome: str, argumentos: dict, prazo_s: float, pastas: tuple[str, ...],
                      progresso=None) -> types.CallToolResult:
        limite = time.monotonic() + prazo_s
        async with self._fila:  # uma chamada por vez: o AutoCAD faz uma coisa por vez, e o prazo é de cada uma
            filho = await self._filho_vivo(pastas)
            if self.c.canal is not None and not await self._pegar_canal(limite):
                return erro(f"'{nome}' esperou {prazo_s:.0f} s o AutoCAD terminar outro pedido do conector e não "
                            "começou. Tente de novo.")
            try:
                resta = limite - time.monotonic()
                if resta <= 0:
                    return erro(f"'{nome}' esperou {prazo_s:.0f} s na fila e não começou.")
                return await self._mandar(filho, nome, argumentos, prazo_s, resta, progresso)
            finally:
                if self.c.canal is not None:
                    self.c.canal.release()

    async def _mandar(self, filho: _Filho, nome: str, argumentos: dict, prazo_s: float, resta: float,
                      progresso) -> types.CallToolResult:
        sessao = filho.sessao
        pedido = sessao._request_id  # o id que esta chamada vai usar (para o cancelled); SDK mcp 1.x (fixado < 2)
        try:
            r = await asyncio.wait_for(sessao.call_tool(nome, argumentos, progress_callback=progresso), resta)
            return converter_resultado(r)
        except asyncio.CancelledError:
            # O cliente cancelou a ferramenta (Esc no assistente): o filho seguiria no COM. Ele é avisado e derrubado
            # ANTES de o `_chamar` soltar o canal, para o próximo pedido do LISP não cair num AutoCAD ocupado.
            await self._interromper(filho, pedido, "cancelada pelo cliente")
            raise
        except asyncio.TimeoutError:
            self._anotar_queda(f"'{nome}' passou de {prazo_s:.0f} s")
            await self._interromper(filho, pedido, "prazo do conector")
            return erro(
                f"'{nome}' passou de {prazo_s:.0f} s e foi interrompida. O desenho pode ter ficado pela metade: "
                "confira no AutoCAD (Ctrl+Z desfaz o último passo). Para um desenho grande, mande em partes "
                "(um pavimento por vez).", interrompida=True)
        except McpError as e:
            if e.error.code == types.CONNECTION_CLOSED or filho.task.done():
                self._anotar_queda(f"caiu durante '{nome}': {e.error.message}")
                await self._derrubar(filho)
                return erro(
                    f"O desenho profissional caiu durante '{nome}' (ele sobe de novo na próxima chamada; esta "
                    "não foi repetida, porque pode ter desenhado parte). Confira o desenho no AutoCAD.\n"
                    + self.fim_do_log(), interrompida=True)
            return erro(f"'{nome}': {e.error.message}", enviada=True)

    async def _interromper(self, filho: _Filho, pedido, motivo: str) -> None:
        """Uma chamada que não vai terminar: avisa o filho (notifications/cancelled, para ele desfazer a transação),
        dá a folga e o derruba (a próxima chamada sobe outro)."""
        try:
            await filho.sessao.send_notification(types.ClientNotification(types.CancelledNotification(
                params=types.CancelledNotificationParams(requestId=pedido, reason=motivo))))
            await asyncio.sleep(self.c.folga_cancelar_s)
        except Exception:  # noqa: BLE001 - o filho pode já ter caído
            pass
        await self._derrubar(filho)

    # ------------------------------------------------------------ API para o servidor

    def _antes(self, nome: str, argumentos) -> tuple[dict, types.CallToolResult | None]:
        if isinstance(argumentos, str):  # o Claude Desktop às vezes manda o objeto como texto
            try:
                argumentos = json.loads(argumentos) if argumentos.strip() else {}
            except ValueError:
                return {}, erro("`argumentos` deve ser um objeto JSON com os argumentos da ferramenta.")
        argumentos = {} if argumentos is None else argumentos
        if not isinstance(argumentos, dict):
            return {}, erro("`argumentos` deve ser um objeto JSON com os argumentos da ferramenta.")
        if not isinstance(nome, str) or not nome.strip():
            return argumentos, erro("Diga o nome da ferramenta (`buscar_ferramentas_de_desenho` mostra os nomes).")
        if len(json.dumps(argumentos, default=str)) > MAX_ARGUMENTOS:
            return argumentos, erro(f"Argumentos grandes demais (mais de {MAX_ARGUMENTOS} caracteres): mande em "
                                    "partes.")
        if nome in self.c.bloqueadas:
            return argumentos, erro(f"'{nome}' não está disponível no conector do Prancha Ok.")
        if self.desligado():
            return argumentos, erro(self._msg_desligado())
        return argumentos, None

    def _verificar(self) -> types.CallToolResult | None:
        if self.c.verificar_autocad is None:
            return None
        try:
            recusa = self.c.verificar_autocad()
        except Exception as e:  # noqa: BLE001
            recusa = f"Não deu para conferir o AutoCAD: {e}"
        return erro(recusa) if recusa else None

    async def chamar_async(self, nome: str, argumentos=None, prazo_s: float | None = None,
                           progresso=None, verificar: bool = True) -> types.CallToolResult:
        """Para as ferramentas async do servidor: espera a ponte sem travar o loop dele."""
        argumentos, recusa = self._antes(nome, argumentos)
        if recusa:
            return recusa
        if verificar and (recusa := await asyncio.to_thread(self._verificar)):
            return recusa
        prazo = prazo_s or self.c.prazo_chamada_s
        try:
            await asyncio.to_thread(self._esperar_ambiente, prazo)
            pastas = await asyncio.to_thread(self._pastas_agora)
        except DesenhoIndisponivel as e:
            return erro(str(e))
        futuro = self._submeter(self._chamar_protegido(nome, argumentos, prazo, pastas, progresso))
        try:
            return await asyncio.wrap_future(futuro)
        except asyncio.CancelledError:
            futuro.cancel()  # o cliente cancelou a nossa ferramenta: cancela a da ponte também
            raise

    def chamar(self, nome: str, argumentos=None, prazo_s: float | None = None,
               verificar: bool = True) -> types.CallToolResult:
        """Para as ferramentas síncronas do servidor (bloqueia a thread que chama)."""
        argumentos, recusa = self._antes(nome, argumentos)
        if recusa:
            return recusa
        if verificar and (recusa := self._verificar()):
            return recusa
        prazo = prazo_s or self.c.prazo_chamada_s
        try:
            self._esperar_ambiente(prazo)
            pastas = self._pastas_agora()
        except DesenhoIndisponivel as e:
            return erro(str(e))
        futuro = self._submeter(self._chamar_protegido(nome, argumentos, prazo, pastas, None))
        try:
            return futuro.result(prazo + self.c.folga_cancelar_s + self.c.prazo_subida_s + 10)
        except concurrent.futures.TimeoutError:
            futuro.cancel()
            return erro(f"'{nome}' não voltou a tempo.", interrompida=True)

    async def _chamar_protegido(self, nome, argumentos, prazo, pastas, progresso) -> types.CallToolResult:
        try:
            return await self._chamar(nome, argumentos, prazo, pastas, progresso)
        except DesenhoIndisponivel as e:
            return erro(str(e))
        except Exception as e:  # noqa: BLE001 - nunca derruba o conector
            self._anotar_queda(repr(e))
            await self._derrubar(self._filho)
            return erro(f"Erro ao falar com o desenho profissional: {e!r}", interrompida=True)

    def situacao(self) -> dict:
        f = self._filho
        return {
            "ambiente": self._sync_estado,
            "erroAmbiente": self._sync_erro,
            "processo": "de_pe" if f is not None and f.sessao is not None else "parado",
            "servidor": f.info if f else None,
            "pastas": list(f.pastas) if f else None,
            "subidas": self._subidas,
            "quedasRecentes": self._quedas_recentes(),
            "desligado": self.desligado(),
            "ultimoErro": self._ultimo_erro,
            "log": str(self.log_filho),
        }

    def encerrar(self) -> None:
        if self._loop is None:
            return
        try:
            self._submeter(self._derrubar(self._filho)).result(10)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------- a ponte do conector

def backend_do_filho() -> str | None:
    """O backend do filho: PRANCHA_OK_DESENHO_BACKEND (ezdxf nos testes), senão "com" no Windows; fora do Windows,
    sem a variável, None (o desenho profissional precisa do AutoCAD)."""
    forcado = (os.environ.get("PRANCHA_OK_DESENHO_BACKEND") or "").strip().lower()
    if forcado in ("com", "ezdxf"):
        return forcado
    return "com" if sys.platform == "win32" else None


def motivo_indisponivel() -> str | None:
    """Por que o desenho profissional não serve neste computador, antes de olhar o AutoCAD (None: pode tentar)."""
    if (os.environ.get("PRANCHA_OK_DESENHO_PRO") or "").strip() == "0":
        return MSG_DESLIGADO
    if backend_do_filho() is None:
        return MSG_SO_WINDOWS
    return None


def _verificar_autocad_padrao() -> str | None:
    from . import autocad

    if autocad._janela_autocad() is None:
        return recusa_do_autocad(False, False, None)
    if autocad.com_do_autocad() is not None:
        return None
    try:
        lt = bool(autocad.info().get("lt"))
    except Exception:  # noqa: BLE001 - sem o LISP, a mensagem genérica do COM
        lt = None
    return recusa_do_autocad(True, False, lt)


def _pastas_padrao() -> list[Path]:
    """A pasta do desenho aberto (pelo COM; desenho nunca salvo não tem) e a de saída."""
    from . import autocad

    pastas = []
    if (com := autocad.com_do_autocad()) and com.get("pasta"):
        pastas.append(Path(com["pasta"]))
    return [*pastas, pasta_de_saida()]


def config_padrao() -> Config:
    """A configuração do conector: o desenho_pro ao lado de src/, os logs e a base em %USERPROFILE%\\.prancha-ok, o
    backend do `backend_do_filho` e, no COM, a conferência do AutoCAD, as pastas do desenho aberto e o canal."""
    from . import autocad

    backend = backend_do_filho() or "com"
    casa = _casa() / ".prancha-ok"
    com = backend == "com"
    return Config(
        pasta_ambiente=PASTA_AMBIENTE, lancador=PASTA_AMBIENTE / "lancador.py", pasta_log=casa / "logs",
        base=casa / "desenho-pro", backend=backend,
        verificar_autocad=_verificar_autocad_padrao if com else None,
        pastas=_pastas_padrao if com else lambda: [pasta_de_saida()],
        canal=autocad.canal_autocad if com else None)


_PONTE: Ponte | None = None
_PONTE_LOCK = threading.Lock()


def obter() -> Ponte:
    """A ponte do conector (uma por processo), criada na 1ª vez."""
    global _PONTE
    with _PONTE_LOCK:
        if _PONTE is None:
            _PONTE = Ponte(config_padrao())
        return _PONTE


def encerrar() -> None:
    """Derruba o filho, se a ponte chegou a existir (o `rodar` do servidor chama no fim)."""
    if _PONTE is not None:
        _PONTE.encerrar()
