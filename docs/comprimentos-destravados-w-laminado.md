# Comprimentos destravados do W laminado

A referência normativa desta rotina é exclusivamente a **ABNT NBR 8800:2024,
Versão Corrigida:2025**. A identificação geométrica e o cálculo de flexibilidade
descritos abaixo são procedimentos do programa para interpretar o modelo
analítico, não uma declaração de que todas as contenções foram dimensionadas.

Referências consultadas:

- [Catálogo ABNT — edição vigente](https://www.abntcatalogo.com.br/default.aspx?P=M6V7DQ6JE0Z9).
- [Texto da NBR 8800:2024 disponível para consulta](https://studylib.net/doc/28489089/nbr-8800--2024-):
  4.10.3.2, 4.12, 5.3.5.1 e 5.4.2.3.

## Convenção de eixos

No OSA, o eixo local **x é longitudinal**. Os eixos transversais são y e z;
na seção W usual, a flexão forte ocorre em torno de y.

| Nome no OSA | Movimento a restringir | Correspondência com 5.3.5.1 |
| --- | --- | --- |
| Ly | Deslocamento na direção local z; flexão em torno de y | Lx da norma |
| Lz | Deslocamento na direção local y; flexão em torno de z | Ly da norma |
| Lt | Giro em torno do eixo longitudinal local x | Lz da norma |
| Lb | Contenção aplicável à flambagem lateral com torção | Lb da norma |

Os nomes novos não devem apenas substituir textos: cada comprimento precisa
alimentar a inércia ou constante correspondente. Não há parâmetro K.

## Requisitos normativos relevantes

A seção 4.12 condiciona a eficácia da contenção à sua resistência e rigidez,
incluindo ligação e ancoragem. A ligação de eixos de barras não comprova esses
requisitos por si só. Uma contenção de translação de viga depende de sua
posição em relação às mesas. A contenção de torção pode atuar em outra posição.
Um ponto de inflexão não constitui automaticamente contenção.

São tratados separadamente os requisitos de compressão (4.12.2) e os de viga
(4.12.3). O cálculo de comprimento não substitui a análise de estabilidade
global nem a verificação de resistência do sistema de contenção.

## Interpretação analítica implementada

1. O elemento, incluindo os grupos, é ordenado como uma sequência colinear,
   sem lacunas, sobreposições ou mudança dos eixos transversais. A direção e a
   rotação usam `member_basis`, a mesma convenção do solver.
2. São examinados os nós que o solver efetivamente conecta ao eixo do elemento,
   inclusive nós interiores de uma barra física não subdividida pelo usuário.
   Um cruzamento desenhado sem conexão analítica não cria contenção.
3. A matriz elástica da estrutura vizinha é obtida dos mesmos elementos do
   solver, com molas, liberações, ligações semirrígidas e barras rígidas. Os
   elementos verificados são excluídos para não contribuírem para seu próprio
   travamento. Restrições rotacionais criadas apenas para regularizar graus de
   liberdade desconectados do solver não são usadas como apoios físicos.
4. Ações unitárias nos eixos locais medem a flexibilidade da estrutura externa.
   Os demais graus de liberdade ficam livres para responder. Uma barra
   pendurada ou um mecanismo não fornece rigidez efetiva. A solução usa matriz
   esparsa, escala pela diagonal e verifica o resíduo de equilíbrio.
5. Para vários pontos que dependem da mesma estrutura, usa-se o inverso da
   soma absoluta da linha da matriz de flexibilidade como limite conservador
   de rigidez. Assim, a avaliação não fixa artificialmente os nós vizinhos.
   A flexibilidade da ligação semirrígida do próprio elemento é somada em série.
6. As contenções de translação em compressão são comparadas com a rigidez
   mínima de 4.12.2.2. A demanda é o maior esforço de compressão das combinações
   processadas. Pontos insuficientes são removidos e os intervalos recalculados.
7. Para Lb, o modelo atual permite identificar contenções **de torção**. A rigidez
   é comparada com 4.12.3.6, usando o maior momento de flexão forte processado e
   a rigidez à distorção da alma sem enrijecedores. A contenção lateral no eixo
   central, isoladamente, não é interpretada como ligação na mesa comprimida.
8. Para cada modo, adota-se separadamente o **maior intervalo** entre os pontos
   considerados. Comprimentos não são somados nem promediados por combinação.
   A memória registra os nós, posições, rigidezes e o intervalo governante.

Não se calcula Cb nesta etapa: seu valor provisório continua 1,0.

## Limites explícitos

- O usuário escolheu determinar as contenções pelo modelo analítico e deixar
  pendente a comprovação de resistência das contenções, ligações e ancoragens.
  Essa pendência acompanha a memória de cálculo.
- O modelo de pórtico possui seis graus de liberdade por nó, sem empenamento.
  Por isso, para **Lt em compressão**, uma mola de giro finita não é convertida
  automaticamente em contenção ideal. Nesta etapa, apenas restrições ideais de
  giro que sejam transmitidas pela ligação reduzem esse comprimento. Quando
  a condição de extremidade necessária não puder ser comprovada, o elemento
  recebe `not_checked`, com a causa e a memória, em vez de uma aprovação.
- Extremidades livres, liberações internas sem contenção e demais condições
  incompatíveis com as fórmulas disponíveis exigem análise específica. Não se
  introduz um K implícito nem um multiplicador arbitrário do comprimento.
- Enrijecedores, diafragmas, ligações nas mesas, travamentos contínuos e a
  resistência de ligações não possuem descrição suficiente no domínio atual.
  Deslocamentos exclusivamente visuais da seção não representam ligações
  excêntricas no modelo analítico.
- A detecção não equivale à validação completa de um sistema que contenha
  vários elementos de verificação ao mesmo tempo. Essa validação deve incluir
  as solicitações conjuntas e os efeitos de estabilidade pertinentes.

Os critérios acima limitam as reduções automáticas ao que é identificável no
modelo atual. A evolução para contenções elásticas de torção em compressão
exige acrescentar a análise correspondente, em vez de aceitar qualquer rigidez
positiva como apoio ideal.
