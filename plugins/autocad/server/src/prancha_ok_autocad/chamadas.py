"""Chamadas com seta no carimbo e no quadro de áreas (0.3.4; observações de 02/10/2026, item 2).

O especialista marcou o parecer #2 da prancha real 02 pelo MCP: 77 nuvens, e "foram tantas nuvens
sobre o carimbo que ali ficou extremamente confuso, muito sobreposto". A sugestão dele: no lugar da
nuvem, uma seta do erro (texto, número ou desenho) até uma chamada "[nº] DÚVIDA/CONFERIR/PERGUNTA";
ao menos no carimbo, e nos desenhos continuam as nuvens.

Vira chamada (o resto continua nuvem, como antes):
  1. o handle cuja caixa tem o centro dentro de uma tabela (carimbo ou quadro de áreas com caixa:
     `regiao.caixa` de qualquer item do parecer), no mesmo layout;
  2. o handle cuja nuvem se sobrepõe à de outros, num amontoado de MINIMO_AMONTOADO ou mais (a nuvem
     com a folga do LISP, pok-caixa-folgada): "onde várias marcas cairiam na mesma caixa". Só
     amontoam marcas de tamanho parecido (lado maior até RAZAO_TAMANHO vezes o da outra) em que
     nenhum desenho envolve a outra marca: a nuvem do lote (folga de 1/4 do lado maior) cobre as
     cotas de dentro e as de fora, junto da divisa, e a edificação, e juntaria a planta de situação
     inteira num grupo só;
  3. a linha sem handle achado cuja região é uma tabela achada: a seta aponta a borda da tabela.

Geometria (toda aqui; o LISP só desenha o que vem no pedido): por grupo (uma tabela ou um
amontoado), uma coluna de rótulos à direita do grupo, um embaixo do outro na ordem dos números, a
FOLGA_COLUNA alturas da borda; a coluna que bateria numa tabela ou noutra coluna do mesmo layout
anda para a direita até ficar livre (as nuvens não contam: a de uma polilinha comprida cobre meia
folha). Um rótulo "[nº] SITUAÇÃO"
por item, na cor da situação, e uma seta (polilinha com a ponta cheia, sem depender do estilo de
cota do desenho) do começo do rótulo até o ponto mais perto de cada lugar do item no grupo; o
handle de vários itens recebe uma seta de cada rótulo.
Medidas em alturas `a` do texto: a mediana das alturas dos textos marcados no grupo ou, sem texto,
o lado maior do grupo / ALTURA_SEM_TEXTO.

As posições do desenho vêm do LISP (comando `caixas`: espaço, layout e caixa de cada handle);
nada aqui fala com o AutoCAD.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .marcas import COR, ROTULO, Linha, chave_regiao, marca_do_handle, regiao_achada

# Os tipos de região que são tabela (services/engine/.../extracao/regioes.py, TIPOS_TABELA).
TIPOS_TABELA = ("carimbo", "quadro_areas")
MINIMO_AMONTOADO = 3
# Lado maior de uma marca sobre o da outra, no máximo, para as duas amontoarem: um texto comprido e
# um número curto da mesma altura ("DORMITÓRIO 01" e "12,5", 13 e 4 caracteres: 3,25) amontoam; o
# lote (30) e a cota do lado dele (2) não.
RAZAO_TAMANHO = 4.0
# Em alturas do texto da chamada.
PASSO = 2.0  # de um rótulo ao seguinte na coluna
MEIA_FAIXA = 0.8  # o rótulo reserva 0,8a acima e abaixo do meio (a letra ocupa 0,5a): 0,4a entre dois
FOLGA_COLUNA = 4.0  # da borda do grupo (ou do obstáculo) ao começo dos rótulos
RECUO_SETA = 0.5  # a seta começa meia altura antes do rótulo
PONTA = 1.0  # comprimento da ponta da seta (no máximo metade da seta)
LARGURA_PONTA = 0.4
LARGURA_LETRA = 0.8  # largura estimada de um caractere (as fontes do AutoCAD ficam abaixo disso)
ALTURA_SEM_TEXTO = 40.0

Caixa = tuple[float, float, float, float]
Ponto = tuple[float, float]


@dataclass(frozen=True)
class Lugar:
    """Onde um handle está no desenho, como o LISP responde (`caixas`)."""
    handle: str
    folha: tuple[str, str]  # (espaço "modelo"|"papel", layout)
    caixa: Caixa
    altura: float | None  # altura do texto (TEXT, MTEXT, ATTRIB); None nos outros


@dataclass(frozen=True)
class Tabela:
    """Carimbo ou quadro de áreas achado no desenho."""
    chave: tuple  # marcas.chave_regiao
    folha: tuple[str, str]
    caixa: Caixa
    referencia: str  # handle do título, que diz o layout ao LISP ("" = modelo, sem título)
    contem: bool  # a caixa é a da tabela (vale para "dentro"); False: só a do título


@dataclass(frozen=True)
class Chamada:
    """Uma seta e o rótulo dela, prontos para o comando `chamadas` do LISP."""
    referencia: str  # handle cujo espaço e layout valem ("" = modelo)
    espaco: str
    cor: int
    altura: float
    seta: tuple[Ponto, Ponto, Ponto]  # começo, base da ponta, ponta
    largura_ponta: float
    rotulo: Ponto  # meio da esquerda do rótulo (MTEXT com anexo 4)
    texto: str  # "[nº] SITUAÇÃO"; vazio: só mais uma seta do mesmo rótulo (o item tem outro lugar)
    itens: tuple[int, ...]


@dataclass
class Plano:
    nuvens: list[tuple[str, int, str]]  # (handle, cor, rótulo), como marcas.marcas_por_handle
    chamadas: list[Chamada]


@dataclass
class _Alvo:
    caixa: Caixa
    referencia: str
    linhas: list[Linha]
    altura: float | None


@dataclass
class _Grupo:
    folha: tuple[str, str]
    caixa: Caixa
    alvos: list[_Alvo]


# ---------------------------------------------------------------- caixas

def _numero(n) -> bool:
    return isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)


def _caixa(c) -> Caixa | None:
    """[x0, y0, x1, y1] com números finitos; caixa sem largura ou sem altura (linha reta, texto
    de um caractere) vale."""
    if not isinstance(c, (list, tuple)) or len(c) != 4 or not all(_numero(n) for n in c):
        return None
    x0, y0, x1, y1 = (float(n) for n in c)
    return (x0, y0, x1, y1) if x1 >= x0 and y1 >= y0 else None


def _uniao(caixas) -> Caixa:
    caixas = list(caixas)
    return (min(c[0] for c in caixas), min(c[1] for c in caixas), max(c[2] for c in caixas),
            max(c[3] for c in caixas))


def _cruzam(a: Caixa, b: Caixa) -> bool:
    """Áreas que se sobrepõem (encostar na borda não conta)."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _dentro(p: Ponto, c: Caixa) -> bool:
    return c[0] <= p[0] <= c[2] and c[1] <= p[1] <= c[3]


