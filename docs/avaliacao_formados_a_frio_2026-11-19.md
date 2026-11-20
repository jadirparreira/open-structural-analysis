# Perfis formados a frio: avaliação e roteiro de conclusão

Avaliação de 19/11/2026 sobre os arquivos presentes na árvore de trabalho, incluindo alterações ainda não commitadas. A avaliação inicial definiu as pendências abaixo. A primeira implementação posterior está registrada na seção seguinte; os achados iniciais foram preservados como evidência do estado anterior.

## Desenvolvimento posterior — estado atual

Esta seção substitui o estado de cobertura da avaliação inicial; o histórico abaixo permanece identificado como anterior. **O objetivo completo continua em desenvolvimento.**

| Frente | Implementação e evidência | Limite restante |
| --- | --- | --- |
| Geometria de paredes finas | Linha média explícita com trechos planos, raios, tangentes e integração; preservação das convenções geométricas legadas. | A migração para dimensões comerciais externas continua separada da compatibilidade dos projetos antigos. |
| Faixas finitas | Quatro pontos de Gauss; 140 espectros comparados com referência numérica independente; refinamento logarítmico dos mínimos. | A classificação automática por deformada ainda requer aprofundamento para modos mistos; ausência de modo não identificado não é tomada como dispensa. |
| Estabilidade global | Cw/centro de torção e equação acoplada de compressão; flexão elástica com garfos, empenamento livre e carga no centro de torção declarados. KL1/KL2/KLt ou críticos externos. | Condições de contorno/carregamento diferentes exigem análise própria. |
| MLE | Elementos AA/AL, gradientes, enrijecedor simples e iteração de seção efetiva. Exemplos 04/07 do manual conferidos com conversão explícita das dimensões. | Na mesa com gradiente, despreza-se conservadoramente a contribuição favorável do enrijecedor de borda; não se anuncia identidade entre MLE e MRD. |
| Serviço | Matriz normal completa: 3×3 na cantoneira Cw=0, com polo efetivo atualizado, e 4×4 nos demais perfis, incluindo bimomento. Linha média arredondada, interseção das faixas efetivas, redistribuição estrutural e comprovação elástica conjunta por limite superior. | O caminho centroidal de seis GL serve à inspeção e não aprova ELS de formados. Exige ativar a análise dos formados e declarar vínculos A/B quando há modo setorial. Não convergência ou ausência de comprovação elástica impedem concluir o ELS. |
| Forças concentradas | Anexo D, Tabelas D.2–D.4; cadastro de contato, distância à extremidade física, ligação, mesas carregadas e força ELU por alma. Persistência e invalidação por assinatura física. | Cadastro usa forças de cálculo declaradas como envoltória; não determina a partilha entre almas nem dimensiona o dispositivo de transferência. A revisão de todos os apoios e forças aplicadas é explícita. |
| Segunda ordem e imperfeições | P–Delta; EA/EI=0,8 nos ELU; cadastro das contribuições gravitacionais por nó/nível e ELU; quatro casos nocionais explícitos por ELU; classificação por deslocamento relativo à base com a mesma rigidez nas duas análises; verificação positiva da rigidez tangente. | Modelo de barras de aço, com níveis/base declarados. Não inclui não linearidade geométrica de placas ou pilares mistos. Outras verificações de resistência, contenções e ligações permanecem separadas. |
| Torção/empenamento | Análise estrutural 7 GL integrada, linear e P–Delta por força normal; opção de análise e vínculos A/B na interface. Núcleo elástico: solução exata por trechos de T linear, empenamento livre/impedido, bimomento, parcela Saint-Venant, fluxo de cisalhamento e tensões combinadas. Reproduz o exemplo Z 200×50×3 do Anexo A do manual. | **Ainda não integrado como resistência ELU da barra.** A distribuição elástica já usa a rigidez de empenamento e as excentricidades; faltam a resistência, a estabilidade sob as tensões combinadas e suas interações. O check de torção solicitante permanece pendente. |
| Cortantes | Rotina 9.8.3 e interação 9.8.4; integração da partilha vertical por alma na cartola, ligada ao check e ao memorial; recuperação geral do fluxo elástico dos dois cortantes. | Faltam resistência das abas livres/cortante Y e domínio do L. Cartola com Vy/torção concomitantes exige superposição dos fluxos. Recuperação elástica de tensões não é resistência de flambagem por cisalhamento. |

Validação mais recente desta sequência:

