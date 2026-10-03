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
;;; Escreve no desenho só na camada PRANCHAOK-PARECER (marcas do parecer, que
;;; não plotam e que o motor ignora) e no dicionário PRANCHAOK (vínculo com o
;;; projeto). Nunca altera o que o arquiteto desenhou.

(setq *pok-versao* "0.3.4")
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
    ;; prancha real 01 tem lados em SPLINE, e o medir_prancha precisa fechar o contorno.
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

(defun pok-rotulo (caixa espaco texto altura cor)
  (entmakex
    (append
      (list '(0 . "MTEXT") '(100 . "AcDbEntity") (cons 8 *pok-camada*))
      (pok-cor cor)
      (if (= (car espaco) "papel") (list '(67 . 1) (cons 410 (cadr espaco))))
      (list '(100 . "AcDbMText")
            (list 10 (nth 0 caixa) (+ (nth 3 caixa) (* 0.5 altura)) 0.0)
            (cons 40 altura) '(71 . 7) (cons 1 texto))
    )
  )
)

;; Caixa com folga, para a nuvem não encostar no texto marcado.
(defun pok-caixa-folgada (caixa ed / w h folga)
  (setq w (- (nth 2 caixa) (nth 0 caixa)) h (- (nth 3 caixa) (nth 1 caixa)))
  (setq folga (max (* 0.25 (max w h)) (* 0.5 (cond ((cdr (assoc 40 ed))) (t 0.0))) 1e-3))
  (list (- (nth 0 caixa) folga) (- (nth 1 caixa) folga) (+ (nth 2 caixa) folga) (+ (nth 3 caixa) folga))
)

(defun pok-altura-rotulo (caixa ed)
  (cond
    ((cdr (assoc 40 ed)))
    (t (* 0.15 (max (- (nth 2 caixa) (nth 0 caixa)) (- (nth 3 caixa) (nth 1 caixa)))))
  )
)

;; marcas: lista de (handle cor texto...). Devolve as marcadas e as que não têm lugar.
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
        (pok-rotulo caixa espaco (pok-juntar (cddr m)) (pok-altura-rotulo caixa ed) (cadr m))
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

;; Altura do rótulo de uma região: a do texto do título, senão 1/50 do lado maior.
(defun pok-altura-regiao (caixa ed)
  (cond
    ((and ed (cdr (assoc 40 ed))) (cdr (assoc 40 ed)))
    (t (max (/ (max (- (nth 2 caixa) (nth 0 caixa)) (- (nth 3 caixa) (nth 1 caixa))) 50.0) 1e-3))
  )
)

;; regioes: lista de (handle-do-titulo caixa espaco cor texto...). Devolve os índices
;; (na ordem do pedido) das que ganharam nuvem e das que não se acharam.
(defun pok-regioes (saida regioes / lugar esp cx ed i feitas sem)
  (pok-garantir-camada)
  (setq i 0)
  (foreach r regioes
    (setq lugar (if (and (= (type r) 'LIST) (>= (length r) 4)) (pok-lugar-regiao (nth 0 r) (nth 1 r) (nth 2 r))))
    (if lugar
      (progn
        (setq esp (nth 0 lugar) cx (nth 1 lugar) ed (nth 2 lugar))
        (pok-nuvem cx esp (nth 3 r))
        (pok-rotulo cx esp (pok-juntar (cddddr r)) (pok-altura-regiao cx ed) (nth 3 r))
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

;; ---------------------------------------------------------------- chamadas (0.3.4)

;; caixas: lista de handles. Responde {"ok":true} e uma linha por handle: o espaço, o layout,
;; a caixa (pok-caixa, sem folga) e a altura do texto (null se não é texto), ou semLugar (o
;; desenho não tem o handle, ou ele está dentro de um bloco, onde a nuvem também não vai).
(defun pok-caixas (saida handles / e ed esp cx)
  (write-line "{\"ok\":true}" saida)
  (foreach h handles
    (setq e (if (and (= (type h) 'STR) (/= h "")) (handent h))
          ed (if e (entget e))
          esp (if ed (pok-espaco ed))
          cx (if (and esp (member (car esp) '("modelo" "papel"))) (pok-caixa ed)))
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
(defun pok-quadro (saida texto / emin emax altura x y)
  (pok-garantir-camada)
  (setq emin (getvar "EXTMIN") emax (getvar "EXTMAX"))
  (setq altura (max (/ (- (cadr emax) (cadr emin)) 90.0) 1e-3))
  (setq x (+ (car emax) (* 4 altura)) y (cadr emax))
  (entmakex
    (append
      (list '(0 . "MTEXT") '(100 . "AcDbEntity") (cons 8 *pok-camada*) '(100 . "AcDbMText")
            (list 10 x y 0.0) (cons 40 altura) (cons 41 (* 70 altura)) '(71 . 1))
      (pok-mtext-dados texto)
    )
  )
  (write-line "{\"ok\":true}" saida)
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
