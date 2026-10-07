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
- `create_node`: cria um nó no projeto aberto.
- `create_member`: cria um membro entre dois nós existentes.

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
