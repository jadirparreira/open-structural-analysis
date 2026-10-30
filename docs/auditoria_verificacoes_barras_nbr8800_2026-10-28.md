# Auditoria das verificações de barras frente à ABNT NBR 8800:2024

**Data:** 28/10/2026
**Norma de referência:** ABNT NBR 8800:2024, terceira edição de 02/10/2024, versão corrigida em 25/02/2025, conforme PDF fornecido no ambiente.
**Escopo:** rotinas de verificação de barras, despacho e resumo das verificações, estimativa de comprimentos destravados, cobertura automatizada e hipóteses de entrada.
**Restrição da atividade:** não foram alterados arquivos de código ou testes. Este relatório é o único artefato novo da auditoria.

## Resumo executivo

Foram confirmados dois riscos importantes de resultado incompleto ou potencialmente otimista e uma limitação condicional de escopo:

1. O torsor aparece nos resultados de análise, mas não é considerado pelas verificações nem pelo resumo do elemento. Há risco de um resultado ser apresentado como verificado apesar de existir torção solicitante.
2. Os comprimentos de contenção podem ser reduzidos por uma heurística geométrica que não comprova rigidez, resistência, ligação, ancoragem ou posição em relação à mesa comprimida. A própria implementação documenta essas limitações, mas permite que os comprimentos alimentem capacidades calculadas.
3. A tração presume área líquida igual à bruta e (C_t=1). Isso é normativamente válido sob determinadas hipóteses, mas os dados necessários para confirmar essas hipóteses não fazem parte da rotina; portanto, o resultado é condicional.

Os três itens foram examinados pelo Agente A e revistos independentemente pelo Agente B. O Agente C arbitrou as classificações condicionais de tração e contenção. A evidência normativa foi conferida no PDF original, incluindo inspeção visual das páginas relevantes.

## Método e evidência de execução

- Inspeção estática das rotinas em `osa/verification/`, do mapeador de resultados, do despachante de verificações e dos testes disponíveis.
- Comparação com as cláusulas citadas da NBR 8800:2024 corrigida em 25/02/2025. As referências abaixo usam a página impressa da norma.
- Execução do recorte de verificações com:

  ```text
  .venv/bin/python -m pytest -k 'verification' --ignore=tests/test_verification_restraints.py
  ```

  Resultado: **22 passed, 629 deselected**. Os 22 testes cobrem os módulos de barras retangulares, circulares, quadradas e perfis L, T e U.
- A execução sem ignorar `tests/test_verification_restraints.py` falha durante a coleta: o teste importa `AnalyticalRestraints`, nome que não existe em `osa.verification.restraints`.
- Não foram encontrados módulos dedicados de teste para as rotinas I e W. As rotinas I e W estão conectadas ao despachante de verificações, mas não têm cobertura própria identificável na suíte.
- A suíte completa coletou 651 testes, mas a coleta foi bloqueada pelo erro de importação acima. Uma tentativa de execução ignorando esse arquivo começou, exibiu falhas em módulos fora do escopo de barras e não produziu sumário final utilizável; esses resultados não são tratados como diagnóstico completo da suíte.

## Achados

### A-01 — Torção solicitante não entra na verificação nem no status do elemento

**Classificação:** inconsistência de verificação normativa, com risco alto de falso resultado aprovado.
**Parecer dos agentes:** A e B concordam; não houve divergência material.
**Confiança:** alta.

**Comportamento observado.** O mapeador grava `torque` nos resultados dos membros e nas amostras ([result_mapper.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/analysis/pynite/result_mapper.py:42)). O despachante executa nove famílias de verificações, mas nenhuma inclui torção ([verification_worker.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/ui/verification_worker.py:177), [verification_worker.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/ui/verification_worker.py:198)). O resumo do elemento é formado com base apenas nos resultados desses nove checks e pode contar como aprovado um elemento cujo torsor foi ignorado ([verification_worker.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/ui/verification_worker.py:202)).

Há também um teste que injeta `torque=0.25` e exige que o memorial não mencione o torsor, a cláusula 5.5.2.3 nem um alerta de que o resultado não deve ser interpretado como aprovação ([test_l_rolled_verification.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/tests/test_l_rolled_verification.py:98)). Esse teste documenta a omissão atual, mas não demonstra conformidade normativa.

