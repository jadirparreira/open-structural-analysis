# Diretrizes de desempenho gráfico

Este documento define os princípios que devem orientar alterações na cena 3D,
nos renderizadores e nos componentes visuais do Open Structural Analysis.
Ele é a fonte de decisão para discussões, implementação e revisão de
otimizações gráficas.

## Objetivo

Manter a modelagem estrutural correta, legível e interativa mesmo quando o
projeto possuir muitos nós, membros, rótulos, ações ou resultados.

Desempenho não significa remover informação indiscriminadamente. Significa
entregar primeiro a informação mais importante e reduzir o custo das
informações secundárias conforme a densidade da cena, o nível de zoom e a
interação do usuário.

## Ordem de prioridade

Quando houver conflito entre recursos, a decisão deve seguir esta ordem:

1. Correção geométrica e estrutural.
2. Interação básica: selecionar, orbitar, pan, zoom e editar.
3. Visibilidade dos elementos essenciais do modelo.
4. Clareza da seleção, dos estados e dos resultados.
5. Detalhes visuais secundários.
6. Efeitos decorativos.

Uma otimização não pode eliminar silenciosamente informação estrutural
essencial. Quando algum detalhe precisar ser ocultado, deve existir uma regra
previsível de visibilidade ou um controle explícito para recuperá-lo.

## O que deve continuar no programa

Mesmo em cenas densas, devem permanecer disponíveis:

- a geometria e a conectividade do modelo;
- a distinção visual entre nós, membros, apoios, ações e resultados;
- a seleção e a identificação do elemento sob o cursor;
- a edição do modelo sem exigir reconstrução completa da cena;
- o contexto espacial mínimo, como orientação e referência de coordenadas;
- o estado de erro, aviso ou processamento quando ele for relevante para a
  decisão do usuário.

Grid, eixos, rótulos, setas, símbolos e outros auxiliares podem ser reduzidos,
agrupados ou ocultados de forma adaptativa, desde que isso não prejudique a
interpretação do modelo.

## Princípios técnicos

### 1. Atualizar somente o que mudou

- Preferir atualizações incrementais a reconstruções completas da cena.
- Separar mudanças de geometria, aparência, seleção, rótulos e câmera.
- Usar marcações de alteração (por exemplo, cena suja, geometria suja ou
  seleção suja) para evitar trabalho repetido.
- Não recalcular malhas, textos ou resultados quando somente a câmera mudou.

### 2. Reutilizar recursos de renderização

- Reutilizar malhas, materiais, buffers e atores sempre que possível.
- Evitar criar um objeto gráfico independente para cada detalhe visual sem
  medir o custo dessa escolha.
- Agrupar elementos que compartilham geometria, material ou comportamento.
- Liberar explicitamente recursos temporários ao trocar de modelo ou de modo
  de visualização.

### 3. Tornar a qualidade adaptativa

- Usar níveis de detalhe conforme zoom, densidade e distância da câmera.
- Priorizar elementos selecionados, sob o cursor e próximos ao foco do usuário.
- Reduzir ou suspender rótulos, marcadores e efeitos secundários durante
  orbit, pan e zoom; restaurá-los ao final da interação.
- Aplicar culling e limites de visibilidade quando elementos fora do campo de
  interesse não contribuírem para a decisão atual.
- Preferir simplificação progressiva a travamento ou falha da aplicação.

### 4. Manter a interação leve

- Eventos de movimento do mouse e da câmera não devem iniciar operações
  pesadas sem necessidade.
- Operações caras devem ser agrupadas, limitadas por frequência ou adiadas
  até o fim da interação quando isso for visualmente aceitável.
- A seleção deve ter um caminho rápido, independente da atualização completa
  de rótulos e resultados.
- O usuário deve continuar recebendo resposta visual durante operações longas.

### 5. Separar domínio e apresentação

- O renderizador deve consumir o domínio em modo somente leitura.
- O estado estrutural não deve ser duplicado em múltiplas estruturas gráficas
  sem uma razão clara.
