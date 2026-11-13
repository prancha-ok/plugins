"""Rótulos das marcas numa coluna fora do desenho, com uma seta até cada marca (0.3.4; DAV-18).

0.3.4 (observações de 02/10/2026, item 2): o especialista marcou o parecer #2 da prancha real 02
pelo MCP: 77 nuvens, e "foram tantas nuvens sobre o carimbo que ali ficou extremamente confuso,
muito sobreposto". No carimbo, no quadro de áreas e onde as nuvens se amontoariam, uma seta do item
até uma chamada "[nº] SITUAÇÃO" no lugar da nuvem.

DAV-18 (call de 26/10/2026): "na marcação do desenho, o texto ficou GIGANTE; tem que estar na mesma
escala do desenho. A legenda é boa, mas também ficou grande. Ficou muito sobreposto: melhor os
rótulos ficarem do lado de fora do desenho." O rótulo da nuvem era um MTEXT do LISP ao lado dela,
com 0,15 do lado da caixa quando o marcado não é texto (a polilinha do lote de 30 m: 6,75 m de
letra), a altura do título na nuvem da região e, no quadro-resumo, 1/90 da altura do EXTMIN/EXTMAX
(a do espaço aberto: com um layout aberto, o papel em mm virava metros no modelo). Agora:
  - a altura `a` de toda marca é a do texto comum da folha (espaço e layout) onde ela vai: a mediana
    das alturas dos TEXT e MTEXT da folha que o LISP manda no `caixas` (sem a camada das marcas),
    entre 1/PISO_TEXTO e 1/TETO_TEXTO do lado maior do desenho da folha; sem texto, 1/SEM_TEXTO dele.
    Os títulos grandes não puxam a mediana (são poucos), e o papel e o modelo têm cada um a sua;
  - o LISP desenha só a nuvem (`marcar`, `regioes`); o rótulo "[nº] SITUAÇÃO: título" de cada item
    vai numa coluna FORA da extensão do desenho da folha, à direita ou à esquerda (o lado mais perto
    das marcas do item), um embaixo do outro na ordem dos números, com uma seta até cada marca dele:
    até a nuvem do handle, até a nuvem da região ou, no carimbo e no amontoado (sem nuvem), até o
    próprio item.
Por que uma coluna da folha e não uma por vista: as vistas de uma prancha ficam lado a lado e o MCP
só conhece as caixas que o motor mandou; o espaço entre elas, com notas, cotas e outras vistas, é
desconhecido, e a coluna de uma vista cairia em cima da vizinha (o "muito sobreposto" da call). Fora
da extensão de tudo, nenhum rótulo cobre o desenho; as setas cruzam o desenho (linhas finas na
camada que não plota), e as duas colunas, uma de cada lado, encurtam as setas pela metade.

Sem nuvem, só a seta (as marcas que viram chamada direta):
  1. o handle cuja caixa tem o centro dentro de uma tabela (carimbo ou quadro de áreas com caixa:
     `regiao.caixa` de qualquer item do parecer), no mesmo layout;
  2. o handle cuja nuvem se sobrepõe à de outros, num amontoado de MINIMO_AMONTOADO ou mais (a nuvem
     com a folga do LISP, pok-caixa-folgada). Só amontoam marcas de tamanho parecido (lado maior até
     RAZAO_TAMANHO vezes o da outra) em que nenhum desenho envolve a outra marca: a nuvem do lote
     (folga de 1/4 do lado maior) cobre as cotas de dentro e as de fora, e juntaria a planta de
     situação inteira num grupo só;
  3. a linha sem handle achado cuja região é uma tabela achada: a seta aponta a borda da tabela.
Os outros handles ganham nuvem; a linha sem handle achado, a nuvem de cada região achada
(servidor._marcar_no_desenho, com as regiões que nenhuma nuvem nem chamada marcou). Essas setas só
rotulam a nuvem: `itens` vazio, e o item conta como marcado pela nuvem.

As posições do desenho vêm do LISP (comando `caixas`: espaço, layout e caixa de cada handle e, por
folha, o texto comum e a extensão); nada aqui fala com o AutoCAD.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .marcas import COR, ROTULO, Linha, chave_regiao, marca_do_handle, regiao_achada

# Os tipos de região que são tabela (services/engine/.../extracao/regioes.py, TIPOS_TABELA).
TIPOS_TABELA = ("carimbo", "quadro_areas")
MODELO = ("modelo", "Model")
MINIMO_AMONTOADO = 3
# Lado maior de uma marca sobre o da outra, no máximo, para as duas amontoarem: um texto comprido e
# um número curto da mesma altura ("DORMITÓRIO 01" e "12,5", 13 e 4 caracteres: 3,25) amontoam; o
# lote (30) e a cota do lado dele (2) não.
RAZAO_TAMANHO = 4.0
# Em alturas do texto da chamada.
PASSO = 2.0  # de um rótulo ao seguinte na coluna
MEIA_FAIXA = 0.8  # o rótulo reserva 0,8a acima e abaixo do meio (a letra ocupa 0,5a): 0,4a entre dois
FOLGA_COLUNA = 4.0  # da borda do desenho ao começo dos rótulos (ou ao fim, na coluna da esquerda)
RECUO_SETA = 0.5  # a seta começa meia altura antes do rótulo (ou depois da coluna, na da esquerda)
PONTA = 1.0  # comprimento da ponta da seta (no máximo metade da seta)
LARGURA_PONTA = 0.4
LARGURA_LETRA = 0.8  # largura estimada de um caractere (as fontes do AutoCAD ficam abaixo disso)
# A altura das marcas, em frações do lado maior do desenho da folha (os mesmos números de
# pok-altura-das-marcas, no prancha_ok.lsp, para o quadro-resumo): o texto comum fica entre
# 1/PISO_TEXTO e 1/TETO_TEXTO dele; sem texto nenhum, 1/SEM_TEXTO. A1 (841 mm) com letra de 2,5 mm:
# 841/336; planta de 60 m com letra de 0,15 m: 60/400.
TETO_TEXTO = 60.0
PISO_TEXTO = 2000.0
SEM_TEXTO = 300.0
MAXIMO_ROTULO = 60  # caracteres do rótulo "[nº] SITUAÇÃO: título"
FOLGA_REGIAO = 0.02  # a folga da nuvem da região com caixa (pok-lugar-regiao: pok-folga 0.02)

Caixa = tuple[float, float, float, float]
Ponto = tuple[float, float]
Folha = tuple[str, str]  # (espaço "modelo"|"papel", layout)


@dataclass(frozen=True)
class Lugar:
    """Onde um handle está no desenho, como o LISP responde (`caixas`)."""
    handle: str
    folha: Folha
    caixa: Caixa
    altura: float | None  # altura do texto (TEXT, MTEXT, ATTRIB); None nos outros


@dataclass(frozen=True)
class InfoFolha:
    """O que o LISP diz de uma folha (`caixas`, DAV-18): o texto comum (mediana das alturas dos TEXT
    e MTEXT fora da camada das marcas, None sem texto), quantos textos entraram na conta e a
    extensão do desenho (sem a camada das marcas e sem o que está longe de tudo; None se vazia)."""
    texto: float | None
    textos: int
    extensao: Caixa | None


class Achados(dict):
    """{handle: Lugar}, e em `folhas` o InfoFolha de cada folha dos handles achados."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folhas: dict[Folha, InfoFolha] = {}


