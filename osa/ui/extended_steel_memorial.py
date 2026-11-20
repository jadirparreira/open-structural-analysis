"""Render structured steel checks with the existing memorial typography."""

from html import escape

_EQUATION_LABELS = {
    "V_{Rd,w}": "Resistência ao cortante de cada alma",
    "F_{Rd}": "Resistência ao esmagamento por alma",
    r"\delta_{y}": "Deslocamento de serviço Y", r"\delta_{z}": "Deslocamento de serviço Z",
    r"\delta_{lim}": "Limite de deslocamento",
    "r_1": "Raio de giração principal maior", "r_2": "Raio de giração principal menor",
    "K_1L_1": "Comprimento efetivo no eixo principal maior",
    "K_2L_2": "Comprimento efetivo no eixo principal menor",
    r"\lambda_1": "Esbeltez no eixo principal maior",
    r"\lambda_2": "Esbeltez no eixo principal menor",
    r"\lambda_t": "Esbeltez de tração (recomendação)",
    "N_{t,Rd1}": "Escoamento da seção bruta", "N_{t,Rd2}": "Ruptura da seção líquida efetiva",
    "N_{t,Rd}": "Resistência à tração", "N_{ey}": "Flambagem por flexão em Y",
    "N_{ez}": "Flambagem por flexão em Z", "N_{et}": "Flambagem por torção",
    "N_e": "Força crítica governante", r"\lambda_y": "Esbeltez global Y",
    r"\lambda_z": "Esbeltez global Z", r"\lambda_0": "Esbeltez reduzida",
    r"\chi": "Fator de redução por instabilidade global", "A_{ef}": "Área efetiva",
    "N_{c,Rd}": "Resistência à compressão", r"\lambda": "Esbeltez da parede",
    r"\lambda_p": "Limite de plastificação", r"\lambda_r": "Limite de flambagem elástica",
    "M_n": "Momento nominal governante", "M_{Rd}": "Resistência à flexão",
    r"\tau_{cr1}": "Primeira tensão crítica de cisalhamento",
    r"\tau_{cr2}": "Segunda tensão crítica de cisalhamento",
    r"\tau_{cr}": "Tensão crítica de cisalhamento governante", "V_{Rd}": "Resistência ao cortante",
    "W_T": "Módulo resistente à torção", "T_{n1}": "Primeiro momento crítico de torção",
    "T_{n2}": "Segundo momento crítico de torção", "T_{Rd}": "Resistência à torção",
    r"\eta_{int}": "Interação de força axial e flexão", r"\eta_T": "Interação com torção",
    "b_{ef}": "Largura efetiva da mesa", "h_{ef}": "Largura efetiva da alma",
    "W_{ef}": "Módulo resistente elástico efetivo", "M_{n,FLM}": "Flambagem local da mesa",
    "M_{n,FLA}": "Flambagem local da alma", "M_{n,FLT}": "Flambagem lateral com torção",
    "N_y": "Força de escoamento da seção bruta", "M_y": "Momento de início de escoamento",
    "N_{e}": "Força crítica global", "N_{l}": "Força crítica local",
    "N_{dist}": "Força crítica distorcional", "M_{e}": "Momento crítico global",
    "M_{l}": "Momento crítico local", "M_{dist}": "Momento crítico distorcional",
    "N_{Re}": "Resistência característica por instabilidade global",
    "N_{Rl}": "Resistência característica por instabilidade local",
    "N_{Rdist}": "Resistência característica por instabilidade distorcional",
    "M_{Re}": "Resistência característica por instabilidade global",
    "M_{Rl}": "Resistência característica por instabilidade local",
    "M_{Rdist}": "Resistência característica por instabilidade distorcional",
    "A_{rem}": "Área removida da mesa comprimida",
    "z_{rem}": "Posição da parcela removida", "z_{ef}": "Deslocamento do centroide efetivo",
    "I_{ef}": "Inércia da seção efetiva", "N_{Rd}": "Força axial resistente de cálculo",
    "A_w": "Área resistente ao cortante", "T_n": "Momento nominal resistente à torção",
    r"\lambda_{FLT}": "Esbeltez para flambagem lateral", r"\rho_v": "Redução por instabilidade ao cortante",
}


