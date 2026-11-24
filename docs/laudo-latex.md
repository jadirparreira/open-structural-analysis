# Laudo e memorial em LaTeX

O programa gera dois documentos no estilo de laudo técnico em LaTeX (classe
`article`, Latin Modern, tabelas `booktabs`, cabeçalho e rodapé com
`fancyhdr`, legendas em negrito):

- **Laudo técnico da estrutura** — comando `REPORT` ou botão *Laudo estrutural*
  na paleta de verificação.
- **Memorial de cálculo de elemento** — botão *Exportar* do memorial, com as
  opções *PDF (LaTeX)*, *Projeto LaTeX (.tex)* e *Documento Word (.docx)*.

## Conteúdo do laudo

| Seção | Origem dos dados |
| --- | --- |
| Capa | Título, obra, local, responsável e revisão informados no diálogo; vista 3D do modelo colorida pela situação no ELU |
| Objeto e descrição | Dimensões envolventes, número de nós, barras, placas e apoios, perfis e comprimentos |
| Normas | Lista padrão (NBR 8800, 8681, 6120, 6123), editável no `.tex` |
| Materiais | Materiais atribuídos às barras e placas |
| Ações e combinações | Grupo de ações ativo; expressão de cada combinação com γ·ψ₀·ψ já multiplicados |
| ELU | Resultados do `VERIFY`: η máximo por perfil, elemento, verificação e combinação críticos; lista dos elementos reprovados |
| ELS | Deslocamento vertical, horizontal e total máximos por combinação de serviço |
| Deformadas | Figuras vetoriais geradas dos resultados da análise (ver abaixo) |
| Geometria | Vista 3D e planta do modelo |
| Quantitativo | Comprimento e peso por material e perfil (massa linear da seção) |
| Conclusões | Resumo automático do ELU e recomendações padrão |

O texto gerado é um ponto de partida: o `.tex` fica salvo em
`<nome>_latex/laudo.tex` ao lado do PDF para o engenheiro complementar a
descrição, as premissas e as conclusões.

## Deformadas geradas por código

As deformadas não são capturas de tela. `osa/reports/figures.py` projeta
ortograficamente o modelo (vista isométrica ou elevação para modelos planos)
e desenha, com matplotlib sem janela:

- a indeformada em cinza claro;
- cada barra pelos 21 pontos amostrados na análise (`samples` com
  `deflection_x/y/z` em coordenadas globais), multiplicados pelo fator de
  escala, coloridos pelo deslocamento total em mm;
- os elementos de placa pelos deslocamentos nodais da malha;
- o ponto de deslocamento máximo, os apoios, a barra de cores e o triedro.

O fator de escala é automático (o maior deslocamento ocupa cerca de 6 % da
maior dimensão do modelo, arredondado para 1, 2 ou 5 × 10ⁿ) ou informado no
diálogo. As figuras são salvas em PDF vetorial dentro de `fig/`.

## Compilação

`osa.reports.latex.find_latex_engine()` procura, nesta ordem:

1. a variável de ambiente `OSA_LATEX_ENGINE` (caminho ou nome do executável);
2. `pdflatex`, `lualatex`, `xelatex` ou `tectonic` no `PATH` (MiKTeX, TeX Live);
3. o Tectonic embutido no instalador (`osa/resources/latex/`) ou preparado no
   código-fonte (`build-tools/tectonic/<plataforma>/`).

O preâmbulo usa `iftex` e funciona tanto no pdfLaTeX (`inputenc`/`fontenc`/
`lmodern`) quanto no XeTeX/LuaTeX (`fontspec`, que também usa Latin Modern).

Sem nenhum compilador, a exportação em PDF salva a pasta com o `.tex` e as
figuras e avisa o usuário; ela pode ser compilada depois em outra máquina ou
no Overleaf.

### Tectonic embutido

`scripts/prepare-latex-engine.py` baixa o binário oficial do
[Tectonic](https://tectonic-typesetting.github.io/) (licença MIT) fixado por
versão e SHA-256, no mesmo padrão do conversor DWG. Os scripts de build do
Windows e do AppImage chamam esse script, e os `.spec` do PyInstaller copiam o
executável para `osa/resources/latex/`.

O Tectonic baixa sob demanda apenas os pacotes LaTeX usados pelo documento, no
cache do usuário. Por isso a **primeira** exportação em PDF precisa de
internet; as seguintes funcionam sem conexão.
