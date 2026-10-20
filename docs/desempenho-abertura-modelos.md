# Desempenho da abertura de modelos

## Cenário e medição

O cenário grande usado nesta otimização contém 3.223 nós, 8.164 barras,
8.164 ações e três conjuntos de resultados salvos. O arquivo ocupa
301.403.539 bytes (aproximadamente 288 MiB). O arquivo de referência não é
distribuído com o repositório.

As medições desta sessão usaram Python 3.13, PySide6 6.11.2, PyVista 0.49.0 e
Qt `offscreen`. O tempo começa ao solicitar a abertura e termina quando a cena
foi instalada e o quadro de carregamento foi fechado. Um temporizador de
16 ms mede os intervalos em que a interface deixou de processar eventos.

| Modelo | Nós | Barras | Abertura após otimização | Maior intervalo entre eventos |
| --- | ---: | ---: | ---: | ---: |
| Pequeno | 2 | 1 | 0,123 s | 44,5 ms |
| Galpão gerado pelo programa | 408 | 839 | 0,571 s | 48,6 ms |
| Grande, com resultados salvos | 3.223 | 8.164 | 6,686 s | 208,0 ms |

Na medição inicial do cenário grande, antes destas otimizações, a abertura
levou **36,710 s**, com um intervalo de **2.986 ms** sem atualização da
interface. A medição final reduziu o tempo em aproximadamente **82%** e o
maior intervalo em aproximadamente **93%**. No cenário grande ainda houve
dois intervalos acima de 100 ms; as coletas completas de memória do Python
continuam sendo uma fonte de pausas curtas.

O ambiente não disponibilizou um contexto OpenGL válido para o widget Qt.
Portanto, estes números validam leitura, preparação, instalação da cena e
agendamento de eventos, e não representam uma medição do desenho final em
uma GPU real. O ganho de tempo e a fluidez devem ser conferidos também no
ambiente gráfico do usuário.

## Gargalos e alterações

- A verificação de coordenadas e conexões comparava cada entidade com todas
  as anteriores. A leitura usa índices espaciais e conjuntos de conexões,
  mantendo a tolerância geométrica e a rejeição de duplicatas. A validação
  medida inicialmente em 9,84 s caiu para aproximadamente 0,25 s.
- Cada apoio reconstruía os mesmos cubos e cilindros em objetos VTK
  separados. Agora cada padrão é preparado uma vez e as cópias são
  posicionadas em lote. O preparo de nós e apoios passou de 15,45 s para
  aproximadamente 0,07 s.
- A interface já desenhava nós com instâncias de uma esfera, mas também
  armazenava uma esfera completa por nó. A cena usa um ponto por instância,
  preservando identidade, cores, seleção e atualização incremental. A
  aparência e a resolução da esfera continuam iguais.
- A montagem das barras reutiliza cores e arrays dos perfis. O cálculo dos
  eixos locais evita operações genéricas repetidas. O preparo das barras
  passou de 4,46 s para aproximadamente 0,9 s.
- O JSON é validado por registros, em pequenos buffers, com oportunidades
  explícitas para a interface executar. Resultados salvos ficam disponíveis
  em registros independentes e são expandidos em dicionários quando
  consultados. Salvar e copiar continuam produzindo dados JSON normais, sem
  depender da permanência do arquivo original.
- O histórico relia o arquivo inteiro na interface apenas para obter sua
  miniatura (3,27 s no cenário grande). A leitura procura a miniatura no fim
  do arquivo e possui fallback incremental para outras ordens de campos.
  As miniaturas são carregadas fora da interface e têm cache com invalidação
  por tamanho e data do arquivo.
- A criação dos identificadores e a instalação da cena são divididas entre
  eventos Qt. O indicador usa animação contínua e os sinais de conclusão
  executam explicitamente na thread da interface.

Não foi introduzido um limite de visibilidade ou uma redução de detalhes.
Barras, apoios, nós e identificadores permanecem disponíveis como antes.

## Reprodução e verificação

Para medir o carregamento e os intervalos de eventos:

```bash
.venv/bin/python scripts/benchmark-project-opening.py "modelo.osa" --offscreen --output /tmp/abertura.json
```

Para incluir o desenho na GPU, execute no ambiente gráfico removendo
`--offscreen`. O script usa configurações temporárias e não salva o modelo
nem altera o histórico de projetos do usuário.

A nova leitura foi comparada à leitura JSON convencional para **todos os
campos e valores numéricos** do cenário grande, incluindo os três conjuntos
de resultados. A comparação foi exata. Os testes adicionais cobrem limites
dos buffers, Unicode e escapes, tolerância e duplicatas, leitura de
miniaturas, consulta e gravação dos resultados, edição incremental de nós,
animação durante a instalação e recuperação após falha de abertura.

Na execução completa da suíte, 373 testes passaram e seis falharam. As seis
falhas foram reproduzidas também no `HEAD` anterior: manifesto do MCP,
seleção com deslocamento visual no ambiente sem OpenGL, alternância de
seleção no inspector, dois testes de navegação e divergência de versão no
diálogo Sobre.
