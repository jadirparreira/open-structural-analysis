# Open Structural Analysis

Aplicação open source para modelagem e análise estrutural tridimensional, desenvolvida em Python com PySide6, PyVista e PyNite.

O programa está sendo desenvolvido para oferecer um ambiente integrado de criação, edição, visualização e análise de estruturas. A estrutura é representada por nós e membros conectados entre si, aos quais podem ser atribuídos materiais, seções transversais, apoios, vinculações, carregamentos e demais propriedades necessárias à análise estrutural.

A interface combina ferramentas de modelagem com uma cena tridimensional interativa, permitindo visualizar a geometria da estrutura, seus elementos, seções, eixos locais, apoios e condições de vinculação. O objetivo é tornar o processo de definição e interpretação do modelo estrutural mais claro, visual e acessível.

O projeto utiliza uma arquitetura modular, separando o domínio estrutural, a interface gráfica, a renderização tridimensional, a persistência dos projetos e o processamento numérico. A análise estrutural é realizada com apoio do PyNite, enquanto o PyVista é responsável pela visualização 3D e o PySide6 pela interface da aplicação.

O Open Structural Analysis encontra-se em desenvolvimento ativo. A base de modelagem e visualização está sendo construída progressivamente, enquanto os recursos relacionados ao processamento estrutural, carregamentos, combinações e apresentação de resultados continuam em evolução.

## Instalação e execução

Requisitos: Git, Python entre 3.10 e 3.13 e [uv](https://docs.astral.sh/uv/).

Clone o repositório e entre no diretório do projeto:

```bash
git clone https://github.com/jadirparreira/open-structural-analysis.git
cd open-structural-analysis
```

Instale as dependências e execute a aplicação:

```bash
uv sync
uv run open-structural-analysis
```

O comando `uv sync` cria o ambiente virtual e instala as dependências nas versões registradas em `uv.lock`. Para executar diretamente pelo módulo Python, use:

```bash
uv run python -m osa
```
