# Claude Code e Claude Desktop

O Open Structural Analysis expõe o modelo aberto por um servidor MCP local em
`http://127.0.0.1:8765/mcp-opensa`, ativado em **Arquivo > Configurações > MCP >
Servidor MCP**. Para o Claude existem duas peças, além desse endpoint:

- **Ponte stdio** (`--mcp-stdio`): o próprio executável do OpenSA funciona como
  servidor MCP por `stdio`. Ele lista sempre as 96 ferramentas e encaminha cada
  chamada ao endpoint HTTP do programa aberto. Se o OpenSA estiver fechado ou o
  servidor desativado, a ferramenta responde com um erro que explica como
  ativá-lo, em vez de deixar o Claude sem ferramentas.
- **Plugin `mcp-opensa` do Claude Code**: instalado automaticamente pelo OpenSA,
  da mesma forma que o plugin do ChatGPT/Codex.

Por que a ponte: o Claude lista as ferramentas de um servidor MCP uma única vez,
ao abrir a sessão. Conectado direto ao endpoint HTTP, ele ficava sem ferramentas
sempre que a sessão começava antes de o OpenSA ser aberto. Com a ponte, as
ferramentas estão sempre disponíveis e passam a funcionar assim que o servidor é
ativado — sem reiniciar a sessão.

## Claude Code e a aba Code do Claude Desktop (automático)

Ao ativar o Servidor MCP, o OpenSA:

1. monta um marketplace local com o plugin `mcp-opensa`
   (`%LOCALAPPDATA%\OpenSA\claude-marketplace` no Windows,
   `~/.local/share/opensa/claude-marketplace` no Linux);
2. grava no plugin o comando da ponte desta instalação (o executável do
   OpenSA, o AppImage ou, no código-fonte, `python -m osa`) com
   `--mcp-stdio`;
3. chama o CLI do Claude Code em segundo plano:
   `claude plugin marketplace add`, `claude plugin install
   mcp-opensa@open-structural-analysis-local --scope user` e, quando o
   conteúdo muda (nova versão ou novo caminho do executável), `claude plugin
   update`.

A aba **Code** do Claude Desktop usa a mesma configuração do Claude Code. Abra
uma sessão nova para carregar as ferramentas; `/mcp` mostra
`plugin:mcp-opensa:mcp-opensa` conectado. As ferramentas aparecem como
`mcp__plugin_mcp-opensa_mcp-opensa__<ferramenta>`.

Se o CLI `claude` não for encontrado (no `PATH`, em `%APPDATA%\npm` ou na
variável `CLAUDE_CLI_PATH`), o OpenSA não instala nada e a página MCP das
configurações avisa. Se você já havia configurado o OpenSA à mão (por exemplo
com `claude mcp add ... http://127.0.0.1:8765/mcp-opensa`), remova essa entrada
para não ter as ferramentas duplicadas: `claude mcp remove <nome>`.

### Instalação manual pelo repositório

O repositório também é um marketplace do Claude Code
(`.claude-plugin/marketplace.json`). Essa variante usa o endpoint HTTP, porque
não sabe onde o OpenSA está instalado; ela exige o OpenSA aberto antes de
iniciar a sessão (ou reconectar em `/mcp`):

```text
/plugin marketplace add jadirparreira/open-structural-analysis
/plugin install mcp-opensa@open-structural-analysis
```

Ao trabalhar dentro do checkout, o `.mcp.json` da raiz faz o mesmo para o
projeto (o Claude Code pede aprovação na primeira sessão).

## Claude Desktop: Chat

O Chat do Claude Desktop inicia servidores MCP por `stdio`. Use a ponte do
próprio OpenSA, sem Node.js nem `mcp-remote`. Edite
`claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`; Linux:
`~/.config/Claude/`) e acrescente ao objeto `mcpServers`, preservando os demais:

```json
{
  "mcpServers": {
    "mcp-opensa": {
      "command": "C:\\Program Files\\Open Structural Analysis\\open-structural-analysis.exe",
      "args": ["--mcp-stdio"],
      "env": { "PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "1" }
    }
  }
}
```

Ajuste `command` para o caminho do executável instalado (no Linux, o caminho do
AppImage). `PYINSTALLER_SUPPRESS_SPLASH_SCREEN` evita que a tela de abertura do
OpenSA apareça quando o Claude inicia a ponte. Reinicie o Claude Desktop depois
de editar o arquivo.

Pelo código-fonte, use `"command": "<checkout>/.venv/Scripts/python.exe"` (ou
`.venv/bin/python`) e `"args": ["-m", "osa", "--mcp-stdio"]`.

## Ponte por linha de comando

```bash
open-structural-analysis --mcp-stdio [--mcp-endpoint http://127.0.0.1:8765/mcp-opensa]
uv run python -m osa --mcp-stdio
```

A ponte não abre a interface. A variável `OSA_MCP_ENDPOINT` também define o
endpoint. Cada chamada abre uma conexão curta com o servidor (que é stateless),
então fechar e reabrir o OpenSA durante a sessão do Claude não exige reconectar.

## Preparação de uma sessão

1. Abra o Open Structural Analysis e o modelo que deseja controlar.
2. Ative **Arquivo > Configurações > MCP > Servidor MCP**. Na primeira vez, o
   plugin do Claude Code é instalado.
3. Abra uma sessão nova no Claude Code ou na aba Code do Claude Desktop
   (ambiente **Local**; sessões Cloud e SSH não alcançam o OpenSA).
4. Peça primeiro um resumo do modelo antes de solicitar alterações.

## Limites e segurança

- O servidor escuta somente em `127.0.0.1`; não o exponha em uma interface de
  rede. A ponte também só encaminha para o endpoint local configurado.
- O servidor não exige credencial local. Enquanto estiver ativo, processos
  locais que alcançam a porta podem consultar e alterar o modelo aberto.
- Desative o servidor MCP no OpenSA quando terminar.

## Diagnóstico

- `/mcp` no Claude Code mostra o estado de `plugin:mcp-opensa:mcp-opensa`.
- `claude plugin list` mostra se `mcp-opensa@open-structural-analysis-local`
  está instalado e ativo.
- Se uma ferramenta responder que o OpenSA não está aberto, abra o programa e
  ative o Servidor MCP; não é preciso reiniciar a sessão.
- Se a sessão Code estiver em Cloud ou SSH, troque o ambiente para **Local**.