def _centro(c: Caixa) -> Ponto:
    return ((c[0] + c[2]) / 2, (c[1] + c[3]) / 2)


def caixa_da_nuvem(lugar: Lugar) -> Caixa:
    """A caixa da nuvem que o LISP desenharia em volta do handle (pok-caixa-folgada): a folga é
    1/4 do lado maior ou meia altura do texto, o que for maior."""
    x0, y0, x1, y1 = lugar.caixa
    folga = max(0.25 * max(x1 - x0, y1 - y0), 0.5 * (lugar.altura or 0.0), 1e-3)
    return (x0 - folga, y0 - folga, x1 + folga, y1 + folga)


# ---------------------------------------------------------------- o que o LISP respondeu

def lugares(resposta: list[dict]) -> dict[str, Lugar]:
    """A resposta do `caixas` (uma linha por handle) como {handle: Lugar}. O handle que o desenho
    não tem, o de dentro de um bloco (semLugar) e a linha torta ficam de fora."""
    saida: dict[str, Lugar] = {}
    for linha in resposta:
        h, caixa, espaco, layout = linha.get("h"), _caixa(linha.get("c")), linha.get("e"), linha.get("l")
        if not (isinstance(h, str) and h and caixa and espaco in ("modelo", "papel") and isinstance(layout, str)):
            continue
        a = linha.get("a")
        saida[h] = Lugar(h, (espaco, layout), caixa, float(a) if _numero(a) and a > 0 else None)
    return saida


def handles_das_tabelas(p: dict) -> list[str]:
    """Os títulos das tabelas do parecer: o `caixas` diz em que layout cada uma está."""
    saida: list[str] = []
    for item in p.get("itens") or []:
        r = item.get("regiao")
        achada = regiao_achada(r) if isinstance(r, dict) and r.get("tipo") in TIPOS_TABELA else None
        if achada and achada["handleTitulo"] and achada["handleTitulo"] not in saida:
            saida.append(achada["handleTitulo"])
    return saida


