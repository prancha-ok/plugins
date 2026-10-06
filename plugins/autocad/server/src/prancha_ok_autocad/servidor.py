"""Servidor MCP (stdio): as ferramentas que o Claude Code / Codex chamam."""
from __future__ import annotations

import math
import time
import webbrowser
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__, atualizacao, autocad, backend, chamadas, instalacao, marcas, medidas
from .autocad import AutocadIndisponivel
from .backend import ErroBackend, NaoConectado
from .locais import api, empacotado, gravar_estado, ler_estado, nome_maquina, pasta, pasta_ipc, pasta_lisp

INSTRUCOES = """\
Prancha Ok confere pranchas de arquitetura contra a legislação do município e emite um parecer
(Aprovado, Pendente ou Em revisão humana). Este MCP liga o AutoCAD aberto a ele. Funciona só
no AutoCAD (2024 ou mais novo, completo ou LT), não no GstarCAD, BricsCAD, ZWCAD e outros
compatíveis: nesses, a pessoa envia o desenho pelo site. O desenho aberto pode ser DWG ou DXF.

Fluxo, sempre nesta ordem: `conectar` (uma vez por computador) -> `vincular_projeto` (uma vez por
desenho) -> peça para salvar o desenho -> `enviar_prancha` -> o Prancha Ok lê a prancha e devolve a
PRÉVIA: as medidas que leu (com letras: A, B, C...) e as perguntas que o parecer faria (numeradas:
1, 2, 3...). Mostre as duas listas e peça a resposta em bloco: "tudo certo", "tudo certo menos B e
D", "só A e C estão certos", "1 sim, 2 2,50 m" ou "vou responder um a um" -> `confirmar_previa` com
as medidas confirmadas ou corrigidas e as respostas dadas -> sai um parecer só, já marcado no
desenho (nuvens, chamadas e quadro-resumo; `marcar_parecer` marca de novo) -> o arquiteto corrige ou
responde o que sobrou (`responder_itens`, que também marca) -> `enviar_prancha` de novo. Crítica ou
falso apontamento que a pessoa contar: `enviar_sugestao`. Se algo não funcionar: `diagnosticar`.

O parecer traz só o que vale para este projeto (o que não se aplica fica de fora, só contado):
- em desacordo (erro): a prancha contraria a referência do item;
- dúvida: falta informação na prancha; pergunte à pessoa;
- pergunta: sobre o projeto (há terraplenagem? corte de árvore?), respondida com "sim" ou "não",
  que decide quais itens valem; ou sobre documentos do processo (RGI, ART, taxa...), com "sim",
  "não" ou "não se aplica". As de documento não seguram o parecer: ficam à parte, para responder
  quando a pessoa tiver os documentos;
- conferir à mão: o Prancha Ok não prova sozinho (ex.: achou o texto, mas não dá para saber se
  está certo). A pessoa confere; nunca diga que está atendido.

Regras:
- Nunca altere o desenho. Quem corrige é o arquiteto; você explica o item e mostra onde está
  (`ir_para_item`). As marcas e o quadro-resumo ficam só na camada PRANCHAOK-PARECER, que não
  plota e que o Prancha Ok ignora na leitura.
- O parecer é um apoio: tudo passa por revisão humana. Não diga que algo está "aprovado pela
  prefeitura"; diga o que o Prancha Ok apontou, com a referência do item (a lei, ou "Sugestão
  referenciada" quando o item não vem de uma lei). Não invente outra fonte para o item.
- Dúvida é informação que a prancha não deu; pergunta é o que só a pessoa sabe. Pergunte e grave
  com `responder_itens`.
- Medidas: as da prévia são o que o Prancha Ok LEU da prancha. Mostre cada valor com de onde saiu e
  mande em `confirmar_previa` só as que a pessoa confirmou ou corrigiu: o valor é declarado por ela.
  `medir_prancha` (medição no AutoCAD) é opcional: serve para comparar quando a pessoa duvida de uma
  medida lida; nunca mande a medição sem o sim dela.
- Salvar o desenho (`enviar_prancha` com salvar=true) só com o "sim" da pessoa, perguntado uma vez.
- Custos estimados são estimativas: o valor final é da Prefeitura. Cite a lei de cada um.
- Prancha não reconhecida (`recusada`): o Prancha Ok não conferiu nada porque o desenho não parece
  uma prancha de legalização (ex.: projeto estrutural, prancha sem planta de situação ou sem
  corte). Diga o que faltou (`motivosRecusa`) e não marque nada no desenho. Esse envio não conta
  na cota de projetos.
"""

mcp = FastMCP("prancha-ok", instructions=INSTRUCOES)

SITUACAO = {"aprovado": "Aprovado", "pendente": "Pendente", "em_revisao": "Em revisão humana",
            "processando": "Processando", "falhou": "Falhou", "recusado": "Prancha não reconhecida",
            "aguardando_medidas": "Esperando a conferência da prévia"}
PRAZO_CONECTAR_S = 45
# Tempo total de uma ferramenta que espera o parecer (o cliente MCP pode cortar antes de 60 s).
PRAZO_PARECER_S = 50


def _erro(e: Exception) -> dict:
    return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- conexão

def _com_aviso_de_versao() -> dict:
    """{"atualizacao": {versao, mensagem}} quando o site tem versão mais nova e {"outroConector": texto} quando outro
    servidor do Prancha Ok roda ao mesmo tempo neste computador (instalacao.aviso_de_outro_servidor); {} senão."""
    saida = {}
    try:
        if aviso := atualizacao.aviso():
            saida["atualizacao"] = aviso
    except Exception:
        pass
    try:
        if duplicado := instalacao.aviso_de_outro_servidor():
            saida["outroConector"] = duplicado
    except Exception:
        pass
    return saida


@mcp.tool()
def conectar() -> dict:
    """Liga este computador à conta do Prancha Ok. Abre o navegador: a pessoa confere o código
    mostrado e aprova, escolhendo a empresa. Se ela ainda não aprovou quando esta ferramenta
    voltar, chame de novo (o mesmo código continua valendo por 10 minutos)."""
    try:
        if backend.token():
            try:
                return {"ok": True, "conectado": True, **backend.eu(), **_com_aviso_de_versao()}
            except NaoConectado:
                backend.esquecer_token()
        pedido = ler_estado().get("pedido")
        # O pedido guardado é do backend que o criou: trocar PRANCHA_OK_API não o reaproveita.
        if not pedido or pedido.get("api") != api() or pedido.get("expiraEm", 0) / 1000 < time.time() + 30:
            pedido = {**backend.abrir_pedido(nome_maquina()), "api": api()}
            gravar_estado(pedido=pedido)
            webbrowser.open(pedido["url"])
        limite = time.monotonic() + PRAZO_CONECTAR_S
        while time.monotonic() < limite:
            try:
                resposta = backend.buscar_token(pedido["segredo"])
            except ErroBackend as e:
                gravar_estado(pedido=None)
                motivo = "recusado no navegador" if e.codigo == "PEDIDO_RECUSADO" else "vencido"
                return {"ok": False, "erro": f"O pedido de conexão foi {motivo}. Chame `conectar` de novo."}
            if "token" in resposta:
                backend.guardar_token(resposta["token"])
                gravar_estado(pedido=None)
                return {"ok": True, "conectado": True, **backend.eu(), **_com_aviso_de_versao()}
            time.sleep(2)
        return {
            "ok": True,
            "conectado": False,
            "codigo": pedido["codigo"],
            "url": pedido["url"],
            "mensagem": f"Abra {pedido['url']} (já deve estar aberto no navegador), confira o código "
                        f"{pedido['codigo']} e clique em Conectar. Depois chame `conectar` de novo.",
        }
    except Exception as e:  # o assistente mostra o motivo; o servidor continua de pé
        return _erro(e)


