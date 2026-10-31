# Importação experimental de projetos PRJ

A opção **Abrir modelo** aceita somente `.osa`. Use **Importar modelo** para `.prj` e `.prj.zip`; ela está na tela inicial, no menu Arquivo e no atalho `Ctrl+I`. O PRJ pode ser binário direto ou um ZIP com o membro `__DADOS__`; o leitor verifica os bytes, não apenas a extensão.

## Primeiro teste

1. Abra o OSA normalmente e use **Importar modelo** (`Ctrl+I`).
2. Selecione o arquivo `teste_conv.prj` ou `teste_conv.prj.zip`.
3. Confira as opções: comprimento `cm`, força `kgf`, cota do topo do baldrame `0 m`, Poisson adotado `0,2`.
4. Para reproduzir o teste executado, mantenha ativados o prolongamento até o assentamento das sapatas, as ligações rígidas e a leitura das propriedades de concreto.
5. Importe. O resumo informa o que foi transcrito e o que precisa ser revisto.
6. Use **Salvar**. O primeiro salvamento pede um destino `.osa`; o PRJ de origem não é sobrescrito.
7. Reabra o `.osa`. A geometria e o relatório de importação acompanham o modelo.

No exemplo `teste_conv`, as opções acima geram **28 nós, 16 barras (8 vigas e 8 trechos de pilar) e 16 ligações rígidas**, com cotas `−1,50`, `0,00` e `3,00 m`. O trecho inferior usa o valor individual `150` lido do perfil de sapata, convertido de cm para m. As seções candidatas são convertidas de cm para mm, e as propriedades de materiais para kN/m² e kN/m³. O arquivo também contém dois registros `L1`, um por pavimento, agora preservados como lajes pendentes da futura conexão com placas.

## Escopo desta versão

- Layouts de lançamento estudados nos arquivos de códigos internos **3419** (`teste_conv`) e **2281** (`Arara Azul`), com tentativa automática de leitura de outros códigos quando os registros têm estrutura compatível. O código interno identifica um formato de serialização, não uma versão do programa de origem.
- Vigas com um ou vários trechos retos e seções retangulares reconhecidas; pilares com continuidade identificável entre pavimentos.
- Nós intermediários `ElementoNo` usados como referências geométricas de extremidades de vigas, sem criação de pilares ou apoios nesses pontos.
- Nomes, pavimentos, geometria, seções e propriedades candidatas de concreto das configurações de pavimento.
- Deslocamentos de extremidade representados opcionalmente por ligações rígidas do OSA. A equivalência analítica dessa idealização ainda precisa ser verificada.
- Representações CAD duplicadas são preservadas no relatório e excluídas da contagem física somente quando correspondem a pilares já identificados.
- Sapatas: posição da base do pilar definida pela profundidade de assentamento individual; nenhum elemento de fundação dimensionado é criado.
- Lajes: preservação das evidências e contrato para futura implementação com placas; nenhum elemento de placa é criado nesta etapa.

**Apoios, molas, liberações, parâmetros 0/0,15, cargas, paredes e combinações ainda não são transcritos para ações/vínculos ativos do modelo de cálculo.** As evidências lidas ficam em `import_metadata.source_evidence` dentro do `.osa`. Os nós importados ficam livres e as barras sem liberações até a revisão no editor. O peso próprio é aplicado pelas ferramentas do próprio OSA, sem duplicação pelo importador.

## Cota das sapatas e vínculos pendentes

Para cada sapata, `z_base = z_topo_baldrame - profundidade_assentamento`. A cota informada para o primeiro pavimento é usada como referência do topo do baldrame. Desníveis particulares ainda precisam ser conferidos. A altura do primeiro pavimento não é usada como substituta da profundidade.

O leitor reconhece os prefixos observados de 25 e 29 bytes após os dados de temperatura, verifica o bloco de solo e aceita os dados de sapata nulos, embutidos ou referenciados. O perfil de tipo `1` foi observado nos registros que contêm `TDadosGravSapata`; outros tipos exigem calibração. O bloco embutido de sapata observado no PRJ 2281 acrescenta 170 bytes à serialização; seu fechamento e o fechamento do pilar são conferidos separadamente.

