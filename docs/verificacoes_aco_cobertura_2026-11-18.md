# Verificações de aço: implementação, cobertura e validação

Registro técnico de 18/11/2026. A cobertura abaixo distingue cálculo implementado de dados que precisam ser informados e de procedimentos ainda não cobertos. Uma família registrada no worker não implica cobertura de todas as situações possíveis dessa família.

## Base de referência

As fontes permanecem na pasta externa fornecida pelo usuário. Nenhum PDF, extração integral ou imagem de norma integra o aplicativo ou seus testes.

| Referência | Uso nesta implementação |
| --- | --- |
| ABNT NBR 8800:2024, terceira edição, versão corrigida em 25/02/2025 | Resistências e interações dos tubulares; revisão dos procedimentos e limites dos laminados. O nome do arquivo “2025” não foi tratado como ano de uma nova edição. |
| ABNT NBR 14762:2010 | Tração dos formados a frio; resistência direta, Anexo C; cortante de alma, interação momento–cortante, flexão composta e limites gerais aplicáveis. |
| ABNT NBR 6355:2012 | Convenção geométrica dos Z45/Z90 e comparação de propriedades com tabelas, inclusive U formado. |
| ABNT NBR 8261:2019 e NBR 16239:2013 | Contexto do produto tubular e critérios específicos. A curva de compressão adotada é a geral da NBR 8800; não se presume o tratamento térmico necessário para aplicar uma curva específica. |
| ABNT NBR 15980:2024 e NBR 16683:2018, versão corrigida de 2020 | Referências de produto/dimensões dos laminados; não substituem a norma de dimensionamento. |

A edição de 2008 da NBR 8800 e a bibliografia antiga não fundamentam as novas resistências. A seleção considera as edições anexadas e aplicáveis, sem afirmar consulta de vigência ao catálogo atual da ABNT. Os valores nominais de material e sua qualificação estrutural continuam sendo dados do projeto; os limites numéricos verificáveis são conferidos, sem substituir certificados ou ensaios.

## Matriz de cobertura

| Família | Procedimentos disponíveis | Entradas e limites relevantes |
| --- | --- | --- |
| W e HP laminados | Tração, compressão, flexão e cortante nos dois eixos, interações axial–flexão, esbeltez; Cb automático para FLT no eixo principal | Cb usa a NBR 8800:2024, 5.4.2.3(a), amostras do diagrama no intervalo Lb já identificado pelo OSA e mínimo entre combinações com momento. An e Ct explícitos quando há tração. A resistência ao torque aplicado não é verificada; a solicitação é registrada na memória e não altera o resultado das demais verificações. FLA fora da faixa não é extrapolada. Raios de concordância adotados precisam corresponder ao produto. |
| I laminado | Mesma estrutura de verificações, com geometria própria; Cb automático para FLT no eixo principal | Corrigidos o valor de referência de FLA e sua extrapolação indevida. A resistência ao torque aplicado não é verificada; a solicitação é registrada na memória e não altera o resultado das demais verificações. Casos especiais de 5.4.2.3(b/c) e 5.4.2.4 não são inferidos pelo cálculo automático de Cb. |
| U laminado | Tração, compressão, flexão/cortante em ambos os eixos e interações existentes; Cb automático para FLT no eixo de simetria | O Cb segue 5.4.2.3(a), com Rm=1 para o U fletido no eixo de simetria. A resistência ao torque aplicado não é verificada; a solicitação é registrada na memória e não altera o resultado das demais verificações. Não se transfere automaticamente o Anexo E para U com alma fora da faixa. |
| L laminado | Tração, compressão com eixos principais e flexo-torção, esbeltez | A hipótese antiga de exemplo de flexão e cortante foi retirada da aprovação normativa; flexão, cortante e interações dependentes sem procedimento específico ficam como limitações informativas na memória e não bloqueiam as demais verificações. Torque aplicado também é apenas registrado. Ly/Lz manuais referem-se aos eixos principais e devem ser informados juntos. |
| T laminado | Tração, compressão, flexão Y com distinção do sinal, cortante Z na alma, interações com resistências disponíveis | Corrigida a direção do cortante da alma, conforme 5.4.3.3. Flexão Z e cortante Y e interações dependentes ficam como limitações informativas na memória e não bloqueiam as demais verificações; Cb ainda não é determinado automaticamente. Torque aplicado também é apenas registrado. |
| Tubular circular | Tração, compressão geral com redução local, flexão e cortante em ambos os eixos, torção e interações suportadas | An/Ct explícitos. LvY/LvZ necessários quando o ramo de cortante depende desses comprimentos. Limites D/t são conferidos. Interações com torção fora do campo uniaxial implementado ficam pendentes do procedimento de tensões de 5.5.2.3. |
| Tubular quadrado/retangular | Tração, compressão com área efetiva, FLM/FLA/FLT, cortantes independentes, torção e interações suportadas | Geometria arredondada: raios externo 2t e interno t. Exige comprovação de que a parcela torsional não governa a compressão; caso contrário, falta Cw. Alma além da faixa e torção fora do domínio não são extrapoladas. |
| U/C/Z simples/Z45/Z90/L/Cartola formados | Tração e MRD de compressão/flexão nos dois eixos; esforços críticos locais e distorcionais automáticos por faixas finitas para compressão uniforme e flexão uniforme; interação axial–flexão com esforços concomitantes | O modo global continua exigindo esforço crítico informado. A análise automática considera ambos os sinais de flexão, mas não representa diagramas não uniformes nem condições particulares de contenção; nesses casos o usuário pode substituir os valores manualmente. Uma classificação modal indisponível mantém a verificação pendente. Um modo só é omitido se declarado ausente por análise geral (C.2). |
| U/C/Z simples/Z45/Z90 formados: cortante Z | Alma única sem enrijecedores transversais, com os ramos de 9.8.3 e interação com momento Y de 9.8.4 | Largura plana e limites gerais são conferidos. Os cortantes Y e Z continuam independentes. |
| Formados: cortante Y, torção; L/Cartola: cortante Z | Identificação da solicitação e pendência explícita | Não se aplica kv=5 de uma alma apoiada a abas livres, nem se presume divisão do cortante entre duas almas. Torção/empenamento exigem procedimento próprio. |

