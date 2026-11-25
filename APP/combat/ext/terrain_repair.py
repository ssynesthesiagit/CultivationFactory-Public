"""Action clearing for retained physical terrain with declared suitable tools."""
from . import effect, hook

CLEAR = 'system:combat.repair_terrain'


def options(engine, actor):
    from .. import carry, senses, targeting
    items = (carry.carrying_of(engine, actor.entity_id) or {}).get('items') or []
    held = {item.get('item_id') for item in items if carry.holds(engine, actor, item['key'])}
    pool = {}
    for zone in engine.state.zones.values():
        profile = (zone.trigger_profile or {}).get('profile') or {}
        tools = profile.get('repair_tools') or []
        if not zone.active or not tools or not held.intersection(tools):
            continue
        for cell in zone.affected_cells:
            if (engine._distance_actor_to_cell(actor, cell) <= 5
                    and targeting.line_of_effect(engine, actor, destination=cell)
                    and senses.perceives_cell(engine, actor, cell)):
                key = f'{cell.x}|{cell.y}|{cell.z}'
                entry = pool.setdefault(key, {'cell': cell, 'zones': []})
                if zone not in entry['zones']:
                    entry['zones'].append(zone)
    return pool


@hook('match_start')
def add_repair(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any((((a.parameters.get('typed') or {}).get('zone_spec') or {}).get('profile') or {}).get('repair_tools')
               for a in engine.action_catalog.values()):
        return
    engine.action_catalog[CLEAR] = ActionDefinition(
        source_definition_id=CLEAR, display_name='Clear broken ground', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={
            'typed': {'effects': [{'type': 'repair_terrain_square'}], 'numbers': {}, 'riders': []},
            'description': 'Use a shovel or masonry tools and your Action to clear one 5-foot square of broken ground within 5 feet.'})


@hook('additional_actions')
def offer_repair(engine, actor):
    return [CLEAR] if CLEAR in engine.action_catalog and options(engine, actor) else []


@hook('candidate_allowed')
def repair_allowed(engine, actor, candidate, action):
    if action is not None and action.source_definition_id == CLEAR:
        return bool(options(engine, actor))
    return None


@effect('repair_terrain_square')
def repair_square(ctx, row):
    from .needle import ask, checkpoint_id
    from .retained_updates import record_zone_update
    from .. import zones
    pool = options(ctx.engine, ctx.actor)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'REPAIR_TERRAIN', ctx.actor.entity_id),
                 ctx.actor, 'choice:needle.repair_terrain', list(pool),
                 labels={key: f'Clear square {entry["cell"].x},{entry["cell"].y}' for key, entry in pool.items()},
                 name='Clear broken ground', prompt='Choose one reachable square to clear with your tools and Action.')
    if len(chosen) != 1 or chosen[0] not in pool:
        return
    entry = pool[chosen[0]]
    cell = entry['cell']
    for zone in entry['zones']:
        zone.affected_cells = tuple(p for p in zone.affected_cells if p != cell)
        record_zone_update(ctx.engine, zone)
        if not zone.affected_cells:
            zones.remove(ctx.engine, zone, 'REPAIRED')
    zones.sync_inside(ctx.engine, ctx.source)
