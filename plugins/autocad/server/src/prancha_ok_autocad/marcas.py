"""O que marcar no desenho e o que vai no quadro-resumo (rodada 2: máximo de marcações).

Entrada: o parecer da rota GET /cliente/v1/pareceres/<id> (packages/backend/convex/cliente.ts),
cujo item, desde a rodada 2 (docs/planos/rodada-2-contrato.md, 4.2 e 4.4), pode trazer
`titulo`, `modo`, `regiao` {tipo, rotulo, handleTitulo?, caixa?, espaco?}, `aguardaGatilho`,
`resposta` e `etapa`, e a situação `conferir_a_mao` ou `pergunta`. Parecer antigo vem sem
esses campos e cai nos mesmos caminhos (sem região, título = texto).

Lugar de uma linha, nesta ordem (contrato, 4.2):
  1. os handles do próprio item (lugar "desenho": ambiente, texto achado, geometria medida);
  2. os handles dos campos de que ele depende (origem do valor lido);
  3. a região com caixa (nuvem em volta da caixa) ou só com o título (nuvem em volta dele);
  4. nada: só o quadro-resumo. A região só com tipo e rótulo diz onde olhar, mas não é lugar.

Nada aqui fala com o AutoCAD: servidor.marcar_parecer manda as marcas (autocad.py) e devolve
a medida (quantas linhas apresentadas têm lugar e quantas viraram nuvem).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Situações que o MCP apresenta no desenho, da pior para a melhor (a pior manda na cor de uma
# nuvem com vários itens). As outras (atendido, dispensado e as que um backend novo inventar)
# ficam de fora.
ORDEM = ("errado", "duvida", "pergunta", "conferir_a_mao")
# Cor ACI da nuvem e do rótulo: vermelho, laranja, magenta e azul (todas legíveis em fundo
# claro e escuro). A camada continua vermelha e sem plotar.
COR = {"errado": 1, "duvida": 30, "pergunta": 6, "conferir_a_mao": 5}
ROTULO = {"errado": "ERRO", "duvida": "DÚVIDA", "pergunta": "PERGUNTA", "conferir_a_mao": "CONFERIR"}
NOME_COR = {"errado": "vermelho = em desacordo", "duvida": "laranja = dúvida",
            "pergunta": "magenta = pergunta", "conferir_a_mao": "azul = conferir à mão"}

# Situações cuja linha conta na medida de lugar (contrato, 9.3). Pergunta é medida à parte:
# a maioria é sobre documentos, que não têm lugar no desenho.
MEDIDAS = ("errado", "duvida", "conferir_a_mao")

MAXIMO_HANDLES_POR_ITEM = 5
MAXIMO_LINHAS_QUADRO = 60
MAXIMO_TEXTO_QUADRO = 110
# O sentinela que o Convex usa para o lugar que não vem de um campo (cliente.ts).
LUGAR_DO_ITEM = "desenho"


@dataclass
class Linha:
    """Uma linha apresentada do parecer, com o lugar já escolhido."""
    numero: int  # ordem + 1: o número que o chat, as nuvens e o quadro mostram
    situacao: str
    titulo: str
    texto: str
    handles: list[str] = field(default_factory=list)
    regiao: dict | None = None  # só se dá para achar no desenho (caixa ou título)
    onde_olhar: str | None = None  # rótulo da região, achada ou não ("Planta de situação")
    faltando: list[str] = field(default_factory=list)
    aguarda_gatilho: str | None = None

    @property
    def tem_lugar(self) -> bool:
        return bool(self.handles or self.regiao)


def _sem_repetir(valores):
    vistos, saida = set(), []
    for v in valores:
        if v not in vistos:
            vistos.add(v)
            saida.append(v)
    return saida


def handles_do_item(item: dict, maximo: int = MAXIMO_HANDLES_POR_ITEM) -> list[str]:
    """Handles da linha na ordem do contrato: os do próprio item, depois os dos campos."""
    lugares = item.get("lugares") or []
    proprios = [h for lugar in lugares if lugar.get("campo") == LUGAR_DO_ITEM for h in lugar.get("handles") or []]
    dos_campos = [h for lugar in lugares if lugar.get("campo") != LUGAR_DO_ITEM for h in lugar.get("handles") or []]
    return _sem_repetir(h for h in proprios + dos_campos if isinstance(h, str) and h)[:maximo]


def caixa_valida(caixa) -> list[float] | None:
    """[x0, y0, x1, y1] com números finitos e área; senão None (o LISP também confere)."""
    if not isinstance(caixa, (list, tuple)) or len(caixa) != 4:
        return None
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in caixa):
        return None
    x0, y0, x1, y1 = (float(n) for n in caixa)
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def regiao_achada(regiao) -> dict | None:
    """A região como o LISP precisa (handleTitulo, caixa, espaco), se dá para achá-la no
    desenho: com caixa, ou com o título. Caixa no papel sem o título não serve: sem o
    título não se sabe o layout."""
    if not isinstance(regiao, dict):
        return None
    titulo = regiao.get("handleTitulo")
    titulo = titulo if isinstance(titulo, str) and titulo else None
    caixa = caixa_valida(regiao.get("caixa"))
    espaco = regiao.get("espaco") if regiao.get("espaco") in ("modelo", "papel") else None
    if titulo is None and (caixa is None or espaco == "papel"):
        return None
    return {"handleTitulo": titulo, "caixa": caixa, "espaco": espaco,
            "rotulo": str(regiao.get("rotulo") or regiao.get("tipo") or "região")}


def linha_do_item(item: dict) -> Linha:
    regiao = item.get("regiao") if isinstance(item.get("regiao"), dict) else None
    return Linha(
        numero=item["ordem"] + 1,
        situacao=item["situacao"],
        titulo=str(item.get("titulo") or item["texto"]),
        texto=item["texto"],
        handles=handles_do_item(item),
        regiao=regiao_achada(regiao),
        onde_olhar=(regiao or {}).get("rotulo") or None,
        faltando=list(item.get("faltando") or []),
        aguarda_gatilho=item.get("aguardaGatilho") or None,
    )


def linhas_apresentadas(p: dict, situacoes) -> list[Linha]:
    """As linhas do parecer nas situações pedidas, na ordem do parecer."""
    return [linha_do_item(i) for i in p.get("itens") or [] if i.get("situacao") in situacoes]


def pior(situacoes) -> str:
    return min(situacoes, key=ORDEM.index)


def _rotulo_curto(linha: Linha) -> str:
    return f"[{linha.numero}] {ROTULO[linha.situacao]}: {linha.titulo}"


def marcas_por_handle(linhas: list[Linha]) -> list[tuple[str, int, str]]:
    """(handle, cor, rótulo) por handle: itens no mesmo lugar dividem a nuvem, com a cor do
    pior. O rótulo é cortado depois (pedido.marca), para caber numa linha do pedido."""
    por_handle: dict[str, list[Linha]] = {}
    for linha in linhas:
        for h in linha.handles:
            por_handle.setdefault(h, []).append(linha)
    return [(h, COR[pior(x.situacao for x in ls)], "; ".join(_rotulo_curto(x) for x in ls))
            for h, ls in por_handle.items()]


def _chave_regiao(regiao: dict) -> tuple:
    return (regiao["handleTitulo"], tuple(regiao["caixa"]) if regiao["caixa"] else None, regiao["espaco"])


def marcas_por_regiao(linhas: list[Linha]) -> tuple[list[tuple], list[dict]]:
    """Uma nuvem por região, com os itens dela: (handleTitulo, caixa, espaco, cor, rótulo) e,
    na mesma ordem, {rotulo da região, itens: [números]}. O rótulo da nuvem começa pelos
    números, que sobrevivem ao corte: "Planta de situação - itens 3, 7, 12 - [3] ERRO: ...". """
    grupos: dict[tuple, list[Linha]] = {}
    for linha in linhas:
        if linha.regiao:
            grupos.setdefault(_chave_regiao(linha.regiao), []).append(linha)
    marcas, grupos_saida = [], []
    for (titulo, caixa, espaco), ls in grupos.items():
        nomes = ", ".join(str(x.numero) for x in ls)
        rotulo = (f"{ls[0].regiao['rotulo']} - {'item' if len(ls) == 1 else 'itens'} {nomes} - "
                  + "; ".join(_rotulo_curto(x) for x in ls))
        marcas.append((titulo, list(caixa) if caixa else None, espaco, COR[pior(x.situacao for x in ls)], rotulo))
        grupos_saida.append({"rotulo": ls[0].regiao["rotulo"], "itens": [x.numero for x in ls]})
    return marcas, grupos_saida


# ---------------------------------------------------------------- perguntas

def opcoes_da_pergunta(linha: Linha) -> list[str]:
    """Gatilho (o projeto tem terraplenagem?) é sim/não; pergunta de documento aceita também
    "não se aplica" (contrato, 4.1)."""
    return ["sim", "não"] if linha.aguarda_gatilho else ["sim", "não", "não se aplica"]


def perguntas_abertas(linhas: list[Linha], rotulos: dict) -> list[dict]:
    """As linhas PERGUNTA agrupadas pelo campo que as responde: uma resposta libera todas."""
    grupos: dict[str, dict] = {}
    for linha in linhas:
        if linha.situacao != "pergunta":
            continue
        for campo in linha.faltando or [linha.aguarda_gatilho or f"item_{linha.numero}"]:
            grupo = grupos.setdefault(campo, {"campo": campo, "pergunta": rotulos.get(campo, campo),
                                              "opcoes": opcoes_da_pergunta(linha), "itens": []})
            grupo["itens"].append(linha.numero)
    return list(grupos.values())


def sobre_o_projeto(grupo: dict) -> bool:
    """Pergunta sobre o projeto (gatilho: sim/não, decide o que vale para a prancha); as outras
    são sobre documentos do processo (RGI, ART, taxa...), que não seguram o parecer."""
    return "não se aplica" not in grupo["opcoes"]


def agrupar_duvidas(linhas: list[Linha]) -> list[Linha | tuple[str, list[Linha]]]:
    """Dúvidas que esperam o mesmo dado viram um grupo (como a aba Dúvidas da web,
    lib/agruparDuvidas.ts): cada dúvida vai para o campo que mais dúvidas pedem; grupo com uma
    dúvida só continua dúvida. Na ordem da primeira dúvida de cada grupo."""
    pedidos: dict[str, int] = {}
    for linha in linhas:
        for campo in set(linha.faltando):
            pedidos[campo] = pedidos.get(campo, 0) + 1

    def chave(linha: Linha) -> str | None:
        melhor = None
        for campo in linha.faltando:
            if melhor is None or pedidos[campo] > pedidos[melhor]:
                melhor = campo
        return melhor if melhor is not None and pedidos[melhor] >= 2 else None

    grupos: dict[str, list[Linha]] = {}
    for linha in linhas:
        if (c := chave(linha)) is not None:
            grupos.setdefault(c, []).append(linha)
    saida: list[Linha | tuple[str, list[Linha]]] = []
    postos: set[str] = set()
    for linha in linhas:
        c = chave(linha)
        if c is None or len(grupos[c]) < 2:
            saida.append(linha)
        elif c not in postos:
            postos.add(c)
            saida.append((c, grupos[c]))
    return saida


# ---------------------------------------------------------------- quadro-resumo

def _cortar(texto: str, limite: int = MAXIMO_TEXTO_QUADRO) -> str:
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."


def linhas_quadro(p: dict, linhas: list[Linha], marcados: set[int], situacao_parecer: str) -> list[str]:
    """Linhas do quadro-resumo (uma por parágrafo do MTEXT). Erros vão todos; dúvidas também,
    mas as que esperam o mesmo dado numa linha só ("falta: Pé-direito...: itens 3, 7, 12");
    "(nuvem)" nos que ganharam nuvem. As perguntas sobre o projeto vão uma por resposta, e as sobre
    documentos numa linha (respondem-se no Prancha Ok); conferir à mão, só os sem nuvem, com onde
    olhar. Se não cabe, corta-se primeiro o conferir à mão e depois as dúvidas: as perguntas
    nunca (revisão do especialista, rodada 2: "o quadro-resumo não pode cortar as perguntas").
    O texto vai como está: autocad.quadro tira o que o MTEXT interpretaria e passa o resto para
    ASCII (pedido.py)."""
    rotulos = p.get("rotulos") or {}
    presentes = [s for s in ORDEM if any(linha.situacao == s for linha in linhas)]
    perguntas = perguntas_abertas(linhas, rotulos)
    cabecalho = [f"PRANCHA OK - PARECER Nº {p['numero']} - {situacao_parecer.upper()}",
                 f"regras {p['versaoRegras']} - camada PRANCHAOK-PARECER (não plota)"]
    if presentes:
        cabecalho.append("nuvens: " + ", ".join(NOME_COR[s] for s in presentes))
    com_nuvem = sum(1 for linha in linhas if linha.numero in marcados)
    cabecalho.append(f"{com_nuvem} de {len(linhas)} itens com nuvem no desenho; os outros estão aqui")
    if perguntas:
        cabecalho.append(f"{sum(len(g['itens']) for g in perguntas)} itens esperam resposta: responda no "
                         "Prancha Ok ou pelo assistente")
    cabecalho.append("")

    def nuvem(linha: Linha) -> str:
        return " (nuvem)" if linha.numero in marcados else ""

    def item(linha: Linha, texto: str) -> str:
        falta = ", ".join(rotulos.get(c, c) for c in linha.faltando)
        return (f"[{linha.numero}]{nuvem(linha)} {_cortar(texto)}"
                + (f" - olhar: {linha.onde_olhar}" if linha.onde_olhar and linha.numero not in marcados else "")
                + (f" - falta: {falta}" if falta else ""))

    erros = [item(x, x.texto) for x in linhas if x.situacao == "errado"]
    duvidas = []
    for d in agrupar_duvidas([x for x in linhas if x.situacao == "duvida"]):
        if isinstance(d, Linha):
            duvidas.append(item(d, d.texto))
            continue
        campo, grupo = d
        numeros = ", ".join(str(x.numero) for x in grupo)
        com = [str(x.numero) for x in grupo if x.numero in marcados]
        duvidas.append(_cortar(f"- falta {rotulos.get(campo, campo)}: itens {numeros}"
                               + (f" (nuvem em {', '.join(com)})" if com else ""), MAXIMO_TEXTO_QUADRO + 40))
    projeto = [g for g in perguntas if sobre_o_projeto(g)]
    documentos = [g for g in perguntas if not sobre_o_projeto(g)]
    linhas_perguntas = [f"- {_cortar(g['pergunta'])} ({'/'.join(g['opcoes'])}; {len(g['itens'])} "
                        f"{'item' if len(g['itens']) == 1 else 'itens'})" for g in projeto]
    if documentos:
        n = len(documentos)
        linhas_perguntas.append(f"- {n} {'pergunta' if n == 1 else 'perguntas'} sobre documentos do processo (RGI, "
                                "ART, taxas...): responda no Prancha Ok")
    conferir = [item(x, x.titulo) for x in linhas if x.situacao == "conferir_a_mao" and x.numero not in marcados]

    secoes = [["EM DESACORDO", erros], ["DÚVIDAS", duvidas], ["PERGUNTAS", linhas_perguntas],
              ["CONFERIR À MÃO (sem nuvem)", conferir]]

    def tamanho() -> int:
        return sum(1 + len(corpo) for _, corpo in secoes if corpo)

    cabe = MAXIMO_LINHAS_QUADRO - len(cabecalho)
    # Corta o conferir à mão, depois as dúvidas, depois os erros; as perguntas ficam.
    for indice in (3, 1, 0):
        titulo, corpo = secoes[indice]
        excesso = tamanho() - cabe
        if excesso <= 0:
            break
        if not corpo:
            continue
        # Fica pelo menos o título e a linha que diz quantos faltam (quando sobra lugar para eles).
        manter = max(0, len(corpo) - excesso - 1)
        cortados = len(corpo) - manter
        secoes[indice][1] = corpo[:manter] + [f"... mais {cortados} (lista completa no Prancha Ok)"]
    saida = list(cabecalho)
    for titulo, corpo in secoes:
        if corpo:
            saida += [titulo, *corpo]
    return saida[:MAXIMO_LINHAS_QUADRO]


# ---------------------------------------------------------------- medida (meta 3)

def medida(linhas: list[Linha], marcados: set[int]) -> dict:
    """Quantas linhas apresentadas têm lugar e quantas viraram nuvem, no total (errado,
    dúvida, conferir à mão: contrato, 9.3), por situação e, à parte, as perguntas."""
    def conta(ls):
        return {"apresentados": len(ls), "comLugar": sum(1 for x in ls if x.tem_lugar),
                "marcados": sum(1 for x in ls if x.numero in marcados)}

    medidas = [linha for linha in linhas if linha.situacao in MEDIDAS]
    total = conta(medidas)
    por_situacao = {s: conta([x for x in linhas if x.situacao == s]) for s in ORDEM
                    if any(x.situacao == s for x in linhas)}
    pct = (lambda n: round(100 * n / total["apresentados"], 1) if total["apresentados"] else None)
    return {**total, "percentualComLugar": pct(total["comLugar"]), "percentualMarcados": pct(total["marcados"]),
            "porSituacao": por_situacao}
