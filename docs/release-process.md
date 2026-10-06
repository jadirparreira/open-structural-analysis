# Processo de releases

Este documento registra as decisões iniciais para distribuição do Open Structural Analysis.

## Distribuição Linux

A primeira distribuição será feita como um AppImage para Linux.

O alvo inicial é:

- Ubuntu 22.04 ou superior;
- arquitetura x86_64/64 bits.

O pacote oficial deverá ser compilado em um ambiente baseado no Ubuntu 22.04, ou em um ambiente equivalente, para preservar a compatibilidade com sistemas mais novos sem depender de bibliotecas mais recentes do Ubuntu usado no desenvolvimento.

O Ubuntu 26 continuará sendo aceito como ambiente de desenvolvimento, mas não será o ambiente de referência para a compilação dos releases Linux.

## Versionamento

O projeto usará versionamento baseado em calendário (Calendar Versioning), no formato:

```text
YYYY.MM
```

O primeiro release planejado será:

```text
2026.10
```

As tags Git usarão o mesmo número com o prefixo `v`:

```text
v2026.10
```

Os releases serão publicados como versões estáveis. Não serão utilizados, inicialmente, sufixos como `rc`, `beta` ou `pre`.

Quando uma versão precisar de correções ou melhorias, elas serão incluídas no próximo release calendarizado. Por exemplo:

```text
2026.10
2026.11
2026.12
```

## Primeiro release

O primeiro release Linux deverá conter, no mínimo:

- o AppImage executável;
- instruções de execução;
- notas resumindo o conteúdo da versão;
- o checksum SHA-256 do arquivo distribuído.

O processo de compilação e publicação será automatizado posteriormente com GitHub Actions.

## Identidade do AppImage

O identificador usado na integração com o desktop Linux será:

```text
openstructuralanalysis
```

Os arquivos principais da estrutura do AppImage usarão estes nomes:

```text
openstructuralanalysis.desktop
openstructuralanalysis.svg
```

O nome exibido ao usuário será `Open Structural Analysis`, e o executável continuará sendo `open-structural-analysis`.
