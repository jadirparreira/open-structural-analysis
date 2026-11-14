# Benchmarks estruturais

## Convenções atuais

- o modelo do OpenSA usa forças em kN e comprimentos em m;
- as geometrias paramétricas das seções são informadas em mm;
- deslocamentos são lidos nos campos `DX`, `DY` e `DZ`;
- rotações são lidas nos campos `RX`, `RY` e `RZ`;
- reações são lidas nos campos `RXN_FX`, `RXN_FY`, `RXN_FZ`, `RXN_MX`,
  `RXN_MY` e `RXN_MZ`;
- esforços de barra são lidos em `member_results`, nas amostras `start`, `end`
  e `samples`.

As fórmulas de referência ficam nos testes ou nos helpers independentes, sem
reutilizar o serviço de propriedades do solver que está sendo verificado.

## Tolerâncias

As tolerâncias devem ser explícitas. Forças, momentos, deslocamentos e
rotações podem possuir escalas diferentes; não usar uma tolerância global
silenciosa para todas as grandezas.
