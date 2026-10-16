# Importação experimental de projetos Eberick

A opção **Abrir modelo** aceita somente `.osa`. Use **Importar modelo** para `.prj` e `.prj.zip`; ela está na tela inicial, no menu Arquivo e no atalho `Ctrl+I`. O PRJ pode ser binário direto ou um ZIP com o membro `__DADOS__`; o leitor verifica os bytes, não apenas a extensão.

## Primeiro teste

1. Abra o OSA normalmente e use **Importar modelo** (`Ctrl+I`).
2. Selecione o arquivo `teste_conv.prj` ou `teste_conv.prj.zip`.
3. Confira as opções: comprimento `cm`, força `kgf`, cota do primeiro pavimento `0 m`, Poisson adotado `0,2`.
4. Para reproduzir o teste executado, mantenha ativados os trechos inferiores, as ligações rígidas e a leitura das propriedades de concreto.
5. Importe. O resumo informa o que foi transcrito e o que precisa ser revisto.
6. Use **Salvar**. O primeiro salvamento pede um destino `.osa`; o PRJ de origem não é sobrescrito.
7. Reabra o `.osa`. A geometria e o relatório de importação acompanham o modelo.

No exemplo `teste_conv`, as opções acima geram **28 nós, 16 barras (8 vigas e 8 trechos de pilar) e 16 ligações rígidas**, com cotas `−0,40`, `0,00` e `3,00 m`. O trecho inferior é uma hipótese baseada na altura do primeiro pavimento, não uma profundidade de fundação comprovada. As seções candidatas são convertidas de cm para mm, e as propriedades de materiais para kN/m² e kN/m³.

## Escopo desta versão

- Perfil interno de lançamento **3419**, estudado no arquivo de teste. O código interno não é a versão comercial do Eberick.
- Vigas retas com um trecho e seções retangulares reconhecidas; pilares com continuidade identificável entre pavimentos.
- Nomes, pavimentos, geometria, seções e propriedades candidatas de concreto das configurações de pavimento.
- Deslocamentos de extremidade representados opcionalmente por ligações rígidas do OSA. A equivalência analítica dessa idealização ainda precisa ser verificada.
- Representações CAD duplicadas são preservadas no relatório e excluídas da contagem física somente quando correspondem a pilares já identificados.

**Apoios, molas, liberações, parâmetros 0/0,15, cargas, paredes e combinações ainda não são transcritos para ações/vínculos ativos do modelo de cálculo.** As evidências lidas ficam em `import_metadata.source_evidence` dentro do `.osa`. Os nós importados ficam livres e as barras sem liberações até a revisão no editor. O peso próprio é aplicado pelas ferramentas do próprio OSA, sem duplicação pelo importador.

O material pode usar as propriedades candidatas lidas do PRJ; nesse caso, o coeficiente de Poisson é uma opção explícita, e G é calculado por `E / [2(1 + ν)]`. Se essa opção for desativada, o importador utiliza um concreto de referência do catálogo OSA, identificado como material para revisão. Sobreposições particulares de material, centros/eixos locais e rotações das seções precisam ser conferidos.

Antes da primeira análise, o OSA reapresenta o resumo e pede confirmação de que unidades, geometria, materiais, apoios, vínculos e cargas foram revistos. A pendência acompanha o `.osa` até a confirmação. O adaptador PyNite também verifica essa pendência para os fluxos sem interface.

Arquivos com versões não suportadas, layouts recusados, seções não reconhecidas, elementos sem continuidade ou tipos de lançamento ainda não implementados são rejeitados quando identificados. O modelo atualmente aberto é mantido. A importação experimental não garante cobertura integral do PRJ nem equivalência estrutural.

## Organização do código

```text
osa/transcriptions/
├── contracts.py              # opções, resultado, erro e contrato do importador
├── __init__.py               # registro e seleção dos formatos
├── eberick.py                # tradução das evidências para o projeto OSA v2
└── eberick_reader/
    ├── core.py               # ZIP, bytes, tipos, referências e índices
    ├── decode.py             # layouts estudados do lançamento
    └── __init__.py
```

A abertura segue `MainWindow → ProjectService → ProjectRepository → import_project → ProjectSerializer`. O importador produz um dicionário no formato nativo; não cria arquivos temporários de projeto. O serializador continua responsável por aplicar um candidato validado ao modelo, e o repositório mantém o salvamento atômico do `.osa`.

Para adicionar outro formato, implemente `name`, `extensions` e `read(path, options) -> ImportResult`, registre com `register_importer` e inclua a extensão em `_import_file_filter` da interface. O resultado deve seguir o formato nativo OSA. Importe módulos pesados apenas dentro do importador correspondente.

## Testes

Com as dependências de desenvolvimento do OSA instaladas:

```bash
python -m pytest tests/test_eberick_import.py tests/test_eberick_import_ui.py tests/test_persistence.py tests/test_model.py tests/test_domain.py tests/test_pynite_adapter.py -q
```

Os testes sem arquivo usam evidências sintéticas. Para incluir a regressão com o **arquivo específico `teste_conv` desta investigação**, em Linux/macOS:

```bash
OSA_EBERICK_PRJ=/caminho/teste_conv.prj.zip QT_QPA_PLATFORM=offscreen PYVISTA_OFF_SCREEN=false python -m pytest tests/test_eberick_import.py tests/test_eberick_import_ui.py -q
```

Não definir `PYVISTA_OFF_SCREEN=true` no teste da janela: o OSA usa o interactor Qt/VTK. O backend Qt pode ser `offscreen` para a automação. A regressão verifica conteúdo e hash do exemplo; não é um teste parametrizado para qualquer projeto.

Nesta entrega foram verificados abertura real pela janela com diálogos controlados, salvamento/reabertura, unidades, seções, referências, cancelamento, recusa de conteúdo não suportado e preservação do arquivo original. Não foi validada equivalência de resultados de cálculo com o Eberick.

## Aparência dos diálogos

Os diálogos de importação mantêm fundo claro e cores explícitas para texto, conteúdo do relatório, campos e popups, incluindo as seleções das listas. A paleta local evita texto branco sobre branco ou preto sobre preto quando o sistema operacional usa aparência escura. O tema geral do OSA recebido continua sendo claro.
