"""O servidor MCP do Prancha Ok rodado como arquivo: `uv run src/servidor_mcp.py`.

É o ponto de entrada da extensão do Claude Desktop (.mcpb, servidor do tipo uv) e do
plugin do Claude Code e do Codex. O mesmo que `python -m prancha_ok_autocad` ou o
comando `prancha-ok-autocad`; o uv instala as dependências do pyproject.toml.
"""
from prancha_ok_autocad.__main__ import main

if __name__ == "__main__":
    main()
