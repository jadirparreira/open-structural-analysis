# MCP local — v5

O MCP opera sobre o modelo aberto no Open Structural Analysis. Ative-o em
**Arquivo > Configurações > MCP > Servidor MCP**. Ele não inicia automaticamente
nem abre o OpenSA por conta própria. O transporte é Streamable HTTP em:

```text
http://127.0.0.1:8765/mcp-opensa
```

A conexão funciona com a versão de desenvolvimento e com os pacotes de release;
o release não precisa de checkout, Python ou uv para iniciar o servidor. Cada
cliente MCP ainda precisa da sua própria configuração ou adaptador.

## Auditoria e compatibilidade

A atualização amplia o servidor de **74 para 107 ferramentas**. As 74 operações
anteriores continuam correspondendo a recursos existentes do programa; nenhuma
ferramenta inteira precisou ser retirada. Foram atualizados seus argumentos,
retornos e descrições. O [inventário completo](mcp-ferramentas.md) lista as 107
ferramentas e seus parâmetros.

Novas operações:

- Catálogos: `get_capabilities`, `list_profiles`.
- Placas: `list_plates`, `create_plate`, `update_plate_properties`, `delete_plate`,
  `split_plate`, `join_plates`.
- Geometria: `move_elements`, `set_element_display_name`, `copy_element_properties`.
- Componentes: `list_node_components`, `set_node_component`.
- Cargas de placas: `add_plate_pressure_profiles`, `add_plate_edge_load`.
- Verificação: `get_verification_state`, `get_verification_results`,
  `run_verification`, `set_member_calculation_properties`, `ungroup_verification_elements`.
- Detalhamento: `set_detail_subtractions`, `set_member_end_cuts`.
- Folhas: criação de vistas reais, cotas, textos e detalhes de componentes; consulta e edição de vistas.
- Arquivos: salvar `.osa`, exportar folhas PDF e eixos de barras DXF, importar referência DXF/DWG.

As operações de sessão abrem o editor mesmo quando a janela está na tela inicial.
As alterações de folhas também sincronizam o modo Projeto na interface.
Os arquivos de saída exigem caminho absoluto e `overwrite=true` para substituir um arquivo existente.
O DXF contém os eixos das barras; não é uma prancha de fabricação.
O detalhamento de bases representa a geometria cadastrada e não dimensiona chumbadores, soldas ou fundações.

A opção `snap_enabled` foi retirada: ela não alterava a captura e sempre retornava
verdadeiro. `node_components_visible` agora expõe a preferência real dos componentes.
Essa preferência continua sujeita às regras da sessão: componentes não aparecem em
Ações, Análise e Verificação. O alias antigo `Memorial` continua aceito por
`set_session`, apontando para Verificação.

As sessões são Geometria, Verificação, Ações, Análise e Detalhamento.
`get_session_state` consulta a sessão; `set_session` muda a sessão visível.

## Modelo e unidades

Comece por `get_capabilities` e `get_project_summary`. Consulte materiais,
famílias e perfis antes de criar elementos. Use os identificadores retornados pelo
OpenSA (`N1`, `B1`, `P1` etc.); nomes de exibição não substituem esses identificadores.

Coordenadas e comprimentos de cálculo usam m; dimensões de seções, componentes e
espessuras de placas usam mm. Forças usam kN e momentos kN·m. Pressões usam kN/m²;
forças e momentos distribuídos nas arestas usam kN/m e kN·m/m.

`update_applied_load` edita cargas existentes preservando seu nome. Para pressões,
`value` define pressão uniforme e `pressure_profiles: [Xi,Xf,Yi,Yf]` define os quatro
valores dos perfis locais. Alterar somente o caso de carga preserva todos os valores.
Nas arestas, `edge_index` começa em zero; forças usam os dois extremos e momentos
usam `value` e referência local. Arestas coincidentes com barras recebem carga pela barra.

`delete_elements` exclui nós, barras e barras rígidas em lote, com `dry_run` e
`cascade`. Nós ligados a placas continuam protegidos; use `delete_plate` para
remover uma placa. Essa operação também remove suas cargas e limpa nós órfãos
pelas regras do domínio.

## Resultados e visualização

`run_analysis` usa as combinações do projeto, com estados limite CAR, ELU e ELS.
Os resultados ficam associados à revisão estrutural. Alterações estruturais
invalidam a análise; alterações apenas visuais preservam os resultados.

