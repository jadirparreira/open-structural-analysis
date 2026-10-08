# MCP local

O Open Structural Analysis inicia um servidor MCP local junto com a janela
principal. O servidor escuta somente em loopback:

```text
http://127.0.0.1:8765/mcp-opensa
```

O servidor opera sobre o mesmo `StructuralModel` que está aberto na interface.
As alterações recebidas por MCP atualizam a cena do OpenSA depois da execução.

## Sessões da interface

As sessões visuais disponíveis são `Geometria`, `Ações` e `Análise`. Use
`get_session_state` para consultar a sessão aberta e `set_session` para abrir a
sessão correspondente antes de uma sequência de operações. A sessão permanece
visível enquanto as ferramentas MCP são executadas, permitindo acompanhar as
alterações na tela.

## Ferramentas iniciais

- `get_project_summary`: consulta a quantidade de entidades e a revisão atual.
- `list_nodes`: lista os nós do projeto aberto.
- `list_members`: lista os membros do projeto aberto.
- `list_materials`: lista os materiais disponíveis no catálogo do projeto.
- `list_sections`: lista as famílias de seção compatíveis com um material.
- `create_node`: cria um nó no projeto aberto usando o nome sequencial padrão do
  OpenSA (`N1`, `N2`, ...).
- `delete_node`: exclui um nó pelo nome retornado pelo OpenSA.
- `set_node_supports`: define as seis restrições de um nó.
- `create_member`: cria um membro entre dois nós existentes usando o nome
  sequencial padrão do OpenSA (`B1`, `B2`, ...).
- `delete_member`: exclui um membro pelo nome retornado pelo OpenSA.
- `set_member_rectangular_section`: atribui material e seção retangular usando
  largura e altura explícitas em milímetros.
- `set_member_properties`: atribui material e seção paramétrica a um ou mais
  membros. As dimensões da seção usam milímetros; uma seção de 15 x 30 cm usa
  `{ "b": 150, "h": 300 }`.
- `delete_elements`: exclui nós, membros e barras rígidas em lote. Use
  `dry_run` para revisar o plano e `cascade` para incluir automaticamente as
  dependências conectadas aos nós selecionados.

Com essas ferramentas, uma IA pode modelar uma estrutura passo a passo:

1. consultar materiais e seções;
2. criar os nós nas coordenadas do projeto;
3. criar os membros entre os nós;
4. atribuir materiais e seções;
5. definir os apoios.

## Análise estrutural

O servidor também expõe o fluxo da seção Análise do OpenSA:

- `list_load_combinations`: lista as combinações configuradas;
- `create_load_combination`, `update_load_combination` e `delete_load_combination`;
- `get_analysis_state`: informa se existem resultados válidos e qual visualização está ativa;
- `run_analysis`: processa todas as combinações ou somente as informadas;
- `list_analysis_results`: lista os resultados disponíveis na revisão atual;
- `get_node_analysis_results`: consulta deslocamentos, rotações e reações nodais;
- `get_member_analysis_results`: consulta esforços, deslocamentos e, opcionalmente, as 21 amostras de cada membro;
- `get_support_reactions`: consulta as reações dos nós apoiados;
- `set_analysis_view`: seleciona a combinação e o diagrama exibido;
- `set_analysis_diagrams_visible`: mostra ou oculta os diagramas na cena.

As combinações usam as siglas das ações nos fatores `factors`, `factors_2` e
`factors_3`. Os estados limite aceitos são `CAR`, `ELU` e `ELS`. Os diagramas
disponíveis são Normal, Cortante Y, Cortante Z, Torsor, Fletor Y, Fletor Z,
Reações de apoio e Deformação X/Y/Z/XYZ.

Os resultados são vinculados à revisão do modelo. Qualquer alteração estrutural
invalida os resultados anteriores, exigindo novo processamento.

### Exclusão em lote

`delete_elements` valida todos os nomes e dependências antes de modificar o
modelo. Por padrão, um nó conectado a um membro ou barra rígida bloqueia a
operação. Com `cascade: true`, essas dependências são incluídas no lote. Ações
aplicadas aos elementos removidos também são eliminadas, e `dry_run: true`
retorna o plano sem fazer alterações.

## Teste local

O servidor pode ser inspecionado com qualquer cliente MCP compatível. Para um
teste de desenvolvimento, use o MCP Inspector e informe o endpoint acima como
Streamable HTTP.

O servidor não publica uma porta externa e não implementa ainda autenticação,
histórico de alterações ou confirmação própria para operações de escrita. Por
isso, esta versão deve ser usada apenas localmente durante o desenvolvimento.

## Plugin local para o ChatGPT Desktop

O pacote em `plugins/mcp-opensa` registra este servidor no ChatGPT Desktop. Na
primeira abertura, o OpenSA copia o plugin para o marketplace pessoal local e
tenta instalá-lo pelo cliente disponível. Se o ChatGPT Desktop já estiver
aberto, é necessário reiniciá-lo uma vez para carregar o marketplace.

Depois disso, basta abrir um chat Work e selecionar `OpenSA` ou escrever
`@OpenSA`.

Se nenhum cliente compatível estiver instalado ou configurado, essa etapa é
ignorada e o aplicativo continua funcionando normalmente.
