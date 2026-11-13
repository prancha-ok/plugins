;;; prancha_ok.lsp - ponte entre o MCP do Prancha Ok e o AutoCAD.
;;;
;;; AutoCAD 2024 ou mais novo, completo ou LT (o LT só tem AutoLISP a partir
;;; do 2024; nada aqui usa ActiveX/vla, que o LT não tem).
;;;
;;; Protocolo (a ideia vem do puran-water/autocad-mcp, MIT):
;;;   1. O MCP grava %USERPROFILE%\.prancha-ok\ipc\pedido-<id>.lsp com UM dado
;;;      AutoLISP por linha: o comando ("quadro") na 1ª e cada argumento numa
;;;      linha (pedido.py). Cada linha é lida com `read`, que não avalia nada: só
;;;      os comandos de `pok-executar` rodam. Nenhuma linha passa de 250
;;;      caracteres: na 0.1.4 o quadro-resumo ia numa string só, de milhares, e
;;;      o AutoCAD 2025 recusava o pedido (PEDIDO_INVALIDO, 30/09/2026). Os
;;;      textos das marcas e do quadro chegam em ASCII, com \U+XXXX no lugar do
;;;      que não é ASCII (o MTEXT mostra o caractere).
;;;   2. O MCP manda à linha de comando (setq *pok-dir* "<pasta ipc>/") e
;;;      (c:pok-mcp): a pasta vem do MCP, que é quem sabe onde gravou.
;;;   3. Este arquivo responde em resposta-<id>.jsonl (grava .tmp e renomeia):
;;;      a 1ª linha é {"ok":...}; a leitura manda uma entidade por linha e
;;;      termina com {"fim":true,...}.
;;;
;;; Marcas (0.1.6, rodada 2): nuvem na cor da situação (vermelho erro, laranja
;;; dúvida, magenta pergunta, azul conferir à mão) em volta de cada handle
;;; (`marcar`) ou de cada região da prancha (`regioes`: a caixa da vista ou,
;;; sem ela, o título da vista, carimbo, quadro de áreas...).
;;;
;;; Chamadas (0.3.4, observações de 02/10/2026, item 2): no carimbo, no quadro de
;;; áreas e onde as nuvens se amontoariam, uma seta do item até um rótulo
;;; "[nº] SITUAÇÃO" numa coluna ao lado. O MCP pergunta onde está cada handle
;;; (`caixas`), decide toda a geometria (chamadas.py) e manda pronta
;;; (`chamadas`): aqui só se confere o formato e se desenha.
;;;
;;; Escala e lugar das marcas (DAV-18, call de 26/10/2026: "o texto ficou GIGANTE",
;;; "melhor os rótulos ficarem do lado de fora do desenho"): `marcar` e `regioes`
;;; desenham só a nuvem; o rótulo de cada item é uma chamada numa coluna fora do
;;; desenho. O `caixas` diz, por folha, o texto comum (mediana das alturas) e a
;;; extensão do desenho; o quadro-resumo usa o texto comum do modelo.
;;;
;;; Desenho (0.6.0, decisão do David D5=c: "o MCP agora desenha"): `desenhar` recebe
;;; entidades como DADOS (polilinha, linha, arco, texto, cota; uma por linha do pedido, lidas
;;; com `read`) e cria cada uma com entmake, só em camadas PRANCHAOK-* (nunca a das
;;; marcas), tudo num UNDO Begin/End: um desfazer volta tudo.
;;;
;;; Unidade (0.7.0, contrato C1): os pontos chegam já na unidade do desenho (o MCP
;;; escala e põe a origem, desenho.py); o item ("unidade" k), o 1º de cada pedido, diz
;;; quantas unidades do desenho valem um metro (m 1, cm 100, mm 1000), e o que aqui é
;;; escrito em metros (o estilo da cota, o tracejado, os deslocamentos da cota em linhas)
;;; vai vezes k. A cota "viva" mostra a própria medida, em metros com duas casas e
;;; vírgula, por cima do estilo da pessoa (xdata DSTYLE da entidade: DIMLFAC 1/k...); o
;;; tracejado acerta pela escala da entidade (48), sem mexer no LTSCALE. Só no desenho
;;; VAZIO o $INSUNITS pode virar 4 (mm): configurar um desenho novo.
;;;
;;; Escreve no desenho só na camada PRANCHAOK-PARECER (marcas do parecer, que
;;; não plotam e que o motor ignora), nas camadas PRANCHAOK-* do `desenhar` (quando a
;;; pessoa pede) e no dicionário PRANCHAOK (vínculo com o projeto). Nunca apaga nem
;;; altera o que o arquiteto desenhou.

(setq *pok-versao* "0.7.2")
(setq *pok-camada* "PRANCHAOK-PARECER")
(setq *pok-codificacao* nil)

;; ---------------------------------------------------------------- arquivos

(defun pok-dir ( / base)
  (if *pok-dir*
    *pok-dir*
    (progn
      (setq base (strcat (getenv "USERPROFILE") "\\.prancha-ok"))
      (vl-mkdir base)
      (vl-mkdir (strcat base "\\ipc"))
      (strcat base "\\ipc\\")
    )
  )
)