def _aviso_confiavel(info: dict) -> str | None:
    confiaveis = str(info.get("trustedpaths") or "").replace("/", "\\").lower().split(";")
    if str(pasta_lisp()).lower() not in [c.strip().rstrip("\\") for c in confiaveis]:
        return (f"{pasta_lisp()} não está no TRUSTEDPATHS do AutoCAD. O MCP tenta pôr a cada comando; se "
                "continuar assim, acrescente a pasta em Opções > Arquivos > Locais confiáveis do AutoCAD.")
    return None


def _vinculo_lembrado(arquivo: str) -> dict | None:
    """Projeto para o qual este arquivo já foi enviado deste computador (reserva do vínculo no DWG)."""
    return (ler_estado().get("vinculos") or {}).get(arquivo.lower())


def _esquecer_vinculo(arquivo: str) -> None:
    vinculos = dict(ler_estado().get("vinculos") or {})
    if vinculos.pop(arquivo.lower(), None) is not None:
        gravar_estado(vinculos=vinculos)


def _vinculo_perdido(vinculo: dict, projetos: list) -> str:
    """O projeto do vínculo não está mais entre os da empresa (pente fino de 04/10/2026, item V: "quando o projeto
    é apagado no site, o desenho continua vinculado a ele sem aviso")."""
    nome = vinculo.get("projeto") or vinculo.get("projetoId")
    return (f"O projeto \"{nome}\", a que este desenho está vinculado, não existe mais no Prancha Ok (foi apagado "
            "no site, ou a conta saiu da empresa dele). Pergunte à pessoa em qual projeto enviar (`listar_projetos`) "
            "e vincule de novo com `vincular_projeto`." + ("" if projetos else " " + SEM_PROJETO))


def _lembrar_vinculo(arquivo: str, projeto_id: str, nome: str) -> None:
    if not arquivo:
        return
    vinculos = dict(ler_estado().get("vinculos") or {})
    vinculos[arquivo.lower()] = {"projetoId": projeto_id, "projeto": nome}
    gravar_estado(vinculos=vinculos)


@mcp.tool()
def status() -> dict:
    """AutoCAD (desenho aberto, salvo ou não, projeto vinculado) e conexão com o Prancha Ok."""
    saida: dict = {"ok": True}
    try:
        saida["autocad"] = autocad.info()
        if aviso := _aviso_confiavel(saida["autocad"]):
            saida["aviso"] = aviso
        lembrado = _vinculo_lembrado(saida["autocad"].get("arquivo") or "")
        if not saida["autocad"].get("vinculo") and lembrado:
            saida["vinculoLembrado"] = {
                **lembrado,
                "mensagem": f"Este desenho não tem vínculo gravado, mas já foi enviado ao projeto "
                            f"\"{lembrado['projeto']}\" deste computador: o envio usa esse projeto.",
            }
    except Exception as e:
        saida["autocad"] = {"erro": str(e)}
    try:
        saida["conexao"] = backend.eu()
        autocad_ = saida.get("autocad") or {}
        vinculo = autocad_.get("vinculo") or saida.get("vinculoLembrado")
        if isinstance(vinculo, dict) and vinculo.get("projetoId"):
            projetos = backend.projetos()
            if not any(p["projetoId"] == vinculo["projetoId"] for p in projetos):
                saida["vinculoPerdido"] = _vinculo_perdido(vinculo, projetos)
    except Exception as e:
        saida["conexao"] = {"erro": str(e)}
    saida.update(_com_aviso_de_versao())
    return saida


@mcp.tool()
def diagnosticar() -> dict:
    """Confere tudo de uma vez quando algo não funciona: versão, pastas, se roda empacotado (MSIX),
    a janela do AutoCAD, o LISP carregado de dentro do AutoCAD (versão, TRUSTEDPATHS, SECURELOAD,
    vínculo) e a conexão com o Prancha Ok. Cada etapa diz ok ou o erro."""
    saida: dict = {
        "versaoMcp": __version__,
        "backend": api(),
        "empacotadoMsix": empacotado(),
        "pastas": {"base": str(pasta()), "lisp": str(pasta_lisp()), "ipc": str(pasta_ipc()),
                   "lispExiste": (pasta_lisp() / "prancha_ok.lsp").exists()},
        "instalacao": ler_estado().get("instalacao"),
        "pastaDoServidor": instalacao.ORIGEM,
        "outrosConectores": instalacao.outros_servidores(),
    }
    try:
        janela = autocad._janela_autocad()
        saida["janelaAutocad"] = ({"ok": True, "hwnd": janela} if janela
                                  else {"ok": False, "erro": autocad.mensagem_sem_autocad(autocad.outro_cad_aberto())})
    except Exception as e:
        saida["janelaAutocad"] = {"ok": False, "erro": str(e)}
    try:
        info = autocad.info()
        saida["lisp"] = {
            "ok": info.get("versaoLisp") == __version__,
            "versao": info.get("versaoLisp"),
            "produto": info.get("produto"),
            "secureload": info.get("secureload"),
            "trustedpaths": info.get("trustedpaths"),
            "pastaConfiavel": _aviso_confiavel(info) is None,
            "desenho": info.get("arquivo"),
            "salvo": info.get("salvo"),
            "vinculo": info.get("vinculo"),
        }
    except Exception as e:
        saida["lisp"] = {"ok": False, "erro": str(e)}
    try:
        saida["conexao"] = {"ok": True, **backend.eu()}
    except Exception as e:
        saida["conexao"] = {"ok": False, "erro": str(e)}
    return saida


# ---------------------------------------------------------------- projeto

# Projeto novo só se cria no site: a conta recém-conectada não tem nenhum e o arquiteto
# precisa saber onde criar (revisão da página /autocad, 01/10/2026).
SEM_PROJETO = ("A empresa conectada ainda não tem nenhum projeto. Projeto novo se cria no site: "
               "a pessoa entra em pranchaok.com.br/app, clica em \"Novo projeto\" (a obra, o município e "
               "a zona) e volta aqui. Depois chame `listar_projetos` de novo.")


def _projetos(projetos: list) -> dict:
    if not projetos:
        return {"ok": True, "projetos": [], "mensagem": SEM_PROJETO}
    return {"ok": True, "projetos": projetos}


@mcp.tool()
def listar_projetos() -> dict:
    """Projetos da empresa conectada (para escolher em qual o desenho vai). Sem nenhum, diz
    onde criar (no site)."""
    try:
        return _projetos(backend.projetos())
    except Exception as e:
        return _erro(e)