- **692 testes aprovados em 79,03 s** na bateria consolidada de formados, faixas finitas, serviço, torção, análise Vlasov, segunda ordem, nocionais, propriedades, interface e persistência.
- Na etapa anterior, **65 testes aprovados em 17,85 s** nos módulos de seção efetiva acoplada/serviço/adaptador e **112 aprovados em 30,85 s** depois da identificação da versão do algoritmo, incluindo verificação de barra. Há sobreposição; os conjuntos não devem ser somados.
- Conferência independente de fluxo, deslocamentos e reações no sistema hiperestático de duas seções; comprovação de que torque nulo no centroide não dispensa torção excêntrica e de que Saint-Venant não pode escapar da hipótese elástica por ter tensão normal nula.
- Após a bateria consolidada, **7 testes de interface aprovados em 2,87 s**, incluindo o novo editor de bimomentos (duas verificações adicionais). Os conjuntos têm sobreposição e não se somam.
- Inspeção visual real dos diálogos de contato/vínculos e do memorial Qt com a matriz normal 4×4, equações e limites de tensão/escopo. Entradas e persistência testadas.
- A execução anterior mais ampla de `test_pynite_adapter.py` encontrou falhas em mocks do renderizador de placas: o objeto simulado não implementa `SetObjectName`. Essas falhas são externas aos cálculos novos e não foram ocultadas nem corrigidas alterando o escopo desta tarefa.

A aprovação global do elemento continua impedida por verificações necessárias sem dados ou sem implementação. Não se deve declarar concluído o dimensionamento completo apenas porque as resistências MRD ou a solução P–Delta convergiram.

## Complemento atual do serviço e da cantoneira

O algoritmo `vlasov-7gl-3` registra três ou quatro campos, a matriz efetivamente aplicada, sua origem e o polo. O ELS usa `coupled-normal-width-global-1`: cada atualização das faixas é seguida pela nova solução estrutural, em vez de convergir larguras com reações artificialmente fixas. O limite é 100 iterações, com tolerância relativa 10⁻⁶ para a matriz (energia) e o polo. A auditoria de tensões usa os esforços e a matriz finais efetivamente processados.

No L, as inclinações auxiliares de torção são internas a cada elemento finito, permitindo descontinuidade de θ′ em torque concentrado, sem impor continuidade setorial fictícia. B e Tw permanecem nulos. A integração independente do fluxo confere as resultantes e o torque nulo em torno do polo efetivo; ensaios adicionais cobrem compressão com flexão impedida e segunda ordem.

Resultados acoplados incompletos, não finitos ou com TSC ≠ Tsv+Tw são rejeitados tanto no ELU como no ELS, mesmo preservando o registro de rigidez convergida. Registros escalares antigos exigem reprocessamento na nova rota. A comprovação é do modelo elástico de parede fina e pequenas rotações; não constitui resistência ELU à torção ou análise geométrica não linear geral.

O menu de análise passou a oferecer **Bimomentos nas extremidades…**. O editor cadastra/revisa/remove a ação em kN·m² por barra, extremidade e caso de carga, mostra o nó correspondente e explica os sinais A/B. Rejeita duplicidades, valores não finitos e edição sobre modelo alterado. A gravação preserva outras cargas e invalida os resultados somente quando há mudança. Os diálogos e o memorial real do L (matriz 3×3, polo e limite equivalente) foram renderizados e conferidos visualmente.

## Histórico do desenvolvimento anterior

As seções seguintes registram etapas anteriores. Para cobertura atual, prevalecem a tabela e o complemento acima.

## Cortante da cartola e análise com empenamento — desenvolvimento posterior

- A cartola passou a verificar Vz com a resultante integrada em cada alma. A integração do fluxo é exata para os trechos retos do modelo de parede fina; os esforços da zona de dobra são atribuídos às almas, e a resistência usa apenas a largura plana. A partilha 0,5/0,5 é recuperada pelo cálculo da seção simétrica, não fixada como entrada. Os coeficientes, resistências por alma e resistência global aparecem no memorial. O cálculo fica pendente se houver Vy, torção ou empenamento concomitante que exija superposição ainda não ligada ao check. Parcelas Saint-Venant/empenamento opostas não são ignoradas só porque sua resultante torsional se anula.
- O núcleo elástico de torção inclui a rigidez condensada de extremidade para empenamento livre/impedido, cargas equivalentes consistentes e transformação transversal centroide–centro de torção. Foram conferidos o trabalho virtual, a torção causada pela aplicação da carga no centroide e a flecha adicional correspondente. O tratamento numérico das barras curtas usa expansão da função de forma, conferida com aritmética decimal de alta precisão.
- Foi acrescentado um elemento de Vlasov de 7 graus de liberdade por nó (`osa/analysis/vlasov.py`), com empenamento independente, produto de inércia, excentricidade do centro de torção, energia elástica e rigidez geométrica por tensões normais iniciais. As comparações cobrem os seis movimentos rígidos, carregamento consistente, resposta analítica de torção/flexão e os críticos de compressão e flexão nas sete famílias.
- **O elemento foi integrado ao adaptador estrutural**, com opção de análise, cadastro físico dos vínculos, continuidade, cargas consistentes, recuperação dos esforços e P–Delta por força normal. A resistência ELU à torção/bimomento permanece em desenvolvimento. O MLE acoplado de serviço foi integrado posteriormente, com o escopo e as pendências indicados abaixo. Os resultados elásticos não são apresentados como aprovação dessas resistências.