**Critério normativo.** A NBR 8800:2024, 5.5.1.1–5.5.1.2, p. 61, limita aquela interação axial-flexão a carregamentos sem torção. Para seções quaisquer sob torção combinada com força axial, momentos fletores e forças cortantes, 5.5.2.3, p. 63, requer a avaliação das tensões normais e de cisalhamento e dos estados-limite pertinentes.

**Por que é inconsistente.** As rotinas aceitam um estado de esforços mais amplo que aquele que de fato verificam. Se o torsor não for nulo, as interações de força axial e flexão não esgotam os efeitos combinados que a norma exige avaliar. Como o torsor não torna o elemento `not_checked`, o usuário pode interpretar o status geral como aprovação completa.

**Correção recomendada.** Implementar as verificações de torção e suas interações com os demais esforços para os tipos de seção suportados, ou marcar o resultado como incompleto/não verificado quando houver torsor solicitante que não esteja coberto. Atualizar o memorial para expor claramente a solicitação e o limite do resultado. Rever o teste citado para que valide a advertência exigida, em vez da ausência dela.

### A-02 — Comprimentos destravados podem ser reduzidos sem comprovar a efetividade do travamento

**Classificação:** limitação do estimador de contenções com risco de superestimar resistência; a confirmação depende do arranjo estrutural representado.
**Parecer dos agentes:** A e B concordam quanto ao risco. C confirma a aplicação separada das cláusulas para barras comprimidas e vigas e qualifica `Lb = Ly` como premissa condicional, não como regra geral da norma.
**Confiança:** alta para o critério normativo; média-alta para a conclusão sem um caso de projeto específico.

**Comportamento observado.** A rotina aceita uma barra conectada como contenção direcional quando sua orientação atende ao limiar geométrico ([restraints.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/restraints.py:279)). A estratégia de contenção cruzada também aplica um critério de área relativa, mas declara que essa comparação não comprova rigidez, resistência, ligação nem ancoragem ([restraints.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/restraints.py:440)). O próprio código registra que a heurística não verifica esses requisitos nem a contenção da mesa comprimida ([restraints.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/restraints.py:317)).

O estimador copia o intervalo de `Ly` para `Lb` e deriva `Lt` pelo menor entre `Ly` e `Lz` ([restraints.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/restraints.py:309)). As rotinas de compressão consomem comprimentos por eixo ([rectangular_bar.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/rectangular_bar.py:137)); as rotinas de flexão usam `Lb` ([rectangular_bar.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/rectangular_bar.py:204)).

**Critério normativo.** A NBR 8800:2024, 4.12.1.2, p. 33, estende os requisitos de pilares a barras sob compressão axial e os de vigas a barras sob momento fletor. A subseção 4.12.2, pp. 33–34, trata das contenções de barras comprimidas. A subseção 4.12.3, p. 34, trata da estabilidade de vigas, incluindo a posição das contenções de translação em relação à mesa comprimida e as distâncias entre contenções. Os requisitos gerais de contenção também consideram força resistente, rigidez, geometria, ligações e ancoragens (4.12.1.1, p. 33).

**Qualificação normativa.** A cláusula 4.12.3 se aplica às contenções pertinentes à flexão e ao comprimento `Lb`; ela não substitui os requisitos de 4.12.2 usados para barras comprimidas (`Ly`, `Lz` e, conforme o caso, `Lt`). A igualdade operacional `Lb = Ly` pode representar um arranjo particular, mas não é uma regra geral da NBR. A efetividade depende das contenções de flexão efetivamente instaladas, incluindo sua posição em relação à mesa comprimida. Sem um modelo de contenção que represente esses requisitos, o achado deve ser tratado como risco condicional, não como prova de que todo resultado atual está incorreto.

**Por que pode ser inconsistente.** Uma barra ligada geometricamente pode não ter rigidez/resistência suficiente, pode não estar ancorada adequadamente ou pode não conter a parte da seção que precisa ser contida. Se, apesar disso, o algoritmo encurtar o comprimento destravado, a força crítica ou o momento resistente calculado pode ficar acima do que o travamento real permite.

