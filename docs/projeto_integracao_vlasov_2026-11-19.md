# Integração do empenamento na análise dos formados

Este registro distingue a integração estrutural já implementada das verificações de resistência ainda abertas; não é declaração de cobertura concluída.

## Núcleos existentes e verificados

- `osa/analysis/vlasov.py`: elemento de 14 graus de liberdade, ordem local por nó `[uC,vC,wC,theta,ry,rz,theta']`, em N e mm. A rigidez tangente é `K-G`, com compressão positiva nos esforços iniciais. A recuperação normal é positiva em tração. O produto de inércia e as propriedades setoriais estão representados.
- `osa/verification/cold_formed_torsion.py`: solução por diagrama de torque linear por trechos, recuperação de tensões de parede fina, rigidez de extremidade condensada e cargas equivalentes de torque. A condensação escalar exige vínculos de empenamento independentes nas extremidades. Ela não impõe continuidade de empenamento entre barras.
- `tests/test_vlasov.py`: trabalho/energia, resposta analítica de console, torção sob quatro condições de empenamento e críticos globais de compressão/flexão para as sete famílias.
- `tests/test_cold_formed_torsion.py`: equilíbrio das tensões/fluxos, exemplo do manual, soluções analíticas e precisão nos limites de comprimento.

## Integração estrutural implementada

O adaptador agora dispõe da opção persistida `warping_analysis` e da requisição `warping`. O menu de análise expõe a opção **Análise dos formados (torção/empenamento)** e o diálogo **Vínculos de empenamento…**. Cada extremidade tem declaração física independente livre/impedida/contínua. Alterações invalidam a análise e a assinatura física. A compatibilidade geométrica/setorial das continuidades é conferida pelo solver; a cantoneira sem Cw não recebe vínculo setorial fictício.

`osa/analysis/pynite/vlasov_solver.py` monta a malha esparsa completa em conjunto com os graus de liberdade de seis coordenadas do modelo existente. Preserva continuidade dentro da barra, liberações, molas físicas de ligação, orientação/espelhamento e trabalho das cargas. Recupera N, V, M, rotação torsional, bimomento, torque Saint-Venant e de empenamento. A API permite ações nodais de bimomento em kN·m²; a transferência axial localizada requer esse dado em função do ponto de aplicação. A força axial centroidal genérica não cria bimomento implícito.

A rota de segunda ordem usa a tensão inicial **axial**: `K−G[N(x)]`, com integração da variação de N, equilíbrio de momentos com P–delta e comprovação positiva da rigidez livre escalada. O alongamento axial permanece de pequenas deformações. Os termos de tensão inicial de flexão/bimomento existentes no núcleo para análises críticas não foram convertidos em uma suposta formulação não linear geral. A verificação de resistência e de flambagem sob essas tensões continua independente. A rota integra a redução EA/EI dos ELU, ECw compatível, nocionais e comparação de deslocamentos com a mesma rigidez. O raio polar da tensão inicial mantém a geometria bruta.

Sob força normal, o torque material `torque_sc = Tsv+Tw` difere do esforço generalizado `generalized_torque_sc` pelo termo geométrico. O bimomento é recuperado incluindo essa parcela. As cargas de momento distribuído são integradas continuamente, sem reproduzir a aproximação legada em vinte binários pontuais. A malha ganha refinamento junto às extremidades e descontinuidades para resolver as camadas de empenamento; a tração é considerada ao determinar a menor escala dessa região.

Ensaios do adaptador incluem referências analíticas de flexão e torção, transferência matricial independente para flexão/torção acopladas, integração de uma barra-coluna com força normal variável, modelo misto com barra convencional, estabilidade pós-crítica, continuidade com eixo invertido, molas semirrígidas, carga no centro de torção e no centroide, bimomento de tração excêntrica do manual, malha esparsa grande e barras de 0,1 m/100 m. A interface dos vínculos foi renderizada e inspecionada. A última execução específica aprovou 27 testes em 5,67 s; inclui a rejeição do mecanismo de rotação torsional livre e de pivôs numericamente nulos. O cálculo linear e P–Delta com empenamento já estão ligados ao adaptador; os ensaios não aprovam automaticamente a resistência ELU.

