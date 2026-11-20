"""Effective service rigidity and displacement checks for cold-formed bars."""
from __future__ import annotations

from functools import lru_cache
from math import isfinite

import numpy as np
from scipy.linalg import eigh

from osa.analysis.vlasov import VLASOV_ALGORITHM
from osa.sections.thin_walled import open_sheet
from osa.verification.calculation_properties import calculation_property
from osa.verification.restraints import MemberChainRestraints
from osa.verification.structured_checks import check, number, step, valid_sample

SERVICE_ALGORITHM = 'coupled-normal-width-global-1'


def service_checks(element, model):
    """Check declared ELS measurements from re-solved effective-rigidity data."""
    reference = 'ABNT NBR 14762:2010, 9.8.5 e Anexo A'
    combinations = {name for name, combo in model.load_combinations.items() if combo.limit_state.upper().startswith('ELS')}
    checks = {}
    if not combinations:
        # The low-level API without a combination registry can still verify
        # supplied design forces. Registered projects require a defined ELS.
        status = 'not_checked' if model.load_combinations else 'not_applicable'
        detail = ('Cadastre e processe as combinações ELS para verificar os deslocamentos.' if model.load_combinations else
                  'API de esforços de cálculo sem escopo de serviço informado; este resultado se refere às resistências de barra.')
        return {'serviceability': {'status': status, 'critical_check': 'Deslocamentos em serviço', 'reference': reference,
                                   'detail': detail, 'parameters': {}, 'steps': []}}
    try:
        method = calculation_property(model, element, 'ServiceMeasure', None)
        if method not in (1., 2., 3.):
            raise ValueError('Escolha a medição de serviço: flecha relativa à corda, deslocamento entre extremidades ou absoluto.')
        selected = [result for result in model.analysis_results if result.load_reference in combinations]
        results = {result.load_reference: result for result in selected}
        if len(results) != len(selected):
            raise ValueError('Resultados ELS duplicados; processe novamente para identificar cada combinação sem ambiguidade.')
        if set(results) != combinations:
            raise ValueError('Resultados ELS ausentes; processe todas as combinações de serviço cadastradas.')
        bars, basis, origin, interval = MemberChainRestraints(model)._element_chain(element)
        axis, local_y, local_z = (np.asarray(vector, dtype=float) for vector in basis)
        span = interval[1]-interval[0]
        service_samples = {'y': [], 'z': []}
        stiffness = {}
        for combination, result in results.items():
            if result.model_revision != model.revision:
                raise ValueError('Resultados ELS desatualizados; processe novamente.')
            rows = []
            for member in bars:
                data = result.member_results.get(member.name, {})
                info = data.get('service_stiffness', {})
                if info.get('status') != 'converged':
                    raise ValueError('ELS sem análise convergida de rigidez efetiva: '+member.name+'. '+info.get('detail', 'Processe novamente o modelo.'))
                if not all(isfinite(float(info.get(key, float('nan')))) and 0 < float(info[key]) <= 1 for key in ('EI_factor', 'EA_factor')):
                    raise ValueError('Fatores de rigidez efetiva ELS inválidos; processe novamente.')
                analysis_version = data.get('warping_analysis', {})
                if analysis_version and analysis_version.get('algorithm') != VLASOV_ALGORITHM:
                    raise ValueError('ELS com algoritmo de empenamento anterior; processe novamente.')
                coupled = info.get('geometry_basis') in {'rounded-mean-line-v1', 'rounded-angle-saint-venant-v1'}
                if not coupled:
                    raise ValueError('ELS sem solução acoplada da matriz normal e do centro de torção; ative a análise dos formados e processe novamente.')
                angle_model = member.section == 'L Formado'
                modes = 3 if angle_model else 4
                expected_basis = 'rounded-angle-saint-venant-v1' if angle_model else 'rounded-mean-line-v1'
                expected_convention = 'Nc,-My,+Mz,-B' if coupled and not angle_model else 'Nc,-My,+Mz'
                if info.get('normal_stress_convention') != expected_convention:
                    raise ValueError('ELS com convenção de tensão anterior; processe novamente com a convenção de compressão Nc,−My,+Mz e −B quando aplicável.')
                if data.get('warping_analysis', {}).get('geometry_basis') in {'rounded-mean-line-v1', 'rounded-angle-saint-venant-v1'} and not coupled:
                    raise ValueError('ELS com empenamento sem matriz efetiva acoplada; processe novamente.')
                if coupled:
                    if info.get('service_algorithm') != SERVICE_ALGORITHM:
                        raise ValueError('ELS com procedimento de atualização de larguras anterior; processe novamente.')
                    bound = float(info.get('maximum_equivalent_stress_bound_mpa', float('nan')))
                    fy_service = float(model.materials[member.material][4])/1000
                    if info.get('elasticity') != 'proven_by_upper_bound' or not isfinite(bound) or bound < 0 or bound > fy_service*(1+1e-6):
                        raise ValueError('ELS com empenamento sem comprovação elástica conjunta das tensões normais e de cisalhamento; processe novamente.')
                    analysis = data.get('warping_analysis', {})
                    matrix = np.asarray(info.get('normal_gram'), dtype=float)
                    processed = np.asarray(analysis.get('normal_gram_geometric'), dtype=float)
                    if (analysis.get('geometry_basis') != expected_basis or matrix.shape != (modes, modes) or
                            processed.shape != (modes, modes) or not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(processed)) or
                            np.any(np.diag(matrix) <= 0)):
                        raise ValueError('Matriz normal/setorial ELS inválida ou ausente.')
                    scale = np.sqrt(np.diag(matrix))
                    if np.max(abs(matrix-processed)/np.outer(scale, scale)) > 1e-9:
                        raise ValueError('A matriz efetiva ELS não corresponde à rigidez usada na análise.')
                    if not isfinite(float(info.get('normal_matrix_relative_error', float('nan')))) or info['normal_matrix_relative_error'] > 1e-6:
                        raise ValueError('A iteração da matriz efetiva ELS não comprova convergência.')
                    pole = np.asarray(info.get('shear_center_section_mm'), dtype=float)
                    actual_pole = np.asarray(analysis.get('normal_origin_section_mm'))+np.asarray(analysis.get('shear_center_offset_geometric_mm'))
                    if pole.shape != (2,) or actual_pole.shape != (2,) or not np.all(np.isfinite(pole)) or not np.all(np.isfinite(actual_pole)) or np.max(abs(pole-actual_pole)) > 1e-8:
                        raise ValueError('O centro de torção efetivo ELS não corresponde ao usado na análise.')
                    if not isfinite(float(info.get('shear_center_relative_error', float('nan')))) or info['shear_center_relative_error'] > 1e-6:
                        raise ValueError('A iteração do centro de torção efetivo não comprova convergência.')
                stiffness[combination+' / '+member.name] = info
                start, end = model.nodes[member.start_node], model.nodes[member.end_node]
                start_point = np.array((start.x, start.y, start.z))
                end_point = np.array((end.x, end.y, end.z))
                sign = 1 if (end_point-start_point)@axis > 0 else -1
                offset = float((start_point-origin)@axis)-interval[0]
                samples = data.get('samples', ())
                if not samples:
                    raise ValueError('Amostras ELS ausentes para '+member.name+'.')
                for sample in samples:
                    if not valid_sample(sample, data):
                        raise ValueError('Amostra ELS incompleta ou inconsistente com a análise de torção/empenamento.')
                    position = offset+sign*float(sample['x'])
                    displacement = np.array([float(sample['deflection_'+direction]) for direction in ('x', 'y', 'z')])
                    if not isfinite(position) or position < -1e-7 or position > span+1e-7 or not np.all(np.isfinite(displacement)):
                        raise ValueError('Deslocamentos ELS não finitos.')
                    rows.append((position, member.name, sample, displacement))
            rows.sort(key=lambda row: row[0])
            if abs(rows[0][0]) > 1e-7 or abs(rows[-1][0]-span) > 1e-7:
                raise ValueError('As amostras ELS não cobrem as extremidades do elemento.')
            start_displacement, end_displacement = rows[0][3], rows[-1][3]
            for position, member_name, sample, displacement in rows:
                measured = (displacement-((1-position/span)*start_displacement+position/span*end_displacement) if method == 1 else
                            end_displacement-start_displacement if method == 2 else displacement)
                for direction, local in (('y', local_y), ('z', local_z)):
                    service_samples[direction].append((combination, member_name, {
                        **sample, 'service_displacement_mm': abs(float(measured@local))*1000,
                    }))
        for direction in ('y', 'z'):
            limit = calculation_property(model, element, 'Delta'+direction.upper(), None)
            error = None if limit is not None else 'Informe o limite de deslocamento '+direction.upper()+' em mm, conforme o uso e as combinações do Anexo A.'
            params = {'measurement': 'flecha relativa à corda' if method == 1 else 'deslocamento entre extremidades' if method == 2 else 'deslocamento absoluto',
                      'span_m': span, 'service_stiffness': stiffness}
            item = check('flexion_'+direction, service_samples[direction], lambda row: row['service_displacement_mm'],
                         limit, params, [], reference, error)
            item['critical_check'] = 'ELS — deslocamento '+direction.upper()
            if item['status'] == 'checked':
                item['steps'] = [step(r'\delta_{'+direction+'}', r'|u-u_{corda}|' if method == 1 else r'|u_B-u_A|' if method == 2 else r'|u|',
                                     number(item['applied']), item['applied'], 'mm', 'Anexo A'),
                                 step(r'\delta_{lim}', r'\delta_{lim}', number(limit), limit, 'mm', 'Anexo A')]
            checks['serviceability_'+direction] = item
        return checks
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {'serviceability': {'status': 'not_checked', 'critical_check': 'Deslocamentos em serviço',
                                   'reference': reference, 'detail': str(exc), 'parameters': {}, 'steps': []}}