Evidência: **480 testes aprovados em 36,18 s** na bateria consolidada; após o refinamento numérico das funções de forma, **84 testes aprovados em 1,11 s** nos dois módulos do núcleo. Esses números têm sobreposição; não devem ser somados como conjuntos distintos.

A NBR 14762:2010, 8.4.2, estabelece dimensionamento por ensaios para casos não previstos. O desenvolvimento dos cortantes em elementos AL precisa preservar essa distinção; o coeficiente de alma apoiada não será apresentado como solução normativa de uma aba livre.

## Seção efetiva com empenamento — núcleo acoplado

Foi desenvolvido o campo setorial contínuo dos arcos da linha média e um MLE com quatro esforços concomitantes (N, My, Mz e bimomento). O núcleo preserva a matriz normal/setorial 4×4 após a redução de largura; o elemento Vlasov já aceita essa matriz e recupera os esforços acoplados. **O núcleo foi posteriormente integrado ao ELS de produção dos perfis com modo setorial:** geometria e polo comuns, matriz normal completa e iteração estrutural. A integração foi posteriormente estendida à cantoneira Cw=0, conforme o complemento atual acima. O caminho legado foi retirado da aprovação ELS.

A bateria dessa frente aprovou **138 testes em 8,98 s**, com integrações e solução por transferência matricial independentes, além das regressões dos núcleos, adaptador e serviço. A página 88 do manual (PDF 89) foi conferida visualmente para as definições setoriais e tensões do Anexo A. O roteiro detalhado da integração e as pendências atuais estão em `docs/projeto_integracao_vlasov_2026-11-19.md`. Esses ensaios têm sobreposição com os conjuntos anteriores e não comprovam a integração ELS do aplicativo.

## Imperfeições e estabilidade — integração posterior

Foi acrescentado um caminho operacional de análise global para modelos de barras de aço:

- Cadastro de cada nó resistente do nível, seu nó de referência **na base da estrutura**, e contribuição gravitacional de cálculo aplicada no nível em cada ELU base. Não se utiliza a força normal acumulada dos pilares como carga gravitacional aplicada no pavimento.
- Geração inspecionável de forças nocionais de 0,3% em ±X e ±Y separadamente, com quatro combinações adicionais por ELU. As nocionais também são adicionadas às combinações com vento. A aba “Casos gerados” mostra as forças efetivamente registradas nas ações do projeto.
- Ativação do procedimento com EA/EI=0,8 e P–Delta nos ELU; ELS mantém a rotina de seção efetiva e não recebe a redução de material de 0,8.
- Primeira e segunda ordem comparadas com a mesma rigidez reduzida; classificação conservadora por envoltória de todos os sinais e ELU, inclusive aqueles que poderiam ser dispensados pelo critério de sentidos de 4.10.4.6. Grande deslocabilidade exige a opção expressa do responsável pelo procedimento alternativo de 4.10.7.2.
- Verificação da positividade da rigidez tangente nos graus de liberdade livres, após a convergência P–Delta. Impede aceitar um equilíbrio algébrico elástico pós-crítico. Para sistemas menores usa Cholesky; para maiores, o menor autovalor da matriz simétrica escalada.
- Assinatura física das ações derivadas: alterações de geometria, apoios, cargas ou combinações exigem revisar o cadastro e regenerar as nocionais. A substituição não acumula casos. Dependências de combinações personalizadas impedem excluir/substituir suas ações silenciosamente.
- Check de procedimento no worker dos formados, calculado uma vez por verificação do modelo. O memorial identifica as combinações, classe, deslocamentos de primeira/segunda ordem e amplificações por ponto de controle.

**Leitura normativa explícita:** o PDF da NBR 8800:2024 corrigida, 4.10.4.5, remete a 4.10.3.3 ao mencionar imperfeições de material, embora a subseção referida trate de imperfeições geométricas de contenções. A implementação segue a redação de 4.10.4.5 para os limites 1,13/1,55 e a redução de material de 4.10.7.1.2. Essa interpretação e a remissão do PDF são identificadas na memória, sem alteração silenciosa da referência.