O MRD usa propriedades brutas e reduções de resistência próprias desse método; não acrescenta uma segunda redução por largura efetiva. Relações largura/espessura fora da cobertura de 9.1.2/Tabela 4 impedem o cálculo aplicável. Para compressão do Z simples, a cobertura da alma sem enrijecedores foi limitada conservadoramente a b/t de 90; não se afirma que isso substitua uma justificativa específica para ampliar o domínio desse perfil.

As verificações tratam da resistência das barras sob as solicitações representadas. Não incluem dimensionamento de ligações, esmagamento local por forças concentradas, furos/recortes na flexão, fadiga, incêndio, vibrações ou verificações de serviço. A análise geral e as contenções devem representar as condições efetivas do projeto.

## Geometria, análise e compatibilidade

- Z simples, Z45 e Z90 são famílias distintas. Z45/Z90 usam d, bf, c, t e raio interno r, sem séries comerciais inventadas.
- U/C/Z simples/L/Cartola formados usam a mesma geometria arredondada no desenho e nas propriedades da análise. Nessas famílias legadas o raio é r=t; um raio diferente não é silenciosamente ignorado.
- As dimensões legadas foram preservadas. No C, a projeção total do enrijecedor inclui c+t; no Z simples, bf parte da face externa da alma. Elas não devem ser confundidas com as dimensões externas c e bf dos novos Z45/Z90.
- O produto de inércia foi corrigido. A análise usa inércias/eixos principais e transforma cargas locais e resultados de volta aos eixos geométricos. Ligações liberadas de modo incompatível com essa transformação são recusadas explicitamente.
- Resultados salvos com a convenção/propriedades anteriores permanecem no arquivo, mas ficam desatualizados e exigem novo processamento. Os dados do modelo não são substituídos nem reinterpretados como outra família.

## Fluxo e estados

