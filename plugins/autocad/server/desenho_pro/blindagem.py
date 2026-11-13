"""A blindagem do autocad-mcp-pro 1.6.0 dentro do conector (auditoria de segurança de 25/10/2026, seguranca.md §3 a §5),
MENOS a retirada do comando livre: decisão do David D22=c, `system_run_command` e `system_run_lisp` ficam como vêm,
com a lista de proteção dele ligada (DANGEROUS_COMMANDS_ENABLED forçado a false).

Quatro partes, nesta ordem (a ordem importa: o fastmcp lê o ambiente e o ./.env AO SER IMPORTADO, e o ezdxf lê o
./ezdxf.ini do cwd):

1. `ler_entrada(os.environ)`: o que o conector mandou (variáveis PRANCHA_OK_DESENHO_* e AUTOCAD_MCP_BACKEND), antes
   de limpar o ambiente;
2. `fixar_ambiente(entrada)`: apaga do ambiente herdado tudo com FASTMCP_, EZDXF_, MCP_, UV_, PYTHON e as variáveis
   do pro, fixa a tabela da seguranca.md §3 e troca o cwd por uma pasta nossa, vazia;
3. `aplicar_caminhos(entrada)`: troca o `security.validate_path` (raízes = as pastas que o conector mandou: a do
   desenho aberto e a de saída nossa; extensões permitidas; qualquer pasta `.prancha-ok` sempre recusada, porque ali
   ficam o LISP confiável do TRUSTEDPATHS e a troca com o AutoCAD), em todo módulo que já o importou por valor;
4. `aplicar_no_servidor(server, entrada)`: tira do registro o `system_launch` e o `system_set_variable` (D24=a; e o
   que vier em PRANCHA_OK_DESENHO_BLOQUEADAS); handle só hexadecimal no trim/fillet/chamfer/extend (o COM interpola o handle num
   `(handent "...")` dentro de um SendCommand); COM só se liga a um AutoCAD já aberto (nunca `Dispatch`, que abre
   um AutoCAD novo).

Este módulo só importa a biblioteca padrão no topo: o que é do pro (fastmcp, config, security, backends) entra
dentro das funções, depois de o ambiente estar fixo.
"""
from __future__ import annotations

import functools
import inspect
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

VERSAO_CONFERIDA = "1.6.0"
BACKENDS = ("com", "ezdxf")
PASTA_DO_CONECTOR = ".prancha-ok"

