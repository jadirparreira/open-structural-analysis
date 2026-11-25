# Wood-Armer e von Mises nas placas

Os resultados adicionais ficam na lista de diagramas da família Placas, na
sessão Análise. Participam da escala de cores, da consulta por clique e dos
quatro modos existentes de apresentação dos elementos finitos.

## Resultados disponíveis

| Diagrama | Grandeza | Unidade |
| --- | --- | --- |
| Wood-Armer X superior (Mwx,sup) | Momento para armadura X na face superior | kN·m/m |
| Wood-Armer Y superior (Mwy,sup) | Momento para armadura Y na face superior | kN·m/m |
| Wood-Armer X inferior (Mwx,inf) | Momento para armadura X na face inferior | kN·m/m |
| Wood-Armer Y inferior (Mwy,inf) | Momento para armadura Y na face inferior | kN·m/m |
| Von Mises superior (σvm,sup) | Tensão equivalente na face superior | MPa |
| Von Mises inferior (σvm,inf) | Tensão equivalente na face inferior | MPa |
| Von Mises máximo (σvm,máx) | Maior tensão equivalente entre as duas faces | MPa |

## Eixos e faces

As direções para Wood-Armer são os eixos X/Y comuns da placa, os mesmos usados
na geração da malha e nos perfis de pressão. Os tensores de cada quadrilátero
são transformados para essas direções antes do cálculo. Isso evita que uma
rotação da malha altere as direções de armadura.

Face superior corresponde ao lado +Z local da placa; inferior corresponde a
-Z local. Essas referências não dependem da câmera nem significam
necessariamente cima e baixo no sistema global, especialmente em placas verticais.
O campo `axes` dos resultados contém os vetores globais X, Y e Z da placa.
Em elementos com pequeno empenamento, a direção X comum é projetada no plano
local do elemento e os eixos são ortonormalizados.

## Wood-Armer

A implementação considera armaduras ortogonais e flexão com torção. Os quatro
valores são magnitudes não negativas de momentos para dimensionamento.
Não são áreas de armadura e não incorporam a interação com esforços de membrana.

Para uma face, sejam `a` e `b` os momentos positivos quando tracionam essa face e
`c = |Mxy|`. Os valores iniciais são `a + c` e `b + c`.

- Se `a < -c`, o resultado X é zero e o resultado Y é `max(0, b + c²/|a|)`.
- Caso contrário, se `b < -c`, o resultado Y é zero e o resultado X é
  `max(0, a + c²/|b|)`.
- Nos demais casos, ambos os resultados iniciais são limitados inferiormente a zero.

O procedimento é aplicado separadamente às faces. Os momentos brutos do
PyNite representam a integral de `z * tensão`, com valores positivos associados
à tração na face +Z. Assim, para a face superior são usados os momentos brutos
transformados; para a inferior, seus opostos.

A correção de uma direção segue o procedimento descrito pela
[Autodesk para Wood-Armer](https://help.autodesk.com/cloudhelp/2020/CHS/RSAPRO-UsersGuide/files/GUID-80FE7814-C14D-4A89-A6DF-68EB9E7E4815.htm).

## Von Mises

Para seção homogênea com espessura `t` em metros, as três componentes de tensão
nas faces são reconstruídas a partir das tensões de membrana e do tensor de
momentos brutos do solver:

```text
σx,sup = σx,mem + 6 Mx / t²
σy,sup = σy,mem + 6 My / t²
τxy,sup = τxy,mem + 6 Mxy / t²
```

Na face inferior, o sinal da parcela de flexão é invertido. Em cada face:

```text
σvm = sqrt(σx² - σx σy + σy² + 3 τxy²)
```

O cálculo assume estado plano de tensões nas faces e não inclui cisalhamento
transversal. A conversão de kN/m² para MPa divide o valor por 1000. O máximo
entre faces é calculado em cada ponto antes da interpolação.

Esse resultado descreve a tensão equivalente elástica. Não aprova a resistência
do concreto nem substitui verificações de armadura, fissuração, punção ou estabilidade.
O uso de von Mises como critério de escoamento é associado a materiais dúcteis,
conforme a [documentação do SOLIDWORKS](https://help.solidworks.com/2024/english/SolidWorks/cworks/r_Summary_of_Failure_Criteria.htm).

## Interpolação e projetos existentes

Os valores são calculados no centro e nos quatro nós de cada elemento usando
as componentes correspondentes à mesma posição. Nos modos com média, a média
é aplicada aos resultados escalares já calculados. As cores e a consulta por
clique seguem essa mesma convenção; a suavização visual não representa uma nova
solução estrutural.

Projetos antigos com análise válida recebem os campos derivados a partir dos
resultados brutos, da espessura e do contorno da placa. Esse enriquecimento não
altera a revisão estrutural, os esforços originais ou as cargas. Quando a análise
já está inválida, continua sendo necessário processar novamente a estrutura.

## MCP

`get_capabilities` lista os sete diagramas, unidades e convenções. A ferramenta
`set_analysis_view` seleciona os novos diagramas com `result_kind: "plate"`.
`get_plate_analysis_results` inclui em cada elemento:

- `wood_armer`: `[Xsup, Ysup, Xinf, Yinf]`, em kN·m/m;
- `wood_armer_nodal`: quatro linhas na mesma ordem dos nós do elemento;
- `von_mises`: `[superior, inferior, maximo_faces]`, em MPa;
- `von_mises_nodal`: quatro linhas na mesma ordem dos nós do elemento.

As propriedades `thickness_m`, `axes` e `postprocessing` descrevem a espessura,
as direções e as convenções. A ausência de componentes de entrada impede o cálculo
do respectivo campo; componentes ausentes não são substituídas por zero.