**Correção recomendada.** Representar contenções efetivas com sua direção, posição, rigidez, resistência e condições de ligação/ancoragem e verificar os critérios próprios de 4.12.2 ou 4.12.3 conforme o esforço. Calcular `Lb` independentemente de `Ly`, com base nas contenções de flexão efetivas. Quando os dados de contenção não forem conhecidos ou comprováveis, identificar o comprimento e a resistência como condicionais ou não verificados, em vez de tratar a geometria de uma barra conectada como comprovação suficiente.

### A-03 — Tração presume (A_n=A_e=A_g) e (C_t=1) sem dados para confirmar a hipótese

**Classificação final do Agente C:** limitação de escopo com premissa condicional; os valores não configuram, por si só, não conformidade normativa direta.
**Pareceres:** A identificou a lacuna; B concordou parcialmente e pediu classificação condicional; C arbitrou e confirmou a qualificação.
**Confiança:** alta.

**Comportamento observado.** As rotinas retangular e circular calculam a resistência à ruptura usando área bruta e reportam `An = Ae = Ag`, `Ct = 1` ([rectangular_bar.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/rectangular_bar.py:116), [round_bar.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/round_bar.py:105)). A rotina quadrada reutiliza a retangular ([square_bar.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/square_bar.py:22)). Não há dados de furos, roscas ou caminho de transmissão da força da ligação nos argumentos dessas rotinas.

**Critério normativo.** A NBR 8800:2024, 5.2.2, p. 39, determina a resistência à tração pelo menor valor entre escoamento da seção bruta e ruptura da seção líquida efetiva. A subseção 5.2.3, p. 39, define (A_e=C_t A_n); 5.2.4.2, p. 40, permite (A_n=A_g) quando não existem furos; e 5.2.5(a), p. 40, permite (C_t=1) quando a força é transmitida diretamente a cada elemento da seção por soldas ou parafusos. A subseção 5.2.7, p. 44, contém regra específica para barras redondas com extremidades rosqueadas.

**Decisão de arbitragem.** `An = Ag` e `Ct = 1` são compatíveis com a norma sob as hipóteses de seção sem furos/reduções relevantes e ligação que transmita a força diretamente a todos os elementos. Como a rotina não recebe esses dados, não é correto afirmar uma inconformidade universal; é correto apontar que a rotina não confirma essas condições e pode superestimar a resistência se elas não forem atendidas.

**Correção recomendada.** Declarar a hipótese no memorial e no resultado da verificação. Para uso geral, receber os detalhes de furos e ligação para calcular `An` e `Ct`, incluindo a condição específica de extremidades roscadas. Enquanto essas informações não existirem, apresentar a verificação como condicional quando as hipóteses não puderem ser confirmadas.

## Cobertura e lacunas de testes

| Família/tema | Evidência disponível | Resultado |
| --- | --- | --- |
| Barra retangular | `test_rectangular_bar_verification.py` | Incluído nos 22 testes aprovados |
| Barra circular | `test_round_bar_verification.py` | Incluído nos 22 testes aprovados |
| Barra quadrada | `test_square_bar_verification.py` | Incluído nos 22 testes aprovados |
| Perfil L laminado | `test_l_rolled_verification.py` | Incluído nos 22 testes aprovados; contém teste que confirma a omissão de aviso para torsor |
| Perfil T laminado | `test_t_rolled_verification.py` | Incluído nos 22 testes aprovados |
| Perfil U laminado | `test_u_rolled_verification.py` | Incluído nos 22 testes aprovados |
| Perfis I e W laminados | Sem módulos de teste dedicados encontrados | Lacuna de cobertura identificada |
| Comprimentos de contenção | `test_verification_restraints.py` | Não coleta por importação de `AnalyticalRestraints` inexistente |
| Suíte completa | 651 testes coletados antes do erro de coleta | Bloqueada pelo problema de importação descrito acima |

## Conclusão dos revisores

