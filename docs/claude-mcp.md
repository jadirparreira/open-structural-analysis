# Claude Desktop e Claude Code

O Open Structural Analysis expõe seu modelo aberto por um servidor MCP local
em `http://127.0.0.1:8765/mcp-opensa`. O endpoint existe enquanto o OpenSA está
aberto e a opção **Servidor MCP** está ativada em **Arquivo > Configurações >
MCP**. Claude não inicia o OpenSA nem esse servidor.

## Claude Code e a aba Code do Claude Desktop

O arquivo `.mcp.json` na raiz deste repositório configura o transporte
Streamable HTTP, que o Claude Code lê diretamente:

```json
{
  "mcpServers": {
    "mcp-opensa": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp-opensa"
    }
  }
}
```

O Claude Code pode pedir aprovação para usar o servidor definido no projeto.
Revise e aprove a entrada `mcp-opensa` na primeira sessão. No Claude Desktop,
escolha o ambiente **Local** na aba **Code**; sessões Cloud e SSH não alcançam o
loopback do computador onde o OpenSA está aberto. A sessão Code local também
pode carregar o servidor configurado para o Chat, conforme a precedência do
Claude Desktop.

O Claude Code instalado separadamente também lê `.mcp.json` quando iniciado
nesta pasta. Use `/mcp` na sessão para conferir a conexão e as ferramentas.

## Claude Desktop: Chat

A configuração local do Chat usa um processo MCP por `stdio`. Para conectar o
servidor HTTP do OpenSA, configure o adaptador `mcp-remote` como esse processo.
No Linux, o arquivo do Claude Desktop fica em
`~/.config/Claude/claude_desktop_config.json`.

Adicione esta entrada ao objeto `mcpServers`, preservando quaisquer outros
servidores que já existam:

```json
{
  "mcpServers": {
    "mcp-opensa": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://127.0.0.1:8765/mcp-opensa"
      ]
    }
  }
}
```

Esse adaptador requer Node.js/npm disponíveis para o usuário que iniciou o
Claude Desktop. Se `npx` não for encontrado ao iniciar pelo menu gráfico, use
no campo `command` o caminho absoluto mostrado por `command -v npx`. Reinicie o
Claude Desktop depois de editar o arquivo. A primeira inicialização pode levar
mais tempo enquanto `npx` baixa o adaptador.

O Claude Desktop também carrega servidores de
`claude_desktop_config.json` em sessões Code locais. Mantemos o nome
`mcp-opensa` igual ao de `.mcp.json` para que o Desktop use uma única definição
e não mostre ferramentas duplicadas.

## Preparação de uma sessão

1. Abra o Open Structural Analysis e o modelo que deseja controlar.
2. Ative **Arquivo > Configurações > MCP > Servidor MCP**.
3. Confirme na tela do OpenSA que o endpoint está disponível.
4. No Claude Desktop, abra uma conversa nova. Para trabalhar no projeto, abra
   uma sessão na aba **Code** e escolha **Local**.
5. Na primeira conexão do Code, aprove o servidor do projeto. No Chat, confira
   se `mcp-opensa` aparece como ferramenta conectada.
6. Peça primeiro um resumo do modelo antes de solicitar alterações.

## Limites e segurança

- O servidor escuta somente em `127.0.0.1`; não o exponha em uma interface de
  rede. Não é necessário publicar o endpoint nem criar um túnel.
- O servidor não exige credencial local. Enquanto estiver ativo, processos
  locais que alcançam a porta podem consultar e alterar o modelo aberto.
- Desative o servidor MCP no OpenSA quando terminar.
- Este repositório fornece a configuração e o endpoint; cada usuário precisa
  configurar o cliente Claude na própria máquina. A conexão depende do OpenSA
  estar aberto com o servidor MCP ativado.

## Diagnóstico pelo usuário

- Se Claude não listar as ferramentas, confirme que o OpenSA está aberto, que o
  servidor MCP está ativado e que `127.0.0.1:8765` está disponível.
- Se o Claude Desktop Chat não iniciar o processo MCP, confira o caminho de
  `npx` e os logs de desenvolvedor do Claude Desktop.
- Se o Code não listar `mcp-opensa`, abra a sessão na raiz deste repositório,
  aceite o aviso de confiança do projeto e confira `/mcp`.
- Se a sessão Code estiver em Cloud ou SSH, troque o ambiente para **Local**.

Não instalamos nem executamos o Claude neste computador. Estes passos deixam a
integração configurada por documentação; a conexão final precisa ser confirmada
em uma máquina com o Claude Desktop ou Claude Code disponível.