Validação desta integração:

- Bateria consolidada: **437 testes aprovados em 35,77 s**.
- Regressão adicional de persistência, semirrígidos, rotação e exportação: **85 testes aprovados em 11,15 s**.
- Casos novos com geração nos quatro sentidos, preservação dos fatores ELU, equilíbrio das ações, amplificação analítica de barra comprimida/fletida, grande deslocabilidade, impedimento pós-crítico, persistência, invalidação, regeneração, integridade dos dados e interface.
- Teste completo com perfil C: análise → worker → memória. O procedimento global atendido não oculta a ausência de ELS nem as outras verificações pendentes.

O fechamento integral da tarefa permanece pendente da resistência ELU à torção/empenamento e estabilidade/interações sob essas tensões, da resistência dos cortantes ainda sem domínio implementado. A classificação modal em faixas finitas continua sendo objeto de aprofundamento; o progresso desta seção não declara concluídas essas frentes.

## Continuidade: correções implementadas em 19/11/2026

- **Tensões das faixas finitas:** removida a segunda translação pelo centroide. A linha média discretizada é centrada pelas suas próprias integrais; os campos de referência são normalizados pela integração exata dos trechos da malha, recuperando N, My e Mz solicitados. Isso também elimina a mistura entre propriedades do contorno maciço e integrais da malha na normalização das cargas.
- **Espelhamento:** propriedades e malha usam a mesma orientação. A normalização dos esforços considera o produto de inércia da própria malha; reflexões preservam o espectro elástico nos casos conferidos.
- **Esbeltez de compressão:** incluído um check independente de resistência pelo MRD, com limite 200 e raios dos eixos principais. Um resultado acima do limite participa da reprovação; a ausência dos dados necessários impede aprovação.
- **Entradas KL1/KL2:** novos campos em metros para os comprimentos efetivos K₁L₁/K₂L₂ nos eixos principais maior/menor. Não há K automático presumido. Valores positivos são validados, persistidos e exigidos de forma consistente nos grupos. Alterações físicas do modelo invalidam os valores pelo mesmo mecanismo de proveniência dos esforços críticos. Restaurar estimativas geométricas não os apaga.
- **Tração:** a recomendação L/r≤300 aparece na memória como aviso, sem alterar a resistência calculada. Ly/Lz ficam disponíveis para os comprimentos destravados. Quando os eixos principais são inclinados, o aviso identifica a estimativa conservadora com max(Ly,Lz)/r₂.
- **Memória:** as etapas mostram raios principais, comprimentos efetivos, índices de esbeltez e a recomendação de tração. As demais verificações de resistência permanecem separadas do novo limite geométrico.

Validação desta etapa: **273 testes aprovados em 16,86 s**, nos dez arquivos indicados abaixo, na execução final. Incluem 70 casos de equilíbrio dos campos unitários (sete famílias, espelhamento e sinais), comparação dos espectros após reflexão, convergência para a solução clássica de uma placa simplesmente apoiada, regressões de esbeltez, persistência, grupos, campos da interface e memória. Para a placa, foram conferidas meias-ondas de 50, 100 e 200 mm e malhas de 8, 16 e 32 faixas; o erro relativo final exigido é inferior a 10⁻⁵.

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/opensa-pff-audit/mpl \
  .venv/bin/python -m pytest -q \
  tests/test_cold_formed_fsm.py tests/test_cold_formed_member.py \
  tests/test_cold_formed_tension.py tests/test_calculation_properties_panel.py \
  tests/test_z_stiffened_sections.py tests/test_section_properties.py \
  tests/test_verification_restraints.py tests/test_persistence.py \
  tests/test_project_loading.py tests/test_memorial_docx_export.py
