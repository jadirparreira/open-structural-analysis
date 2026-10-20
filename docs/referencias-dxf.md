# Referências DXF e DWG

Com um projeto aberto, use **Arquivo → Importar referência…** e selecione um
arquivo `.dxf` ou `.dwg`. A referência é exibida em cinza no ambiente 3D e inserida no
plano **XY**, com sua origem em **X = 0, Y = 0, Z = 0**. As coordenadas do
desenho em relação à origem original do CAD são preservadas.

Na seção **Geometria**, o botão **Configurar referência**, depois de
**Configurar eixos**, abre a lista dos desenhos importados. Nesse painel:

- Marque ou desmarque cada referência para exibir ou ocultar.
- Selecione um desenho para editar **Plano**, **X**, **Y** e **Z** na seção
  **Parâmetros**. A unidade `m` aparece dentro dos campos de coordenadas.
- Escolha o plano XY, XZ ou YZ.
- Passe o mouse sobre a referência e clique no pequeno **X** ao final da linha
  para retirá-la do projeto.

Clique fora do quadro para fechá-lo. O botão **Configurar referência** fica
destacado enquanto o quadro estiver aberto, assim como **Configurar eixos**.
O botão **Eixos** e o comando `AXES` alternam a exibição dos eixos na cena;
`CONFIGAXES` abre o quadro de configuração.

O eixo horizontal do desenho corresponde a X nos planos XY/XZ e a Y no plano YZ.
O eixo vertical corresponde a Y no plano XY e a Z nos planos XZ/YZ. A posição
informada é sempre um deslocamento nos três eixos globais. A importação enquadra
o desenho na vista; as alterações de posição e plano preservam a câmera.

Ao selecionar uma referência no quadro, o desenho fica azul, com linhas mais
visíveis, e uma esfera azul indica sua origem global. Esse marcador tem o mesmo
tamanho dos nós estruturais e é apenas visual. Ao fechar o quadro, o destaque e
o marcador desaparecem.

As ferramentas **Medir** e **Adicionar barra** capturam extremidades e pontos
médios das linhas e polilinhas, além de centros de círculos e arcos. Essas
capturas respeitam os controles de extremidades/centros e o botão Snap, funcionam
também com o quadro fechado e acompanham a origem e o plano de cada referência.
Referências ocultas não oferecem pontos de captura. Traços de hachuras, segmentos
dos tracejados, textos e subdivisões das curvas não criam pontos extras. Não há
captura livre ao longo das linhas da referência.

As referências continuam sem seleção ou edição por clique na cena. Sua geometria
e o marcador de origem não participam da análise estrutural. Os desenhos
e suas configurações ficam incorporados ao arquivo `.osa`, permitindo reabrir
o projeto sem o arquivo CAD original. Modificações posteriores no CAD não atualizam
automaticamente a referência: remova-a e importe a nova versão.

Os pontos de captura ficam incorporados ao projeto. Referências de arquivos OSA
mais antigos, que guardavam apenas o desenho renderizado, usam extremidades e
pontos médios desses segmentos armazenados. Reimportá-las recupera os pontos
originais do CAD, sem as subdivisões de curvas, hachuras e tracejados.

## Desenhos e unidades

São importadas as entidades visíveis do espaço de modelo, projetadas no plano
XY do CAD. Blocos, curvas, textos, tracejados, traço e ponto, hachuras por padrão
e preenchimentos sólidos com recortes são convertidos em geometria. Cores e
espessuras originais não são reproduzidas nesta versão.

As unidades declaradas no desenho são convertidas para metros. Se o arquivo não
declarar unidades, considera-se **1 unidade = 1 metro**, com um aviso ao usuário.
Para desenhos em centímetros ou milímetros, confira essa definição no CAD antes
de importar.

DWG é lido localmente pelo GNU LibreDWG, sem envio do desenho a serviços externos.
A conversão intermediária para DXF ocorre em uma pasta temporária descartada ao
final, sem modificar o arquivo original. O painel mantém o nome do DWG escolhido.
Objetos especializados do CAD sem suporte pelo leitor podem gerar avisos; confira
o resultado quando esses avisos forem apresentados.

Imagens raster e referências externas não incorporadas ao desenho não são
importadas. Entidades sem suporte geram avisos quando identificadas pelo leitor.
Não são importadas folhas do espaço de papel. Arquivos danificados ou desenhos
sem geometria visível são recusados sem alterar as referências já carregadas.

## Desempenho

A leitura e conversão são realizadas em segundo plano. Cada referência utiliza
uma única geometria em lote, armazenada em cache e exibida por um ator gráfico.
Mover, trocar o plano ou ocultar uma referência altera apenas sua transformação
ou visibilidade, sem converter novamente o CAD ou reconstruir o modelo estrutural.
As curvas são aproximadas com tolerância de 1 mm; os padrões de linha são
convertidos em segmentos, mantendo seu aspecto durante a navegação.

O limite é de 64 MiB de coordenadas por referência, antes da compressão no
projeto. Hachuras que excedam 30 segundos de geração ou tenham espaçamento
excessivamente pequeno são recusadas com uma mensagem para simplificação no CAD,
evitando importar um desenho parcialmente truncado.

## Preparar o suporte a DWG no desenvolvimento

Execute `uv run python scripts/prepare-dwg-converter.py`. O script usa a versão
0.14 do GNU LibreDWG, com verificação SHA-256 dos arquivos oficiais. No Linux ele
compila o conversor com compilador C e `make`; no Windows de 64 bits,
prepara o executável e suas DLLs da distribuição oficial. O leitor fica em
`build-tools/libredwg/<plataforma>/`, diretório gerado e ignorado pelo Git.

Os scripts de empacotamento executam essa preparação automaticamente e incluem
o leitor, a licença e os fontes correspondentes. A importação não depende de
compilador ou de instalação de CAD no computador do usuário final.

Para usar uma instalação própria do LibreDWG, deixe `dwg2dxf` no `PATH` ou defina
`OSA_DWG_CONVERTER` com o caminho completo do executável. DXF continua disponível
mesmo em ambientes de desenvolvimento onde o conversor DWG ainda não foi preparado.
