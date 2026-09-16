# Open Structural Analysis

Aplicação open source para modelagem e análise de estruturas, construída em Python, PySide6 e PyVista. O projeto possui domínio, serviços, comandos, renderização, persistência e integração do solver em camadas independentes.

## Instalação no Linux

É recomendável usar um ambiente virtual com Python 3.10 a 3.13 (algumas bibliotecas gráficas ainda não distribuem wheels para versões muito recentes do Python).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
open-structural-analysis
```

Para desenvolvimento:

```bash
pip install -e '.[dev]'
pytest
```

## O que esta versão faz

- Cria nós por coordenadas X, Y e Z;
- Cria barras ligando dois nós existentes;
- Mostra o modelo em uma cena 3D com grid, identificadores, apoios e eixos locais;
- Permite selecionar e editar nós e membros pelo painel de propriedades;
- Gerencia materiais e famílias de seções;
- Salva e abre projetos no formato JSON versionado;
- Aceita os comandos `node`, `member` e `portico`.

## Próximas etapas

1. Definição das ações, casos e combinações de carga;
2. Complementação das propriedades de seção exigidas pelo PyNite;
3. Processamento, resultados e diagramas de esforços.

Os eixos locais são X (vermelho), Y (amarelo) e Z (verde). Consulte [a arquitetura](docs/architecture.md) para conhecer as responsabilidades dos módulos e a política de unidades.
