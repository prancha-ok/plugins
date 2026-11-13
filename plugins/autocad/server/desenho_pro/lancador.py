"""Lançador do autocad-mcp-pro 1.6.0 (MIT, Umutcan Edizsalan) dentro do conector do Prancha Ok (0.7.0).

Roda no ambiente fixo desta pasta (pyproject.toml + uv.lock, Python 3.12 por .python-version), nunca no do conector,
e não importa nada do conector. A ponte (src/prancha_ok_autocad/ponte.py) sobe assim, como processo filho por
stdio:

    <desenho_pro>/.venv/Scripts/python.exe -I -X utf8 <desenho_pro>/lancador.py      (bin/python fora do Windows)

`-I`: nem a pasta do script nem variáveis PYTHON* entram no sys.path; o lançador põe esta pasta no FIM do sys.path,
só para achar os módulos dele (portugues.py, camadas.py, blindagem.py), que não têm o nome de nenhum módulo do pro.

Contrato de entrada (variáveis de ambiente que o conector manda; todo o resto do ambiente herdado com FASTMCP_,
EZDXF_, MCP_, UV_, PYTHON e as variáveis do pro é apagado e trocado pela tabela fixa de blindagem.ambiente_fixo):

    AUTOCAD_MCP_BACKEND            "com" (Windows, AutoCAD completo aberto) ou "ezdxf" (testes, fora do Windows).
                                   Ausente: "com" no Windows, "ezdxf" fora. Outro valor ("auto"...): não sobe.
    DISCOVERY_MODE, TOOL_PACKS     o conector manda search e core,arch; o lançador força esses valores de qualquer
                                   jeito (e TOOL_PROFILE=full, DANGEROUS_COMMANDS_ENABLED=false, ENABLE_3D=false).
    PRANCHA_OK_DESENHO_PASTAS      lista JSON de pastas absolutas onde o pro pode ler e gravar arquivos: a do desenho
                                   aberto e a de saída do conector. Lida só na subida (pasta nova = subir outro
                                   filho). Pasta dentro de qualquer `.prancha-ok` é ignorada (e qualquer caminho
                                   ali, recusado). Ausente ou vazia: todo caminho é recusado.
                                   Extensões: gravar .dwg .dxf .dwt .pdf .png .csv .xlsx; ler, também .lin e imagens.
    PRANCHA_OK_DESENHO_BASE        pasta nossa (padrão %USERPROFILE%\\.prancha-ok\\desenho-pro): `trabalho/` vira o
                                   cwd (esvaziada a cada subida) e `fastmcp/` o FASTMCP_HOME.
    PRANCHA_OK_DESENHO_LOG         arquivo do log do Python do filho (512 KB + 1 cópia). Ausente: só avisos no stderr.
    PRANCHA_OK_DESENHO_BLOQUEADAS  lista JSON de ferramentas a tirar do registro, além do system_launch e do
                                   system_set_variable (sempre).
                                   Nome que não existe é ignorado.
    COM_CALL_TIMEOUT,              prazo de cada chamada no filho, em segundos (5 a 600; padrão 60 e 120): a ponte
    EZDXF_CALL_TIMEOUT             manda menos que o prazo dela, para o filho desistir antes.

O que fica igual ao pro: todas as ferramentas de core,arch (menos system_set_variable, D24=a), inclusive
system_run_command e system_run_lisp (decisão D22=c), com a lista de proteção dele ligada. O que muda (nesta ordem; a ordem importa):

1. lê a entrada e fixa o ambiente e o cwd ANTES de importar o fastmcp (ele lê o ambiente e o ./.env ao ser importado);
2. confere a versão instalada: os ajustes mexem por dentro e valem só para a 1.6.0;
3. confere TODOS os ajustes (caminhos, português, camadas) antes de aplicar o primeiro, e aplica: tudo ou nada (se
   algum falha, o servidor não sobe);
   - caminhos: o validate_path nosso (blindagem.py);
   - português: lang "pt" nas ferramentas arch_* (vocabulário, P/J, vírgula, catálogo, quadros em metros, DIMLFAC no
     ezdxf; portugues.py);
   - camadas: A-WALL-E-N e as outras viram PRANCHAOK-PLANTA-* (camadas.py);
4. importa o servidor dele, tira o system_launch e o system_set_variable (D24=a) do registro, handle só hexadecimal no trim/fillet/chamfer/extend e,
   no COM, só um AutoCAD já aberto;
5. sobe em stdio, explicitamente, sem banner: `mcp.run(transport="stdio", show_banner=False)`.

Saída: o stdout é o canal MCP (nada aqui escreve nele). Códigos de saída sem subir: 2 entrada inválida, 3 versão do
autocad-mcp-pro diferente da conferida, 4 algum ajuste não confere; a frase vai no stderr, começando por
"[prancha-ok]".
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

VERSAO_ESPERADA = "1.6.0"
AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.append(str(AQUI))  # no fim: os módulos do pro (server, config, security...) vêm antes

import blindagem  # noqa: E402  (só biblioteca padrão no topo)


class NaoSobe(Exception):
    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def _configurar_log(caminho: Path | None) -> None:
    raiz = logging.getLogger()
    for h in list(raiz.handlers):  # o basicConfig dele é INFO no stderr e ignora LOG_LEVEL
        raiz.removeHandler(h)
    if caminho:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = logging.handlers.RotatingFileHandler(caminho, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
        arquivo.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        raiz.addHandler(arquivo)
    raiz.setLevel(logging.WARNING)
    # Uma linha por chamada (TOOL OK / TOOL ERR, com o tempo), só no arquivo: é o que ajuda a investigar.
    logging.getLogger("autocad_mcp").setLevel(logging.INFO if caminho else logging.WARNING)
    for nome in ("fastmcp", "mcp", "FastMCP"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.WARNING)


def preparar(ambiente=None):
    """Tudo menos subir: devolve (server, entrada, tiradas). Levanta NaoSobe."""
    try:
        entrada = blindagem.ler_entrada(os.environ if ambiente is None else ambiente)
    except blindagem.EntradaInvalida as exc:
        raise NaoSobe(2, f"entrada inválida: {exc}") from exc
    blindagem.fixar_ambiente(entrada)

    import version  # o version.py de topo do pacote dele (só biblioteca padrão)

    if version.__version__ != VERSAO_ESPERADA:
        raise NaoSobe(3, f"autocad-mcp-pro {version.__version__} no ambiente; o lançador foi conferido na "
                         f"{VERSAO_ESPERADA}. Rode `uv sync --frozen` em desenho_pro.")
    import camadas
    import portugues

    try:
        # Tudo conferido antes de aplicar o primeiro.
        blindagem.conferir_caminhos()
        portugues.conferir()
        camadas.conferir()
        blindagem.aplicar_caminhos(entrada)
        portugues.aplicar()
        camadas.aplicar()
        import server

        tiradas = blindagem.aplicar_no_servidor(server, entrada)
        faltam = blindagem.caminhos_sem_troca()
        if faltam:
            raise RuntimeError(f"validate_path original ainda em {', '.join(faltam)}")
        import config

        if config.settings.dangerous_commands_enabled or config.settings.discovery_mode != "search":
            raise RuntimeError("DANGEROUS_COMMANDS_ENABLED/DISCOVERY_MODE não ficaram como o lançador fixou")
    except NaoSobe:
        raise
    except Exception as exc:
        raise NaoSobe(4, f"o ajuste do autocad-mcp-pro {VERSAO_ESPERADA} não confere: {exc}") from exc
    return server, entrada, tiradas


def main() -> None:
    try:
        server, entrada, tiradas = preparar()
    except NaoSobe as exc:
        print(f"[prancha-ok] {exc}", file=sys.stderr)
        sys.exit(exc.codigo)
    _configurar_log(entrada.log)
    log = logging.getLogger("autocad_mcp")
    log.info("Prancha Ok: lançador pronto (%s); tiradas: %s; pastas: %s", entrada.backend, ", ".join(tiradas) or "-",
             ", ".join(str(p) for p in entrada.pastas) or "-")
    for motivo in entrada.ignoradas:
        log.warning("Prancha Ok: pasta ignorada: %s", motivo)
    server.mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
