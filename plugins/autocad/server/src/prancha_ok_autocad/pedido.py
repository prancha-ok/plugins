"""Formato do pedido que o prancha_ok.lsp lê, e dos textos que vão para o desenho.

O pedido é um arquivo com UM dado AutoLISP por linha: o comando na 1ª e cada
argumento numa linha própria. O LISP lê linha a linha e passa cada uma ao `read`.
Assim nenhuma linha nem nenhuma string passa de LIMITE_LINHA caracteres, mesmo
num parecer com dezenas de itens.

Por quê (ponto 12 das observações de 30/09/2026): na 0.1.4 o quadro-resumo de um
parecer com 32 itens pendentes ia numa string só, de milhares de caracteres, numa
linha só, e o AutoCAD 2025 respondeu PEDIDO_INVALIDO (o `read`/`read-line` não
deu conta), enquanto as nuvens, com textos de até 240 caracteres, passaram.

Os textos que viram MTEXT (rótulo da nuvem e quadro-resumo) vão em ASCII puro:
o que não é ASCII vira o código Unicode do próprio AutoCAD (\\U+00E1 é "á"), que o
MTEXT mostra como o caractere. Assim a codificação do arquivo (UTF-8 ou ANSI,
conforme a versão do AutoCAD) não muda nada. Pontuação tipográfica (·, —, “ ”, …)
vira a equivalente em ASCII, que qualquer fonte do AutoCAD tem.
"""
from __future__ import annotations

import math
import re

# Caracteres por linha do pedido (e, portanto, por string). Abaixo dos 256 que as
# versões antigas do AutoLISP aceitavam numa string.
LIMITE_LINHA = 250

_TROCAS = {
    "\u00b7": "-",  # · ponto médio
    "\u2022": "-",  # • marcador
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",  # hífens e travessões
    "\u2212": "-",  # − sinal de menos
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u2026": "...",
    "\u2264": "<=", "\u2265": ">=", "\u2260": "<>",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",
    "\u2192": "->",
}


def lisp(valor) -> str:
    """Valor Python como literal AutoLISP (string, número, lista)."""
    if isinstance(valor, str):
        escapado = valor.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
        return f'"{escapado}"'
    if isinstance(valor, bool) or valor is None:
        return "T" if valor else "nil"
    if isinstance(valor, int):
        if not -(2**31) <= valor < 2**31:  # o inteiro do AutoLISP tem 32 bits
            raise ValueError(f"inteiro fora do alcance do AutoLISP: {valor}")
        return repr(valor)
    if isinstance(valor, float):
        # Sem notação científica (1e-05), que o `read` não tem por que aceitar: casas fixas.
        if not math.isfinite(valor):
            raise ValueError(f"número não finito: {valor}")
        return f"{valor:.6f}"
    if isinstance(valor, (list, tuple)):
        return "(" + " ".join(lisp(v) for v in valor) + ")"
    raise TypeError(f"sem literal AutoLISP para {type(valor).__name__}")


def pedido_lisp(comando: str, *argumentos) -> str:
    """O conteúdo do arquivo de pedido: o comando e cada argumento, um por linha."""
    linhas = [lisp(comando), *(lisp(a) for a in argumentos)]
    for linha in linhas:
        if len(linha) > LIMITE_LINHA:
            raise ValueError(f"linha de {len(linha)} caracteres no pedido '{comando}' (máximo {LIMITE_LINHA})")
    return "\n".join(linhas) + "\n"


def texto_mtext(texto: str) -> str:
    """Texto para o conteúdo de um MTEXT, em ASCII: sem os códigos de formatação do MTEXT
    (barra invertida, chaves, %%), sem quebra de linha, e o que não é ASCII como \\U+XXXX."""
    saida = []
    for c in texto.replace("%%", "%"):
        c = _TROCAS.get(c, c)
        if c == "\\":
            saida.append("/")
        elif c == "{":
            saida.append("(")
        elif c == "}":
            saida.append(")")
        elif len(c) > 1 or 32 <= ord(c) < 127:
            saida.append(c)
        elif ord(c) < 32 or ord(c) == 127:
            saida.append(" ")
        elif ord(c) <= 0xFFFF:
            saida.append(f"\\U+{ord(c):04X}")
        else:
            saida.append("?")  # fora do plano básico (emoji): o \U+ do AutoCAD tem 4 dígitos
    return "".join(saida)


# Um "átomo" do conteúdo do MTEXT: um código (\U+XXXX, \P) ou um caractere. Os pedaços
# nunca cortam um código ao meio.
_ATOMO = re.compile(r"\\U\+[0-9A-F]{4}|\\P|.", re.DOTALL)


def _custo(atomo: str) -> int:
    """Caracteres que o átomo ocupa no literal AutoLISP (barra e aspas ganham uma barra)."""
    return len(atomo) + atomo.count("\\") + atomo.count('"')


def pedacos(conteudo: str, limite: int = LIMITE_LINHA) -> list[str]:
    """Corta o conteúdo do MTEXT em pedaços cujo literal AutoLISP cabe em `limite` (o LISP
    junta com strcat). Nunca devolve lista vazia."""
    saida: list[str] = []
    atual, custo = [], 2  # as aspas do literal
    for atomo in _ATOMO.findall(conteudo):
        c = _custo(atomo)
        if custo + c > limite and atual:
            saida.append("".join(atual))
            atual, custo = [], 2
        atual.append(atomo)
        custo += c
    if atual or not saida:
        saida.append("".join(atual))
    return saida


def cabe(conteudo: str, limite: int) -> str:
    """O começo do conteúdo do MTEXT cujo literal cabe em `limite`, com "..." se cortou."""
    atomos = _ATOMO.findall(conteudo)
    if 2 + sum(_custo(a) for a in atomos) <= limite:
        return conteudo
    saida, custo = [], 2 + 3
    for atomo in atomos:
        if custo + _custo(atomo) > limite:
            break
        saida.append(atomo)
        custo += _custo(atomo)
    return "".join(saida).rstrip() + "..."


def marca(handle: str, cor: int, rotulo: str) -> list:
    """Uma marca do comando `marcar`: [handle, cor ACI, rótulo do MTEXT], numa linha do pedido."""
    resto = LIMITE_LINHA - len(lisp([handle, cor])) - 1  # o espaço antes do rótulo
    return [handle, cor, cabe(texto_mtext(rotulo), resto)]


def regiao(handle_titulo: str | None, caixa: list[float] | None, espaco: str | None, cor: int,
           rotulo: str) -> list:
    """Uma nuvem do comando `regioes`: [handle do título ou "", caixa (x0 y0 x1 y1) ou nil,
    espaço ("modelo", "papel" ou ""), cor ACI, rótulo do MTEXT], numa linha do pedido."""
    cabeca = [handle_titulo or "", [float(n) for n in caixa] if caixa else None, espaco or "", cor]
    resto = LIMITE_LINHA - len(lisp(cabeca)) - 1
    return [*cabeca, cabe(texto_mtext(rotulo), resto)]


def pedacos_quadro(linhas: list[str]) -> list[str]:
    """O conteúdo do MTEXT do quadro-resumo (uma linha por parágrafo, \\P) em pedaços."""
    return pedacos("\\P".join(texto_mtext(linha) for linha in linhas))
