"""As camadas de arquitetura do autocad-mcp-pro 1.6.0 (ISO 13567: A-WALL-E-N...) com os nomes PRANCHAOK-PLANTA-*: o
conector só acrescenta em camadas PRANCHAOK-* (D5=c), e um escritório que já usa a ISO 13567 tem camadas com os nomes
dele. Mesmos tipos de linha; as cores e as espessuras (ISO 128) das camadas que o motor do Prancha Ok também desenha
(COR_E_ESPESSURA) ficam as dele: o `arch_plan_from_spec` cria todas as camadas do arch, e o `desenhar` do conector não
mexe em camada que já existe, então a mesma planta plota igual pelos dois caminhos. Muda os objetos no lugar (listas e
dicts), porque draw.py, rooms.py, catalogue.py, critique.py e engineering/layers.py guardam referências a eles.

`conferir()` só olha; `aplicar()` confere e muda. Idempotente.
"""
from __future__ import annotations

import importlib

NOMES = {
    "A-WALL-E-N": "PRANCHAOK-PLANTA-PAREDES",
    "A-WALL-H-N": "PRANCHAOK-PLANTA-HACHURA",
    "A-DOOR-E-N": "PRANCHAOK-PLANTA-PORTAS",
    "A-WIND-E-N": "PRANCHAOK-PLANTA-JANELAS",
    "A-STAIR-E-N": "PRANCHAOK-PLANTA-ESCADAS",
    "A-FURN-E-N": "PRANCHAOK-PLANTA-MOBILIARIO",
    "A-SANR-E-N": "PRANCHAOK-PLANTA-LOUCAS",
    "A-GRID-E-N": "PRANCHAOK-PLANTA-EIXOS",
    "A-ROOM-T-N": "PRANCHAOK-PLANTA-TEXTOS",
    "A-DIMEN-T-N": "PRANCHAOK-PLANTA-COTAS",
    "A-SYMB-T-N": "PRANCHAOK-PLANTA-SIMBOLOS",
    "A-OVHD-E-N": "PRANCHAOK-PLANTA-PROJECAO",
    "A-CONST-E-N": "PRANCHAOK-PLANTA-CONST",  # com CONST: a crítica iso128 dele pula a camada de rascunho pelo nome
}


#: (cor ACI, espessura mm) das camadas do motor (services/engine/.../planta/gerar.py, CAMADAS, e mobiliario.py,
#: CAMADA_MOBILIARIO; contrato 0.7.0 C2: 0,25 esquadrias, 0,18 mobiliário, 0,13 cotas e textos). As outras ficam as
#: do autocad-mcp-pro (as paredes, a hachura e as janelas já são iguais).
COR_E_ESPESSURA = {
    "PRANCHAOK-PLANTA-PORTAS": (2, 0.25),
    "PRANCHAOK-PLANTA-MOBILIARIO": (8, 0.18),
    "PRANCHAOK-PLANTA-TEXTOS": (7, 0.13),
    "PRANCHAOK-PLANTA-COTAS": (3, 0.13),
}


def aplicado() -> bool:
    A = importlib.import_module("engineering.arch.layers")
    return all(n in NOMES.values() for n in A.ARCH_ROLE_LAYER.values())


def conferir() -> None:
    """Levanta RuntimeError se as camadas da 1.6.0 mudaram. Não muda nada."""
    if aplicado():
        return
    A = importlib.import_module("engineering.arch.layers")
    if {r[0] for r in A.ARCH_LAYERS} - {"0"} != set(NOMES):
        raise RuntimeError("as camadas de arquitetura do autocad-mcp-pro mudaram: confira camadas.NOMES")
    if not set(A.ARCH_ROLE_LAYER.values()) | set(A.ARCH_LAYER_ROLES.values()) <= set(NOMES):
        raise RuntimeError("os papéis das camadas do autocad-mcp-pro mudaram: confira camadas.NOMES")
    L = importlib.import_module("engineering.layers")
    if "arch" not in L.LAYER_ROLES:
        raise RuntimeError("engineering.layers.LAYER_ROLES['arch'] sumiu: confira o ajuste das camadas")
    R = importlib.import_module("engineering.arch.rooms")
    if not isinstance(getattr(R, "WALL_LAYER_KEYWORDS", None), tuple):
        raise RuntimeError("rooms.WALL_LAYER_KEYWORDS mudou: confira o ajuste das camadas")


def aplicar() -> None:
    conferir()
    if aplicado():
        return
    A = importlib.import_module("engineering.arch.layers")
    linhas = []
    for nome, cor, tipo, espessura, descricao in A.ARCH_LAYERS:
        nome = NOMES.get(nome, nome)
        cor, espessura = COR_E_ESPESSURA.get(nome, (cor, espessura))
        linhas.append((nome, cor, tipo, espessura, descricao))
    A.ARCH_LAYERS[:] = linhas
    for d in (A.ARCH_ROLE_LAYER, A.ARCH_LAYER_ROLES):
        for k, v in list(d.items()):
            d[k] = NOMES.get(v, v)
    defs = {}
    for k, (cor, tipo, espessura) in A.ARCH_LAYER_DEFS.items():
        nome = NOMES.get(k, k)
        cor, espessura = COR_E_ESPESSURA.get(nome, (cor, espessura))
        defs[nome] = (cor, tipo, espessura)
    A.ARCH_LAYER_DEFS.clear()
    A.ARCH_LAYER_DEFS.update(defs)
    L = importlib.import_module("engineering.layers")
    L.LAYER_ROLES["arch"] = dict(A.ARCH_LAYER_ROLES)
    R = importlib.import_module("engineering.arch.rooms")
    if "PAREDE" not in R.WALL_LAYER_KEYWORDS:  # arch_rooms_detect acha as nossas paredes sem `layers`
        R.WALL_LAYER_KEYWORDS = (*R.WALL_LAYER_KEYWORDS, "PAREDE")
