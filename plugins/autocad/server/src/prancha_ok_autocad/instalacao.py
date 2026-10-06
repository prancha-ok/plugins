"""Instalação automática: o servidor se prepara sozinho, sem perguntar nada.

A extensão do Claude Desktop (.mcpb) e o plugin do Claude Code e do Codex não rodam
script de instalação. O que o comando `instalar` fazia à mão passa a acontecer aqui,
e cada passo é idempotente (rodar de novo não muda nada):

1. Ao subir (`preparar`, chamado por servidor.rodar): copia o prancha_ok.lsp desta
   versão para %USERPROFILE%\\.prancha-ok\\lisp quando ele falta ou é de outra versão,
   cria a pasta de troca e anota em estado.json a versão instalada.
2. Em todo comando ao AutoCAD (`expressao_confiavel`, no começo do gatilho de
   autocad.py): se a pasta do LISP ainda não está no TRUSTEDPATHS, o próprio AutoCAD
   a acrescenta, antes de carregar o LISP. É o mesmo canal do comando (vale no
   AutoCAD completo e no LT) e roda dentro do AutoCAD, fora do contêiner do Claude
   Desktop (MSIX), onde gravar no registro não chega ao AutoCAD (instalar.py). O
   AutoCAD guarda o TRUSTEDPATHS no perfil ao fechar. As outras pastas confiáveis do
   escritório ficam como estão.

O comando `instalar` continua: faz o passo 1 e, com o AutoCAD fechado e fora do MSIX,
grava a pasta no registro (instalar.py).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path, PureWindowsPath

from . import __version__
from .locais import atualizar_lisp, gravar_estado, ler_estado, pasta_ipc, pasta_lisp
from .pedido import lisp


def preparar() -> dict:
    """Passo 1. Devolve o que fez: {versao, anterior, lispCopiado}. Não escreve na saída
    padrão (no servidor MCP ela é o canal com o assistente)."""
    copiado = atualizar_lisp()
    pasta_ipc()
    anterior = (ler_estado().get("instalacao") or {}).get("versao")
    if anterior != __version__:
        gravar_estado(instalacao={"versao": __version__, "anterior": anterior})
    return {"versao": __version__, "anterior": anterior, "lispCopiado": copiado}


# A pasta deste servidor (a do pacote): a extensão do Claude Desktop e um registro manual rodam de pastas diferentes.
ORIGEM = str(Path(__file__).resolve().parents[2])


def _vivo(pid: int) -> bool:
    """O processo existe? No Windows, pela API (os.kill(pid, 0) lá MATA o processo); fora dele, sinal 0."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        processo = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not processo:
            return False
        codigo = ctypes.c_ulong(0)
        try:
            ok = ctypes.windll.kernel32.GetExitCodeProcess(processo, ctypes.byref(codigo))
            return bool(ok) and codigo.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(processo)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def registrar_servidor(origem: str = ORIGEM, pid: int | None = None) -> None:
    """Anota em estado.json este servidor (pasta, versão e processo) e tira os que já terminaram."""
    servidores = {o: s for o, s in (ler_estado().get("servidores") or {}).items()
                  if isinstance(s, dict) and _vivo(int(s.get("pid") or 0))}
    servidores[origem] = {"versao": __version__, "pid": pid or os.getpid(), "inicio": time.time()}
    gravar_estado(servidores=servidores)


def outros_servidores(origem: str = ORIGEM) -> list[dict]:
    """Os servidores do Prancha Ok rodando agora a partir de outra pasta (pente fino de 04/10/2026, sugestão 5: "Os
    dois servidores rodaram juntos e um sobrescrevia o LISP do outro")."""
    return [{"pasta": o, "versao": s.get("versao")} for o, s in (ler_estado().get("servidores") or {}).items()
            if o != origem and isinstance(s, dict) and _vivo(int(s.get("pid") or 0))]


def aviso_de_outro_servidor(origem: str = ORIGEM) -> str | None:
    outros = outros_servidores(origem)
    if not outros:
        return None
    lista = "; ".join(f"versão {o['versao']} em {o['pasta']}" for o in outros)
    return ("Há outro conector do Prancha Ok rodando neste computador ao mesmo tempo (" + lista + "). Em geral é a "
            "extensão do Claude Desktop junto com um registro manual \"prancha-ok\" (feito pelo jeito avançado ou "
            "pelo INSTALAR.md): os dois trocam o arquivo do Prancha Ok no AutoCAD um do outro. Deixe um só: na "
            "extensão, apague o \"prancha-ok\" de mcpServers (Claude Desktop: Configurações > Desenvolvedor > Editar "
            "configuração; Claude Code: claude mcp remove prancha-ok) e reinicie o assistente.")


def preparar_ao_subir() -> None:
    """O passo 1 na subida do servidor: nunca o impede de subir. O motivo de uma falha
    vai para o log do assistente (saída de erro); o `diagnosticar` mostra as pastas."""
    try:
        registrar_servidor()
    except Exception as e:  # estado.json sem permissão: o aviso de servidor duplicado fica sem dado
        print(f"[prancha-ok] não deu para registrar o servidor: {e}", file=sys.stderr)
    try:
        feito = preparar()
    except Exception as e:  # pasta sem permissão, disco cheio...
        print(f"[prancha-ok] não deu para preparar a pasta do LISP: {e}", file=sys.stderr)
        return
    if feito["lispCopiado"] or feito["anterior"] != feito["versao"]:
        print(f"[prancha-ok] LISP {feito['versao']} instalado em {pasta_lisp()} "
              f"(antes: {feito['anterior'] or 'nenhum'})", file=sys.stderr)


def expressao_confiavel(pasta: str | PureWindowsPath | None = None) -> str:
    """Passo 2: expressão AutoLISP que põe `pasta` (padrão: a do LISP) no TRUSTEDPATHS se
    ela ainda não está lá. A procura ignora maiúsculas e o sentido da barra, passando os
    dois lados pelo mesmo `strcase` do AutoCAD; o `setvar` vai num vl-catch-all-apply
    para uma recusa do AutoCAD não derrubar o comando (o carregamento depois diz o motivo,
    LOAD_RECUSADO)."""
    alvo = str(pasta if pasta is not None else pasta_lisp()).rstrip("\\/")
    procura = alvo.replace("\\", "/")
    atual = '(getvar "TRUSTEDPATHS")'
    return (
        f"(if (not (vl-string-search (strcase {lisp(procura)}) "
        f"(strcase (vl-string-translate {lisp(chr(92))} \"/\" {atual}))))"
        f" (vl-catch-all-apply (quote setvar) (list \"TRUSTEDPATHS\""
        f" (if (= {atual} \"\") {lisp(alvo)} (strcat {atual} \";\" {lisp(alvo)})))))"
    )