@dataclass(frozen=True)
class Tabela:
    """Carimbo ou quadro de áreas achado no desenho."""
    chave: tuple  # marcas.chave_regiao
    folha: Folha
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
    texto: str  # "[nº] SITUAÇÃO: título"; vazio: só mais uma seta do mesmo rótulo (o item tem outro lugar)
    # Os itens que a seta marca sozinha (vai ao próprio item, sem nuvem: tabela, amontoado). Vazio
    # quando ela só rotula uma nuvem (do handle ou da região): o item conta pela nuvem.
    itens: tuple[int, ...]


@dataclass
class Plano:
    nuvens: list[tuple[str, int, str]]  # (handle, cor, rótulo), como marcas.marcas_por_handle
    chamadas: list[Chamada]


@dataclass
class _Alvo:
    """Uma ponta de seta de um item: a caixa onde ela chega, na folha do handle `referencia`."""
    folha: Folha
    caixa: Caixa
    referencia: str
    direta: bool  # a seta é a marca (sem nuvem)


@dataclass
class _Rotulo:
    linha: Linha
    alvos: list[_Alvo] = field(default_factory=list)


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


def _lado_maior(c: Caixa) -> float:
    return max(c[2] - c[0], c[3] - c[1])


def _folga(c: Caixa, fracao: float) -> Caixa:
    d = fracao * _lado_maior(c)
    return (c[0] - d, c[1] - d, c[2] + d, c[3] + d)