def tabelas(p: dict, achados: dict[str, Lugar]) -> list[Tabela]:
    """Carimbos e quadros de áreas que os itens do parecer (todas as situações) apontam e que se
    acham no desenho, como o LISP acha uma região (pok-lugar-regiao): com o título achado, no
    layout dele; sem ele, a caixa vale no modelo."""
    saida: list[Tabela] = []
    for item in p.get("itens") or []:
        r = item.get("regiao")
        achada = regiao_achada(r) if isinstance(r, dict) and r.get("tipo") in TIPOS_TABELA else None
        if achada is None or any(t.chave == chave_regiao(achada) for t in saida):
            continue
        titulo = achados.get(achada["handleTitulo"]) if achada["handleTitulo"] else None
        caixa = tuple(achada["caixa"]) if achada["caixa"] else None
        if titulo:
            saida.append(Tabela(chave_regiao(achada), titulo.folha, caixa or titulo.caixa, titulo.handle,
                                caixa is not None))
        elif caixa and achada["espaco"] != "papel":
            saida.append(Tabela(chave_regiao(achada), ("modelo", "Model"), caixa, "", True))
    return saida


# ---------------------------------------------------------------- o plano

def _tamanho(lugar: Lugar) -> float:
    """O lado maior da marca (no texto, ao menos a altura dele)."""
    x0, y0, x1, y1 = lugar.caixa
    return max(x1 - x0, y1 - y0, lugar.altura or 0.0)


def _envolve(fora: Lugar, dentro: Lugar) -> bool:
    """Um desenho (não texto) em volta do outro, como o lote em volta da edificação. Texto sobre
    texto e duas caixas iguais são o amontoado mesmo."""
    f, d = fora.caixa, dentro.caixa
    return (fora.altura is None and f != d
            and f[0] <= d[0] and f[1] <= d[1] and d[2] <= f[2] and d[3] <= f[3])


def _amontoam(a: Lugar, b: Lugar) -> bool:
    """Duas marcas do mesmo layout, de tamanho parecido, nenhuma em volta da outra, com as nuvens
    se cobrindo."""
    menor, maior = sorted((_tamanho(a), _tamanho(b)))
    return (a.folha == b.folha and maior <= RAZAO_TAMANHO * menor
            and not _envolve(a, b) and not _envolve(b, a)
            and _cruzam(caixa_da_nuvem(a), caixa_da_nuvem(b)))


def _amontoados(handles: list[str], achados: dict[str, Lugar]) -> list[list[str]]:
    """Grupos de handles que amontoam (`_amontoam`, em cadeia), com MINIMO_AMONTOADO ou mais, na
    ordem do primeiro handle de cada um."""
    pai = {h: h for h in handles}

    def raiz(h: str) -> str:
        while pai[h] != h:
            pai[h] = pai[pai[h]]
            h = pai[h]
        return h

    for i, a in enumerate(handles):
        for b in handles[i + 1:]:
            if _amontoam(achados[a], achados[b]):
                pai[raiz(b)] = raiz(a)
    grupos: dict[str, list[str]] = {}
    for h in handles:
        grupos.setdefault(raiz(h), []).append(h)
    return [g for g in grupos.values() if len(g) >= MINIMO_AMONTOADO]


def planejar(linhas: list[Linha], achados: dict[str, Lugar], tabelas_achadas: list[Tabela]) -> Plano:
    """Divide as marcas entre nuvens e chamadas e decide onde fica cada chamada. A linha sem
    handle achado e sem tabela fica de fora: vai para a nuvem da região (servidor)."""
    por_handle: dict[str, list[Linha]] = {}
    for linha in linhas:
        for h in linha.handles:
            if h in achados:
                por_handle.setdefault(h, []).append(linha)

    grupos: dict[tuple, _Grupo] = {}

    def no_grupo(chave: tuple, folha: tuple[str, str], caixa: Caixa, alvo: _Alvo) -> None:
        grupo = grupos.setdefault(chave, _Grupo(folha, caixa, []))
        grupo.alvos.append(alvo)
        grupo.caixa = _uniao([grupo.caixa, alvo.caixa])

    soltos = []
    for h, ls in por_handle.items():
        lugar = achados[h]
        tabela = next((t for t in tabelas_achadas if t.contem and t.folha == lugar.folha
                       and _dentro(_centro(lugar.caixa), t.caixa)), None)
        if tabela:
            no_grupo(("tabela", tabela.chave), tabela.folha, tabela.caixa, _Alvo(lugar.caixa, h, ls, lugar.altura))
        else:
            soltos.append(h)
    amontoados = _amontoados(soltos, achados)
    em_amontoado = {h for g in amontoados for h in g}
    for indice, grupo in enumerate(amontoados):
        for h in grupo:
            lugar = achados[h]
            no_grupo(("amontoado", indice), lugar.folha, lugar.caixa, _Alvo(lugar.caixa, h, por_handle[h], lugar.altura))

    com_handle = {x.numero for ls in por_handle.values() for x in ls}
    por_chave = {t.chave: t for t in tabelas_achadas}
    for linha in linhas:
        tabela = por_chave.get(chave_regiao(linha.regiao)) if linha.regiao else None
        if linha.numero not in com_handle and tabela:
            no_grupo(("tabela", tabela.chave), tabela.folha, tabela.caixa,
                     _Alvo(tabela.caixa, tabela.referencia, [linha], None))

    nuvens = [h for h in soltos if h not in em_amontoado]
    plano = Plano(nuvens=[marca_do_handle(h, por_handle[h]) for h in nuvens], chamadas=[])
    # Obstáculos de cada layout: as tabelas e as colunas já postas. As nuvens não: a de uma
    # polilinha comprida (o lote, a moldura) cobre meia folha e jogaria a coluna para longe
    # (prancha real 02, simulada: a coluna do carimbo ia 270 unidades para a direita).
    ocupado: dict[tuple[str, str], list[Caixa]] = {}
    for t in tabelas_achadas:
        ocupado.setdefault(t.folha, []).append(t.caixa)
    ordem = [("tabela", t.chave) for t in tabelas_achadas] + [("amontoado", i) for i in range(len(amontoados))]
    for chave in ordem:
        if chave in grupos:
            plano.chamadas += _coluna(grupos[chave], ocupado.setdefault(grupos[chave].folha, []))
    return plano


