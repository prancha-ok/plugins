"""Onde o MCP guarda as coisas na máquina e com qual backend fala."""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# Backend de produção (Convex, HTTP actions). PRANCHA_OK_API troca: no teste
# local com a VM, http://172.22.0.1:3211 (o host visto de dentro do Windows).
API_PADRAO = "https://optimistic-fennec-411.convex.site"


def api() -> str:
    return (os.environ.get("PRANCHA_OK_API") or API_PADRAO).rstrip("/")


def pasta() -> Path:
    """%USERPROFILE%\\.prancha-ok: a troca com o AutoCAD e o LISP.

    Fora de AppData de propósito: no Claude Desktop do Windows (app MSIX), o
    MCP roda dentro do contêiner do pacote, e pasta nova criada em
    %LOCALAPPDATA%/%APPDATA% vai parar em ...\\Packages\\<pacote>\\LocalCache,
    invisível para o AutoCAD (teste na VM, 29/09/2026). Fora de AppData o MSIX
    não desvia nada. O LISP recebe o caminho pelo próprio comando (autocad.py)."""
    caminho = Path(os.environ.get("USERPROFILE") or Path.home()) / ".prancha-ok"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def empacotado() -> bool:
    """Rodando dentro de um app MSIX (ex.: Claude Desktop no Windows)? Aí o registro
    (HKCU\\Software) é virtualizado: o TRUSTEDPATHS gravado não chega ao AutoCAD."""
    if os.name != "nt":
        return False
    import ctypes

    tamanho = ctypes.c_uint32(0)
    APPMODEL_ERROR_NO_PACKAGE = 15700
    return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(tamanho), None) != APPMODEL_ERROR_NO_PACKAGE


def pasta_ipc() -> Path:
    """Troca de pedidos com o AutoCAD. Tem que bater com `pok-dir` do prancha_ok.lsp."""
    caminho = pasta() / "ipc"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def pasta_lisp() -> Path:
    """Pasta confiável (TRUSTEDPATHS) de onde o AutoCAD carrega o prancha_ok.lsp."""
    caminho = pasta() / "lisp"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


LISP = "prancha_ok.lsp"


def atualizar_lisp() -> bool:
    """Copia o LISP desta versão do MCP para a pasta confiável quando ele falta ou é
    outro (versão nova do MCP). Devolve se copiou. A cópia vai para um .tmp e troca o
    arquivo de uma vez: o AutoCAD nunca lê um LISP pela metade."""
    origem = Path(__file__).with_name(LISP)
    destino = pasta_lisp() / LISP
    novo = origem.read_bytes()
    if destino.exists() and destino.read_bytes() == novo:
        return False
    temporario = destino.with_suffix(".tmp")
    shutil.copyfile(origem, temporario)
    os.replace(temporario, destino)
    return True


def lisp_instalado() -> Path:
    """O LISP desta versão do MCP na pasta confiável (copiado se preciso)."""
    atualizar_lisp()
    return pasta_lisp() / LISP


def nome_maquina() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname() or "Computador"


_ESTADO = "estado.json"
# Leitura presa (no Windows, o arquivo que outro conector está trocando dá PermissionError): tenta de novo, com pausa.
TENTATIVAS_ESTADO = 5
PAUSA_ESTADO_S = 0.05


# O que é de um backend (o pedido de conexão, os ids de projeto e de parecer, o aviso de versão do site dele). Com o
# backend da produção, no topo do estado.json, como sempre. Com outro PRANCHA_OK_API (a extensão de homologação, o
# backend local), em estado.json["backends"][api()]: as duas extensões instaladas juntas não trocam os vínculos nem o
# último parecer uma da outra. O resto (instalacao, servidores) é da máquina, um só para todos os backends.
CHAVES_DO_BACKEND = ("pedido", "vinculos", "ultimoParecer", "origens", "medidasConfirmadas", "versaoPublicada")
_BACKENDS = "backends"


def _da_producao() -> bool:
    return api() == API_PADRAO


def _do_backend(arquivo: dict) -> dict:
    """O que o código vê do estado.json: com outro backend, as chaves da máquina e as do backend dele."""
    if _da_producao():
        return arquivo
    backends = arquivo.get(_BACKENDS)
    proprio = backends.get(api()) if isinstance(backends, dict) else None
    visto = {c: v for c, v in arquivo.items() if c not in CHAVES_DO_BACKEND and c != _BACKENDS}
    if isinstance(proprio, dict):
        visto.update({c: v for c, v in proprio.items() if c in CHAVES_DO_BACKEND})
    return visto


