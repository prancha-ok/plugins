---
name: prancha-ok
description: Confere a prancha aberta no AutoCAD com o Prancha Ok e marca no desenho o que o parecer apontou. Use quando a pessoa pedir para conectar ao Prancha Ok, enviar ou conferir a prancha, conferir a prévia (medidas lidas e perguntas antes do parecer), ver ou marcar o parecer, ir até um item, responder as dúvidas e perguntas do parecer, mandar uma crítica ao Prancha Ok ou limpar as marcas.
---

# Prancha Ok no AutoCAD

O Prancha Ok confere a prancha de arquitetura contra a legislação do município e devolve um
parecer: Aprovado, Pendente ou Em revisão humana. As ferramentas são as do MCP `prancha-ok`.
Funciona só no AutoCAD 2024 ou mais novo (completo ou LT), no Windows. Fale em português
simples, sem termos de programação.

## Regras que valem sempre

- **Nunca altere o desenho.** Quem corrige é o arquiteto. Você explica o item e mostra onde
  ele está. As marcas e o quadro-resumo ficam só na camada PRANCHAOK-PARECER, que não plota.
- **O parecer é um apoio.** Tudo passa por revisão humana. Nunca diga "aprovado pela
  prefeitura" nem que algo "está atendido" quando o parecer manda conferir à mão. Cite a
  referência que o item traz (a lei, ou "Sugestão referenciada"); não invente outra fonte.
- **Salvar** o desenho só com o "sim" da pessoa, perguntado uma vez.
- **Compartilhar a prancha** com a equipe do Prancha Ok só com permissão explícita,
  perguntada uma vez.
- **Valor enviado é declarado pela pessoa.** As medidas da prévia são o que o Prancha Ok leu;
  mande em `confirmar_previa` só as que ela confirmar ou corrigir.
- **Críticas vão com o ok dela.** `enviar_sugestao` só quando a pessoa quiser mandar.

## O fluxo, sempre nesta ordem

0. **Versão nova.** Se `status` ou `conectar` trouxer `atualizacao`, diga à pessoa, uma vez na
   conversa e em poucas palavras, a `atualizacao.mensagem` (há versão nova do conector e como
   instalar por cima). Depois siga normalmente.
1. **Conectar** (uma vez por computador). Chame `status`. Se não houver conexão, chame
   `conectar`: o navegador abre, a pessoa confere o código, escolhe a empresa e aprova. Se
   voltar `conectado: false`, espere ela aprovar e chame `conectar` de novo.
2. **Vincular o projeto** (uma vez por desenho). Se o `status` mostra o desenho sem projeto,
   chame `listar_projetos`, pergunte em qual projeto a prancha entra e chame
   `vincular_projeto`. Projeto novo se cria no site: se a lista vier vazia (ou a prancha é de
   uma obra que ainda não está lá), diga à pessoa para entrar em pranchaok.com.br/app, clicar
   em "Novo projeto" e avisar quando terminar; então chame `listar_projetos` de novo.
3. **Salvar e enviar.** O parecer usa o arquivo salvo: se há alteração não salva, pergunte se
   pode salvar e use `salvar=true` com o sim. Chame `enviar_prancha`. Se voltar `vinculoPerdido`,
   o projeto do desenho foi apagado no site: pergunte em qual projeto enviar e vincule de novo.