**Serviço:** corrigida a conversão dos momentos legados para a base de compressão `[Nc,−My,+Mz]`, com teste estrutural de tração/flexão em cartola assimétrica. A metadata registra essa convenção e rejeita resultados anteriores. A rota ELS de quatro campos foi integrada posteriormente, conforme a seção final deste registro; a cantoneira no modelo sem modo setorial e as hipóteses dos caminhos legados permanecem sujeitas à auditoria indicada abaixo.

## Critérios preservados na integração

1. Os vínculos de empenamento são dados físicos da análise: livre, impedido ou continuidade explícita com outra barra compatível. Não devem ser armazenados como simples overrides de verificação, pois alteram a rigidez e devem invalidar a análise/assinatura física.
2. Manter os graus de liberdade de empenamento nos nós internos e em continuidades. Uma condensação independente por barra não representa a transmissão de bimomento em uma barra contínua. Nos encontros não colineares, não inventar compatibilidade entre funções setoriais diferentes.
3. Usar a referência centroidal da geometria do programa. No plano transversal, `vSC=vC-zSC*theta` e `wSC=wC+ySC*theta`. A força aplicada no centroide produz `TSC=TC+zSC*Vy-ySC*Vz`; cargas declaradas excêntricas precisam da parcela adicional correspondente. Torque nulo no solver antigo não comprova ausência física de torção.
4. Usar vetores de carga consistentes com as funções de forma de empenamento. A distribuição de torque e a rigidez do sistema devem ser resolvidas conjuntamente em sistemas hiperestáticos. Não recuperar o empenamento sobre um diagrama incompatível de um modelo que usou apenas GJ.
5. A conversão para o solver atual em m–kN deve preservar trabalho: deslocamentos translacionais multiplicam por 1000, o grau de liberdade `theta'` em rad/m divide por 1000 para rad/mm, e a energia N·mm converte por 10⁻⁶ para kN·m. Conferir também a conversão do bimomento.
6. Considerar as ligações semirrígidas e liberações nos graus de liberdade físicos antes da condensação. A nova malha interna não deve redefinir o valor físico das molas de ligação a cada subdivisão.
7. Separar propriedades geométricas que entram na tensão inicial das rigidezes reduzidas do material. EA/EI reduzidos não significam mudança física da área, centro de torção ou raio polar da seção. O termo normal ECw precisa de tratamento coerente com a redução adotada; GJ segue a hipótese do procedimento.
8. Validar a análise linear acoplada, a recuperação de forças e deslocamentos e a continuidade de empenamento antes de ligar o procedimento P–Delta. O núcleo já confere as matrizes geométricas para críticos, mas isso não prova por si só uma implementação completa de equilíbrio não linear de pórticos.
9. Recuperar Saint-Venant, bimomento, torque de empenamento e tensões concomitantes com os esforços de flexão/normal. Conferir estabilidade e interações ELU com método normativo ou evidência própria; tensão elástica abaixo de fy não substitui flambagem local/distorcional/global.

## Cortantes remanescentes

A cartola sob Vz sem Vy/torção concomitantes já está ligada à verificação, com partilha calculada. Faltam o cortante das abas livres, L e a superposição dos fluxos de torção/empenamento. O domínio de 9.8.3 é a alma com seus vínculos; o uso de kv=5 em elemento AL não é uma extensão automática. A NBR 14762:2010, 8.4.2/Seção 11, deve ser considerada nos casos sem procedimento previsto. Qualquer método complementar deve ter domínio e origem explicitados e validação independente.

## Outras frentes ainda abertas

- Aprofundar a classificação dos modos mistos das faixas finitas; a concordância dos autovalores não prova a identificação modal.
- Completar resistência ELU sob torção/bimomento, sua estabilidade e interações. A ação explícita de bimomento dispõe de API e do editor de extremidades descrito na atualização vigente.
- Conferir limites, entradas, persistência e memorial das próximas verificações de resistência.
- Executar a auditoria final do objetivo completo, sem usar os testes dos núcleos como prova de integração do aplicativo.


## Desenvolvimento do MLE de serviço com bimomento

Na etapa de núcleo foram acrescentadas as três peças abaixo. A integração estrutural correspondente foi executada na etapa seguinte, descrita ao final deste registro:

- `rounded_sectorial_field`, em `osa/sections/thin_walled.py`: campo setorial contínuo sobre os trechos retos e arcos reais da linha média. Integra `y dz−z dy` nos arcos e remove a parcela afim pelas três condições de ortogonalidade; determina Cw e o polo principal com a mesma medida de área. Não reescala Cw para forçar igualdade com a aproximação de cantos retos. `sectorial_properties` mantém a convenção anterior, explicitamente distinta.
- `osa/verification/cold_formed_warping_effective.py`: equilíbrio normal com base `[1,z,−y,ω]` e esforços de compressão `[N,My,Mz,Bc]`. O bimomento positivo em tração do solver usa `Bc=−B`. As larguras efetivas recebem a tensão linear completa de cada trecho plano; a matriz 4×4 preserva os acoplamentos após a redução. Os arcos permanecem efetivos, conforme a convenção geométrica do MLE existente. A tensão normal máxima inclui os dois lados da espessura para flexão e todos os pontos estacionários dos arcos; o empenamento usa a aproximação de tensão constante através da espessura. Não constitui resistência ELU.
- `VlasovSection.normal_matrix`, em `osa/analysis/vlasov.py`: matriz normal/setorial opcional, simétrica e positiva, validada e armazenada imutavelmente. O elemento passa a usar a energia normal completa, e a recuperação constitutiva inclui as parcelas acopladas de N, My, Mz e B. A formulação anterior é recuperada quando a matriz não é informada.

A página impressa 88/PDF 89 do manual foi conferida visualmente: equação A.8 para tensões normais com bimomento, A.9 para a parcela de cisalhamento de empenamento e A.10 para a definição da área setorial. O novo núcleo usa essas definições; o uso das larguras efetivas e da matriz acoplada é distinguido da expressão de tensões da seção bruta.

Validação: **138 testes aprovados em 8,98 s** nos novos campos setoriais, seção efetiva acoplada e elemento de barra, mais regressões dos núcleos existentes, adaptador e serviço. Incluem as sete famílias, reflexão, translação, continuidade nas tangências, integração independente das derivadas setoriais, equivalência ao caso de cantos retos, equilíbrio dos quatro esforços por quadratura adaptativa independente, matriz de material removido sem ganho de rigidez, extremos de tensão conferidos por amostragem fina e o exemplo de tração excêntrica do manual. A resposta de barra com matriz acoplada foi comparada à solução independente por transferência matricial; o refinamento 8→16→32 elementos confere a convergência das respostas axial, de flexão e de rotação torsional.

### Integração ELS executada

1. **Base comum:** a análise 7 GL dos perfis com modo setorial passa a usar `rounded_section_from_sheet`: Cw, polo, função ω e propriedades normais integradas na mesma linha média com arcos. O datum dos nós continua sendo o centroide do contorno adotado pelo programa. O eventual afastamento para o centroide da linha média é transportado pela matriz normal, sem mover as cargas/nós. As continuidades comparam a geometria e o campo setorial dos arcos, inclusive espelhamento e inversão do eixo. A cantoneira permanece explicitamente na aproximação convencional de Cw=0, identificada por `sharp-angle-no-sectorial`.
2. **Rigidez acoplada:** as matrizes normais efetivas completas são transportadas para a malha, nos eixos principais usados pelo adaptador, e retornam no memorial nos eixos geométricos. A rotação da matriz inclui os acoplamentos; o J de Saint-Venant permanece o da seção bruta. Os fatores EA/EI exibidos para a rota acoplada são indicadores; não substituem a matriz na solução.
3. **Envoltória e redistribuição:** `effective_warping_envelope` encontra a interseção das faixas efetivas de todos os estados concomitantes amostrados de uma barra/combinação. A mesma matriz uniforme é usada ao longo dessa barra. As regiões tornadas inefetivas permanecem assim nas iterações estruturais posteriores. A convergência é medida pela maior variação relativa de energia normal, considerando todos os acoplamentos, com tolerância 10⁻⁶; não se usa uma diferença de entradas com unidades incompatíveis. A propriedade de ordem de rigidez é de energia; o programa não afirma um teorema de envoltória de cada componente de deslocamento de qualquer modelo com rigidez variável.
4. **Rastreabilidade:** resultados identificam `geometry_basis=rounded-mean-line-v1` e `algorithm=vlasov-7gl-2`. Matrizes efetivamente usadas, máscaras efetivas e máximos de tensão são registrados. O verificador exige a identidade entre a matriz relatada e a matriz da análise; resultados anteriores exigem reprocessar. A carga/geometry/persistence lifecycle existente continua invalidando resultados antigos por revisão. A resistência ELU à torção/bimomento permanece pendente.