def _no_arquivo(arquivo: dict, visto: dict) -> dict:
    """O estado.json depois de `visto` mudar: as chaves da produção e as dos outros backends ficam como estavam."""
    if _da_producao():
        return visto
    backends = arquivo.get(_BACKENDS)
    backends = dict(backends) if isinstance(backends, dict) else {}
    backends[api()] = {c: v for c, v in visto.items() if c in CHAVES_DO_BACKEND}
    novo = {c: v for c, v in arquivo.items() if c in CHAVES_DO_BACKEND}
    novo.update({c: v for c, v in visto.items() if c not in CHAVES_DO_BACKEND and c != _BACKENDS})
    novo[_BACKENDS] = backends
    return novo


class EstadoIndisponivel(OSError):
    """O estado.json existe mas não se leu (preso, sem permissão): nada se grava, para não apagar o que ele tem."""


def _pausa(segundos: float) -> None:
    time.sleep(segundos)


def _ler_texto(caminho: Path) -> str | None:
    """O texto do estado.json, ou None se ele não existe. Leitura que falha tenta de novo; falhou sempre, levanta."""
    erro: OSError | None = None
    for tentativa in range(TENTATIVAS_ESTADO):
        try:
            return caminho.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as e:
            erro = e
            if tentativa < TENTATIVAS_ESTADO - 1:
                _pausa(PAUSA_ESTADO_S)
    raise EstadoIndisponivel(f"Não consegui ler {caminho} ({erro}); nada foi gravado nele.")


def ler_estado() -> dict:
    """Pedido de conexão em andamento (o segredo dele vale 10 min, uma vez), vínculos, último parecer e a origem de
    cada um, medidas confirmadas: as do backend de PRANCHA_OK_API (CHAVES_DO_BACKEND). O token da conexão não fica
    aqui: fica no Gerenciador de Credenciais (backend.py), também por backend.
    Só para ler: sem o arquivo, ou sem conseguir lê-lo, {}. Para mudar, `atualizar_estado` (que não apaga nada
    quando a leitura falha)."""
    try:
        texto = _ler_texto(pasta() / _ESTADO)
        estado = json.loads(texto) if texto is not None else {}
    except (OSError, ValueError):
        return {}
    return _do_backend(estado) if isinstance(estado, dict) else {}


def _guardar_ilegivel(caminho: Path, texto: str) -> None:
    """O estado.json que não é JSON (cortado por uma versão de antes, disco com defeito) vai para um arquivo ao lado,
    com o conteúdo de antes: o estado recomeça, mas o que ele tinha não se perde."""
    guardado = caminho.with_name(f"estado.ilegivel-{time.time_ns()}.json")
    guardado.write_text(texto, encoding="utf-8")


def _gravar_atomico(caminho: Path, estado: dict) -> None:
    """Escreve num temporário da mesma pasta e troca o arquivo de uma vez (os.replace): quem lê nunca vê o arquivo pela
    metade, e uma gravação interrompida deixa o de antes inteiro."""
    fd, temporario = tempfile.mkstemp(prefix="estado.", suffix=".tmp", dir=caminho.parent)
    os.close(fd)
    try:
        with open(temporario, "w", encoding="utf-8") as f:
            f.write(json.dumps(estado, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        for tentativa in range(TENTATIVAS_ESTADO):
            try:
                os.replace(temporario, caminho)
                return
            except PermissionError:  # no Windows, o destino aberto por outro leitor: espera e tenta de novo
                if tentativa == TENTATIVAS_ESTADO - 1:
                    raise
                _pausa(PAUSA_ESTADO_S)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def atualizar_estado(mudar: Callable[[dict], None]) -> dict:
    """Lê o estado, aplica `mudar` (que altera o dicionário no lugar) e grava, de uma vez. A leitura que falha não vira
    {}: levanta EstadoIndisponivel e nada se grava; o arquivo que não é JSON fica guardado ao lado (_guardar_ilegivel).
    Devolve o estado gravado (o que o backend de PRANCHA_OK_API vê dele, como `ler_estado`)."""
    caminho = pasta() / _ESTADO
    texto = _ler_texto(caminho)
    estado: dict = {}
    if texto is not None:
        try:
            lido = json.loads(texto)
        except ValueError:
            lido = None
        if isinstance(lido, dict):
            estado = lido
        else:
            _guardar_ilegivel(caminho, texto)
    visto = _do_backend(estado)
    mudar(visto)
    _gravar_atomico(caminho, _no_arquivo(estado, visto))
    return visto


def gravar_estado(**mudancas) -> None:
    atualizar_estado(lambda estado: estado.update(mudancas))