@mcp.tool()
def vincular_projeto(projeto_id: str) -> dict:
    """Grava no desenho aberto o projeto do Prancha Ok a que ele pertence (os próximos envios vão
    para ele). Projeto novo se cria na web. Deixa o desenho com alteração não salva."""
    try:
        projeto = next((p for p in backend.projetos() if p["projetoId"] == projeto_id), None)
        if projeto is None:
            return {"ok": False, "erro": "Projeto não encontrado nesta empresa. Use `listar_projetos`."}
        empresa = backend.eu()["empresa"]
        info = autocad.vincular(projeto_id, projeto["nome"], empresa["empresaId"])
        _lembrar_vinculo(info.get("arquivo") or "", projeto_id, projeto["nome"])
        return {"ok": True, "projeto": projeto["nome"],
                "mensagem": "Vínculo gravado no desenho. Ele fica no arquivo quando o desenho for salvo "
                            "(o próximo envio pode salvar, com o sim da pessoa)."}
    except Exception as e:
        return _erro(e)


# ---------------------------------------------------------------- parecer

def _custos(p: dict) -> list[dict]:
    saida = []
    for c in p.get("custos", []):
        if c["situacao"] == "nao_se_aplica":
            continue
        saida.append({
            "nome": c["nome"],
            "lei": c["lei"],
            **({"valor": c["valor"], "faixa": [c["minimo"], c["maximo"]]} if c["situacao"] == "estimado" else {}),
            **({"faltaInformar": [p["rotulos"].get(f, f) for f in c["faltando"]]} if c["faltando"] else {}),
            **({"nota": c["nota"]} if c["nota"] else {}),
        })
    return saida


def _motivos_recusa(p: dict) -> list[str]:
    """O que faltou na prancha recusada (pronto para mostrar)."""
    return list(p.get("motivosRecusa") or ([p["erro"]] if p.get("erro") else []))


def _recusa(p: dict) -> dict:
    """Parecer recusado (prancha não reconhecida): sem itens nem custos, só o que faltou."""
    motivos = _motivos_recusa(p)
    return {
        "ok": True,
        "recusada": True,
        "parecerId": p["parecerId"],
        "numero": p["numero"],
        "situacao": SITUACAO["recusado"],
        "arquivo": p["nomeArquivo"],
        "url": p["url"],
        "motivosRecusa": motivos,
        "mensagem": "O Prancha Ok não reconheceu este desenho como uma prancha de legalização e não fez a "
                    "conferência: não há itens nem custos, e este envio não conta na cota. "
                    + (f"O que faltou: {'; '.join(motivos)}. " if motivos else "")
                    + "Confira se o desenho aberto é a prancha do projeto (com o município, o endereço, o "
                      "responsável técnico com CREA ou CAU, a planta de situação e um corte) e envie de novo. "
                      "Nada foi marcado no desenho.",
    }


def _no_desenho(item: dict, rotulos: dict, detalhe: bool) -> list[dict]:
    return [
        {"campo": rotulos.get(lugar["campo"], lugar["campo"]), "valor": lugar["valor"], "handles": lugar["handles"]}
        for lugar in item.get("lugares") or [] if detalhe or not lugar["informado"]
    ]


def _linha_resumo(item: dict, rotulos: dict, detalhe: bool, *, texto: bool = True) -> dict:
    """Um item para o chat: número, título, o que diz, a referência (a lei, ou "Sugestão
    referenciada" quando não há lei) e onde olhar na prancha."""
    saida = {"item": item["ordem"] + 1}
    if item.get("titulo"):
        saida["titulo"] = item["titulo"]
    if texto or detalhe or not item.get("titulo"):
        saida["texto"] = item["texto"]
    saida["referencia"] = item.get("referenciaLegal")
    if onde := marcas.onde_olhar(item):
        saida["ondeOlhar"] = onde
    if no_desenho := _no_desenho(item, rotulos, detalhe):
        saida["noDesenho"] = no_desenho
    if item.get("faltando"):
        saida["faltaInformar"] = [rotulos.get(c, c) for c in item["faltando"]]
    return saida


def _cadastral(item: dict) -> bool:
    """Documento do processo (RGI, ART, taxa...), não do projeto: fica à parte, como no site (setor "cadastro" ou
    pergunta sem condição; web: lib/organizarParecer.ts)."""
    return not item.get("aguardaGatilho") and (item.get("setor") == "cadastro" or item["situacao"] == "pergunta")


def _contagem(p: dict, itens: list[dict]) -> dict:
    """A conta como o site: por item (as linhas de cada cômodo contam uma vez), e fechando. Pente fino de
    04/10/2026, sugestão 1: "235 itens conferidos, 145 valem para este projeto, mas as abas somavam 106" (os 39
    cadastrais, à parte, não estavam na conta)."""
    por_item: dict[str, dict] = {}
    for i in itens:
        chave = i.get("idRegra") or f"linha-{i['ordem']}"
        por_item.setdefault(chave, i)

    def n(situacao):
        return sum(1 for i in por_item.values() if i["situacao"] == situacao and not _cadastral(i))

    contagem = {"erros": n("errado"), "duvidas": n("duvida"), "perguntas": n("pergunta"),
                "conferirAMao": n("conferir_a_mao"), "atendidos": n("atendido"), "dispensados": n("dispensado"),
                "cadastrais": sum(1 for i in por_item.values() if _cadastral(i))}
    valem = len(por_item)
    contagem["valemParaEsteProjeto"] = valem
    # Pareceres da rodada 2 trazem a contagem do catálogo: quantos itens não se aplicam a este projeto (não viram
    # linha) e o total conferido.
    catalogo = (p.get("contagem") or {}).get("catalogo") if isinstance(p.get("contagem"), dict) else None
    cadastrais = contagem["cadastrais"]
    explicacao = f"{valem} itens valem para este projeto: {valem - cadastrais} na análise técnica e " \
                 f"{cadastrais} {'cadastral' if cadastrais == 1 else 'cadastrais'} (documentos do processo, à parte)"
    if isinstance(catalogo, dict) and "naoSeAplica" in catalogo:
        contagem["naoSeAplicam"] = catalogo["naoSeAplica"]
        contagem["itensConferidos"] = catalogo.get("total")
        explicacao += f"; {catalogo['naoSeAplica']} não se aplicam; {catalogo.get('total')} conferidos ao todo"
    contagem["comoFecha"] = explicacao + ". Custos estimados à parte, fora dessa conta."
    return contagem


def _do_responsavel(p: dict, itens: list[dict]) -> dict | None:
    """O que o responsável técnico respondeu na web (rodada 4b): quanto falta para fechar, se ele
    fechou a análise e os desacordos que ele contestou (o motor continua apontando). É dele, não
    do Prancha Ok. None sem a conta (backend antigo ou parecer sem resultado)."""
    conta = p.get("contaDoResponsavel")
    if not isinstance(conta, dict) or not isinstance(conta.get("faltam"), int):
        return None
    resolvidos = conta.get("resolvidos") or {}
    contestados = [{"item": i["ordem"] + 1, "titulo": i.get("titulo") or i["texto"], "por": i["marca"].get("nome"),
                    "justificativa": i["marca"].get("justificativa")}
                   for i in itens if marcas.escolha_do_responsavel(i) == "discordo"]
    return {
        "faltamParaFechar": conta["faltam"],
        "fechadoPeloResponsavel": conta.get("statusDoResponsavel") == "aprovado_pelo_responsavel",
        "conferidosPeloResponsavel": resolvidos.get("conferidosPorVoce", 0),
        "naoSeAplicaPeloResponsavel": conta.get("naoSeAplicaPorVoce", 0),
        "contestados": contestados,
        "aviso": "Respostas do responsável técnico na web, não do Prancha Ok: nunca diga que o Prancha Ok "
                 "conferiu esses itens. Os contestados continuam apontados pelo motor.",
    }


