# Arquitetura

O Open Structural Analysis usa uma arquitetura em camadas. As dependências
apontam para o domínio; o domínio não importa PySide6, PyVista ou PyNite.

```text
ui / commands -> services -> domain
                         |-> persistence
                         |-> analysis -> PyNite
rendering -----------------> domain (somente leitura)
```

## Responsabilidades

- `osa/domain`: entidades, agregado estrutural e invariantes.
- `osa/services`: casos de uso e coordenação de operações.
- `osa/commands`: parser e sessão da linha de comandos, sem Qt.
- `osa/rendering`: cena e renderizadores PyVista/VTK.
- `osa/ui`: componentes PySide6 e composição visual.
- `osa/data`: catálogos externos versionados.
- `osa/sections`: geometria paramétrica e cálculo de propriedades das seções.
- `osa/persistence`: projeto JSON versionado e migrações.
- `osa/analysis`: contrato do solver e adaptador isolado do PyNite.
- `osa/app.py`: composition root da aplicação.

`osa/model.py` e `osa/scene.py` são fachadas de compatibilidade para imports da
versão 0.1. Elas não contêm regras ou renderização próprias.

## Unidades

As coordenadas continuam usando a unidade definida pelo projeto. Os catálogos
de seções registram somente a geometria de origem em milímetros. Área, massa
linear, inércias e constante de torção são calculadas pelo núcleo paramétrico.
As famílias laminadas usam perfis do catálogo; famílias formadas, tubulares e
barras mantêm o catálogo vazio e recebem suas dimensões diretamente no painel
da seção. Em ambos os casos, as propriedades derivadas seguem o mesmo núcleo
paramétrico e a mesma idealização geométrica retangular ou tubular.
Os contornos dos perfis W, U, L, T e I laminados, além de U, C, Z, L e Cartola
formados, são gerados diretamente por funções paramétricas. Cada família usa
seus próprios parâmetros, raios de dobra e detalhes de enrijecimento no SVG.
W, U e I usam seus contornos amostrados também no cálculo de área, centroide e
inércias; as seções formadas, L e T mantêm a idealização retangular adotada
para suas propriedades.
Conversões para o solver devem ocorrer no adaptador, nunca nos widgets.

## Persistência

O formato atual é `open-structural-analysis/v2`. O leitor aceita arquivos v1 e
preserva restrições e propriedades opcionais que o carregador antigo ignorava.
Resultados carregados só são considerados atuais quando sua revisão coincide
com a revisão do modelo.

## Análise

O adaptador PyNite estabelece a fronteira, traduz nós e restrições e recebe
`A`, `Iy`, `Iz` e `J` calculados a partir da geometria paramétrica. A tradução
de ações será ativada quando os respectivos tipos forem definidos no domínio.
