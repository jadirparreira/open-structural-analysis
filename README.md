# Open Structural Analysis

Aplicação open source para modelagem e análise estrutural tridimensional, desenvolvida em Python com PySide6, PyVista e PyNite.

O programa está sendo desenvolvido para oferecer um ambiente integrado de criação, edição, visualização e análise de estruturas. A estrutura é representada por nós e membros conectados entre si, aos quais podem ser atribuídos materiais, seções transversais, apoios, vinculações, carregamentos e demais propriedades necessárias à análise estrutural.

A interface combina ferramentas de modelagem com uma cena tridimensional interativa, permitindo visualizar a geometria da estrutura, seus elementos, seções, eixos locais, apoios e condições de vinculação. O objetivo é tornar o processo de definição e interpretação do modelo estrutural mais claro, visual e acessível.

O projeto utiliza uma arquitetura modular, separando o domínio estrutural, a interface gráfica, a renderização tridimensional, a persistência dos projetos e o processamento numérico. A análise estrutural é realizada com apoio do PyNite, enquanto o PyVista é responsável pela visualização 3D e o PySide6 pela interface da aplicação.

O Open Structural Analysis encontra-se em desenvolvimento ativo. A base de modelagem e visualização está sendo construída progressivamente, enquanto os recursos relacionados ao processamento estrutural, carregamentos, combinações e apresentação de resultados continuam em evolução.

As coordenadas dos nós são expressas em metros e arredondadas ao milímetro
mais próximo (`0,001 m`) na criação, edição, cópia e divisão de membros.
Projetos existentes mantêm as coordenadas originais ao serem abertos, evitando
unir nós ou reduzir membros a comprimento zero sem uma edição explícita.

## Instalação e execução

Requisitos: [Git](https://git-scm.com/downloads), [Python entre 3.10 e 3.13](https://www.python.org/downloads/) e [uv](https://docs.astral.sh/uv/).

Clone o repositório e entre no diretório do projeto:

```bash
git clone https://github.com/jadirparreira/open-structural-analysis.git
cd open-structural-analysis
```

Instale as dependências:

```bash
uv sync
```

O comando `uv sync` cria o ambiente virtual e instala as dependências nas versões registradas em `uv.lock`.

Para habilitar a importação de DWG na execução pelo código-fonte, prepare o leitor
local uma vez (no Linux, são necessários compilador C e `make`):

```bash
uv run python scripts/prepare-dwg-converter.py
```

Os instaladores Windows e o AppImage já incluem esse leitor.

Execute a aplicação:
```bash
uv run open-structural-analysis
```

O comando `uv run open-structural-analysis` inicia o programa utilizando o ambiente virtual gerenciado pelo uv.

### Atualização

Para atualizar uma cópia já clonada do projeto, execute no diretório do repositório:

```bash
git pull
uv sync
uv run open-structural-analysis
```

O `git pull` baixa as alterações do GitHub e o `uv sync` atualiza o ambiente quando as dependências do projeto mudam.

## Referências de desenho

Importe plantas DXF ou DWG em **Arquivo → Importar referência…** e configure
visibilidade, origem e plano pelo botão **Configurar referência**, na paleta
de Geometria. Consulte [Referências DXF e DWG](docs/referencias-dxf.md).

## Integração MCP com Claude

O Claude Code usa o `.mcp.json` do projeto para conectar-se ao OpenSA. Para o
Claude Desktop Chat, configure o adaptador local `mcp-remote`. Consulte
[Claude Desktop e Claude Code](docs/claude-mcp.md) para os dois caminhos e os
passos de conexão.
