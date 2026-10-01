"""Preparar e desfazer o AutoCAD para o MCP (comandos `instalar` e `desinstalar`).

Desde a 0.2.0 o servidor se instala sozinho (instalacao.py): copia o LISP ao subir e põe
a pasta no TRUSTEDPATHS pelo próprio comando mandado ao AutoCAD. O `instalar` continua
para quem quer deixar tudo pronto antes de abrir o AutoCAD (pelo registro, fora do MSIX).

O MCP carrega o prancha_ok.lsp sozinho (autocad.py), de %USERPROFILE%\\.prancha-ok\\lisp.
Para o AutoCAD não recusar nem perguntar a cada desenho (SECURELOAD), essa pasta
entra no TRUSTEDPATHS. Nada do escritório é sobrescrito: nem o acaddoc.lsp, nem
as outras pastas confiáveis.

Onde gravar o TRUSTEDPATHS:
- AutoCAD aberto: pelo próprio AutoCAD (COM no completo; no LT, pela linha de
  comando), e ele mesmo guarda no perfil ao fechar. É o único jeito que funciona
  dentro do Claude Desktop do Windows (app MSIX), onde o registro é virtualizado:
  o que se grava em HKCU\\Software não chega ao AutoCAD (teste na VM, 29/09/2026).
- AutoCAD fechado e fora do MSIX: no registro, em cada perfil.
"""
from __future__ import annotations

import subprocess
import sys
import time

from . import backend
from .instalacao import preparar
from .locais import empacotado, pasta, pasta_lisp

_RAIZ = r"Software\Autodesk\AutoCAD"


def _autocad_aberto() -> bool:
    saida = subprocess.run(["tasklist", "/FI", "IMAGENAME eq acad.exe", "/NH"], capture_output=True, text=True)
    return "acad.exe" in saida.stdout.lower()


def _mesma_pasta(a: str, b: str) -> bool:
    return a.strip().rstrip("\\/").lower().replace("/", "\\") == b.strip().rstrip("\\/").lower().replace("/", "\\")


def _com_pastas(atual: str, alvo: str, incluir: bool) -> str:
    pastas = [p for p in str(atual or "").split(";") if p.strip()]
    sem = [p for p in pastas if not _mesma_pasta(p, alvo)]
    return ";".join([*sem, alvo] if incluir else sem)


# ---------------------------------------------------------------- AutoCAD aberto

def _documento_com():
    import win32com.client

    return win32com.client.GetActiveObject("AutoCAD.Application").ActiveDocument


def _trustedpaths_pelo_autocad(alvo: str, incluir: bool) -> str:
    """Grava pelo AutoCAD aberto. Devolve como ficou (lido de volta) ou "?" se não deu para ler."""
    try:
        documento = _documento_com()
        documento.SetVariable("TRUSTEDPATHS", _com_pastas(documento.GetVariable("TRUSTEDPATHS"), alvo, incluir))
        return str(documento.GetVariable("TRUSTEDPATHS"))
    except Exception:  # AutoCAD LT (sem COM) ou sem desenho aberto
        pass
    # LT: o mesmo canal do MCP (WM_COPYDATA), com uma expressão AutoLISP.
    from .autocad import _digitar

    alvo_lisp = alvo.replace("\\", "/")
    if incluir:
        expressao = (f'(if (not (vl-string-search (strcase "{alvo_lisp}") (strcase (vl-string-translate "\\\\" "/" '
                     f'(getvar "TRUSTEDPATHS"))))) (setvar "TRUSTEDPATHS" (strcat (getvar "TRUSTEDPATHS") ";{alvo_lisp}")))')
    else:
        expressao = (f'(setvar "TRUSTEDPATHS" (vl-string-subst "" ";{alvo_lisp}" (vl-string-translate "\\\\" "/" '
                     '(getvar "TRUSTEDPATHS"))))')
    _digitar(expressao)
    time.sleep(1)
    return "?"


# ---------------------------------------------------------------- AutoCAD fechado (registro)

def _perfis():
    """(chave de Variables, descrição) de cada perfil de cada AutoCAD instalado para este usuário."""
    import winreg

    def filhos(chave):
        i = 0
        while True:
            try:
                yield winreg.EnumKey(chave, i)
            except OSError:
                return
            i += 1

    try:
        raiz = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RAIZ)
    except OSError:
        return
    with raiz:
        for versao in list(filhos(raiz)):  # R25.0, R25.1, R26.0...
            with winreg.OpenKey(raiz, versao) as chave_versao:
                for produto in list(filhos(chave_versao)):  # ACAD-xxxx:416 (idioma)
                    caminho = rf"{_RAIZ}\{versao}\{produto}\Profiles"
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as perfis:
                            for perfil in list(filhos(perfis)):
                                yield rf"{caminho}\{perfil}\Variables", f"{versao} {produto} {perfil}"
                    except OSError:
                        continue


