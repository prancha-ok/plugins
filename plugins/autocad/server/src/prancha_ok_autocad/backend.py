"""Cliente das rotas /cliente/v1 do backend (packages/backend/convex/clienteHttp.ts)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import httpx
import keyring

from .locais import api

_COFRE = "prancha-ok-autocad"


class ErroBackend(RuntimeError):
    def __init__(self, status: int, codigo: str, motivo: str | None = None, erros: list[str] | None = None):
        super().__init__(f"{codigo} (HTTP {status})")
        self.status, self.codigo = status, codigo
        # A frase pronta que algumas recusas trazem (ex.: TERRENO_DO_ZERO_INDISPONIVEL).
        self.motivo = motivo
        # As frases de uma recusa com várias (PROGRAMA_IMPOSSIVEL da planta: o que mudar no programa).
        self.erros = erros or []


class NaoConectado(RuntimeError):
    """Sem token, ou o token não vale mais (revogado, 90 dias sem uso, saiu da empresa)."""


# Token no Gerenciador de Credenciais do Windows (keyring), um por backend.
def token() -> str | None:
    return keyring.get_password(_COFRE, api())


def guardar_token(valor: str) -> None:
    keyring.set_password(_COFRE, api(), valor)


def esquecer_token() -> None:
    try:
        keyring.delete_password(_COFRE, api())
    except keyring.errors.PasswordDeleteError:
        pass


def _resposta(r: httpx.Response) -> dict | list:
    try:
        corpo = r.json()
    except ValueError:
        corpo = {}
    if r.status_code >= 400:
        codigo = corpo.get("codigo", "ERRO") if isinstance(corpo, dict) else "ERRO"
        motivo = corpo.get("motivo") if isinstance(corpo, dict) and isinstance(corpo.get("motivo"), str) else None
        erros = corpo.get("erros") if isinstance(corpo, dict) and isinstance(corpo.get("erros"), list) else []
        if r.status_code == 401:
            raise NaoConectado("A conexão com o Prancha Ok não vale mais: use a ferramenta `conectar`.")
        raise ErroBackend(r.status_code, codigo, motivo, [e for e in erros if isinstance(e, str)])
    return corpo


def _cliente() -> httpx.Client:
    return httpx.Client(base_url=api(), timeout=30.0)


def _autenticado(metodo: str, caminho: str, **kwargs) -> dict | list:
    atual = token()
    if not atual:
        raise NaoConectado("Este computador ainda não está conectado ao Prancha Ok: use a ferramenta `conectar`.")
    with _cliente() as c:
        return _resposta(c.request(metodo, caminho, headers={"Authorization": f"Bearer {atual}"}, **kwargs))


# ---------------------------------------------------------------- login pelo navegador

def abrir_pedido(nome_maquina: str) -> dict:
    """{codigo, segredo, url, expiraEm}"""
    with _cliente() as c:
        return _resposta(c.post("/cliente/v1/conexao", json={"nomeMaquina": nome_maquina}))


def buscar_token(segredo: str) -> dict:
    """{situacao: "pendente"} | {token, empresa} | erro 410 (recusado/expirado)."""
    with _cliente() as c:
        return _resposta(c.post("/cliente/v1/conexao/token", json={"segredo": segredo}))


# ---------------------------------------------------------------- dados

def eu() -> dict:
    return _autenticado("GET", "/cliente/v1/eu")


def projetos() -> list:
    return _autenticado("GET", "/cliente/v1/projetos")


def terreno_do_zero(projeto_id: str) -> dict:
    """O desenho de partida do projeto do zero (0.6.0), do estudo do lote ou do terreno do RGI conferido:
    {avisos, origem: "estudo" | "rgi", desenho: {unidade: "m", camadas, entidades, extensao}}. Sem como montar:
    409 TERRENO_DO_ZERO_INDISPONIVEL, com o `motivo`."""
    return _autenticado("GET", f"/cliente/v1/projetos/{quote(projeto_id, safe='')}/terreno-do-zero")


def planta(projeto_id: str, programa: dict) -> dict:
    """A planta baixa gerada pelo programa da casa (0.6.0, projeto do zero): o Prancha Ok desenha e confere o que
    desenhou. {desenho: {unidade: "m", camadas, entidades, extensao, escala, comodos, avisos} (no sistema do terreno
    desenhado), conferencia: {problemas: [{tipo, texto}], comodosLidos: [{nome, areaM2}], areaConstruidaM2, toPct, ca}}.
    422 PROGRAMA_IMPOSSIVEL com os `erros`; 409 TERRENO_DO_ZERO_INDISPONIVEL ou PLANTA_NA_LEGALIZACAO com o `motivo`."""
    return _autenticado("POST", f"/cliente/v1/projetos/{quote(projeto_id, safe='')}/planta",
                        json={"programa": programa})


def _armazenar(projeto_id: str, conteudo: bytes, tipo: str) -> str:
    """Manda os bytes direto ao storage do Convex (URL de envio) e devolve o storageId."""
    envio = _autenticado("POST", "/cliente/v1/envios", json={"projetoId": projeto_id})
    with httpx.Client(timeout=300.0) as c:
        return _resposta(c.post(envio["url"], content=conteudo, headers={"Content-Type": tipo}))["storageId"]


def enviar_prancha(projeto_id: str, arquivo: Path, leitura: dict | None = None,
                   compartilhar_prancha: bool = False) -> dict:
    """Envia a prancha, DWG ou DXF (e, se houver, a leitura do AutoCAD, só com DWG: { produto,
    versaoAcad, versaoLisp, entidades }) e abre o parecer: {parecerId, numero, url}. Sempre com a
    prévia (0.4.0): o parecer para depois da leitura, em "aguardando_medidas", até `confirmar`."""
    corpo: dict = {"projetoId": projeto_id, "storageId": _armazenar(projeto_id, arquivo.read_bytes(),
                                                                    "application/octet-stream"),
                   "nomeArquivo": arquivo.name, "previa": True}
    if leitura is not None:
        corpo["leitura"] = {
            "storageId": _armazenar(projeto_id, json.dumps(leitura, ensure_ascii=False).encode("utf-8"),
                                    "application/json"),
            "produto": leitura["produto"],
            "versaoAcad": leitura["versaoAcad"],
            "versaoLisp": leitura["versaoLisp"],
            "compartilharPrancha": compartilhar_prancha,
        }
    return _autenticado("POST", "/cliente/v1/pareceres", json=corpo)


def parecer(parecer_id: str) -> dict:
    return _autenticado("GET", f"/cliente/v1/pareceres/{parecer_id}")


def confirmar(parecer_id: str, valores: dict[str, float], respostas: dict[str, str | float]) -> dict:
    """A prévia conferida: as medidas confirmadas ou corrigidas e as respostas às perguntas. O mesmo parecer volta
    a processar e sai com tudo: {parecerId, numero, url}."""
    return _autenticado("POST", f"/cliente/v1/pareceres/{parecer_id}/confirmar",
                        json={"valores": valores, "respostas": respostas})


def terreno(parecer_id: str, ruas: list[str], area_m2: float | None) -> dict:
    """O terreno conferido pelo desenho (0.5.0): as letras dos lados que dão para a rua e a área (None: a conferida, a do
    RGI, a do IPTU ou a da prancha). {areaM2, testadaM, esquina, lados: [{letra, medidaM, posicao, rua}]}."""
    return _autenticado("POST", f"/cliente/v1/pareceres/{parecer_id}/terreno", json={"ruas": ruas, "areaM2": area_m2})


def rever(parecer_id: str, valores: dict[str, float], respostas: dict[str, str | float]) -> dict:
    """Medidas e respostas da prévia revistas depois do parecer (0.5.0): parecer novo {parecerId, numero, url}."""
    return _autenticado("POST", f"/cliente/v1/pareceres/{parecer_id}/rever",
                        json={"valores": valores, "respostas": respostas})


def responder(parecer_id: str, dados: dict, dispensas: list[dict]) -> dict:
    """Respostas às dúvidas (como o formulário da web): parecer novo {parecerId, numero, url}."""
    return _autenticado("POST", f"/cliente/v1/pareceres/{parecer_id}/respostas",
                        json={"dados": dados, "dispensas": dispensas})


def sugestao(texto: str, parecer_id: str | None, itens: list[dict]) -> dict:
    """Sugestão da conversa para a equipe do Prancha Ok (relato "sugestao"): {relatoId}.
    `itens`: [{ordem, comentario}] do parecer `parecer_id`."""
    corpo: dict = {"texto": texto, "itens": itens}
    if parecer_id:
        corpo["parecerId"] = parecer_id
    return _autenticado("POST", "/cliente/v1/sugestoes", json=corpo)