A NBR 14762:2010, 9.8.5(a), foi conferida visualmente na página impressa 51/PDF 57: a redução de rigidez deve usar MLE com a tensão normal das combinações de serviço. O caminho de quatro campos aplica esse cálculo à tensão linear de cada trecho plano e preserva as regiões efetivas e seus acoplamentos.

### Comprovação elástica da análise de serviço

Na rota acoplada não basta comparar somente a tensão normal a fy. Foi acrescentado um limite superior de tensão equivalente por **amostra concomitante**, com a parcela Saint-Venant nas duas faces e o fluxo associado aos cortantes e ao empenamento. Esse limite é uma comprovação suficiente da hipótese elástica no modelo de parede fina, não uma resistência ELU ou uma verificação de flambagem por cisalhamento. Não representa concentrações locais de tensão na dobra ou na introdução física da carga; esses efeitos não são resolvidos pela teoria de barra. Se o limite não comprovar elasticidade, o ELS fica **não verificado**, sem afirmar que esse limite conservador prova escoamento real.

Para o campo `σc` positivo em compressão, a derivada dos esforços normais usada no fluxo é `[0,Vz,−Vy,−Tw]`, em N, N mm e suas derivadas, após converter as convenções dos cortantes plotados. Em segunda ordem, os termos dos momentos recebem ainda `−N wC'` e `+N vC'`. O fluxo satisfaz `dq/ds=t·dσc/dx`, começa e termina em zero e recupera os esforços de face positiva `(-Vy,-Vz,Tw)`. Portanto `max|q| ≤ TV(q)/2`. A soma das áreas efetivas de cada trecho multiplicadas pelo máximo exato de `|dσc/dx|` naquele trecho limita a variação total. Somam-se `|Tsv|t/J` e a tensão normal máxima para obter um limite superior de von Mises. As faixas são inefetivas para a rigidez normal; não representam remoção física da espessura que transmite o fluxo.

Foi corrigida também a recuperação de segunda ordem **dentro** do elemento: a derivada do deslocamento centroidal inclui `vC'=vSC'+zSC·θ'` e `wC'=wSC'−ySC·θ'`. Ignorar as parcelas das funções de forma de empenamento podia conservar os valores de extremidade, mas perder o equilíbrio nas posições internas. O novo ensaio confere, entre pontos amostrados consecutivos, o equilíbrio de My, Mz e B com os deslocamentos recuperados.

### Escopo legado e pendências restantes

- O caminho de seis graus de liberdade não aprova ELS quando houver torque ou cortante excêntrico ao centro de torção. A resistência também passa a registrar a torção não resolvida mesmo quando o torque referido ao centroide for zero. Os ensaios legados de flexão simples usam agora a cartola sob carga no plano de simetria; o C com cortante no centroide tem teste próprio exigindo a solução 7 GL. Os casos de contato do C preservam explicitamente essa família em seu cadastro de teste.
- **A elegibilidade do ramo legado também verifica o empenamento induzido pela própria redução de largura.** Quando o MLE reduz EA/EI, uma solução de quatro campos sob os mesmos padrões, com B=0, verifica a ativação da componente setorial por razão energética. Ativação acima de 10⁻⁶ exige 7 GL, inclusive sob momento uniforme com T e cortante nulos. O ensaio de C200 sob momento 2,1 kN·m confere essa rejeição tanto na análise quanto na leitura de resultado antigo. O caso de cartola sob carga no plano de simetria permanece no domínio legado sem ativação setorial. Ainda falta estender a comprovação elástica conjunta de cisalhamento a todos os caminhos de três campos, além do complemento do L mencionado abaixo.
- O L na aproximação Cw=0 ainda usa o ramo de MLE de três campos; o ELS com torção/cortantes permanece não verificado até concluir a comprovação conjunta nessa base. Não se atribui um modo setorial fictício à cantoneira.
- Continuam abertos ELU sob torção/bimomento (incluindo estabilidade/interações), cortante de abas livres e L, superposição de fluxos na resistência de almas e validação aprofundada dos modos mistos de faixas finitas. O coeficiente kv=5 da alma não é aplicado a elemento AL.

