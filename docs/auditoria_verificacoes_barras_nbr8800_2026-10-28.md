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
