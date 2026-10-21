"""O desenho de partida do projeto do zero (0.6.0): as entidades do Prancha Ok como itens do comando `desenhar`.

O backend monta o desenho (packages/backend/convex/lib/desenhoDoTerreno.ts: o lote, os afastamentos, as medidas, a
rua, o norte, o título e o quadro) como uma lista de entidades simples, a mesma que o site escreve em DXF. Aqui cada
entidade vira um item do pedido (o formato está no prancha_ok.lsp, seção "desenhar"): um dado por linha, nenhuma
linha acima de LIMITE_LINHA; o que não cabe numa linha continua em itens "+" (mais pontos, mais texto). Os itens vão
em pedidos de até MAXIMO_ITENS linhas, sem cortar uma entidade entre dois pedidos; cada pedido é um grupo de
desfazer no AutoCAD.

Só em camadas PRANCHAOK-* (nunca a das marcas, PRANCHAOK-PARECER, que o `limpar` apaga e o motor ignora): o
Prancha Ok só acrescenta, e o que a pessoa desenhou fica como está. O LISP confere de novo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .pedido import LIMITE_LINHA, cabe, lisp, pedacos, texto_mtext

CAMADA_DAS_MARCAS = "PRANCHAOK-PARECER"
# Linhas por pedido (um grupo de desfazer cada). O terreno do zero tem umas 60 entidades: cabe num só.
MAXIMO_ITENS = 400
# Caracteres do TEXT depois da conversão para ASCII (o AutoCAD guarda até 255 numa string de entidade).
MAXIMO_TEXTO = 250
# Pedaço de texto de um item: cabe numa linha "+" com folga.
PEDACO_TEXTO = 100
TIPOS = ("polilinha", "linha", "arco", "texto", "cota")


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


def itens_da_entidade(e) -> list[list] | None:
    """Os itens do pedido de uma entidade do contrato, ou None se ela não é desenhável (tipo desconhecido, camada
    fora das PRANCHAOK-*, número que não é número)."""
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
    de, ate, linha = _ponto(e.get("de")), _ponto(e.get("ate")), _ponto(e.get("linha"))
    pedacos_texto = _pedacos_do_texto(e.get("texto"))
    if de is None or ate is None or linha is None or pedacos_texto is None or math.dist(de, ate) <= 1e-6:
        return None
    return _empacotar(["cota", camada, *de, *ate, *linha], pedacos_texto)


def _itens_das_camadas(camadas) -> list[list]:
    saida = []
    for c in camadas or []:
        if not isinstance(c, dict) or not camada_permitida(c.get("nome")):
            continue
        cor = c.get("cor")
        tipo_linha = c.get("tipoLinha") or "CONTINUOUS"
        item = ["camada", c["nome"], cor if isinstance(cor, int) and not isinstance(cor, bool) and 0 < cor < 256
                else 7, tipo_linha if isinstance(tipo_linha, str) else "CONTINUOUS"]
        if c.get("imprime") is False:  # a camada que não plota (o contorno livre dos cômodos da planta)
            item.append(0)
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
            prefixo: str | None = None) -> Pedidos:
    """O desenho do contrato em pedidos do `desenhar`. `so_se_vazio`: a camada que, com algo nela, faz o 1º pedido
    não desenhar nada (o terreno já está no desenho). `prefixo`: só as camadas e entidades com esse começo de nome
    (a planta só desenha nas PRANCHAOK-PLANTA-*: o terreno não vai de novo). As camadas vão no 1º pedido; o zoom, no
    último."""
    maximo_itens = maximo_itens or MAXIMO_ITENS

    def da_vez(nome) -> bool:
        return prefixo is None or (isinstance(nome, str) and nome.upper().startswith(prefixo.upper()))

    blocos, ignoradas = [], 0
    for e in desenho.get("entidades") or []:
        itens = itens_da_entidade(e) if isinstance(e, dict) and da_vez(e.get("camada")) else None
        if itens is None:
            ignoradas += 1
        else:
            blocos.append(itens)
    camadas = [c for c in desenho.get("camadas") or [] if isinstance(c, dict) and da_vez(c.get("nome"))]
    primeiro = ([["se-vazio", so_se_vazio]] if so_se_vazio else []) + _itens_das_camadas(camadas)
    saida = [primeiro]
    for bloco in blocos:
        if saida[-1] and len(saida[-1]) + len(bloco) > maximo_itens:
            saida.append([])
        saida[-1].extend(bloco)
    if zoom := _zoom(desenho.get("extensao")):
        if len(saida[-1]) + 1 > maximo_itens:
            saida.append([])
        saida[-1].append(zoom)
    return Pedidos(pedidos=[p for p in saida if p], ignoradas=ignoradas, enviadas=len(blocos))
