"""O português do Brasil no autocad-mcp-pro 1.6.0 (MIT, Umutcan Edizsalan), acrescentado em tempo de execução antes
de subir o servidor dele (versão fixa no uv.lock). Conferido símbolo a símbolo contra a 1.6.0:

- engineering/arch/lang.py: LANGS (tupla, troca), _VOCAB e _TAG_PREFIX (dicts, acrescenta "pt"), fmt_number (a
  vírgula só no "tr": troca por uma que trata o "pt" como o "tr"). fmt_area_m2, vocab, tag_prefix e _lang leem os
  globais do módulo: valem sozinhos.
- Quem fez `from engineering.arch.lang import X` guardou o objeto antigo: engineering.arch (LANGS, fmt_number),
  arch.spec (LANGS), arch.rooms (LANGS), arch.schedule (LANGS, fmt_number), arch.catalogue (LANGS), arch.symbols
  (fmt_number). stairs e draw só importam vocab/tag_prefix (leem os dicts).
- arch.schedule._mm: nos quadros em pt as medidas saem em metros ("0,80"), como o escritório brasileiro escreve.
- arch.catalogue: o rótulo e a busca só conhecem en/tr; acrescenta os nomes em português (busca "cama", "geladeira").
- backends.ezdxf_backend._HEADER_DIMVARS: sem o $DIMLFAC, o ezdxf não leva o fator de escala da cota à cota
  (no AutoCAD de verdade o DIMLFAC do desenho vale); acrescenta, para "6,30" em vez de "6300" também sem AutoCAD.

`conferir()` só olha (levanta se algo mudou); `aplicar()` confere e muda. Idempotente. O lançador confere todos os
ajustes antes de aplicar o primeiro (tudo ou nada).
"""
from __future__ import annotations

import importlib

VERSAO_CONFERIDA = "1.6.0"

# Curtas: as colunas dos quadros dele têm 20 mm de papel com letra de 2,5 mm (≈ 9 letras).
VOCAB_PT = {
    "door_schedule": "QUADRO DE PORTAS",
    "window_schedule": "QUADRO DE JANELAS",
    "room_schedule": "QUADRO DE AMBIENTES",
    "tag": "CÓD.",
    "width": "LARG.",
    "height": "ALT.",
    "sill": "PEITORIL",
    "swing": "ABRE P/",
    "hand": "MÃO",
    "wall": "PAREDE",
    "number": "Nº",
    "name": "AMBIENTE",
    "area": "ÁREA",
    "total": "TOTAL",
    "up": "SOBE",
    "down": "DESCE",
    "north": "N",
    "level": "NÍVEL",
    "in": "DENTRO",
    "out": "FORA",
    "left": "ESQ.",
    "right": "DIR.",
}
TAG_PT = {"door": "P", "window": "J"}
CATALOGO_PT = {
    "single_bed": "cama de solteiro",
    "double_bed": "cama de casal",
    "wardrobe": "guarda-roupa",
    "sofa_3_seat": "sofá de 3 lugares",
    "armchair": "poltrona",
    "chair": "cadeira",
    "dining_table_4": "mesa de jantar de 4 lugares",
    "desk": "escrivaninha",
    "kitchen_counter": "bancada de cozinha",
    "fridge": "geladeira",
    "bookshelf": "estante",
    "nightstand": "criado-mudo",
    "coffee_table": "mesa de centro",
    "wc": "bacia sanitária com caixa acoplada",
    "bidet": "bidê",
    "wall_basin": "lavatório",
    "shower_tray": "box do chuveiro",
    "bathtub": "banheira",
    "kitchen_sink": "pia de cozinha",
    "washing_machine": "máquina de lavar",
}
_IMPORTADORES = ("engineering.arch", "engineering.arch.spec", "engineering.arch.rooms", "engineering.arch.schedule",
                 "engineering.arch.catalogue", "engineering.arch.symbols")


def _e_pt(lang) -> bool:
    return isinstance(lang, str) and lang.strip().lower() == "pt"


def aplicado() -> bool:
    return "pt" in importlib.import_module("engineering.arch.lang").LANGS


