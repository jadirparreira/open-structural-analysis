# Marcas de solda nas folhas do projeto

O comando **Elementos do modelo → Marca de solda** abre o painel à direita, com o título **Solda**. Durante o lançamento, os outros painéis de propriedades ficam ocultos. O painel tem altura fixa, rolagem interna e prévia centralizada em um quadro. O primeiro clique seleciona uma vista; os seguintes posicionam a ponta da seta nessa vista, inclusive em detalhes de componentes. Não é necessário acertar uma aresta. Durante o lançamento, a ponta da seta captura extremidades, pontos médios e interseções das linhas visíveis da vista selecionada, respeitando as preferências de snap do programa. O ponto capturado usa o indicador azul habitual; longe de um snap, a inserção continua livre. Esc encerra o comando e preserva as marcas já inseridas; Enter não confirma etapas. O botão do meio permite fazer pan antes ou depois de selecionar a vista, sem encerrar o lançamento.

Após encerrar o comando, clicar no símbolo permite editar suas propriedades. Arrastar desloca a linha de referência, mantendo a seta no local da solda. Delete remove a marca. As marcas são anotações de cada vista, salvas em `weld_marks`, sem modificar a geometria estrutural. A seção **Solda** nas configurações do projeto define as cores da linha, do texto e dos símbolos e a altura do texto. Os padrões são linha vermelha, texto e símbolos pretos e texto com 3 mm de altura no papel. As linhas usam a espessura padrão de 1 pixel cosmético. Durante o arraste, o contexto completo da folha fica em cache e somente a solda é redesenhada; ao soltar, a renderização normal e os limites da vista são atualizados. Alterações de zoom ou tamanho da área de desenho invalidam o cache.

Estão disponíveis filete, chanfro reto, meio V e V; lado da seta, oposto ou ambos; tamanho da perna/profundidade, comprimento e passo para filetes intermitentes; abertura da raiz e ângulo nos chanfros aplicáveis; contorno; solda de campo; toda a volta; processo ou observação na cauda. Valor zero nos campos opcionais omite a indicação. Um filete com comprimento e passo positivos mostra `comprimento-passo`. A linha de referência tem 18 mm no caso simples e aumenta conforme a largura das medidas, com as mesmas dimensões no papel em qualquer zoom. Números decimais usam vírgula.

O frame tracejado dos grupos de detalhes mantém seus limites em coordenadas da folha durante zoom, pan e redimensionamento da janela; os limites são recalculados quando o conteúdo ou a disposição do grupo muda.

## Conferência dos símbolos

A revisão visual foi feita sobre as figuras 10.45 e 10.46 e os seis exemplos da tabela 10.4 de Fakury (páginas impressas 273–274), com comparação complementar à apresentação de simbologia da UFJF e ao quadro gráfico da AWS. Adota-se a convenção AWS de linha de referência única usada nessas referências brasileiras; não se mistura com o sistema ISO de linha tracejada.

| Elemento disponível | Conferência e ajuste |
| --- | --- |
| Filete | Triângulo retângulo de pernas iguais; face vertical à esquerda, independentemente da direção da chamada. |
| Chanfro reto | Dois traços paralelos perpendiculares à linha de referência. |
| Chanfro meio V | Face vertical à esquerda e vértice na referência, com a diagonal abrindo para o lado indicado. Corrigida a orientação anterior. |
| Chanfro V | Vértice na referência e pernas abrindo para o lado indicado. Corrigida a orientação anterior. |
| Lado da seta / oposto / ambos | Símbolos abaixo / acima / nos dois lados da referência, mantendo os textos legíveis. |
| Toda a volta | Círculo na junção entre a chamada e a referência. |
| Campo | Bandeira triangular preenchida junto à junção. |
| Contornos | Plano, convexo e côncavo junto à face externa da solda. No filete acompanham a face inclinada; nos chanfros ficam transversais à abertura. O côncavo é uma opção complementar do quadro AWS. |
| Medidas | Perna/profundidade à esquerda; comprimento e passo à direita; raiz no interior do chanfro e ângulo junto ao símbolo. |
| Seta / cauda | Ponta preenchida orientada ao local clicado; cauda bifurcada somente quando há processo ou observação. |

A disposição foi compactada sem espelhar a face vertical dos símbolos quando a linha de referência está à esquerda. O tamanho do glifo é convencional: o ângulo indicado numericamente não transforma o glifo em desenho geométrico do chanfro.

## Referências consultadas

- Fakury, Silva e Caldas, *Dimensionamento de elementos estruturais de aço e mistos de aço e concreto*, item 10.9.4, páginas impressas 272–274; figuras 10.45 e 10.46 e tabela 10.4 (páginas 289–291 do PDF disponível). Foi adotada a linha de referência única: símbolo abaixo para o lado da seta, acima para o oposto; face vertical do filete e meio V à esquerda. As medidas indicadas são em mm. O livro se baseia na NBR 8800:2008.
- UFJF, professor Moisés Luiz Lagares Júnior, [Processos de Fabricação III — Soldagem: conceitos gerais](https://www2.ufjf.br/profab/files/2016/09/Conceitos-Gerais-em-Soldagem.pdf), slides 19–24, apresentação da convenção AWS A2.4 em referência didática brasileira.
- American Welding Society, [AWS A2.4:2020, apresentação e sumário oficiais](https://pubs.aws.org/Download_PDFS/2__A2_4_2020_PV.pdf), para conferir o escopo e as atualizações do sistema de símbolos.
- American Welding Society, [quadro de símbolos de soldagem](https://app.aws.org/mwf/attachments/64/225364/AWSWeldSymbolchart.pdf), edição 2007, como referência gráfica complementar.

O recurso implementa o subconjunto de símbolos descrito acima. Não realiza dimensionamento de soldas nem cobre integralmente a AWS A2.4 ou o sistema de linha tracejada da ISO 2553.
