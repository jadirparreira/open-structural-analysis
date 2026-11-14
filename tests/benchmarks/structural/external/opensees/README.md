# Referências OpenSees

Esta pasta contém casos externos compatíveis com as capacidades já disponíveis
no OpenSA. O teste atual é um pórtico plano elástico estático, representado no
OpenSA como um modelo 3D no plano X-Z.

## Convenções

- unidades: kN e m;
- OpenSees usa o elemento 2D `elasticBeamColumn`;
- OpenSA usa barras 3D com os graus de liberdade fora do plano restringidos;
- rotações e momentos em torno do eixo Y possuem sinais opostos entre as duas
  representações, conforme o sistema de eixos adotado.

Os valores em `fixtures/elastic_portal_frame.json` foram obtidos com
`OpenSeesPy 3.8.0.0`. O checkout local do projeto OpenSees usado como
referência de origem está no commit `0d8b51407`; o executável desse checkout
não é requisito para rodar a suíte do OpenSA. O fixture mantém a referência
independente disponível no CI.