- **Agente A:** identificou os três achados, executou os testes pertinentes disponíveis após localizar o ambiente virtual e apontou as lacunas de cobertura.
- **Agente B:** confirmou a omissão de torção; confirmou o risco da heurística de contenções e refinou as cláusulas normativas aplicáveis; qualificou o tema da área líquida e (C_t) como condicional.
- **Agente C:** arbitrou o tema de tração como premissa condicional, não como erro em todo uso; confirmou que os requisitos de contenção para barras comprimidas (4.12.2) e vigas (4.12.3) devem ser analisados separadamente.

Este relatório identifica inconsistências e lacunas de escopo com base no código e na norma citada. Não é uma certificação de conformidade global nem uma avaliação de um modelo estrutural específico.

## Adendo — investigação da rotina W Laminado

**Data:** 28/10/2026
**Escopo desta etapa:** somente W Laminado. Nenhum arquivo de código ou teste foi alterado.

### Campanha comparativa

- Executadas **2.000 solicitações determinísticas variadas**, com os 108 perfis W do catálogo percorridos; cada solicitação tinha cinco posições amostradas e combinações de esforço axial, momentos nos dois eixos, cortantes nos dois eixos e torsor. Foram variados também os materiais A36/A572 Gr. 50 e os parâmetros manuais `Ly`, `Lz`, `Lt`, `Lb`, `Cb` e `Ct`. Os casos foram injetados como resultados amostrados para exercitar as rotinas; o solver estrutural não foi reexecutado.
- Foram comparadas independentemente as resistências e taxas de utilização que a rotina W calcula com as equações aplicáveis da NBR 8800:2024, versão corrigida em 25/02/2025: tração (5.2.2), compressão (5.3.2–5.3.4), flexão (5.4.2 e Anexo D), cortante (5.4.3.1 e 5.4.3.5) e interação (5.5.1.2). A referência de contenções usou os comprimentos fornecidos ao caso; a validade da heurística que os estima permanece no achado A-02.
- Nos casos de catálogo, foram calculadas 992 verificações de tração, 984 de compressão, 1.500 de flexão em cada eixo, 1.250 de cortante em cada eixo, 992 de flexotração, 734 de flexocompressão e 250 de flexão oblíqua. As demais ocorrências eram não aplicáveis ao tipo de esforço daquele caso.
- As resistências e interações numéricas coincidiram com a referência independente dentro da tolerância numérica, **exceto** pelas divergências listadas abaixo. O campo memorial `Mr_fla_kn_cm` ficou ausente nos 1.500 casos em que a memória da flexão Y foi examinada.
- Uma exploração suplementar com geometrias artificiais de alma muito esbelta encontrou extensões da fórmula FLA além da faixa de aplicabilidade e casos sem resistência positiva. Essas geometrias não pertencem aos 108 perfis do catálogo e foram tratadas como evidência de limite de escopo, não como falhas nos 2.000 casos catalogados.

### Achados W registrados

#### W-01 — `M_{r,FLA}` aparece como traço na memória

**Classificação:** falha de apresentação; há também divergência numérica condicional em uma faixa não acionada pelos perfis catalogados.
**Evidência:** a memória lê `Mr_fla_kn_cm`, mas essa chave não é devolvida pela rotina W ([calculation_memorial_dialog.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/ui/calculation_memorial_dialog.py:1258), [w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:327)). A Tabela D.1, p. 144, define `Mr = fy W` para FLA de seções I/H duplamente simétricas. Na interpolação entre `λp` e `λr`, a rotina reutiliza `mr_kn_cm = 0,70 Wy fy`, calculado para FLM/FLT ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:252)).

**Efeito observado:** os perfis W catalogados ficaram abaixo de `λp,FLA` nos casos analisados, portanto essa diferença não alterou a resistência calculada nesses 2.000 casos. Para uma geometria que alcance o intervalo `λp,FLA < λ ≤ λr,FLA`, o valor de referência para FLA seria diferente e a capacidade pode ser subestimada. O traço da memória foi reproduzido em todos os casos aplicáveis.

#### W-02 — `M_{z,Rd}` aparece como traço quando `M_{z,Sd}=0`

**Classificação:** representação enganosa de parcela não solicitada.
**Evidência:** a interação lê a resistência Z dos parâmetros da verificação de flexão Z ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:725)). Quando não existe momento Z significativo, a verificação Z retorna não aplicável sem parâmetros; a interação mantém `Mz_Rd_kn_cm=None`, e o memorial formata `0/—` ([calculation_memorial_dialog.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/ui/calculation_memorial_dialog.py:2181)).

