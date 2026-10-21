# Comprimentos usados nas verificações

A referência é a ABNT NBR 8800:2024, versão corrigida em 25/02/2025:
4.12 (contenções, páginas impressas 33–35) e 5.3.5.1 (forças de flambagem,
páginas impressas 48–49). No OSA, x é o eixo longitudinal da barra;
os nomes dos comprimentos são Ly, Lz e Lt.

## Critérios da implementação

- Apoios extremos e contenções intermediárias têm papéis distintos. A rigidez
  mínima para qualificar uma contenção intermediária não elimina um apoio
  extremo do cálculo local da barra. A estabilidade global da estrutura é uma
  verificação distinta.
- Ausência de liberação transmite a restrição do nó à barra. Ela não cria
  ancoragem externa: a rotina também consulta apoios e elementos externos ao grupo.
- Um nó de subdivisão ou uma barra externa sem ancoragem não reduz os comprimentos.
- Em balanço com engaste de translação e rotação comprovado no modo considerado,
  adota-se conservadoramente o dobro do trecho até a extremidade livre. Contenções
  intermediárias são ignoradas nessa aproximação. Uma base liberada ou semirrígida
  não é promovida a engaste ideal.
- Se a contenção à torção nos extremos não puder ser qualificada, o cálculo de
  compressão pode continuar desprezando a contribuição positiva do empenamento.
  A hipótese conservadora é Lt → ∞, que resulta em Net = GJ/r0² pelo limite da
  expressão de 5.3.5.1-c. Isso é uma opção de cálculo da implementação; não é uma
  afirmação de que a norma exige Lt infinito. A hipótese aparece nas notas do memorial.
- Molas de torção intermediárias não qualificadas não encurtam Lt na compressão.
- Liberações ou flexibilidades rotacionais internas sem contenção que preserve
  a estabilidade do grupo continuam impedindo o uso das expressões de uma barra
  contínua. A rotina informa o modo e o nó afetados.

## Reaproveitamento dos dados

Memorial e verificações usam `restraint_lengths`, com comprimentos, modos,
pendências e notas compartilhados por grupo, parâmetros e análise. Uma alteração
do modelo ou uma nova análise invalida os dados. Não se recalcula o mesmo grupo
ao abrir o memorial antes ou depois da verificação.

As frações das equações do memorial devem usar `\dfrac`.
