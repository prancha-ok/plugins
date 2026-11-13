"""O parecer em tabela para o chat (DAV-16, call de 26/10/2026: "mostrar a revisão numa tabela com o que está certo
e o que está errado, para bater o olho rápido").

A tabela sai pronta daqui, em markdown, e o assistente só a mostra: assim os números são os das nuvens e do
`ir_para_item` (ordem + 1), as linhas são as mesmas que `marcas` apresenta no desenho (sem o que o responsável já
resolveu na web) e nada some nem se inventa ao passar de JSON para texto. Uma linha por item apresentado, na ordem
de gravidade (em desacordo, dúvida, pergunta sobre o projeto, conferir à mão); o que está certo (atendidos) e o que
fica de fora (não se aplicam, cadastrais, resolvidos pelo responsável) vão contados embaixo.
"""
from __future__ import annotations

from . import marcas

CABECALHO = "| Nº | Item | Situação | Onde olhar |\n|---:|---|---|---|"
SITUACAO = {"errado": "Em desacordo", "duvida": "Dúvida", "pergunta": "Pergunta", "conferir_a_mao": "Conferir à mão"}
# O "não" e o "corrigido" do responsável continuam em desacordo (marcas.situacao_apresentada), com o porquê.
NOTA_DO_RESPONSAVEL = {"nao": " (responsável conferiu: não)", "corrigido": " (corrigido na prancha: envie de novo)"}
# Linhas da tabela, no máximo (como o quadro-resumo do desenho): o que passa sai do conferir à mão, nunca do resto.
MAXIMO_LINHAS = 60
MAXIMO_TITULO = 90


def cadastral(item: dict) -> bool:
    """Documento do processo (RGI, ART, taxa...), não do projeto: fica à parte, como no site (setor "cadastro" ou
    pergunta sem condição; web: lib/organizarParecer.ts)."""
    return not item.get("aguardaGatilho") and (item.get("setor") == "cadastro" or item.get("situacao") == "pergunta")


def _celula(texto: str, maximo: int | None = None) -> str:
    """Texto numa célula: uma linha, sem a barra que quebraria a coluna."""
    limpo = " ".join(str(texto).split()).replace("|", "/")
    if maximo and len(limpo) > maximo:
        limpo = limpo[:maximo - 1].rstrip() + "…"
    return limpo


def _linha(item: dict) -> str:
    situacao = SITUACAO[marcas.situacao_apresentada(item)] + NOTA_DO_RESPONSAVEL.get(
        marcas.escolha_do_responsavel(item) or "", "")
    titulo = _celula(item.get("titulo") or item.get("texto") or "", MAXIMO_TITULO)
    return f"| {item['ordem'] + 1} | {titulo} | {situacao} | {_celula(marcas.onde_olhar(item) or '-')} |"


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def do_parecer(p: dict, contagem: dict, situacao: str) -> str:
    """A tabela do parecer pronto (`p` como a rota /cliente/v1 devolve) e, embaixo, a conta do que ficou fora dela.
    `contagem` é a do resumo (servidor._contagem: por item, como o site); `situacao`, o status para ler."""
    ordem = {s: n for n, s in enumerate(marcas.ORDEM)}
    itens = sorted((i for i in p.get("itens") or []
                    if marcas.situacao_apresentada(i) in SITUACAO and not marcas.resolvido_pelo_responsavel(i)
                    and not cadastral(i)),
                   key=lambda i: (ordem[marcas.situacao_apresentada(i)], i["ordem"]))
    fixos = [i for i in itens if marcas.situacao_apresentada(i) != "conferir_a_mao"]
    conferir = [i for i in itens if marcas.situacao_apresentada(i) == "conferir_a_mao"]
    cabem = max(0, MAXIMO_LINHAS - len(fixos))
    mostrados, cortados = fixos + conferir[:cabem], len(conferir[cabem:])

    partes = [f"**Parecer nº {p.get('numero')}: {situacao}**", ""]
    if mostrados:
        partes += [CABECALHO, *(_linha(i) for i in mostrados)]
    else:
        partes.append("Nada em desacordo, em dúvida, em pergunta nem para conferir à mão.")
    if cortados:
        partes += ["", f"... e mais {_plural(cortados, 'item', 'itens')} para conferir à mão (lista completa no "
                       f"Prancha Ok{': ' + p['url'] if p.get('url') else ''})."]

    fora = [_plural(contagem.get("atendidos", 0), "atendido (certo pelo Prancha Ok)",
                    "atendidos (certos pelo Prancha Ok)")]
    if contagem.get("dispensados"):
        fora.append(_plural(contagem["dispensados"], "dispensado", "dispensados"))
    resolvidos = sum(1 for i in p.get("itens") or [] if marcas.resolvido_pelo_responsavel(i))
    if resolvidos:
        fora.append(_plural(resolvidos, "resolvido pelo responsável no site", "resolvidos pelo responsável no site"))
    if contagem.get("cadastrais"):
        fora.append(_plural(contagem["cadastrais"], "cadastral (documentos do processo, à parte)",
                            "cadastrais (documentos do processo, à parte)"))
    if contagem.get("naoSeAplicam") is not None:
        fora.append(f"{contagem['naoSeAplicam']} não se aplicam a este projeto")
    partes += ["", "Fora da tabela: " + "; ".join(fora) + "."]
    return "\n".join(partes)
