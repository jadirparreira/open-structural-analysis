# mcp-opensa

Plugin local para conectar clientes compatíveis com MCP ao Open Structural
Analysis em execução no mesmo computador.

## Uso

1. Abra o Open Structural Analysis.
2. Confirme que o servidor local está disponível em
   `http://127.0.0.1:8765/mcp-opensa`.
3. Na primeira execução, o OpenSA registra o marketplace e tenta instalar o
   plugin no cliente local automaticamente.
4. Reinicie o ChatGPT Desktop uma vez, se ele já estava aberto.
5. Abra um chat Work e selecione `mcp-opensa`.

O plugin não inicia o OpenSA. O aplicativo precisa estar aberto para que as
ferramentas operem sobre o projeto estrutural ativo.
