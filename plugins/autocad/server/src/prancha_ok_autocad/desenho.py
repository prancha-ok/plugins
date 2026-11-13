"""O desenho de partida do projeto do zero (0.6.0): as entidades do Prancha Ok como itens do comando `desenhar`.

O backend monta o desenho (packages/backend/convex/lib/desenhoDoTerreno.ts: o lote, os afastamentos, as medidas, a
rua, o norte, o título e o quadro) como uma lista de entidades simples, a mesma que o site escreve em DXF. Aqui cada
entidade vira um item do pedido (o formato está no prancha_ok.lsp, seção "desenhar"): um dado por linha, nenhuma
linha acima de LIMITE_LINHA; o que não cabe numa linha continua em itens "+" (mais pontos, mais texto). Os itens vão
em pedidos de até MAXIMO_ITENS linhas, sem cortar uma entidade entre dois pedidos; cada pedido é um grupo de
desfazer no AutoCAD.

Só em camadas PRANCHAOK-* (nunca a das marcas, PRANCHAOK-PARECER, que o `limpar` apaga e o motor ignora): o
Prancha Ok só acrescenta, e o que a pessoa desenhou fica como está. O LISP confere de novo.

Unidade e origem (0.7.0, contrato C1): o backend manda sempre em METROS, no sistema dele (o UTM do vértice A quando o
lote veio do mapa, ou o vértice A em 0,0). A escala e a origem são do conector: T(p) = k (p - deslocar), com k as
unidades do desenho por metro (m 1, cm 100, mm 1000) e `deslocar` o que se tira de cada ponto (0,0 mantém o sistema do
backend; a origem do plano leva o vértice A a 0,0). `escalar` aplica T a QUALQUER desenho do backend (o terreno e a
planta): pontos, alturas de texto, raios, cotas, contornos da hachura e o zoom; ângulos e textos ficam. O que está em
metros dentro do LISP (o estilo da cota, o tracejado, os deslocamentos da cota em linhas) vai vezes k pelo item
("unidade" k), o 1º de cada pedido. `sistema_do_desenho` escolhe k e a origem pela ordem do contrato (a unidade que
a pessoa disse, o nosso lote já desenhado, $INSUNITS com a altura dos textos, desenho vazio em metros).

Desde 08/11/2026 (decisão do David: o DWG do protocolo vai georreferenciado em UTM SIRGAS 2000), o desenho vazio
nasce em METROS, nas coordenadas do backend: o vértice A no UTM quando o lote veio do mapa (o estudo do lote), ou em
0,0 sem ele (o backend avisa). Antes, nascia em mm com o vértice A em 0,0 e o UTM só no quadro. O mm continua quando a
pessoa o pede (`unidade="mm"`): é a unidade do desenho profissional (o arch_plan_from_spec do autocad-mcp-pro só
trabalha em mm), sem o UTM.
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass

from .pedido import LIMITE_LINHA, cabe, lisp, pedacos, texto_mtext

CAMADA_DAS_MARCAS = "PRANCHAOK-PARECER"
# Linhas por pedido (um grupo de desfazer cada). O terreno do zero tem umas 60 entidades: cabe num só.
MAXIMO_ITENS = 400
# Caracteres do TEXT depois da conversão para ASCII (o AutoCAD guarda até 255 numa string de entidade).
MAXIMO_TEXTO = 250
# Pedaço de texto de um item: cabe numa linha "+" com folga.
PEDACO_TEXTO = 100
TIPOS = ("polilinha", "linha", "arco", "texto", "cota", "hachura")
# Unidades do desenho por metro.
UNIDADES = {"m": 1.0, "cm": 100.0, "mm": 1000.0}
# $INSUNITS (DXF Reference, HEADER): 4 milímetros, 5 centímetros, 6 metros.
INSUNITS = {4: "mm", 5: "cm", 6: "m"}
INSUNITS_DA_UNIDADE = {nome: codigo for codigo, nome in INSUNITS.items()}
# Alturas de texto plausíveis no modelo, em cada unidade (letra de 5 cm a 2 m; terreno-mm.md §3).
FAIXAS_DA_ALTURA = {"m": (0.05, 2.0), "cm": (5.0, 200.0), "mm": (50.0, 2000.0)}
# As espessuras de linha que a camada aceita (código 370, centésimos de mm; DXF Reference, "LAYER", e o LWEIGHT).
ESPESSURAS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
# Folga para casar o lote desenhado com o do projeto: 1% no perímetro (a unidade) e 5 cm em cada vértice (a origem).
FOLGA_DO_PERIMETRO = 0.01
FOLGA_DO_VERTICE_M = 0.05
# O lote casado a até 1 cm do sistema do backend ou do vértice A em 0,0 fica exatamente nele.
ENCAIXE_DA_ORIGEM_M = 0.01


def camada_permitida(nome) -> bool:
    return (isinstance(nome, str) and len(nome) <= 60 and nome.upper().startswith("PRANCHAOK-")
            and nome.upper() != CAMADA_DAS_MARCAS)


def _numero(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _ponto(p) -> tuple[float, float] | None:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        return None
    x, y = _numero(p[0]), _numero(p[1])
    return None if x is None or y is None else (x, y)


def _tamanho(item: list) -> int:
    return len(lisp(item))


# ---------------------------------------------------------------- escala e origem

def insunits_de(k: float) -> int:
    """O $INSUNITS de k unidades por metro (6 m, 5 cm, 4 mm); outro k não tem código."""
    codigo = INSUNITS_DA_UNIDADE.get(nome_da_unidade(k))
    if codigo is None:
        raise ValueError(f"sem $INSUNITS para {k:g} unidades por metro")
    return codigo


def nome_da_unidade(k: float) -> str:
    return next((nome for nome, v in UNIDADES.items() if v == k), f"{k:g} por metro")


def casas_da_unidade(k: float) -> int:
    """As casas para arredondar um número no desenho para o chat: 2 em metros (o cm), 1 em cm e em mm (o 0,1 mm)."""
    return max(1, 2 - round(math.log10(k))) if k > 0 else 2


def escalar_ponto(p, k: float, deslocar=(0.0, 0.0)) -> list[float]:
    """T(p) = k (p - deslocar), um ponto do backend (m) no desenho aberto."""
    return [(float(p[0]) - deslocar[0]) * k, (float(p[1]) - deslocar[1]) * k]


def _escalar_se_ponto(p, k, deslocar):
    return escalar_ponto(p, k, deslocar) if _ponto(p) is not None else p


def escalar(desenho: dict, k: float, deslocar=(0.0, 0.0)) -> dict:
    """Uma cópia do desenho do backend (em metros, no sistema dele) na unidade do desenho aberto: T(p) = k (p -
    deslocar) nos pontos (polilinha, linha, arco, texto, as três pontas da cota, os contornos da hachura e o zoom), e
    vezes k nas alturas de texto e nos raios. Ângulos (`giro`, `inicio`, `fim`) e textos ficam como estão: o texto da
    cota ("12,00") continua em metros, como a pessoa lê. Serve ao terreno e à planta (o que não é entidade nem
    extensão vai como veio). `unidade` passa a ser a do desenho."""
    saida = copy.deepcopy(desenho)
    deslocar = (float(deslocar[0]), float(deslocar[1]))
    for e in saida.get("entidades") or []:
        if not isinstance(e, dict):
            continue
        tipo = e.get("tipo")
        if tipo == "polilinha" and isinstance(e.get("pontos"), list):
            e["pontos"] = [_escalar_se_ponto(q, k, deslocar) for q in e["pontos"]]
        elif tipo in ("linha", "cota"):
            for chave in ("de", "ate", "linha"):
                if chave in e:
                    e[chave] = _escalar_se_ponto(e[chave], k, deslocar)
        elif tipo == "arco":
            e["centro"] = _escalar_se_ponto(e.get("centro"), k, deslocar)
            if _numero(e.get("raio")) is not None:
                e["raio"] = float(e["raio"]) * k
        elif tipo == "texto":
            e["ponto"] = _escalar_se_ponto(e.get("ponto"), k, deslocar)
            if _numero(e.get("altura")) is not None:
                e["altura"] = float(e["altura"]) * k
        elif tipo == "hachura" and isinstance(e.get("contornos"), list):
            e["contornos"] = [[_escalar_se_ponto(q, k, deslocar) for q in c] if isinstance(c, list) else c
                              for c in e["contornos"]]
    if isinstance(ext := saida.get("extensao"), dict):
        saida["extensao"] = {chave: _escalar_se_ponto(ext.get(chave), k, deslocar) for chave in ("de", "ate")}
    saida["unidade"] = nome_da_unidade(k)
    return saida


def somar_origem_ao_spec(spec: dict, origem) -> dict:
    """Uma cópia do spec do `arch_plan_from_spec` do autocad-mcp-pro (no plano local do lote, em mm) com a origem do
    desenho (onde fica o vértice A, em mm) somada a cada ponto: `walls[].axis`, `rooms[].at`, `schedules[].at` e
    `stairs[].start`. O `offset` das aberturas é ao longo do eixo da parede e não muda."""
    ox, oy = float(origem[0]), float(origem[1])
    saida = copy.deepcopy(spec)

    def somar(p):
        q = _ponto(p)
        return [q[0] + ox, q[1] + oy] if q is not None else p

    for parede in saida.get("walls") or []:
        if isinstance(parede, dict) and isinstance(parede.get("axis"), list):
            parede["axis"] = [somar(p) for p in parede["axis"]]
    for chave, campo in (("rooms", "at"), ("schedules", "at"), ("stairs", "start")):
        for item in saida.get(chave) or []:
            if isinstance(item, dict) and campo in item:
                item[campo] = somar(item[campo])
    return saida


@dataclass(frozen=True)
class Sistema:
    """Como o desenho do backend (m) entra no desenho aberto: T(p) = k (p - deslocar).

    `origem_do_plano` (m, no sistema do backend) é onde fica o vértice A do plano local do lote (o `origemDoPlano` da
    rota: o UTM do vértice A, ou 0,0). `fonte` diz como a unidade foi escolhida: "pedida", "lote" (o nosso lote já
    desenhado), "textos" ($INSUNITS e a altura dos textos) ou "vazio" (desenho vazio: metros, e o $INSUNITS vira 6).
    `gravar_insunits`: o desenho está vazio e o $INSUNITS vira o da unidade (`insunits`: 6 m, 5 cm, 4 mm)."""
    k: float
    deslocar: tuple[float, float]
    origem_do_plano: tuple[float, float]
    fonte: str
    evidencia: str
    gravar_insunits: bool = False

    @property
    def unidade(self) -> str:
        return nome_da_unidade(self.k)

    @property
    def insunits(self) -> int | None:
        """O $INSUNITS da unidade (DXF Reference, HEADER: 4 mm, 5 cm, 6 m)."""
        return INSUNITS_DA_UNIDADE.get(self.unidade)

    def do_backend(self, p) -> list[float]:
        return escalar_ponto(p, self.k, self.deslocar)

    def do_plano_local(self, p) -> list[float]:
        """Um ponto do plano local do lote (m, vértice A em 0,0) no desenho aberto."""
        return self.do_backend((self.origem_do_plano[0] + float(p[0]), self.origem_do_plano[1] + float(p[1])))

    @property
    def origem_no_desenho(self) -> list[float]:
        """Onde o vértice A fica no desenho aberto (na unidade dele)."""
        return self.do_plano_local((0.0, 0.0))

    @property
    def no_utm(self) -> bool:
        """O desenho fica com as coordenadas do backend (o UTM, quando o lote veio do mapa)."""
        return self.deslocar == (0.0, 0.0) and self.origem_do_plano != (0.0, 0.0)


@dataclass(frozen=True)
class PrecisaUnidade:
    """Não dá para saber a unidade do desenho aberto sem perguntar: `evidencia` diz o que se viu."""
    evidencia: str


def deslocar_padrao(unidade: str, origem_do_plano) -> tuple[float, float]:
    """Em metros o sistema do backend fica (o UTM, como na 0.6.0); em cm e mm, o vértice A em 0,0: o UTM em mm
    (10 algarismos) é fora da prática e perde precisão nas contas do autocad-mcp-pro (terreno-mm.md §4)."""
    if unidade == "m":
        return (0.0, 0.0)
    return (float(origem_do_plano[0]), float(origem_do_plano[1]))


def _perimetro(pts) -> float:
    return sum(math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))


def casar_lote(desenhado, do_backend) -> tuple[float, tuple[float, float]] | None:
    """O nosso lote já desenhado (os vértices da polilinha da camada PRANCHAOK-LOTE, na unidade do desenho) contra o
    lote do backend (m, no sistema dele): (k, deslocar) quando é o mesmo lote, senão None. k pelo perímetro (1, 100 ou
    1000 a FOLGA_DO_PERIMETRO); o deslocamento pela média de p - q/k na correspondência de vértices (qualquer vértice
    de partida, nos dois sentidos) de menor resíduo, aceito com todo vértice a FOLGA_DO_VERTICE_M."""
    d = [q for q in (_ponto(p) for p in desenhado or []) if q is not None]
    b = [q for q in (_ponto(p) for p in do_backend or []) if q is not None]
    if len(d) > 2 and math.dist(d[0], d[-1]) <= 1e-9:
        d = d[:-1]
    if len(d) < 3 or len(d) != len(b):
        return None
    pb = _perimetro(b)
    if pb <= 0:
        return None
    razao = _perimetro(d) / pb
    k = next((v for v in UNIDADES.values() if abs(razao / v - 1) <= FOLGA_DO_PERIMETRO), None)
    if k is None:
        return None
    n = len(b)
    melhor = None
    for sentido in (1, -1):
        for inicio in range(n):
            par = [d[(inicio + sentido * j) % n] for j in range(n)]
            dx = sum(b[j][0] - par[j][0] / k for j in range(n)) / n
            dy = sum(b[j][1] - par[j][1] / k for j in range(n)) / n
            residuo = max(math.dist(((b[j][0] - dx) * k, (b[j][1] - dy) * k), par[j]) for j in range(n))
            if melhor is None or residuo < melhor[0]:
                melhor = (residuo, (dx, dy))
    if melhor[0] > FOLGA_DO_VERTICE_M * k:
        return None
    return k, melhor[1]


def _numero_br(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def sistema_do_desenho(info: dict, lote_desenhado, lote_do_backend, origem_do_plano,
                       pedida: str | None = None) -> Sistema | PrecisaUnidade:
    """A unidade e a origem do desenho aberto, na ordem do contrato C1 (terreno-mm.md §3):

    1. a unidade que a pessoa disse (`pedida`: m, cm, mm) vence a unidade (o lugar, com o lote casado nela, é o dele);
    2. o nosso lote já desenhado (`lote_desenhado`, do comando `lote`) que casa com o do backend (`lote_do_backend`,
       m, no sistema do backend): dá k e a origem de verdade;
    3. desenho com conteúdo: $INSUNITS (4, 5, 6) com a altura mediana dos textos na faixa dele; sem $INSUNITS, a
       única faixa em que a altura cabe; conflito, faixa dupla ou nenhum texto: PrecisaUnidade (o Claude pergunta);
    4. desenho vazio: metros, nas coordenadas do backend (o UTM do vértice A, quando o lote veio do mapa), e o
       conector grava $INSUNITS = 6 (só no desenho vazio; com um lote nosso que não casa, não é vazio:
       PrecisaUnidade). A unidade dita num desenho vazio também grava o $INSUNITS dela.

    `info` é o do comando `info` (insunits, entidadesNoModelo, alturaDosTextos). O deslocamento, fora do lote casado:
    `deslocar_padrao`."""
    origem = (float(origem_do_plano[0]), float(origem_do_plano[1])) if _ponto(origem_do_plano) else (0.0, 0.0)

    def sistema(unidade, fonte, evidencia, gravar=False):
        return Sistema(UNIDADES[unidade], deslocar_padrao(unidade, origem), origem, fonte, evidencia, gravar)

    entidades = info.get("entidadesNoModelo")
    vazio = entidades == 0 and not lote_desenhado
    casado = None
    if lote_desenhado and (casado := casar_lote(lote_desenhado, lote_do_backend)):
        k, deslocar = casado
        # O lote no sistema do backend ou com o vértice A em 0,0 (a 1 cm): o deslocamento exato, sem o resíduo.
        for exato in ((0.0, 0.0), origem):
            if math.dist(deslocar, exato) <= ENCAIXE_DA_ORIGEM_M:
                deslocar = exato
                break
        casado = (k, deslocar)
    if pedida is not None:
        if pedida not in UNIDADES:
            return PrecisaUnidade(f"A unidade pedida ({pedida!r}) não é m, cm nem mm.")
        if casado and casado[0] == UNIDADES[pedida]:
            # A pessoa diz a unidade, não o lugar: o lote já desenhado nessa unidade dá a origem de verdade.
            return Sistema(casado[0], casado[1], origem, "pedida",
                           f"A pessoa disse que o desenho é em {pedida}, e o lote do projeto já está no desenho "
                           "(camada PRANCHAOK-LOTE) nessa unidade.")
        return sistema(pedida, "pedida", f"A pessoa disse que o desenho é em {pedida}."
                       + (" O desenho está vazio: o $INSUNITS passa a dizer a unidade." if vazio else ""), gravar=vazio)
    nota_do_lote = ""
    if casado:
        k, deslocar = casado
        return Sistema(k, deslocar, origem, "lote",
                       f"O lote do projeto já está no desenho (camada PRANCHAOK-LOTE), em {nome_da_unidade(k)}.")
    if lote_desenhado:
        nota_do_lote = " A polilinha da camada PRANCHAOK-LOTE não é o lote deste projeto."
    insunits = info.get("insunits")
    declarada = INSUNITS.get(insunits) if isinstance(insunits, int) and not isinstance(insunits, bool) else None
    if entidades == 0 and lote_desenhado:
        # Um lote nosso que não casa (o terreno mudou no site, ou outra unidade) não é desenho vazio: nada de mm nem de
        # gravar o $INSUNITS por cima de um terreno que pode estar em metros.
        return PrecisaUnidade("O desenho tem só o que o Prancha Ok desenhou, e a polilinha da camada PRANCHAOK-LOTE "
                              "não é o lote deste projeto (o terreno mudou no site?)"
                              + (f"; o $INSUNITS diz {declarada}." if declarada else "."))
    if entidades == 0:
        return sistema("m", "vazio", "O desenho está vazio: o projeto nasce em metros, nas coordenadas UTM SIRGAS 2000 "
                       "do lote (com o vértice A em 0,0 quando o lote não foi desenhado no mapa)." + nota_do_lote,
                       gravar=True)
    altura = _numero(info.get("alturaDosTextos"))
    if altura is None or altura <= 0:
        return PrecisaUnidade(
            ("O desenho tem conteúdo, mas nenhum texto no modelo para conferir a unidade"
             if entidades else "Não deu para ler o desenho aberto")
            + (f" (o $INSUNITS diz {declarada}, e o modelo acadiso dá mm a todo desenho novo)." if declarada else ".")
            + nota_do_lote)
    cabem = [nome for nome, (de, ate) in FAIXAS_DA_ALTURA.items() if de <= altura <= ate]
    texto_da_altura = f"os textos têm {_numero_br(round(altura, 4))} de altura"
    if declarada:
        if declarada in cabem:
            return sistema(declarada, "textos", f"O desenho diz {declarada} ($INSUNITS) e {texto_da_altura}.")
        parece = f": parece {' ou '.join(cabem)}" if cabem else ", o que não é letra em m, cm nem mm"
        return PrecisaUnidade(f"O desenho diz {declarada} ($INSUNITS), mas {texto_da_altura}{parece}." + nota_do_lote)
    if len(cabem) == 1:
        return sistema(cabem[0], "textos", f"O desenho não diz a unidade ($INSUNITS) e {texto_da_altura}: "
                                            f"só faz sentido em {cabem[0]}.")
    return PrecisaUnidade(f"O desenho não diz a unidade ($INSUNITS) e {texto_da_altura}"
                          + (f": pode ser {' ou '.join(cabem)}." if cabem else ", o que não é letra em m, cm nem mm.")
                          + nota_do_lote)


# ---------------------------------------------------------------- itens do pedido

def _empacotar(cabeca: list, unidades: list[list]) -> list[list]:
    """A cabeça do item e as unidades (cada uma, uma lista de valores que fica junta: um ponto, um pedaço de texto)
    em linhas de até LIMITE_LINHA: enche a linha de cima e continua em itens "+"."""
    linhas = [list(cabeca)]
    for unidade in unidades:
        if _tamanho(linhas[-1] + unidade) > LIMITE_LINHA:
            linhas.append(["+"])
        linhas[-1].extend(unidade)
    return linhas


def _pedacos_do_texto(texto) -> list[list] | None:
    """O texto em ASCII (\\U+XXXX no que não é: o TEXT mostra o caractere), cortado em MAXIMO_TEXTO, em pedaços."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    conteudo = cabe(texto_mtext(texto.strip()), MAXIMO_TEXTO + 2)  # o `cabe` conta as aspas do literal
    return [[p] for p in pedacos(conteudo, PEDACO_TEXTO)]


