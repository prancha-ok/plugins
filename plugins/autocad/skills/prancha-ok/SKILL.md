---
name: prancha-ok
description: Confere a prancha aberta no AutoCAD com o Prancha Ok e marca no desenho o que o parecer apontou. Use quando a pessoa pedir para conectar ao Prancha Ok, medir, enviar ou conferir a prancha, ver ou marcar o parecer, ir até um item, responder as dúvidas e perguntas do parecer, mandar uma crítica ao Prancha Ok ou limpar as marcas.
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
- **Valor enviado é declarado pela pessoa.** `medir_prancha` só propõe; envie só o que ela
  confirmar ou corrigir.
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
3. **Medir antes de enviar.** Chame `medir_prancha`. Mostre a proposta numa lista curta: cada
   valor, a unidade e o "como" (ex.: "Área do terreno: 360,00 m², contorno do lote"). Diga
   também o que não deu para medir (`naoMedido`) e, se houver, onde o quadro diverge do
   desenho (`divergencias`: a pessoa escolhe um dos dois). Pergunte: "Estão certos? Corrija o
   que precisar." Se vier aviso de unidade, pergunte a unidade do desenho e meça de novo.
4. **Enviar com as medidas confirmadas.** Chame `enviar_prancha` com
   `respostas={campo: valor}` só com os valores que a pessoa confirmou ou corrigiu (número,
   sem unidade). Eles entram já no primeiro parecer. O envio usa o arquivo salvo, DWG ou DXF;
   se há alteração não salva, pergunte se pode salvar e, com o sim, use `salvar=true`.
5. **Ver o parecer.** Diga a situação e, em poucas linhas, o que está em desacordo, as dúvidas
   e as perguntas. Se ainda estiver processando, chame `ver_parecer` com `aguardar=true`.
   Para a lista inteira, `ver_parecer` com `detalhe=true`. O que o responsável já respondeu no
   site vem em `responsavel` (quanto falta para fechar, os desacordos que ele contestou): é dele,
   nunca diga que o Prancha Ok conferiu.
6. **Marcar no desenho.** Chame `marcar_parecer`. Ele põe uma nuvem numerada em cada item que
   tem lugar na prancha (vermelho: em desacordo; laranja: dúvida; magenta: pergunta; azul:
   conferir à mão) e um quadro-resumo ao lado, com quanto falta para fechar. O que o responsável
   resolveu no site não ganha nuvem. Diga quantos itens ficaram marcados.
7. **Ir até o item.** Quando a pessoa perguntar de um item ("me leva no 3"), chame
   `ir_para_item` com o número que o parecer e as nuvens mostram.
8. **Responder as dúvidas e as perguntas.** Dúvida é informação que a prancha não deu;
   pergunta é o que só a pessoa sabe (há terraplenagem? corte de árvore?). Pergunte a ela.
   Para medir outra coisa no desenho, use `ler_desenho` (cotas e polilinhas), proponha o
   valor e peça confirmação. Grave com `responder_itens`: números em metros ou m², sem
   unidade; opções como "sim", "não" ou "não se aplica". Ele gera um parecer novo; mostre o
   que mudou e marque de novo (passo 6).
9. **Depois que o arquiteto corrigir**, volte ao passo 3 (meça de novo: o desenho mudou).

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

Quando a pessoa pedir, ou antes de entregar a prancha, chame `limpar_marcas`: apaga as nuvens
e o quadro-resumo da camada PRANCHAOK-PARECER e não mexe em mais nada.

## Quando algo não funciona

Chame `diagnosticar` e explique o que ele mostrou. O caso mais comum é o AutoCAD fechado,
minimizado ou com uma caixa de diálogo aberta. No GstarCAD, BricsCAD, ZWCAD e outros
compatíveis o conector não funciona: a pessoa envia o desenho pelo site.