def _resumo(p: dict, detalhe: bool = False) -> dict:
    """O parecer para ler no chat. Resumido (padrão): erros por extenso, dúvidas agrupadas
    pela pergunta que as resolve, perguntas abertas agrupadas pela resposta que libera os
    itens e os pontos para conferir à mão só com o título e onde olhar, sem repetir o que a
    pessoa já informou na web. O que não se aplica a este projeto não aparece (só contado)."""
    if p["status"] == "recusado":
        return _recusa(p)
    rotulos = p.get("rotulos", {})
    todos = p.get("itens", [])
    # O que o responsável já resolveu na web (conferiu, contestou, "não se aplica") sai das listas:
    # vai contado em "responsavel". A contagem continua a do motor.
    itens = [i for i in todos if not marcas.resolvido_pelo_responsavel(i)]
    duvidas = [i for i in itens if i["situacao"] == "duvida"]
    saida = {
        "ok": True,
        "parecerId": p["parecerId"],
        "numero": p["numero"],
        "situacao": SITUACAO.get(p["status"], p["status"]),
        "versaoRegras": p["versaoRegras"],
        "arquivo": p["nomeArquivo"],
        "url": p["url"],
        "erro": p["erro"],
        "contagem": _contagem(p, todos),
        "erros": [_linha_resumo(i, rotulos, detalhe) for i in itens if i["situacao"] == "errado"],
    }
    if detalhe:
        saida["duvidas"] = [_linha_resumo(i, rotulos, detalhe) for i in duvidas]
    else:
        # Uma pergunta, vários itens: "há rede pública?" resolve dois itens de uma vez.
        perguntas: dict[str, dict] = {}
        sem_pergunta = []
        for i in duvidas:
            if not i["faltando"]:
                sem_pergunta.append({"item": i["ordem"] + 1, "idRegra": i["idRegra"], "texto": i["texto"]})
            for campo in i["faltando"]:
                grupo = perguntas.setdefault(campo, {"campo": campo, "pergunta": rotulos.get(campo, campo), "itens": []})
                grupo["itens"].append(i["ordem"] + 1)
        saida["duvidas"] = {"perguntas": list(perguntas.values()), "semPergunta": sem_pergunta,
                            "comoResponder": "responder_itens com {campo: valor}; dúvida que não se aplica: "
                                             "dispensas com idRegra e justificativa"}
    linhas = marcas.linhas_apresentadas(p, ("pergunta",))
    if abertas := marcas.perguntas_abertas(linhas, rotulos):
        saida["perguntas"] = {
            # Primeiro as do projeto (decidem o que vale); as de documento, à parte.
            "abertas": [g for g in abertas if marcas.sobre_o_projeto(g)],
            "sobreDocumentos": [g for g in abertas if not marcas.sobre_o_projeto(g)],
            "comoResponder": "responder_itens com {campo: resposta}, a resposta uma das opcoes da pergunta "
                             "(\"sim\", \"não\" ou \"não se aplica\"), só a que a pessoa der. Pergunta não se "
                             "dispensa: se não vale para o projeto, a resposta é \"não se aplica\".",
        }
    conferir = [i for i in itens if i["situacao"] == "conferir_a_mao"]
    if conferir:
        saida["conferirAMao"] = {
            "oQueE": "Pontos que o Prancha Ok não consegue provar sozinho: a pessoa confere na prancha. "
                     "Nunca diga que estão atendidos.",
            "itens": [_linha_resumo(i, rotulos, detalhe, texto=False) for i in conferir],
        }
    if responsavel := _do_responsavel(p, todos):
        saida["responsavel"] = responsavel
    if custos := _custos(p):
        saida["custosEstimados"] = {"aviso": "Estimativa do Prancha Ok; o valor final é calculado pela Prefeitura.",
                                    "itens": custos}
    if comparacao := p.get("comparacao"):
        saida["desdeOAnterior"] = {
            "parecer": comparacao["anteriorNumero"],
            **({"regrasMudaram": f"{comparacao['versaoRegrasAnterior']} -> {p['versaoRegras']}"}
               if comparacao["regrasMudaram"] else {}),
            "resolvidos": comparacao["resolvidos"],
            "novos": comparacao["novos"],
            "mudaramDeSituacao": comparacao["mudaram"],
            "semMudanca": comparacao["semMudanca"],
        }
    return saida


# ---------------------------------------------------------------- medir antes do parecer

# Medidas confirmadas guardadas por parecer (para a nuvem achar o lugar do valor informado).
MAXIMO_PARECERES_COM_MEDIDAS = 20


def _guardar_medidas(parecer_id: str, confirmadas: dict) -> None:
    if not confirmadas:
        return
    guardadas = dict(ler_estado().get("medidasConfirmadas") or {})
    guardadas[parecer_id] = confirmadas
    gravar_estado(medidasConfirmadas=dict(list(guardadas.items())[-MAXIMO_PARECERES_COM_MEDIDAS:]))


def _medidas_do_parecer(parecer_id: str) -> dict:
    return (ler_estado().get("medidasConfirmadas") or {}).get(parecer_id) or {}


@mcp.tool()
def medir_prancha(unidade: str = "m") -> dict:
    """Opcional: mede no desenho aberto, pelo AutoCAD, terreno (área, lados, testada), área de
    projeção, afastamentos, pavimentos, altura, áreas por pavimento e vagas. As medidas que valem
    são as que o Prancha Ok lê da prancha (a prévia de `enviar_prancha`); esta medição serve para
    comparar quando a pessoa duvida de uma delas, ou para responder uma pergunta da prévia (com o sim
    dela). Devolve uma PROPOSTA, cada valor com como foi medido e os handles. `unidade`: a do desenho
    ("m", "cm" ou "mm"); pergunte se o resultado vier com aviso de unidade."""
    try:
        return {
            "ok": True,
            **medidas.medir(autocad.ler_entidades(), unidade),
            "comoUsar": "Proposta, não medida oficial: mostre cada valor com o \"como\". Para corrigir uma medida "
                        "ou responder uma pergunta da prévia com um destes valores, só com o sim da pessoa, em "
                        "confirmar_previa. Divergência entre o quadro e o desenho: a pessoa escolhe.",
        }
    except Exception as e:
        return _erro(e)


def _parecer_id(parecer_id: str | None) -> str:
    escolhido = parecer_id or ler_estado().get("ultimoParecer")
    if not escolhido:
        raise ValueError("Nenhum parecer enviado deste computador ainda: use `enviar_prancha`.")
    return escolhido


def _esperar(parecer_id: str, ate: float) -> dict:
    """O parecer, esperando terminar até o instante `ate` (time.monotonic)."""
    while True:
        p = backend.parecer(parecer_id)
        if p["status"] != "processando" or time.monotonic() + 3 > ate:
            return p
        time.sleep(3)


def _com_espera(p: dict, detalhe: bool) -> dict:
    if p["status"] == "aguardando_medidas":
        return _previa(p)
    resumo = _resumo(p, detalhe)
    if p["status"] == "processando":
        resumo["mensagem"] = ("Ainda processando (costuma levar de 20 s a 2 min). Chame `ver_parecer` com "
                              "aguardar=true.")
    return resumo


def _tipo_do_desenho(arquivo: Path) -> str:
    """"dwg" ou "dxf" pelo nome do arquivo aberto; outro formato não vai."""
    tipo = arquivo.suffix.lower().lstrip(".")
    if tipo not in ("dwg", "dxf"):
        raise ValueError(f"O Prancha Ok lê DWG e DXF; o desenho aberto é {arquivo.name}.")
    return tipo