Os esforços críticos globais informados do MRD e as declarações de modo ausente ficam associados às condições físicas do modelo. Alterações de geometria, material, apoios ou cargas que mudem essas condições removem esses valores, inclusive declarações de modo ausente; é necessário informar os resultados da nova análise elástica. Os esforços locais e distorcionais automáticos são recalculados pela geometria/material atuais; valores manuais substitutivos continuam sujeitos à invalidação. Agrupar/desagrupar também remove os dados das barras afetadas, pois o elemento de estabilidade mudou. An/Ct e as demais propriedades manuais permanecem independentes dessa invalidação. A reabertura conserva os dados do MRD somente quando a assinatura física salva corresponde ao modelo.

O worker continua recebendo uma cópia privada do modelo e devolvendo resultados para aplicação na thread da interface. Agrupamento, revisão do modelo, propriedades de cálculo, contenções e troca de resultados continuam participando do controle de validade.

Quando as combinações estão cadastradas, as resistências usam as classificadas como ELU. ELS/CAR não substituem ELU; a ausência de classificação ou de um resultado ELU esperado impede a aprovação global. Resultados fornecidos diretamente à API sem cadastro de combinações são tratados como solicitações de cálculo informadas pelo chamador.

O comando de restaurar estimativas automáticas afeta apenas comprimentos e Cb. Dados necessários de ligação, Lv e estabilidade não provocam essa pergunta e não são apagados por ela. Os slots de conclusão da verificação são explicitamente registrados no Qt para entrega à thread gráfica.

Para W/HP, I e U laminados, o Cb automático é calculado conforme a NBR 8800:2024, 5.4.2.3(a), a partir dos momentos absolutos em Lb/4, Lb/2 e 3Lb/4 e do máximo amostrado no intervalo Lb governante que o programa já determina geometricamente. O menor Cb entre combinações com momento é usado na resistência compartilhada pelo elemento; o usuário pode manter um Cb manual. O método de identificação de comprimentos não foi alterado e continua sem avaliar rigidez, resistência, ligações ou ancoragem das contenções. Se Lb for digitado manualmente como escalar, sem indicar onde está o trecho no diagrama, o Cb volta a 1,0; também há retorno conservador a 1,0 se faltarem amostras para cobrir o intervalo. Cargas fora da semialtura e as condições especiais de 5.4.2.3(b/c) e 5.4.2.4 não são reconhecidas automaticamente.

Amostras precisam conter posição, normal, dois momentos, dois cortantes e torsor, todos finitos. Materiais e geometrias também passam por validação. As interações usam a mesma combinação, barra e posição. Força normal negativa continua significando tração.

`checked`, `not_applicable` e `not_checked` permanecem distintos. Uma pendência obrigatória impede aprovação. Uma reprovação calculada permanece visível mesmo havendo outra verificação pendente. O painel, a cena e a memória apresentam essa distinção.

## Entradas e memórias

O painel existente ganhou An/An0, Ct explícito, LvY/LvZ e esforços críticos do MRD:

- NcrG, em kN (informado); NcrL/NcrD, em kN (automáticos por padrão);
- McrGy/McrGz, em kN·m (informados); McrLy/McrDy e McrLz/McrDz, em kN·m (automáticos por padrão);
- ∅ registra ausência comprovada de um modo; campo em branco significa informação ausente.

Para flexão, os esforços críticos informados devem representar a envoltória mínima dos sinais e diagramas de momento aplicáveis, para a seção, contenções e comprimentos efetivos do elemento. Grupos exigem os mesmos dados em suas barras. Valores de resistência de cálculo não podem ser fornecidos no lugar desses esforços críticos elásticos.

Os casos governantes dos laminados também identificam barra e posição. A localização vem do registro do cálculo ou de uma amostra que corresponda às solicitações usadas, sem recalcular resistências; falha de rastreamento impede aprovação global.

As novas memórias consomem as etapas armazenadas pelo cálculo: referência, equação, substituição, parâmetros, resistência, índice, modo e caso governante. Preservam as quatro seções principais, tipografia, cores e equações SVG. O DOCX mantém equações OMML editáveis e centralizadas; as expressões longas são divididas para caber na página.

## Evidência de validação

A suíte focada abrange propriedades e contornos, tabelas da NBR 6355, cantilevers com flexão não simétrica e cargas locais/globais, famílias novas, laminados, regressão das três barras maciças, contenções, persistência, grupos, entradas inválidas, sinais, interações, estados, interface, exportação e execução assíncrona.

