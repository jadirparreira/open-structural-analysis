# Benchmark de operabilidade: Mezanino Barreira

Referência: projeto fornecido pelo usuário em 12/11/2026, com 152 nós, 237 barras e 33 grupos de verificação. A primeira folha tem cinco vistas e 10.692 segmentos. As medições foram feitas em Qt `offscreen`, sem contexto OpenGL; portanto, medem principalmente trabalho de CPU e não substituem a avaliação interativa com a placa gráfica do usuário.

| Operação | Antes | Depois | Condições |
| --- | ---: | ---: | --- |
| Redesenho da folha com pan e zoom (mediana de 30) | 36,62 ms | 12,38 ms | 1200 × 800, vistas salvas |
| Redesenho da folha (percentil 95) | 38,94 ms | 14,84 ms | Mesmo cenário |
| Troca repetida para Verificação | 5.653 / 5.630 ms | 558 / 538 ms | Com cProfile |
| Troca repetida para Detalhamento | 3.718 / 3.748 ms | 469 / 490 ms | Com cProfile |

Sem profiler, após as alterações, as duas trocas repetidas medidas foram 396 / 410 ms para Verificação e 362 / 351 ms para Detalhamento. A primeira troca de cada sessão pode ter custo diferente. O profiler acrescenta custo, principalmente ao código com muitas chamadas Python, por isso os valores com e sem profiler não devem ser comparados diretamente.

As medições de 36,62 / 12,38 ms da primeira rodada não carregavam o modelo no widget isolado e, portanto, não incluíam os eixos. Elas não representam o custo completo da folha.

A folha reutiliza caminhos de desenho e seus limites enquanto os segmentos não mudam. A filtragem das arestas internas dos grupos avalia segmentos em lote e a geometria dos símbolos de liberação é calculada por operações vetoriais. Nenhuma regra de visibilidade foi alterada.

Para reproduzir:

```bash
.venv/bin/python scripts/benchmark-project-sheet.py '/caminho/para/modelo.osa'
.venv/bin/python scripts/benchmark-session-switch.py '/caminho/para/modelo.osa' --offscreen --profile
```

A troca entre sessões ainda apresenta atraso mensurável. É necessário medir também na interface com OpenGL e validar pan, zoom, seleção, identificação, cotas e troca de sessões no computador de uso antes de concluir que a lentidão percebida foi eliminada.


## Segunda rodada: pan, zoom e troca Modelo/Projeto

O benchmark da folha foi corrigido para carregar também o modelo e desenhar seus eixos. Com ele, o redesenho anterior a esta rodada teve mediana de **34,49 ms** e percentil 95 de **47,89 ms**, sem profiler. Reutilizar os cálculos dos eixos reduziu a mediana para **15,01 ms** antes de introduzir o cache de navegação.

Durante o pan, o desenho é reutilizado em uma área maior que a janela. A margem é refeita a partir da gravação vetorial quando o movimento ultrapassa seus limites. Após 100 ms sem movimento, a folha é redesenhada com a escala exata; ao clicar ou usar identificação/cotas antes disso, os dados de interação são atualizados. A rodada seguinte substituiu a ampliação da imagem no zoom pela reprodução vetorial, para evitar o borramento relatado pelo usuário. A área adicional em memória é limitada a 64 MiB, exceto quando a própria janela já ultrapassa esse limite.

Na segunda rodada, antes da alteração visual do zoom, com a folha cheia, pan de 30 pixels por quadro e variação de zoom: mediana **2,50 ms**, percentil 95 **4,20 ms**. Nas mesmas condições, a folha vazia mediu **2,55 ms** e **4,15 ms**. Essas medições avaliam pintura Qt offscreen em 1200 × 800 e não comprovam a fluidez com a GPU e o sistema de janelas reais.

Na troca Modelo/Projeto, com profiler, as entradas repetidas em Projeto caíram de **83–88 ms** para **23–26 ms**. A primeira entrada medida foi de 156 ms, incluindo a preparação inicial do desenho. Sem profiler, as entradas repetidas medidas ficaram entre **10 e 21 ms**.

```bash
.venv/bin/python scripts/benchmark-project-sheet.py '/caminho/para/modelo.osa' --navigation --pan-step 30
.venv/bin/python scripts/benchmark-project-sheet.py '/caminho/para/modelo.osa' --navigation --pan-step 30 --empty
.venv/bin/python scripts/benchmark-detailing-switch.py '/caminho/para/modelo.osa' --offscreen --profile
```