**Efeito observado:** quando a solicitação Z está abaixo do limiar de aplicabilidade, a rotina de interação atribui parcela zero e não precisa da resistência Z para calcular a taxa. O traço, nesse caso, não causou diferença na taxa calculada; deve ser distinguido de uma resistência calculada que faltou no memorial.

#### W-03 — largura livre da alma usa profundidade sem descontar raios

**Classificação:** divergência geométrica com efeito conservador observado na compressão.
**Evidência:** a NBR define a largura `b` de alma laminada como a distância livre entre mesas menos os dois raios de concordância (5.1.2.2.3-a, p. 43); o Anexo D.3, p. 147, dá a mesma definição para `h`. A rotina usa `d − 2tf` para a largura de alma na área efetiva em compressão ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:897)) e também calcula `λFLA` com `di = d − 2tf` ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:252)). Em contraste, o cortante Z já desconta os raios ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:620)).

**Efeito observado:** nos 108 perfis do catálogo, os dados não incluem raio; a geometria usada adota o padrão interno de 10 mm. Com esse raio adotado, 27 das 984 verificações de compressão tinham elementos locais esbeltos e diferiram da referência baseada na largura plana: `Aef` e `Nc,Rd` calculados pela rotina ficaram até **1,96 % abaixo** da referência; a taxa correspondente ficou até **2,00 % acima**. O efeito observado foi conservador. Para `λFLA`, o parâmetro exibido ficou até 16,9 % acima da referência de largura livre nos casos comparáveis, mas não mudou a capacidade dos perfis catalogados porque todos permaneceram no ramo `λ ≤ λp,FLA`.

**Dependência de dados:** como o catálogo não fornece raio de concordância, a comparação usa o raio padrão de 10 mm da geometria do programa. As dimensões reais de cada perfil devem ser confirmadas antes de quantificar o efeito por perfil.

#### W-04 — FLA extrapolada além da faixa da Tabela D.1

**Classificação:** limite de aplicabilidade tratado como resultado verificado para geometrias não catalogadas.
**Evidência:** quando `λFLA > λr,FLA`, o código continua a interpolação e a limita entre zero e `Mp` ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:255)). A NBR define vigas de alma não esbelta para `λ ≤ λr` (D.1.2, p. 137); a fórmula de D.2.2 não se aplica à FLA para `λ > λr`, remetendo ao Anexo E. O Anexo E.1.2, p. 148, descreve vigas I/H soldadas, não perfis W laminados.

**Efeito observado:** na exploração suplementar de 50 geometrias artificiais, 27 casos chegaram a essa faixa e a rotina ainda retornou uma capacidade pela extrapolação. A cobertura normativa para W laminado com alma nessa faixa não foi estabelecida nesta auditoria. Não tratar esses resultados como comparados à fórmula de D.2.2.

#### W-05 — limites de escopo das solicitações combinadas

- **Torção:** aplica-se ao W o achado A-01. O campo de torsor foi variado na campanha, mas a rotina não o usa; 5.5.1.1 restringe a interação axial-flexão ali apresentada a casos sem torção, e 5.5.2.3 trata tensões sob torção combinada.
- **Cortantes simultâneos em Y e Z:** os dois cortantes são verificados separadamente por 5.4.3.1 e 5.4.3.5. A rotina não calcula a verificação combinada por tensões de cisalhamento que 5.5.1.3 permite tratar conforme 5.5.2.3-b/d. As solicitações simultâneas foram geradas, mas a comparação numérica ficou limitada às duas verificações individuais; portanto, esse estado combinado permanece sem conclusão.
- **Esbeltez global `L/r > 200`:** a rotina calcula e guarda `slenderness_limit=200`, mas não emite advertência quando ultrapassado ([w_rolled.py](/home/jadirparreira/Programação/Open%20Structural%20Analisys/osa/verification/w_rolled.py:1091)). A NBR 5.3.7.1–5.3.7.2, p. 52, trata 200 como recomendação e pede limites definidos pelo responsável técnico se não atendida; isto fica registrado como lacuna de comunicação, não como violação de um limite obrigatório da resistência.