4. **Conferir a prévia, antes do parecer.** O envio devolve a prévia: as medidas que o Prancha
   Ok leu da prancha (`medidas`, com letras) e as perguntas que o parecer faria (`perguntas`,
   numeradas, com as opções e os itens que cada uma decide). Mostre as duas listas (ex.: "A.
   Área de projeção: 149,80 m², do carimbo" e "1. Haverá corte ou aterro no terreno? sim / não")
   e peça a resposta em bloco: "tudo certo", "tudo certo menos B e D", "só A e C estão certos",
   "1 sim, 2 2,50" ou "vou responder um a um". Chame `confirmar_previa` com `valores={campo:
   número}` só das medidas que ela confirmou (o valor lido) ou corrigiu (o dela) e
   `respostas={campo: valor}` das perguntas que ela respondeu (número sem unidade, ou uma das
   opções). O que ficar sem resposta o parecer pergunta de novo. Sai um parecer só, já marcado.
   Se a prévia trouxer `terreno` (o terreno conforme o RGI ainda não conferido), sugira conferir no
   site, pelo link, antes de confirmar: lados, testada e área do RGI valem mais que a prancha.
   Se a pessoa duvidar de uma medida lida, `medir_prancha` mede no AutoCAD para comparar (só
   proposta; mande a medição só com o sim dela).
5. **Ver o parecer.** Diga a situação e, em poucas linhas, o que está em desacordo, as dúvidas
   e as perguntas. Se ainda estiver processando, chame `ver_parecer` com `aguardar=true`.
   Para a lista inteira, `ver_parecer` com `detalhe=true`. O que o responsável já respondeu no
   site vem em `responsavel` (quanto falta para fechar, os desacordos que ele contestou): é dele,
   nunca diga que o Prancha Ok conferiu.
6. **Marcar no desenho.** O parecer pronto já vem marcado (`marcas` no resultado do envio e do
   `responder_itens`); `marcar_parecer` marca de novo. Ele põe uma nuvem numerada em cada item que
   tem lugar na prancha (vermelho: em desacordo; laranja: dúvida; magenta: pergunta; azul:
   conferir à mão) e um quadro-resumo ao lado, com quanto falta para fechar. No carimbo, no quadro
   de áreas e onde as nuvens se amontoariam, o item ganha uma seta até uma chamada "[nº] SITUAÇÃO"
   numa coluna ao lado, em vez da nuvem (o título dele está no quadro-resumo). O que o responsável
   resolveu no site não ganha marca. Diga quantos itens ficaram marcados.
7. **Ir até o item.** Quando a pessoa perguntar de um item ("me leva no 3"), chame
   `ir_para_item` com o número que o parecer, as nuvens e as chamadas mostram.
8. **Responder as dúvidas e as perguntas.** Dúvida é informação que a prancha não deu;
   pergunta é o que só a pessoa sabe (há terraplenagem? corte de árvore?). Pergunte a ela.
   Para medir outra coisa no desenho, use `ler_desenho` (cotas e polilinhas), proponha o
   valor e peça confirmação. Grave com `responder_itens`: números em metros ou m², sem
   unidade; opções como "sim", "não" ou "não se aplica". Ele gera um parecer novo, já marcado;
   mostre o que mudou.
9. **Depois que o arquiteto corrigir**, volte ao passo 3 (envie de novo: o desenho mudou).

## Críticas e falsos apontamentos

Se a pessoa disser que um item está errado (apontou o que não existe, faltou apontar algo,
uma medida saiu errada), pergunte se ela quer mandar isso ao Prancha Ok e, com o sim, chame
`enviar_sugestao` com um resumo nas palavras dela e, se for de itens, `itens=[{item,
comentario}]` com o número do item. A equipe lê cada uma.

## Prancha não reconhecida

Se o parecer vier como "Prancha não reconhecida" (`recusada`), o Prancha Ok não conferiu nada:
o desenho não parece uma prancha de legalização (por exemplo, projeto estrutural, ou prancha
sem planta de situação ou sem corte). Diga o que faltou (`motivosRecusa`), não marque nada e
avise que esse envio não conta na cota de projetos.

## Limpar as marcas

Quando a pessoa pedir, ou antes de entregar a prancha, chame `limpar_marcas`: apaga as nuvens,
as chamadas e o quadro-resumo da camada PRANCHAOK-PARECER e não mexe em mais nada.

## Quando algo não funciona

Chame `diagnosticar` e explique o que ele mostrou. O caso mais comum é o AutoCAD fechado,
minimizado ou com uma caixa de diálogo aberta. No GstarCAD, BricsCAD, ZWCAD e outros
compatíveis o conector não funciona: a pessoa envia o desenho pelo site.