def conferir() -> None:
    """Levanta RuntimeError se a versão ou algum símbolo que o ajuste usa mudou. Não muda nada."""
    from version import __version__  # o version.py de topo do pacote dele

    if __version__ != VERSAO_CONFERIDA:
        raise RuntimeError(f"o português foi conferido na {VERSAO_CONFERIDA}; o autocad-mcp-pro instalado é "
                           f"{__version__}: confira lang.py e quem importa dele antes de subir a versão")
    if aplicado():
        return
    L = importlib.import_module("engineering.arch.lang")
    if set(VOCAB_PT) != set(L._VOCAB["en"]) or set(TAG_PT) != set(L._TAG_PREFIX["en"]):
        raise RuntimeError("o vocabulário do autocad-mcp-pro mudou: confira o VOCAB_PT")
    if not callable(getattr(importlib.import_module("engineering.arch.schedule"), "_mm", None)):
        raise RuntimeError("schedule._mm sumiu: confira o ajuste dos quadros")
    if "tr" not in L.fmt_number.__code__.co_consts:
        raise RuntimeError("fmt_number não decide mais a vírgula pelo \"tr\": confira o ajuste")
    C = importlib.import_module("engineering.arch.catalogue")
    if set(CATALOGO_PT) != set(C.CATALOGUE_NAMES):
        raise RuntimeError("o catálogo do autocad-mcp-pro mudou: confira o CATALOGO_PT")
    for nome in ("_row", "catalogue", "_fold", "_BY_NAME", "ITEMS"):
        if not hasattr(C, nome):
            raise RuntimeError(f"catalogue.{nome} sumiu: confira o ajuste do catálogo")
    E = importlib.import_module("backends.ezdxf_backend")
    if not isinstance(getattr(E, "_HEADER_DIMVARS", None), dict):
        raise RuntimeError("ezdxf_backend._HEADER_DIMVARS sumiu: confira o ajuste do DIMLFAC")


def aplicar() -> None:
    conferir()
    if aplicado():
        return
    L = importlib.import_module("engineering.arch.lang")
    C = importlib.import_module("engineering.arch.catalogue")
    SC = importlib.import_module("engineering.arch.schedule")
    E = importlib.import_module("backends.ezdxf_backend")
    # Tudo conferido: daqui em diante só muda.
    L._VOCAB["pt"] = dict(VOCAB_PT)
    L._TAG_PREFIX["pt"] = dict(TAG_PT)
    langs = (*L.LANGS, "pt")
    original = L.fmt_number

    def fmt_number(value, lang, decimals=2):
        return original(value, "tr" if _e_pt(lang) else lang, decimals)

    fmt_number.__doc__ = original.__doc__
    L.LANGS = langs
    L.fmt_number = fmt_number
    for nome in _IMPORTADORES:
        m = importlib.import_module(nome)
        if hasattr(m, "LANGS"):
            m.LANGS = langs
        if hasattr(m, "fmt_number"):
            m.fmt_number = fmt_number

    row, busca = C._row, C.catalogue

    def _row(item, lang):
        linha = row(item, "en" if _e_pt(lang) else lang)
        linha["label_pt"] = CATALOGO_PT[item.name]
        if _e_pt(lang):
            linha["label"] = CATALOGO_PT[item.name]
        return linha

    def catalogue(query=None, family=None, *, lang="en"):
        if not _e_pt(lang):
            return tuple(_row(C._BY_NAME[a["name"]], lang) for a in busca(query, family, lang=lang))
        # Em pt: a validação da família é a dele; a busca é no nome, no rótulo em inglês e no em português (sem o
        # turco: "cama" achava "çamaşır makinesi", a máquina de lavar).
        busca(None, family, lang="en")
        palavras = C._fold(query).split() if query else []
        return tuple(_row(item, lang) for item in C.ITEMS if (family is None or item.family == family) and all(
            p in C._fold(f"{item.name.replace('_', ' ')} {item.label_en} {CATALOGO_PT[item.name]}") for p in palavras))

    mm = SC._mm

    def _mm(value, lang):
        # Nos quadros em pt as medidas vão em metros, como o escritório brasileiro escreve (0,80 × 2,10), não em mm.
        if _e_pt(lang) and value is not None:
            return fmt_number(float(value) / 1000.0, lang, 2)
        return mm(value, lang)

    SC._mm = _mm
    C._row, C.catalogue = _row, catalogue
    # O pacote reexporta a função `catalogue` com o mesmo nome do submódulo (engineering/arch/__init__.py).
    importlib.import_module("engineering.arch").catalogue = catalogue
    E._HEADER_DIMVARS.setdefault("dimlfac", ("$DIMLFAC", 1.0, float))
