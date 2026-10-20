# Diagramas de elementos rotacionados

Os eixos locais usados pelo cálculo coincidem com os eixos da seção desenhada
no OpenSA, incluindo sua rotação. A convenção do OpenSA usa Z global vertical;
o adaptador converte essa base para a referência Y vertical do PyNite. Passar
somente o ângulo de rotação não é suficiente para pilares e barras inclinadas.
Essa conversão também se aplica às inércias, cargas locais e vinculações.

**Fletor Y/Z** e **Cortante Y/Z** mostram componentes nos eixos locais de cada
barra. Um zero nessa vista significa que a componente selecionada é nula,
não que a barra esteja sem flexão. A rotação pode decompor a flexão entre My e
Mz. Os sinais e as cores seguem a convenção de apresentação já usada no OpenSA.

Os diagramas usam diretamente cada componente local, como no visualizador
nativo do PyNite. Não há combinação de My com Mz na apresentação. As faixas se
projetam em z local para My e em y local para Mz; suas geometrias acompanham a
rotação das seções. O OpenSA inverte o sinal textual dos momentos para manter
sua convenção de apresentação; os valores absolutos e o lado físico da curva
coincidem com o PyNite. As malhas continuam agrupadas por cor.

Resultados salvos antes dessa correção são marcados como desatualizados e exigem
novo processamento. A mudança pode alterar os valores calculados, pois corrige
a orientação física das rigidezes, além de corrigir a representação gráfica.

No pórtico de validação (vão de 4 m, altura de 3 m, perfis W 410 x 38.8, pilares
com rotação de 90°, peso próprio e carga vertical de 20 kN/m na viga), a combinação
característica recalculada apresenta aproximadamente 19,684 kN·m nos encontros
viga/pilares, 9,677 kN·m nas bases e 21,100 kN·m de momento positivo no vão.
Antes da conversão de eixos, os pilares eram calculados na outra orientação e
apresentavam My praticamente nulo e Mz de até 2,131 kN·m.
