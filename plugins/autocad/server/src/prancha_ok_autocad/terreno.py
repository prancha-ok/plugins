"""O terreno conferido pelo desenho (0.5.0): as letras dos lados do lote no AutoCAD e o que vai ao chat.

O site confere o terreno clicando nos lados de rua na prancha (etapa de medidas no próprio desenho). Aqui, o conector
escreve no desenho a letra e a medida de cada lado (uma seta do rótulo ao meio do lado, em verde os que dão para a rua
pela sugestão ou pelo terreno já conferido, em cinza os outros) e a pessoa diz no chat quais dão para a rua; o
backend calcula a posição de cada lado (frente, laterais, fundos) e grava o terreno, com a mesma conta do site
(packages/backend/convex/lib/terrenoDoDesenho.ts).

Os lados vêm do `terrenoNoDesenho` da rota do parecer: {letra, medidaM, handle, pontos: [x, y, ...] no modelo, rua}.
O lote é sempre do espaço do modelo (o motor o procura lá), em coordenadas do mundo: as chamadas vão no modelo, sem
handle de referência (o lado pode estar dentro de um bloco).
"""
from __future__ import annotations

import math

from .chamadas import LARGURA_LETRA, Chamada

COR_RUA = 3  # verde (ACI), como no site
COR_LOTE = 8  # cinza
ALTURA_RELATIVA = 0.025  # altura da letra: 2,5% da diagonal do lote
SETA = 2.0  # comprimento da seta, em alturas
PONTA = 0.8  # comprimento da ponta, em alturas
LARGURA_PONTA = 0.35  # em alturas
FOLGA = 0.4  # da seta ao rótulo, em alturas

Ponto = tuple[float, float]


def _pares(pontos: list[float]) -> list[Ponto]:
    return [(float(pontos[k]), float(pontos[k + 1])) for k in range(0, len(pontos) - 1, 2)]


def meio_do_lado(pontos: list[float]) -> tuple[Ponto, Ponto]:
    """O ponto na metade do comprimento do lado e a direção (unitária) do trecho onde ele cai."""
    pares = _pares(pontos)
    trechos = [(a, b, math.dist(a, b)) for a, b in zip(pares, pares[1:], strict=False)]
    metade = sum(t[2] for t in trechos) / 2
    for a, b, d in trechos:
        if d > 0 and metade <= d:
            f = metade / d
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
        metade -= d
    a, b = pares[0], pares[-1]
    d = math.dist(a, b) or 1.0
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def dentro_do_lote(p: Ponto, contorno: list[Ponto]) -> bool:
    """O ponto está dentro do contorno do lote (par ou ímpar de cruzamentos de um raio para a direita)."""
    dentro = False
    for (x0, y0), (x1, y1) in zip(contorno, contorno[1:] + contorno[:1], strict=True):
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
            dentro = not dentro
    return dentro


def _medida(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",") + " m"


def chamadas_dos_lados(lados: list[dict]) -> list[Chamada]:
    """Uma chamada por lado: a seta para fora do lote, do rótulo "A 21,00 m" ao meio do lado."""
    todos = [p for lado in lados for p in _pares(lado["pontos"])]
    if not todos:
        return []
    xs, ys = [p[0] for p in todos], [p[1] for p in todos]
    altura = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)) * ALTURA_RELATIVA, 1e-6)
    saida = []
    for lado in lados:
        meio, (dx, dy) = meio_do_lado(lado["pontos"])
        # Para fora: o lado da normal em que um passo curto sai do contorno (vale para lote em L, onde o centro dos
        # vértices fica fora do lote ou do lado errado de um lado de dentro).
        fora = (-dy, dx)
        if dentro_do_lote((meio[0] + fora[0] * altura * 0.1, meio[1] + fora[1] * altura * 0.1), todos):
            fora = (dy, -dx)
        comeco = (meio[0] + fora[0] * (SETA + PONTA) * altura, meio[1] + fora[1] * (SETA + PONTA) * altura)
        base = (meio[0] + fora[0] * PONTA * altura, meio[1] + fora[1] * PONTA * altura)
        texto = f"{lado['letra']} {_medida(lado['medidaM'])}"
        largura = len(texto) * LARGURA_LETRA * altura
        # O rótulo (MTEXT ancorado no meio da esquerda) depois do começo da seta, do lado de fora.
        x = comeco[0] + FOLGA * altura if fora[0] >= 0 else comeco[0] - FOLGA * altura - largura
        y = comeco[1] + fora[1] * FOLGA * altura
        saida.append(Chamada(referencia="", espaco="modelo", cor=COR_RUA if lado.get("rua") else COR_LOTE,
                             altura=altura, seta=(comeco, base, meio), largura_ponta=LARGURA_PONTA * altura,
                             rotulo=(x, y), texto=texto, itens=()))
    return saida


def para_o_chat(t: dict) -> dict:
    """O que o assistente mostra: os lados com a letra e a medida, os sugeridos como rua e as áreas conhecidas."""
    areas = t.get("areas") or {}
    return {
        "conferido": bool(t.get("conferido")),
        "lados": [{"letra": l["letra"], "medida": _medida(l["medidaM"]), "rua": bool(l.get("rua"))} for l in t["lados"]],
        "ruasSugeridas": [l["letra"] for l in t["lados"] if l.get("rua")],
        "areas": {nome: valor for nome, valor in (("conferida", areas.get("conferida")), ("rgi", areas.get("rgi")),
                                                 ("iptu", areas.get("iptu")), ("prancha", areas.get("prancha")))
                  if valor is not None},
    }
