# Processo de releases

Este documento registra as decisões iniciais para distribuição do Open Structural Analysis.

## Distribuição Linux

A primeira distribuição será feita como um AppImage para Linux.

O alvo inicial é:

- Ubuntu 22.04 ou superior;
- arquitetura x86_64/64 bits.

O pacote oficial deverá ser compilado em um ambiente baseado no Ubuntu 22.04, ou em um ambiente equivalente, para preservar a compatibilidade com sistemas mais novos sem depender de bibliotecas mais recentes do Ubuntu usado no desenvolvimento.

O Ubuntu 26 continuará sendo aceito como ambiente de desenvolvimento, mas não será o ambiente de referência para a compilação dos releases Linux.

## Distribuição Windows

A distribuição Windows será feita por meio de um instalador executável gerado com Inno Setup.

O alvo inicial é:

- Windows 10 versão 22H2 ou superior;
- Windows 11;
- arquitetura x86_64/64 bits.

Não haverá, inicialmente, suporte oficial para Windows 7, Windows 8, Windows 8.1, versões de 32 bits ou Windows ARM.

O instalador deverá incluir o aplicativo e todas as suas dependências, criar os atalhos do programa, usar o nome `Open Structural Analysis`, usar o ícone oficial e disponibilizar um desinstalador.

Não será distribuído um pacote portátil `.zip` nesta etapa.

## Builds oficiais

As builds oficiais para Linux e Windows serão realizadas com Python 3.13.

## Automação dos releases

A automação será implementada em um workflow do GitHub Actions chamado:

```text
release.yml
```

Esse workflow terá três jobs principais:

```text
build-linux-appimage
build-windows-installer
publish-release
```

O job `build-linux-appimage` será responsável por gerar:

```text
OpenStructuralAnalysis-2026.1-x86_64.AppImage
```

O job `build-windows-installer` será responsável por gerar:

```text
OpenStructuralAnalysis-2026.1-Windows-x86_64-Setup.exe
```

O job `publish-release` anexará os dois arquivos e o arquivo de checksums ao release do GitHub:

```text
SHA256SUMS.txt
```

O workflow de release será acionado pela criação de uma tag no formato:

```text
vYYYY.MM
```

Por exemplo:

```text
v2026.1
```

Antes da publicação, a automação deverá validar que a versão da tag corresponde à versão definida no `pyproject.toml`, executar os testes e verificar se os dois pacotes foram gerados corretamente.

Não será gerado pacote portátil `.zip` para Windows e não haverá assinatura digital nesta etapa.

## Versionamento

O projeto usará versionamento baseado em calendário (Calendar Versioning), no formato:

```text
YYYY.MM
```

O primeiro release planejado será:

```text
2026.1
```

As tags Git usarão o mesmo número com o prefixo `v`:

```text
v2026.1
```

Os releases serão publicados como versões estáveis. Não serão utilizados, inicialmente, sufixos como `rc`, `beta` ou `pre`.

Quando uma versão precisar de correções ou melhorias, elas serão incluídas no próximo release calendarizado. Por exemplo:

```text
2026.1
2026.2
2026.3
```

## Primeiro release

O primeiro release Linux deverá conter, no mínimo:

- o AppImage executável;
- instruções de execução;
- notas resumindo o conteúdo da versão;
- o checksum SHA-256 do arquivo distribuído.

O processo de compilação e publicação será automatizado pelo workflow `release.yml` do GitHub Actions.

O release Windows deverá conter, além do AppImage Linux:

- o instalador Windows;
- instruções de instalação e execução;
- o checksum SHA-256 dos arquivos distribuídos.

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