# O parecer que já tem itens para marcar (processando, falhou e recusado não têm).
_PRONTOS = ("aprovado", "pendente", "em_revisao")


def _deve_marcar(status: str, marcar: bool) -> bool:
    return marcar and status in _PRONTOS


def _com_marcas(resumo: dict, parecer_id: str, status: str, marcar: bool) -> dict:
    """O parecer pronto já vai para o desenho (item 1 das observações de 02/10/2026: "automaticamente
    os erros, dúvidas, conferir à mão [...] apontados como nuvem"). Falha ao marcar não desfaz o
    parecer: vai como aviso."""
    if not _deve_marcar(status, marcar):
        return resumo
    marcado = marcar_parecer(parecer_id)
    if not marcado.get("ok"):
        return {**resumo, "marcas": {"ok": False, "erro": marcado.get("erro")}}
    return {**resumo, "marcas": {k: marcado[k] for k in ("marcados", "apresentados", "nuvens", "chamadas", "mensagem")
                                 if k in marcado}}


def _respostas_numericas(respostas: dict | None) -> dict[str, float]:
    """As medidas confirmadas, como números (a confirmação só aceita número)."""
    saida = {}
    for campo, valor in (respostas or {}).items():
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
            raise ValueError(f"A medida \"{campo}\" precisa ser um número (metros ou m², sem unidade).")
        saida[str(campo)] = float(valor)
    return saida


def _letra(n: int) -> str:
    """A, B, ..., Z, AA, AB...: a letra da medida na lista da prévia."""
    letras = ""
    n += 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _numero_br(valor: float, unidade: str) -> str:
    if not unidade:
        return str(int(valor)) if float(valor).is_integer() else f"{valor}".replace(".", ",")
    return f"{valor:.2f}".replace(".", ",") + f" {unidade}"


def _previa(p: dict) -> dict:
    """O parecer esperando a conferência (a prévia do 1º parecer, 0.4.0): as medidas que o motor leu, com letras,
    e as perguntas que o parecer faria, numeradas. Pente fino de 04/10/2026, item B: antes, o 1º parecer saía só
    com as medidas e as respostas abriam o nº 2."""
    previa = p.get("previa") or {}
    medidas = [{"letra": _letra(i), "campo": m["campo"], "medida": m["rotulo"],
                "valor": _numero_br(m["valor"], m["unidade"]), "numero": m["valor"],
                "deOndeSaiu": m["onde"]["local"] + (f": \"{m['onde']['trecho']}\"" if m["onde"].get("trecho") else "")}
               for i, m in enumerate(previa.get("medidas") or [])]
    perguntas = [{"numero": i + 1, "campo": q["campo"], "pergunta": q["rotulo"], "tipo": q["tipo"],
                  **({"opcoes": q["opcoes"]} if q.get("opcoes") else {}), "decide": q.get("itens") or []}
                 for i, q in enumerate(previa.get("perguntas") or [])]
    terreno = previa.get("terreno") if isinstance(previa.get("terreno"), dict) else None
    extra = {}
    if terreno and not terreno.get("conferido"):
        # Foto F3 do pente fino de 04/10/2026: "essa conferência, que considero importantíssima [...] o ideal seria
        # esses valores serem conferidos pelo usuário também antes do 1º parecer". A conferência lado a lado é no site.
        extra["terreno"] = {
            "conferido": False,
            "url": terreno.get("url"),
            "mensagem": "O terreno conforme o RGI (lados, testada, área, esquina) ainda não foi conferido neste projeto. "
                        "Ele vale mais que a prancha. Sugira conferir no site antes de confirmar a prévia"
                        + (f" ({terreno['url']})" if terreno.get("url") else "")
                        + "; o que for conferido lá entra neste parecer. A pessoa pode seguir sem.",
        }
    return {
        **extra,
        "ok": True,
        "previa": True,
        "parecerId": p["parecerId"],
        "numero": p["numero"],
        "situacao": SITUACAO["aguardando_medidas"],
        "arquivo": p["nomeArquivo"],
        "url": p["url"],
        "medidas": medidas,
        "perguntas": perguntas,
        "comoUsar": "Antes do parecer, mostre as medidas lidas numa lista com letras (cada uma com de onde saiu) e as "
                    "perguntas numeradas (com as opções), e peça a resposta em bloco: \"tudo certo\", \"tudo certo "
                    "menos B e D\", \"só A e C estão certos\", \"1 sim, 2 2,50\" ou \"vou responder um a um\". Depois "
                    "chame confirmar_previa(valores={campo: número} só das medidas confirmadas ou corrigidas, "
                    "respostas={campo: valor} das perguntas respondidas: número sem unidade, ou uma das opções). O "
                    "que ficar sem resposta o parecer pergunta de novo. Sai um parecer só, com tudo.",
    }


def _guardar_medidas_da_previa(parecer_id: str, previa: dict, valores: dict[str, float]) -> None:
    """O lugar das medidas confirmadas como lidas (os handles do motor), para a nuvem do valor informado achar de
    onde ele saiu (marcas.com_lugar_medido). Corrigida pela pessoa: o lugar não é o lido."""
    lidas = {m["campo"]: m for m in previa.get("medidas") or []}
    _guardar_medidas(parecer_id, {
        campo: {"valor": valor, "handles": lidas[campo].get("handles") or []}
        for campo, valor in valores.items()
        if campo in lidas and abs(float(lidas[campo]["valor"]) - float(valor)) < 0.005})


