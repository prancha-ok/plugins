# Desenho profissional do conector do Prancha Ok

Esta pasta é o ambiente fixo do **autocad-mcp-pro 1.6.0**, de Umutcan Edizsalan, licença MIT
(<https://github.com/U-C4N/Autocad-MCP>; o texto da licença está em `LICENSE-autocad-mcp-pro`, ao lado). O conector
do Prancha Ok o usa para desenhar no AutoCAD completo: a planta baixa por especificação (paredes com junções limpas e
hachura, portas, janelas, cotas, quadros) e as outras ferramentas de desenho dele.

Nada do código do autocad-mcp-pro está nesta pasta: o `uv` o instala do PyPI pelo `uv.lock` (com os hashes), em
`.venv/`, na primeira subida do conector. Aqui ficam só:

- `pyproject.toml`, `uv.lock` e `.python-version` (3.12): o ambiente, separado do do conector;
- `lancador.py`: sobe o autocad-mcp-pro como processo filho do conector, por stdio;
- `portugues.py`: quadros, rótulos e cotas em português (vírgula decimal, P/J, metros nos quadros);
- `camadas.py`: as camadas da planta viram `PRANCHAOK-PLANTA-*`;
- `blindagem.py`: ambiente limpo, pastas e extensões permitidas, só um AutoCAD já aberto, sem `system_launch`.

Só no Windows, com o AutoCAD completo aberto: o AutoCAD LT não tem a automação (COM/ActiveX) de que o
autocad-mcp-pro depende. No LT, o conector desenha o terreno e a planta com o desenho dele.