O nó `Base_P…` recebe a cota calculada e aparece como extremidade da barra do pilar. `import_metadata.support_candidates` registra nome do nó, pilar de origem, profundidade, cota e códigos brutos de apoio. Esses códigos não são convertidos em engastes, rótulas ou molas. A identificação gráfica de um vínculo ativo depende da próxima etapa de calibração; nesta entrega, o relatório lista as posições de apoio pendentes.

Blocos de coroamento e outros tipos de fundação continuam fora desse cálculo de altura. Sua referência geométrica precisa ser confirmada antes da implementação. Se a profundidade não for reconhecida, o importador recusa o prolongamento em vez de usar a altura do pavimento; é possível desativar esse prolongamento para importar somente os pavimentos suportados.

Arquivos `.osa` gerados pela versão anterior mantêm suas coordenadas. Reimporte o PRJ para aplicar a nova regra de assentamento.

## Conexão preparada para placas

O leitor identifica registros de laje (`Laje`, `ElementoLaje` e classes `TElementoLaje…`). Tipos de catálogo, como `TLajePreFabricada`, configurações e grupos de continuidade não são contados como lajes lançadas. Para `TElementoLajeContornoComPilar`, são lidos o nome, o pavimento e as referências aos trechos do contorno; essas referências são relacionadas aos membros importados.

`import_metadata.source_evidence.slabs` preserva uma região binária por registro, com codificação `zlib+base64`, tamanho, hash e limites no fluxo original. Essa região inclui o contexto até a próxima laje ou o fim da região do croqui; **não é declarada como o tamanho exato do objeto**. Assim, campos ainda não interpretados ficam disponíveis sem inventar geometria ou cargas.

`import_metadata.plate_transfer` segue `osa-plate-transfer/v1`, com unidades em metros. Cada candidato tem ID de origem, nome, pavimento, referências de contorno e campos para contorno 3D, aberturas, espessura e material. Dados ainda não decodificados são `null` e constam em `missing_fields`. O mapeamento atual do PRJ é parcial: os contornos completos, aberturas, espessuras e atribuições de material ainda precisam ser decodificados e validados.

O módulo `osa.transcriptions.plates` oferece `PlateDefinition`, `PlateTarget` e `connect_plates`. Quando houver suporte nativo, implemente `PlateTarget.import_plates()` para criar o lote em uma transação. `connect_plates` valida o lote completo antes de chamar o destino; candidatos incompletos não são enviados. O domínio nativo deverá persistir os IDs retornados e marcar os respectivos candidatos como `imported`, junto aos elementos de placa efetivamente criados.

Enquanto houver lajes pendentes, o modelo pode ser importado, editado e salvo, mas o processamento é interrompido tanto na janela quanto no adaptador PyNite. Confirmar a revisão não remove essa pendência. Nenhuma carga equivalente de laje é gerada: a representação prevista é por elementos de placa.

## Validação do projeto Arara Azul

No PRJ real de código 2281, foram conferidos os 22 `ElPilarFundacao` (P1 a P22), todos com o valor de profundidade `150`, dados de sapata embutidos e fechamentos reconhecidos. A leitura dos outros 22 registros de pilar também passou.

O leitor agora reconhece o prefixo geométrico das **54 paredes**, incluindo o bloco opcional `TDadosCargasPlacasParedes`. Essas paredes e seus dados brutos ficam nas evidências; não são convertidas em elementos nem em cargas.

As **30 vigas, com 101 trechos**, são lidas integralmente na lista de lançamento. Cada trecho recebe uma barra própria, preservando seção, extremidades, referências e deslocamentos. Vigas com vários trechos usam nomes como `V1_T1`, `V1_T2`; o relatório mantém o nome e o ID da viga original. Também são reconhecidos os **26 nós intermediários** referenciados pelas vigas. Os seis componentes encontrados em registros `CargaNo` desses pontos são preservados como dados brutos, sem atribuir unidades, eixos ou ações ativas.

