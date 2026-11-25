# Benchmark de operabilidade: Galpão Pluptiz

O projeto fornecido tem 1.091 nós e 1.756 barras. Ele não contém folha salva; para o teste foi criada uma cópia temporária com três vistas geradas a partir da geometria de detalhamento do próprio modelo. A folha tem 14.597 segmentos, sem identificações ou cotas adicionais. O original não foi modificado.

No Qt offscreen, em 1200 × 800, 30 quadros com pan de 30 pixels por passo e zoom variável tiveram mediana de **4,96 ms** e percentil 95 de **6,61 ms**. A medição dessa rodada usava reprodução vetorial durante o zoom e cache raster no pan; na rodada seguinte o zoom passou a redesenhar diretamente para atualizar o tracejado dos eixos imediatamente. Uma medição na mesma folha com zoom inicial 8× teve mediana de **4,78 ms** e percentil 95 de **7,10 ms**.

Em Gerenciar Vistas, a preparação inicial da prévia bloqueava por **59,6 s**, com cProfile ligado. Após substituir a extração de cada barra da malha global por extração de suas faixas contíguas e evitar recortes desnecessários, uma medição intermediária levou **7,8 s** com profiler. A preparação foi então movida para uma tarefa em segundo plano, usando cópia do estado do modelo e geometria independente da cena gráfica. Na medição final sem profiler, a construção da janela levou **57,2 ms**, o pedido de prévia retornou em **1,0 ms**, e a prévia ficou pronta em **3,53 s**; a maior lacuna no temporizador de interface foi **83,6 ms**. Ao reabrir a mesma vista, a prévia foi reutilizada e ficou pronta em **8,7 ms**. O cache é invalidado quando muda a revisão do modelo ou dos grupos de verificação. Tempos com e sem profiler não são diretamente comparáveis.

A troca de vista cancela a aplicação do resultado anterior; fechar a janela não espera a tarefa acabar. A geração de linhas vetoriais ao adicionar uma vista à folha ou exportar DXF continua sendo uma operação separada, que pode demorar em modelos grandes.

Para reproduzir sem alterar o projeto:

```bash
.venv/bin/python scripts/benchmark-build-sheet.py '/caminho/Galpão Pluptiz.osa' /tmp/galpao-folha-teste.osa
.venv/bin/python scripts/benchmark-project-sheet.py /tmp/galpao-folha-teste.osa --navigation --pan-step 30
.venv/bin/python scripts/benchmark-view-manager.py '/caminho/Galpão Pluptiz.osa' --offscreen
```

As medições offscreen não exercitam o contexto OpenGL real. A fluidez e a aparência ainda devem ser confirmadas no computador de uso, especialmente em projetos com muitas cotas e identificações.


## Ajustes posteriores: eixos e transições curvas

O zoom passou a redesenhar o conteúdo com os parâmetros da escala corrente em cada quadro. Isso preserva o padrão tracejado e as áreas de seleção dos eixos sem aguardar o fim da navegação. O pan continua usando o cache. Em uma cópia nova do Galpão com três vistas e **15.297 segmentos**, incluindo as transições curvas recuperadas, o teste de pan e zoom teve mediana de **4,10 ms** e percentil 95 de **7,51 ms**. As vistas não contêm cotas nem identificações adicionais.

A projeção e a prévia passam a incluir as transições longitudinais de curvas utilizadas pelo modelo, com recorte à profundidade da vista e remoção das linhas ocultas. As vistas previamente salvas que possuem os dados de projeção são regeneradas uma vez em segundo plano; as posições, cotas e identificações são mantidas. Na amostra do Mezanino, as cinco vistas terminaram essa atualização em **7,51 s**, enquanto a folha permanecia disponível.

Com a recuperação dessas linhas, a medição da primeira prévia do Galpão levou **4,65 s** em segundo plano; o pedido retornou em **1,0 ms**, a reabertura em cache em **9,6 ms**, e a maior lacuna do temporizador foi **60,4 ms**, em Qt offscreen. Como nas demais medições, o resultado gráfico deve ser conferido também no ambiente real com OpenGL.

## Auditoria geral e cache de vistas 3D — 12/11/2026

O benchmark de troca entre vistas foi executado em Qt `offscreen` no Galpão
(1.091 nós, 1.756 barras). Antes do cache limitado, três rodadas deram estas
medianas por vista: Completo 98,8 ms, Cobertura 166,3 ms, Laterais 107,7 ms e
Oitões 78,8 ms. O custo aumentava nas vistas filtradas porque cada troca
compactava novamente os mesmos subconjuntos da malha de barras.

Agora a cena mantém subconjuntos filtrados em cache, invalida-os quando muda a
geometria fonte e limita o espaço estimado a 40 MiB. No Galpão, os três
subconjuntos salvos ocupam aproximadamente 36,4 MiB; modelos que excedam o
limite descartam entradas antigas em ordem de uso. Com 15 rodadas, as trocas
aquecidas tiveram:

| Vista | Antes, mediana (3 rodadas) | Depois, mediana aquecida | Depois, p95 aquecido |
| --- | ---: | ---: | ---: |
| Completo | 98,8 ms | 98,7 ms | 139,5 ms |
| Cobertura | 166,3 ms | 78,3 ms | 86,9 ms |
| Laterais | 107,7 ms | 62,0 ms | 105,9 ms |
| Oitões | 78,8 ms | 50,3 ms | 52,2 ms |

A primeira troca filtrada após abrir a cena ainda prepara o cache: Cobertura
177 ms, Laterais 116 ms e Oitões 83 ms nesta rodada. A vista Completo não
mudou de forma material. Os p95 aquecidos ainda incluem picos no backend
offscreen, especialmente em Completo e Laterais; por isso as medianas mostram
melhor a redução consistente, enquanto o p95 deixa visível que ainda há
travamentos ocasionais a investigar.

No Mezanino (152 nós, 237 barras), a troca repetida para Completo ficou em
25,4 ms de mediana aquecida e 26,1 ms de p95 aquecido. O cache de subconjuntos
não entra em ação quando a vista não oculta barras.

Outras operações medidas no mesmo ambiente: abrir o Galpão levou 1,54 s, com
uma lacuna de evento de 216 ms; abrir o Mezanino levou 0,91–0,95 s, com uma
lacuna de 193–220 ms. O benchmark de Gerenciar Vistas do Galpão respondeu ao
pedido em 1,0 ms e concluiu a prévia em 4,76 s em segundo plano, com lacuna
máxima de 68,9 ms; reabrir a prévia em cache levou 8,7 ms. A abertura ainda
tem uma pausa perceptível e merece medição própria nas próximas etapas.

Para repetir as trocas e obter as medições fria, aquecida e p95:

```bash
.venv/bin/python scripts/benchmark-scene-views.py '/caminho/Galpão Pluptiz.osa' --offscreen --rounds 15
```

Todos os números desta auditoria são de CPU/Qt offscreen. O plugin Qt não
conseguiu criar um contexto OpenGL neste ambiente; eles não comprovam a
fluidez da viewport na GPU usada pelo usuário.
