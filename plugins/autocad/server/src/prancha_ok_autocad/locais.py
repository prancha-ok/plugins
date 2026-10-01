"""Onde o MCP guarda as coisas na máquina e com qual backend fala."""
from __future__ import annotations

import json
import os
import shutil
import socket
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


def ler_estado() -> dict:
    """Pedido de conexão em andamento (o segredo dele vale 10 min, uma vez) e último parecer.
    O token da conexão não fica aqui: fica no Gerenciador de Credenciais (backend.py)."""
    try:
        return json.loads((pasta() / _ESTADO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(**mudancas) -> None:
    estado = {**ler_estado(), **mudancas}
    (pasta() / _ESTADO).write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