def coupled_service_stiffness(member, material, samples, *, retained_limit=None, structural_update=False):
    """Effective normal matrix in geometric axes, including the angle model."""
    from osa.analysis.vlasov import rounded_section_from_sheet
    from osa.sections.properties import calculate_section_properties
    from osa.sections.thin_walled import effective_shear_center
    from osa.verification.cold_formed_warping_effective import effective_normal_update, effective_warping_envelope

    E, fy = float(material[0])/1000, float(material[4])/1000
    if not all(isfinite(value) and value > 0 for value in (E, fy)):
        raise ValueError('E e fy inválidos para serviço com empenamento.')
    samples = tuple(samples)
    if not samples:
        raise ValueError('Amostras ELS com empenamento ausentes.')
    angle = member.section == 'L Formado'
    modes = 3 if angle else 4
    loads = []
    for row in samples:
        normal = (float(row['axial'])*1000, -float(row['moment_y'])*1e6, float(row['moment_z'])*1e6)
        if angle and abs(float(row['bimoment'])) > 1e-9:
            raise ValueError('O modelo de cantoneira Cw=0 não admite bimomento solicitante.')
        loads.append(normal if angle else (*normal, -float(row['bimoment'])*1e9))
    if not np.all(np.isfinite(loads)):
        raise ValueError('Esforços ELS com empenamento não finitos.')
    geometry = member.geometry_dict()
    sheet = open_sheet(member.section, geometry, mirror=member.section_mirrored)
    props = calculate_section_properties(member.section, geometry, mirror_z=member.section_mirrored)
    origin = (props.centroid_y_mm, props.centroid_z_mm)
    lip = (geometry['c']+sheet.thickness if member.section == 'C Formado' else
           geometry['c'] if member.section in {'Z45 Formado', 'Z90 Formado'} else None)
    update = effective_normal_update if structural_update else effective_warping_envelope
    envelope = update(sheet, E, loads, normal_origin=origin,
        nominal_lip=lip, retained_limit=retained_limit, sectorial_mode=not angle)
    if not structural_update and envelope.maximum_stress_mpa > fy*(1+1e-6):
        raise ValueError('A tensão normal ELS supera fy na seção efetiva do modelo Cw=0.' if angle else
                         'A tensão normal ELS incluindo bimomento supera fy na seção efetiva.')
    gross = rounded_section_from_sheet(member.section, geometry, member.section_mirrored,
        sectorial_mode=not angle).normal_gram[:modes, :modes]
    normal = np.asarray(envelope.normal_matrix)
    ratio = min(1., float(eigh(normal, gross, eigvals_only=True)[0]))
    if ratio <= 1e-6:
        raise ValueError('Rigidez normal/setorial efetiva insuficiente em serviço.')
    pole = effective_shear_center(envelope.field, envelope.intervals) if angle else envelope.field.shear_center_mm
    return {'service_algorithm': SERVICE_ALGORITHM if structural_update else 'fixed-force-section-1',
        'normal_gram': envelope.normal_matrix, 'retained_intervals': envelope.intervals,
        'normal_origin_section_mm': origin, 'shear_center_section_mm': pole, 'normal_mode_count': modes,
        'geometry_basis': 'rounded-angle-saint-venant-v1' if angle else 'rounded-mean-line-v1',
        'EI_factor': ratio, 'EA_factor': float(min(1., normal[0, 0]/gross[0, 0])),
        'factor_scope': 'Indicadores de redução; o solver usa a matriz normal completa, sem substituir os acoplamentos por estes escalares.',
        'maximum_normal_stress_mpa': envelope.maximum_stress_mpa,
        'normal_stress_convention': 'Nc,-My,+Mz' if angle else 'Nc,-My,+Mz,-B', 'section_iterations': envelope.iterations,
        'method': ('MLE acoplado; matriz normal 3×3, Cw=0 e polo efetivo de Saint-Venant' if angle else
                   'MLE acoplado; matriz normal/setorial 4×4, interseção das regiões efetivas, linha média arredondada'),
        'notes': (*envelope.notes, 'Modelo de parede fina sobre a linha média; não resolve concentrações locais de tensão nas dobras ou na introdução física das cargas.')}


