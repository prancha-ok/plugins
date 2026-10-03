# Prancha Ok para AutoCAD: instalação

Guia para o assistente (Claude Code ou Codex) que está instalando este MCP a
pedido do usuário. O usuário colou o prompt da página
<https://pranchaok.com.br/autocad>: o zip foi baixado de lá (sha256 conferido
com o da página) e extraído nesta pasta, normalmente
`%USERPROFILE%\prancha-ok-autocad`. Para atualizar, o mesmo prompt extrai a
versão nova por cima e repete os passos abaixo (o `uv sync` e o `instalar`
podem rodar de novo sem problema).

O que o MCP faz: liga o AutoCAD aberto ao Prancha Ok. Envia a prancha salva,
traz o parecer e marca no desenho, com nuvens, os itens que pedem atenção, numa
camada própria (`PRANCHAOK-PARECER`) que não plota. Ele **nunca altera** o que o arquiteto
desenhou.

## Requisitos

- Windows 10 ou 11.
- AutoCAD 2024 ou mais novo, completo ou LT. Não funciona no Mac, nem em
  programas compatíveis com DWG (GstarCAD, BricsCAD, ZWCAD, progeCAD,
  DraftSight): neles, o usuário envia o DWG pelo site. Se o usuário só tem um
  desses, avise antes de instalar.
- Python 3.10 a 3.13. Se não houver, avise o usuário e mande o link
  <https://www.python.org/downloads/windows/> (marcar "Add python.exe to PATH").

## Passos (o assistente faz, sem perguntar)

Chame de `<pasta>` o caminho completo desta pasta (ex.:
`C:\Users\ana\prancha-ok-autocad`).

1. Instale as dependências:
   ```
   python -m pip install --user uv
   python -m uv sync --python 3.12
   ```
   (dentro de `<pasta>`). Isso cria `<pasta>\.venv`.
2. Registre o MCP no assistente que você é:
   - Claude Code (terminal):
     `claude mcp add prancha-ok --scope user -- "<pasta>\.venv\Scripts\python.exe" -m prancha_ok_autocad`
   - Claude Desktop (aba Code): o comando `claude` não fica no PATH. Acrescente
     em `%USERPROFILE%\.claude.json`, dentro de `"mcpServers"` (crie se não houver),
     o mesmo que o `claude mcp add --scope user` grava:
     ```json
     "prancha-ok": {
       "type": "stdio",
       "command": "<pasta>\\.venv\\Scripts\\python.exe",
       "args": ["-m", "prancha_ok_autocad"],
       "env": {}
     }
     ```
   - Codex: `codex mcp add prancha-ok -- "<pasta>\.venv\Scripts\python.exe" -m prancha_ok_autocad`.
     Se o comando `codex` não existir (app da Microsoft Store), acrescente em
     `%USERPROFILE%\.codex\config.toml`:
     ```toml
     [mcp_servers.prancha-ok]
     command = "<pasta>/.venv/Scripts/python.exe"
     args = ["-m", "prancha_ok_autocad"]
     ```
     (barras normais no caminho).
3. Nada a rodar: o MCP se instala sozinho (0.2.0 ou mais nova). Ao subir, ele
   copia o LISP para `%USERPROFILE%\.prancha-ok\lisp`; no primeiro comando ao
   AutoCAD, põe essa pasta entre as confiáveis (`TRUSTEDPATHS`), pelo próprio
   AutoCAD, sem mexer no `acaddoc.lsp` nem nas outras pastas. Se quiser deixar
   pronto antes, com o AutoCAD aberto num desenho:
   `"<pasta>\.venv\Scripts\python.exe" -m prancha_ok_autocad instalar`.
4. Avise o usuário para reiniciar o assistente (para carregar o MCP), abrir o
   AutoCAD com uma prancha e pedir: "conecte ao Prancha Ok". A ferramenta
   `conectar` abre o navegador; o usuário confere o código e aprova.

Não rode nada que escreva no DWG durante a instalação.

## Atualizar

Não rode o `desinstalar`. Extraia a versão nova por cima de `<pasta>`, apague as
pastas `__pycache__` de `<pasta>\src` (e de `<pasta>\src\prancha_ok_autocad`), repita o
passo 1 e reconecte o MCP no assistente (`/mcp`). Sem apagar o `__pycache__`, o Python pode
seguir com o código da versão anterior (os zips até a 0.3.2 tinham a mesma data em todos os
arquivos). O LISP novo é copiado e carregado
sozinho (a versão dele acompanha a do pacote).

## Claude Desktop no Windows

O Claude Desktop é um app empacotado (MSIX). O MCP e tudo o que o assistente roda
herdam o contêiner dele, e o Windows desvia o que eles gravam em
`%LOCALAPPDATA%`/`%APPDATA%` e em `HKCU\Software` para dentro do pacote, onde o
AutoCAD não enxerga. Por isso:

- a troca com o AutoCAD fica em `%USERPROFILE%\.prancha-ok` (fora de AppData,
  o Windows não desvia);
- a pasta confiável é gravada pelo AutoCAD aberto, não pelo registro.

Se algo antigo ficou em `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Local\PranchaOk`,
pode apagar.

## Uso

"Envie esta prancha para o Prancha Ok", "marque os erros no desenho",
"me leva até o item 3", "o afastamento frontal é 3 m e tem rede de esgoto" (responde
as dúvidas do parecer). O envio usa o desenho salvo: o assistente pede para salvar
quando precisa. Se algo não funcionar, peça "diagnostica o Prancha Ok".

## Desinstalar

Com o AutoCAD aberto:

1. `"<pasta>\.venv\Scripts\python.exe" -m prancha_ok_autocad desinstalar`
   (tira a pasta das confiáveis, esquece a conexão e apaga o conteúdo de
   `%USERPROFILE%\.prancha-ok`).
2. `claude mcp remove prancha-ok --scope user` ou `codex mcp remove prancha-ok`
   (ou apague `"prancha-ok"` de `mcpServers` no `.claude.json`, ou a seção
   `[mcp_servers.prancha-ok]` do `config.toml`).
3. Apague `<pasta>`.
4. No Prancha Ok, em Configurações > Conexões, revogue este computador.

## Para quem desenvolve

`PRANCHA_OK_API` troca o backend (padrão: produção). Teste local com a VM:
`claude mcp add prancha-ok --scope user --env PRANCHA_OK_API=http://172.22.0.1:3211 -- …`.
Código e decisões: `apps/autocad-mcp` e `docs/planos/autocad-mcp.md` no repositório do Prancha Ok.
O canal com o AutoCAD parte da ideia do [autocad-mcp](https://github.com/puran-water/autocad-mcp)
(MIT, ver `LICENSE-autocad-mcp`).
