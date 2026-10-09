# mcp-opensa

Plugin local para conectar clientes compatíveis com MCP ao Open Structural
Analysis em execução no mesmo computador.

## Uso

1. Abra o Open Structural Analysis.
2. Acesse `Arquivo > Configurações > MCP` e ative o servidor.
3. Confirme que o servidor local está disponível em
   `http://127.0.0.1:8765/mcp-opensa`.
4. Reinicie o ChatGPT Desktop uma vez, se ele já estava aberto.
5. Abra um chat Work e selecione `OpenSA` ou escreva `@OpenSA`.

O plugin não inicia o OpenSA nem o servidor MCP por conta própria. O aplicativo
precisa estar aberto e o servidor precisa estar ativado nas configurações para
que as ferramentas operem sobre o projeto estrutural ativo.
