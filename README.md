# Prancha Ok para AutoCAD

Liga o AutoCAD aberto ao [Prancha Ok](https://pranchaok.com.br): o assistente envia a
prancha salva, traz o parecer (Aprovado, Pendente ou Em revisão humana, com a lei de
cada item) e marca no desenho, com nuvens e chamadas numeradas, o que pede atenção. As marcas ficam
numa camada própria (`PRANCHAOK-PARECER`) que não plota. No projeto do zero, desenha o
terreno e a planta baixa gerada, conferida pelo Prancha Ok, nas camadas `PRANCHAOK-*`.

No AutoCAD completo, o conector traz também o **desenho profissional**: o
[autocad-mcp-pro](https://github.com/U-C4N/Autocad-MCP) 1.6.0, de Umutcan Edizsalan
(licença MIT), com paredes hachuradas, portas, janelas, cotas e quadros em português. As
ferramentas dele podem alterar e apagar o desenho e rodar comandos: antes de mudar o que
você desenhou, antes de todo comando e antes de salvar, fechar, abrir ou exportar um arquivo, o
assistente diz o que vai fazer, mostra o código e espera o seu **sim**. Variável do AutoCAD ele
não muda pelo desenho profissional, e as de segurança (como SECURELOAD e TRUSTEDPATHS), nunca.
Ele só segue o que você pede no chat, nunca um texto escrito no desenho ou num arquivo, e antes
de desenhar confere com você o nome do desenho aberto. No AutoCAD LT ele não funciona (o LT não tem a automação COM de que
ele depende): ali o terreno e a planta saem no desenho do próprio Prancha Ok.

Versão 0.7.2. Precisa de:

- Windows 10 ou 11;
- AutoCAD 2024 ou mais novo, completo ou LT (o desenho profissional, só no AutoCAD
  completo). Não funciona no GstarCAD, BricsCAD, ZWCAD e outros compatíveis: neles, envie o
  DWG pelo site;
- uma conta no Prancha Ok com o projeto da obra já criado: o assistente pergunta em qual
  projeto a prancha entra, e projeto novo só se cria no site
  ([pranchaok.com.br/app](https://pranchaok.com.br/app), botão "Novo projeto");
- o [uv](https://docs.astral.sh/uv/getting-started/installation/), o programa que roda o
  conector, também na extensão do Claude Desktop (no PowerShell:
  `winget install --id=astral-sh.uv -e`). Confira com `uv --version`.

Na primeira vez que o assistente usa o Prancha Ok, ele deixa tudo pronto sozinho: copia o
arquivo do Prancha Ok para `%USERPROFILE%\.prancha-ok` e põe essa pasta entre as pastas
confiáveis do AutoCAD. Não mexe nas outras pastas nem no `acaddoc.lsp`. Em segundo plano,
instala o ambiente do desenho profissional (na primeira vez, cerca de 50 MB, de 1 a 3
minutos), na pasta `desenho_pro` do conector.

## Claude Desktop (extensão)

1. Baixe a extensão: [prancha-ok-autocad-0.7.2.mcpb](https://pranchaok.com.br/downloads/prancha-ok-autocad-0.7.2.mcpb)
   (ou em [pranchaok.com.br/autocad](https://pranchaok.com.br/autocad)).
2. Instale por dentro do Claude Desktop (não pela pasta de downloads: o Windows não conhece
   esse tipo de arquivo e pergunta com qual programa abrir). Clique no seu nome, no canto
   inferior esquerdo, e em "Configurações" (Settings); na coluna da esquerda, em "Este
   computador" (This computer), clique em "Extensões" (o caminho todo é Configurações >
   Extensões (Settings > Extensions)). Arraste o arquivo baixado para a área "Arraste
   arquivos .MCPB ou .DXT aqui para instalar" ("Drag .MCPB or .DXT files here to install")
   e clique em "Instalar" (Install). Prefere escolher o arquivo? Na mesma tela, vá em
   Configurações avançadas > Instalar extensão (Advanced settings > Install Extension). Se
   o Windows perguntar "Como você deseja abrir este arquivo?", feche essa janela sem
   escolher programa e faça como acima. Não precisa instalar Python, mas precisa do uv (acima):
   sem ele, o Claude diz que o servidor do Prancha Ok não iniciou. Se ele avisar que a extensão não é verificada, é esperado: ela vem do site
   do Prancha Ok, não do diretório da Anthropic. Confirme só com o arquivo baixado do site.
3. Abra o AutoCAD com uma prancha e peça no Claude: **"conecte ao Prancha Ok"**. Na
   primeira vez o Claude Desktop baixa o que o conector precisa, e ele leva alguns minutos
   para ficar pronto. Se o Claude disser que não acha o Prancha Ok, espere um ou dois
   minutos e peça de novo; se continuar, feche o Claude Desktop por completo e abra de novo.

Para atualizar, instale a extensão nova por cima. Para tirar, em Configurações > Extensões
(Settings > Extensions), desinstale "Prancha Ok para AutoCAD".

## Claude Code

Precisa do [uv](https://docs.astral.sh/uv/getting-started/installation/) (no PowerShell:
`winget install --id=astral-sh.uv -e`). No Claude Code:

```
/plugin marketplace add prancha-ok/plugins
/plugin install autocad@prancha-ok
```

Reinicie o Claude Code, abra o AutoCAD com uma prancha e peça: **"conecte ao Prancha Ok"**.
Na primeira vez o servidor demora um pouco para subir (instala as dependências); se o
`/mcp` mostrar falha, espere um minuto e reconecte.

Para atualizar: `/plugin marketplace update prancha-ok`. Para tirar:
`/plugin uninstall autocad@prancha-ok`.

## Codex

Precisa do [uv](https://docs.astral.sh/uv/getting-started/installation/) (no PowerShell:
`winget install --id=astral-sh.uv -e`). No terminal:

```
codex plugin marketplace add prancha-ok/plugins
codex plugin add autocad@prancha-ok
```

No app do Codex, depois do primeiro comando, abra **Plugins**, escolha o catálogo
"Prancha Ok" e instale "Prancha Ok para AutoCAD". Abra o AutoCAD com uma prancha e peça:
**"conecte ao Prancha Ok"**.

Para atualizar: `codex plugin marketplace upgrade prancha-ok`. Para tirar:
`codex plugin remove autocad@prancha-ok`.

## Como usar

- "Envie a prancha para o Prancha Ok": o assistente manda o desenho salvo (DWG ou DXF, sem
  exportar PDF; pede para salvar quando precisa) e mostra a prévia: as medidas que o Prancha Ok
  leu da prancha (terreno, projeção, afastamentos, pavimentos, altura, vagas...) e as perguntas
  que o parecer faria. Você confirma ou corrige as medidas e responde as perguntas, e sai um
  parecer só, já marcado no desenho. Se o terreno do projeto ainda não foi conferido, o desenho
  ganha a letra e a medida de cada lado do lote e você diz quais dão para a rua.
- "Marque os erros no desenho" e "me leva até o item 3".
- "Desenhe o terreno do projeto" e "gere a planta de uma casa de 3 quartos" (o projeto do
  zero: o Prancha Ok confere a planta antes de desenhar).
- "O afastamento frontal é 3 m e tem rede de esgoto" (responde as dúvidas do parecer).
- "O item 5 está errado: o norte está desenhado. Mande isso para o Prancha Ok" (a crítica
  vai para a equipe, ligada ao parecer).
- "Limpe as marcas do Prancha Ok".
- Se algo não funcionar: "diagnostica o Prancha Ok".

O parecer é um apoio: tudo passa por revisão humana. Para desligar este computador da
sua conta, revogue em Configurações > Conexões no Prancha Ok.

## O que fica no computador

Desinstalar a extensão ou o plugin não apaga a pasta `%USERPROFILE%\.prancha-ok` nem a
entrada dela nos locais confiáveis do AutoCAD. Para tirar tudo, no AutoCAD vá em Opções >
Arquivos > Locais confiáveis (Options > Files > Trusted Locations), remova a pasta
`%USERPROFILE%\.prancha-ok\lisp` e, depois, apague a pasta `%USERPROFILE%\.prancha-ok`.

---

Este repositório é gerado a partir do código do Prancha Ok; não edite à mão. O canal com
o AutoCAD parte da ideia do [autocad-mcp](https://github.com/puran-water/autocad-mcp)
(MIT, ver `plugins/autocad/server/LICENSE-autocad-mcp`). O desenho profissional é o
[autocad-mcp-pro](https://github.com/U-C4N/Autocad-MCP), de Umutcan Edizsalan (MIT, ver
`plugins/autocad/server/desenho_pro/LICENSE-autocad-mcp-pro`), instalado do PyPI pelo
`uv.lock` de `desenho_pro`; o código dele não está neste repositório.