Com as opções padrão, o resultado conferido pela janela do OSA é **225 nós, 145 barras (101 trechos de viga e 44 trechos de pilar), 133 ligações rígidas e 22 posições de apoio pendentes**. As cotas são `−1,50`, `0,00` e `5,00 m`. Foram verificados os 101 pares de extremidades, ausência de nós isolados, salvamento e reabertura em `.osa`. O hash do PRJ de origem permanece igual.

Isso valida a importação geométrica desse arquivo específico, sem afirmar equivalência de cálculo. Cargas, apoios, liberações e paredes continuam sem participação ativa no modelo. Não foram encontrados registros de laje lançada nesse PRJ pelo inventário de classes estudado.

## Materiais e revisão

O material pode usar as propriedades candidatas lidas do PRJ; nesse caso, o coeficiente de Poisson é uma opção explícita, e G é calculado por `E / [2(1 + ν)]`. Se essa opção for desativada, o importador utiliza um concreto de referência do catálogo OSA, identificado como material para revisão. Sobreposições particulares de material, centros/eixos locais e rotações das seções precisam ser conferidos.

Nos modelos sem lajes pendentes, antes da primeira análise o OSA reapresenta o resumo e pede confirmação de que unidades, geometria, materiais, apoios, vínculos e cargas foram revistos. A pendência acompanha o `.osa` até a confirmação. O adaptador PyNite também verifica essa pendência para os fluxos sem interface. Nos modelos com lajes pendentes, a análise aguarda sua efetiva integração como placas.

Layouts recusados, seções não reconhecidas, elementos sem continuidade ou tipos de lançamento ainda não implementados são rejeitados quando identificados. O modelo atualmente aberto é mantido. A importação experimental não garante cobertura integral do PRJ nem equivalência estrutural.

## Compatibilidade entre versões

O código interno do projeto é informativo. A importação tenta o decodificador de lançamento a partir das classes encontradas e verifica posições, tamanhos, fechamentos, referências entre objetos, contagens de pavimentos/croquis/vigas/trechos/pilares/pontos e coerência das excentricidades. As tags numéricas de serialização são lidas como dados brutos. A lista de trechos pode conter vários itens; sua capacidade reservada pode ser maior que a contagem. O total de trechos deve corresponder ao inventário de `ElementoTrecho`, sem duplicação de IDs.

As variantes observadas usam atributos de linha de 1 ou 9 bytes, prefixos de trecho de 10 ou 29 bytes após as excentricidades e caudas de 9 ou 13 bytes após a temperatura. A seleção exige âncoras e fechamentos nas posições previstas; não usa apenas o código interno nem procura um fechamento arbitrário. Quando presente, a árvore `TBarraEstrutura` anterior às referências de extremidade é percorrida para localizar o lançamento. As referências a barras e nós processados não são usadas como substitutas da geometria lançada.

Os dados posteriores à lista de trechos, como `Viga` e `TDadosGravViga`, não são transcritos. O leitor informa o fim conhecido do lançamento e mantém `object_end_known=false` para a viga externa, sem declarar que interpretou o objeto inteiro ou seus resultados de dimensionamento.

Quando o layout é reconhecido com outro código, o relatório informa **compatibilidade experimental**, preserva o código original e mantém a revisão obrigatória antes da análise. O `.osa` registra em `import_metadata.compatibility` o layout usado, o código de referência e o modo `structural_probe`. Este modo informa o reconhecimento do layout observado, sem certificar a semântica de todos os campos de uma versão diferente.

Falhas em registros auxiliares de ações e combinações aparecem como aviso e em `import_metadata.decode_warnings`: esses registros já não geram ações ativas no OSA. Se a falha ocorrer dentro de uma viga ou pilar, a leitura do elemento também falha e a importação é recusada. Falhas nos registros necessários, referências ou contagens impedem substituir o modelo aberto; a mensagem identifica o código, a classe e a posição da diferença quando disponíveis.

