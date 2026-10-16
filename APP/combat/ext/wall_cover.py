"""Attack-qualified terrain walls, shared by actual attacks and AI previews.

zones.sync_walls derives these profiles from committed zones on creation and
reload. Unqualified walls keep the common terrain path; absent walls are inert.
"""
from . import hook


@hook('directional_cover')
def restricted_wall_cover(engine, attacker, target, ray):
    attack = ray.get('attack')
    if not attack:
        return None
    profiles = engine.__dict__.get('_qualified_wall_cover', ())
    cells = engine.__dict__.get('_cover_ranged_weapon', set())
    if not profiles and not cells:
        return None
    # Use the resolving packet's kind, not its held weapon: a cultivated
    # weapon-damage attack still isn't an ordinary weapon attack.
    kind = ((attack.get('effect') or {}).get('attack_kind')
            or (attack.get('parameters') or {}).get('attack_kind')
            or ('weapon' if attack.get('delivery') == 'weapon' else 'unknown'))
    from ..space import position
    from ..terrain_occlusion import cell_span_hit
    start, end = position(ray['start']), position(ray['end'])
    bonuses = []
    for row in profiles:
        rule = row['rule']
        if rule.get('cover_ranged_only') and not ray.get('ranged'):
            continue
        if rule.get('cover_attack_kinds') and kind not in rule['cover_attack_kinds']:
            continue
        bottom = int(rule.get('base_altitude_ft', 0))
        height = rule.get('height_ft')
        top = bottom + height if height is not None else None
        if any(cell_span_hit(start, end, cell, bottom, top) for cell in row['cells']):
            bonuses.append(5 if rule['cover'] == 'three_quarters' else 2)
    # Retain the pre-existing explicit restricted-cell query contract.
    if cells and ray.get('ranged') and attack.get('delivery') == 'weapon':
        crossed = {tuple(row['cell']) for row in ray.get('crossed_edges') or ()}
        if cells & crossed:
            bonuses.append(5)
    return max(bonuses, default=0) if bonuses else None