@mcp.tool()
def enviar_prancha(projeto_id: str | None = None, compartilhar_prancha: bool = False, salvar: bool = False,
                   marcar: bool = True) -> dict:
    """Envia o desenho aberto, DWG ou DXF (como está salvo no disco), para um parecer novo no
    projeto vinculado (ou em `projeto_id`). Com DWG vai junto a leitura que o próprio AutoCAD
    faz do desenho (o Prancha Ok compara as duas; onde divergem, o item vira dúvida). Espera a
    leitura por até ~50 s no total e devolve a PRÉVIA: as medidas lidas e as perguntas que o
    parecer faria, para a pessoa conferir e responder; depois, `confirmar_previa` gera o parecer.
    Sem nada para conferir, o parecer já sai (e é marcado no desenho se `marcar`).
    `salvar`: salva o desenho (QSAVE) antes de enviar, se houver alteração não salva (inclusive
    as marcas e o vínculo, que o próprio MCP grava). Só com o "sim" da pessoa, perguntado uma vez.
    `compartilhar_prancha`: só com a permissão explícita da pessoa (pergunte uma vez). Deixa a
    equipe do Prancha Ok baixar esta prancha quando as leituras divergem, para corrigir o leitor."""
    inicio = time.monotonic()
    try:
        desenho = autocad.info()
        if not desenho.get("temNome"):
            return {"ok": False, "erro": "O desenho ainda não foi salvo com um nome. Salve (Ctrl+S) e tente de novo."}
        if not desenho.get("salvo"):
            if not salvar:
                return {"ok": False, "precisaSalvar": True,
                        "erro": "O desenho tem alterações não salvas (as marcas e o vínculo do MCP também contam). "
                                "Pergunte se pode salvar e chame de novo com salvar=true, ou peça Ctrl+S."}
            autocad.salvar()
            desenho = autocad.info()
            if not desenho.get("salvo"):
                return {"ok": False, "erro": "O AutoCAD não salvou o desenho (há alguma janela aberta nele?)."}
        arquivo = Path(desenho["arquivo"])
        tipo = _tipo_do_desenho(arquivo)
        vinculo = desenho.get("vinculo") or _vinculo_lembrado(desenho["arquivo"]) or {}
        projeto = projeto_id or vinculo.get("projetoId")
        projetos = backend.projetos()
        if projeto and not projeto_id and not any(p["projetoId"] == projeto for p in projetos):
            _esquecer_vinculo(desenho["arquivo"])
            return {"ok": False, "vinculoPerdido": True, "projetos": projetos,
                    "erro": _vinculo_perdido(vinculo, projetos)}
        if not projeto:
            if not projetos:
                return {"ok": False, "projetos": [], "erro": SEM_PROJETO}
            if len(projetos) == 1:
                unico = projetos[0]
                return {"ok": False, "sugestao": unico,
                        "erro": f"Este desenho não está ligado a um projeto. A empresa tem um só: \"{unico['nome']}\". "
                                f"Confirme com a pessoa e chame de novo com projeto_id=\"{unico['projetoId']}\"."}
            return {"ok": False, "projetos": projetos,
                    "erro": "Este desenho não está ligado a um projeto. Pergunte à pessoa qual e chame de novo com "
                            "projeto_id, ou use `vincular_projeto`."}
        aviso, leitura = None, None
        if tipo == "dwg":  # o DXF já traz os handles do AutoCAD; a segunda leitura só acompanha DWG
            try:
                leitura = {"produto": desenho.get("produto") or "AutoCAD",
                           "versaoAcad": desenho.get("versaoAcad") or "?",
                           "versaoLisp": desenho.get("versaoLisp") or "?", "entidades": autocad.ler_entidades()}
            except AutocadIndisponivel as e:
                # Sem a segunda leitura o parecer sai igual ao da web: não é motivo para não enviar.
                aviso = f"Enviado sem a leitura do AutoCAD ({e})."
        aberto = backend.enviar_prancha(projeto, arquivo, leitura, compartilhar_prancha)
        gravar_estado(ultimoParecer=aberto["parecerId"])
        nome = next((p["nome"] for p in projetos if p["projetoId"] == projeto), vinculo.get("projeto") or projeto)
        _lembrar_vinculo(desenho["arquivo"], projeto, nome)
        lido = _esperar(aberto["parecerId"], inicio + PRAZO_PARECER_S)
        if lido["status"] == "aguardando_medidas":
            previa = lido.get("previa") or {}
            if previa.get("medidas") or previa.get("perguntas"):
                resposta = _previa(lido)
                return {**resposta, "aviso": aviso} if aviso else resposta
            # Nada a conferir nem a perguntar: o parecer sai direto.
            backend.confirmar(aberto["parecerId"], {}, {})
            lido = _esperar(aberto["parecerId"], inicio + PRAZO_PARECER_S)
        resumo = _com_marcas(_com_espera(lido, detalhe=False), aberto["parecerId"], lido["status"], marcar)
        return {**resumo, "aviso": aviso} if aviso else resumo
    except ErroBackend as e:
        if e.codigo == "PARECER_EM_PROCESSAMENTO":
            return {"ok": False, "erro": "Ainda há um parecer processando neste projeto. Espere ele terminar "
                                         "(`ver_parecer` com aguardar=true) e envie de novo."}
        return {"ok": False, "erro": f"{e}"}
    except Exception as e:
        return _erro(e)


@mcp.tool()
def confirmar_previa(valores: dict[str, float] | None = None, respostas: dict[str, str | float] | None = None,
                     parecer_id: str | None = None, marcar: bool = True) -> dict:
    """Confirma a prévia do parecer (o último enviado deste computador, se não disser qual) e gera o parecer com
    tudo. `valores`: {campo: número} só das medidas da prévia que a pessoa confirmou (o valor lido) ou corrigiu (o
    dela); a não conferida não vai e fica como foi lida. `respostas`: {campo: valor} das perguntas da prévia que
    ela respondeu (número sem unidade, ou uma das opções). Nunca mande sem o sim dela. Espera o parecer por até
    ~50 s e, pronto, marca no desenho (`marcar`)."""
    inicio = time.monotonic()
    try:
        pid = _parecer_id(parecer_id)
        antes = backend.parecer(pid)
        if antes["status"] != "aguardando_medidas":
            return {"ok": False, "erro": "Este parecer não está esperando a conferência: veja com `ver_parecer`."}
        confirmadas = _respostas_numericas(valores)
        backend.confirmar(pid, confirmadas, dict(respostas or {}))
        _guardar_medidas_da_previa(pid, antes.get("previa") or {}, confirmadas)
        pronto = _esperar(pid, inicio + PRAZO_PARECER_S)
        return _com_marcas(_com_espera(pronto, detalhe=False), pid, pronto["status"], marcar)
    except ErroBackend as e:
        explicacao = {
            "CAMPO_NAO_PERMITIDO": "esse campo não está na prévia; mande só as medidas e as perguntas dela",
            "VALOR_INVALIDO": "valor fora do formato (número de 0 a 10 milhões, sem unidade, ou uma das opções)",
            "PARECER_NAO_AGUARDA_MEDIDAS": "a prévia já foi confirmada",
        }.get(e.codigo)
        return {"ok": False, "erro": f"{e}" + (f": {explicacao}" if explicacao else "")}
    except Exception as e:
        return _erro(e)


@mcp.tool()
def ver_parecer(parecer_id: str | None = None, detalhe: bool = False, aguardar: bool = False) -> dict:
    """Situação e itens do parecer (o último enviado deste computador, se não disser qual), com os
    custos estimados e o que mudou desde o parecer anterior. Resumido por padrão (erros por
    extenso, dúvidas agrupadas pela pergunta, perguntas abertas e o que conferir à mão);
    `detalhe=true` traz tudo. `aguardar=true` espera até ~50 s se ainda estiver processando."""
    try:
        pid = _parecer_id(parecer_id)
        p = _esperar(pid, time.monotonic() + PRAZO_PARECER_S) if aguardar else backend.parecer(pid)
        return _com_espera(p, detalhe)
    except Exception as e:
        return _erro(e)


