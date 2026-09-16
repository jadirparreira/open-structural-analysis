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
- `osa/persistence`: projeto JSON versionado e migrações.
- `osa/analysis`: contrato do solver e adaptador isolado do PyNite.
- `osa/app.py`: composition root da aplicação.

`osa/model.py` e `osa/scene.py` são fachadas de compatibilidade para imports da
versão 0.1. Elas não contêm regras ou renderização próprias.

## Unidades

As coordenadas continuam usando a unidade definida pelo projeto. O catálogo W
registra explicitamente dimensões em milímetros, área em cm², massa linear em
kg/m e propriedades dos materiais nas unidades indicadas pelo nome dos campos.
Conversões para o solver devem ocorrer no adaptador, nunca nos widgets.

## Persistência

O formato atual é `open-structural-analysis/v2`. O leitor aceita arquivos v1 e
preserva restrições e propriedades opcionais que o carregador antigo ignorava.
Resultados carregados só são considerados atuais quando sua revisão coincide
com a revisão do modelo.

## Análise

O adaptador PyNite já estabelece a fronteira, traduz nós e restrições e recusa
membros enquanto ainda faltarem propriedades como `Iy`, `Iz` e `J`. Isso evita
resultados obtidos com propriedades inventadas. A tradução de ações será
ativada quando os respectivos tipos forem definidos no domínio.