def texto_da_medida(metros: float) -> str:
    """A medida como a cota viva mostra (DIMDEC 2, DIMDSEP ",", DIMZIN 0): "10,00", "2,50"."""
    return f"{metros:.2f}".replace(".", ",")


def _cor(cor) -> int:
    """Cor ACI da entidade (1 a 255), ou 256 (DaCamada)."""
    return cor if isinstance(cor, int) and not isinstance(cor, bool) and 0 < cor < 256 else 256


def itens_da_entidade(e, k: float = 1.0) -> list[list] | None:
    """Os itens do pedido de uma entidade (já na unidade do desenho: `escalar`), ou None se ela não é desenhável
    (tipo desconhecido, camada fora das PRANCHAOK-*, número que não é número). `k` (unidades por metro) decide a cota
    viva: o texto que é a própria medida em metros vai como "cota-viva" (a DIMENSION mostra a medida, DIMLFAC 1/k)."""
    if not isinstance(e, dict) or e.get("tipo") not in TIPOS or not camada_permitida(e.get("camada")):
        return None
    camada, tipo = e["camada"], e["tipo"]
    if tipo == "polilinha":
        pontos = [_ponto(p) for p in e.get("pontos") or []]
        if len(pontos) < 2 or None in pontos or not isinstance(e.get("fechada"), bool):
            return None
        return _empacotar(["polilinha", camada, 1 if e["fechada"] else 0], [list(p) for p in pontos])
    if tipo == "linha":
        de, ate = _ponto(e.get("de")), _ponto(e.get("ate"))
        tipo_linha = e.get("tipoLinha") or ""
        if de is None or ate is None or not isinstance(tipo_linha, str) or len(tipo_linha) > 60:
            return None
        return [["linha", camada, *de, *ate, tipo_linha]]
    if tipo == "arco":
        # Graus, anti-horário de `inicio` a `fim` (contrato da planta, planta-v1): o LISP passa a radianos.
        centro, raio = _ponto(e.get("centro")), _numero(e.get("raio"))
        inicio, fim = _numero(e.get("inicio")), _numero(e.get("fim"))
        if centro is None or raio is None or raio <= 0 or inicio is None or fim is None:
            return None
        return [["arco", camada, *centro, raio, inicio, fim]]
    if tipo == "texto":
        ponto, altura, giro = _ponto(e.get("ponto")), _numero(e.get("altura")), _numero(e.get("giro"))
        pedacos_texto = _pedacos_do_texto(e.get("texto"))
        if (ponto is None or altura is None or altura <= 0 or giro is None or pedacos_texto is None
                or e.get("alinhamento") not in ("esquerda", "centro")):
            return None
        return _empacotar(["texto", camada, *ponto, altura, giro, e["alinhamento"]], pedacos_texto)
    if tipo == "hachura":
        # ("hachura" camada cor n x y ... n x y ...): cada contorno, o número de vértices e os vértices.
        contornos = e.get("contornos")
        if e.get("padrao", "SOLID") != "SOLID" or not isinstance(contornos, list) or not contornos:
            return None
        unidades: list[list] = []
        for c in contornos:
            pontos = [_ponto(p) for p in c] if isinstance(c, list) else [None]
            if len(pontos) < 3 or None in pontos:
                return None
            unidades.append([len(pontos), *pontos[0]])
            unidades.extend(list(p) for p in pontos[1:])
        return _empacotar(["hachura", camada, _cor(e.get("cor"))], unidades)
    de, ate, linha = _ponto(e.get("de")), _ponto(e.get("ate")), _ponto(e.get("linha"))
    pedacos_texto = _pedacos_do_texto(e.get("texto"))
    if de is None or ate is None or linha is None or pedacos_texto is None or math.dist(de, ate) <= 1e-6:
        return None
    viva = e["texto"].strip() == texto_da_medida(math.dist(de, ate) / k)
    return _empacotar(["cota-viva" if viva else "cota", camada, *de, *ate, *linha], pedacos_texto)


