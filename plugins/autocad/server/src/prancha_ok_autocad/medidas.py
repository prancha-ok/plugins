"""Medir o desenho antes do parecer (`medir_prancha`, 0.3.0).

Rodada 3, ponto 4.1 das observações de 01/10/2026: "rodei no MCP e os números não alteraram".
O assistente media depois do parecer e as medidas não voltavam a ele. Agora mede antes: lê do
desenho aberto (a leitura do AutoCAD, formato do comando `ler` do prancha_ok.lsp) o que o parecer
costuma pedir, devolve uma PROPOSTA com os handles de onde cada valor saiu, o responsável técnico
confirma e o `enviar_prancha` manda só os valores confirmados (`respostas`), que entram já no
primeiro parecer.

Entidade (uma por dicionário): h handle, t tipo, c camada, e espaço (modelo/papel/bloco), x texto,
p pontos [[x, y], ...], a altura do texto, m medida da cota, f polilinha fechada, b nome do bloco.

O que se mede, sempre como proposta (nada aqui decide sozinho):
- terreno: o contorno fechado (polilinha ou traços que se fecham) que contém a área do lote
  escrita e tem essa área, como o motor faz; sem ela, o único contorno numa camada de lote
  (LOTE, DIVISA...) com a edificação dentro; senão, não propõe. Área e lados; a frente é o
  lado mais perto de um nome de rua (RUA, AV., ESTRADA...) fora do lote;
- edificação: a maior polilinha fechada dentro do lote (de preferência numa camada de projeção,
  edificação, construção, cobertura); área de projeção e afastamentos aos lados do lote (frente,
  fundos e o menor lateral, num lote de quatro lados);
- pavimentos: os títulos distintos das plantas de pavimento (térreo, 1º pavimento, subsolo...);
- altura: a diferença entre o maior e o menor nível escrito (+0,00, +7,10);
- áreas escritas no quadro: térreo, cada pavimento, total construída, projeção, terreno;
- vagas: o total escrito ("VAGAS: 2"), as vagas numeradas ("VAGA 01") ou os blocos de carro.

Os campos (`campo`) são os do formulário do Prancha Ok que o envio aceita (backend:
cliente.CAMPOS_MEDIDOS). O que não tem campo (os lados, as áreas dos outros pavimentos) vai só
para mostrar.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

Ponto = tuple[float, float]

ESCALAS = {"m": 1.0, "cm": 0.01, "mm": 0.001}
ROTULOS = {
    "area_terreno": ("Área do terreno", "m²"),
    "testada_lote_m": ("Testada (frente do lote)", "m"),
    "area_projecao_m2": ("Área de projeção da edificação", "m²"),
    "AC": ("Área total construída", "m²"),
    "area_pavimento_terreo_m2": ("Área do pavimento térreo", "m²"),
    "NPC": ("Nº de pavimentos", ""),
    "altura_edificacao_hmax_m": ("Altura da edificação", "m"),
    "afastamento_frontal_projeto_m": ("Afastamento frontal", "m"),
    "afastamento_lateral_projeto_m": ("Afastamento lateral (o menor)", "m"),
    "afastamento_fundos_projeto_m": ("Afastamento de fundos", "m"),
    "n_vagas_previstas": ("Vagas de garagem previstas", ""),
}
CAMPOS = tuple(ROTULOS)

_CAMADA_LOTE = re.compile(r"LOTE|TERRENO|DIVISA|LIMITE|PERIMETRO|GLEBA")
# Camada com "TERRENO" no nome que não é o lote: curva de nível (prancha real), texto, cota, hachura.
_CAMADA_NAO_LOTE = re.compile(r"CURVA|TEXTO|COTA|HACH|NIVEL|TOPO")
_ROTULO_LOTE = re.compile(r"\b(LOTE|TERRENO)\b")
_AREA_M2 = re.compile(r"(\d{1,3}(?:\.\d{3})+,\d{1,2}|\d+[.,]\d{1,2})\s*M2")
_CAMADA_EDIFICACAO = re.compile(r"PROJE|EDIFIC|CONSTRU|COBERT|TELHADO|CASA|PAVIMENTO|ALVENARIA|PAREDE")
_RUA = re.compile(r"(^|[^A-Z])(RUA|R\.|AVENIDA|AV\.?|ESTRADA|ESTR\.|TRAVESSA|TV\.|RODOVIA|ALAMEDA|PRACA|"
                  r"LOGRADOURO|BECO|LADEIRA)( |$)")
_PAVIMENTO = re.compile(r"\b(TERREO|PAVIMENTO|PAV\.?|SUBSOLO|MEZANINO|SOTAO|PILOTIS|SEMI ?-?ENTERRADO)\b")
_NAO_E_PAVIMENTO = re.compile(r"SITUACAO|LOCALIZACAO|LOCACAO|COBERTURA|TELHADO|FUNDAC|ESTRUTUR|FORMA|CORTE|FACHADA")
_NIVEL = re.compile(r"^(?:NIVEL|NV|N\.?A\.?|COTA|EL)?\.?\s*:?\s*([+-]\s?\d{1,3}[.,]\d{2,3})\s*M?$")
_NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+|\d+,\d+|\d+\.\d+|\d+")
_VAGA_NUMERADA = re.compile(r"^VAGA\s*(?:N[O°]?\.?\s*)?0*(\d{1,3})$")
_TOTAL_VAGAS = re.compile(r"(?:N[O°]?\.?\s*(?:DE\s+)?VAGAS|TOTAL\s+DE\s+VAGAS|VAGAS)\s*[:=-]?\s*(\d{1,3})\b|"
                          r"\b(\d{1,3})\s+VAGAS\b")
_BLOCO_CARRO = re.compile(r"VAGA|CARRO|AUTOMOVEL|VEICULO|\bAUTO\b")

# Como o motor (services/engine, extracao/lote.py): dois traços do lote se ligam a até 2 cm; o lote
# tem de 100 a 5000 m²; a área escrita confirma o contorno a até 5%; "LOTE"/"TERRENO" a até 8
# alturas do texto da área.
TOLERANCIA_JUNTA_M = 0.02
CONECTOR_FAIXA_M = 0.3
AREA_MINIMA_LOTE_M2, AREA_MAXIMA_LOTE_M2 = 100, 5000
TOLERANCIA_AREA_ESCRITA = 0.05
RAIO_ROTULO_LOTE_ALTURAS = 8
MAXIMO_HANDLES = 5


def normal(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.replace("º", "O").split()).upper()


def numero(texto: str) -> float | None:
    """Primeiro número escrito: "1.234,56" (milhar com ponto), "223,20" ou "223.20"."""
    m = _NUMERO.search(texto)
    if not m:
        return None
    bruto = m.group(0)
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    try:
        return float(bruto)
    except ValueError:
        return None


@dataclass
class Proposta:
    campo: str | None
    rotulo: str
    unidade: str
    valor: float
    como: str
    handles: list[str] = field(default_factory=list)

    def para_o_chat(self) -> dict:
        saida = {"rotulo": self.rotulo, "valor": self.valor, "unidade": self.unidade, "como": self.como,
                 "handles": self.handles[:MAXIMO_HANDLES]}
        return {"campo": self.campo, **saida} if self.campo else saida


def _pontos(e: dict) -> list[Ponto]:
    saida = []
    for p in e.get("p") or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2 and all(isinstance(c, (int, float)) for c in p[:2]):
            saida.append((float(p[0]), float(p[1])))
    return saida


def _texto(e: dict) -> str:
    return normal(str(e.get("x") or ""))


def _arestas(poligono: list[Ponto]) -> list[tuple[Ponto, Ponto]]:
    """Os lados do polígono fechado: cada vértice com o seguinte (o último com o primeiro)."""
    return list(zip(poligono, poligono[1:] + poligono[:1], strict=True))


def _area(poligono: list[Ponto]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in _arestas(poligono))) / 2


def _dentro(p: Ponto, poligono: list[Ponto]) -> bool:
    x, y = p
    dentro = False
    for (x1, y1), (x2, y2) in _arestas(poligono):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


def _dist_segmento(p: Ponto, a: Ponto, b: Ponto) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    comprimento2 = dx * dx + dy * dy
    t = 0.0 if comprimento2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / comprimento2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _dist_poligono_lado(poligono: list[Ponto], a: Ponto, b: Ponto) -> float:
    """Menor distância entre o contorno do polígono e o segmento a-b."""
    arestas = _arestas(poligono)
    return min(min(_dist_segmento(p, a, b) for p in poligono),
               min(_dist_segmento(q, c, d) for c, d in arestas for q in (a, b)))


def _sem_repetidos(poligono: list[Ponto]) -> list[Ponto]:
    saida: list[Ponto] = []
    for p in poligono:
        if not saida or math.dist(p, saida[-1]) > 1e-9:
            saida.append(p)
    if len(saida) > 1 and math.dist(saida[0], saida[-1]) <= 1e-9:
        saida.pop()
    return saida


def _juntar_colineares(poligono: list[Ponto], graus: float = 3.0) -> list[Ponto]:
    """Tira os vértices no meio de um lado reto (o lado desenhado em dois traços)."""
    pontos = list(poligono)
    mudou = True
    while mudou and len(pontos) > 3:
        mudou = False
        for i in range(len(pontos)):
            a, b, c = pontos[i - 1], pontos[i], pontos[(i + 1) % len(pontos)]
            v1 = math.atan2(b[1] - a[1], b[0] - a[0])
            v2 = math.atan2(c[1] - b[1], c[0] - b[0])
            if abs(math.degrees(math.remainder(v2 - v1, 2 * math.pi))) < graus:
                del pontos[i]
                mudou = True
                break
    return pontos


# ---------------------------------------------------------------- terreno

@dataclass
class Contorno:
    pontos: list[Ponto]
    handles: list[str]
    camada: str


def _contornos(entidades: list[dict], tolerancia: float) -> list[Contorno]:
    """Contornos fechados do model space: as polilinhas fechadas e, camada por camada, os traços
    abertos (LINE, LWPOLYLINE, SPLINE pelos pontos de ajuste) ligados ponta com ponta."""
    fechados, abertos = [], {}
    for e in entidades:
        if e.get("e") != "modelo" or e.get("t") not in ("LWPOLYLINE", "LINE", "SPLINE"):
            continue
        camada = normal(str(e.get("c") or ""))
        pontos = _pontos(e)
        if e.get("t") == "LWPOLYLINE" and e.get("f") and len(pontos) >= 3:
            pontos = _sem_repetidos(pontos)
            fechados.append(Contorno(pontos, [str(e.get("h"))], camada))
            fechados += [Contorno(volta, [str(e.get("h"))], camada) for volta in _voltas_da_faixa(pontos, tolerancia)]
        elif len(pontos) >= 2:
            abertos.setdefault(camada, []).append((pontos, str(e.get("h"))))
    return fechados + [c for camada, pecas in abertos.items() for c in _fechar(pecas, camada, tolerancia)]


def _voltas_da_faixa(pontos: list[Ponto], tolerancia: float) -> list[list[Ponto]]:
    """Lote desenhado como faixa (prancha real 02, como no motor): uma polilinha fechada com a
    volta de fora e a de dentro ligadas por dois trechos curtos (até 30 cm). Cada volta é um
    contorno candidato. [] se não for faixa."""
    n = len(pontos)
    conector = CONECTOR_FAIXA_M / TOLERANCIA_JUNTA_M * tolerancia  # 30 cm na unidade do desenho
    curtos = [i for i in range(n) if math.dist(pontos[i], pontos[(i + 1) % n]) < conector]
    if len(curtos) != 2:
        return []
    a, b = curtos
    voltas = [pontos[a + 1:b + 1], pontos[b + 1:] + pontos[:a + 1]]
    if not all(len(v) >= 3 for v in voltas):
        return []
    maior, menor = sorted(voltas, key=_area, reverse=True)
    return voltas if all(_dentro(q, maior) for q in menor) else []


def _fechar(pecas: list[tuple[list[Ponto], str]], camada: str, tolerancia: float) -> list[Contorno]:
    """Liga os traços pela ponta (como o lote do desenho sintético: LINE + LWPOLYLINE + LINE)."""
    restantes = list(pecas)
    saida = []
    while restantes:
        pontos, handle = restantes.pop(0)
        cadeia, handles = list(pontos), [handle]
        achou = True
        while achou and math.dist(cadeia[0], cadeia[-1]) > tolerancia:
            achou = False
            for i, (outros, h) in enumerate(restantes):
                if math.dist(cadeia[-1], outros[0]) <= tolerancia:
                    cadeia += outros[1:]
                elif math.dist(cadeia[-1], outros[-1]) <= tolerancia:
                    cadeia += list(reversed(outros))[1:]
                else:
                    continue
                handles.append(h)
                restantes.pop(i)
                achou = True
                break
        if len(cadeia) >= 4 and math.dist(cadeia[0], cadeia[-1]) <= tolerancia:
            saida.append(Contorno(_sem_repetidos(cadeia), handles, camada))
    return saida


def _areas_do_lote_escritas(entidades: list[dict]) -> list[tuple[Ponto, float, str]]:
    """Área do lote escrita no model space ("ÁREA DO LOTE: 360,00 m²", ou "409,89 m²" com "LOTE"
    ou "TERRENO" a até 8 alturas): (ponto do texto, valor, handle). Como o motor
    (services/engine, extracao/lote.py)."""
    textos = [e for e in entidades if e.get("e") == "modelo" and e.get("t") in ("TEXT", "MTEXT", "ATTRIB")
              and e.get("x") and _pontos(e)]
    rotulos = [_pontos(e)[0] for e in textos if _ROTULO_LOTE.search(_texto(e))]
    saida = []
    for e in textos:
        ponto, t = _pontos(e)[0], _texto(e)
        raio = RAIO_ROTULO_LOTE_ALTURAS * float(e.get("a") or 0)
        if not (_ROTULO_LOTE.search(t) or any(math.dist(r, ponto) <= raio for r in rotulos)):
            continue
        for bruto in _AREA_M2.findall(t):
            if (valor := numero(bruto)) and valor > 0:
                saida.append((ponto, valor, str(e.get("h"))))
    return saida


def _area_do_terreno_no_quadro(entidades: list[dict]) -> list[tuple[float, list[str]]]:
    """"ÁREA DO TERRENO" (ou do lote) com o valor no texto ou à direita: (valor, handles)."""
    textos = _textos(entidades)
    saida = []
    for e in textos:
        t = _texto(e)
        if re.match(r"AREA (DO |DE )?(TERRENO|LOTE)\b", t) and (achado := _valor_ao_lado(e, textos)):
            saida.append((achado[0], sorted({str(e.get("h")), achado[1]})))
    return saida


def _escolher_lote(candidatos: list[Contorno], entidades: list[dict], escala: float
                   ) -> tuple[Contorno, str, list[str]] | None:
    """O lote, com o porquê e os handles do que o confirma: o contorno que contém a área do lote
    escrita e tem essa área (a até 5%); senão, o único com a área do terreno escrita no quadro;
    senão, o único contorno numa camada de lote (LOTE, DIVISA...; não curva de nível, texto ou
    cota) com a edificação dentro. Sem nenhum dos dois,
    None: melhor não propor que propor a curva de nível ou a moldura da legenda."""
    ancorados = []
    for contorno in candidatos:
        area = _area(contorno.pontos) * escala ** 2
        for ponto, valor, handle in _areas_do_lote_escritas(entidades):
            diferenca = abs(area - valor) / valor
            if diferenca <= TOLERANCIA_AREA_ESCRITA and _dentro(ponto, contorno.pontos):
                ancorados.append((diferenca, contorno, valor, handle))
    if ancorados:
        _d, contorno, valor, handle = min(ancorados, key=lambda x: x[0])
        return contorno, f"contorno com a área do lote escrita dentro dele ({valor:.2f} m²)", [handle]
    # A área do terreno do quadro (na folha): vale o único contorno com essa área (a até 5%).
    for valor, handles in _area_do_terreno_no_quadro(entidades):
        iguais = [c for c in candidatos
                  if abs(_area(c.pontos) * escala ** 2 - valor) / valor <= TOLERANCIA_AREA_ESCRITA]
        if len({tuple(c.handles) for c in iguais}) == 1:
            return iguais[0], f"contorno com a área do terreno escrita no quadro ({valor:.2f} m²)", handles
    pela_camada = [c for c in candidatos if _CAMADA_LOTE.search(c.camada) and not _CAMADA_NAO_LOTE.search(c.camada)
                   and _edificacoes(entidades, c)]
    if len(pela_camada) == 1:
        return pela_camada[0], f"contorno na camada {pela_camada[0].camada}, com a edificação dentro", []
    return None


def _no_lote(p: Ponto, lote: list[Ponto]) -> bool:
    """Dentro do lote ou em cima da divisa (edificação encostada, afastamento zero)."""
    return _dentro(p, lote) or min(_dist_segmento(p, a, b) for a, b in _arestas(lote)) <= 1e-3


def _edificacoes(entidades: list[dict], contorno: Contorno) -> list[Contorno]:
    """Polilinhas fechadas dentro do lote (ou encostadas na divisa), de 2% da área dele para cima."""
    lote, area_lote = contorno.pontos, _area(contorno.pontos)
    saida = []
    for e in entidades:
        if (e.get("e") != "modelo" or e.get("t") != "LWPOLYLINE" or not e.get("f")
                or str(e.get("h")) in contorno.handles):
            continue
        camada = normal(str(e.get("c") or ""))
        pontos = _sem_repetidos(_pontos(e))
        if len(pontos) < 3 or _CAMADA_NAO_LOTE.search(camada):
            continue
        if all(_no_lote(p, lote) for p in pontos) and 0.02 * area_lote <= _area(pontos) < area_lote:
            saida.append(Contorno(pontos, [str(e.get("h"))], camada))
    return saida


def _frente(lote: list[Ponto], entidades: list[dict]) -> tuple[int, str] | None:
    """O lado do lote mais perto de um nome de rua escrito fora dele: (índice do lado, handle)."""
    lados = _arestas(lote)
    maior = max(math.dist(a, b) for a, b in lados)
    melhor = None
    for e in entidades:
        if e.get("e") != "modelo" or e.get("t") not in ("TEXT", "MTEXT") or not _RUA.search(_texto(e)):
            continue
        pontos = _pontos(e)
        if not pontos or _dentro(pontos[0], lote):
            continue
        distancias = [_dist_segmento(pontos[0], a, b) for a, b in lados]
        d = min(distancias)
        if d <= maior and (melhor is None or d < melhor[0]):
            melhor = (d, distancias.index(d), str(e.get("h")))
    return (melhor[1], melhor[2]) if melhor else None


def _paralelo(a: tuple[Ponto, Ponto], b: tuple[Ponto, Ponto], graus: float = 30.0) -> bool:
    ang = lambda s: math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])  # noqa: E731
    diferenca = abs(math.degrees(math.remainder(ang(a) - ang(b), math.pi)))
    return diferenca < graus


def _arred(valor: float) -> float:
    return round(valor + 0.0, 2)


def _achar_lote(entidades: list[dict], escala: float) -> tuple[Contorno, str, list[str]] | None:
    candidatos = [c for c in _contornos(entidades, TOLERANCIA_JUNTA_M / escala)
                  if AREA_MINIMA_LOTE_M2 < _area(c.pontos) * escala ** 2 < AREA_MAXIMA_LOTE_M2]
    return _escolher_lote(candidatos, entidades, escala)


def _terreno(entidades: list[dict], escala: float, propostas: list[Proposta], saida: dict) -> None:
    escolhido = _achar_lote(entidades, escala)
    if escolhido is None:
        saida["naoMedido"].append("terreno: não achei o lote com certeza (nem a área do lote escrita dentro de um "
                                  "contorno, nem uma camada de lote com a edificação dentro); pergunte a área")
        for unidade, outra in ESCALAS.items():
            if outra != escala and _achar_lote(entidades, outra) is not None:
                saida["avisos"].append(f"Com o desenho em {unidade}, o lote aparece: confirme a unidade com a pessoa "
                                       f"e meça de novo com unidade=\"{unidade}\".")
                break
        return
    contorno, porque, confirmam = escolhido
    edificacoes = _edificacoes(entidades, contorno)
    lote = _juntar_colineares(contorno.pontos)
    area = _arred(_area(lote) * escala ** 2)
    lados = _arestas(lote)
    propostas.append(Proposta("area_terreno", *ROTULOS["area_terreno"], area, porque, [*contorno.handles, *confirmam]))
    frente = _frente(lote, entidades)
    saida["lote"] = {
        "lados": [{"lado": i + 1, "comprimento": _arred(math.dist(a, b) * escala),
                   **({"frente": True} if frente and frente[0] == i else {})} for i, (a, b) in enumerate(lados)],
        "handles": contorno.handles[:MAXIMO_HANDLES],
    }
    if frente is None:
        saida["naoMedido"].append("testada e afastamentos: nenhum nome de rua (RUA, AV., ESTRADA...) perto do lote; "
                                  "pergunte qual lado é a frente")
    else:
        i, handle_rua = frente
        a, b = lados[i]
        propostas.append(Proposta("testada_lote_m", *ROTULOS["testada_lote_m"], _arred(math.dist(a, b) * escala),
                                  f"lado {i + 1} do lote, o mais perto do nome da rua",
                                  [*contorno.handles, handle_rua]))
    if not edificacoes:
        saida["naoMedido"].append("projeção e afastamentos: nenhuma polilinha fechada dentro do lote")
        return
    preferidas = [e for e in edificacoes if _CAMADA_EDIFICACAO.search(e.camada)]
    maior = max(preferidas or edificacoes, key=lambda c: _area(c.pontos))
    # Sem camada que diga, só a maior; com ela, todas as partes (paredes, blocos da casa): o
    # afastamento é da parte mais perto de cada lado.
    partes = [p for p in preferidas if p is maior or not all(_no_lote(q, maior.pontos) for q in p.pontos)] or [maior]
    if len(partes) == 1:
        como = f"maior polilinha fechada dentro do lote (camada {maior.camada})"
        if not preferidas:
            como += "; a camada não diz que é a edificação, confirme"
        propostas.append(Proposta("area_projecao_m2", *ROTULOS["area_projecao_m2"],
                                  _arred(_area(maior.pontos) * escala ** 2), como, maior.handles))
    else:
        # Prancha real 02: a casa em várias polilinhas (paredes, a projeção do pavimento de cima);
        # a maior delas tinha 36 m² de uma projeção de 150 m².
        saida["naoMedido"].append(f"projeção: a edificação está em {len(partes)} polilinhas separadas; pergunte a "
                                  "área (ou use a do quadro)")
    if frente is None:
        return
    distancias = [min(_dist_poligono_lado(p.pontos, a, b) for p in partes) * escala for a, b in lados]
    handles = [h for p in partes for h in p.handles][:MAXIMO_HANDLES - 1] + contorno.handles[:1]
    de_onde = "camada " + ", ".join(sorted({p.camada for p in partes}))
    i = frente[0]
    propostas.append(Proposta("afastamento_frontal_projeto_m", *ROTULOS["afastamento_frontal_projeto_m"],
                              _arred(distancias[i]), f"da edificação ({de_onde}) ao lado {i + 1} (frente)", handles))
    opostos = [j for j in range(len(lados)) if j != i and _paralelo(lados[j], lados[i])]
    if len(lados) != 4 or len(opostos) != 1:
        saida["naoMedido"].append("afastamentos laterais e de fundos: o lote não tem quatro lados; veja as "
                                  "distâncias por lado em `afastamentosPorLado`")
    else:
        fundos = opostos[0]
        laterais = [j for j in range(4) if j not in (i, fundos)]
        lateral = min(laterais, key=lambda j: distancias[j])
        propostas.append(Proposta("afastamento_fundos_projeto_m", *ROTULOS["afastamento_fundos_projeto_m"],
                                  _arred(distancias[fundos]),
                                  f"da edificação ({de_onde}) ao lado {fundos + 1} (fundos)", handles))
        propostas.append(Proposta("afastamento_lateral_projeto_m", *ROTULOS["afastamento_lateral_projeto_m"],
                                  _arred(distancias[lateral]),
                                  f"da edificação ({de_onde}) ao lado {lateral + 1} (lateral)",
                                  handles))
    saida["afastamentosPorLado"] = [{"lado": j + 1, "distancia": _arred(d)} for j, d in enumerate(distancias)]


# ---------------------------------------------------------------- textos

_CODIGO_MTEXT = re.compile(r"\\[ACcFfHhQqTtWwpi][^;\\{}]*;|\\[LlOoKk~]")


def limpar_mtext(bruto: str) -> list[str]:
    """As linhas do MTEXT sem a formatação ("{\\fArial|b0;ÁREA}\\PTP = 78%" -> ["ÁREA", "TP = 78%"]),
    como o motor (services/engine, extracao/entidades_cad.limpar_mtext)."""
    texto = re.sub(r"\\S([^;^/#]*)[\^/#]([^;]*);", lambda m: m.group(1) + m.group(2), bruto.replace("\\P", "\n"))
    texto = _CODIGO_MTEXT.sub("", texto).replace("{", "").replace("}", "")
    return [linha for linha in (" ".join(t.split()) for t in texto.split("\n")) if linha]


def _textos(entidades: list[dict]) -> list[dict]:
    """Os textos da folha e do model space, uma linha por item (o memorial é um MTEXT de várias)."""
    saida = []
    for e in entidades:
        if e.get("e") not in ("modelo", "papel") or e.get("t") not in ("TEXT", "MTEXT", "ATTRIB") or not e.get("x") \
                or not _pontos(e):
            continue
        linhas = limpar_mtext(str(e["x"])) if e.get("t") == "MTEXT" else [str(e["x"])]
        saida += [{**e, "x": linha} for linha in linhas]
    return saida


def _pavimentos(textos: list[dict], propostas: list[Proposta]) -> None:
    titulos: dict[str, list[str]] = {}
    for e in textos:
        t = _texto(e)
        if not t.startswith("PLANTA") or not _PAVIMENTO.search(t) or _NAO_E_PAVIMENTO.search(t):
            continue
        chave = re.sub(r"\bESC(ALA)?\b.*$", "", t)
        chave = re.sub(r"\b(PLANTA|BAIXA|DO|DA|DE|PAVIMENTO|PAV)\b|[^A-Z0-9]", "", chave) or "PAVIMENTO"
        titulos.setdefault(chave, []).append(str(e.get("h")))
    if titulos:
        handles = [h for hs in titulos.values() for h in hs]
        propostas.append(Proposta("NPC", *ROTULOS["NPC"], float(len(titulos)),
                                  f"{len(titulos)} títulos distintos de planta de pavimento", handles))


# Mais que isso entre o menor e o maior nível: altitudes misturadas com níveis relativos.
ALTURA_MAXIMA = 100.0


def _altura(textos: list[dict], propostas: list[Proposta], saida: dict) -> None:
    niveis = []
    for e in textos:
        m = _NIVEL.match(_texto(e))
        if m and (valor := numero(m.group(1).replace(" ", ""))) is not None:
            niveis.append((-valor if m.group(1).strip().startswith("-") else valor, str(e.get("h"))))
    if len({v for v, _ in niveis}) < 2:
        return
    alto, baixo = max(niveis), min(niveis)
    if alto[0] - baixo[0] > ALTURA_MAXIMA:
        saida["naoMedido"].append("altura: os níveis escritos misturam altitude e nível relativo; diga a altura")
        return
    if alto[0] - baixo[0] < 2.0:
        return
    propostas.append(Proposta("altura_edificacao_hmax_m", *ROTULOS["altura_edificacao_hmax_m"],
                              _arred(alto[0] - baixo[0]),
                              f"do menor nível escrito ({baixo[0]:+.2f}) ao maior ({alto[0]:+.2f}); confira se são a "
                              "base e o topo da edificação", [alto[1], baixo[1]]))


_ORDINAL = re.compile(r"\b\d+\s*O\b\.?")


def _area_escrita(texto: str) -> float | None:
    """A área escrita no texto: número com casas decimais ou inteiro de 10 para cima (o "1" de
    "1º PAVIMENTO" e o "2" de "2 PAVIMENTOS" não são área)."""
    partes = re.split(r"[:=]", _ORDINAL.sub(" ", texto), maxsplit=1)
    # Com ":" ou "=", o valor vem depois ("07 - ÁREA TOTAL DE PROJEÇÃO: 149,80m²", prancha real 02).
    for m in _NUMERO.finditer(partes[-1]):
        v = numero(m.group(0))
        if v is not None and (re.search(r"[.,]\d", m.group(0)) or v >= 10):
            return v
    return None


# Até quantas alturas de letra à direita do rótulo o valor pode estar, na mesma linha da tabela: no
# carimbo da prancha real 02, "07 - ÁREA TOTAL DE PROJEÇÃO:" (altura 2,0) tem o "149,80m²" a 144,6.
DISTANCIA_DO_VALOR = 100


def _meio_da_linha(e: dict) -> float:
    """A altura do meio da primeira linha do texto: o MTEXT guarda o canto de cima; o TEXT e o
    ATTRIB, o pé da linha de base (o rótulo em MTEXT e o valor em TEXT ficam 2,5 unidades
    desalinhados no ponto, mas na mesma linha da tabela)."""
    _x, y = _pontos(e)[0]
    altura = float(e.get("a") or 1.0)
    return y - altura / 2 if e.get("t") == "MTEXT" else y + altura / 2


def _valor_ao_lado(rotulo: dict, textos: list[dict]) -> tuple[float, str] | None:
    """Área no próprio texto, depois do rótulo, ou no texto à direita na mesma linha da tabela."""
    if (v := _area_escrita(_texto(rotulo))) is not None:
        return v, str(rotulo.get("h"))
    x, _y = _pontos(rotulo)[0]
    meio = _meio_da_linha(rotulo)
    altura = float(rotulo.get("a") or 1.0)
    vizinhos = []
    for e in textos:
        if e is rotulo or e.get("e") != rotulo.get("e"):
            continue
        ex, _ey = _pontos(e)[0]
        if (0 < ex - x <= DISTANCIA_DO_VALOR * altura and abs(_meio_da_linha(e) - meio) <= 0.6 * altura
                and (v := _area_escrita(_texto(e))) is not None):
            vizinhos.append((ex - x, v, str(e.get("h"))))
    if not vizinhos:
        return None
    _dx, v, h = min(vizinhos)
    return v, h


def _areas_escritas(textos: list[dict], propostas: list[Proposta], saida: dict) -> None:
    pavimentos = []
    achados: dict[str, tuple[float, list[str], str]] = {}
    for e in textos:
        t = _texto(e)
        # "08 - AC - ÁREA CONSTRUÍDA:" (prancha real 02): a sigla antes de ÁREA.
        if not t.startswith("AREA") and "AREA " not in t[:16]:
            continue
        rotulo = re.split(r"[:=]", t, maxsplit=1)[0].strip()
        valor = _valor_ao_lado(e, textos)
        if valor is None:
            continue
        v, h = valor
        handles = sorted({str(e.get("h")), h})
        if "TERREO" in rotulo:
            achados.setdefault("area_pavimento_terreo_m2", (v, handles, rotulo))
        elif "CONSTRUIDA" in rotulo or "A CONSTRUIR" in rotulo:
            achados.setdefault("AC", (v, handles, rotulo))
        elif "PROJECAO" in rotulo:
            achados.setdefault("area_projecao_m2", (v, handles, rotulo))
        elif "TERRENO" in rotulo or "LOTE" in rotulo:
            achados.setdefault("area_terreno", (v, handles, rotulo))
        if _PAVIMENTO.search(rotulo):
            pavimentos.append({"rotulo": rotulo, "valor": v, "handles": handles})
    if pavimentos:
        saida["areasPorPavimento"] = pavimentos
    for campo, (v, handles, rotulo) in achados.items():
        escrita = Proposta(campo, *ROTULOS[campo], v, f"escrito no desenho: \"{rotulo}\"", handles)
        medida = next((p for p in propostas if p.campo == campo), None)
        if medida is None:
            propostas.append(escrita)
        elif abs(medida.valor - v) > 0.01:
            # O quadro diz uma coisa e o desenho mede outra: propõe o escrito (é o que a prancha
            # declara; na prancha real 02 a polilinha medida era só a projeção do pavimento de cima)
            # e mostra a medida, para a pessoa decidir.
            propostas[propostas.index(medida)] = escrita
            saida["divergencias"].append({"campo": campo, "rotulo": ROTULOS[campo][0], "escrito": v,
                                          "medido": medida.valor, "comoMedido": medida.como,
                                          "handlesMedido": medida.handles[:MAXIMO_HANDLES]})
            if campo == "area_projecao_m2" and abs(medida.valor - v) > DIFERENCA_PROJECAO * v:
                _sem_afastamentos(propostas, saida, medida.valor, v)
    if "AC" not in achados and len(pavimentos) >= 2 and not any(p.campo == "AC" for p in propostas):
        total = _arred(sum(p["valor"] for p in pavimentos))
        propostas.append(Proposta("AC", *ROTULOS["AC"], total, "soma das áreas escritas por pavimento",
                                  [h for p in pavimentos for h in p["handles"]]))


# A polilinha medida como a edificação e a projeção escrita diferem mais que isso: a polilinha não é
# a edificação inteira (prancha real 02: 35,84 m² medidos, a projeção do pavimento de cima, contra
# 149,80 m² escritos), e os afastamentos medidos dela não valem.
DIFERENCA_PROJECAO = 0.2


def _sem_afastamentos(propostas: list[Proposta], saida: dict, medido: float, escrito: float) -> None:
    """Tira os afastamentos medidos da polilinha que não é a edificação inteira e diz por quê."""
    afastamentos = [p for p in propostas if (p.campo or "").startswith("afastamento_")]
    if not afastamentos:
        return
    for p in afastamentos:
        propostas.remove(p)
    saida.pop("afastamentosPorLado", None)
    virgula = lambda n: f"{n:.2f}".replace(".", ",")  # noqa: E731
    saida["naoMedido"].append(f"afastamentos: a polilinha medida como a edificação ({virgula(medido)} m²) não é a "
                              f"projeção escrita ({virgula(escrito)} m²); meça na planta de situação ou pergunte")


def _vagas(entidades: list[dict], textos: list[dict], propostas: list[Proposta]) -> None:
    for e in textos:
        m = _TOTAL_VAGAS.search(_texto(e))
        if m and not _VAGA_NUMERADA.match(_texto(e)):
            total = int(m.group(1) or m.group(2))
            propostas.append(Proposta("n_vagas_previstas", *ROTULOS["n_vagas_previstas"], float(total),
                                      f"escrito no desenho: \"{_texto(e)[:60]}\"", [str(e.get("h"))]))
            return
    numeradas: dict[int, str] = {}
    for e in textos:
        if m := _VAGA_NUMERADA.match(_texto(e)):
            numeradas.setdefault(int(m.group(1)), str(e.get("h")))
    if numeradas:
        propostas.append(Proposta("n_vagas_previstas", *ROTULOS["n_vagas_previstas"], float(len(numeradas)),
                                  f"{len(numeradas)} vagas numeradas no desenho", list(numeradas.values())))
        return
    carros = [str(e.get("h")) for e in entidades if e.get("t") == "INSERT" and e.get("e") == "modelo"
              and _BLOCO_CARRO.search(normal(str(e.get("b") or "")))]
    if carros:
        propostas.append(Proposta("n_vagas_previstas", *ROTULOS["n_vagas_previstas"], float(len(carros)),
                                  f"{len(carros)} blocos de vaga/carro no model space (se a mesma vaga aparece em "
                                  "duas plantas, conta duas vezes)", carros))


# ---------------------------------------------------------------- tudo

def medir(entidades: list[dict], unidade: str = "m") -> dict:
    """A proposta de medidas do desenho: {propostas, lote, afastamentosPorLado, areasPorPavimento,
    divergencias, naoMedido, avisos}. Nada é gravado: o responsável técnico confirma antes."""
    if unidade not in ESCALAS:
        raise ValueError(f"unidade deve ser uma de {', '.join(ESCALAS)}")
    escala = ESCALAS[unidade]
    propostas: list[Proposta] = []
    saida: dict = {"unidade": unidade, "naoMedido": [], "avisos": [], "divergencias": []}
    _terreno(entidades, escala, propostas, saida)
    textos = _textos(entidades)
    _pavimentos(textos, propostas)
    _altura(textos, propostas, saida)
    _areas_escritas(textos, propostas, saida)
    _vagas(entidades, textos, propostas)
    medidos = {p.campo for p in propostas}
    for campo in ("NPC", "altura_edificacao_hmax_m", "n_vagas_previstas"):
        if campo not in medidos:
            saida["naoMedido"].append(f"{ROTULOS[campo][0].lower()}: não achei no desenho")
    ordem = {campo: i for i, campo in enumerate(CAMPOS)}
    saida["propostas"] = [p.para_o_chat() for p in sorted(propostas, key=lambda p: ordem.get(p.campo, 99))]
    return {k: v for k, v in saida.items() if v not in ([], None)} | {"propostas": saida["propostas"]}
