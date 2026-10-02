"""Aviso de versão nova do conector (a extensão .mcpb não se atualiza sozinha no Claude Desktop:
só as do diretório oficial; decisão do David, 02/10/2026).

O site publica a versão em `{SITE}/downloads/autocad.json` (gerado pelo `npm run empacotar`). O
`conectar` e o `status` comparam com a deste pacote e, se há uma mais nova, devolvem o aviso para o
assistente repassar. Consulta curta (3 s), guardada por 6 h no estado.json; qualquer falha fica em
silêncio: o aviso nunca atrapalha o trabalho.

    aviso() -> None | {"versao", "mensagem"}
"""
from __future__ import annotations

import os
import re
import time

import httpx

from . import __version__
from .locais import gravar_estado, ler_estado

# Site de produção. PRANCHA_OK_SITE troca (vazio desliga, como no teste com o backend local).
SITE_PADRAO = "https://pranchaok.com.br"
PRAZO_S = 3.0
GUARDA_S = 6 * 3600


def site() -> str:
    return os.environ.get("PRANCHA_OK_SITE", SITE_PADRAO).rstrip("/")


def _numeros(versao: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", versao)[:3])


def mais_nova(publicada: str, instalada: str = __version__) -> bool:
    """'0.3.2' é mais nova que '0.3.1'; texto que não é versão nunca é."""
    p, i = _numeros(publicada), _numeros(instalada)
    return bool(p) and bool(i) and p > i


def _publicada(agora: float) -> str | None:
    guardada = ler_estado().get("versaoPublicada") or {}
    if guardada.get("site") == site() and agora - guardada.get("em", 0) < GUARDA_S:
        return guardada.get("versao")
    try:
        resposta = httpx.get(f"{site()}/downloads/autocad.json", timeout=PRAZO_S)
        versao = resposta.json().get("versao") if resposta.status_code == 200 else None
    except Exception:
        return None
    if isinstance(versao, str):
        gravar_estado(versaoPublicada={"site": site(), "versao": versao, "em": agora})
        return versao
    return None


def mensagem(versao: str) -> str:
    return (f"Há uma versão nova do conector do Prancha Ok ({versao}; esta é a {__version__}). Para "
            f"atualizar: baixe em {site()}/autocad e, no Claude Desktop, arraste o arquivo para "
            "Configurações › Extensões e clique em Instalar (substitui a versão atual). No Claude Code: "
            "/plugin marketplace update prancha-ok.")


def aviso(agora: float | None = None) -> dict | None:
    if not site():
        return None
    versao = _publicada(time.time() if agora is None else agora)
    return {"versao": versao, "mensagem": mensagem(versao)} if versao and mais_nova(versao) else None
