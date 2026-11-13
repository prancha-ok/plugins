"""O parecer é do desenho aberto? Conferido antes de marcar (máquinas de estado, item 5: o conector marcava o último
parecer enviado deste computador em qualquer desenho aberto, e as marcas de outro arquivo apagavam as dele).

Vale também para ir até um item (`ir_para_item`: o handle de outro arquivo selecionaria outra coisa) e para as letras
do terreno (`conferir_terreno`: escritas e lidas no desenho do parecer). Cada um diz, no fim da frase, o que não fez.

Puro: recebe o parecer (rota GET /cliente/v1/pareceres/<id>: `numero`, `nomeArquivo`), a origem que este computador
guardou ao enviar (`{projetoId, projeto, arquivo}`, ou None para o parecer que não saiu daqui), o desenho aberto
(`autocad.info()`: `temNome`, `arquivo`) e o vínculo dele (`{projetoId, projeto}` ou None). Devolve a frase do porquê
não marcar, ou None quando o parecer é deste desenho.
"""
from __future__ import annotations

from pathlib import PureWindowsPath

# O nome que a rota devolve quando o arquivo do parecer não existe mais.
SEM_NOME = "—"

DEPOIS = (" Não marquei nada (o desenho aberto não foi alterado). Abra o desenho desse parecer e peça de novo, ou "
          "envie o desenho aberto (`enviar_prancha`) para ter um parecer dele.")
DEPOIS_IR = (" Não fui até o item (os lugares dele são do desenho do parecer). Abra esse desenho e peça de novo.")
DEPOIS_TERRENO = (" Não escrevi as letras dos lados nem gravei o terreno (o desenho aberto não foi alterado). Abra o "
                  "desenho desse parecer e peça de novo.")


def caminho(arquivo: str | None) -> str:
    """O caminho para comparar: separadores do Windows e sem diferença de maiúsculas (o Windows não diferencia)."""
    return str(PureWindowsPath(arquivo)).lower() if arquivo else ""


def _nome(arquivo: str | None) -> str:
    return PureWindowsPath(arquivo).name if arquivo else ""


def motivo_para_nao_marcar(parecer: dict, origem: dict | None, desenho: dict, vinculo: dict | None,
                           depois: str = DEPOIS) -> str | None:
    numero = parecer.get("numero") or parecer.get("parecerId") or "?"
    nome_do_parecer = _nome((origem or {}).get("arquivo")) or str(parecer.get("nomeArquivo") or "")
    aberto = desenho.get("arquivo") or ""
    if desenho.get("temNome") is False:
        return (f"O desenho aberto ainda não foi salvo com um nome, e o parecer nº {numero} é da prancha "
                f"\"{nome_do_parecer or 'enviada'}\"." + depois)
    projeto_do_parecer = (origem or {}).get("projetoId")
    projeto_aberto = (vinculo or {}).get("projetoId")
    if projeto_do_parecer and projeto_aberto and projeto_do_parecer != projeto_aberto:
        da_prancha = f"da prancha \"{nome_do_parecer}\", " if nome_do_parecer else ""
        return (f"O parecer nº {numero} é {da_prancha}do projeto \"{origem.get('projeto') or projeto_do_parecer}\", "
                f"e o desenho aberto, \"{_nome(aberto)}\", está vinculado ao projeto "
                f"\"{vinculo.get('projeto') or projeto_aberto}\"." + depois)
    if (origem or {}).get("arquivo"):
        if caminho(origem["arquivo"]) != caminho(aberto):
            return (f"O parecer nº {numero} foi enviado do desenho \"{origem['arquivo']}\", e o aberto é "
                    f"\"{aberto}\"." + depois)
        return None
    nome_guardado = str(parecer.get("nomeArquivo") or "")
    if nome_guardado and nome_guardado != SEM_NOME and nome_guardado.lower() != _nome(aberto).lower():
        return (f"O parecer nº {numero} é da prancha \"{nome_guardado}\", e o desenho aberto é "
                f"\"{_nome(aberto)}\"." + depois)
    return None
