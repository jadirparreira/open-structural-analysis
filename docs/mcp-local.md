# MCP local

O Open Structural Analysis inicia um servidor MCP local junto com a janela
principal. O servidor escuta somente em loopback:

```text
http://127.0.0.1:8765/mcp-opensa
```

O servidor opera sobre o mesmo `StructuralModel` que está aberto na interface.
As alterações recebidas por MCP atualizam a cena do OpenSA depois da execução.

## Ferramentas iniciais

- `get_project_summary`: consulta a quantidade de entidades e a revisão atual.
- `list_nodes`: lista os nós do projeto aberto.
- `list_members`: lista os membros do projeto aberto.
- `list_materials`: lista os materiais disponíveis no catálogo do projeto.
- `list_sections`: lista as famílias de seção compatíveis com um material.
- `create_node`: cria um nó no projeto aberto.
- `set_node_supports`: define as seis restrições de um nó.
- `create_member`: cria um membro entre dois nós existentes, opcionalmente já
  com material, seção e geometria.
- `set_member_properties`: atribui material e seção paramétrica a um ou mais
  membros. As dimensões da seção usam milímetros; uma seção de 15 x 30 cm usa
  `{ "b": 150, "h": 300 }`.

Com essas ferramentas, uma IA pode modelar uma estrutura passo a passo:

1. consultar materiais e seções;
2. criar os nós nas coordenadas do projeto;
3. criar os membros entre os nós;
4. atribuir materiais e seções;
5. definir os apoios.

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