`set_analysis_view` aceita `result_kind: "bar"` ou `"plate"`. A seleção troca a
lista e os diagramas exibidos no modelo. Informe a família explicitamente quando
o rótulo for compartilhado, como `Fletor Y (My)`. Os catálogos completos de rótulos
e chaves estão em `get_capabilities`; as chaves antigas de barras continuam aceitas.
Omitir a combinação preserva a seleção atual.

Também estão disponíveis:

- `deformation_scale`: 1 ou múltiplos de 10 entre 10 e 100;
- `diagram_scale`: 0,1 a 1,0 em passos de 0,1;
- `plate_result_display_mode`: modos retornados por `get_capabilities`;
- `set_analysis_diagrams_visible`: altera a visibilidade da família ativa;
- consultas de resultados nodais, barras, placas e reações, pelos esquemas do inventário.

Momentos de placas usam kN·m/m, cortantes kN/m e tensões de membrana kN/m².
Deslocamentos exibidos são em mm; os campos numéricos das consultas mantêm as
unidades especificadas em cada ferramenta.

`run_verification` usa a mesma rotina e as mesmas limitações da interface. Exige
análise válida, aceita todas as barras, uma barra ou um grupo completo. Trabalha
sobre uma cópia e recusa publicar resultados se o modelo mudar durante a execução.
Os comprimentos e coeficientes definidos pelo usuário são preservados. Consulte
os status e limitações de cada resultado; executar a ferramenta não implica que
todos os elementos sejam verificáveis.

Acesso ao MCP não substitui as operações interativas de edição de folhas,
importação de desenhos ou exportação de documentos que não constem do inventário.

## Pacotes de release

O servidor utiliza asyncio/h11 explicitamente e não depende da configuração de
console do Uvicorn. Isso evita a falha de inicialização quando o executável Windows
sem console tem `stdout`/`stderr` ausentes. Os dois arquivos `.spec` carregam o hook
`packaging/hooks/hook-osa.mcp.server.py`, que inclui os módulos dinâmicos e os
metadados necessários. O plugin é localizado nos recursos do pacote congelado,
independentemente do diretório atual.

O workflow de release bloqueia a publicação se o diagnóstico MCP falhar:

- Linux: executa o AppImage final com extração temporária, sem exigir FUSE.
- Windows: instala silenciosamente o instalador gerado e testa o executável instalado.

O diagnóstico `--mcp-self-test /caminho/relatorio.json` usa modelo e configurações
temporários, simula ausência de console, verifica recursos do plugin e faz uma
conexão MCP HTTP real: inicialização, listagem das ferramentas, leitura e criação
de um nó. Não altera o projeto aberto nem as configurações pessoais. Em
Windows, informe um caminho absoluto adequado para o relatório.

Para validar um pacote durante o desenvolvimento:

```bash
uv run python scripts/check-packaged-mcp.py /caminho/do/executavel-ou.AppImage
```

Esse verificador executa o programa fora do checkout, remove PYTHONPATH/PYTHONHOME
e exige um processo congelado com relatório de sucesso. O diagnóstico valida o
servidor e os recursos; não comprova que o usuário selecionou o plugin no cliente.

## Clientes e ativação

Ao ativar o servidor, o OpenSA copia o plugin local para o marketplace pessoal e
tenta registrá-lo no ChatGPT Desktop. Reinicie o cliente se ele já estava aberto
e selecione OpenSA no chat Work. O plugin local está na versão 0.3.0.

Para outros clientes, configure o endpoint acima. O exemplo `.mcp.json` da raiz
é uma configuração de cliente, não uma dependência do servidor empacotado.
Consulte [Claude Desktop e Claude Code](claude-mcp.md) para os exemplos desse cliente.

O servidor escuta somente em `127.0.0.1`, sem credencial adicional. Enquanto
ativo, processos locais com acesso à porta podem consultar e alterar o modelo.
Ao desativar a opção ou fechar o OpenSA, o servidor é encerrado.

### Wood-Armer e von Mises

A família de placas também oferece quatro momentos Wood-Armer e três tensões
von Mises. As chaves exatas aparecem em `get_capabilities`; os valores centrais
e nodais aparecem em `get_plate_analysis_results`. Consulte
[Wood-Armer e von Mises nas placas](plate-postprocessing.md) para eixos, faces,
unidades, interpolação e limites de aplicação.
