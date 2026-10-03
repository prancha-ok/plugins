"""O que marcar no desenho e o que vai no quadro-resumo (rodada 2: máximo de marcações).

Entrada: o parecer da rota GET /cliente/v1/pareceres/<id> (packages/backend/convex/cliente.ts),
cujo item, desde a rodada 2 (docs/planos/rodada-2-contrato.md, 4.2 e 4.4), pode trazer
`titulo`, `modo`, `regiao` {tipo, rotulo, handleTitulo?, caixa?, espaco?}, `aguardaGatilho`,
`resposta` e `etapa`, e a situação `conferir_a_mao` ou `pergunta`. Parecer antigo vem sem
esses campos e cai nos mesmos caminhos (sem região, título = texto). Desde a rodada 5, também
`outrasRegioes` (mesma forma): os outros lugares do item, um por tipo ("planta baixa E corte";
"carimbo E site da Prefeitura", este fora da prancha, só com o rótulo). Rota antiga, sem o campo:
só a `regiao`, como antes.

Lugar de uma linha, nesta ordem (contrato, 4.2):
  1. os handles do próprio item (lugar "desenho": ambiente, texto achado, geometria medida);
  2. os handles dos campos de que ele depende (origem do valor lido);
  3. a região com caixa (nuvem em volta da caixa) ou só com o título (nuvem em volta dele), e
     também cada um dos outros lugares achados no desenho (`outrasRegioes`);
  4. nada: só o quadro-resumo. A região só com tipo e rótulo diz onde olhar, mas não é lugar.
No carimbo, no quadro de áreas e onde as nuvens se amontoariam, a marca é uma chamada com seta
em vez da nuvem (0.3.4, chamadas.py).

Resposta do responsável na web (rodada 4b; a rota manda `marca` em cada item desde a 0.3.1 do
backend, e o MCP antigo ignora): o item que ele conferiu ("sim"), contestou ("discordo") ou marcou
"não se aplica" não ganha nuvem nem linha no quadro; o "não" conta como desacordo (vermelho); o
"corrigido" continua desacordo até a prancha nova. O quadro diz quanto falta para fechar
(`contaDoResponsavel`) e, fechada a análise na web, "aprovado pelo responsável". Nada disso vira
"atendido pelo Prancha Ok".

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
# Respostas do responsável na web que resolvem o item (convex/lib/conferencias.ts): sem nuvem.
RESOLVIDO_PELO_RESPONSAVEL = ("sim", "discordo", "nao_se_aplica")


def escolha_do_responsavel(item: dict) -> str | None:
    """A resposta do responsável no item (`marca.escolha` da rota), ou None (sem marca, ou rota antiga)."""
    marca = item.get("marca")
    escolha = marca.get("escolha") if isinstance(marca, dict) else None
    return escolha if isinstance(escolha, str) else None


def resolvido_pelo_responsavel(item: dict) -> bool:
    return escolha_do_responsavel(item) in RESOLVIDO_PELO_RESPONSAVEL


def situacao_apresentada(item: dict) -> str | None:
    """A situação na nuvem: a do motor, menos o "não" do responsável, que é desacordo."""
    return "errado" if escolha_do_responsavel(item) == "nao" else item.get("situacao")


@dataclass
class Linha:
    """Uma linha apresentada do parecer, com o lugar já escolhido."""
    numero: int  # ordem + 1: o número que o chat, as nuvens e o quadro mostram
    situacao: str
    titulo: str
    texto: str
    handles: list[str] = field(default_factory=list)
    regiao: dict | None = None  # só se dá para achar no desenho (caixa ou título)
    # Os outros lugares do item achados no desenho (rodada 5), na forma de `regiao`.
    outras_regioes: list[dict] = field(default_factory=list)
    # Rótulos de todos os lugares, achados ou não ("Planta baixa e Corte").
    onde_olhar: str | None = None
    faltando: list[str] = field(default_factory=list)
    aguarda_gatilho: str | None = None

    @property
    def regioes(self) -> list[dict]:
        """Todas as regiões achadas no desenho: a `regiao` (se achada) e as outras."""
        return ([self.regiao] if self.regiao else []) + self.outras_regioes

    @property
    def tem_lugar(self) -> bool:
        return bool(self.handles or self.regioes)


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
            "rotulo": str(regiao.get("rotulo") or regiao.get("tipo") or "região"),
            "tipo": regiao.get("tipo") if isinstance(regiao.get("tipo"), str) else None}


def com_lugar_medido(p: dict, medidas: dict | None) -> dict:
    """O parecer com o lugar das medidas confirmadas antes do envio (`medir_prancha`, 0.3.0).
    O backend não dá handle para o valor informado (o lugar no desenho não vale mais); quando o
    valor informado é o que o MCP mediu, o lugar é o de onde ele saiu. `medidas`:
    {campo: {valor, handles}} gravado no envio. Valor diferente (o terreno do RGI venceu a
    medida, ou a pessoa respondeu outro) fica sem lugar."""
    if not medidas:
        return p
    itens = []
    for item in p.get("itens") or []:
        lugares = []
        for lugar in item.get("lugares") or []:
            medida = medidas.get(lugar.get("campo")) if lugar.get("informado") and not lugar.get("handles") else None
            valor = lugar.get("valor")
            if (isinstance(medida, dict) and isinstance(valor, (int, float)) and not isinstance(valor, bool)
                    and abs(float(valor) - float(medida.get("valor", math.nan))) < 0.005):
                lugar = {**lugar, "handles": [str(h) for h in medida.get("handles") or []]}
            lugares.append(lugar)
        itens.append({**item, "lugares": lugares})
    return {**p, "itens": itens}


def _outras_regioes(item: dict) -> list[dict]:
    outras = item.get("outrasRegioes")
    return [r for r in outras if isinstance(r, dict)] if isinstance(outras, list) else []


def onde_olhar(item: dict) -> str | None:
    """Os rótulos de todos os lugares do item, a `regiao` primeiro, sem repetir: "Planta baixa",
    "Planta baixa e Corte", "Carimbo, Corte e Fachada". Sem lugar nenhum, None."""
    regiao = item.get("regiao") if isinstance(item.get("regiao"), dict) else None
    rotulos = _sem_repetir(str(r.get("rotulo")).strip() for r in [regiao or {}, *_outras_regioes(item)]
                           if r.get("rotulo") and str(r.get("rotulo")).strip())
    if not rotulos:
        return None
    return rotulos[0] if len(rotulos) == 1 else f"{', '.join(rotulos[:-1])} e {rotulos[-1]}"


def linha_do_item(item: dict) -> Linha:
    regiao = item.get("regiao") if isinstance(item.get("regiao"), dict) else None
    return Linha(
        numero=item["ordem"] + 1,
        situacao=situacao_apresentada(item),
        titulo=str(item.get("titulo") or item["texto"]),
        texto=item["texto"],
        handles=handles_do_item(item),
        regiao=regiao_achada(regiao),
        outras_regioes=[r for r in map(regiao_achada, _outras_regioes(item)) if r],
        onde_olhar=onde_olhar(item),
        faltando=list(item.get("faltando") or []),
        aguarda_gatilho=item.get("aguardaGatilho") or None,
    )


def linhas_apresentadas(p: dict, situacoes) -> list[Linha]:
    """As linhas do parecer nas situações pedidas, na ordem do parecer, menos as que o responsável
    já resolveu na web (conferiu, contestou ou marcou "não se aplica")."""
    return [linha_do_item(i) for i in p.get("itens") or []
            if situacao_apresentada(i) in situacoes and not resolvido_pelo_responsavel(i)]


def linha_da_conta(conta) -> str | None:
    """O que a conta do responsável (feita na web) diz no quadro: quanto falta para fechar, ou que
    ele fechou a análise. None sem a conta (backend antigo, parecer sem resultado)."""
    if not isinstance(conta, dict) or not isinstance(conta.get("faltam"), int):
        return None
    if conta.get("statusDoResponsavel") == "aprovado_pelo_responsavel":
        return "APROVADO PELO RESPONSÁVEL (análise fechada no Prancha Ok)"
    resolvidos = conta.get("resolvidos") or {}
    decididos = sum(v for k, v in resolvidos.items() if k != "peloPrancha" and isinstance(v, int))
    decididos += conta.get("naoSeAplicaPorVoce") or 0
    return (f"faltam {conta['faltam']} para fechar"
            + (f"; {decididos} respondidos pelo responsável, sem nuvem" if decididos else ""))


def pior(situacoes) -> str:
    return min(situacoes, key=ORDEM.index)


def _rotulo_curto(linha: Linha) -> str:
    return f"[{linha.numero}] {ROTULO[linha.situacao]}: {linha.titulo}"


def marca_do_handle(handle: str, linhas: list[Linha]) -> tuple[str, int, str]:
    """(handle, cor, rótulo) da nuvem de um handle: os itens dele, com a cor do pior."""
    return (handle, COR[pior(x.situacao for x in linhas)], "; ".join(_rotulo_curto(x) for x in linhas))


def marcas_por_handle(linhas: list[Linha]) -> list[tuple[str, int, str]]:
    """(handle, cor, rótulo) por handle: itens no mesmo lugar dividem a nuvem, com a cor do
    pior. O rótulo é cortado depois (pedido.marca), para caber numa linha do pedido."""
    por_handle: dict[str, list[Linha]] = {}
    for linha in linhas:
        for h in linha.handles:
            por_handle.setdefault(h, []).append(linha)
    return [marca_do_handle(h, ls) for h, ls in por_handle.items()]


def chave_regiao(regiao: dict) -> tuple:
    return (regiao["handleTitulo"], tuple(regiao["caixa"]) if regiao["caixa"] else None, regiao["espaco"])


def marcas_por_regiao(linhas: list[Linha]) -> tuple[list[tuple], list[dict]]:
    """Uma nuvem por região, com os itens dela: (handleTitulo, caixa, espaco, cor, rótulo) e,
    na mesma ordem, {rotulo da região, itens: [números]}. O rótulo da nuvem começa pelos
    números, que sobrevivem ao corte: "Planta de situação - itens 3, 7, 12 - [3] ERRO: ...".
    O item de mais de um lugar (rodada 5: "planta baixa e corte") entra na nuvem de cada um."""
    grupos: dict[tuple, tuple[str, list[Linha]]] = {}
    for linha in linhas:
        for regiao in linha.regioes:
            _, ls = grupos.setdefault(chave_regiao(regiao), (regiao["rotulo"], []))
            if linha not in ls:
                ls.append(linha)
    marcas, grupos_saida = [], []
    for (titulo, caixa, espaco), (nome, ls) in grupos.items():
        nomes = ", ".join(str(x.numero) for x in ls)
        rotulo = (f"{nome} - {'item' if len(ls) == 1 else 'itens'} {nomes} - "
                  + "; ".join(_rotulo_curto(x) for x in ls))
        marcas.append((titulo, list(caixa) if caixa else None, espaco, COR[pior(x.situacao for x in ls)], rotulo))
        grupos_saida.append({"rotulo": nome, "itens": [x.numero for x in ls]})
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


def linhas_quadro(p: dict, linhas: list[Linha], marcados: set[int], situacao_parecer: str,
                  chamadas: frozenset[int] | set[int] = frozenset()) -> list[str]:
    """Linhas do quadro-resumo (uma por parágrafo do MTEXT). Erros vão todos; dúvidas também,
    mas as que esperam o mesmo dado numa linha só ("falta: Pé-direito...: itens 3, 7, 12");
    "(nuvem)" nos que ganharam nuvem e "(chamada)" nos que só ganharam chamada (`chamadas`, 0.3.4:
    o rótulo da chamada não tem o título, então o conferir à mão com chamada também vem aqui). As perguntas sobre o projeto vão uma por resposta, e as sobre
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
    if conta := linha_da_conta(p.get("contaDoResponsavel")):
        cabecalho.append(conta)
    if presentes:
        cabecalho.append(("nuvens e chamadas: " if chamadas else "nuvens: ") + ", ".join(NOME_COR[s] for s in presentes))
    com_nuvem = sum(1 for linha in linhas if linha.numero in marcados)
    if chamadas:
        cabecalho.append(f"{com_nuvem} de {len(linhas)} itens com nuvem ou chamada no desenho; os outros estão aqui")
    else:
        cabecalho.append(f"{com_nuvem} de {len(linhas)} itens com nuvem no desenho; os outros estão aqui")
    if perguntas:
        cabecalho.append(f"{sum(len(g['itens']) for g in perguntas)} itens esperam resposta: responda no "
                         "Prancha Ok ou pelo assistente")
    cabecalho.append("")

    def nuvem(linha: Linha) -> str:
        if linha.numero in chamadas:
            return " (chamada)"
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
    conferir = [item(x, x.titulo) for x in linhas
                if x.situacao == "conferir_a_mao" and (x.numero not in marcados or x.numero in chamadas)]

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
