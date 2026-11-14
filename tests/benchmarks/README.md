# Benchmarks do Open Structural Analysis

Esta pasta reúne verificações reproduzíveis do comportamento estrutural do
OpenSA. Ela não substitui os testes unitários: os benchmarks exercitam o fluxo
completo de modelagem, carregamento, análise e leitura de resultados.

## Categorias

- `structural/analytical/`: comparação com soluções fechadas independentes;
- `structural/invariants/`: equilíbrio e invariantes físicos;
- `structural/external/`: comparação com referências de outros solvers;
- `structural/convergence/`: efeito da discretização do modelo.

Os benchmarks estruturais devem usar as APIs reais do OpenSA e permanecer
independentes da interface gráfica.

## Executar

```text
python -m pytest tests/benchmarks/structural -q
ruff check tests/benchmarks
```

## Evidência

A ordem de confiança adotada é:

1. solução analítica independente;
2. equilíbrio e invariantes físicos;
3. referência externa, como OpenSees;
4. regressão de comportamento já aceito.

Cada referência externa deve registrar unidades, convenções de sinais, versão
do solver e origem dos valores.