- A otimização visual não pode alterar a geometria, as propriedades ou os
  resultados estruturais.
- Dados destinados à renderização devem ser preparados em estruturas adequadas
  para processamento em lote, sem espalhar conversões pelos widgets.

### 6. Medir antes e depois

Toda otimização relevante deve registrar:

- cenário usado, incluindo quantidade aproximada de elementos;
- ação avaliada, como abrir, editar, selecionar ou navegar;
- tempo de atualização, fluidez percebida e consumo de memória quando
  aplicável;
- comportamento antes e depois da alteração;
- eventual perda ou mudança de detalhe visual.

Os testes devem incluir pelo menos um modelo pequeno, um modelo representativo
e um modelo grande. Os números exatos dos cenários devem evoluir com o uso
real do programa; não se deve declarar uma otimização apenas porque o código
parece mais simples.

Como referência inicial, uma interação contínua deve permanecer perceptível e
controlável. O objetivo ideal é aproximar 60 quadros por segundo; quando isso
não for possível, deve-se priorizar uma interação estável, sem travamentos
longos, e documentar o limite observado.

## Regras de decisão para redução visual

Quando a cena estiver sobrecarregada, aplicar as reduções nesta ordem:

1. ocultar efeitos puramente decorativos;
2. reduzir densidade do grid e dos eixos auxiliares;
3. limitar rótulos e marcadores aos elementos selecionados, próximos ou em
   foco;
4. simplificar símbolos, espessuras e malhas secundárias;
5. reduzir detalhes de resultados não selecionados;
6. somente então considerar ocultar elementos estruturais, sempre com regra
   previsível e indicação clara ao usuário.

A seleção, o foco e os comandos de exibição devem conseguir recuperar a
informação reduzida sem modificar o modelo.

## Evitar

- reconstruir toda a cena para uma alteração local;
- recalcular propriedades estruturais em eventos puramente gráficos;
- criar rótulos ou geometrias ilimitados sem política de densidade;
- manter simultaneamente versões redundantes e pesadas da mesma geometria;
- executar processamento pesado em cada evento de mouse ou câmera;
- trocar correção visual por ganho de desempenho sem registrar a decisão;
- usar um limite arbitrário de elementos sem medir memória, tempo e fluidez;
- ocultar informação essencial sem uma forma clara de inspeção.

## Processo obrigatório para uma otimização

1. Descrever o sintoma e o cenário de reprodução.
2. Identificar se o custo está na preparação de dados, na criação de objetos
   gráficos, na renderização, nos rótulos, na interação ou na memória.
3. Medir uma referência antes da alteração.
4. Aplicar a menor mudança que respeite as prioridades deste documento.
5. Verificar correção, seleção, edição e legibilidade em modelos de tamanhos
   diferentes.
6. Medir novamente e registrar o resultado no Pull Request ou na issue.
7. Se a regra de visibilidade mudar, documentar o comportamento esperado e
   como o usuário recupera o detalhe.

## Checklist de revisão

- [ ] A alteração preserva geometria, conectividade e resultados?
- [ ] A interação básica continua disponível em cenas densas?
- [ ] O trabalho foi limitado ao que realmente mudou?
- [ ] Recursos gráficos são reutilizados ou liberados corretamente?
- [ ] Existe política para rótulos, detalhes e elementos fora de foco?
- [ ] Foram avaliados modelos pequeno, representativo e grande?
- [ ] Há uma medição ou observação reproduzível antes/depois?
- [ ] O comportamento de redução visual é previsível para o usuário?
- [ ] Os testes existentes continuam passando?

## Regra de manutenção deste documento

Este arquivo deve ser atualizado quando uma otimização estabelecer uma nova
regra geral, mudar a prioridade de algum elemento ou introduzir um modo de
qualidade configurável.

Detalhes específicos de implementação pertencem ao código e aos testes. Este
documento deve conter princípios duráveis e critérios de decisão, não uma lista
de otimizações temporárias ou dependentes de uma biblioteca específica.
