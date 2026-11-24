# Inventário das ferramentas MCP — v5

O servidor registra **96 ferramentas**. Esta relação corresponde aos esquemas efetivos do servidor; `get_capabilities` permite consultar recursos e diagramas em tempo de execução.

| Ferramenta | Parâmetros | Operação |
| --- | --- | --- |
| `add_member_distributed_load` | `member_name`, `direction`, `initial_kn_m`, `final_kn_m`, `load_case`, `reference?` | Aplica ou atualiza uma força distribuída em kN/m na barra. Use initial e final para uma carga linearmente variável; valores iguais representam carga uniforme. reference pode ser global ou local. |
| `add_member_moment` | `member_name`, `direction`, `value_knm_m`, `load_case` | Aplica ou atualiza um momento distribuído em kN·m/m no eixo local X, Y ou Z da barra. |
| `add_node_force` | `node_name`, `direction`, `value_kn`, `load_case` | Aplica ou atualiza uma força nodal em kN nas direções X, Y ou Z. |
| `add_node_moment` | `node_name`, `direction`, `value_knm`, `load_case` | Aplica ou atualiza um momento nodal em kN·m nas direções X, Y ou Z. |
| `add_plate_edge_load` | `plate_name`, `edge_index`, `load_case`, `action_type`, `direction`, `initial`, `final?`, `reference?` | Aplica força (kN/m) ou momento (kN·m/m) na aresta, índice desde zero. Momento usa referência local. |
| `add_plate_pressure` | `plate_name`, `pressure_kn_m2`, `load_case` | Aplica ou atualiza uma pressão superficial em kN/m² na malha da laje. |
| `add_plate_pressure_profiles` | `plate_name`, `load_case`, `x_initial`, `x_final`, `y_initial`, `y_final` | Aplica perfis independentes de pressão X/Y locais em kN/m², como no painel de ações da placa. |
| `apply_selfweight` | `load_case`, `materials?` | Substitui os carregamentos do caso informado pelo peso próprio de barras e placas. Informe materials para filtrar materiais; omitindo, todos os materiais serão usados. |
| `clear_actions` | `load_case?`, `target?`, `targets?` | Remove carregamentos por load_case, target, targets ou uma combinação desses filtros. target mantém o filtro de um único elemento; targets aceita vários nós e barras. |
| `copy_element_properties` | `kind`, `source_name`, `target_name`, `properties` | Copia categorias: node component/restrictions; bar color/material/section/rotation/releases; plate color/material/section/restrictions. |
| `copy_elements` | `offset`, `node_names?`, `member_names?`, `rigid_bar_names?`, `plate_names?` | Copia nós, barras, barras rígidas e/ou placas por uma translação. Informe listas de nomes e um deslocamento [dx, dy, dz] nas unidades do projeto. Barras e placas copiadas preservam suas propriedades. |
| `copy_member_properties` | `source_member`, `target_member`, `properties?` | Copia propriedades de uma barra de referência para uma barra de destino. As propriedades possíveis são color, material, section, rotation, offsets e releases. Se omitidas, todas são copiadas. |
| `create_action_group` | `name`, `actions` | Cria um grupo personalizado. Cada ação deve ter name e abbreviation, por exemplo {name: 'Ação permanente', abbreviation: 'AP'}. |
| `create_load_combination` | `name`, `factors?`, `factors_2?`, `factors_3?`, `active_actions?`, `action_group?`, `limit_state?` | Cria uma combinação. factors, factors_2 e factors_3 usam as siglas das ações como chaves; active_actions informa as siglas participantes. limit_state pode ser CAR, ELU ou ELS. |
| `create_member` | `start_node`, `end_node` | Cria uma barra entre dois nós existentes no projeto aberto. Consulte os nós antes de chamar esta ferramenta. O nome da barra é atribuído automaticamente pelo OpenSA. |
| `create_node` | `x`, `y`, `z` | Cria um nó no projeto estrutural atualmente aberto. Use coordenadas numéricas e confirme as unidades com o usuário quando necessário. |
| `create_plate` | `contour`, `thickness_mm?`, `material?`, `supports?`, `restrictions?`, `restriction_stiffness?`, `restriction_directions?` | Cria placa de concreto com contorno em m, espessura em mm e molas distribuídas em kN/m³. |
| `create_rigid_bar` | `start_node`, `end_node` | Cria uma barra rígida entre dois nós existentes. |
| `create_scene_view` | `name` | Cria uma vista nomeada vazia e a torna ativa. Depois, use set_scene_members_visibility para ocultar ou reexibir barras e barras rígidas nela. |
| `delete_action` | `action_name` | Exclui um carregamento específico pelo nome retornado por list_actions. |
| `delete_action_group` | `name` | Exclui um grupo personalizado de ações. |
| `delete_drawing_reference` | `reference_id` | Remove permanentemente do projeto uma referência CAD importada. Confirme o id com list_drawing_references antes de remover. |
| `delete_elements` | `nodes?`, `members?`, `rigid_bars?`, `cascade?`, `dry_run?` | Exclui vários nós, barras e barras rígidas em uma operação validada. Use dry_run para visualizar o plano sem alterar o modelo. Por segurança, nós com dependências bloqueiam a operação; use cascade=true para incluir automaticamente as barras e barras rígidas conectados. |
| `delete_load_combination` | `name` | Exclui uma combinação existente pelo nome. |
| `delete_member` | `member_name` | Exclui uma barra pelo nome padrão retornado por list_members. |
| `delete_node` | `node_name` | Exclui um nó pelo nome padrão retornado por list_nodes. O nó não pode ainda estar conectado a barras. |
| `delete_plate` | `plate_name` | Exclui placa e suas cargas, limpando nós órfãos como na interface. |
| `delete_rigid_bar` | `rigid_bar_name` | Exclui uma barra rígida pelo nome retornado por list_rigid_bars. |
| `delete_scene_view` | `name` | Remove uma vista nomeada. Se ela estiver ativa, 'Completo' passa a ser ativa. A vista 'Completo' não pode ser removida. |
| `get_action_state` | — | Consulta o grupo e a ação atualmente selecionados no OpenSA. |
| `get_analysis_state` | — | Consulta o estado da análise, resultados disponíveis e visualização atual. |
| `get_capabilities` | — | Descobre sessões, diagramas, unidades e recursos suportados nesta versão. |
| `get_member_analysis_results` | `combination`, `member_names?`, `include_samples?` | Consulta esforços e deslocamentos das barras. include_samples inclui as 21 amostras ao longo de cada barra para reconstruir diagramas. |
| `get_node_analysis_results` | `combination`, `node_names?` | Consulta deslocamentos, rotações e reações nodais de uma combinação analisada. |
| `get_plate_analysis_results` | `combination`, `plate_names?` | Consulta deslocamentos nodais, esforços locais e pós-processamento por elemento de placa. Inclui wood_armer [Xsup,Ysup,Xinf,Yinf] em kN·m/m e von_mises [sup,inf,max] em MPa, com campos _nodal, eixos e convenções em postprocessing. |
| `get_project_summary` | — | Use esta ferramenta para saber o estado do projeto estrutural atualmente aberto no OpenSA antes de executar outras ações. |
| `get_scene_views` | — | Lista as vistas persistentes do projeto, a vista ativa, as barras ocultas e as barras rígidas ocultas em cada vista. A vista 'Completo' mostra tudo. |
| `get_session_state` | — | Consulta se Geometria, Ações ou Análise está aberta na interface. |
| `get_support_reactions` | `combination`, `node_names?` | Consulta forças e momentos de reação nos nós apoiados. |
| `get_verification_results` | `element_keys?` | Retorna verificações por chave bar:N ou group:N\|N, preservando status/limitações e todos os checks. |
| `get_verification_state` | — | Consulta grupos, resultados e se a análise permite executar as verificações. |
| `get_view_options` | — | Consulta o que está visível na cena do OpenSA. |
| `group_verification_elements` | `member_names` | Agrupa duas ou mais barras existentes como um único elemento na sessão Verificação. Todas devem estar conectadas em sequência e alinhadas na mesma reta. Informe os nomes padrão das barras retornados por list_members. |
| `join_members` | `first_member`, `second_member` | Une dois barras que compartilham um nó e são colineares. O primeiro nome é preservado. |
| `join_plates` | `first_plate`, `second_plate` | Une placas compatíveis que compartilham uma borda. |
| `list_action_groups` | — | Consulta os grupos de ações e as ações disponíveis em cada grupo. |
| `list_actions` | `load_case?`, `target?` | Consulta os carregamentos aplicados. Pode filtrar por load_case ou target. Use esta ferramenta antes de editar ou excluir uma carga. |
| `list_analysis_results` | — | Lista as combinações que possuem resultados válidos na revisão atual. |
| `list_drawing_references` | — | Lista as referências CAD importadas no projeto, com identidade, plano, origem, visibilidade e contagens de geometria. Não retorna os dados binários do desenho. |
| `list_load_combinations` | — | Consulta as combinações de carregamento configuradas no projeto. |
| `list_materials` | — | Consulta os materiais disponíveis no projeto aberto. |
| `list_members` | — | Use esta ferramenta para consultar as barras do projeto aberto. |
| `list_node_components` | — | Lista tipos, parâmetros padrão e instâncias dos componentes visuais dos nós. |
| `list_nodes` | — | Use esta ferramenta para consultar os nós do projeto aberto. |
| `list_plates` | — | Lista placas, contornos, espessuras, apoios e restrições distribuídas. |
| `list_profiles` | `material_type`, `section_family` | Consulta perfis e dimensões dos catálogos. Tipos Aço/Concreto/Madeira; use list_sections para famílias. |
| `list_reference_axes` | — | Consulta os eixos de referência configurados no projeto aberto. |
| `list_rigid_bars` | — | Consulta as barras rígidas do projeto aberto. |
| `list_sections` | `material?` | Consulta as famílias de seção disponíveis. Informe o nome do material ou o tipo do material, como 'Concreto'. |
| `move_elements` | `targets`, `offset` | Move [tipo, nome] por [dx,dy,dz] em m; tipos node/bar/rigid_bar/plate. Nós compartilhados movem uma vez. |
| `remove_selfweight` | `load_case` | Remove as cargas de peso próprio do caso de carregamento informado. |
| `rename_scene_view` | `old_name`, `new_name` | Renomeia uma vista existente. A vista 'Completo' é fixa. |
| `reverse_member` | `member_name` | Inverte a orientação de uma barra, trocando seus nós inicial e final. |
| `run_analysis` | `combinations?` | Executa a análise estrutural. Se combinations não for informado, processa todas as combinações configuradas e retorna os resultados gerados. |
| `run_verification` | `member_names?` | Executa as mesmas verificações da interface em cópia privada; mantém overrides e recusa publicar resultados obsoletos. |
| `select_scene_view` | `name` | Ativa uma vista existente pelo nome retornado por get_scene_views. |
| `set_action_group` | `group_name` | Seleciona um grupo de ações existente ou um modelo padrão. |
| `set_active_action` | `action_name` | Seleciona a ação/caso de carregamento usado pela interface. Use o nome da ação retornado por list_action_groups. |
| `set_analysis_diagrams_visible` | `visible` | Mostra ou oculta os diagramas de resultados na cena do OpenSA. |
| `set_analysis_view` | `combination?`, `diagram?`, `result_kind?`, `deformation_scale?`, `diagram_scale?`, `plate_result_display_mode?` | Seleciona a combinação e o diagrama exibido. Diagramas: Normal, Cortante Y, Cortante Z, Torsor, Fletor Y, Fletor Z, Reações de apoio, Deformação X, Deformação Y, Deformação Z e Deformação XYZ. Também aceita os rótulos da paleta, como Cortante Y (Vy). Placas: Fletor X (Mx), Fletor Y (My), Momento volvente XY (Mxy), Cortante X (Qx), Cortante Y (Qy), Tensão normal X (σx), Tensão normal Y (σy) e Tensão de cisalhamento XY (τxy). Selecionar um esforço/tensão de placa ativa o modo de placas; selecionar um esforço de barra ativa o modo de barras. Use result_kind=bar ou plate para distinguir rótulos compartilhados como Fletor Y (My). deformation_scale: 1 ou 10..100 em passos de 10; diagram_scale: 0.1..1.0 em passos de 0.1. plate_result_display_mode: centros, nos_sem_media, nos_media ou nos_media_macro. Esforços/tensões referem-se aos eixos locais; deslocamentos aos globais. |
| `set_detail_subtractions` | `target_kind`, `target_name`, `cutters` | Define sólidos subtraídos no detalhamento (bar/plate); não muda o modelo analítico. |
| `set_element_display_name` | `kind`, `name`, `display_name` | Altera nome de exibição de node ou plate; preserva sua identidade estrutural. |
| `set_member_calculation_properties` | `member_name`, `properties` | Define Ly/Lz/Lt/Lb em m e Ct/Cb adimensionais; null restaura cálculo automático sem invalidar análise. |
| `set_member_end_cuts` | `member_name`, `cuts` | Define cortes visuais por planos: identifier, point (m), normal, reference_label e planes opcionais; [] remove cortes. |
| `set_member_properties` | `member_names`, `material`, `section`, `geometry`, `profile?` | Atribui material e seção paramétrica a uma ou mais barras. As dimensões da geometria usam milímetros; por exemplo, uma seção retangular de 15 x 30 cm usa {b: 150, h: 300}. |
| `set_member_rectangular_section` | `member_names`, `width_mm`, `height_mm`, `material?` | Atribui uma seção retangular a uma ou mais barras. Informe largura e altura em milímetros; 15 x 30 cm corresponde a 150 x 300 mm. O material padrão é Concreto Estrutural. |
| `set_node_component` | `node_name`, `component_id`, `parameters?` | Atribui base_plate/stair_plate ou remove com null. Parâmetros dimensionais em mm; componente só visual. |
| `set_node_supports` | `node_name`, `dx`, `dy`, `dz`, `rx?`, `ry?`, `rz?` | Define as restrições translacionais e rotacionais de um nó. Use true para restringir cada grau de liberdade, na ordem X, Y, Z, Rx, Ry e Rz. |
| `set_reference_axes` | `axes` | Substitui os eixos de referência do projeto. Informe um objeto com as chaves X, Y e Z; cada uma contém uma lista de objetos {label, value}. Em XY, value em X posiciona a linha em x=value, value em Y posiciona a linha em y=value e value em Z define a elevação. |
| `set_scene_members_visibility` | `member_names?`, `visible?`, `rigid_bar_names?` | Define a visibilidade de barras e barras rígidas na vista ativa. Informe member_names e/ou rigid_bar_names. Use visible=false para ocultar ou true para reexibir. É necessário selecionar uma vista nomeada; a vista 'Completo' não permite ocultar elementos. |
| `set_session` | `session` | Abre uma sessão visual do OpenSA. Use exatamente Geometria, Ações ou Análise antes das operações relacionadas à respectiva sessão. |
| `set_verification_element_name` | `member_names`, `name` | Define o nome de um elemento ou grupo na sessão Verificação. O nome aceita somente letras e números; use texto vazio para limpar. Para um grupo, informe todos os nomes das barras que o compõem. Informe uma única barra para nomear um elemento individual. |
| `set_view_options` | `options` | Controla a visualização da cena sem alterar o modelo. Opções: grid_visible, reference_axes_visible, node_labels_visible, member_labels_visible, plate_labels_visible, local_axes_visible, nodes_visible, solid_members_visible, member_releases_visible, semirigid_links_visible, node_supports_visible, node_components_visible, node_forces_visible, node_moments_visible, member_forces_visible, member_moments_visible e plate_pressures_visible. Informe somente os campos desejados. |
| `show_all_scene_members` | — | Remove as ocultações de barras e barras rígidas da vista nomeada ativa. |
| `split_member` | `member_name`, `parts` | Divide uma barra em partes iguais, criando nós intermediários. Informe o nome padrão da barra e o número de partes maior que 1. |
| `split_plate` | `plate_name`, `first_point`, `second_point` | Divide placa por segmento entre dois pontos do contorno em coordenadas globais (m). |
| `ungroup_verification_elements` | `member_name` | Desfaz o grupo de verificação que contém a barra. |
| `update_action_group` | `old_name`, `name`, `actions` | Atualiza o nome e as ações de um grupo personalizado existente. |
| `update_applied_load` | `action_name`, `target?`, `direction?`, `initial_kn_m?`, `final_kn_m?`, `value?`, `load_case?`, `reference?`, `pressure_profiles?`, `edge_index?` | Atualiza um carregamento existente pelo nome retornado por list_actions, preservando sua identidade automática (por exemplo, Carga 5). Para cargas distribuídas use initial_kn_m e final_kn_m; para forças e momentos concentrados e momentos de aresta use value. Pressões de placa aceitam value uniforme ou pressure_profiles [Xi,Xf,Yi,Yf] em kN/m². Arestas aceitam edge_index desde zero. Também é possível alterar target, direction, load_case e reference. |
| `update_drawing_reference` | `reference_id`, `origin?`, `plane?`, `visible?` | Altera a origem [x,y,z], o plano (XY, XZ ou YZ) ou a visibilidade de uma referência importada. Informe somente os campos que deseja alterar; use o id retornado por list_drawing_references. |
| `update_load_combination` | `old_name`, `name?`, `factors?`, `factors_2?`, `factors_3?`, `active_actions?`, `action_group?`, `limit_state?` | Atualiza uma combinação existente; informe somente os campos desejados. |
| `update_member_endpoints` | `member_name`, `start_node`, `end_node` | Altera os nós inicial e final de uma barra, preservando sua identidade e propriedades. |
| `update_member_properties` | `member_names`, `material?`, `section?`, `geometry?`, `profile?`, `rotation?`, `releases?`, `rotation_flexibility_percent?`, `solid_face_offsets_mm?`, `solid_section_offsets_mm?`, `color?`, `section_mirrored?`, `solid_face_angles_deg?` | Atualiza qualquer combinação de propriedades das barras. Informe uma lista de nomes e somente os campos que deseja alterar. Pode alterar material, section, geometry, profile, rotation, releases (12 booleanos na ordem Dxa,Dxb,Dya,Dyb,Dza,Dzb,Rxa,Rxb,Rya,Ryb,Rza,Rzb), rotation_flexibility_percent (6 inteiros), offsets em milímetros, color, section_mirrored e solid_face_angles_deg (4 ângulos em graus). Para geometry, informe ou mantenha material e section válidos. |
| `update_node_properties` | `node_name`, `x?`, `y?`, `z?`, `supports?`, `support_stiffness?`, `support_directions?` | Atualiza propriedades de um nó existente sem alterar seu nome. Informe somente os campos desejados. Para coordenadas, informe x, y e z juntos. supports possui seis booleanos na ordem Dx,Dy,Dz,Rx,Ry,Rz. support_stiffness possui seis valores, com rigidezas translacionais em kN/m e rotacionais em kN·m/rad. support_directions: seis sentidos -, = ou +. |
| `update_plate_properties` | `plate_name`, `thickness_mm?`, `material?`, `color?`, `positioning_displacement?`, `edge_positioning?`, `restrictions?`, `restriction_stiffness?`, `restriction_directions?` | Atualiza placa: espessura em mm; deslocamento visual em m; molas em kN/m³; arestas [barra, mm, graus]. |
| `update_rigid_bar_endpoints` | `rigid_bar_name`, `start_node`, `end_node` | Altera os nós de uma barra rígida. O nome da barra rígida será atualizado automaticamente para refletir os novos nós. |

`?` indica parâmetro opcional. As unidades e restrições de cada argumento também constam no esquema MCP, consultável pelo cliente.

Consulte [MCP local](mcp-local.md) para ativação, compatibilidade e validação dos pacotes.