def espessura_da_camada(mm) -> int | None:
    """A espessura de linha da camada (mm, 0,50) no código 370 (centésimos de mm, 50), se é uma das que o AutoCAD
    aceita; senão None (a camada fica com a padrão)."""
    v = _numero(mm)
    if v is None:
        return None
    centesimos = round(v * 100)
    return centesimos if centesimos in ESPESSURAS and abs(v * 100 - centesimos) < 1e-6 else None


def _itens_das_camadas(camadas) -> list[list]:
    saida = []
    for c in camadas or []:
        if not isinstance(c, dict) or not camada_permitida(c.get("nome")):
            continue
        cor = c.get("cor")
        tipo_linha = c.get("tipoLinha") or "CONTINUOUS"
        item = ["camada", c["nome"], cor if isinstance(cor, int) and not isinstance(cor, bool) and 0 < cor < 256
                else 7, tipo_linha if isinstance(tipo_linha, str) else "CONTINUOUS"]
        espessura = espessura_da_camada(c.get("espessura"))
        if c.get("imprime") is False or espessura is not None:  # a camada que não plota (o contorno dos cômodos)
            item.append(0 if c.get("imprime") is False else 1)
        if espessura is not None:
            item.append(espessura)
        saida.append(item)
    return saida


def _zoom(extensao) -> list | None:
    if not isinstance(extensao, dict):
        return None
    de, ate = _ponto(extensao.get("de")), _ponto(extensao.get("ate"))
    if de is None or ate is None:
        return None
    x0, x1 = sorted((de[0], ate[0]))
    y0, y1 = sorted((de[1], ate[1]))
    return ["zoom", x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


@dataclass(frozen=True)
class Pedidos:
    pedidos: list[list[list]]  # cada um, os itens de um `desenhar`
    ignoradas: int  # entidades do contrato que não vão (tipo desconhecido, camada de fora, dado torto)
    enviadas: int


def pedidos(desenho: dict, so_se_vazio: str | None = None, maximo_itens: int | None = None,
            prefixo: str | None = None, k: float | None = None, gravar_insunits: bool = False) -> Pedidos:
    """O desenho (já na unidade do desenho aberto: `escalar`) em pedidos do `desenhar`. `so_se_vazio`: a camada que,
    com algo nela, faz o 1º pedido não desenhar nada (o terreno já está no desenho). `prefixo`: só as camadas e
    entidades com esse começo de nome (a planta só desenha nas PRANCHAOK-PLANTA-*: o terreno não vai de novo). `k`
    (unidades do desenho por metro): o item ("unidade" k) abre cada pedido (o LISP volta a 1 a cada pedido) e decide
    as cotas vivas; sem ele, metros. `gravar_insunits`: o 1º pedido grava o $INSUNITS da unidade (6 m, 5 cm, 4 mm,
    pelo k) se o desenho está vazio (o LISP confere de novo). As camadas vão no 1º pedido; o zoom, no último."""
    maximo_itens = maximo_itens or MAXIMO_ITENS
    k_itens = k if k is not None else 1.0

    def da_vez(nome) -> bool:
        return prefixo is None or (isinstance(nome, str) and nome.upper().startswith(prefixo.upper()))

    blocos, ignoradas = [], 0
    for e in desenho.get("entidades") or []:
        itens = itens_da_entidade(e, k_itens) if isinstance(e, dict) and da_vez(e.get("camada")) else None
        if itens is None:
            ignoradas += 1
        else:
            blocos.append(itens)
    camadas = [c for c in desenho.get("camadas") or [] if isinstance(c, dict) and da_vez(c.get("nome"))]
    unidade = [["unidade", float(k)]] if k is not None else []
    primeiro = (([["se-vazio", so_se_vazio]] if so_se_vazio else []) + unidade
                + ([["insunits-se-vazio", insunits_de(k_itens)]] if gravar_insunits else []) + _itens_das_camadas(camadas))
    saida = [primeiro]
    for bloco in blocos:
        if len(saida[-1]) > len(unidade) and len(saida[-1]) + len(bloco) > maximo_itens:
            saida.append(list(unidade))
        saida[-1].extend(bloco)
    if zoom := _zoom(desenho.get("extensao")):
        if len(saida[-1]) + 1 > maximo_itens:
            saida.append(list(unidade))
        saida[-1].append(zoom)
    return Pedidos(pedidos=[p for p in saida if p], ignoradas=ignoradas, enviadas=len(blocos))


# ---------------------------------------------------------------- o quadro do terreno

_LINHA_DO_SISTEMA = re.compile(r"^DESENHO EM METROS VERDADEIROS\b")
_NOME_POR_EXTENSO = {"m": ("METROS VERDADEIROS", "M"), "cm": ("CENTÍMETROS", "CM"), "mm": ("MILÍMETROS", "MM")}


def linha_do_sistema(sistema: Sistema, com_utm: bool) -> str:
    """A linha do quadro do terreno que diz a unidade e a origem do desenho (a do backend diz sempre metros e o UTM
    ou o 0,0 do vértice A). `com_utm`: o quadro lista o UTM dos vértices (o lote veio do mapa)."""
    nome, sigla = _NOME_POR_EXTENSO.get(sistema.unidade, (sistema.unidade.upper(), sistema.unidade.upper()))
    unidade = "DESENHO EM METROS VERDADEIROS" if sistema.k == 1 else f"DESENHO EM {nome} (1 UNIDADE = 1 {sigla})"
    ox, oy = sistema.origem_no_desenho
    casas = casas_da_unidade(sistema.k)
    if sistema.no_utm:
        origem = "ORIGEM NO UTM DO VÉRTICE A."
    elif abs(ox) < 10 ** -casas and abs(oy) < 10 ** -casas:
        origem = "ORIGEM (0,0) NO VÉRTICE A" + ("; UTM DOS VÉRTICES ACIMA." if com_utm else ", SEM COORDENADAS DO MAPA.")
    else:
        origem = (f"VÉRTICE A EM ({_numero_br(round(ox, casas))}; {_numero_br(round(oy, casas))})"
                  + ("; UTM DOS VÉRTICES ACIMA." if com_utm else ", SEM COORDENADAS DO MAPA."))
    return f"{unidade}, {origem}"


def ajustar_quadro(desenho: dict, sistema: Sistema) -> dict:
    """O desenho do terreno com a linha "DESENHO EM METROS VERDADEIROS, ..." do quadro dizendo a unidade e a origem
    do desenho aberto (no sistema do backend, em metros, ela fica como veio)."""
    saida = copy.deepcopy(desenho)
    for e in saida.get("entidades") or []:
        if isinstance(e, dict) and e.get("tipo") == "texto" and isinstance(e.get("texto"), str):
            if _LINHA_DO_SISTEMA.match(e["texto"]):
                com_utm = "UTM" in e["texto"]
                if not (sistema.k == 1 and sistema.deslocar == (0.0, 0.0)):
                    e["texto"] = linha_do_sistema(sistema, com_utm)
    return saida
