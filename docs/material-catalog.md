# Referências do catálogo de materiais

O catálogo inclui 13 aços, 12 classes de concreto e oito espécies de madeira de uso difundido no Brasil. Os números são referências editáveis para análise elástica e peso próprio. Não representam certificação de um lote nem executam dimensionamento de concreto ou madeira.

## Campos efetivamente usados

| Material | Campos exibidos em Editar > Propriedades |
| --- | --- |
| Aço | E, G, coeficiente de Poisson, peso específico, fy e fu |
| Concreto | Ecs, G, coeficiente de Poisson e peso específico |
| Madeira | E0,m paralelo às fibras, G, coeficiente de Poisson e peso específico |

O solver trabalha em m e kN. E e G são armazenados em kN/m²; peso específico em kN/m³. As tabelas abaixo usam MPa para facilitar a leitura dos módulos. Resistências de concreto e madeira não foram acrescentadas a campos de escoamento ou ruptura destinados ao aço.

## Aços acrescentados

Os sete novos registros usam E = 200 000 MPa, G = 76 900 MPa, ν = 0,3 e peso específico de 76,9822025 kN/m³, correspondente a 7 850 kg/m³ com g = 9,80665 m/s², seguindo os parâmetros elásticos já adotados no catálogo. fy e fu são os limites mínimos da especificação ou do produto indicado.

| Material | fy (MPa) | fu (MPa) | Referência de uso |
| --- | ---: | ---: | --- |
| ASTM A500 Gr B | 315 | 400 | Tubos, edição A500/A500M-21a |
| ASTM A500 Gr C | 345 | 425 | Tubos, edição A500/A500M-21a |
| NBR 7008-3 ZAR 230 | 230 | 310 | Chapas galvanizadas, aço-base |
| NBR 7008-3 ZAR 280 | 280 | 380 | Chapas galvanizadas, aço-base |
| NBR 7008-3 ZAR 345 | 345 | 430 | Chapas galvanizadas, aço-base |
| NBR 7007 AR 350 COR | 350 | 485 | Barras e perfis patináveis da referência Gerdau |
| ASTM A992 | 345 | 450 | Perfis laminados I/H |

- A500: os valores foram vinculados à edição 21a, que unifica os limites por grau para as seções circulares e não circulares. Edições anteriores usavam limites diferentes para tubos circulares. A edição e o certificado do material fornecido precisam corresponder ao cadastro.
- ZAR: usam os mínimos da linha NBR 7008-3:2021 no catálogo Usiminas, e não os valores superiores de determinados produtos proprietários USIGAL. A faixa de fornecimento da referência é de 0,40 a 3,00 mm; a espessura resistente corresponde ao aço-base.
- AR 350 COR: usa a referência comercial Gerdau para barras e perfis, sem generalizar os mesmos valores para chapas ASTM A588 de qualquer espessura.
- A992: adota fy mínimo de 345 MPa. O intervalo de escoamento de fornecimento não aumenta a resistência de cálculo do cadastro.

O SAE 1020 recebeu uma descrição esclarecendo que é uma designação química. Seus valores de resistência permanecem referências editáveis e precisam corresponder à condição de fornecimento. Acrescentar um grau ao catálogo de materiais disponibiliza suas propriedades; a cobertura das rotinas de verificação de cada família de perfil continua sendo informada pelos resultados dessas rotinas.

## Concretos

Classes da ABNT NBR 8953:2015, até C90. Ecs estimado aos 28 dias com agregado granito/gnaisse (αE = 1,0), conforme ABNT NBR 6118:2023, 8.2.8. Foram usados:

```text
fck ≤ 50 MPa: Eci = 5600 sqrt(fck)
fck > 50 MPa: Eci = 21500 (fck/10 + 1,25)^(1/3)
αi = min(1; 0,8 + 0,2 fck/80)
Ecs = αi Eci
G = Ecs/2,4; ν = 0,2
```

Eci, Ecs e fck nessas expressões estão em MPa. O peso específico adotado é 25 kN/m³, para concreto armado endurecido, conforme a Tabela 1 da ABNT NBR 6120:2019.

| Classe | Ecs (MPa) | G (MPa) | ν | Peso específico (kN/m³) |
| --- | ---: | ---: | ---: | ---: |
| Concreto C20 | 21287.367 | 8869.736 | 0,2 | 25 |
| Concreto C25 | 24150.000 | 10062.500 | 0,2 | 25 |
| Concreto C30 | 26838.405 | 11182.669 | 0,2 | 25 |
| Concreto C35 | 29402.917 | 12251.215 | 0,2 | 25 |
| Concreto C40 | 31875.759 | 13281.566 | 0,2 | 25 |
| Concreto C45 | 34278.922 | 14282.884 | 0,2 | 25 |
| Concreto C50 | 36628.131 | 15261.721 | 0,2 | 25 |
| Concreto C55 | 38092.925 | 15872.052 | 0,2 | 25 |
| Concreto C60 | 39531.328 | 16471.387 | 0,2 | 25 |
| Concreto C70 | 42357.247 | 17648.853 | 0,2 | 25 |
| Concreto C80 | 45132.117 | 18805.049 | 0,2 | 25 |
| Concreto C90 | 46703.176 | 19459.657 | 0,2 | 25 |

As condições de agregado e idade constam nas referências do catálogo. Se houver ensaios ou outros agregados, os valores podem ser editados. A classe no nome identifica o fck utilizado para estimar Ecs; não cria uma verificação de resistência à compressão no programa.

## Madeiras