def render(memory, row, formatted, spaced_equations, equation_triplet):
    cold = memory.get("profile_type", "").endswith("Formado")
    geometry = memory.get("geometric_parameters", {})
    material = memory.get("material_parameters", {})
    summary = memory.get("verification_summary") or {}
    identity = [("Nome", memory.get("element_name") or ", ".join(memory.get("members", ())) or "—"),
                ("Barra(s) do elemento", ", ".join(memory.get("members", ()))),
                ("Tipo de Perfil", memory.get("profile_type", "—")),
                ("Seção", memory.get("section", "—")), ("Material", memory.get("material", "—"))]
    dimensions = [("Diâmetro externo (D)", "D_mm", "mm"), ("Espessura da parede (t)", "t_mm", "mm"),
                  ("Área bruta (Ag)", "Ag_cm2", "cm²"), ("Momento de inércia Y (Iy)", "Iy_cm4", "cm⁴"),
                  ("Momento de inércia Z (Iz)", "Iz_cm4", "cm⁴"),
                  ("Módulo elástico Y (Wy)", "Wy_cm3", "cm³"), ("Módulo elástico Z (Wz)", "Wz_cm3", "cm³"),
                  ("Módulo plástico Y (Zy)", "Zy_cm3", "cm³"), ("Módulo plástico Z (Zz)", "Zz_cm3", "cm³"),
                  ("Raio de giração Y (ry)", "ry_cm", "cm"), ("Raio de giração Z (rz)", "Rz_cm", "cm"),
                  ("Constante de torção (J)", "It_cm4", "cm⁴"),
                  ("Comprimento destravado Y (Ly)", "Ly_cm", "cm"),
                  ("Comprimento destravado Z (Lz)", "Lz_cm", "cm")]
    if memory.get("profile_type") in {"Tubular Quadrado", "Tubular Retangular"}:
        dimensions = [("Largura externa (b)", "b_mm", "mm"),
                      ("Altura externa (h)", "h_mm", "mm")] + dimensions[1:]
    if cold:
        dimensions = [("Altura (d)", "d_mm", "mm"), ("Largura da aba (bf)", "bf_mm", "mm"),
                      ("Espessura (t)", "t_mm", "mm"), ("Raio interno (r)", "r_mm", "mm")]
        if geometry.get("c_mm") is not None:
            dimensions.append(("Enrijecedor (c)", "c_mm", "mm"))
        if geometry.get("angle_deg") is not None:
            dimensions.append(("Ângulo do enrijecedor", "angle_deg", "°"))
        dimensions += [("Área bruta (Ag)", "Ag_cm2", "cm²"), ("Inércia Y", "Iy_cm4", "cm⁴"),
                       ("Inércia Z", "Iz_cm4", "cm⁴"), ("Produto de inércia", "Iyz_cm4", "cm⁴"),
                       ("Inércia principal maior", "I1_cm4", "cm⁴"), ("Inércia principal menor", "I2_cm4", "cm⁴"),
                       ("Ângulo dos eixos principais", "alpha_deg", "°"),
                       ("Módulo elástico Y (inclui Iyz)", "Wy_cm3", "cm³"),
                       ("Módulo elástico Z (inclui Iyz)", "Wz_cm3", "cm³"),
                       ("Constante de torção J (parede fina)", "It_cm4", "cm⁴")]
    materials = [("Módulo de elasticidade (E)", "E_kn_m2", "kN/m²"),
                 ("Módulo de cisalhamento (G)", "G_kn_m2", "kN/m²"),
                 ("Coeficiente de Poisson", "poisson", ""),
                 ("Tensão de escoamento (fy)", "fy_kn_m2", "kN/m²"),
                 ("Tensão de ruptura (fu)", "fu_kn_m2", "kN/m²")]

    def heading(text):
        return f'<h3 style="margin:22px 0 8px;font-size:15px">{escape(text)}</h3>'

    def table(rows):
        return '<table cellspacing="0" cellpadding="0">' + ''.join(row(*item) for item in rows) + '</table>'

    content = '<div style="font-family:sans-serif;font-size:13px;color:#24292f">'
    content += '<h2 style="margin:14px 0 12px;font-size:18px">Memória de cálculo de elemento estrutural</h2>'
    content += heading("1. Dados do elemento") + table(identity)
    content += heading("2. Parâmetros geométricos")
    content += table([(label, formatted(geometry.get(key), unit)) for label, key, unit in dimensions])
    content += heading("3. Parâmetros materiais")
    content += table([(label, formatted(material.get(key), unit)) for label, key, unit in materials])
    content += heading("4. Verificações")
    if not summary:
        return content + '<p style="margin:5px 0;color:#57606a">Execute a análise e a verificação do elemento.</p></div>'
    status = summary.get("status")
    rejection = summary.get("has_rejected_check") or (status == "checked" and summary.get("utilization", 0) > 1)
    conclusion = "REPROVADO — há verificações reprovadas" if rejection else "NÃO VERIFICADO — existem pendências" if status == "not_checked" else "APROVADO" if status == "checked" else "Sem solicitação aplicável"
    content += f'<p style="margin:5px 0;color:#57606a"><b>{escape(conclusion)}</b></p>'
    if status == "not_checked":
        content += f'<p style="margin:5px 0;color:#57606a">{escape(summary.get("detail", ""))}</p>'
    notes = []
    shown_coupled_service = set()
    for key, check in summary.get("checks", {}).items():
        title = check.get("critical_check", key)
        reference = check.get("reference", "")
        content += f'<p style="margin:22px 0 12px;color:#57606a;font-weight:700">{escape(title)} — {escape(reference)}</p>'
        check_status = check.get("status")
        for item in check.get("steps", ()) if check_status != "not_applicable" else ():
            label = _EQUATION_LABELS.get(item["symbol"], "Parâmetro de verificação")
            content += f'<p style="margin:0 0 3px;color:#57606a">{escape(label)} ({escape(item["reference"])})</p>'
            lines = equation_triplet(item["symbol"], item["formula"], item["substitution"],
                                     formatted(item["value"]), item["unit"])
            content += spaced_equations(lines, named=False)
        if key == 'stability_procedure' and check_status == 'checked':
            content += '<p style="margin:5px 0;color:#57606a">' + escape(check.get('detail', 'Procedimento conferido.')) + '</p>'
            stability = check.get('parameters', {})
            content += table([(name, info['classification'] + '; δ₂/δ₁ máximo = ' + formatted(info['maximum_ratio']))
                              for name, info in stability.get('global_stability', {}).items()])
            for combination, info in stability.get('global_stability', {}).items():
                notes.append(info.get('interpretation', ''))
                content += '<p style="margin:10px 0 5px;color:#57606a">' + escape(combination + ' — deslocamentos relativos à base') + '</p>'
                content += table([(f"{item['level']} / {item['upper_node']}–{item['base_node']} / {item['direction']}",
                                   f"δ₁={formatted(item['first_order_m']*1000, 'mm')}; δ₂={formatted(item['second_order_m']*1000, 'mm')}; δ₂/δ₁={formatted(item['ratio'])}")
                                  for item in info.get('rows', ())])
            if stability.get('large_alternative'):
                content += '<p>Opção declarada pelo responsável: procedimento alternativo de 4.10.7.2 para grande deslocabilidade; forças nocionais também nas combinações com ações horizontais.</p>'
        elif check_status == "checked":
            eta = check["utilization"]
            result = "APROVADO" if eta <= 1 else "REPROVADO"
            content += spaced_equations(equation_triplet(
                r"\eta", r"S_d/R_d", f'{formatted(check["applied"])}/{formatted(check["capacity"])}',
                formatted(eta * 100) + rf"\,\%\quad\mathbf{{{result}}}"), named=False)
            content += '<p style="margin:0 0 3px;color:#57606a">' + escape(
                f'Combinação governante: {check["critical_combination"]}; barra {check["critical_member"]}; '
                f'x = {formatted(check["critical_position_m"], "m")}.') + '</p>'
        else:
            prefix = "Não verificado: " if check_status == "not_checked" else "Não aplicável: "
            content += f'<p style="margin:5px 0;color:#57606a">{escape(prefix + check.get("detail", "dados indisponíveis"))}</p>'
        parameters = check.get("parameters", {})
        governing = parameters.get("governing") or (parameters.get("tension_governing") if key == "axial_tension" else None)
        if governing and check_status == "checked":
            content += '<p style="margin:5px 0;color:#57606a">' + escape("Modo governante: " + str(governing)) + '</p>'
        if key == 'shear_z' and parameters.get('shear_web_distribution'):
            content += '<p style="margin:5px 0;color:#57606a">' + escape(parameters.get('shear_distribution_scope', '')) + '</p>'
            content += table([(f"Alma {item['plate']}",
                              f"Vᵢ/Vz={formatted(item['vertical_fraction'])}; h={formatted(item['flat_height_mm'], 'mm')}; VRd,w={formatted(item['per_web_resistance_kn'], 'kN')}")
                             for item in parameters['shear_web_distribution']])
        if key == 'torsion' and parameters.get('unresolved_eccentric_torsion'):
            content += '<p style="margin:5px 0;color:#57606a">Indicação de torção por cortante excêntrico na análise sem empenamento. Estes valores não recuperam bimomento nem comprovam resistência; exigem reprocessar os vínculos de empenamento e a rigidez acoplada.</p>'
            content += table([(item['combination']+' / '+item['member'],
                f"|TSC| estimado={formatted(item['estimated_torque_magnitude_kn_m'], 'kN·m')}; x={formatted(item['position_m'], 'm')}")
                for item in parameters['unresolved_eccentric_torsion']])
        if key == 'torsion' and parameters.get('elastic_warping_effects'):
            content += '<p style="margin:5px 0;color:#57606a">Esforços elásticos recuperados com empenamento. Os máximos abaixo têm posições próprias e não constituem uma interação de resistência.</p>'
            content += table([(item['combination']+' / '+item['member'],
                f"B={formatted(item['bimoment_kn_m2'], 'kN·m²')} em x={formatted(item['bimoment_position_m'], 'm')}; TSC={formatted(item['torque_sc_kn_m'], 'kN·m')} em x={formatted(item['torque_position_m'], 'm')}")
                for item in parameters['elastic_warping_effects']])
        automatic_criticals = parameters.get("automatic_elastic_criticals", {})
        for symbol, item in automatic_criticals.items():
            label = _EQUATION_LABELS.get(
                {"NcrG": "N_{e}", "McrGy": "M_{e}", "McrGz": "M_{e}",
                 "NcrL": "N_{l}", "NcrD": "N_{dist}",
                 "McrLy": "M_{l}", "McrDy": "M_{dist}",
                 "McrLz": "M_{l}", "McrDz": "M_{dist}"}.get(symbol, symbol),
                symbol,
            )
            value_unit = "kN" if symbol.startswith("N") else "kN·m"
            description = (f"{label} calculado automaticamente por faixas finitas: "
                           if "half_wave_mm" in item else f"{label} calculado automaticamente: ")
            description += formatted(item['value'], value_unit)
            if "half_wave_mm" in item:
                description += f"; meia-onda crítica {formatted(item['half_wave_mm'], 'mm')}"
            description += ". " + item.get("source", "")
            content += '<p style="margin:5px 0;color:#57606a">' + escape(description) + '</p>'
        for source, info in parameters.get("service_stiffness", {}).items():
            if info.get('geometry_basis') in {'rounded-mean-line-v1', 'rounded-angle-saint-venant-v1'}:
                if source in shown_coupled_service:
                    continue
                shown_coupled_service.add(source)
                stress_label = 'Tensão normal máxima (Cw=0)' if info.get('normal_mode_count') == 3 else 'Tensão normal máxima, incluindo empenamento'
                content += '<p style="margin:5px 0;color:#57606a">' + escape(
                    f"Rigidez efetiva acoplada — {source}: {info['iterations']} iterações; "
                    f"Aef/Ag={formatted(info['EA_factor'])}; menor razão de energia normal={formatted(info['EI_factor'])}. "
                    f"{stress_label}={formatted(info.get('maximum_normal_stress_mpa'), 'MPa')} "
                    f"em x={formatted(info.get('maximum_stress_position_m'), 'm')}. " + info.get('method', '')) + '</p>'
                normal_basis = '[1, z, −y]' if info.get('normal_mode_count') == 3 else '[1, z, −y, ω]'
                pole_note = ('A cantoneira usa Cw=0, com polo efetivo de Saint-Venant recalculado.' if info.get('normal_mode_count') == 3 else
                             'A função ω mantém o polo principal da seção bruta; a matriz preserva os acoplamentos da redução.')
                content += f'<p style="margin:5px 0;color:#57606a">Matriz normal efetiva dividida por E; base {normal_basis} nos eixos geométricos. Os termos fora da diagonal foram usados na análise. As coordenadas normais referem-se ao centroide adotado pelos nós. {pole_note}</p>'
                if info.get('shear_center_section_mm') is not None:
                    offsets = [a-b for a, b in zip(info['shear_center_section_mm'], info['normal_origin_section_mm'], strict=True)]
                    pole_label = 'Centro de torção efetivo em relação ao centroide' if info.get('normal_mode_count') == 3 else 'Polo setorial bruto em relação ao centroide'
                    content += table([(pole_label, 'y='+formatted(offsets[0], 'mm')+'; z='+formatted(offsets[1], 'mm'))])
                exponents = (0, 1, 1, 2)
                labels = ('1', 'z', '−y', 'ω')
                content += table([(labels[i], '; '.join(labels[j]+'='+formatted(value, {2: 'mm²', 3: 'mm³', 4: 'mm⁴', 5: 'mm⁵', 6: 'mm⁶'}[2+exponents[i]+exponents[j]])
                    for j, value in enumerate(values))) for i, values in enumerate(info.get('normal_gram', ()))])
                content += table([('Limite superior da tensão equivalente em serviço',
                    formatted(info.get('maximum_equivalent_stress_bound_mpa'), 'MPa')),
                    ('Posição governante do limite', formatted(info.get('equivalent_bound_position_m'), 'm'))])
                notes.append(info.get('elasticity_method', ''))
                notes.append(info.get('factor_scope', ''))
            else:
                content += '<p style="margin:5px 0;color:#57606a">' + escape(
                    f"Rigidez efetiva — {source}: EI/EIg={formatted(info['EI_factor'])}; "
                    f"EA/EAg={formatted(info['EA_factor'])}; {info['iterations']} iterações. "
                    + info.get("method", "")) + '</p>'
            notes.extend(info.get("notes", ()))
        if parameters.get("force_source"):
            content += '<p style="margin:5px 0;color:#57606a">' + escape(parameters['force_source'] + '. ' + parameters.get('assumptions', '')) + '</p>'
            content += table([(label, formatted(parameters.get(key), unit)) for label, key, unit in (
                ('Contato longitudinal', 'contact_mm', 'mm'), ('Distância livre à extremidade', 'edge_distance_mm', 'mm'),
                ('Altura plana da alma', 'h_mm', 'mm'), ('Espessura', 't_mm', 'mm'), ('Raio interno', 'ri_mm', 'mm'))])
        for source, info in parameters.get('analysis_methods', {}).items():
            notes.append(f"Análise — {source}: {info['method']}; fator EA/EI={formatted(info['EA_EI_factor'])}. "
                         + info.get('imperfections', '') + '. ' + info.get('scope', ''))
        notes.extend(parameters.get("restraint_notes", ()))
        notes.extend(parameters.get("restraint_issues", ()))
        notes.extend(parameters.get("advisories", ()))
    content += '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">Premissas e limites</p>'
    if cold:
        content += '<p style="margin:5px 0;color:#57606a">' + escape(
            "Base normativa: ABNT NBR 14762:2010. O método da resistência direta (MRD, Anexo C) "
            "utiliza a seção bruta e esforços críticos global, local e distorcional de análise geral "
            "de estabilidade elástica (C.2). Os modos local e distorcional são calculados por faixas "
            "finitas para compressão uniforme e flexão com momento uniforme, considerando ambos os "
            "sinais. O crítico global usa KL1/KL2/KLt ou análise externa; na flexão automática exige "
            "confirmação dos garfos, empenamento livre e carga no centro de torção. Um modo só é omitido "
            "por dispensa normativa, espaço modal nulo ou declaração de análise geral, conforme C.2. Para diagramas "
            "não uniformes ou contenções diferentes, confira a análise e informe o valor manualmente. "
            "A identificação automática usa mínimos internos das curvas e uma classificação modal numérica; "
            "isso é uma salvaguarda do solver, não um limite adicional da norma. Se um modo não for "
            "identificado com segurança, a verificação fica pendente. As resistências incluem os modos disponíveis e o coeficiente de ponderação "
            "próprio do MRD: 1,20 na compressão e 1,10 na flexão. "
            "As áreas An, An0 e Ct são dados explícitos da ligação. "
            "Os módulos elásticos incluem o acoplamento pelo produto de inércia. "
            "Não se presume travamento por telhas, ausência de torção nem divisão de cortante entre almas. "
            "Cortantes Y e Z são independentes; a interação de momento e cortante de 9.8.4 é examinada separadamente. "
            "O Anexo D usa as regiões declaradas e forças ELU por alma, sem presumir partilha. O serviço usa nova análise com rigidez efetiva pelo MLE e limites de deslocamento explícitos. Não estão incluídos o dimensionamento das ligações e furos na flexão. "
            "O modelo de barra deve representar a linha efetiva de aplicação das cargas; excentricidades "
            "em relação ao centro de torção exigem efeitos de torção e empenamento.") + '</p>'
    else:
        content += '<p style="margin:5px 0;color:#57606a">' + escape(
            "A espessura informada deve corresponder ao produto e atender a 5.1.3. "
            "Foi adotada a curva geral de compressão da NBR 8800:2024, sem presumir tratamento térmico. "
            "An e Ct devem ser determinados conforme os furos e a transmissão de força da ligação. "
            "Comprimentos automáticos são estimativas do modelo; confira as contenções efetivas. "
            "As verificações de cortante Y e Z são independentes. Esta memória trata das resistências das barras; "
            "não inclui o dimensionamento das ligações nem os estados-limite de serviço.") + '</p>'
    if memory.get("profile_type") in {"Tubular Quadrado", "Tubular Retangular"}:
        content += '<p style="margin:5px 0;color:#57606a">' + escape(
            "Os cantos seguem a geometria do programa: raio externo 2t e interno t. "
            "As larguras planas são as dimensões externas menos 4t. "
            "O coeficiente Cb padrão é 1,0, conservador; valores manuais exigem justificativa. "
            "A FLT segue a Tabela D.1 para cargas aplicadas à meia-altura da seção. "
            "A parcela GJ/r0² é usada para comprovar que a torção não governa a compressão; "
            "se essa comprovação não for possível, a verificação fica pendente de Cw.") + '</p>'
    for note in dict.fromkeys(notes):
        content += f'<p style="margin:5px 0;color:#57606a">{escape(str(note))}</p>'
    return content + '</div>'