#: Extensões que o pro pode gravar (desenho, modelo, PDF, imagem de conferência, planilha de extração).
EXT_ESCRITA = frozenset({".dwg", ".dxf", ".dwt", ".pdf", ".png", ".csv", ".xlsx"})
#: E ler (mais tipo de linha e imagens do image_attach). Nada de .lsp, .fas, .vlx, .scr, .bat, .ps1, .exe...
EXT_LEITURA = EXT_ESCRITA | {".lin", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

#: Métodos do backend que levam handle para dentro de um SendCommand no COM (com_backend.py da 1.6.0).
HANDLES_NO_COMANDO = {
    "entity_trim": ("target_handle", "cutter_handle"),
    "entity_extend": ("target_handle", "boundary_handle"),
    "entity_fillet": ("handle1", "handle2"),
    "entity_chamfer": ("handle1", "handle2"),
}
HANDLE = re.compile(r"[0-9A-Fa-f]{1,16}")

#: Sempre fora do registro, mesmo que um dia o TOOL_PACKS os traga: o system_launch liga ou ABRE o AutoCAD; o
#: system_set_variable muda variável do AutoCAD, inclusive as de segurança e de arquivo (SECURELOAD, TRUSTEDPATHS,
#: ACADLSPASDOC...; auditoria A7), e o Claude não muda variável nenhuma pelo pro (decisão do David D24=a).
SEMPRE_TIRADAS = ("system_launch", "system_set_variable")

_PREFIXOS_LIMPOS = ("FASTMCP_", "EZDXF_", "MCP_", "UV_", "PYTHON")
_DO_PRO = frozenset({
    "AUTOCAD_MCP_BACKEND", "CAD_PROGID", "ALLOWED_PATHS", "DANGEROUS_COMMANDS_ENABLED", "ENABLE_3D",
    "ALLOW_REMOTE_HTTP", "MCP_AUTH_TOKEN", "TOOL_PROFILE", "TOOL_PACKS", "DISCOVERY_MODE", "LOG_LEVEL",
    "MAX_UNDO_STACK", "MAX_DXF_BYTES", "MAX_LIST_LIMIT", "COM_CALL_TIMEOUT", "EZDXF_CALL_TIMEOUT",
    "EZDXF_UNDO_DEPTH",
})

MSG_AUTOCAD_FECHADO = (
    "AutoCAD is not open (or not reachable through COM). The Prancha Ok connector never starts AutoCAD by itself: "
    "ask the user to open AutoCAD with the drawing, then try again.")


class EntradaInvalida(ValueError):
    """O conector mandou uma variável de ambiente que não dá para usar: o lançador não sobe."""


@dataclass
class Entrada:
    backend: str
    base: Path
    pastas: list[Path]
    ignoradas: list[str] = field(default_factory=list)
    bloqueadas: list[str] = field(default_factory=list)
    log: Path | None = None
    prazo_com_s: float = 60.0
    prazo_ezdxf_s: float = 120.0

    @property
    def trabalho(self) -> Path:
        return self.base / "trabalho"


def _casa(ambiente) -> Path:
    return Path(ambiente.get("USERPROFILE") or ambiente.get("HOME") or Path.home())


def na_pasta_do_conector(caminho: Path) -> bool:
    """Qualquer parte do caminho chamada `.prancha-ok` (sem caixa): o LISP confiável, a troca com o AutoCAD, os logs."""
    return any(parte.casefold() == PASTA_DO_CONECTOR for parte in caminho.parts)


def _lista_json(ambiente, nome: str) -> list[str]:
    bruto = (ambiente.get(nome) or "").strip()
    if not bruto:
        return []
    try:
        valor = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise EntradaInvalida(f"{nome} não é JSON: {exc}") from exc
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise EntradaInvalida(f"{nome} tem que ser uma lista de textos em JSON")
    return valor


def _prazo(ambiente, nome: str, padrao: float) -> float:
    bruto = (ambiente.get(nome) or "").strip()
    if not bruto:
        return padrao
    try:
        valor = float(bruto)
    except ValueError as exc:
        raise EntradaInvalida(f"{nome} não é número: {bruto!r}") from exc
    return min(max(valor, 5.0), 600.0)


def ler_entrada(ambiente) -> Entrada:
    """O contrato de entrada (ver o topo do lancador.py). Não muda nada."""
    bruto = (ambiente.get("AUTOCAD_MCP_BACKEND") or "").strip().lower()
    backend = bruto or ("com" if sys.platform == "win32" else "ezdxf")
    if backend not in BACKENDS:
        # "auto" cairia calado no ezdxf sem AutoCAD: desenharia num documento em memória que a pessoa nunca vê.
        raise EntradaInvalida(f"AUTOCAD_MCP_BACKEND={bruto!r}: só {' ou '.join(BACKENDS)}")
    base_bruta = (ambiente.get("PRANCHA_OK_DESENHO_BASE") or "").strip()
    base = Path(base_bruta) if base_bruta else _casa(ambiente) / PASTA_DO_CONECTOR / "desenho-pro"
    if not base.is_absolute():
        raise EntradaInvalida(f"PRANCHA_OK_DESENHO_BASE tem que ser absoluto: {base_bruta!r}")
    pastas, ignoradas = [], []
    for texto in _lista_json(ambiente, "PRANCHA_OK_DESENHO_PASTAS"):
        p = Path(texto)
        if not texto.strip() or not p.is_absolute():
            ignoradas.append(f"{texto!r}: não é um caminho absoluto")
            continue
        p = p.resolve()
        if na_pasta_do_conector(p):
            ignoradas.append(f"{texto!r}: dentro de {PASTA_DO_CONECTOR}, que é do conector")
            continue
        if p not in pastas:
            pastas.append(p)
    log = (ambiente.get("PRANCHA_OK_DESENHO_LOG") or "").strip()
    return Entrada(
        backend=backend,
        base=base.resolve(),
        pastas=pastas,
        ignoradas=ignoradas,
        bloqueadas=_lista_json(ambiente, "PRANCHA_OK_DESENHO_BLOQUEADAS"),
        log=Path(log) if log else None,
        prazo_com_s=_prazo(ambiente, "COM_CALL_TIMEOUT", 60.0),
        prazo_ezdxf_s=_prazo(ambiente, "EZDXF_CALL_TIMEOUT", 120.0),
    )


def ambiente_fixo(entrada: Entrada) -> dict[str, str]:
    """A tabela da seguranca.md §3: o que o pro e o fastmcp veem, sempre igual."""
    return {
        # autocad-mcp-pro
        "AUTOCAD_MCP_BACKEND": entrada.backend,   # "com" no Windows: sem cair calado no ezdxf
        "CAD_PROGID": "AutoCAD.Application",
        "DISCOVERY_MODE": "search",
        "TOOL_PACKS": "core,arch",
        "TOOL_PROFILE": "full",
        "DANGEROUS_COMMANDS_ENABLED": "false",
        "ENABLE_3D": "false",
        "ALLOW_REMOTE_HTTP": "false",
        # Nunca vazio (vazio = qualquer pasta): as raízes de verdade entram em aplicar_caminhos, como lista (o
        # ALLOWED_PATHS dele se divide na vírgula, e uma pasta pode ter vírgula no nome).
        "ALLOWED_PATHS": str(entrada.base / "nenhuma-pasta"),
        "MAX_DXF_BYTES": str(200 * 1024 * 1024),
        "MAX_LIST_LIMIT": "5000",
        "MAX_UNDO_STACK": "5",
        "COM_CALL_TIMEOUT": f"{entrada.prazo_com_s:g}",
        "EZDXF_CALL_TIMEOUT": f"{entrada.prazo_ezdxf_s:g}",
        "EZDXF_UNDO_DEPTH": "0",                  # sem cópias do desenho no %TEMP%
        "LOG_LEVEL": "WARNING",
        # fastmcp
        "FASTMCP_CHECK_FOR_UPDATES": "off",       # sem consulta ao PyPI a cada início
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        "FASTMCP_TRANSPORT": "stdio",
        "FASTMCP_ENV_FILE": str(entrada.trabalho / "nao-existe.env"),
        "FASTMCP_HOME": str(entrada.base / "fastmcp"),
        "FASTMCP_LOG_LEVEL": "WARNING",
        "FASTMCP_ENABLE_RICH_LOGGING": "false",
        "FASTMCP_DEPRECATION_WARNINGS": "false",
    }


def _esvaziar(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for item in pasta.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def fixar_ambiente(entrada: Entrada) -> None:
    for chave in list(os.environ):
        if chave.upper().startswith(_PREFIXOS_LIMPOS) or chave.upper() in _DO_PRO:
            del os.environ[chave]
    os.environ.update(ambiente_fixo(entrada))
    (entrada.base / "fastmcp").mkdir(parents=True, exist_ok=True)
    _esvaziar(entrada.trabalho)   # o fastmcp lia ./.env e o ezdxf lê ./ezdxf.ini do cwd
    os.chdir(entrada.trabalho)


# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

def _dentro(caminho: Path, raiz: Path) -> bool:
    try:
        return caminho.is_relative_to(raiz)
    except (ValueError, TypeError):
        return False


def validador(original, raizes: list[Path]):
    """O validate_path nosso: o dele primeiro (`..`, UNC, pastas do sistema), depois as nossas regras."""
    from fastmcp.exceptions import ToolError

    def _nossas_regras(resolvido: Path, allow_write: bool) -> None:
        if na_pasta_do_conector(resolvido):
            raise ToolError(f"Path rejected: '{resolvido}' is inside the Prancha Ok connector folder "
                            f"({PASTA_DO_CONECTOR}).")
        if not any(_dentro(resolvido, r) for r in raizes):
            permitidas = ", ".join(str(r) for r in raizes) or "(none)"
            raise ToolError(f"Path rejected: '{resolvido}' is outside the folders the Prancha Ok connector allows: "
                            f"{permitidas}. Save next to the open drawing or in the connector's output folder.")
        sufixo = resolvido.suffix.lower()
        # Pasta (output_dir do batch_plot/deliver) não tem extensão; cada arquivo dentro passa por aqui de novo.
        if sufixo and not resolvido.is_dir():
            aceitas = EXT_ESCRITA if allow_write else EXT_LEITURA
            if sufixo not in aceitas:
                raise ToolError(f"Path rejected: extension '{sufixo}' is not allowed by the Prancha Ok connector "
                                f"(allowed: {', '.join(sorted(aceitas))}).")

    def validate_path(path: str, *, allow_write: bool = False) -> Path:
        if path and str(path).strip():
            bruto = Path(str(path))
            if na_pasta_do_conector(bruto):
                raise ToolError(f"Path rejected: '{path}' is inside the Prancha Ok connector folder "
                                f"({PASTA_DO_CONECTOR}).")
            _nossas_regras(bruto.resolve(), allow_write)   # antes do dele: a frase é a nossa
        resolvido = original(path, allow_write=allow_write)  # o dele: `..`, UNC, pastas do sistema, pasta-mãe
        _nossas_regras(resolvido, allow_write)
        return resolvido

    validate_path.__doc__ = original.__doc__
    validate_path.prancha_ok = True
    validate_path.original = original
    return validate_path


def _trocar_em_todo_modulo(nome: str, antigo, novo) -> list[str]:
    """Quem fez `from security import validate_path` guardou o objeto antigo: troca em cada módulo carregado."""
    trocados = []
    for nome_modulo, modulo in list(sys.modules.items()):
        if modulo is not None and getattr(modulo, nome, None) is antigo:
            setattr(modulo, nome, novo)
            trocados.append(nome_modulo)
    return trocados


def conferir_caminhos() -> None:
    import config
    import security

    if not getattr(security.validate_path, "prancha_ok", False):
        parametros = inspect.signature(security.validate_path).parameters
        if list(parametros) != ["path", "allow_write"] or parametros["allow_write"].kind != inspect.Parameter.KEYWORD_ONLY:
            raise RuntimeError("security.validate_path mudou de assinatura: confira a blindagem dos caminhos")
    for atributo in ("allowed_paths", "dangerous_commands_enabled"):
        if not hasattr(config.settings, atributo):
            raise RuntimeError(f"config.settings.{atributo} sumiu: confira a blindagem")


def aplicar_caminhos(entrada: Entrada) -> None:
    import config
    import security

    conferir_caminhos()
    config.settings.allowed_paths = list(entrada.pastas) or [entrada.base / "nenhuma-pasta"]
    config.settings.dangerous_commands_enabled = False
    if getattr(security.validate_path, "prancha_ok", False):
        return
    original = security.validate_path
    _trocar_em_todo_modulo("validate_path", original, validador(original, list(entrada.pastas)))


def caminhos_sem_troca() -> list[str]:
    """Módulos carregados que ainda guardam um validate_path que não é o nosso (tem que ser [])."""
    return [n for n, m in list(sys.modules.items())
            if m is not None and callable(getattr(m, "validate_path", None))
            and n.split(".")[0] in ("server", "security", "backends", "engineering")
            and not getattr(m.validate_path, "prancha_ok", False)]


# ---------------------------------------------------------------------------
# Servidor: ferramentas, handles, COM
# ---------------------------------------------------------------------------

def _classes_do_backend():
    from backends import com_backend, ezdxf_backend

    return ezdxf_backend.EzdxfBackend, com_backend.ComBackend


def conferir_servidor(server) -> None:
    if not hasattr(getattr(server, "mcp", None), "local_provider"):
        raise RuntimeError("server.mcp.local_provider sumiu: confira a blindagem das ferramentas")
    for classe in _classes_do_backend():
        for metodo, params in HANDLES_NO_COMANDO.items():
            funcao = getattr(classe, metodo, None)
            if funcao is None or not inspect.iscoroutinefunction(funcao):
                raise RuntimeError(f"{classe.__name__}.{metodo} sumiu: confira a blindagem dos handles")
            if not set(params) <= set(inspect.signature(funcao).parameters):
                raise RuntimeError(f"{classe.__name__}.{metodo} mudou de parâmetros: confira a blindagem dos handles")
    from backends import com_backend

    for nome in ("_acad_app", "_COM_STATE"):
        if not hasattr(com_backend, nome):
            raise RuntimeError(f"com_backend.{nome} sumiu: confira a blindagem do COM")


def _so_handle_hexadecimal(funcao, metodo: str, params: tuple[str, ...]):
    assinatura = inspect.signature(funcao)

    @functools.wraps(funcao)
    async def guardado(self, *args, **kwargs):
        from fastmcp.exceptions import ToolError

        argumentos = assinatura.bind(self, *args, **kwargs).arguments
        for p in params:
            valor = argumentos.get(p)
            if not isinstance(valor, str) or not HANDLE.fullmatch(valor):
                raise ToolError(f"{metodo}: handle inválido em {p!r} ({str(valor)[:40]!r}); um handle do AutoCAD é "
                                "hexadecimal, como '2F3'.")
        return await funcao(self, *args, **kwargs)

    guardado.prancha_ok = True
    return guardado


def _sem_abrir_autocad() -> None:
    """O `_acad_app` original cai no `Dispatch`, que ABRE o AutoCAD fechado (e o completo, até para quem usa o LT)."""
    from backends import com_backend as cb

    def _acad_app():
        if "app" not in cb._COM_STATE:
            import win32com.client

            try:
                cb._COM_STATE["app"] = win32com.client.GetActiveObject(cb.config.settings.cad_progid)
            except Exception as exc:
                raise RuntimeError(MSG_AUTOCAD_FECHADO) from exc
        return cb._COM_STATE["app"]

    _acad_app.prancha_ok = True
    cb._acad_app = _acad_app

    async def system_launch(self, visible: bool = True, open_path: str | None = None) -> dict:
        from fastmcp.exceptions import ToolError

        raise ToolError("system_launch is disabled by the Prancha Ok connector: it never starts AutoCAD.")

    system_launch.prancha_ok = True
    cb.ComBackend.system_launch = system_launch


def aplicar_no_servidor(server, entrada: Entrada) -> list[str]:
    """Devolve as ferramentas tiradas do registro."""
    conferir_servidor(server)
    tiradas = []
    for nome in (*SEMPRE_TIRADAS, *entrada.bloqueadas):
        try:
            server.mcp.local_provider.remove_tool(nome)
            tiradas.append(nome)
        except KeyError:  # não existe nesta versão (ou já saiu): nada a tirar
            pass
    for classe in _classes_do_backend():
        for metodo, params in HANDLES_NO_COMANDO.items():
            funcao = getattr(classe, metodo)
            if not getattr(funcao, "prancha_ok", False):
                setattr(classe, metodo, _so_handle_hexadecimal(funcao, metodo, params))
    _sem_abrir_autocad()
    import security

    # Quem importou o validate_path por valor depois da troca já pegou o nosso; a varredura de novo é por garantia.
    _trocar_em_todo_modulo("validate_path", security.validate_path.original, security.validate_path)
    return tiradas