def _trustedpaths_no_registro(alvo: str, incluir: bool) -> int:
    import winreg

    alterados = 0
    for chave, _descricao in _perfis():
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, chave, 0, winreg.KEY_READ | winreg.KEY_WRITE) as variaveis:
            try:
                atual, _ = winreg.QueryValueEx(variaveis, "TRUSTEDPATHS")
            except OSError:
                atual = ""
            novo = _com_pastas(atual, alvo, incluir)
            if novo != str(atual):
                winreg.SetValueEx(variaveis, "TRUSTEDPATHS", 0, winreg.REG_SZ, novo)
                alterados += 1
    return alterados


# ---------------------------------------------------------------- comandos

def instalar() -> int:
    if sys.platform != "win32":
        print("O MCP do Prancha Ok para AutoCAD roda no Windows.")
        return 1
    preparar()
    print(f"LISP do Prancha Ok em {pasta_lisp() / 'prancha_ok.lsp'}")
    alvo = str(pasta_lisp())
    if _autocad_aberto():
        lido = _trustedpaths_pelo_autocad(alvo, incluir=True)
        if lido == "?":
            print("Pasta confiável enviada ao AutoCAD pela linha de comando (AutoCAD LT). Confira com a ferramenta "
                  "`status` do MCP: o bloco autocad mostra o trustedpaths.")
        elif any(_mesma_pasta(p, alvo) for p in lido.split(";")):
            print(f"Pasta confiável no AutoCAD: {alvo} (conferido lendo o TRUSTEDPATHS de dentro do AutoCAD).")
        else:
            print(f"O AutoCAD não aceitou {alvo} no TRUSTEDPATHS. Quando ele perguntar se pode carregar o "
                  "prancha_ok.lsp, escolha 'Sempre carregar'.")
            return 4
    elif empacotado():
        # Dentro do MSIX o registro é virtualizado: gravar lá não adianta.
        print("Abra o AutoCAD com um desenho e rode de novo: aqui (Claude Desktop do Windows) só dá para "
              "configurar a pasta confiável com o AutoCAD aberto.")
        return 2
    else:
        if not list(_perfis()):
            print("Não achei o AutoCAD instalado para este usuário (abra o AutoCAD uma vez e rode de novo). "
                  "O conector funciona só no AutoCAD (2024 ou mais novo, completo ou LT), não no GstarCAD, "
                  "BricsCAD, ZWCAD e outros compatíveis: neles, envie o DWG pelo site.")
            return 3
        alterados = _trustedpaths_no_registro(alvo, incluir=True)
        print(f"Pasta confiável adicionada em {alterados} perfil(is) do AutoCAD." if alterados
              else "A pasta já era confiável em todos os perfis do AutoCAD.")
    print("Pronto. Com o AutoCAD aberto numa prancha, peça no assistente: \"conecte ao Prancha Ok\".")
    return 0


def desinstalar() -> int:
    """Tira a pasta das confiáveis, esquece a conexão e apaga o conteúdo de
    %USERPROFILE%\\.prancha-ok. A pasta em si fica: apagada e recriada de dentro do
    MSIX, ela pode parar onde o AutoCAD não enxerga."""
    if sys.platform != "win32":
        return 1
    alvo = str(pasta_lisp())
    if _autocad_aberto():
        _trustedpaths_pelo_autocad(alvo, incluir=False)
        print("Pasta tirada das confiáveis do AutoCAD.")
    elif not empacotado():
        print(f"Pasta tirada das confiáveis em {_trustedpaths_no_registro(alvo, incluir=False)} perfil(is) do AutoCAD.")
    else:
        print("Para tirar a pasta das confiáveis, rode de novo com o AutoCAD aberto (ou apague em Opções > Arquivos).")
    backend.esquecer_token()
    base = pasta()
    for item in (base / "lisp", base / "ipc"):
        for arquivo in item.glob("*"):
            arquivo.unlink(missing_ok=True)
    (base / "estado.json").unlink(missing_ok=True)
    print(f"Conexão esquecida e arquivos do Prancha Ok apagados de {base}. Para desligar o computador da conta "
          "também, revogue em Configurações > Conexões no Prancha Ok.")
    return 0