### Evidências desta integração

- **681 testes aprovados em 55,01 s** na bateria consolidada final desta etapa, incluindo os ensaios de fluxo, versão do algoritmo e ativação de empenamento pela largura efetiva.
- **65 testes aprovados em 17,85 s** no conjunto de seção efetiva, serviço acoplado e adaptador, incluindo o fluxo conferido por integração independente.
- **112 testes aprovados em 30,85 s** após introduzir o identificador do algoritmo, nos módulos de serviço, adaptador e verificação de barra; **19 testes aprovados em 14,83 s** após restringir o ramo legado que ativa empenamento pela largura efetiva. Os conjuntos têm sobreposição; não se somam.
- Comparações independentes de torção sob bimomento, barra com seção efetiva acoplada e sistema hiperestático com duas seções diferentes, conferindo deslocamentos e reações axiais/transversais/rotacionais. Ensaios adicionais verificam segunda ordem, escoamento por Saint-Venant mesmo com tensão normal nula, persistência em JSON e reprocessamento, rejeição de base/matriz incompatíveis e ausência de ganho de energia pela redução.
- Diálogo real do memorial Qt renderizado e inspecionado, com matriz 4×4 e unidades, tensões e limite equivalente, equações e indicação separada das verificações pendentes. Captura temporária: `/tmp/opensa-pff-audit/memorial-coupled-service-dialog.png`.


## Atualização vigente — matriz completa e cantoneira

Esta atualização substitui as descrições anteriores de elegibilidade do ELS legado e de pendência da comprovação elástica conjunta do L.

- `vlasov-7gl-3`: todas as famílias usam a linha média arredondada e a matriz normal completa. O L usa `rounded-angle-saint-venant-v1`, três campos, Cw=0 e polo efetivo atualizado pela projeção no material normal retido. Os demais usam quatro campos e `rounded-mean-line-v1`.
- `coupled-normal-width-global-1`: uma atualização de largura por solução global, interseção monotônica das regiões efetivas, até 100 iterações, tolerância relativa 10⁻⁶ da matriz em energia e do polo. O critério evita a falsa não convergência da seção sob esforços artificialmente fixos em estruturas hiperestáticas. A comprovação material é feita somente com matriz, polo e esforços finais.
- O L agora recebe a mesma comprovação elástica conjunta normal/cisalhamento por limite superior. B=Tw=0; inclinações auxiliares são locais a cada elemento finito, permitindo a quebra de θ′ em torque pontual. Integração independente confere o fluxo e as resultantes em torno do polo efetivo.
- A rota centroidal anterior conserva resultados para inspeção, mas não aprova o ELS de nenhum formado. O usuário ativa a análise dos formados e declara os vínculos A/B somente quando há modo setorial. A interface explica esse requisito.
- Amostras de uma análise acoplada devem conter B, TSC, T generalizado, Tsv, Tw, θ e as duas inclinações centroidais, além dos esforços usuais. Valores ausentes/não finitos ou incompatibilidade TSC=Tsv+Tw e torque=−TSC impedem a aprovação, inclusive se somente o ELS estiver danificado e o ELU permanecer íntegro.

A formulação mantém as hipóteses de parede fina e pequenas rotações. Permanecem as frentes ELU de torção/bimomento e estabilidade/interações, resistência dos cortantes sem domínio implementado, classificação modal mista .


O editor **Bimomentos nas extremidades…** está ligado ao menu de análise. As linhas definem barra, extremo/nó, caso e ação em kN·m²; há explicação dos sinais e da conjugação com θ′. O cadastro exclui L/Cw=0, rejeita duplicidades e valores não finitos antes de gravar, preserva outras ações e exige reabrir se o modelo mudou. Edição e remoção invalidam os resultados. O diálogo e o memorial real da cantoneira foram renderizados e inspecionados.

Validação vigente: **692 testes aprovados em 79,03 s** na bateria consolidada, após integrar o L, a atualização global de larguras e a integridade das amostras. Depois, **7 testes de interface aprovados em 2,87 s**, incluindo dois novos casos do editor. Ruff passou nos módulos de cálculo e ensaios alterados nesta etapa. Os conjuntos se sobrepõem e não se somam.
