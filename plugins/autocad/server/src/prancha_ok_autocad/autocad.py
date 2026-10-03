"""Canal com o AutoCAD: um pedido em arquivo e o comando digitado na janela.

A ideia vem do puran-water/autocad-mcp (MIT, ver LICENSE-autocad-mcp):
  1. grava pedido-<id>.lsp na pasta de troca: o comando e cada argumento, um
     dado AutoLISP por linha (pedido.py), que o LISP lê com `read` (não avalia nada);
  2. manda à linha de comando do AutoCAD (WM_COPYDATA, sem roubar o foco;
     COM SendCommand como plano B no AutoCAD completo)
     (progn (if (/= *pok-versao* "x") (load "…/prancha_ok.lsp")) (c:pok-mcp));
  3. espera resposta-<id>.jsonl (a 1ª linha diz ok ou erro).
Carregar o LISP pelo próprio comando dispensa mexer no acaddoc.lsp do
escritório. O mesmo comando, antes de carregar, põe a pasta do LISP no TRUSTEDPATHS
se ela ainda não está lá (instalacao.py): não há passo de instalação à parte.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

from . import __version__
from .instalacao import expressao_confiavel
from .locais import lisp_instalado, pasta_ipc
from .pedido import chamada, marca, pedacos_quadro, pedido_lisp, regiao

INTERVALO_S = 0.1
PRAZO_PADRAO_S = 20.0


class AutocadIndisponivel(RuntimeError):
    """AutoCAD fechado, sem desenho aberto, ou o comando não voltou no prazo."""


def _executavel(hwnd: int) -> str:
    """Nome do executável dono da janela (ex.: acad.exe), ou "" se não der para saber."""
    import win32api
    import win32con
    import win32process

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        processo = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return Path(win32process.GetModuleFileNameEx(processo, 0)).name.lower()
        finally:
            win32api.CloseHandle(processo)
    except Exception:  # processo de outro usuário ou já fechado
        return ""


def _janela_autocad() -> int | None:
    """A janela principal do AutoCAD (completo ou LT: os dois rodam como acad.exe).

    Não basta "autocad" no título: a aba do navegador aberta pelo `conectar`
    ("Conectar o AutoCAD — Prancha Ok") e uma pasta chamada autocad no Explorer
    também têm, e o comando ia parar lá (achado no teste na VM, 29/09/2026).
    Vale a janela de primeiro nível do acad.exe com classe Afx* (a moldura MFC,
    ex.: AfxMDIFrame140u). Com mais de uma, a que está em primeiro plano; senão a
    de cima na ordem das janelas (a usada mais recentemente)."""
    import win32gui

    achadas: list[int] = []

    def visitar(hwnd, _):
        if (win32gui.GetParent(hwnd) == 0 and win32gui.GetClassName(hwnd).startswith("Afx")
                and "autocad" in win32gui.GetWindowText(hwnd).lower() and _executavel(hwnd) == "acad.exe"):
            achadas.append(hwnd)
        return True

    win32gui.EnumWindows(visitar, None)
    if not achadas:
        return None
    frente = win32gui.GetForegroundWindow()
    return frente if frente in achadas else achadas[0]


# Programas compatíveis com DWG em que o conector não funciona (só no AutoCAD: a janela,
# o acad.exe e o AutoLISP do AutoCAD). O especialista testou no GstarCAD (30/09/2026).
OUTROS_CADS = {
    "gcad.exe": "GstarCAD",
    "bricscad.exe": "BricsCAD",
    "zwcad.exe": "ZWCAD",
    "icad.exe": "progeCAD/IntelliCAD",
    "draftsight.exe": "DraftSight",
}


def mensagem_sem_autocad(outro: str | None = None) -> str:
    """O que dizer quando a janela do AutoCAD não aparece (e, se houver, o outro CAD aberto)."""
    if outro:
        return (f"Não achei o AutoCAD aberto; achei o {outro}. O conector do Prancha Ok funciona só no AutoCAD "
                "(2024 ou mais novo, completo ou LT), não no GstarCAD, BricsCAD, ZWCAD e outros compatíveis. "
                "Nesses programas, envie o DWG pelo site (pranchaok.com.br): o parecer é o mesmo.")
    return ("Não achei a janela do AutoCAD. Abra o AutoCAD com a prancha e tente de novo. O conector funciona só "
            "no AutoCAD (2024 ou mais novo, completo ou LT), não no GstarCAD, BricsCAD, ZWCAD e outros compatíveis.")


def outro_cad_aberto() -> str | None:
    """Nome de um CAD compatível (não AutoCAD) com janela aberta, ou None."""
    if sys.platform != "win32":
        return None
    import win32gui

    achados: list[str] = []

    def visitar(hwnd, _):
        if win32gui.GetParent(hwnd) == 0 and win32gui.IsWindowVisible(hwnd):
            nome = OUTROS_CADS.get(_executavel(hwnd))
            if nome and nome not in achados:
                achados.append(nome)
        return True

    try:
        win32gui.EnumWindows(visitar, None)
    except Exception:  # só serve para a mensagem: sem ela, a genérica
        return None
    return achados[0] if achados else None


def _copydata(hwnd: int, texto: str) -> bool:
    """Manda o texto à linha de comando por WM_COPYDATA (dwData=1, UTF-16 com \\0).

    É o jeito que o AutoCAD aceita comando de outro processo: funciona no LT e no
    completo, com a linha de comando escondida (Ctrl+9) e sem roubar o foco. O
    PostMessage(WM_CHAR) no MDIClient, do upstream, não chega no AutoCAD 2027."""
    import ctypes
    from ctypes import wintypes

    class COPYDATASTRUCT(ctypes.Structure):
        _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]

    WM_COPYDATA, SMTO_ABORTIFHUNG = 0x004A, 0x0002
    buffer = ctypes.create_unicode_buffer(texto)  # termina em \0
    dados = COPYDATASTRUCT(1, ctypes.sizeof(buffer), ctypes.cast(buffer, ctypes.c_void_p))
    resultado = ctypes.c_size_t(0)
    enviado = ctypes.windll.user32.SendMessageTimeoutW(
        hwnd, WM_COPYDATA, 0, ctypes.byref(dados), SMTO_ABORTIFHUNG, 5000, ctypes.byref(resultado))
    return bool(enviado)


def _sendcommand(texto: str) -> bool:
    """Plano B, só no AutoCAD completo (o LT não tem COM): ActiveDocument.SendCommand."""
    try:
        import win32com.client

        win32com.client.GetActiveObject("AutoCAD.Application").ActiveDocument.SendCommand(texto)
        return True
    except Exception:  # LT, sem documento aberto, ou COM ocupado
        return False


def _janela_pronta() -> int:
    if sys.platform != "win32":
        raise AutocadIndisponivel("O canal com o AutoCAD só funciona no Windows.")
    import win32con
    import win32gui

    hwnd = _janela_autocad()
    if hwnd is None:
        raise AutocadIndisponivel(mensagem_sem_autocad(outro_cad_aberto()))
    if win32gui.IsIconic(hwnd):
        # Restaura sem tirar o foco de quem está usando o assistente.
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        time.sleep(0.3)
        if win32gui.IsIconic(hwnd):
            raise AutocadIndisponivel("O AutoCAD está minimizado. Restaure a janela e tente de novo.")
    return hwnd


def _digitar(texto: str) -> None:
    """Dois ESC (cancelam comando pela metade, inclusive de um pedido que venceu) e o texto + Enter."""
    hwnd = _janela_pronta()
    if not _copydata(hwnd, "\x1b\x1b") or not _copydata(hwnd, texto + "\r"):
        if not _sendcommand("\x1b\x1b" + texto + "\r"):
            raise AutocadIndisponivel("O AutoCAD não aceitou o comando (ocupado com uma janela aberta?). "
                                      "Feche caixas de diálogo abertas no AutoCAD e tente de novo.")


def _gatilho(ident: str) -> str:
    """O comando mandado ao AutoCAD. Diz ao LISP onde está a pasta de troca, põe a pasta
    do LISP entre as confiáveis se ainda não está (antes do `load`, para o SECURELOAD
    aceitar) e, se algo impede de chegar ao c:pok-mcp, grava o motivo em diag-<id>.txt
    (só com funções do próprio AutoLISP: funciona no LT e sem o LISP carregado)."""
    lsp = lisp_instalado().as_posix()
    ipc = pasta_ipc().as_posix() + "/"
    v = __version__
    return (
        f'(progn (setq *pok-dir* "{ipc}")'
        f' {expressao_confiavel()}'
        f' (defun pok-diag (x / f) (if (setq f (open "{ipc}diag-{ident}.txt" "w")) (progn (write-line x f) (close f))))'
        f' (cond ((not (findfile "{lsp}")) (pok-diag "LISP_NAO_ENCONTRADO"))'
        f' ((and (/= *pok-versao* "{v}") (vl-catch-all-error-p (vl-catch-all-apply (quote load) (list "{lsp}"))))'
        f' (pok-diag "LOAD_RECUSADO"))'
        f' ((/= *pok-versao* "{v}") (pok-diag "VERSAO_ERRADA"))'
        f' (t (c:pok-mcp))) (princ))'
    )


def _ultimo_prompt() -> str | None:
    """A última linha da linha de comando (LASTPROMPT), pelo COM (só AutoCAD completo)."""
    try:
        import win32com.client

        return str(win32com.client.GetActiveObject("AutoCAD.Application").ActiveDocument.GetVariable("LASTPROMPT"))
    except Exception:
        return None


def _erro_do_diagnostico(codigo: str) -> AutocadIndisponivel:
    lsp = lisp_instalado()
    if codigo == "LISP_NAO_ENCONTRADO":
        return AutocadIndisponivel(
            f"O AutoCAD não enxerga o LISP do Prancha Ok em {lsp}. Se o assistente roda no Claude Desktop do "
            "Windows, apague a pasta e deixe o MCP recriar (versão 0.1.3 ou mais nova usa %USERPROFILE%\\.prancha-ok, "
            "que o Windows não esconde do AutoCAD)."
        )
    if codigo == "LOAD_RECUSADO":
        return AutocadIndisponivel(
            f"O AutoCAD achou o LISP, mas não carregou ({lsp}). Com SECURELOAD ligado, ele só carrega de pasta "
            f"confiável, e o MCP põe {lsp.parent} no TRUSTEDPATHS a cada comando: se o AutoCAD não aceitou "
            "(política da empresa?), acrescente a pasta em Opções > Arquivos > Locais confiáveis ou, quando o "
            "AutoCAD perguntar, escolha 'Sempre carregar'."
        )
    return AutocadIndisponivel(
        f"O AutoCAD carregou um prancha_ok.lsp de outra versão (esperada {__version__}). Há mais de um MCP do "
        "Prancha Ok neste computador (ex.: a extensão do Claude Desktop e o plugin do Claude Code), de versões "
        "diferentes, usando a mesma pasta: atualize os dois ou deixe só um."
    )


def _ler(caminho: Path) -> str:
    dados = caminho.read_bytes()
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        # AutoCAD que não abre o arquivo em UTF-8 escreve em ANSI (Windows-1252).
        return dados.decode("cp1252")


def pedir(comando: str, *argumentos, prazo_s: float = PRAZO_PADRAO_S) -> list[dict]:
    """Manda o comando ao LISP e devolve as linhas JSON da resposta (a 1ª tem `ok`)."""
    pasta = pasta_ipc()
    ident = uuid.uuid4().hex[:12]
    pedido = pasta / f"pedido-{ident}.lsp"
    resposta = pasta / f"resposta-{ident}.jsonl"
    temporario = pasta / f"pedido-{ident}.tmp"
    diagnostico = pasta / f"diag-{ident}.txt"
    temporario.write_text(pedido_lisp(comando, *argumentos), encoding="utf-8")
    temporario.replace(pedido)
    try:
        gatilho = _gatilho(ident)
        _digitar(gatilho)
        limite = time.monotonic() + prazo_s
        plano_b = time.monotonic() + 3.0
        while time.monotonic() < limite:
            # O LISP apaga o pedido assim que o pega. Se em 3 s ele ainda está lá, o texto
            # não chegou: tenta uma vez pelo COM (AutoCAD completo).
            if plano_b and time.monotonic() > plano_b:
                plano_b = 0
                if pedido.exists():
                    _sendcommand(gatilho + "\r")
            if diagnostico.exists():
                raise _erro_do_diagnostico(_ler(diagnostico).strip())
            if resposta.exists():
                try:
                    linhas = [json.loads(linha) for linha in _ler(resposta).splitlines() if linha.strip()]
                except (OSError, ValueError):
                    time.sleep(INTERVALO_S)  # ainda sendo renomeado
                    continue
                if linhas and not linhas[0].get("ok"):
                    raise AutocadIndisponivel(f"O AutoCAD recusou '{comando}': {linhas[0].get('erro')}")
                return linhas
            time.sleep(INTERVALO_S)
        if pedido.exists():
            ultimo = _ultimo_prompt()
            raise AutocadIndisponivel(
                "O AutoCAD não chegou a ler o pedido. Confira se há um desenho aberto e nenhuma caixa de diálogo "
                "aberta (inclusive o aviso de segurança do LISP), e tente de novo."
                + (f" Última linha do AutoCAD: {ultimo}" if ultimo else "")
            )
        raise AutocadIndisponivel(
            "O comando chegou ao AutoCAD, mas o LISP do Prancha Ok não respondeu. Veja se o AutoCAD perguntou "
            "se pode carregar o prancha_ok.lsp (escolha 'Sempre carregar'). Com SECURELOAD ligado, o AutoCAD só "
            f"carrega LISP de pasta confiável: confira se {lisp_instalado().parent} está em Opções > Arquivos > "
            "Locais confiáveis. A linha de comando do AutoCAD (F2) mostra o erro."
        )
    finally:
        for arquivo in (pedido, resposta, temporario, diagnostico):
            arquivo.unlink(missing_ok=True)


def info() -> dict:
    return pedir("info")[0]


def ler_entidades(prazo_s: float = 120.0) -> list[dict]:
    """Todas as entidades do desenho (menos as marcas do parecer), uma por dicionário."""
    linhas = pedir("ler", prazo_s=prazo_s)
    if not linhas or "fim" not in linhas[-1]:
        raise AutocadIndisponivel("A leitura do desenho veio incompleta.")
    return linhas[1:-1]


# Nome do projeto no vínculo (XRECORD do desenho): cabe numa linha do pedido.
MAXIMO_NOME_PROJETO = 120


def marcar(marcas: list[tuple[str, int, str]]) -> dict:
    """Nuvem + rótulo em cada handle, na cor da situação. Cada marca vai numa linha do pedido:
    (handle cor rótulo), com o rótulo em ASCII (pedido.texto_mtext) cortado para caber.
    Devolve {marcadas: [handles], semLugar: [handles]}."""
    return pedir("marcar", *(marca(h, cor, rotulo) for h, cor, rotulo in marcas), prazo_s=60.0)[0]


def marcar_regioes(regioes: list[tuple]) -> dict:
    """Nuvem em volta de cada região (vista da prancha, carimbo, quadro de áreas): pela caixa
    ou, sem ela, em volta do título. Cada uma numa linha do pedido (pedido.regiao).
    Devolve {marcadas: [índices], semLugar: [índices]} (índice na lista pedida)."""
    return pedir("regioes", *(regiao(*r) for r in regioes), prazo_s=60.0)[0]


def caixas(handles: list[str]) -> list[dict]:
    """Onde está cada handle (0.3.4): uma linha por handle, {h, e: espaço, l: layout, c: caixa
    [x0 y0 x1 y1], a: altura do texto ou null} ou {h, semLugar: true} (o desenho não tem, ou está
    dentro de um bloco). chamadas.py decide com isso o que vira chamada e onde."""
    return pedir("caixas", *handles, prazo_s=60.0)[1:]


def marcar_chamadas(lista) -> dict:
    """Seta + rótulo de cada chamada (chamadas.Chamada), com a geometria já decidida.
    Devolve {marcadas: [índices], semLugar: [índices]} (índice na lista pedida)."""
    return pedir("chamadas", *(chamada(c.referencia, c.espaco, c.cor, c.altura, c.seta, c.largura_ponta,
                                       c.rotulo, c.texto) for c in lista), prazo_s=60.0)[0]


def limpar() -> dict:
    return pedir("limpar")[0]


def ir(handle: str | None, caixa: list[float] | None = None, espaco: str | None = None) -> dict:
    """Zoom no handle (e o seleciona) ou, com `caixa`, na caixa da região (no layout do
    título `handle`, ou no modelo se não há título)."""
    return pedir("ir", handle or "", [float(n) for n in caixa] if caixa else None, espaco or "")[0]


def vincular(projeto_id: str, projeto: str, empresa_id: str) -> dict:
    return pedir("vincular", projeto_id, projeto[:MAXIMO_NOME_PROJETO], empresa_id)[0]


def quadro(linhas: list[str]) -> dict:
    """Quadro-resumo do parecer na camada das marcas: um MTEXT, uma linha por parágrafo.
    O conteúdo vai em pedaços curtos (pedido.pedacos), que o LISP junta."""
    return pedir("quadro", *pedacos_quadro(linhas), prazo_s=60.0)[0]


def salvar() -> dict:
    """QSAVE do desenho aberto. Só com o consentimento da pessoa (o MCP pergunta)."""
    return pedir("salvar", prazo_s=60.0)[0]
