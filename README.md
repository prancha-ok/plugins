# Prancha Ok para AutoCAD

Liga o AutoCAD aberto ao [Prancha Ok](https://pranchaok.com.br): o assistente envia a
prancha salva, traz o parecer (Aprovado, Pendente ou Em revisão humana, com a lei de
cada item) e marca no desenho, com nuvens numeradas, o que pede atenção. As marcas ficam
numa camada própria (`PRANCHAOK-PARECER`) que não plota. O assistente **nunca altera** o
que você desenhou.

Versão 0.3.2. Precisa de:

- Windows 10 ou 11;
- AutoCAD 2024 ou mais novo, completo ou LT. Não funciona no GstarCAD, BricsCAD, ZWCAD e
  outros compatíveis: neles, envie o DWG pelo site;
- uma conta no Prancha Ok com o projeto da obra já criado: o assistente pergunta em qual
  projeto a prancha entra, e projeto novo só se cria no site
  ([pranchaok.com.br/app](https://pranchaok.com.br/app), botão "Novo projeto").

Na primeira vez que o assistente usa o Prancha Ok, ele deixa tudo pronto sozinho: copia o
arquivo do Prancha Ok para `%USERPROFILE%\.prancha-ok` e põe essa pasta entre as pastas
confiáveis do AutoCAD. Não mexe nas outras pastas nem no `acaddoc.lsp`.

## Claude Desktop (extensão)

1. Baixe a extensão: [prancha-ok-autocad-0.3.2.mcpb](https://pranchaok.com.br/downloads/prancha-ok-autocad-0.3.2.mcpb)
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
   escolher programa e faça como acima. Não precisa instalar Python: o Claude Desktop
   cuida disso. Se ele avisar que a extensão não é verificada, é esperado: ela vem do site
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

- "Meça a prancha e envie para o Prancha Ok": o assistente mede o terreno, a projeção, os
  afastamentos, os pavimentos, a altura e as vagas, mostra os valores e só envia os que você
  confirmar, que entram já no primeiro parecer. Vale para DWG e DXF (o envio usa o desenho
  salvo; o assistente pede para salvar quando precisa).
- "Marque os erros no desenho" e "me leva até o item 3".
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
(MIT, ver `plugins/autocad/server/LICENSE-autocad-mcp`).
