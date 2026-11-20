"""Trace the adopted global second-order/imperfection procedure."""
from math import isclose, isfinite

from osa.services.notional_service import notional_plan_current


def stability_procedure(model, results):
    base = {'critical_check': 'Análise global, imperfeições e segunda ordem',
            'reference': 'ABNT NBR 14762:2010, 8.1; ABNT NBR 8800:2024, 4.10.4 e 4.10.7',
            'parameters': {}, 'steps': []}
    if not model.load_combinations:
        return {**base, 'status': 'not_applicable', 'detail':
                'API de esforços de seção sem cadastro de combinações: o resultado não valida a análise global da estrutura.'}
    try:
        compressed = {name for result in results for name, data in result.member_results.items()
                      if any(float(sample.get('axial', 0)) > 1e-6 for sample in data.get('samples', ()))}
    except (TypeError, ValueError, OverflowError):
        return {**base, 'status': 'not_checked', 'detail': 'Resultados globais incompletos ou inválidos para verificar a estabilidade.'}
    if not compressed:
        return {**base, 'status': 'not_applicable', 'detail':
                'Não foram identificadas barras comprimidas nos casos de cálculo processados. Não há amplificação P–Δ por compressão nesses casos.'}
    try:
        if not model.notional_plan or not notional_plan_current(model):
            raise ValueError('Cadastre/revise os níveis resistentes e forças gravitacionais de cálculo e gere as forças nocionais. P–Delta sem tratamento das imperfeições não conclui 8.1.')
        if not model.second_order_analysis or abs(model.ultimate_stiffness_factor-.8) > 1e-12:
            raise ValueError('O procedimento implementado exige segunda ordem e EA/EI=0,8 nos ELU, inclusive nos casos nocionais.')
        if model.plates:
            raise ValueError('O procedimento de segunda ordem implementado se aplica ao modelo de barras, sem não linearidade geométrica de placas.')
        for name in compressed:
            member = model.bars.get(name)
            if member is None:
                continue
            a, b = model.nodes[member.start_node], model.nodes[member.end_node]
            if abs(a.z-b.z) > 1e-7:
                upper = a if a.z > b.z else b
                if upper.name not in {station.upper_node for station in model.notional_plan.stations}:
                    raise ValueError('Nível resistente sem ponto de controle/carga nocional na barra comprimida '+name+'. Inclua nós intermediários com contribuição gravitacional zero, quando necessário.')
            if model.material_types.get(member.material) != 'Aço':
                raise ValueError('Este procedimento não abrange barras comprimidas mistas ou de outro material; suas rigidezes e análise exigem tratamento próprio.')
        by_reference = {result.load_reference: result for result in results}
        if len(by_reference) != len(results):
            raise ValueError('Resultados ELU duplicados; processe novamente.')
        if not set(model.notional_plan.combinations) <= set(by_reference):
            raise ValueError('Processe todas as combinações nocionais cadastradas, nos quatro sentidos.')
        classifications, maximum = {}, 1.
        all_ultimate = {name for name, combo in model.load_combinations.items() if combo.limit_state.upper() == 'ELU'}
        if not all_ultimate <= set(by_reference):
            raise ValueError('Processe todas as combinações ELU para classificar a estabilidade.')
        for reference in all_ultimate:
            result = by_reference[reference]
            if result.model_revision != model.revision:
                raise ValueError('Resultados de estabilidade desatualizados.')
            # The same global procedure metadata is attached to each member.
            metadata = next(iter(result.member_results.values()), {}).get('structural_analysis', {})
            if (metadata.get('method') != 'P-Delta' or metadata.get('EA_EI_factor') != .8 or
                    metadata.get('notional_basis') != model.notional_plan.basis):
                raise ValueError('Caso nocional sem análise P–Delta com a rigidez e a proveniência exigidas.')
            if (metadata.get('tangent_stability') or {}).get('status') != 'positive':
                raise ValueError('Rigidez tangente não conferida no equilíbrio P–Delta.')
            info = metadata.get('storey_amplification')
            if not info or info.get('algorithm') != 'osa-story-base-v1' or info['classification'] == 'indeterminada':
                raise ValueError('Não foi possível classificar a deslocabilidade por comparação entre primeira e segunda ordem. Reveja os pontos de controle dos níveis.')
            if not isfinite(float(info['maximum_ratio'])):
                raise ValueError('Amplificação de deslocamento não finita.')
            expected_rows = {(station.upper_node, station.base_node, direction)
                             for station in model.notional_plan.stations for direction in ('X', 'Y')}
            rows = info.get('rows', ())
            if len(rows) != len(expected_rows) or {(row['upper_node'], row['base_node'], row['direction']) for row in rows} != expected_rows:
                raise ValueError('Pontos de controle da classificação incompletos ou incompatíveis.')
            ratios = []
            for row in rows:
                first, second, ratio = (float(row[key]) for key in ('first_order_m', 'second_order_m', 'ratio'))
                if not all(isfinite(value) for value in (first, second, ratio)):
                    raise ValueError('Deslocamentos de classificação não finitos.')
                actual = float(result.node_results[row['upper_node']]['D'+row['direction']])-float(result.node_results[row['base_node']]['D'+row['direction']])
                expected_ratio = abs(second/first) if abs(first) >= 1e-10 else 1. if abs(second) < 1e-10 else None
                if not isclose(actual, second, rel_tol=1e-8, abs_tol=1e-10) or expected_ratio is None or not isclose(ratio, expected_ratio, rel_tol=1e-8, abs_tol=1e-10):
                    raise ValueError('Deslocamentos ou amplificação sem correspondência com os resultados processados.')
                ratios.append(ratio)
            if not isclose(max(ratios), info['maximum_ratio'], rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError('Envoltória de amplificação incompatível com os níveis.')
            expected_class = 'pequena' if info['maximum_ratio'] <= 1.13 else 'média' if info['maximum_ratio'] <= 1.55 else 'grande'
            if info['classification'] != expected_class:
                raise ValueError('Classificação não corresponde à amplificação dos deslocamentos.')
            if info['classification'] == 'grande' and not model.notional_plan.allow_large_displacement:
                raise ValueError('Grande deslocabilidade: exige análise rigorosa ou opção expressa do responsável pelo procedimento alternativo de 4.10.7.2, com nocionais adicionadas às ações horizontais.')
            classifications[reference] = info
            maximum = max(maximum, info['maximum_ratio'])
        return {**base, 'status': 'checked', 'utilization': 0., 'applied': 0., 'capacity': 1.,
                'critical_combination': max(classifications, key=lambda name: classifications[name]['maximum_ratio']),
                'critical_member': 'sistema', 'critical_position_m': 0., 'combinations': [],
                'detail': 'Procedimento de análise conferido; as resistências e ligações são verificações separadas.',
                'parameters': {'global_stability': classifications,
                    'large_alternative': model.notional_plan.allow_large_displacement, 'maximum_amplification': maximum,
                    'advisories': ('Classificação por envoltória conservadora de todos os sinais e combinações ELU, incluindo situações de ações horizontais e gravitacionais com efeitos opostos; não se utiliza dispensa de casos para reduzir a classe.', 'Forças nocionais adicionadas também às combinações com ações horizontais. Contribuições gravitacionais por nível/nó declaradas no cadastro; não são forças axiais acumuladas dos pilares.',)}}
    except (KeyError, TypeError, ValueError) as exc:
        return {**base, 'status': 'not_checked', 'detail': str(exc)}
