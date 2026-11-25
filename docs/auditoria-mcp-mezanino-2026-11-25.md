# Auditoria MCP do mezanino — 25/11/2026

## Escopo e resultado

Teste funcional com premissas de demonstração autorizadas pelo usuário. Todas as 107 ferramentas tiveram pelo menos uma chamada HTTP bem-sucedida durante a auditoria. Isso demonstra execução, não certifica todos os argumentos, todas as plataformas ou a adequação estrutural do exemplo.

O teste percorreu Geometria, Ações, Análise, Verificação e Detalhamento. Operações destrutivas e de topologia foram exercitadas em elementos temporários e removidas do modelo final. Os 30 diagramas de barras/placas e os quatro modos de apresentação de placas foram percorridos.

## Correções

- Alterações e troca de sessão pelo MCP abrem o editor quando a janela está na tela inicial.
- Criação de folhas sincroniza o modo Projeto, a seleção e os dados da interface.
- Divisão de barra reutiliza nós existentes nas posições de divisão, preservando suas propriedades.
- Verificação não aprova globalmente uma barra com torção solicitante sem rotina correspondente. Uma reprovação por outra solicitação permanece reprovada.
- Onze ferramentas novas permitem criar/consultar folhas, gerar vistas reais e detalhes de bases, adicionar cotas/textos, editar vistas, salvar OSA, exportar PDF/DXF e importar referência CAD.
- Edição da posição de um detalhe move os metadados do grupo e seu título, preservando o arranjo das vistas. A correção tem teste automatizado e foi repetida via HTTP na instância reiniciada, com atualização visual confirmada pelo usuário.
- Atualizados mocks e expectativas antigas de testes, incluindo conversão do peso próprio e fechamento de janela sem diálogo pendente.

## Modelo de demonstração

- Planta 8 x 4 m, altura 3 m; 12 nós, 12 barras e uma laje.
- Seis pilares W 200 x 46,1 e seis vigas W 250 x 32,7; ASTM A572 Gr 50.
- Laje C25 de 150 mm; seis bases engastadas; nós viga/pilar rígidos.
- Peso próprio automático, acabamento de 1 kN/m² e sobrecarga de 3 kN/m².
- Três combinações: CAR e ELS com PP+AP+AV; ELU com 1,4(PP+AP+AV).
- Bases representadas por chapas 350 x 350 x 20 mm e quatro chumbadores M20 por base. Essas dimensões são demonstrativas.

As três combinações foram analisadas. O equilíbrio vertical ELS apresentou carga de 263,8854019152657 kN e reação de 263,88540191526846 kN. A verificação final retornou oito aprovados e quatro não verificados por torção. Não foi dimensionado concreto armado, ligações, chumbadores, soldas ou fundações. O exemplo não é executivo.

## Arquivos gerados

Na pasta de artefatos `mezanino-mcp` da sessão: cópia inicial, `Mezanino-MCP.osa`, três folhas PDF, DXF dos eixos, resultados de verificação, equilíbrio e trilha JSONL. As folhas foram renderizadas e inspecionadas. Uma folha padrão vazia permanece no OSA e não foi exportada. O DXF contém eixos analíticos, não detalhamento de fabricação.

## Testes e limites

- Conjunto direcionado de MCP, navegação, comandos e verificação: 157 testes aprovados.
- Testes adicionais de detalhamento e regressão da tela inicial: 43 aprovados; log `detailing-final.log` nos artefatos.
- Ruff dos novos módulos e teste de fluxo: aprovado. `git diff --check`: aprovado.
- A tentativa da suíte completa encontrou falhas e não foi concluída. Uma execução isolada de quatro módulos retornou 89 aprovados e oito falhas em inversão/seleção de barras, mensagens de exclusão de nós, estados mistos de apoios, texto de seleção múltipla e rolagem de diálogo de componentes. Também houve falhas de renderização/placas no ambiente Qt sem tela. Não há evidência suficiente para atribuir todas ao ambiente ou aprovar o lançamento.
- A API de importação foi exercitada com DXF. A conversão DWG depende do conversor externo e não foi validada com um DWG real nesta auditoria.
- Foi identificado que `reverse_member` retornava sucesso embora a interface normalizasse novamente a direção. O código agora rejeita a inversão antes de alterar o modelo quando a orientação canônica está ativa, como já faz a interface; teste de atomicidade aprovado. A correção foi repetida via HTTP após reiniciar: a operação retornou erro explícito e a revisão permaneceu inalterada. Os testes gráficos antigos esperam inversão manual e precisam ser alinhados ao comportamento canônico fixo atual.

## Antes do lançamento

Investigar as falhas restantes da suíte geral, alinhar os testes de inversão ao comportamento canônico e conferir seleção na interface gráfica e validar importação DWG com arquivo real caso o recurso seja anunciado. As limitações de dimensionamento devem continuar explícitas na interface e nos relatórios. As alterações desta auditoria ainda não foram commitadas.

## Rodada adicional a partir da tela inicial

O usuário abriu uma instância nova e ativou o MCP na tela inicial. A rodada confirmou:

- Criar o primeiro nó abriu o editor de Geometria (confirmação visual do usuário).
- O mezanino completo foi reconstruído e atualizado sem intervenção na tela (confirmação do usuário).
- Ações, Análise e Verificação foram executadas novamente; três resultados de análise disponíveis.
- Folhas, vistas, cotas, textos e bases foram criados. A interface abriu o modo Projeto e acompanhou o movimento do grupo (confirmação do usuário e metadados das duas vistas).
- Da folha, `set_session` voltou para Análise; ELU e Fletor Z foram selecionados e apareceram na cena 3D (confirmação do usuário).
- A recusa da inversão com orientação canônica foi conferida via HTTP sem alteração da revisão.
- Oito testes de fluxo passaram, incluindo transição da folha para cada uma das quatro sessões do modelo. Ruff do teste e diff sem erros.
- O arquivo salvo foi carregado em outro modelo pelo repositório e serializado novamente. Conteúdo equivalente após normalizar os dois parâmetros de material opcionais preenchidos com zero pelo leitor. Preservados nós, barras, placas, cargas, combinações, três análises e folhas. As verificações não são persistidas pelo formato atual e devem ser recalculadas. O aplicativo ativo não foi fechado para este teste.
- Reconexões de clientes HTTP funcionaram entre as etapas. Desativar/ativar o servidor pela interface e importar DWG real ainda não foram validados nesta rodada.

Os logs adicionais são `home-screen-validation.log`, `reopen-validation.json` e a trilha acumulada `calls.jsonl` na pasta de artefatos.