E0,m e densidade aparente vêm do Anexo E informativo da ABNT NBR 7190:1997, para umidade de 12%. Essa edição histórica fornece as médias por espécie usadas como referência; elas não foram apresentadas como classificação estrutural conforme a norma atual. G é estimado por E0,m/16, conforme ABNT NBR 7190-1:2022. Peso específico = densidade aparente × 9,80665/1000.

| Espécie | E0,m (MPa) | G estimado (MPa) | Peso específico (kN/m³) |
| --- | ---: | ---: | ---: |
| Angelim-pedra | 12912.000 | 807.000 | 6.805815 |
| Cupiúba | 13627.000 | 851.688 | 8.217973 |
| Eucalipto grandis | 12813.000 | 800.812 | 6.276256 |
| Garapa | 18359.000 | 1147.438 | 8.747532 |
| Ipê | 18011.000 | 1125.688 | 10.473502 |
| Jatobá | 23607.000 | 1475.438 | 10.532342 |
| Maçaranduba | 22733.000 | 1420.812 | 11.209001 |
| Pinus elliottii | 11889.000 | 743.062 | 5.491724 |

Os nomes científicos constam na descrição de cada material. Garapa usa a amostra identificada como Garapa Roraima na referência. O módulo paralelo pressupõe as fibras alinhadas ao eixo da barra. A rigidez efetiva do lote e as condições de serviço precisam corresponder ao uso pretendido; o catálogo não aplica automaticamente fluência ou fatores de modificação.

Poisson não integra a rigidez das barras de madeira, mas é usado pelo elemento de placa. Os registros de espécies não fornecem esse dado; o valor inicial zero é editável e não representa uma propriedade experimental da espécie. Nas barras, E e G permanecem independentes.

## Materiais das placas

Placas podem usar concreto, aço ou madeira. No lançamento pela interface, material e seção começam como Indefinido. A espessura zero representa seção ainda não definida; o cálculo exige material cadastrado e espessura positiva. Chamadas programáticas que omitem as propriedades mantêm os padrões anteriores por compatibilidade. Peso próprio usa o peso específico do material selecionado e a espessura da placa.

O elemento de placa atual é homogêneo e isotrópico: usa E e Poisson, com cisalhamento derivado de E/[2(1+ν)], sem usar o G independente cadastrado para barras. Para madeira, emprega E0,m nas duas direções, como aproximação equivalente; não representa ortotropia, direção das fibras, camadas nem fluência. A liberação de madeira no seletor não constitui um modelo de painel laminado.

Wood-Armer permanece um pós-processamento de momentos destinado a armaduras; não verifica aço ou madeira. Von Mises não constitui critério de resistência para madeira. Nenhum desses resultados acrescenta verificação automática de resistência da placa.

## Compatibilidade e atualização

Os materiais genéricos Concreto Estrutural e Madeira Estrutural foram retirados do catálogo. Os comandos de concreto e a criação de placas usam Concreto C30 como padrão. As classes e espécies são incorporadas ao abrir projetos antigos; materiais e valores já salvos no projeto são preservados, exceto o antigo Concreto Estrutural, migrado para Concreto C30 com as propriedades dessa classe. Resultados anteriores à migração exigem nova análise. A importação de madeira sem espécie identificada mantém um material provisório para revisão, sem atribuir uma espécie automaticamente. Os materiais do catálogo seguem a mesma proteção contra exclusão dos padrões anteriores.

Editar um material agora atualiza os dados associados às suas barras. A conversão de massa linear para peso próprio usa 9,80665 m/s², igual à conversão inversa usada para obter a densidade, mantendo o peso calculado compatível com o peso específico informado.

## Fontes consultadas

- [ABNT NBR 6118:2023, documento original, itens 8.2.8 e 8.2.9](https://cdn1.get-qr.com/files/66df3692b1d68fa1faf6a57a/1725904532378-5174ed6d6ac57a8935170ae8b69ff0ef.pdf).
- [ABNT NBR 6120:2019, documento original, Tabela 1](https://www.scribd.com/document/541084226/Nbr-6120-de-2019-Cargas).
- [ABNT NBR 7190:1997, documento original, Anexo E](https://pdfcoffee.com/nbr-7190-pdf-free.html).
- [ABNT NBR 7190-1:2022, documento original](https://pdfcoffee.com/pdf-abtn-nbr-7190-2022-dl-pdf-free.html).
- [Classes da NBR 8953:2015 reproduzidas em auditoria do Governo do Distrito Federal](https://www.cg.df.gov.br/wp-conteudo/uploads/2023/01/RA_02_2023_SODF_e_NOVACAP_2020_2021.pdf).

### Fontes dos aços

- [Steel Tube Institute - ASTM A500](https://steeltubeinstitute.org/resources/astm-a500/).
- [ASTM A500/A500M-21a, documento original](https://www.scribd.com/document/789061023/A500-A500M-21a).
- [Usiminas - Galvanizados por Imersão a Quente, tabela NBR 7008-3:2021](https://www.usiminas.com/wp-content/uploads/2024/12/2024_07_06-CATALOGO-GAL-IMER-QUENTE-ABERTO_V2.pdf).
- [Gerdau - Barras e Perfis, propriedades mecânicas referenciais e linha SAE](https://www2.gerdau.com.br/wp-content/uploads/2022/07/Barras-e-Perfis-Catalogo-Gerdau-1.pdf).
- [Gerdau - Perfis Estruturais, tabela ASTM A992](https://www2.gerdau.com.br/wp-content/uploads/2022/07/Folder-Perfis-Estruturais-Gerdau-Informac%CC%A7o%CC%83es-Te%CC%81cnicas-1.pdf).