def coupled_service_stress(member, material, samples, normal_gram, retained_intervals, *, second_order=False, shear_center_section_mm=None):
    """Constitutive stress audit for the matrix actually used in the solve."""
    from osa.sections.properties import calculate_section_properties
    from osa.sections.thin_walled import effective_shear_center, rounded_sectorial_field
    from osa.verification.cold_formed_warping_effective import _solve, maximum_warping_fiber_stress

    props = calculate_section_properties(member.section, member.geometry_dict(), mirror_z=member.section_mirrored)
    field = rounded_sectorial_field(open_sheet(member.section, member.geometry_dict(), mirror=member.section_mirrored),
        normal_origin=(props.centroid_y_mm, props.centroid_z_mm))
    matrix = np.asarray(normal_gram, dtype=float)
    angle = member.section == 'L Formado'
    modes = 3 if angle else 4
    if matrix.shape != (modes, modes):
        raise ValueError('Dimensão da matriz normal incompatível com o modelo da seção.')
    retained, weights = field.quadrature(retained_intervals)
    retained = retained[:, :modes]
    represented = retained.T@(weights[:, None]*retained)
    scale = np.sqrt(np.diag(matrix))
    if np.max(abs(represented-matrix)/np.outer(scale, scale)) > 1e-9:
        raise ValueError('As regiões efetivas não correspondem à matriz normal processada.')
    expected_pole = effective_shear_center(field, retained_intervals) if angle else field.shear_center_mm
    pole = np.asarray(shear_center_section_mm, dtype=float)
    if pole.shape != (2,) or not np.all(np.isfinite(pole)) or np.max(abs(pole-expected_pole)) > 1e-8*max(member.geometry_dict()['d'], member.geometry_dict()['bf']):
        raise ValueError('O centro de torção efetivo não corresponde à seção processada.')
    maximum, position, equivalent, equivalent_position = 0., 0., 0., 0.
    for row in samples:
        loads = (float(row['axial'])*1000, -float(row['moment_y'])*1e6, float(row['moment_z'])*1e6)
        if not angle:
            loads = (*loads, -float(row['bimoment'])*1e9)
        elif abs(float(row['bimoment']))+abs(float(row['warping_torque'])) > 1e-9:
            raise ValueError('A cantoneira Cw=0 não admite esforços de empenamento.')
        coefficients = _solve(matrix, np.asarray(loads))
        stress = maximum_warping_fiber_stress(field, (*coefficients, 0.) if angle else coefficients)
        if stress >= maximum:
            maximum, position = stress, float(row['x'])
        # Physical positive-face shears are the negatives of the plotted
        # Vy/Vz. With omega'=r_SC cross tangent, q'=d(sigma_compression)/dx
        # gives resultant (-Vy,-Vz,Tw) and zero flow at both free edges.
        compression = float(row['axial'])*1000 if second_order else 0.
        derivative_loads = np.array((0., float(row['shear_z'])*1000-compression*float(row['centroid_slope_z']),
            -float(row['shear_y'])*1000+compression*float(row['centroid_slope_y']), -float(row['warping_torque'])*1e6))
        derivative = _solve(matrix, derivative_loads[:modes])
        if angle:
            derivative = np.r_[derivative, 0.]
        variation = 0.
        for index, piece in enumerate(field.sheet.pieces):
            fraction = 1. if piece.center is not None else sum(b-a for a, b in retained_intervals[piece.plate])
            limit = maximum_warping_fiber_stress(field, derivative, piece_indices=(index,), include_faces=False)
            variation += limit*fraction*piece.length*field.sheet.thickness
        # q starts and ends at zero, so max|q| <= total_variation(q)/2.
        # Piecewise maxima times retained area bound that total variation.
        tau = variation/(2*field.sheet.thickness)+abs(float(row['saint_venant_torque']))*1e6*field.sheet.thickness/props.j_mm4
        bound = float(np.sqrt(stress**2+3*tau**2))
        if bound >= equivalent:
            equivalent, equivalent_position = bound, float(row['x'])
    if maximum > float(material[4])/1000*(1+1e-6):
        raise ValueError('A tensão normal ELS supera fy na matriz efetivamente usada do modelo Cw=0.' if angle else
                         'A tensão normal ELS incluindo bimomento supera fy na matriz efetivamente usada.')
    if equivalent > float(material[4])/1000*(1+1e-6):
        raise ValueError('Não foi comprovada a elasticidade ELS pelo limite superior de tensão equivalente, incluindo cortantes e torção; exige análise de tensões mais refinada ou revisão do modelo.')
    return {'maximum_normal_stress_mpa': maximum, 'maximum_stress_position_m': position,
            'maximum_equivalent_stress_bound_mpa': equivalent, 'equivalent_bound_position_m': equivalent_position,
            'elasticity': 'proven_by_upper_bound',
            'elasticity_method': ('Limite superior de von Mises por amostra concomitante: tensão normal máxima, variação total do fluxo de cortante e Saint-Venant nas duas faces.' if angle else
                                  'Limite superior de von Mises por amostra concomitante: tensão normal máxima, variação total do fluxo de cortante/empenamento e Saint-Venant nas duas faces.')}


@lru_cache(maxsize=256)
def _shear_center_offsets(family, geometry, mirror):
    from osa.analysis.vlasov import rounded_section_from_sheet

    section = rounded_section_from_sheet(family, dict(geometry), mirror, sectorial_mode=family != 'L Formado')
    return section.ysc/1000, section.zsc/1000


def shear_center_offsets(member):
    return _shear_center_offsets(member.section, tuple(sorted(member.geometry_dict().items())), member.section_mirrored)


def needs_warping_solution(member, samples):
    """Detect torsion/eccentric shear that a centroidal 6-DOF solve omits."""
    ysc, zsc = shear_center_offsets(member)
    # A cancelling centroidal couple also needs the coupled formulation.
    return any(max(abs(float(row['torque'])),
        abs(zsc*float(row['shear_y'])-ysc*float(row['shear_z']))) > 1e-6 for row in samples)