def _altura(grupo: _Grupo) -> float:
    alturas = sorted(a.altura for a in grupo.alvos if a.altura)
    if alturas:
        meio = len(alturas) // 2
        return alturas[meio] if len(alturas) % 2 else (alturas[meio - 1] + alturas[meio]) / 2
    x0, y0, x1, y1 = grupo.caixa
    return max(max(x1 - x0, y1 - y0) / ALTURA_SEM_TEXTO, 1e-3)


def _seta(inicio: Ponto, caixa: Caixa, a: float) -> tuple[Ponto, Ponto, Ponto]:
    """Do começo ao ponto da caixa mais perto dele, com a base da ponta a PONTA alturas da ponta
    (no máximo metade da seta)."""
    ponta = (min(max(inicio[0], caixa[0]), caixa[2]), min(max(inicio[1], caixa[1]), caixa[3]))
    distancia = math.dist(inicio, ponta)
    if distancia == 0:
        return (inicio, ponta, ponta)
    comprimento = min(PONTA * a, distancia / 2)
    base = (ponta[0] + (inicio[0] - ponta[0]) * comprimento / distancia,
            ponta[1] + (inicio[1] - ponta[1]) * comprimento / distancia)
    return (inicio, base, ponta)


def _coluna(grupo: _Grupo, ocupado: list[Caixa]) -> list[Chamada]:
    """Um rótulo por item do grupo, na ordem dos números, numa coluna à direita do grupo, livre do
    que já ocupa o layout; uma seta do rótulo a cada lugar do item no grupo (as setas além da 1ª
    vão sem texto)."""
    por_item: dict[int, tuple[Linha, list[_Alvo]]] = {}
    for alvo in sorted(grupo.alvos, key=lambda alvo: alvo.referencia):
        for linha in alvo.linhas:
            por_item.setdefault(linha.numero, (linha, []))[1].append(alvo)
    numeros = sorted(por_item)
    a = _altura(grupo)
    textos = {n: f"[{n}] {ROTULO[por_item[n][0].situacao]}" for n in numeros}
    largura = max(len(t) for t in textos.values()) * LARGURA_LETRA * a
    ys = [grupo.caixa[3] - a - i * PASSO * a for i in range(len(numeros))]
    x = grupo.caixa[2] + FOLGA_COLUNA * a
    while True:
        coluna = (x, ys[-1] - MEIA_FAIXA * a, x + largura, ys[0] + MEIA_FAIXA * a)
        batem = [o for o in ocupado if _cruzam(coluna, o)]
        if not batem:
            break
        x = max(o[2] for o in batem) + FOLGA_COLUNA * a
    ocupado.append(coluna)
    saida = []
    for n, y in zip(numeros, ys, strict=True):
        linha, alvos = por_item[n]
        inicio = (x - RECUO_SETA * a, y)
        for i, alvo in enumerate(alvos):
            saida.append(Chamada(alvo.referencia, grupo.folha[0], COR[linha.situacao], a, _seta(inicio, alvo.caixa, a),
                                 LARGURA_PONTA * a, (x, y), textos[n] if i == 0 else "", (n,)))
    return saida


def caixa_do_rotulo(chamada: Chamada) -> Caixa:
    """O lugar reservado para o rótulo na coluna (para conferir que nenhum cobre outro). A seta sem
    texto tem caixa sem largura."""
    x, y = chamada.rotulo
    a = chamada.altura
    return (x, y - MEIA_FAIXA * a, x + len(chamada.texto) * LARGURA_LETRA * a, y + MEIA_FAIXA * a)