@mcp.tool()
def responder_itens(respostas: dict[str, str | float] | None = None, dispensas: list[dict] | None = None,
                    parecer_id: str | None = None, marcar: bool = True) -> dict:
    """Responde as dúvidas e as perguntas do parecer pelo chat (como o formulário da web):
    `respostas` é {campo: valor} com os campos que o parecer pediu (`duvidas.perguntas`,
    `perguntas.abertas` e `perguntas.sobreDocumentos` em ver_parecer; opção como
    "sim"/"não"/"não se aplica", número em metros ou m² sem unidade). `dispensas`: [{idRegra, justificativa}] para dúvida que não se aplica
    (pergunta não se dispensa: responda "não se aplica"). Gera um parecer novo da mesma prancha
    e espera o resultado; pronto, já marca no desenho (`marcar`). Só grave valor que a pessoa disse
    ou confirmou."""
    inicio = time.monotonic()
    try:
        pid = _parecer_id(parecer_id)
        if (base := backend.parecer(pid))["status"] == "recusado":
            return {**_recusa(base), "ok": False,
                    "erro": "Prancha não reconhecida: não há dúvidas para responder. Envie a prancha certa."}
        novo = backend.responder(pid, respostas or {}, dispensas or [])
        gravar_estado(ultimoParecer=novo["parecerId"])
        # O parecer novo herda o que foi informado no de origem, inclusive as medidas confirmadas.
        _guardar_medidas(novo["parecerId"], _medidas_do_parecer(pid))
        pronto = _esperar(novo["parecerId"], inicio + PRAZO_PARECER_S)
        return _com_marcas(_com_espera(pronto, detalhe=False), novo["parecerId"], pronto["status"], marcar)
    except ErroBackend as e:
        explicacao = {
            "CAMPO_NAO_PERMITIDO": "esse campo não foi pedido pelo parecer (o que foi lido da prancha não se "
                                   "troca por aqui)",
            "VALOR_INVALIDO": "valor fora do formato (número sem unidade, ou uma das opções da pergunta)",
            "DISPENSA_NAO_PERMITIDA": "só dúvidas se dispensam; erro não, e pergunta se responde "
                                      "(\"não se aplica\" quando não vale para o projeto)",
            "JUSTIFICATIVA_INVALIDA": "a justificativa precisa ter de 3 a 500 caracteres",
            "PARECER_SEM_RESULTADO": "o parecer ainda está processando ou falhou",
        }.get(e.codigo)
        return {"ok": False, "erro": f"{e}" + (f": {explicacao}" if explicacao else "")}
    except Exception as e:
        return _erro(e)


# ---------------------------------------------------------------- marcas no desenho

def _nada_a_marcar(p: dict) -> dict:
    """Parecer recusado: não há o que marcar, e o desenho não é tocado."""
    return {"ok": False, "recusada": True, "motivosRecusa": _motivos_recusa(p),
            "erro": "Esta prancha não foi reconhecida pelo Prancha Ok, então não há itens para marcar (o desenho "
                    "não foi alterado). Veja em motivosRecusa o que faltou."}


def _situacoes(incluir_duvidas: bool, incluir_conferir: bool) -> tuple[str, ...]:
    return tuple(s for s in marcas.ORDEM
                 if s == "errado" or (incluir_duvidas and s == "duvida")
                 or (incluir_conferir and s in ("pergunta", "conferir_a_mao")))


def _indices(resposta: dict, chave: str, total: int) -> list[int]:
    return [i for i in resposta.get(chave) or [] if isinstance(i, int) and 0 <= i < total]


def _marcar_no_desenho(linhas: list[marcas.Linha], p: dict | None = None) -> tuple[set[int], dict]:
    """Manda as marcas ao AutoCAD. Primeiro pergunta onde está cada handle (e o título de cada
    tabela do parecer); chamadas.planejar divide: no carimbo, no quadro de áreas e onde as nuvens
    se amontoariam, chamada com seta (0.3.4); no resto, nuvem no handle. A linha que não ganhou
    nenhuma (sem handle, ou handle que o desenho não tem mais) vai para a nuvem da região, se houver.
    Devolve os números das linhas marcadas e o que não se achou, com `soChamada`: as marcadas só
    por chamada (o quadro-resumo dá o título delas)."""
    pedidos = list(dict.fromkeys([h for x in linhas for h in x.handles] + chamadas.handles_das_tabelas(p or {})))
    achados = chamadas.lugares(autocad.caixas(pedidos)) if pedidos else {}
    plano = chamadas.planejar(linhas, achados, chamadas.tabelas(p or {}, achados))
    feito = autocad.marcar(plano.nuvens) if plano.nuvens else {}
    com_nuvem = set(feito.get("marcadas") or [])
    marcados = {x.numero for x in linhas if com_nuvem.intersection(x.handles)}
    desenhadas = autocad.marcar_chamadas(plano.chamadas) if plano.chamadas else {}
    com_chamada = {n for i in _indices(desenhadas, "marcadas", len(plano.chamadas)) for n in plano.chamadas[i].itens}
    pendentes = [x for x in linhas if x.numero not in marcados | com_chamada and x.regioes]
    regioes, grupos = marcas.marcas_por_regiao(pendentes)
    feitas = autocad.marcar_regioes(regioes) if regioes else {}
    for indice in _indices(feitas, "marcadas", len(grupos)):
        marcados.update(grupos[indice]["itens"])
    nao_achadas = [grupos[i] for i in _indices(feitas, "semLugar", len(grupos))]
    nao_achados = [h for h in pedidos if h not in achados and any(h in x.handles for x in linhas)]
    return marcados | com_chamada, {
        "handlesNaoAchados": nao_achados + [h for h in feito.get("semLugar") or [] if h not in nao_achados],
        "regioesNaoAchadas": nao_achadas,
        "nuvens": len(com_nuvem) + len(feitas.get("marcadas") or []),
        "chamadas": sum(1 for i in _indices(desenhadas, "marcadas", len(plano.chamadas)) if plano.chamadas[i].texto),
        "soChamada": com_chamada - marcados}


@mcp.tool()
def marcar_parecer(parecer_id: str | None = None, incluir_duvidas: bool = True, incluir_conferir: bool = True,
                   quadro: bool = True) -> dict:
    """Marca no desenho, com nuvem e número do item, tudo o que o parecer apresenta e tem lugar
    na prancha: em vermelho o que está em desacordo, em laranja as dúvidas e, com
    `incluir_conferir`, em azul o que conferir à mão e em magenta as perguntas. A nuvem vai em
    volta do valor no desenho (handles) ou, quando o item é de uma parte da prancha (planta
    de situação, corte...), em volta dessa parte. No carimbo, no quadro de áreas e onde várias
    nuvens cairiam no mesmo lugar, o item ganha uma seta até uma chamada "[nº] SITUAÇÃO" numa
    coluna ao lado, em vez da nuvem. Ao lado do
    desenho, um quadro-resumo com os itens e o que ficou sem lugar (e as perguntas abertas).
    Apaga as marcas anteriores antes. Tudo na camada PRANCHAOK-PARECER. Deixa o desenho com
    alteração não salva. Devolve quantos itens apresentados têm lugar e quantos viraram nuvem."""
    try:
        pid = _parecer_id(parecer_id)
        p = marcas.com_lugar_medido(backend.parecer(pid), _medidas_do_parecer(pid))
        if p["status"] == "recusado":
            return _nada_a_marcar(p)
        linhas = marcas.linhas_apresentadas(p, _situacoes(incluir_duvidas, incluir_conferir))
        autocad.limpar()
        marcados, faltas = _marcar_no_desenho(linhas, p)
        if quadro:
            autocad.quadro(marcas.linhas_quadro(p, linhas, marcados, SITUACAO.get(p["status"], p["status"]),
                                                faltas["soChamada"]))
        medida = marcas.medida(linhas, marcados)
        return {
            "ok": True,
            **{k: medida[k] for k in ("apresentados", "comLugar", "marcados", "percentualMarcados")},
            "porSituacao": medida["porSituacao"],
            "nuvens": faltas["nuvens"],
            "chamadas": faltas["chamadas"],
            "handlesNaoAchados": faltas["handlesNaoAchados"],
            "regioesNaoAchadas": faltas["regioesNaoAchadas"],
            "itensSemLugarNoDesenho": [{"item": x.numero, "titulo": x.titulo,
                                        **({"ondeOlhar": x.onde_olhar} if x.onde_olhar else {})}
                                       for x in linhas if x.numero not in marcados and x.situacao != "pergunta"],
            "perguntasAbertas": sum(1 for x in linhas if x.situacao == "pergunta"),
            "quadroResumo": quadro,
            "mensagem": "Nuvens, chamadas e quadro-resumo na camada PRANCHAOK-PARECER (não plotam; o Prancha Ok "
                        "ignora essa camada). No carimbo, no quadro de áreas e onde as nuvens se amontoariam, cada "
                        "item é uma seta até uma chamada \"[nº] SITUAÇÃO\" ao lado (o título está no quadro-resumo). "
                        "Vermelho: em desacordo; laranja: dúvida; azul: conferir à mão; magenta: pergunta. O desenho "
                        "fica com alteração não salva.",
        }
    except Exception as e:
        return _erro(e)


