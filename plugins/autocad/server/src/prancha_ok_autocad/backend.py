"""Cliente das rotas /cliente/v1 do backend (packages/backend/convex/clienteHttp.ts)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import keyring

from .locais import api

_COFRE = "prancha-ok-autocad"


class ErroBackend(RuntimeError):
    def __init__(self, status: int, codigo: str):
        super().__init__(f"{codigo} (HTTP {status})")
        self.status, self.codigo = status, codigo


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
        if r.status_code == 401:
            raise NaoConectado("A conexão com o Prancha Ok não vale mais: use a ferramenta `conectar`.")
        raise ErroBackend(r.status_code, codigo)
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


def _armazenar(projeto_id: str, conteudo: bytes, tipo: str) -> str:
    """Manda os bytes direto ao storage do Convex (URL de envio) e devolve o storageId."""
    envio = _autenticado("POST", "/cliente/v1/envios", json={"projetoId": projeto_id})
    with httpx.Client(timeout=300.0) as c:
        return _resposta(c.post(envio["url"], content=conteudo, headers={"Content-Type": tipo}))["storageId"]


def enviar_prancha(projeto_id: str, arquivo: Path, leitura: dict | None = None,
                   compartilhar_prancha: bool = False, respostas: dict[str, float] | None = None) -> dict:
    """Envia a prancha, DWG ou DXF (e, se houver, a leitura do AutoCAD, só com DWG: { produto,
    versaoAcad, versaoLisp, entidades }) e abre o parecer: {parecerId, numero, url}.
    `respostas`: as medidas que o responsável técnico confirmou ({campo: número}), que entram
    já neste parecer."""
    corpo: dict = {"projetoId": projeto_id, "storageId": _armazenar(projeto_id, arquivo.read_bytes(),
                                                                    "application/octet-stream"),
                   "nomeArquivo": arquivo.name}
    if respostas:
        corpo["respostas"] = respostas
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