def caixa_da_nuvem(lugar: Lugar) -> Caixa:
    """A caixa da nuvem que o LISP desenharia em volta do handle (pok-caixa-folgada): a folga é
    1/4 do lado maior ou meia altura do texto, o que for maior."""
    x0, y0, x1, y1 = lugar.caixa
    folga = max(0.25 * max(x1 - x0, y1 - y0), 0.5 * (lugar.altura or 0.0), 1e-3)
    return (x0 - folga, y0 - folga, x1 + folga, y1 + folga)


def _mediana(valores) -> float | None:
    valores = sorted(valores)
    if not valores:
        return None
    meio = len(valores) // 2
    return valores[meio] if len(valores) % 2 else (valores[meio - 1] + valores[meio]) / 2


# ---------------------------------------------------------------- o que o LISP respondeu

def lugares(resposta: list[dict]) -> Achados:
    """A resposta do `caixas` como {handle: Lugar}, com o InfoFolha de cada folha em `folhas`. O
    handle que o desenho não tem, o de dentro de um bloco (semLugar) e a linha torta ficam de fora."""
    saida = Achados()
    for linha in resposta:
        espaco, layout = linha.get("e"), linha.get("l")
        if espaco not in ("modelo", "papel") or not isinstance(layout, str):
            continue
        a = linha.get("a")
        a = float(a) if _numero(a) and a > 0 else None
        if linha.get("folha") is True:
            n = linha.get("n")
            saida.folhas[(espaco, layout)] = InfoFolha(a, n if isinstance(n, int) and n >= 0 else 0,
                                                       _caixa(linha.get("ext")))
            continue
        h, caixa = linha.get("h"), _caixa(linha.get("c"))
        if isinstance(h, str) and h and caixa:
            saida[h] = Lugar(h, (espaco, layout), caixa, a)
    return saida


def handles_das_regioes(p: dict) -> list[str]:
    """Os títulos das regiões do parecer (todas: tabelas e vistas, de todos os itens): o `caixas`
    diz em que layout cada uma está, para a tabela tirar a nuvem do que está dentro dela e a coluna
    de fora apontar a nuvem da região."""
    saida: list[str] = []
    for item in p.get("itens") or []:
        outras = item.get("outrasRegioes") if isinstance(item.get("outrasRegioes"), list) else []
        for r in [item.get("regiao"), *outras]:
            achada = regiao_achada(r)
            if achada and achada["handleTitulo"] and achada["handleTitulo"] not in saida:
                saida.append(achada["handleTitulo"])
    return saida


# O servidor pede os títulos por este nome (0.3.4, quando só as tabelas importavam).
handles_das_tabelas = handles_das_regioes


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
            saida.append(Tabela(chave_regiao(achada), MODELO, caixa, "", True))
    return saida