```

`compileall` e `git diff --check` passaram. Ruff passou nos módulos de verificação, proveniência, painel, renderização da memória e testes específicos dos formados. Os apontamentos já existentes em `domain/model.py` e `tests/test_calculation_properties_panel.py` não foram tratados nesta etapa.

**Limites desta entrega:** não conclui a validação da classificação modal local/distorcional, da recuperação geométrica da linha média ou da busca de mínimos da assinatura. O ensaio analítico de placa verifica a formulação das faixas, não certifica isoladamente todos os críticos de perfis dobrados. Estabilidade global automática, MLE, ELS, cortantes ainda não cobertos, forças concentradas e torção/empenamento continuam pendentes. Projetos anteriores precisam executar novamente a verificação; compressão sem KL1/KL2 ficará pendente até esses dados serem fornecidos.

## Conclusão da avaliação inicial

O OpenSA já possui uma base relevante de dimensionamento de barras abertas pela NBR 14762:2010. Há tração, resistência direta de compressão e flexão, cálculo elástico por faixas finitas, cortante em alma única e interações. Entretanto, a implementação ainda não deve ser considerada concluída: existem erros no campo de tensões que alimenta as faixas finitas, falta verificação de esbeltez das barras formadas, a estabilidade global depende de entradas externas e não há verificação de serviço com rigidez efetiva.

Recomenda-se corrigir e validar a base atual antes de ampliar famílias ou declarar cobertura geral. Implementar o Método das Larguras Efetivas (MLE) é uma boa segunda rota para acompanhar o manual, mas não é uma obrigação adicional para uma implementação válida do Método da Resistência Direta (MRD). São alternativas previstas em 8.4.1; não se devem aplicar as duas reduções de flambagem local cumulativamente.

## Referências adotadas

| Documento | Papel na avaliação |
| --- | --- |
| ABNT NBR 14762:2010, arquivo fornecido pelo usuário | Dimensionamento: materiais, limites geométricos, tração, compressão, flexão, cortante, interações, deslocamentos e situações especiais. |
| ABNT NBR 6355:2012, arquivo fornecido pelo usuário | Padronização, nomenclatura, dimensões e propriedades geométricas; não substitui a norma de dimensionamento. |
| Silva, Pierin e Silva, *Estruturas compostas por perfis formados a frio*, Instituto Aço Brasil/CBCA, 2014 | Desenvolvimento pelo MLE, exemplos resolvidos e discussão de instabilidade, torção e propriedades setoriais. |

As edições são as solicitadas. Esta avaliação não certifica a vigência atual de todas as referências normativas do projeto. A apresentação e a base normativa do manual também foram conferidas no [acervo oficial do CBCA](https://www.cbca-acobrasil.org.br/site/biblioteca/?bsc=ativar&bscPgn=2&bscQtdReg=10&chkCat%5B%5D=7&txtBscKeyword=).

Foram extraídos os textos e conferidas visualmente páginas relevantes: NBR 14762, páginas impressas 25 e 77; NBR 6355, página impressa 11; manual, página impressa 51. As demais referências de itens abaixo foram examinadas no texto extraído, sem reproduzir integralmente os documentos no repositório.

## Cobertura encontrada na avaliação inicial

| Verificação ou recurso | Situação atual | Falta para concluir |
| --- | --- | --- |
| Famílias abertas | U, C/U enrijecido, Z simples, Z45, Z90, L e cartola registrados. | Delimitar cobertura por família, solicitação e contenção; registro no worker não equivale a cobertura integral. |
| Geometria bruta | Contornos arredondados, área, inércias, produto de inércia e eixos principais; há comparações tabulares para U e Z45/Z90. | Uniformizar convenções dimensionais e ampliar validação de C/Ue, L e cartola. Completar propriedades setoriais para estabilidade global. |
| Tração — 9.6.2 | Três resistências, com coeficientes próprios da norma. | An, An0 e Ct ainda dependem do usuário. Automatização exige representar furos e ligação; não se deve supor área líquida igual à bruta. Falta recomendação de esbeltez de 9.6.3. |
| Compressão por MRD — C.3 | Curvas de resistência e coeficiente 1,20 implementados. | Ne/NcrG externo, classificação modal e validação numérica independente; falta limite KL/r de 9.7.4. |
| Flexão por MRD — C.4 | Curvas global, local e distorcional; coeficiente 1,10; dois eixos e envoltória dos sinais. | Corrigir tensões das faixas finitas, espelhamento e normalização. Me/McrG externo; representar domínio de contenções e diagrama. |
| Flambagem local e distorcional | Solução própria por faixas finitas, com substituição manual e indicação da meia-onda. | Demonstrar precisão, convergência e separação modal. Modo não identificado não comprova ausência física. |
| Limites b/t — 9.1.2 | Bloqueio de parte das extrapolações da Tabela 4. | Consolidar larguras planas por elemento, direção de tensões e domínio; distinguir limites adotados conservadoramente de limites expressos da norma. |
| Cortante Z — 9.8.3 | Alma única sem enrijecedores transversais de U/C/Z; três ramos. | L e cartola sem procedimento. Não há modelo de enrijecedores transversais. |
| Cortante Y | Pendente quando solicitado. | Distribuição de tensões e procedimento específico para as paredes participantes. |
| Momento–cortante — 9.8.4 | Interação My–Vz, com esforços na mesma seção. | Outras configurações e interação para almas enrijecidas, se essas passarem a ser suportadas. |
| Flexão composta — 9.9 | Soma dos índices com esforços concomitantes; normal constante exigida. | Validar agrupamentos, eixos e sinais; garantir que os esforços venham de análise estrutural apropriada. |
| Torção aplicada/empenamento | Pendente quando há torsor amostrado. | Centro de torção, Cw, coordenadas setoriais, vínculos ao empenamento, bimomento e tensões combinadas. |
| ELS — 9.8.5 / C.5 e Anexo A | Não integrado ao verificador de formados. | Rigidez efetiva nas combinações de serviço, deslocamentos e respectivos limites. |
| Forças concentradas — Anexo D | Não verificadas. | Comprimento de apoio, posição da força, número de almas e mecanismos locais; entradas próprias para aplicar o procedimento. |
| Ligações e barras de perfis associados | Sem dimensionamento específico nesta rotina. | Seção 10; 9.7.5 e 9.8.6 quando incluídos no escopo. Agrupamento longitudinal de barras não representa associação de perfis na seção. |
| Materiais — seção 4 | Propriedades positivas e fu/fy mínimo conferidos. | Qualificação, ductilidade e condições dos aços sem qualificação não podem ser certificadas apenas pela razão fu/fy. |

Arquivos centrais: `osa/verification/cold_formed.py`, `cold_formed_member.py`, `cold_formed_fsm.py`, `osa/sections/properties.py`, `osa/sections/geometry.py` e `osa/ui/verification_worker.py`.

## Achados prioritários da avaliação inicial

### P1 — Coordenadas das tensões nas faixas finitas

Em `cold_formed_fsm.py:214`, `_stresses()` subtrai `centroid_y_mm` e `centroid_z_mm` dos pontos da linha média. Esses pontos vêm de `section_shape()`, cujo contorno já é centrado no centroide (`geometry.py`, construção de `centered_loops`). As propriedades guardam o centroide do contorno original como metadado. A segunda translação cria uma parcela uniforme de tensão indevida em perfis cujo centroide original não está na origem.

Conferência reproduzida com `FiniteStripSection('C Formado', {'d':100., 'bf':50., 'c':15., 't':2.})`: para `Mz=1 N·mm`, a integração das tensões na linha média resulta em aproximadamente **−0,01944 N de força axial**, embora o caso solicitado seja flexão pura. Usando diretamente as coordenadas já centradas, o resíduo fica aproximadamente **+0,000328 N** nessa mesma discretização. Esse resíduo restante também precisa ser controlado por convergência/normalização; a simples remoção da segunda translação não encerra a validação.

Consequência: os momentos críticos automáticos alimentam o MRD com um campo de tensões diferente do pretendido. A direção do erro na resistência não foi estabelecida para todos os casos; não cabe presumir conservadorismo.

Critério de fechamento: comprovar força axial nula e os dois momentos resultantes corretos para cargas unitárias My/Mz, com tolerância definida e convergência da malha, antes de validar as curvas críticas.

### P1 — Espelhamento incompatível entre malha e propriedades

Em `cold_formed_fsm.py:203` a linha média recebe `mirror`; em `:207` as propriedades são calculadas sem `mirror_z`. Assim, para Z e L, o produto de inércia usado no campo de tensões não acompanha o espelhamento da seção.

Conferência com Z90, d=100, bf=50, c=17, t=r=2 mm, integrando o campo solicitado `My=1 N·mm, Mz=0`:

| Configuração | My recuperado (N·mm) | Mz recuperado (N·mm) |
| --- | ---: | ---: |
| Sem espelhamento | 0,9580 | −0,00794 |
| Espelhado | 3,6515 | 2,2370 |

Os resíduos da primeira linha já exigem estudo de discretização; a segunda mostra uma incompatibilidade adicional de orientação. A envoltória dos sinais do momento não resolve essa troca do campo espacial de tensões.

Critério de fechamento: propriedades, malha e cargas na mesma convenção; reflexão da geometria e transformação correspondente dos esforços devem preservar o problema físico e a resistência.

### P1 — Esbeltez das barras formadas não participa da aprovação

O worker chama verificações de esbeltez para W/I/U/L/T laminados, mas não para as famílias formadas (`verification_worker.py:384–390`). A rotina dos formados também não cria esse check. A NBR 14762, 9.7.4, limita KL/r a 200 para compressão; 9.6.3 recomenda L/r até 300 para tração, com natureza diferente de exigência.

Foi reproduzido um C com d=100, bf=50, c=15, t=2 mm, L=6 m, normal de compressão de 0,01 kN e críticos manuais NcrG=100, NcrL=50, NcrD=80 kN. Para K=1, L/r usando o menor raio de giração resulta em **317,30**. O worker retorna **`checked`**, índice **0,00022667**, sem check de esbeltez. Os críticos desse caso são entradas artificiais de diagnóstico, não um dimensionamento físico de referência; o ensaio demonstra que a esbeltez não é conferida independentemente deles.

Critério de fechamento: comprimentos e eixos pertinentes explícitos, limite de compressão integrado ao resultado e recomendação de tração apresentada como recomendação. Para Z/L, não substituir automaticamente raios principais pelos raios dos eixos geométricos.

### P1 — Validação das faixas finitas ainda insuficiente

`signature()` usa 14 comprimentos por padrão. A busca automática procura mínimos interiores em ramos classificados por deslocamentos, com limiares heurísticos de 0,18 e uma exclusão de meias-ondas distorcionais menores que a dimensão da seção. Esses valores são escolhas numéricas, não critérios normativos de identificação modal.

Os testes atuais das faixas verificam existência e positividade de modos e os dois sinais do problema de flexão. Eles não comparam os valores críticos com uma solução independente. É necessário incluir convergência de malha, refinamento de mínimos, intervalo de meias-ondas, equilíbrio dos campos unitários, mudança de escala, espelhamento e casos de modos mistos/ausentes. A seleção de apenas parte do espectro também precisa ser avaliada ao acompanhar os ramos.

Critério de fechamento: conjunto de casos de referência com geometria, unidades, vínculos, tensões, resultados críticos e tolerâncias documentados. Não aceitar apenas “autovalor positivo”.

## Implementação recomendada após as correções

### 1. Consolidar a geometria de paredes finas

Criar uma representação explícita da linha média, com trechos retos e dobras, espessura, larguras planas, bordas livres/apoiadas e papel de cada parede. Ela deve alimentar propriedades, limites b/t, faixas finitas e, futuramente, seção efetiva.

Hoje a linha média é recuperada por pareamento das faces do contorno. É necessário verificar se esse processo preserva comprimento, dobras e equilíbrio para espessuras e proporções variadas. Uma linha média construída diretamente evita depender dessa recuperação.

Preservar compatibilidade dos projetos antigos: as convenções legadas de C e Z simples não equivalem automaticamente às dimensões externas padronizadas. A NBR 6355, Anexo A, adota método linear para as propriedades tabulares, com hipóteses próprias para Cw/centro de torção, e raio interno t até 6,3 mm, passando a 1,5t acima disso. Diferenças frente à integração do contorno maciço devem ser explicadas, não escondidas por tolerâncias amplas. A limitação r=t das famílias legadas precisa permanecer explícita até haver migração geométrica.

### 2. Automatizar estabilidade global com domínio declarado

Acrescentar centro de torção, Cw e parâmetros necessários às famílias suportadas. Para compressão, implementar as situações de 9.7.2.1 a 9.7.2.3: flexão, torção e flexo-torção, inclusive eixos principais e raiz da equação para seções assimétricas.

Para flexão, começar pelos casos cobertos por 9.8.2.2 e Anexo E, com vínculos, comprimentos e sinais representados. Não usar a fórmula de um perfil monossimétrico em qualquer Z/L ou em qualquer orientação. Os resultados podem alimentar o MRD apenas quando compatíveis com o caso elástico de C.2.

Manter os críticos externos como substituição explícita e rastreável. A detecção geométrica de contenção não comprova sua rigidez, resistência ou restrição ao empenamento. Nenhum modo deve ser omitido por ter faltado um mínimo na varredura.

### 3. Acrescentar MLE para seguir os exemplos do manual

Implementar, em sequência: elementos AA/AL com gradiente de tensão; enrijecedor de borda e seus limites; seção efetiva por trechos; atualização de área, centroide e inércias; iteração da distribuição de tensões em flexão; resistências globais e distorcionais conforme o método escolhido.

Não basta reduzir a área bruta por um fator único. Na flexão, a seção efetiva desloca a linha neutra; a mesa e o enrijecedor têm condições próprias. O MLE deve conservar um caminho de cálculo completo e separado do MRD.

Esse desenvolvimento permite conferir diretamente os exemplos do manual. A falta de MLE não invalida por si só a opção pelo MRD, e seus resultados não precisam coincidir exatamente quando os métodos fazem aproximações distintas.

### 4. Concluir cortantes, torção e efeitos locais conforme o uso

Para a cartola, calcular a parcela de cortante em cada alma em vez de impor uma divisão genérica. Para L e cortante transversal das outras seções, estabelecer distribuição de tensões e domínio próprios. Incluir as interações correspondentes.

Modelar excentricidade entre a aplicação de carga e o centro de torção. Hoje bloquear um torsor existente nas amostras não detecta um torque que o modelo estrutural deixou de gerar. Torção de Saint-Venant, empenamento e suas tensões combinadas requerem desenvolvimento além da resistência direta de compressão/flexão.

Para terças e vigas com apoio ou força concentrada, incluir o Anexo D com as entradas físicas necessárias. A ausência de enrijecedores transversais no modelo limita a ampliação dos ramos de cortante e das interações. Casos vinculados a telhas/painéis, se desejados, exigem também as condições específicas aplicáveis, como as do Anexo F; a vinculação não pode ser presumida.

### 5. Integrar ELS e análise estrutural apropriada

O adaptador atual chama `target.analyze()` (`osa/analysis/pynite/adapter.py:44`), sem uma chamada explícita de análise P-Delta nesse fluxo. Isso não demonstra o atendimento aos requisitos de estabilidade, imperfeições e segunda ordem de 8.1. É necessário definir as hipóteses e o tratamento da análise antes de considerar concluída a flexocompressão do sistema estrutural.

Para ELS, implementar a rigidez efetiva conforme 9.8.5 ou C.5, coerente com o método selecionado, e os limites pertinentes do Anexo A. Exibir deslocamento obtido com inércia bruta não substitui essa verificação. Separar estados de atendimento do ELU e do ELS e descrever claramente a cobertura no resultado.

## Validação sugerida com o manual

| Casos | Objetivo |
| --- | --- |
| Exemplos 01–03, pp. 44–45 | Tração, áreas líquidas e efeitos da ligação. |
| Exemplo 04, pp. 51–53 | Ue 100×50×17×1,2 mm, L=4 m: propriedades, flexo-torção e seção efetiva. O exemplo apresenta Ne≈9,57 kN. |
| Exemplos 05–06, pp. 53–56 | Comprimentos/contenções e alterações do modo governante na compressão. |
| Exemplos 07–08, pp. 62–70 | Flexão, seção efetiva, FLT e efeito do sinal/eixo. |
| Exemplo 09, p. 71 | Cortante e momento–cortante no perfil do exemplo 07. |
| Anexo A do manual | Centro de torção, propriedades setoriais e tensões de torção. |
| Exemplo de cobertura do Anexo D do manual | Integração final de análise, combinações, barras e deslocamentos; não confundir com o Anexo D da NBR 14762. |

Antes de comparar números, converter as dimensões externas da referência para a geometria efetivamente calculada no OpenSA e registrar os eixos. Comparar primeiro propriedades e esforços críticos; depois resistências. Nos exemplos pelo MLE, separar a validação de componentes comuns daquela do resultado final por método.

## Evidência desta avaliação

Comando executado:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_cold_formed_tension.py tests/test_cold_formed_member.py \
  tests/test_cold_formed_fsm.py tests/test_z_stiffened_sections.py
```

