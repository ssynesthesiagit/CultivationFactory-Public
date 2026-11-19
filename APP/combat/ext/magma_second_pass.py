"""Reviewed Magma moving lines on the shared surface-area extension."""
from . import hook

MOVERS = {
    'TAL_MAGMA_LAVA_FLOW': 'Lava Flow',
    'TAL_MAGMA_BLACKGLASS_RIVER': 'Blackglass River',
}


@hook('compile_actions')
def moving_lines(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for source, name in MOVERS.items():
        mechanic = info['mechanics'].get(source) or {}
        if source not in info['owned_ids'] or not (mechanic.get('area') or {}).get('surface_bound'):
            continue
        original = f"action:typed.{info['short']}.{source}"
        movement = (mechanic.get('area') or {}).get('surface_translation')
        if not movement:
            continue
        spec = {'source': source, **movement}
        distance = ('up to ' if spec.get('min_ft', 0) < spec['max_ft'] else '') + f"{spec['max_ft']} feet"
        out.append(ActionDefinition(
            source_definition_id=original+'.move', display_name=name+': move the line', owner_id=info['actor_id'],
            economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'effects': [{'type': 'surface_translation', **spec}],
                                 'source': 'system:surface_translation', 'numbers': info['numbers'], 'duration': {'kind': 'instant'}, 'riders': []},
                        'surface_translation': spec, 'rider_utility': 8, 'expected_damage': 0,
                        'description': f'Bonus Action while concentrating: move your {name} {distance} along a continuous surface. '
                                       'Its width and direction stay the same; it cannot pass through walls or empty air.'}))
    return out or None