def lugar_da_regiao(regiao: dict, achados: dict[str, Lugar]) -> tuple[Folha, Caixa, str] | None:
    """(folha, caixa da nuvem, handle de referência) de uma região achada (marcas.regiao_achada), como
    o LISP a acha e a nuvem dela (pok-lugar-regiao): título achado, no layout dele, a caixa da região
    com folga de 2% ou, sem caixa, a nuvem do título; sem o título, a caixa vale no modelo."""
    titulo = achados.get(regiao["handleTitulo"]) if regiao["handleTitulo"] else None
    caixa = tuple(regiao["caixa"]) if regiao["caixa"] else None
    if titulo:
        return titulo.folha, _folga(caixa, FOLGA_REGIAO) if caixa else caixa_da_nuvem(titulo), titulo.handle
    if caixa and regiao["espaco"] != "papel":
        return MODELO, _folga(caixa, FOLGA_REGIAO), ""
    return None


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
    """Divide as marcas dos handles entre nuvens e setas diretas e põe o rótulo de cada item (com as
    setas até as marcas dele) na coluna de fora do desenho da folha."""
    por_handle: dict[str, list[Linha]] = {}
    for linha in linhas:
        for h in linha.handles:
            if h in achados:
                por_handle.setdefault(h, []).append(linha)

    soltos = [h for h in por_handle
              if not any(t.contem and t.folha == achados[h].folha and _dentro(_centro(achados[h].caixa), t.caixa)
                         for t in tabelas_achadas)]
    em_amontoado = {h for g in _amontoados(soltos, achados) for h in g}
    nuvens = [h for h in soltos if h not in em_amontoado]
    com_nuvem = set(nuvens)

    por_chave = {t.chave: t for t in tabelas_achadas}
    rotulos: dict[tuple[Folha, int], _Rotulo] = {}

    def alvo(linha: Linha, a: _Alvo) -> None:
        rotulos.setdefault((a.folha, linha.numero), _Rotulo(linha)).alvos.append(a)

    for linha in linhas:
        handles = [h for h in linha.handles if h in achados]
        tabela = por_chave.get(chave_regiao(linha.regiao)) if linha.regiao else None
        if handles:
            for h in handles:
                lugar = achados[h]
                if h in com_nuvem:
                    alvo(linha, _Alvo(lugar.folha, caixa_da_nuvem(lugar), h, False))
                else:
                    alvo(linha, _Alvo(lugar.folha, lugar.caixa, h, True))
        elif tabela:
            alvo(linha, _Alvo(tabela.folha, tabela.caixa, tabela.referencia, True))
        else:
            # Sem handle: a nuvem de cada região achada (servidor); a seta só a rotula.
            for regiao in linha.regioes:
                if achada := lugar_da_regiao(regiao, achados):
                    alvo(linha, _Alvo(achada[0], achada[1], achada[2], False))

    plano = Plano(nuvens=[marca_do_handle(h, por_handle[h]) for h in nuvens], chamadas=[])
    folhas = list(dict.fromkeys(folha for folha, _ in rotulos))
    for folha in folhas:
        da_folha = sorted((r for (f, _), r in rotulos.items() if f == folha), key=lambda r: r.linha.numero)
        desenho = extensao(folha, achados, tabelas_achadas, [a for r in da_folha for a in r.alvos])
        plano.chamadas += _colunas(folha, da_folha, desenho, altura_do_texto(folha, achados, desenho))
    return plano


def extensao(folha: Folha, achados: dict[str, Lugar], tabelas_achadas: list[Tabela], alvos: list[_Alvo]) -> Caixa:
    """O desenho da folha: a extensão que o LISP mediu, mais tudo o que se conhece nela (handles
    achados, tabelas, as nuvens e regiões que as setas apontam)."""
    info = getattr(achados, "folhas", {}).get(folha)
    caixas = [lugar.caixa for lugar in achados.values() if lugar.folha == folha]
    caixas += [t.caixa for t in tabelas_achadas if t.folha == folha] + [a.caixa for a in alvos]
    if info and info.extensao:
        caixas.append(info.extensao)
    return _uniao(caixas)