Resultado: **80 testes aprovados em 8,56 s**. Essa execução é focada; não é a suíte completa nem uma validação independente de todos os procedimentos normativos.

Os ensaios adicionais de diagnóstico foram executados em memória, sem alterar o motor: integração do campo unitário nas faixas e execução do worker com barra esbelta. Para reproduzir os resultantes, usar a malha e `_stresses()` de `FiniteStripSection` e integrar cada trecho com espessura t: força por trapézio e momento pelo produto exato das duas funções lineares (tensão e coordenada). As geometrias e os resultados estão nas tabelas dos achados.

Não foram copiados PDFs, extrações integrais ou imagens das referências para o repositório. As alterações preexistentes foram preservadas.

## Ordem de execução proposta na avaliação inicial

1. Corrigir coordenadas/espelhamento das faixas finitas, normalizar os campos e acrescentar referências independentes.
2. Integrar esbeltez dos formados e consolidar limites geométricos e cobertura apresentada ao usuário.
3. Completar propriedades setoriais e automatizar a estabilidade global nos casos com hipóteses controladas.
4. Implementar MLE, se mantida a intenção de acompanhar diretamente o manual, validando os exemplos gradualmente.
5. Integrar ELS com rigidez efetiva e definir o tratamento da análise estrutural de estabilidade/segunda ordem.
6. Concluir cortantes por família, forças concentradas e torção/empenamento conforme a prioridade dos modelos reais.
7. Desenvolver perfis associados, ligações e casos específicos de terças/telhas em escopos explícitos.

Para declarar a primeira etapa concluída, cada solicitação efetivamente presente deve ter uma verificação aplicável e validada ou uma pendência visível. Recomendações devem ser distinguidas de exigências. A interface deve separar “ELU das barras atendido no domínio implementado” de uma aprovação de todas as verificações da estrutura.