**As regressões reais de importação geométrica usam os arquivos específicos 3419 e 2281 descritos acima.** As regressões adicionais de troca de código com 2281, 3028 e 9999 usam cópias do binário 3419 nas quais somente as tags de serialização foram alteradas; não são arquivos produzidos por versões correspondentes do programa de origem. Um layout diferente exige ampliar o decodificador, mantendo o mesmo contrato de saída para OSA. A validação de uma amostra não garante cobertura de todos os projetos do mesmo código.

`source_evidence.beam_groups` identifica as vigas originais e seus trechos; `source_evidence.beams` contém os trechos individuais; `source_evidence.points` contém os nós intermediários. `member_sources` relaciona cada barra OSA aos IDs da viga e do trecho de origem. O relatório distingue a quantidade de vigas da quantidade de trechos.

## Organização do código

```text
osa/transcriptions/
├── contracts.py              # opções, resultado, erro e contrato do importador
├── __init__.py               # registro e seleção dos formatos
├── eberick.py                # tradução das evidências para o projeto OSA v2
├── plates.py                 # contrato e ponto de conexão para as futuras placas
└── eberick_reader/
    ├── core.py               # ZIP, bytes, tipos, referências e índices
    ├── decode.py             # layouts estudados do lançamento
    ├── slabs.py              # evidências e regiões binárias das lajes
    └── __init__.py
```

A abertura segue `MainWindow → ProjectService → ProjectRepository → import_project → ProjectSerializer`. O importador produz um dicionário no formato nativo; não cria arquivos temporários de projeto. O serializador continua responsável por aplicar um candidato validado ao modelo, e o repositório mantém o salvamento atômico do `.osa`.

Para adicionar outro formato, implemente `name`, `extensions` e `read(path, options) -> ImportResult`, registre com `register_importer` e inclua a extensão em `_import_file_filter` da interface. O resultado deve seguir o formato nativo OSA. Importe módulos pesados apenas dentro do importador correspondente.

## Testes

Com as dependências de desenvolvimento do OSA instaladas:

```bash
python -m pytest tests/test_eberick_import.py tests/test_eberick_import_ui.py tests/test_plate_transfer.py tests/test_persistence.py tests/test_model.py tests/test_domain.py tests/test_pynite_adapter.py -q
```

Os testes sem arquivo usam evidências sintéticas. Para incluir a regressão com o **arquivo específico `teste_conv` desta investigação**, em Linux/macOS:

```bash
OSA_EBERICK_PRJ=/caminho/teste_conv.prj.zip QT_QPA_PLATFORM=offscreen PYVISTA_OFF_SCREEN=false python -m pytest tests/test_eberick_import.py tests/test_eberick_import_ui.py -q
```

Para incluir a importação geométrica completa do Arara Azul, inclusive pela janela real e com salvamento/reabertura, defina também `OSA_EBERICK_FOUNDATIONS_PRJ="/caminho/Arara Azul - Ampliação.prj"`. O nome dessa variável foi mantido por compatibilidade com a regressão inicial das sapatas.

Não definir `PYVISTA_OFF_SCREEN=true` no teste da janela: o OSA usa o interactor Qt/VTK. O backend Qt pode ser `offscreen` para a automação. A regressão verifica conteúdo e hash do exemplo; não é um teste parametrizado para qualquer projeto.

Nesta entrega foram verificados abertura real dos dois arquivos pela janela com diálogos controlados, salvamento/reabertura, unidades, seções, referências, cancelamento, recusa de conteúdo não suportado, preservação do arquivo original, variantes sintéticas de código e rejeição de layout corrompido tanto no código de referência quanto em outro código. No Arara Azul, as regressões também verificam recusa de trecho omitido, ID de trecho duplicado, referência a ponto inexistente, parede corrompida e corrupção em trecho posterior de viga. Não foi validada equivalência de resultados de cálculo com o programa de origem.

## Aparência dos diálogos

Os diálogos de importação mantêm fundo claro e cores explícitas para texto, conteúdo do relatório, campos e popups, incluindo as seleções das listas. A paleta local evita texto branco sobre branco ou preto sobre preto quando o sistema operacional usa aparência escura. O tema geral do OSA recebido continua sendo claro.