Referências independentes incluem integração numérica dos módulos plásticos de tubos arredondados, áreas de dobras circulares por integração geométrica, deflexão acoplada de cantilever e cálculos numéricos dos ramos normativos. Os testes não acessam a pasta dos PDFs.

A conferência visual usa exportações reais do programa para W, L, T, tubular circular/retangular, C, Z45 e Z90. Foram examinadas as 51 páginas renderizadas e corrigidos cortes de expressões no Word e a rolagem horizontal dos novos campos. A conferência adicional das coordenadas de palavras no PDF não encontrou conteúdo fora das margens nesses oito casos.

Antes da automação de Cb, **355 testes passaram em 26 arquivos** nos três processos focados descritos na validação da implementação inicial; esse número não representa uma execução de toda a suíte nem substitui a validação abaixo da versão atual.

Após a automação de Cb, **50 testes direcionados** para W/I/U laminados, validações e propriedades de cálculo passaram em 15,43 s, incluindo o cálculo automático, o override manual, o Lb manual sem localização do trecho, a inversão de curvatura entre amostras e a equação na memória. Após aplicar o mesmo tratamento às limitações de torção, flexão e cortante dos laminados, **48 testes de W/U/L/T passaram em 18,54 s**; eles conferem que as lacunas de escopo não bloqueiam as verificações cobertas e são descritas na memória. `compileall`, `git diff --check` e Ruff nos módulos afetados passaram. Uma execução ampla com `pytest tests -x -q` passou por 245 testes e parou em `tests/test_detailing_performance.py::test_sheet_linework_upgrade_keeps_annotation_and_rejects_stale_results`, que chama `_sheet_linework_upgraded` sem o argumento obrigatório `success`; essa falha é alheia às rotinas de verificação de perfis e continua pendente.

Uma execução anterior reunindo testes gráficos sofreu encerramento nativo com `Bus error` em Qt/VTK no modo offscreen. A execução isolada passou; isso não comprova a eliminação da instabilidade nativa no processo agregado. Os slots de entrega à interface foram registrados explicitamente no Qt.

`compileall` e `git diff --check` passaram. A comparação do Ruff dos 52 arquivos Python alterados com HEAD não encontrou novos apontamentos; 45 apontamentos já existentes nesses arquivos permanecem fora do escopo.

### Referências de conferência reproduzíveis

| Conferência | Fonte e entradas | Resultado e tolerância |
| --- | --- | --- |
| Propriedades Z45/Z90 | NBR 6355:2012, tabelas A.4/A.5; 100 × 50 × 17 × 2 mm, raio interno 2 mm | Z45: A=4,51 cm², Iy=73,48 cm⁴, Iz=34,91 cm⁴, Iyz=38,52 cm⁴. Z90: 4,42; 70,26; 28,27; 33,95. Tolerância relativa 0,2%, considerando arredondamento tabular e discretização dos arcos. |
| Módulos plásticos tubulares | Tubo 100 × 200 × 5 mm, raios externo/interno 10/5 mm | Integração numérica independente das faixas horizontais e verticais, comparada à expressão fechada; tolerância relativa 10⁻⁹. |
| Tração dos formados | NBR 14762:2010, 9.6.2; Ag=10 cm², fy=25 kN/cm², fu=40 kN/cm² | Casos independentes governados por escoamento (250/1,10 kN), ruptura fora da ligação (200/1,35 kN) e na ligação (224/1,65 kN); comparação numérica com tolerância relativa padrão do pytest, 10⁻⁶. |
| MRD de compressão | NBR 14762:2010, C.3; Ny=100, Ne=25, Nl=10, Nd=40 kN | Conferência independente dos três modos e γ=1,20, além dos ramos e transições de flexão de C.4; tolerância relativa 10⁻⁶. Os números são exemplos numéricos de conferência, sem atribuição de publicação bibliográfica. |
| Eixos principais | Cantilever elástico com seção não simétrica, versões espelhadas e cargas locais/globais | Deflexão analítica acoplada usando Iy, Iz e Iyz; equilíbrio de forças e momentos. As hipóteses e tolerâncias estão nos testes de Z enrijecido. |

Esses exemplos usam as edições adotadas, sem transportar coeficientes de exemplos históricos. Não há dependência dos PDFs para executar os testes.
