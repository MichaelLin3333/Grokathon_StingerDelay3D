"""Shared v0 wire adapter. Internal planner keeps one source of travel numbers."""

def shared_plan(body, planner):
    constraints = body.get('constraints')
    if not isinstance(constraints, dict):
        raise ValueError('constraints must be an object')
    prefs = constraints.get('prefs') or {}
    trace = planner.plan_trip({'origin': constraints.get('origin'), 'destination': constraints.get('destination'),
        'arrive_by': constraints.get('arrive_by'), 'depart_at': constraints.get('depart_at'),
        'avoid_stairs': prefs.get('avoid_stairs', False), 'walk_speed': prefs.get('walk_speed_mps', 1.35)})
    def convert(plan):
        return {'legs': [{'kind': leg['kind'], 'duration_s_p50': leg['duration_minutes']*60,
                 'label': leg['instruction'], 'route_id': str(leg['route_id']) if leg['route_id'] is not None else None,
                 'path': leg['geometry'], 'distance_m': leg['distance_m'], 'estimate': leg.get('approximate', False),
                 'synthetic': plan['synthetic']} for leg in plan['legs']],
                'total_s': {key: value*60 for key, value in plan['quantiles'].items()},
                'leave_at': plan['departure_time'], 'arrive_at': plan['arrival_time'],
                'p_on_time': plan['p_on_time'], 'p_catch': plan['p_catch'],
                'explanation_facts': trace['explanation_facts'], 'mode': 'bus' if any(l['kind']=='ride' for l in plan['legs']) else 'walk_only'}
    return {'trace': {'plan': convert(trace['chosen']), 'alternatives': [convert(p) for p in trace['alternatives']],
        'allowed_numbers': trace['allowed_numbers'], 'model_id': trace['chosen']['prediction_source'],
        'confidence_horizon_s': trace['constraints']['horizon_minutes']*60, 'verification_version': 'v0',
        'status': 'at_risk' if trace['chosen']['p_on_time'] is not None and trace['chosen']['p_on_time'] < .9 else 'ok',
        'origin_name': trace['origin']['name'], 'destination_name': trace['destination']['name']}, 'contract_version': 'v0'}
