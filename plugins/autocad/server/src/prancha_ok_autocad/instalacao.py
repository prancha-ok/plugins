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

import sys
from pathlib import PureWindowsPath

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


def preparar_ao_subir() -> None:
    """O passo 1 na subida do servidor: nunca o impede de subir. O motivo de uma falha
    vai para o log do assistente (saída de erro); o `diagnosticar` mostra as pastas."""
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