;; Abre em UTF-8 quando o AutoCAD aceita a codificação (2021+); senão, ANSI.
(defun pok-abrir (caminho modo / f)
  (setq f (vl-catch-all-apply 'open (list caminho modo "utf8")))
  (if (or (vl-catch-all-error-p f) (null f))
    (progn (setq *pok-codificacao* "ansi") (open caminho modo))
    (progn (setq *pok-codificacao* "utf8") f)
  )
)

;; O pedido: um dado por linha, cada um lido com `read`. Devolve a lista dos dados
;; ("comando" arg1 arg2...) ou (ERRO n), com n a 1ª linha que o `read` não aceitou.
(defun pok-ler-pedido (caminho / f linha n dado dados ruim)
  (setq n 0)
  (if (setq f (pok-abrir caminho "r"))
    (progn
      (while (and (not ruim) (setq linha (read-line f)))
        (setq n (1+ n))
        (if (/= (vl-string-trim " \t\r" linha) "")
          (progn
            (setq dado (vl-catch-all-apply 'read (list linha)))
            (if (vl-catch-all-error-p dado)
              (setq ruim n)
              (setq dados (cons dado dados))
            )
          )
        )
      )
      (close f)
    )
  )
  (if ruim (list 'ERRO ruim) (reverse dados))
)

;; Texto que chega em pedaços (cada um numa linha do pedido): junta tudo.
(defun pok-juntar (pedacos)
  (apply 'strcat (mapcar '(lambda (x) (if (= (type x) 'STR) x "")) pedacos))
)

;; ---------------------------------------------------------------- JSON

(defun pok-hex2 (n / d)
  (setq d "0123456789ABCDEF")
  (strcat (substr d (1+ (/ n 16)) 1) (substr d (1+ (rem n 16)) 1))
)

(defun pok-js (s / partes)
  (if (null s)
    "null"
    (progn
      (setq partes nil)
      (foreach c (vl-string->list s)
        (setq partes
          (cons
            (cond
              ((= c 34) "\\\"")
              ((= c 92) "\\\\")
              ((< c 32) (strcat "\\u00" (pok-hex2 c)))
              (t (chr c))
            )
            partes
          )
        )
      )
      (strcat "\"" (apply 'strcat (reverse partes)) "\"")
    )
  )
)

;; rtos obedece ao DIMZIN do desenho, que pode tirar o zero à esquerda
;; (".5", inválido em JSON). Mudar o DIMZIN marcaria o desenho como alterado.
(defun pok-jn (n / s)
  (if (null n)
    "null"
    (progn
      (setq s (rtos n 2 6))
      (cond
        ((= s "") "0")
        ((= (substr s 1 1) ".") (strcat "0" s))
        ((and (> (strlen s) 1) (= (substr s 1 2) "-.")) (strcat "-0" (substr s 2)))
        (t s)
      )
    )
  )
)

(defun pok-jp (p) (strcat "[" (pok-jn (car p)) "," (pok-jn (cadr p)) "]"))

(defun pok-jlista (itens / s)
  (setq s "")
  (foreach i itens (setq s (if (= s "") i (strcat s "," i))))
  (strcat "[" s "]")
)

(defun pok-jbool (b) (if b "true" "false"))

;; ---------------------------------------------------------------- geometria

(defun pok-grau (r) (* r (/ 180.0 pi)))

(defun pok-girar (x y r)
  (list (- (* x (cos r)) (* y (sin r))) (+ (* x (sin r)) (* y (cos r))))
)

(defun pok-pontos-de (ed codigos / pts)
  (foreach par ed
    (if (member (car par) codigos) (setq pts (cons (list (cadr par) (caddr par)) pts)))
  )
  (reverse pts)
)

;; Cantos de um retângulo local (x0 y0 x1 y1), girado por r e levado a p.
(defun pok-cantos (p x0 y0 x1 y1 r)
  (mapcar
    '(lambda (c / q) (setq q (pok-girar (car c) (cadr c) r)) (list (+ (car p) (car q)) (+ (cadr p) (cadr q))))
    (list (list x0 y0) (list x1 y0) (list x1 y1) (list x0 y1))
  )
)

(defun pok-limites (pts / xs ys)
  (setq xs (mapcar 'car pts) ys (mapcar 'cadr pts))
  (list (apply 'min xs) (apply 'min ys) (apply 'max xs) (apply 'max ys))
)

(defun pok-rotacao-mtext (ed / d)
  (if (setq d (cdr (assoc 11 ed)))
    (atan (cadr d) (car d))
    (cond ((cdr (assoc 50 ed))) (t 0.0))
  )
)

;; Caixa (xmin ymin xmax ymax) da entidade, aproximada; nil se não dá para saber.
(defun pok-caixa (ed / tipo p tb r w h anexo col lin x0 y0 pts)
  (setq tipo (cdr (assoc 0 ed)))
  (cond
    ((member tipo '("TEXT" "ATTRIB" "ATTDEF"))
     (setq p (cdr (assoc 10 ed)) tb (textbox ed) r (cond ((cdr (assoc 50 ed))) (t 0.0)))
     (if (and p tb)
       (pok-limites (pok-cantos p (car (car tb)) (cadr (car tb)) (car (cadr tb)) (cadr (cadr tb)) r))
     )
    )
    ((= tipo "MTEXT")
     (setq p (cdr (assoc 10 ed))
           w (cond ((cdr (assoc 42 ed))) (t 0.0))
           h (cond ((cdr (assoc 43 ed))) ((cdr (assoc 40 ed))) (t 0.0))
           anexo (cond ((cdr (assoc 71 ed))) (t 1))
           col (rem (1- anexo) 3)
           lin (/ (1- anexo) 3)
           r (pok-rotacao-mtext ed)
           x0 (- (* col (/ w 2.0)))
           y0 (cond ((= lin 0) (- h)) ((= lin 1) (- (/ h 2.0))) (t 0.0)))
     (pok-limites (pok-cantos p x0 y0 (+ x0 w) (+ y0 h) r))
    )
    (t
     (setq pts (pok-pontos-de ed '(10 11 13 14)))
     (if pts (pok-limites pts))
    )
  )
)

;; ---------------------------------------------------------------- onde está

(defun pok-nome-dono (ed / dono)
  (if (setq dono (cdr (assoc 330 ed))) (entget dono))
)

;; Pelo código 67 (1 = paper space) e o layout (410): quando o dono não diz.
;; Na prancha real 01, 274 entidades tinham dono que não é INSERT nem BLOCK_RECORD.
(defun pok-espaco-pelo-67 (ed)
  (if (= 1 (cdr (assoc 67 ed)))
    (list "papel" (cdr (assoc 410 ed)))
    (list "modelo" "Model")
  )
)

;; ("modelo"|"papel"|"bloco" layout-ou-bloco) de uma entidade. O ATTRIB fica
;; onde está o INSERT dele.
(defun pok-espaco (ed / dono nome)
  (setq dono (pok-nome-dono ed))
  (cond
    ((null dono) (pok-espaco-pelo-67 ed))
    ((= (cdr (assoc 0 dono)) "INSERT") (pok-espaco dono))
    ((= (cdr (assoc 0 dono)) "BLOCK_RECORD")
     (setq nome (strcase (cdr (assoc 2 dono))))
     (cond
       ((wcmatch nome "`*MODEL_SPACE") (list "modelo" "Model"))
       ((wcmatch nome "`*PAPER_SPACE*") (list "papel" (cdr (assoc 410 ed))))
       (t (list "bloco" (cdr (assoc 2 dono))))
     )
    )
    (t (pok-espaco-pelo-67 ed))
  )
)

;; ---------------------------------------------------------------- leitura

(defun pok-texto-mtext (ed / partes)
  (setq partes "")
  (foreach par ed (if (= (car par) 3) (setq partes (strcat partes (cdr par)))))
  (strcat partes (cond ((cdr (assoc 1 ed))) (t "")))
)

;; Uma linha JSON por entidade: h handle, t tipo, c camada, e espaço, l layout
;; (ou nome do bloco), x texto, p pontos, a altura do texto, r rotação (graus),
;; m medida da cota, f fechada, g tag do atributo, b bloco inserido, k cor.
(defun pok-linha-entidade (ed espaco / tipo campos p)
  (setq tipo (cdr (assoc 0 ed)))
  (setq campos
    (list
      (strcat "\"h\":" (pok-js (cdr (assoc 5 ed))))
      (strcat "\"t\":" (pok-js tipo))
      (strcat "\"c\":" (pok-js (cdr (assoc 8 ed))))
      (strcat "\"e\":" (pok-js (car espaco)))
      (strcat "\"l\":" (pok-js (cadr espaco)))
    )
  )
  (if (cdr (assoc 62 ed)) (setq campos (append campos (list (strcat "\"k\":" (itoa (cdr (assoc 62 ed))))))))
  (cond
    ((member tipo '("TEXT" "ATTRIB" "ATTDEF"))
     (setq campos
       (append campos
         (list
           (strcat "\"x\":" (pok-js (cdr (assoc 1 ed))))
           (strcat "\"p\":[" (pok-jp (cdr (assoc 10 ed))) "]")
           (strcat "\"a\":" (pok-jn (cdr (assoc 40 ed))))
           (strcat "\"r\":" (pok-jn (pok-grau (cond ((cdr (assoc 50 ed))) (t 0.0)))))
         )
       )
     )
     (if (/= tipo "TEXT") (setq campos (append campos (list (strcat "\"g\":" (pok-js (cdr (assoc 2 ed))))))))
    )
    ((= tipo "MTEXT")
     (setq campos
       (append campos
         (list
           (strcat "\"x\":" (pok-js (pok-texto-mtext ed)))
           (strcat "\"p\":[" (pok-jp (cdr (assoc 10 ed))) "]")
           (strcat "\"a\":" (pok-jn (cdr (assoc 40 ed))))
           (strcat "\"r\":" (pok-jn (pok-grau (pok-rotacao-mtext ed))))
         )
       )
     )
    )
    ((= tipo "DIMENSION")
     (setq campos
       (append campos
         (list
           (strcat "\"m\":" (pok-jn (cdr (assoc 42 ed))))
           (strcat "\"x\":" (pok-js (cdr (assoc 1 ed))))
           (strcat "\"p\":" (pok-jlista (mapcar 'pok-jp (pok-pontos-de ed '(13 14 11)))))
         )
       )
     )
    )
    ((member tipo '("LWPOLYLINE" "LINE"))
     (setq campos
       (append campos
         (list
           (strcat "\"p\":" (pok-jlista (mapcar 'pok-jp (pok-pontos-de ed '(10 11)))))
           (strcat "\"f\":" (pok-jbool (= 1 (logand 1 (cond ((cdr (assoc 70 ed))) (t 0))))))
         )
       )
     )
    )
    ;; 0.3.0: a SPLINE pelos pontos de ajuste (11) ou, sem eles, de controle (10): o lote da
    ;; prancha real 01 tem lados em SPLINE (a leitura vai ao Prancha Ok junto do envio).
    ((= tipo "SPLINE")
     (setq campos
       (append campos
         (list (strcat "\"p\":" (pok-jlista (mapcar 'pok-jp (pok-pontos-de ed (if (assoc 11 ed) '(11) '(10)))))))
       )
     )
    )
    ((= tipo "INSERT")
     (setq campos
       (append campos
         (list
           (strcat "\"b\":" (pok-js (cdr (assoc 2 ed))))
           (strcat "\"p\":[" (pok-jp (cdr (assoc 10 ed))) "]")
         )
       )
     )
    )
    ((= tipo "HATCH")
     (setq campos (append campos (list (strcat "\"b\":" (pok-js (cdr (assoc 2 ed)))))))
    )
  )
  (strcat "{" (substr (apply 'strcat (mapcar '(lambda (c) (strcat "," c)) campos)) 2) "}")
)

(setq *pok-ignorados* '("SEQEND" "VERTEX" "ENDBLK" "BLOCK"))

(defun pok-escrever (saida ed espaco)
  (if (and ed
           (not (member (cdr (assoc 0 ed)) *pok-ignorados*))
           (/= (strcase (cond ((cdr (assoc 8 ed))) (t ""))) *pok-camada*))
    (progn (write-line (pok-linha-entidade ed espaco) saida) T)
  )
)

;; Blocos com nome (definições), sem os anônimos (*D cotas, *U dinâmicos, *X
;; hachuras), sem xref (bit 4) nem os espaços de modelo e papel.
(defun pok-bloco-lido-p (b / nome)
  (setq nome (cdr (assoc 2 b)))
  (and (/= (substr nome 1 1) "*") (= 0 (logand 4 (cond ((cdr (assoc 70 b))) (t 0)))))
)

(defun pok-ler (saida / e ed n b)
  (setq n 0 e (entnext))
  (while e
    (setq ed (entget e))
    (if (pok-escrever saida ed (pok-espaco ed)) (setq n (1+ n)))
    (setq e (entnext e))
  )
  (setq b (tblnext "BLOCK" T))
  (while b
    (if (pok-bloco-lido-p b)
      (progn
        (setq e (cdr (assoc -2 b)))
        (while e
          (setq ed (entget e))
          (if (pok-escrever saida ed (list "bloco" (cdr (assoc 2 b)))) (setq n (1+ n)))
          (setq e (entnext e))
        )
      )
    )
    (setq b (tblnext "BLOCK"))
  )
  n
)

;; ---------------------------------------------------------------- vínculo com o projeto

;; Um XRECORD direto no dicionário de objetos do desenho (PRANCHAOK_VINCULO). Até a
;; 0.1.3 ficava num dicionário PRANCHAOK próprio, que num teste sumiu depois de um
;; Ctrl+S (29/09/2026): a leitura aceita os dois.
(defun pok-vinculo ( / x d)
  (cond
    ((setq x (dictsearch (namedobjdict) "PRANCHAOK_VINCULO"))
     (list (cdr (assoc 1 x)) (cdr (assoc 300 x)) (cdr (assoc 301 x))))
    ((and (setq d (dictsearch (namedobjdict) "PRANCHAOK"))
          (setq x (dictsearch (cdr (assoc -1 d)) "VINCULO")))
     (list (cdr (assoc 1 x)) (cdr (assoc 300 x)) (cdr (assoc 301 x))))
  )
)

(defun pok-gravar-vinculo (projeto nome empresa / antigo)
  (if (setq antigo (dictsearch (namedobjdict) "PRANCHAOK_VINCULO"))
    (progn (dictremove (namedobjdict) "PRANCHAOK_VINCULO") (entdel (cdr (assoc -1 antigo))))
  )
  (dictadd (namedobjdict) "PRANCHAOK_VINCULO"
    (entmakex (list '(0 . "XRECORD") '(100 . "AcDbXrecord") (cons 1 projeto) (cons 300 nome) (cons 301 empresa)))
  )
)

;; ---------------------------------------------------------------- marcas do parecer

(defun pok-garantir-camada ()
  (if (not (tblsearch "LAYER" *pok-camada*))
    ;; Vermelha e sem plotar (290 = 0): a marca nunca sai na prancha impressa.
    (entmake
      (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbLayerTableRecord")
            (cons 2 *pok-camada*) '(70 . 0) '(62 . 1) '(6 . "Continuous") '(290 . 0))
    )
  )
)

;; Cor ACI da marca (62), quando o pedido diz uma (1 a 255); senão a da camada.
(defun pok-cor (cor)
  (if (and (= (type cor) 'INT) (> cor 0) (< cor 256)) (list (cons 62 cor)))
)

;; Pontos de uma nuvem de revisão em volta da caixa, no sentido anti-horário,
;; com arcos para fora (bulge negativo).
(defun pok-nuvem (caixa espaco cor / x0 y0 x1 y1 w h arco nx ny i pts dados)
  (setq x0 (nth 0 caixa) y0 (nth 1 caixa) x1 (nth 2 caixa) y1 (nth 3 caixa)
        w (- x1 x0) h (- y1 y0)
        arco (/ (max w h) 8.0)
        nx (max 2 (fix (/ w arco)))
        ny (max 2 (fix (/ h arco))))
  (setq i 0) (repeat nx (setq pts (cons (list (+ x0 (* w (/ i (float nx)))) y0) pts) i (1+ i)))
  (setq i 0) (repeat ny (setq pts (cons (list x1 (+ y0 (* h (/ i (float ny))))) pts) i (1+ i)))
  (setq i 0) (repeat nx (setq pts (cons (list (- x1 (* w (/ i (float nx)))) y1) pts) i (1+ i)))
  (setq i 0) (repeat ny (setq pts (cons (list x0 (- y1 (* h (/ i (float ny))))) pts) i (1+ i)))
  (setq pts (reverse pts))
  (foreach p pts (setq dados (append dados (list (cons 10 p) '(42 . -0.5)))))
  (entmakex
    (append
      (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 *pok-camada*))
      (pok-cor cor)
      (if (= (car espaco) "papel") (list '(67 . 1) (cons 410 (cadr espaco))))
      (list '(100 . "AcDbPolyline") (cons 90 (length pts)) '(70 . 1))
      dados
    )
  )
)

;; Caixa com folga, para a nuvem não encostar no texto marcado.
(defun pok-caixa-folgada (caixa ed / w h folga)
  (setq w (- (nth 2 caixa) (nth 0 caixa)) h (- (nth 3 caixa) (nth 1 caixa)))
  (setq folga (max (* 0.25 (max w h)) (* 0.5 (cond ((cdr (assoc 40 ed))) (t 0.0))) 1e-3))
  (list (- (nth 0 caixa) folga) (- (nth 1 caixa) folga) (+ (nth 2 caixa) folga) (+ (nth 3 caixa) folga))
)

;; marcas: lista de (handle cor texto...). Só a nuvem: desde a DAV-18 (call de 26/10/2026, "o texto ficou
;; GIGANTE", "melhor os rótulos ficarem do lado de fora do desenho") o rótulo de cada item é uma chamada numa
;; coluna fora do desenho (`chamadas`, geometria em chamadas.py); o texto que ainda vem no pedido não se desenha
;; (era 0,15 do lado da caixa na polilinha e na cota: 6,75 m de letra no lote de 30 m).
;; Devolve as marcadas e as que não têm lugar.
(defun pok-marcar (saida marcas / e ed espaco caixa feitas sem)
  (pok-garantir-camada)
  (foreach m marcas
    (setq e (handent (car m)) ed (if e (entget e)) espaco (if ed (pok-espaco ed)))
    (if (and ed
             (member (car espaco) '("modelo" "papel"))
             (setq caixa (pok-caixa ed)))
      (progn
        (setq caixa (pok-caixa-folgada caixa ed))
        (pok-nuvem caixa espaco (cadr m))
        (setq feitas (cons (pok-js (car m)) feitas))
      )
      (setq sem (cons (pok-js (car m)) sem))
    )
  )
  (write-line
    (strcat "{\"ok\":true,\"marcadas\":" (pok-jlista (reverse feitas)) ",\"semLugar\":" (pok-jlista (reverse sem)) "}")
    saida
  )
)

(defun pok-limpar (saida / ss i n)
  (setq n 0)
  (if (setq ss (ssget "_X" (list (cons 8 *pok-camada*))))
    (progn
      (setq i 0)
      (repeat (sslength ss) (entdel (ssname ss i)) (setq i (1+ i)))
      (setq n (sslength ss))
    )
  )
  (write-line (strcat "{\"ok\":true,\"apagadas\":" (itoa n) "}") saida)
)

;; Caixa (x0 y0 x1 y1) que veio no pedido, em reais, se tem 4 números e área; senão nil.
(defun pok-caixa-valida (c)
  (if (and (= (type c) 'LIST)
           (= (length c) 4)
           (vl-every '(lambda (n) (member (type n) '(INT REAL))) c)
           (> (nth 2 c) (nth 0 c))
           (> (nth 3 c) (nth 1 c)))
    (mapcar 'float c)
  )
)

;; Caixa com uma folga de f (fração do lado maior) em volta.
(defun pok-folga (caixa f / d)
  (setq d (* f (max (- (nth 2 caixa) (nth 0 caixa)) (- (nth 3 caixa) (nth 1 caixa)))))
  (list (- (nth 0 caixa) d) (- (nth 1 caixa) d) (+ (nth 2 caixa) d) (+ (nth 3 caixa) d))
)

;; Onde fica uma região do pedido: (espaco caixa ed-do-titulo), ou nil. Com o título
;; (handle h) achado, o espaço e o layout são os dele e, sem caixa no pedido, a caixa
;; é a do próprio título. Sem o título, a caixa vale no modelo; no papel, sem o
;; título não se sabe o layout.
(defun pok-lugar-regiao (h caixa espaco / e ed esp cx)
  (setq e (if (and (= (type h) 'STR) (/= h "")) (handent h))
        ed (if e (entget e))
        esp (if ed (pok-espaco ed))
        cx (pok-caixa-valida caixa))
  (if cx (setq cx (pok-folga cx 0.02)))
  (cond
    ((and ed (member (car esp) '("modelo" "papel")))
     (if (and (not cx) (setq cx (pok-caixa ed))) (setq cx (pok-caixa-folgada cx ed)))
     (if cx (list esp cx ed)))
    ((and cx (not ed) (/= espaco "papel")) (list (list "modelo" "Model") cx nil))
  )
)

;; regioes: lista de (handle-do-titulo caixa espaco cor texto...). Só a nuvem, como no `marcar` (DAV-18: o
;; rótulo de cada item da região é uma chamada na coluna fora do desenho; o da região ia na altura do título).
;; Devolve os índices (na ordem do pedido) das que ganharam nuvem e das que não se acharam.
(defun pok-regioes (saida regioes / lugar esp cx i feitas sem)
  (pok-garantir-camada)
  (setq i 0)
  (foreach r regioes
    (setq lugar (if (and (= (type r) 'LIST) (>= (length r) 4)) (pok-lugar-regiao (nth 0 r) (nth 1 r) (nth 2 r))))
    (if lugar
      (progn
        (setq esp (nth 0 lugar) cx (nth 1 lugar))
        (pok-nuvem cx esp (nth 3 r))
        (setq feitas (cons (itoa i) feitas))
      )
      (setq sem (cons (itoa i) sem))
    )
    (setq i (1+ i))
  )
  (write-line
    (strcat "{\"ok\":true,\"marcadas\":" (pok-jlista (reverse feitas)) ",\"semLugar\":" (pok-jlista (reverse sem)) "}")
    saida
  )
)

;; ---------------------------------------------------------------- texto comum e extensão de uma folha (DAV-18)

;; O nome do layout como padrão do wcmatch (o filtro 410 do ssget): os caracteres especiais com a crase na frente.
(defun pok-escapar-wc (s / i c saida)
  (setq i 1 saida "")
  (repeat (strlen s)
    (setq c (substr s i 1) i (1+ i))
    (setq saida (strcat saida (if (member c '("#" "@" "." "*" "?" "~" "[" "]" "`" ",")) (strcat "`" c) c)))
  )
  saida
)

;; Caixa (x0 y0 x1 y1) de uma entidade para a extensão do desenho, sem o textbox (o TEXT vai pela altura e por
;; 0,8 altura por caractere, como chamadas.LARGURA_LETRA). Só os pontos que são lugar: o 10 da HATCH e da
;; POLYLINE é a elevação (0,0) e o 12 da DIMENSION é o ponto do bloco dela; esses tipos e o POINT (lixo de
;; importação longe de tudo) não entram. nil se não dá para saber.
(defun pok-caixa-extensao (ed / tipo p r w h)
  (setq tipo (cdr (assoc 0 ed)))
  (cond
    ((= tipo "TEXT")
     (setq p (cdr (assoc 10 ed))
           h (cond ((cdr (assoc 40 ed))) (t 0.0))
           w (* 0.8 h (strlen (cond ((cdr (assoc 1 ed))) (t ""))))
           r (cond ((cdr (assoc 50 ed))) (t 0.0)))
     (if p (pok-limites (pok-cantos p 0.0 0.0 w h r))))
    ((= tipo "MTEXT") (pok-caixa ed))
    ((member tipo '("CIRCLE" "ARC"))
     (setq p (cdr (assoc 10 ed)) r (cdr (assoc 40 ed)))
     (if (and p (pok-num-p r)) (list (- (car p) r) (- (cadr p) r) (+ (car p) r) (+ (cadr p) r))))
    ((= tipo "ELLIPSE")
     (setq p (cdr (assoc 10 ed)) w (cdr (assoc 11 ed)))
     (if (and p w)
       (progn
         (setq r (distance (list 0.0 0.0) (list (car w) (cadr w))))
         (list (- (car p) r) (- (cadr p) r) (+ (car p) r) (+ (cadr p) r)))))
    ;; A VIEWPORT 1 é a própria folha do papel.
    ((and (= tipo "VIEWPORT") (/= 1 (cdr (assoc 69 ed))))
     (setq p (cdr (assoc 10 ed)) w (cdr (assoc 40 ed)) h (cdr (assoc 41 ed)))
     (if (and p (pok-num-p w) (pok-num-p h))
       (list (- (car p) (/ w 2.0)) (- (cadr p) (/ h 2.0)) (+ (car p) (/ w 2.0)) (+ (cadr p) (/ h 2.0)))))
    ((member tipo '("LINE" "SPLINE" "MLINE")) (pok-limites-ou-nil (pok-pontos-de ed '(10 11))))
    ((member tipo '("LWPOLYLINE" "LEADER" "INSERT")) (pok-limites-ou-nil (pok-pontos-de ed '(10))))
    ((member tipo '("SOLID" "TRACE" "3DFACE" "WIPEOUT")) (pok-limites-ou-nil (pok-pontos-de ed '(10 11 12 13))))
    ((= tipo "DIMENSION") (pok-limites-ou-nil (pok-pontos-de ed '(10 11 13 14))))
  )
)

(defun pok-limites-ou-nil (pts) (if pts (pok-limites pts)))

;; (mínimo quantil-1% quantil-99% máximo) de uma lista de números (o vl-sort-i guarda os repetidos).
(defun pok-quantis (l / ordem n)
  (setq ordem (vl-sort-i l '<) n (length l))
  (mapcar '(lambda (q) (nth (nth (fix (* q (1- n))) ordem) l)) '(0.0 0.01 0.99 1.0))
)

;; A extensão sem o que está longe de tudo: cada lado é o da entidade mais longe, salvo quando ela passa do
;; núcleo (entre os quantis de 1% e 99%) por mais que o tamanho do núcleo (uma linha perdida a quilômetros).
(defun pok-extensao-robusta (x0s y0s x1s y1s / qx0 qy0 qx1 qy1 d)
  (setq qx0 (pok-quantis x0s) qy0 (pok-quantis y0s) qx1 (pok-quantis x1s) qy1 (pok-quantis y1s)
        d (max (- (nth 2 qx1) (nth 1 qx0)) (- (nth 2 qy1) (nth 1 qy0))))
  (list (if (> (- (nth 1 qx0) (nth 0 qx0)) d) (nth 1 qx0) (nth 0 qx0))
        (if (> (- (nth 1 qy0) (nth 0 qy0)) d) (nth 1 qy0) (nth 0 qy0))
        (if (> (- (nth 3 qx1) (nth 2 qx1)) d) (nth 2 qx1) (nth 3 qx1))
        (if (> (- (nth 3 qy1) (nth 2 qy1)) d) (nth 2 qy1) (nth 3 qy1)))
)

;; O texto comum e a extensão de um layout ("Model" = o modelo), fora da camada das marcas: (mediana das alturas
;; dos TEXT e MTEXT, até 2000; quantos textos entraram; extensão robusta ou nil). Acima de 200 mil entidades, uma
;; a cada `passo`. O texto comum é a escala das marcas (DAV-18): o rótulo, a seta e o quadro-resumo na altura de
;; um texto do próprio desenho, no espaço onde vão.
(defun pok-folha (layout / ss n passo i ed tipo h cx alturas nt x0s y0s x1s y1s)
  (setq nt 0)
  (if (setq ss (ssget "_X" (list (cons 410 (pok-escapar-wc layout)) (cons 8 (strcat "~" *pok-camada*)))))
    (progn
      (setq n (sslength ss) passo (1+ (/ n 200000)) i 0)
      (while (< i n)
        (setq ed (entget (ssname ss i)) tipo (cdr (assoc 0 ed)) i (+ i passo))
        (if (and (< nt 2000) (member tipo '("TEXT" "MTEXT")) (pok-num-p (setq h (cdr (assoc 40 ed)))) (> h 0))
          (setq alturas (cons (float h) alturas) nt (1+ nt)))
        (if (setq cx (pok-caixa-extensao ed))
          (setq x0s (cons (float (nth 0 cx)) x0s) y0s (cons (float (nth 1 cx)) y0s)
                x1s (cons (float (nth 2 cx)) x1s) y1s (cons (float (nth 3 cx)) y1s)))
      )
    )
  )
  (list (pok-mediana alturas) nt (if x0s (pok-extensao-robusta x0s y0s x1s y1s)))
)

;; A altura das marcas: o texto comum, entre 1/2000 e 1/60 do lado maior da extensão; sem texto, 1/300 dele
;; (os mesmos números de chamadas.py: PISO_TEXTO, TETO_TEXTO, SEM_TEXTO).
(defun pok-altura-das-marcas (texto lado)
  (if texto (max (/ lado 2000.0) (min texto (/ lado 60.0))) (/ lado 300.0))
)

;; ---------------------------------------------------------------- chamadas (0.3.4)

;; caixas: lista de handles. Responde {"ok":true} e uma linha por handle: o espaço, o layout,
;; a caixa (pok-caixa, sem folga) e a altura do texto (null se não é texto), ou semLugar (o
;; desenho não tem o handle, ou ele está dentro de um bloco, onde a nuvem também não vai). Depois,
;; uma linha por folha (espaço e layout) dos handles achados (DAV-18): {"folha":true, e, l, a: o texto
;; comum, n: quantos textos, ext: a extensão}, de onde chamadas.py tira a altura e a coluna de fora.
(defun pok-caixas (saida handles / e ed esp cx folhas info)
  (write-line "{\"ok\":true}" saida)
  (foreach h handles
    (setq e (if (and (= (type h) 'STR) (/= h "")) (handent h))
          ed (if e (entget e))
          esp (if ed (pok-espaco ed))
          cx (if (and esp (member (car esp) '("modelo" "papel"))) (pok-caixa ed)))
    (if (and cx (not (member esp folhas))) (setq folhas (append folhas (list esp))))
    (write-line
      (if cx
        (strcat "{\"h\":" (pok-js h) ",\"e\":" (pok-js (car esp)) ",\"l\":" (pok-js (cadr esp))
                ",\"c\":" (pok-jlista (mapcar 'pok-jn cx))
                ",\"a\":" (pok-jn (if (member (cdr (assoc 0 ed)) '("TEXT" "MTEXT" "ATTRIB" "ATTDEF")) (cdr (assoc 40 ed))))
                "}")
        (strcat "{\"h\":" (pok-js (if (= (type h) 'STR) h "")) ",\"semLugar\":true}")
      )
      saida
    )
  )
  (foreach esp folhas
    (setq info (pok-folha (cadr esp)))
    (write-line
      (strcat "{\"folha\":true,\"e\":" (pok-js (car esp)) ",\"l\":" (pok-js (cadr esp))
              ",\"a\":" (pok-jn (nth 0 info)) ",\"n\":" (itoa (nth 1 info))
              ",\"ext\":" (if (nth 2 info) (pok-jlista (mapcar 'pok-jn (nth 2 info))) "null") "}")
      saida
    )
  )
)

;; Ponto (x y) do pedido, em reais; nil se não são dois números.
(defun pok-ponto (p)
  (if (and (= (type p) 'LIST)
           (= (length p) 2)
           (vl-every '(lambda (n) (member (type n) '(INT REAL))) p))
    (mapcar 'float p)
  )
)

;; Onde desenhar a chamada: no espaço e no layout do handle de referência ou, sem ele, no modelo.
(defun pok-espaco-chamada (h espaco / e ed esp)
  (setq e (if (and (= (type h) 'STR) (/= h "")) (handent h))
        ed (if e (entget e))
        esp (if ed (pok-espaco ed)))
  (cond
    ((and esp (member (car esp) '("modelo" "papel"))) esp)
    ((and (not ed) (= espaco "modelo")) (list "modelo" "Model"))
  )
)

;; Seta: polilinha do começo à base da ponta (largura 0) e da base à ponta (largura `largura`
;; na base, 0 na ponta): ponta cheia, sem depender do estilo de cota do desenho (e no LT).
(defun pok-seta (pts largura espaco cor)
  (entmakex
    (append
      (list (cons 0 "LWPOLYLINE") (cons 100 "AcDbEntity") (cons 8 *pok-camada*))
      (pok-cor cor)
      (if (= (car espaco) "papel") (list (cons 67 1) (cons 410 (cadr espaco))))
      (list (cons 100 "AcDbPolyline") (cons 90 3) (cons 70 0)
            (cons 10 (nth 0 pts)) (cons 40 0.0) (cons 41 0.0)
            (cons 10 (nth 1 pts)) (cons 40 largura) (cons 41 0.0)
            (cons 10 (nth 2 pts)) (cons 40 0.0) (cons 41 0.0))
    )
  )
)

;; Rótulo da chamada: MTEXT com o ponto no meio da esquerda (anexo 4), uma linha.
(defun pok-texto-chamada (ponto altura texto espaco cor)
  (entmakex
    (append
      (list (cons 0 "MTEXT") (cons 100 "AcDbEntity") (cons 8 *pok-camada*))
      (pok-cor cor)
      (if (= (car espaco) "papel") (list (cons 67 1) (cons 410 (cadr espaco))))
      (list (cons 100 "AcDbMText") (list 10 (car ponto) (cadr ponto) 0.0)
            (cons 40 altura) (cons 71 4) (cons 1 texto))
    )
  )
)

;; chamadas: lista de (handle-de-referencia espaco cor altura (começo base ponta)
;; largura-da-ponta (x y)-do-rotulo texto...); texto "" é só a seta. Devolve os índices (na ordem do pedido) das
;; desenhadas e das que vieram tortas ou sem lugar.
(defun pok-chamadas (saida chamadas / esp pts rot i feitas sem)
  (pok-garantir-camada)
  (setq i 0)
  (foreach c chamadas
    (setq esp nil pts nil rot nil)
    (if (and (= (type c) 'LIST)
             (>= (length c) 8)
             (member (type (nth 3 c)) '(INT REAL))
             (> (nth 3 c) 0)
             (member (type (nth 5 c)) '(INT REAL))
             (= (type (nth 4 c)) 'LIST)
             (= (length (nth 4 c)) 3)
             (setq pts (mapcar 'pok-ponto (nth 4 c)))
             (not (member nil pts))
             (setq rot (pok-ponto (nth 6 c)))
             (setq esp (pok-espaco-chamada (nth 0 c) (nth 1 c))))
      (progn
        (pok-seta pts (float (nth 5 c)) esp (nth 2 c))
        ;; Texto vazio: só mais uma seta do mesmo rótulo (o item tem outro lugar no grupo).
        (if (/= (pok-juntar (cdddr (cddddr c))) "")
          (pok-texto-chamada rot (float (nth 3 c)) (pok-juntar (cdddr (cddddr c))) esp (nth 2 c)))
        (setq feitas (cons (itoa i) feitas))
      )
      (setq sem (cons (itoa i) sem))
    )
    (setq i (1+ i))
  )
  (write-line
    (strcat "{\"ok\":true,\"marcadas\":" (pok-jlista (reverse feitas)) ",\"semLugar\":" (pok-jlista (reverse sem)) "}")
    saida
  )
)

;; Abre o layout, dá zoom e seleciona: em volta da entidade `handle` ou, com `caixa`, em
;; volta da caixa da região (no layout do título `handle`, ou no modelo sem título).
(defun pok-ir (saida handle caixa espaco / lugar esp cx ed m)
  (setq lugar (pok-lugar-regiao handle caixa espaco))
  (if lugar
    (progn
      (setq esp (nth 0 lugar) cx (nth 1 lugar) ed (nth 2 lugar))
      (if (/= (strcase (getvar "CTAB")) (strcase (cadr esp))) (setvar "CTAB" (cadr esp)))
      (if (and (= (car esp) "papel") (> (getvar "CVPORT") 1)) (command "_.PSPACE"))
      (setq m (max (- (nth 2 cx) (nth 0 cx)) (- (nth 3 cx) (nth 1 cx)) 1e-3))
      ;; Região: a vista inteira e um pouco em volta. Entidade: bastante contexto.
      (setq m (if (pok-caixa-valida caixa) (* 0.1 m) (* 2 m)))
      (command "_.ZOOM" "_W"
               (list (- (nth 0 cx) m) (- (nth 1 cx) m))
               (list (+ (nth 2 cx) m) (+ (nth 3 cx) m)))
      (if ed (sssetfirst nil (ssadd (cdr (assoc -1 ed)))))
      (write-line (strcat "{\"ok\":true,\"layout\":" (pok-js (cadr esp)) "}") saida)
    )
    (write-line (strcat "{\"ok\":false,\"erro\":\"SEM_LUGAR\",\"handle\":" (pok-js handle) "}") saida)
  )
)

;; ---------------------------------------------------------------- quadro-resumo e salvar

;; MTEXT de qualquer tamanho: o texto vai em pedaços de 250 caracteres (código 3) e o
;; último no código 1, como o DXF exige.
(defun pok-mtext-dados (texto / partes)
  (while (> (strlen texto) 250)
    (setq partes (cons (cons 3 (substr texto 1 250)) partes) texto (substr texto 251))
  )
  (append (reverse partes) (list (cons 1 texto)))
)

;; Quadro com os itens do parecer, na camada das marcas, à direita do desenho (model
;; space): o parecer aparece dentro do DWG, inclusive os itens sem lugar no desenho.
;; Não apaga o anterior: o `limpar` (que o MCP chama antes de marcar) tira tudo da camada.
;; DAV-18 (call de 26/10/2026, "a legenda é boa, mas também ficou grande"): a letra é a do texto comum do modelo
;; (pok-altura-das-marcas), não 1/90 da altura do EXTMIN/EXTMAX, que é a do espaço aberto (com um layout aberto,
;; o papel em mm virava metros no modelo) e não encolhe quando se apaga; o quadro fica à direita do desenho e
;; das chamadas já postas (a coluna da direita).
(defun pok-quadro (saida texto / info ext lado altura x y)
  (pok-garantir-camada)
  (setq info (pok-folha "Model")
        ext (cond ((nth 2 info)) (t (list 0.0 0.0 1.0 1.0)))
        lado (max (- (nth 2 ext) (nth 0 ext)) (- (nth 3 ext) (nth 1 ext)) 1e-3)
        altura (pok-altura-das-marcas (nth 0 info) lado))
  (setq x (+ (max (nth 2 ext) (cond ((pok-x-das-marcas)) (t (nth 2 ext)))) (* 4 altura)) y (nth 3 ext))
  (entmakex
    (append
      (list '(0 . "MTEXT") '(100 . "AcDbEntity") (cons 8 *pok-camada*) '(100 . "AcDbMText")
            (list 10 x y 0.0) (cons 40 altura) (cons 41 (* 70 altura)) '(71 . 1))
      (pok-mtext-dados texto)
    )
  )
  (write-line "{\"ok\":true}" saida)
)

;; O x mais à direita das marcas já postas no modelo (nuvens, setas e rótulos), ou nil. O rótulo da chamada
;; (MTEXT sem largura) vale 0,8 altura por caractere, como em chamadas.py.
(defun pok-x-das-marcas ( / ss i ed cx x)
  (if (setq ss (ssget "_X" (list (cons 410 "Model") (cons 8 (pok-escapar-wc *pok-camada*)))))
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ed (entget (ssname ss i)) i (1+ i))
        (if (setq cx (pok-caixa-extensao ed)) (setq x (if x (max x (nth 2 cx)) (nth 2 cx))))
        (if (= (cdr (assoc 0 ed)) "MTEXT")
          (setq x (max x (+ (car (cdr (assoc 10 ed)))
                            (* 0.8 (cdr (assoc 40 ed)) (strlen (pok-texto-mtext ed)))))))
      )
    )
  )
  x
)

;; QSAVE do desenho aberto (só com o consentimento da pessoa: quem pede é o MCP).
(defun pok-salvar (saida)
  (if (= 1 (getvar "DWGTITLED"))
    (progn
      (command "_.QSAVE")
      (write-line (strcat "{\"ok\":true,\"salvo\":" (pok-jbool (= 0 (getvar "DBMOD"))) "}") saida)
    )
    (write-line "{\"ok\":false,\"erro\":\"SEM_NOME\"}" saida)
  )
)

;; ---------------------------------------------------------------- desenhar (0.6.0)

;; O pedido do `desenhar` (desenho.py): um item por linha, sempre dados.
;;   ("se-vazio" camada)                      1º item, opcional: com algo nessa camada, não desenha nada
;;   ("unidade" k)                            unidades do desenho por metro (0.7.0); sem ele, 1 (metros)
;;   ("insunits-se-vazio" 4)                  grava o $INSUNITS (4 mm, 5 cm, 6 m) só se o modelo não tem nada
;;                                            fora das camadas PRANCHAOK-*
;;   ("camada" nome cor tipo-de-linha [imprime [espessura]])  cria a camada se ela não existe (a que existe fica
;;                                            como está); imprime 0: não plota (o padrão é plotar); espessura:
;;                                            a de linha em centésimos de mm (código 370: 50 = 0,50 mm)
;;   ("polilinha" camada fechada x y x y ...) fechada: 1 ou 0
;;   ("linha" camada x1 y1 x2 y2 tipo)        tipo: "" (o da camada), "DASHED", "CONTINUOUS"...
;;   ("arco" camada xc yc raio inicio fim)    ângulos em graus, anti-horário de inicio a fim (a folha da porta)
;;   ("texto" camada x y altura giro alinhamento texto...)  giro em graus; "esquerda" ou "centro"
;;   ("cota" camada x1 y1 x2 y2 xl yl texto...)  (xl yl): a ponta da linha de cota do lado de (x2 y2)
;;   ("cota-viva" camada x1 y1 x2 y2 xl yl texto...)  a mesma, mostrando a medida do AutoCAD (o texto só vale
;;                                            na cota em linhas, quando a DIMENSION não entra)
;;   ("hachura" camada cor n x y ... n x y ...)  hachura sólida (SOLID): cada contorno, o número de vértices e
;;                                            os vértices; cor ACI, 256 = a da camada
;;   ("zoom" x0 y0 x1 y1)
;;   ("+" ...)                                continua o item de cima (mais pontos, mais texto): a
;;                                            linha do pedido não passa de 250 caracteres
;; Só em camada PRANCHAOK-* que não seja a das marcas; o item torto ou de outra camada é contado e ignorado.

(defun pok-num-p (x) (member (type x) '(INT REAL)))

(defun pok-nums-p (l) (and l (vl-every 'pok-num-p l)))

(defun pok-camada-desenho-p (nome)
  (and (= (type nome) 'STR)
       (wcmatch (strcase nome) "PRANCHAOK-*")
       (/= (strcase nome) *pok-camada*))
)

(defun pok-pt (x y) (list (float x) (float y) 0.0))
(defun pok-mais (p q) (mapcar '+ p q))
(defun pok-menos (p q) (mapcar '- p q))
(defun pok-vezes (p k) (mapcar '(lambda (c) (* c k)) p))

;; Ângulo (radianos) para o texto nunca ficar de cabeça para baixo: de 90° a 270° gira meia volta.
(defun pok-legivel (r / a)
  (setq a (rem (+ (rem r (* 2 pi)) (* 2 pi)) (* 2 pi)))
  (if (and (> a (/ pi 2)) (<= a (* 1.5 pi))) (- a pi) a)
)

;; Unidades do desenho por metro no pedido que está sendo desenhado (o `por-metro` do pok-desenhar, escopo
;; dinâmico), ou 1.
(defun pok-k ()
  (if (and (pok-num-p por-metro) (> por-metro 0)) (float por-metro) 1.0)
)

;; O tipo de linha pronto para usar, ou nil (fica o da camada). CONTINUOUS sempre existe; DASHED, se o desenho
;; não tem, é criado com o padrão do DXF do site (lib/dxfDoTerreno.ts: traço 1,0 e espaço 0,5, em metros, vezes
;; k), sem depender de achar o acad.lin (o LT tem outro arquivo); o DASHED que o desenho já tem fica como está.
(defun pok-tipo-linha (nome / n)
  (if (= (type nome) 'STR) (setq n (strcase nome)))
  (cond
    ((or (null n) (= n "")) nil)
    ((= n "CONTINUOUS") "Continuous")
    ((tblsearch "LTYPE" n) nome)
    ((= n "DASHED")
     (entmake (list (cons 0 "LTYPE") (cons 100 "AcDbSymbolTableRecord") (cons 100 "AcDbLinetypeTableRecord")
                    (cons 2 "DASHED") (cons 70 0) (cons 3 "Dashed __ __ __") (cons 72 65) (cons 73 2)
                    (cons 40 (* 1.5 (pok-k))) (cons 49 (* 1.0 (pok-k))) (cons 74 0)
                    (cons 49 (* -0.5 (pok-k))) (cons 74 0)))
     (if (tblsearch "LTYPE" "DASHED") "DASHED"))
  )
)

;; A escala da entidade (48) que dá ao DASHED um período de 1,5 m no desenho, qualquer que seja o padrão dele (o
;; nosso, 1,5 m; o do acadiso.lin, 19,05) e o LTSCALE da pessoa, que fica como está: 1,5 k / (padrão x LTSCALE).
;; nil sem DASHED no desenho ou com número que não serve.
(defun pok-escala-tracejado ( / tl padrao lts)
  (setq tl (tblsearch "LTYPE" "DASHED")
        padrao (if tl (cdr (assoc 40 tl)))
        lts (getvar "LTSCALE"))
  (if (and (pok-num-p padrao) (> padrao 0) (pok-num-p lts) (> lts 0))
    (/ (* 1.5 (pok-k)) (* padrao lts))
  )
)

;; O (48 . escala) da entidade que sai tracejada: o tipo dela é DASHED ou, sem tipo (o da camada), a camada é
;; DASHED. Senão nil.
(defun pok-48 (camada tl / lay celt)
  (if (and (or (null tl) (= tl "")) (setq lay (tblsearch "LAYER" camada))) (setq tl (cdr (assoc 6 lay))))
  (if (and (= (type tl) 'STR) (= (strcase tl) "DASHED") (setq celt (pok-escala-tracejado)))
    (list (cons 48 celt))
  )
)

;; As espessuras de linha que a camada aceita (código 370, centésimos de mm; DXF Reference, LAYER).
(setq *pok-espessuras* '(0 5 9 13 15 18 20 25 30 35 40 50 53 60 70 80 90 100 106 120 140 158 200 211))

;; Cria a camada que falta (cor ACI, tipo de linha, com imprime 0 sem plotar: 290 = 0, e a espessura de linha:
;; 370); T se criou. A que já existe não muda.
(defun pok-camada-desenho (nome cor tipo imprime espessura / tl)
  (if (and (pok-camada-desenho-p nome) (not (tblsearch "LAYER" nome)))
    (progn
      (setq tl (cond ((pok-tipo-linha tipo)) (t "Continuous")))
      (entmake (append
                 (list (cons 0 "LAYER") (cons 100 "AcDbSymbolTableRecord") (cons 100 "AcDbLayerTableRecord")
                       (cons 2 nome) (cons 70 0)
                       (cons 62 (if (and (= (type cor) 'INT) (> cor 0) (< cor 256)) cor 7))
                       (cons 6 tl)
                       (cons 290 (if (= imprime 0) 0 1)))
                 (if (and (= (type espessura) 'INT) (member espessura *pok-espessuras*)) (list (cons 370 espessura)))))
      (if (tblsearch "LAYER" nome) T)
    )
  )
)

;; (x y x y ...) -> ((x y) (x y) ...)
(defun pok-pares (nums / pts)
  (while (and nums (cdr nums))
    (setq pts (cons (list (float (car nums)) (float (cadr nums))) pts) nums (cddr nums)))
  (reverse pts)
)

;; a: (camada fechada x y x y ...)
(defun pok-d-polilinha (a / pts)
  (if (and (member (nth 1 a) '(0 1))
           (pok-nums-p (cddr a))
           (= 0 (rem (length (cddr a)) 2))
           (>= (length (setq pts (pok-pares (cddr a)))) 2))
    (entmakex
      (append
        (list (cons 0 "LWPOLYLINE") (cons 100 "AcDbEntity") (cons 8 (car a)))
        (pok-48 (car a) nil)
        (list (cons 100 "AcDbPolyline") (cons 90 (length pts)) (cons 70 (nth 1 a)))
        (mapcar '(lambda (p) (cons 10 p)) pts)
      )
    )
  )
)

;; a: (camada x1 y1 x2 y2 tipo)
(defun pok-d-linha (a / tl)
  (if (pok-nums-p (list (nth 1 a) (nth 2 a) (nth 3 a) (nth 4 a)))
    (progn
      (setq tl (pok-tipo-linha (nth 5 a)))
      (entmakex
        (append
          (list (cons 0 "LINE") (cons 100 "AcDbEntity") (cons 8 (car a)))
          (if tl (list (cons 6 tl)))
          (pok-48 (car a) tl)
          (list (cons 100 "AcDbLine") (cons 10 (pok-pt (nth 1 a) (nth 2 a))) (cons 11 (pok-pt (nth 3 a) (nth 4 a))))
        )
      )
    )
  )
)

;; a: (camada xc yc raio inicio fim). ARC: 50 e 51 em radianos, o AutoCAD vai de 50 a 51 no sentido anti-horário.
(defun pok-d-arco (a)
  (if (and (pok-nums-p (list (nth 1 a) (nth 2 a) (nth 3 a) (nth 4 a) (nth 5 a)))
           (= (length a) 6)
           (> (nth 3 a) 0))
    (entmakex
      (append
        (list (cons 0 "ARC") (cons 100 "AcDbEntity") (cons 8 (car a)))
        (pok-48 (car a) nil)
        (list (cons 100 "AcDbCircle") (cons 10 (pok-pt (nth 1 a) (nth 2 a))) (cons 40 (float (nth 3 a)))
              (cons 100 "AcDbArc") (cons 50 (* (nth 4 a) (/ pi 180.0))) (cons 51 (* (nth 5 a) (/ pi 180.0))))
      )
    )
  )
)

;; TEXT de uma linha. "centro": o ponto é o meio do texto (72 = 1 e 73 = 2, com o 11); "esquerda": o canto de baixo.
(defun pok-texto-desenho (camada p altura txt r alinhamento)
  (entmakex
    (append
      (list (cons 0 "TEXT") (cons 100 "AcDbEntity") (cons 8 camada) (cons 100 "AcDbText")
            (cons 10 p) (cons 40 (float altura)) (cons 1 txt) (cons 50 r))
      (if (= alinhamento "centro") (list (cons 72 1) (cons 11 p) (cons 73 2)) (list (cons 72 0) (cons 73 0)))
    )
  )
)

;; a: (camada x y altura giro alinhamento texto...)
(defun pok-d-texto (a / txt)
  (setq txt (pok-juntar (cddr (cddddr a))))
  (if (and (pok-nums-p (list (nth 1 a) (nth 2 a) (nth 3 a) (nth 4 a)))
           (> (nth 3 a) 0)
           (/= txt "")
           (member (nth 5 a) '("esquerda" "centro")))
    (pok-texto-desenho (car a) (pok-pt (nth 1 a) (nth 2 a)) (nth 3 a) txt (* (nth 4 a) (/ pi 180.0)) (nth 5 a))
  )
)

;; A cota alinhada como DIMENSION (70 = 1 alinhada + 32 bloco só dela): 13 e 14 as pontas medidas, 10 a ponta da
;; linha de cota do lado do 14, 11 o meio do texto, 1 a medida escrita. Sem o código 2, o AutoCAD faz o bloco *D.
;; O estilo vai por cima do estilo atual (xdata DSTYLE, só nesta entidade: o estilo da pessoa não muda), com os
;; números do estilo do DXF do site, em metros, e o DIMSCALE k (o desenho em mm: tudo 1000 vezes maior). A cota
;; viva (`viva`) tem o 1 vazio (a medida do AutoCAD) e mostra metros: DIMLFAC 1/k, DIMDEC 2, DIMDSEP "," (44),
;; DIMZIN 0 ("2,00", nunca "2"), DIMRND 0, DIMLUNIT 2 (decimal) e DIMALT 0 (sem as unidades alternativas).
(defun pok-dimension (camada p1 p2 pl meio txt viva)
  (entmakex
    (list (cons 0 "DIMENSION") (cons 100 "AcDbEntity") (cons 8 camada) (cons 100 "AcDbDimension")
          (cons 10 pl) (cons 11 meio) (cons 70 33) (cons 1 (if viva "" txt)) (cons 100 "AcDbAlignedDimension")
          (cons 13 p1) (cons 14 p2)
          (list -3 (append
                     (list "ACAD" (cons 1000 "DSTYLE") (cons 1002 "{")
                           (cons 1070 40) (cons 1040 (pok-k))  ; DIMSCALE
                           (cons 1070 41) (cons 1040 0.2)      ; DIMASZ
                           (cons 1070 42) (cons 1040 0.1)      ; DIMEXO
                           (cons 1070 44) (cons 1040 0.1)      ; DIMEXE
                           (cons 1070 140) (cons 1040 0.25)    ; DIMTXT
                           (cons 1070 142) (cons 1040 0.1)     ; DIMTSZ (traço de arquitetura)
                           (cons 1070 147) (cons 1040 0.1)     ; DIMGAP
                           (cons 1070 77) (cons 1070 1))       ; DIMTAD (texto acima da linha)
                     (if viva
                       (list (cons 1070 144) (cons 1040 (/ 1.0 (pok-k)))  ; DIMLFAC
                             (cons 1070 271) (cons 1070 2)                ; DIMDEC
                             (cons 1070 278) (cons 1070 44)               ; DIMDSEP (a vírgula)
                             (cons 1070 78) (cons 1070 0)                 ; DIMZIN
                             (cons 1070 45) (cons 1040 0.0)               ; DIMRND
                             (cons 1070 277) (cons 1070 2)                ; DIMLUNIT (decimal)
                             (cons 1070 170) (cons 1070 0)))              ; DIMALT
                     (list (cons 1002 "}"))))
    )
  )
)

;; A mesma cota em LINE + TEXT, quando o AutoCAD não aceita a DIMENSION: a linha de cota, as chamadas (só quando
;; a linha sai das pontas), um traço de 45° em cada ponta e a medida, como o bloco *D do DXF do site (0,1 m e a
;; letra de 0,25 m, vezes k).
(defun pok-cota-em-linhas (camada p1 p2 pl meio r txt / q1 desloca d alem ao traco linha)
  (setq desloca (pok-menos pl p2)
        q1 (pok-mais p1 desloca)
        d (distance p2 pl)
        ao (pok-vezes (pok-menos p2 p1) (/ 1.0 (distance p1 p2)))
        traco (pok-vezes (list (- (car ao) (cadr ao)) (+ (cadr ao) (car ao)) 0.0) (* 0.1 (pok-k))))
  (if (> d 1e-9)
    (progn
      (setq alem (pok-vezes desloca (/ (* 0.1 (pok-k)) d)))
      (pok-d-linha (list camada (car p1) (cadr p1) (car (pok-mais q1 alem)) (cadr (pok-mais q1 alem)) ""))
      (pok-d-linha (list camada (car p2) (cadr p2) (car (pok-mais pl alem)) (cadr (pok-mais pl alem)) ""))
    )
  )
  (foreach q (list q1 pl)
    (pok-d-linha (list camada (car (pok-menos q traco)) (cadr (pok-menos q traco))
                       (car (pok-mais q traco)) (cadr (pok-mais q traco)) "")))
  (setq linha (pok-d-linha (list camada (car q1) (cadr q1) (car pl) (cadr pl) "")))
  (if linha (pok-texto-desenho camada meio (* 0.25 (pok-k)) txt r "centro"))
)

;; a: (camada x1 y1 x2 y2 xl yl texto...). O texto fica 0,25 m (vezes k) acima do meio da linha de cota, no sentido
;; de leitura. `viva`: a DIMENSION mostra a medida (pok-dimension).
(defun pok-d-cota (a viva / p1 p2 pl txt q1 r acima meio)
  (setq txt (pok-juntar (cdddr (cddddr a))))
  (if (and (pok-nums-p (list (nth 1 a) (nth 2 a) (nth 3 a) (nth 4 a) (nth 5 a) (nth 6 a))) (/= txt ""))
    (progn
      (setq p1 (pok-pt (nth 1 a) (nth 2 a)) p2 (pok-pt (nth 3 a) (nth 4 a)) pl (pok-pt (nth 5 a) (nth 6 a)))
      (if (> (distance p1 p2) 1e-6)
        (progn
          (setq q1 (pok-mais p1 (pok-menos pl p2))
                r (pok-legivel (atan (- (cadr p2) (cadr p1)) (- (car p2) (car p1))))
                acima (list (- (sin r)) (cos r) 0.0)
                meio (pok-mais (pok-vezes (pok-mais q1 pl) 0.5) (pok-vezes acima (* 0.25 (pok-k)))))
          (cond
            ((pok-dimension (car a) p1 p2 pl meio txt viva))
            ((pok-cota-em-linhas (car a) p1 p2 pl meio r txt) (setq cotas-em-linhas (1+ cotas-em-linhas)))
          )
        )
      )
    )
  )
)

;; Os n primeiros da lista, e a lista sem eles.
(defun pok-primeiros (l n / s)
  (repeat n (setq s (cons (car l) s) l (cdr l)))
  (reverse s)
)
(defun pok-sem-os-primeiros (l n)
  (repeat n (setq l (cdr l)))
  l
)

;; (n x y ... n x y ...) -> ((pontos do 1º contorno) (do 2º) ...), ou nil se algum contorno é torto (menos de 3
;; vértices, número que falta ou que não é número).
(defun pok-contornos (nums / n ok saida)
  (setq ok T)
  (while (and ok nums)
    (setq n (car nums) nums (cdr nums))
    (if (and (= (type n) 'INT) (>= n 3) (>= (length nums) (* 2 n)) (pok-nums-p (pok-primeiros nums (* 2 n))))
      (setq saida (cons (pok-pares (pok-primeiros nums (* 2 n))) saida)
            nums (pok-sem-os-primeiros nums (* 2 n)))
      (setq ok nil)
    )
  )
  (if ok (reverse saida))
)

;; a: (camada cor n x y ... n x y ...). HATCH SOLID por entmake (DXF Reference, HATCH): cada contorno uma polilinha
;; fechada (92 = 7: externo, polilinha, derivado; 72 = 0 sem arco; 73 = 1 fechada; 93 vértices, 97 = 0 sem objeto
;; associado), estilo normal (75 = 0: os contornos de dentro viram furo), 76 = 1 predefinido, uma semente.
(defun pok-d-hachura (a / cor contornos)
  (setq cor (nth 1 a) contornos (pok-contornos (cddr a)))
  (if (and contornos (= (type cor) 'INT) (> cor 0) (<= cor 256))
    (entmakex
      (append
        (list (cons 0 "HATCH") (cons 100 "AcDbEntity") (cons 8 (car a)) (cons 62 cor) (cons 100 "AcDbHatch")
              (list 10 0.0 0.0 0.0) (list 210 0.0 0.0 1.0) (cons 2 "SOLID") (cons 70 1) (cons 71 0)
              (cons 91 (length contornos)))
        (apply 'append
          (mapcar
            '(lambda (pts)
               (append (list (cons 92 7) (cons 72 0) (cons 73 1) (cons 93 (length pts)))
                       (mapcar '(lambda (p) (cons 10 p)) pts)
                       (list (cons 97 0))))
            contornos))
        (list (cons 75 0) (cons 76 1) (cons 98 1) (list 10 0.0 0.0 0.0))
      )
    )
  )
)

;; ("insunits-se-vazio" u): o $INSUNITS do desenho vazio (nada no modelo fora da camada das marcas); T se gravou.
(defun pok-gravar-insunits (u)
  (if (and (member u '(4 5 6)) (not (pok-algo-no-modelo)))
    (not (vl-catch-all-error-p (vl-catch-all-apply 'setvar (list "INSUNITS" u))))
  )
)

;; Um item já inteiro (com os "+" juntados). Os contadores são os locais do pok-desenhar (escopo dinâmico).
(defun pok-desenhar-um (item / tipo a feito)
  (if (= (type item) 'LIST) (setq tipo (car item) a (cdr item)))
  (cond
    ((= tipo "unidade") (if (and (pok-num-p (car a)) (> (car a) 0)) (setq por-metro (float (car a)))))
    ((= tipo "insunits-se-vazio") (if (pok-gravar-insunits (car a)) (setq insunits-gravado (car a))))
    ((= tipo "camada")
     (if (pok-camada-desenho (nth 0 a) (nth 1 a) (nth 2 a) (nth 3 a) (nth 4 a)) (setq camadas (1+ camadas))))
    ((= tipo "zoom")
     (if (setq a (pok-caixa-valida a))
       (command "_.ZOOM" "_W" (list (nth 0 a) (nth 1 a)) (list (nth 2 a) (nth 3 a)))))
    (t
     (if (pok-camada-desenho-p (car a))
       (setq feito
         (cond
           ((= tipo "polilinha") (pok-d-polilinha a))
           ((= tipo "linha") (pok-d-linha a))
           ((= tipo "arco") (pok-d-arco a))
           ((= tipo "texto") (pok-d-texto a))
           ((= tipo "cota") (pok-d-cota a nil))
           ((= tipo "cota-viva") (pok-d-cota a T))
           ((= tipo "hachura") (pok-d-hachura a))
         )
       )
     )
     (if feito (setq criadas (1+ criadas)) (setq ignoradas (1+ ignoradas))))
  )
)

;; Junta cada item com os "+" que vêm depois dele e desenha.
(defun pok-desenhar-itens (itens / pend)
  (foreach item itens
    (cond
      ((and (= (type item) 'LIST) (= (car item) "+"))
       (if pend (setq pend (append pend (cdr item))) (setq ignoradas (1+ ignoradas))))
      (t
       (if pend (pok-desenhar-um pend))
       (setq pend item))
    )
  )
  (if pend (pok-desenhar-um pend))
)

(defun pok-json-desenho (extra)
  (strcat "{\"ok\":true" extra ",\"criadas\":" (itoa criadas) ",\"ignoradas\":" (itoa ignoradas)
          ",\"camadas\":" (itoa camadas) ",\"cotasEmLinhas\":" (itoa cotas-em-linhas)
          (if insunits-gravado (strcat ",\"insunitsGravado\":" (itoa insunits-gravado)) "") "}")
)

;; O desenho no espaço do modelo, num grupo de desfazer só. Nunca apaga nem altera entidade que já existe.
;; O CTAB muda antes do UNDO _Begin (protegido: se o AutoCAD não deixar, nada é desenhado e nenhum grupo fica aberto).
;; UNDOCTL: bit 1 = UNDO ligado, bit 2 = só um comando (o UNDO "One", sem Begin/End). Fora do UNDO completo, desenha
;; sem o grupo (o _Begin ficaria preso no prompt) e avisa com "semDesfazer":true.
(defun pok-desenhar (saida itens / criadas ignoradas camadas cotas-em-linhas ss r u grupo sem-desfazer por-metro
                                    insunits-gravado)
  (setq criadas 0 ignoradas 0 camadas 0 cotas-em-linhas 0 por-metro 1.0)
  (if (and (= (type (car itens)) 'LIST) (= (car (car itens)) "se-vazio"))
    (setq ss (if (= (type (cadr (car itens))) 'STR) (ssget "_X" (list (cons 8 (cadr (car itens))))))
          itens (cdr itens))
  )
  (cond
    (ss (write-line (pok-json-desenho (strcat ",\"jaDesenhado\":" (itoa (sslength ss)))) saida))
    ((and (/= (strcase (getvar "CTAB")) "MODEL")
          (vl-catch-all-error-p (setq r (vl-catch-all-apply 'setvar (list "CTAB" "Model")))))
     (write-line (strcat "{\"ok\":false,\"erro\":"
                         (pok-js (strcat "desenhar: o AutoCAD nao deixou ir ao espaco do modelo (CTAB): "
                                         (vl-catch-all-error-message r)))
                         ",\"criadas\":0}")
                 saida))
    (t
      (setq u (getvar "UNDOCTL")
            grupo (and (= (type u) 'INT) (= (logand u 1) 1) (= (logand u 2) 0))
            sem-desfazer (if grupo "" ",\"semDesfazer\":true"))
      (if grupo (command "_.UNDO" "_Begin"))
      (setq r (vl-catch-all-apply 'pok-desenhar-itens (list itens)))
      (if grupo (command "_.UNDO" "_End"))
      (write-line
        (if (vl-catch-all-error-p r)
          (strcat "{\"ok\":false,\"erro\":" (pok-js (strcat "desenhar: " (vl-catch-all-error-message r)))
                  ",\"criadas\":" (itoa criadas) sem-desfazer "}")
          (pok-json-desenho sem-desfazer)
        )
        saida
      )
    )
  )
)

;; ---------------------------------------------------------------- a unidade do desenho aberto (0.7.0)

;; O que está no espaço do modelo fora da camada das marcas, ou nil: o desenho vazio. O nosso terreno e a nossa planta
;; (PRANCHAOK-*) contam: um terreno em metros da 0.6.0 não é desenho vazio, e o $INSUNITS dele não vira mm.
;; 410 = "Model" (o espaço do modelo, em qualquer língua); "~PRANCHAOK-PARECER" é o wcmatch de "tudo menos".
(defun pok-algo-no-modelo ()
  (ssget "_X" (list (cons 410 "Model") (cons 8 "~PRANCHAOK-PARECER")))
)

;; A mediana de uma lista de números (vl-sort-i guarda os repetidos; o vl-sort pode tirá-los), ou nil.
(defun pok-mediana (nums / ordem n)
  (if nums
    (progn
      (setq ordem (mapcar '(lambda (i) (nth i nums)) (vl-sort-i nums '<))
            n (length ordem))
      (if (= (rem n 2) 1)
        (nth (/ n 2) ordem)
        (/ (+ (nth (1- (/ n 2)) ordem) (nth (/ n 2) ordem)) 2.0)
      )
    )
  )
)

;; Até 500 alturas dos TEXT e MTEXT do modelo fora das camadas PRANCHAOK-* (o 40 dos dois).
(defun pok-alturas-dos-textos ( / ss i h alturas)
  (if (setq ss (ssget "_X" (list (cons 0 "TEXT,MTEXT") (cons 410 "Model") (cons 8 "~PRANCHAOK-*"))))
    (progn
      (setq i 0)
      (while (and (< i (sslength ss)) (< i 500))
        (setq h (cdr (assoc 40 (entget (ssname ss i)))))
        (if (and (pok-num-p h) (> h 0)) (setq alturas (cons (float h) alturas)))
        (setq i (1+ i))
      )
    )
  )
  alturas
)

;; O pedaço do `info` que diz a unidade do desenho: $INSUNITS, LTSCALE, quantas entidades há no modelo fora da
;; camada das marcas (0: vazio), a mediana da altura dos textos e o programa (PROGRAM "acad" no completo e "acadlt"
;; no LT; PRODUCT "AutoCAD" e "AutoCAD LT").
(defun pok-info-unidade ( / ss alturas programa)
  (setq ss (pok-algo-no-modelo)
        alturas (pok-alturas-dos-textos)
        programa (getvar "PROGRAM"))
  (strcat
    ",\"insunits\":" (if (pok-num-p (getvar "INSUNITS")) (itoa (getvar "INSUNITS")) "null")
    ",\"ltscale\":" (pok-jn (getvar "LTSCALE"))
    ",\"entidadesNoModelo\":" (itoa (if ss (sslength ss) 0))
    ",\"vazio\":" (pok-jbool (null ss))
    ",\"alturaDosTextos\":" (pok-jn (pok-mediana alturas))
    ",\"textosMedidos\":" (itoa (length alturas))
    ",\"programa\":" (pok-js programa)
    ",\"lt\":" (pok-jbool (or (and (= (type programa) 'STR) (wcmatch (strcase programa) "*LT"))
                               (wcmatch (strcase (cond ((getvar "PRODUCT")) (t ""))) "* LT*")))
  )
)

;; O nosso lote já desenhado: os vértices da 1ª polilinha da camada PRANCHAOK-LOTE no modelo, para o MCP achar a
;; unidade e a origem do terreno que está lá (desenho.casar_lote). Sem ela, "pontos": null.
(defun pok-lote (saida / ss ed)
  (setq ss (ssget "_X" (list (cons 0 "LWPOLYLINE") (cons 8 "PRANCHAOK-LOTE") (cons 410 "Model"))))
  (if ss (setq ed (entget (ssname ss 0))))
  (write-line
    (strcat "{\"ok\":true,\"lotes\":" (itoa (if ss (sslength ss) 0))
            ",\"handle\":" (pok-js (if ed (cdr (assoc 5 ed))))
            ",\"pontos\":" (if ed (pok-jlista (mapcar 'pok-jp (pok-pontos-de ed '(10)))) "null") "}")
    saida
  )
)

;; ---------------------------------------------------------------- info e despacho

(defun pok-info (saida / v)
  (setq v (pok-vinculo))
  (write-line
    (strcat
      "{\"ok\":true"
      ",\"versaoLisp\":" (pok-js *pok-versao*)
      ",\"produto\":" (pok-js (getvar "PRODUCT"))
      ",\"versaoAcad\":" (pok-js (getvar "ACADVER"))
      ",\"arquivo\":" (pok-js (strcat (getvar "DWGPREFIX") (getvar "DWGNAME")))
      ",\"temNome\":" (pok-jbool (= 1 (getvar "DWGTITLED")))
      ",\"salvo\":" (pok-jbool (= 0 (getvar "DBMOD")))
      ",\"layoutAtual\":" (pok-js (getvar "CTAB"))
      ",\"codificacao\":" (pok-js *pok-codificacao*)
      ",\"secureload\":" (itoa (getvar "SECURELOAD"))
      ",\"trustedpaths\":" (pok-js (getvar "TRUSTEDPATHS"))
      (pok-info-unidade)
      ",\"vinculo\":"
      (if v
        (strcat "{\"projetoId\":" (pok-js (nth 0 v)) ",\"projeto\":" (pok-js (nth 1 v)) ",\"empresaId\":" (pok-js (nth 2 v)) "}")
        "null"
      )
      "}"
    )
    saida
  )
)

(defun pok-executar (pedido saida / comando args n)
  (setq comando (car pedido) args (cdr pedido))
  (cond
    ((= comando "ping")
     (write-line (strcat "{\"ok\":true,\"versaoLisp\":" (pok-js *pok-versao*) "}") saida))
    ((= comando "info") (pok-info saida))
    ((= comando "ler")
     (write-line (strcat "{\"ok\":true,\"versaoLisp\":" (pok-js *pok-versao*) "}") saida)
     (setq n (pok-ler saida))
     (write-line (strcat "{\"fim\":true,\"entidades\":" (itoa n) "}") saida))
    ((= comando "marcar") (pok-marcar saida args))
    ((= comando "regioes") (pok-regioes saida args))
    ((= comando "caixas") (pok-caixas saida args))
    ((= comando "chamadas") (pok-chamadas saida args))
    ((= comando "desenhar") (pok-desenhar saida args))
    ((= comando "lote") (pok-lote saida))
    ((= comando "limpar") (pok-limpar saida))
    ((= comando "quadro") (pok-quadro saida (pok-juntar args)))
    ((= comando "salvar") (pok-salvar saida))
    ((= comando "ir") (pok-ir saida (nth 0 args) (nth 1 args) (nth 2 args)))
    ((= comando "vincular")
     (pok-gravar-vinculo (nth 0 args) (nth 1 args) (nth 2 args))
     (pok-info saida))
    (t (write-line (strcat "{\"ok\":false,\"erro\":" (pok-js (strcat "comando desconhecido: " (vl-princ-to-string comando))) "}") saida))
  )
)

(defun pok-atender (dir nome / id pedido tmp saida resultado)
  ;; pedido-<id>.lsp
  (setq id (substr nome 8 (- (strlen nome) 11)))
  (setq pedido (pok-ler-pedido (strcat dir nome)))
  (vl-file-delete (strcat dir nome))
  (setq tmp (strcat dir "resposta-" id ".tmp"))
  (setq saida (pok-abrir tmp "w"))
  (setq resultado
    (cond
      ((eq (car pedido) 'ERRO)
       (write-line (strcat "{\"ok\":false,\"erro\":\"PEDIDO_INVALIDO (linha " (itoa (cadr pedido)) ")\"}") saida)
       nil)
      ((= (type (car pedido)) 'STR) (vl-catch-all-apply 'pok-executar (list pedido saida)))
      (t (write-line "{\"ok\":false,\"erro\":\"PEDIDO_INVALIDO\"}" saida) nil)
    )
  )
  (close saida)
  (if (vl-catch-all-error-p resultado)
    (progn
      (setq saida (pok-abrir tmp "w"))
      (write-line (strcat "{\"ok\":false,\"erro\":" (pok-js (vl-catch-all-error-message resultado)) "}") saida)
      (close saida)
    )
  )
  (vl-file-delete (strcat dir "resposta-" id ".jsonl"))
  (vl-file-rename tmp (strcat dir "resposta-" id ".jsonl"))
)

;; Chamado pelo MCP (digita "(c:pok-mcp)" na linha de comando).
(defun c:pok-mcp ( / dir)
  (setq dir (pok-dir))
  (foreach nome (vl-directory-files dir "pedido-*.lsp" 1) (pok-atender dir nome))
  (princ)
)

;; ---------------------------------------------------------------- teste manual (spike)

;; POKTESTE: sem MCP nem rede. Grava ao lado do DWG:
;;   prancha-ok-teste.jsonl  info + leitura (depois das marcas)
;; e marca a 1ª cota do model space e o 1º texto do paper space com "TAXA".
(defun c:pokteste ( / arq saida e ed alvo1 alvo2 n)
  (setq arq (strcat (getvar "DWGPREFIX") "prancha-ok-teste.jsonl"))
  (setq e (entnext))
  (while (and e (not (and alvo1 alvo2)))
    (setq ed (entget e))
    (if (and (not alvo1) (= (cdr (assoc 0 ed)) "DIMENSION") (= (car (pok-espaco ed)) "modelo"))
      (setq alvo1 (cdr (assoc 5 ed))))
    (if (and (not alvo2)
             (member (cdr (assoc 0 ed)) '("TEXT" "MTEXT"))
             (= (car (pok-espaco ed)) "papel")
             (wcmatch (strcase (cond ((cdr (assoc 1 ed))) (t ""))) "*TAXA*"))
      (setq alvo2 (cdr (assoc 5 ed))))
    (setq e (entnext e))
  )
  (setq saida (pok-abrir arq "w"))
  (pok-info saida)
  (pok-gravar-vinculo "projeto-teste" "Projeto de teste (acentuação: ção, área)" "empresa-teste")
  (pok-marcar saida
    (vl-remove nil
      (list (if alvo1 (list alvo1 1 "[1] Cota de teste do Prancha Ok"))
            (if alvo2 (list alvo2 5 "[2] Texto de teste: área, ção")))))
  (pok-info saida)
  (write-line "{\"leitura\":true}" saida)
  (setq n (pok-ler saida))
  (write-line (strcat "{\"fim\":true,\"entidades\":" (itoa n) "}") saida)
  (close saida)
  (if alvo2 (progn (setq saida (pok-abrir (strcat arq ".ir") "w")) (pok-ir saida alvo2 nil "") (close saida)))
  (princ (strcat "\n[Prancha Ok] teste gravado em " arq " (" (itoa n) " entidades). Marcados: "
                 (vl-princ-to-string alvo1) " " (vl-princ-to-string alvo2)))
  (princ)
)

(princ (strcat "\n[Prancha Ok] prancha_ok.lsp " *pok-versao* " carregado."))
(princ)