@mcp.tool()
def ir_para_item(item: int, parecer_id: str | None = None) -> dict:
    """Mostra no AutoCAD (layout certo, zoom e seleção) onde está o item número `item` (o número
    que `ver_parecer` e as marcas mostram): o valor no desenho ou, se o item é de uma parte da
    prancha (planta de situação, corte, carimbo...), essa parte inteira."""
    try:
        pid = _parecer_id(parecer_id)
        p = marcas.com_lugar_medido(backend.parecer(pid), _medidas_do_parecer(pid))
        if p["status"] == "recusado":
            return _nada_a_marcar(p)
        escolhido = next((i for i in p["itens"] if i["ordem"] + 1 == item), None)
        if escolhido is None:
            return {"ok": False, "erro": f"O parecer não tem o item {item}."}
        linha = marcas.linha_do_item(escolhido)
        erro = None
        for handle in linha.handles:
            try:
                return {"ok": True, **autocad.ir(handle)}
            except AutocadIndisponivel as e:
                if "SEM_LUGAR" not in str(e):  # AutoCAD fora do ar: não adianta tentar o próximo
                    raise
                erro = e  # handle que o desenho não tem mais (ou dentro de um bloco): tenta o próximo
        if linha.regioes:  # a `regiao` achada ou, sem ela, o primeiro dos outros lugares achados
            r = linha.regioes[0]
            return {"ok": True, "regiao": r["rotulo"], **autocad.ir(r["handleTitulo"], r["caixa"], r["espaco"])}
        if erro:
            raise erro
        onde = f" Olhe em: {linha.onde_olhar}." if linha.onde_olhar else ""
        return {"ok": False, "erro": "Esse item não tem lugar no desenho (valor informado na web, documento do "
                                     f"processo, ou o que falta na prancha). Ele está no quadro-resumo.{onde}"}
    except (AutocadIndisponivel, ErroBackend, NaoConectado, ValueError) as e:
        return _erro(e)


@mcp.tool()
def limpar_marcas() -> dict:
    """Apaga todas as marcas (nuvens, chamadas) e o quadro-resumo do parecer (camada PRANCHAOK-PARECER) do desenho."""
    try:
        return autocad.limpar()
    except Exception as e:
        return _erro(e)


@mcp.tool()
def ler_desenho(camada: str | None = None, tipo: str | None = None, texto_contem: str | None = None,
                espaco: str | None = None, limite: int = 200) -> dict:
    """Leitura bruta do desenho aberto, para investigar ou medir: entidades com handle (h), tipo (t),
    camada (c), espaço (e: modelo/papel/bloco), layout (l), texto (x), pontos (p), altura (a),
    medida de cota (m). Filtros opcionais; `texto_contem` não diferencia maiúsculas."""
    try:
        entidades = autocad.ler_entidades()
        filtradas = [
            e for e in entidades
            if (camada is None or (e.get("c") or "").lower() == camada.lower())
            and (tipo is None or e.get("t") == tipo.upper())
            and (espaco is None or e.get("e") == espaco)
            and (texto_contem is None or texto_contem.lower() in (e.get("x") or "").lower())
        ]
        return {"ok": True, "total": len(entidades), "filtradas": len(filtradas),
                "entidades": filtradas[: max(1, min(limite, 2000))]}
    except Exception as e:
        return _erro(e)


# ---------------------------------------------------------------- sugestão

TAMANHO_MAXIMO_SUGESTAO = 4000  # o do relato no backend (relatos.TAMANHO_MAXIMO_RELATO)


def _itens_da_sugestao(itens: list[dict] | None) -> list[dict]:
    """[{item, comentario}] (o número que o parecer e as nuvens mostram) -> [{ordem, comentario}]."""
    saida = []
    for i in itens or []:
        numero, comentario = i.get("item"), str(i.get("comentario") or "").strip()
        if isinstance(numero, bool) or not isinstance(numero, int) or numero < 1 or not comentario:
            raise ValueError("Cada item da sugestão precisa do número do item (1, 2, ...) e de um comentário.")
        saida.append({"ordem": numero - 1, "comentario": comentario[:TAMANHO_MAXIMO_SUGESTAO]})
    return saida


@mcp.tool()
def enviar_sugestao(texto: str, parecer_id: str | None = None, itens: list[dict] | None = None) -> dict:
    """Manda à equipe do Prancha Ok as críticas e os falsos apontamentos que a pessoa contou na
    conversa (item que apontou erro que não existe, o que faltou apontar, medida que saiu errada).
    `texto`: o resumo, com as palavras dela (até 4000 caracteres). `itens`: [{item, comentario}]
    com o número do item do parecer. Vai ligada a `parecer_id` ou ao último parecer enviado deste
    computador. Mande só com o ok da pessoa."""
    try:
        texto = texto.strip()
        if not texto or len(texto) > TAMANHO_MAXIMO_SUGESTAO:
            return {"ok": False, "erro": f"O texto precisa ter de 1 a {TAMANHO_MAXIMO_SUGESTAO} caracteres: resuma."}
        lista = _itens_da_sugestao(itens)
        pid = parecer_id or ler_estado().get("ultimoParecer")
        if lista and not pid:
            return {"ok": False, "erro": "Para comentar itens, diga de qual parecer (parecer_id)."}
        try:
            backend.sugestao(texto, pid, lista)
        except ErroBackend as e:
            # O último parecer deste computador foi apagado no site (ou o projeto dele): a sugestão sem itens vai
            # como geral (pente fino de 04/10/2026, sugestão 8: "sem projetos, devolve erro 404").
            if e.codigo != "NAO_ENCONTRADO" or parecer_id or lista:
                raise
            gravar_estado(ultimoParecer=None)
            backend.sugestao(texto, None, [])
        return {"ok": True, "mensagem": "Sugestão enviada à equipe do Prancha Ok, que lê cada uma. Obrigado."}
    except ErroBackend as e:
        explicacao = {
            "NAO_ENCONTRADO": "o parecer não é desta empresa (ou não existe)",
            "SEM_ACESSO": "algum número de item não existe nesse parecer",
            "RELATO_INVALIDO": "texto vazio ou longo demais, ou item repetido",
            "MUITAS_TENTATIVAS": "muitas sugestões nesta hora; junte tudo numa só e tente mais tarde",
        }.get(e.codigo)
        return {"ok": False, "erro": f"{e}" + (f": {explicacao}" if explicacao else "")}
    except Exception as e:
        return _erro(e)


def rodar() -> None:
    # Extensão e plugin não rodam script de instalação: o servidor se prepara ao subir.
    instalacao.preparar_ao_subir()
    mcp.run()