**Situação:** achados anotados para autorização posterior de correção. Nenhuma alteração foi feita nas rotinas ou nos testes.

### Implementação autorizada — 28/10/2026

O usuário autorizou a correção dos achados da rotina W e da memória. Foram alterados somente os caminhos condicionais de W Laminado em `w_rolled.py`, `verification_worker.py`, `memorial_data.py` e `calculation_memorial_dialog.py`, e acrescentado `test_w_rolled_verification.py`. A hierarquia tipográfica, espaçamentos e apresentação das equações existentes foram preservados; os limites foram acrescentados como aviso compacto no padrão visual atual.

- A largura livre da alma passou a descontar os dois raios tanto na compressão quanto em FLA; o raio é exposto na memória. Quando não existe `r` explícito na geometria, a rotina mantém o padrão de 10 mm e informa esse pressuposto. O JSON atual não contém os raios; o folder oficial Gerdau localizado apresenta `d'` para uma lista de bitolas, mas não confirmei correspondência e cobertura para todas as 108 seções do JSON. Não importei uma tabela parcial como se cobrisse o catálogo inteiro; os raios reais continuam pendentes de validação.
- A FLA agora calcula e entrega `Mr_fla_kn_cm = Wy·fy` e usa esse valor na interpolação do Anexo D.2.3. Para `λFLA > λr,FLA`, retorna `not_checked` com a razão e o motivo, sem extrapolar a expressão; a memória mostra a faixa e a causa.
- A resistência à flexão em Z é calculada mesmo quando `Mz,Sd=0`, disponibilizando `Mz,Rd` para a interação e evitando `0/—`.
- Demanda não nula de torsor ou cortantes simultâneos em Y/Z agora marca o resumo do elemento como incompleto (`not_checked`) e aparece no aviso da memória. A rotina continua sem calcular essas interações; o aviso impede interpretar a verificação parcial como aprovação global.
- `L/r > 200` gera nota segundo o caráter de recomendação da NBR 8800:2024, 5.3.7. As premissas de tração `An=Ag` e `Ct=1` também ficam explícitas na memória.
- A memória informa que `Ly`, `Lz`, `Lt` e `Lb` são estimados a partir do modelo, apresenta as notas/ocorrências retornadas pela rotina de contenções e orienta conferir esses valores com os travamentos construtivos efetivos.

**Verificação após a implementação:** 12 testes focados passaram (`test_w_rolled_verification.py` e `test_memorial_docx_export.py`); `ruff` passou nos dois arquivos de rotina W/renderer e no novo módulo de testes; compilação Python e `git diff --check` passaram. A coleta de `test_verification_restraints.py` continua impedida por importar `AnalyticalRestraints`, nome não presente no módulo atual; não houve alteração nessa cobertura compartilhada. Os testes novos exercitam as correções centrais, mas não substituem uma nova campanha aleatória de 2.000 casos pós-correção.

**Lacunas remanescentes:** a rotina ainda não calcula a torção nem as combinações de tensões normativas correspondentes; agora sinaliza o limite. Também não calcula a interação de cortantes Y/Z. O modelo continua sem geometria de furos e detalhes de ligação, portanto a resistência à tração continua condicional a `An=Ag` e `Ct=1`. A exatidão por perfil W depende de validar e cadastrar os raios reais para toda a lista atual. A fonte técnica consultada foi o [folder oficial de perfis estruturais Gerdau](https://gsn.gerdau.com/sites/gsn_gerdau/files/downloadable_files/Folder%20Perfis%20Estruturais%20Gerdau%20-%20Segmento%20Industrial.pdf), que identifica `R` como raio de concordância e tabula `d'` para as bitolas nele listadas.

### Atualização — 30/10/2026

A verificação combinada de cortantes Y/Z foi removida por decisão do usuário. O programa mantém as verificações independentes em Y e Z e não detecta, sinaliza nem apresenta seção de memorial para a simultaneidade. O registro acima descreve a auditoria e a implementação em 28/10/2026; esta atualização registra a decisão posterior de escopo.