def altura_do_texto(folha: Folha, achados: dict[str, Lugar], desenho: Caixa) -> float:
    """A altura das marcas na folha: o texto comum (o do LISP; sem texto solto na folha, a mediana
    dos textos achados nela, como os atributos do carimbo), entre 1/PISO_TEXTO e 1/TETO_TEXTO do
    lado maior do desenho; sem texto nenhum, 1/SEM_TEXTO dele."""
    info = getattr(achados, "folhas", {}).get(folha)
    texto = info.texto if info and info.textos and info.texto else None
    if texto is None:
        texto = _mediana(lugar.altura for lugar in achados.values() if lugar.folha == folha and lugar.altura)
    lado = max(_lado_maior(desenho), 1e-3)
    if texto is None:
        return lado / SEM_TEXTO
    return min(max(texto, lado / PISO_TEXTO), lado / TETO_TEXTO)


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


def texto_do_rotulo(linha: Linha) -> str:
    texto = f"[{linha.numero}] {ROTULO[linha.situacao]}: {linha.titulo}"
    return texto if len(texto) <= MAXIMO_ROTULO else texto[: MAXIMO_ROTULO - 3] + "..."


def _colunas(folha: Folha, rotulos: list[_Rotulo], desenho: Caixa, a: float) -> list[Chamada]:
    """Os rótulos da folha (na ordem dos números) em duas colunas fora do desenho: à direita os
    itens cujas marcas estão na metade direita, à esquerda os outros. Cada coluna começa no alto do
    desenho, a FOLGA_COLUNA alturas da borda, um rótulo a cada PASSO alturas (desce além do desenho
    se precisar: continua fora dele). A seta sai do lado da coluna que dá para o desenho, na altura
    do rótulo (na da esquerda, depois do rótulo mais comprido: nenhuma seta passa por outro rótulo),
    até o ponto mais perto de cada alvo; as setas além da 1ª vão sem texto."""
    meio = _centro(desenho)[0]
    lado = [_centro(_uniao(alvo.caixa for alvo in r.alvos))[0] >= meio for r in rotulos]
    direita = [r for r, d in zip(rotulos, lado, strict=True) if d]
    esquerda = [r for r, d in zip(rotulos, lado, strict=True) if not d]
    saida: list[Chamada] = []
    for coluna, a_direita in ((direita, True), (esquerda, False)):
        if not coluna:
            continue
        textos = [texto_do_rotulo(r.linha) for r in coluna]
        largura = max(len(t) for t in textos) * LARGURA_LETRA * a
        x = desenho[2] + FOLGA_COLUNA * a if a_direita else desenho[0] - FOLGA_COLUNA * a - largura
        for i, (r, texto) in enumerate(zip(coluna, textos, strict=True)):
            y = desenho[3] - a - i * PASSO * a
            inicio = (x - RECUO_SETA * a, y) if a_direita else (x + largura + RECUO_SETA * a, y)
            for j, alvo in enumerate(r.alvos):
                saida.append(Chamada(alvo.referencia, folha[0], COR[r.linha.situacao], a, _seta(inicio, alvo.caixa, a),
                                     LARGURA_PONTA * a, (x, y), texto if j == 0 else "",
                                     (r.linha.numero,) if alvo.direta else ()))
    return saida


def caixa_do_rotulo(chamada: Chamada) -> Caixa:
    """O lugar reservado para o rótulo na coluna (para conferir que nenhum cobre outro). A seta sem
    texto tem caixa sem largura."""
    x, y = chamada.rotulo
    a = chamada.altura
    return (x, y - MEIA_FAIXA * a, x + len(chamada.texto) * LARGURA_LETRA * a, y + MEIA_FAIXA * a)
