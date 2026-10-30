"""Opt-in Action clearing of one reachable square of a retained plant area."""
from . import effect, hook

CLEAR = 'system:combat.clear_growth'


def options(engine, actor):
    from .. import targeting, senses
    out = {}
    for zone in engine.state.zones.values():
        if not zone.active or (zone.trigger_profile.get('profile') or {}).get('clear_square_action') != 1:
            continue
        for cell in zone.affected_cells:
            if (engine._distance_actor_to_cell(actor, cell) <= 5
                    and targeting.line_of_effect(engine, actor, destination=cell)
                    and senses.perceives_cell(engine, actor, cell)):
                out[f'{zone.zone_id}|{cell.x}|{cell.y}'] = (zone, cell)
    return out


@hook('match_start')
def add_clear_action(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any(((((a.parameters or {}).get('typed') or {}).get('zone_spec') or {}).get('profile') or {}).get('clear_square_action') == 1
               for a in engine.action_catalog.values()):
        return
    engine.action_catalog[CLEAR] = ActionDefinition(
        source_definition_id=CLEAR, display_name='Clear a square of growth', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={
            'typed': {'effects': [{'type': 'clear_growth_square'}], 'numbers': {}, 'riders': []},
            'description': 'Spend your Action to clear one 5-foot square of growth within 5 feet. '
                           'That square stops hindering movement or applying the area’s effects.'})


@hook('additional_actions')
def offer_clear_action(engine, actor):
    return [CLEAR] if CLEAR in engine.action_catalog and options(engine, actor) else []


@hook('candidate_allowed')
def clear_allowed(engine, actor, candidate, action):
    if action is not None and action.source_definition_id == CLEAR:
        return bool(options(engine, actor))
    return None


@effect('clear_growth_square')
def clear_square(ctx, row):
    from .needle import ask, checkpoint_id
    from .retained_updates import record_zone_update
    from .. import zones
    pool = options(ctx.engine, ctx.actor)
    labels = {key: f'{zone.trigger_profile.get("name") or "Growth"}: clear square {cell.x},{cell.y}'
              for key, (zone, cell) in pool.items()}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'CLEAR_GROWTH', ctx.actor.entity_id),
                 ctx.actor, 'choice:needle.clear_growth', list(pool), labels=labels,
                 name='Clear a square of growth', prompt='Choose one reachable 5-foot square to clear with your Action.')
    if len(chosen) != 1 or chosen[0] not in pool:
        return
    zone, cell = pool[chosen[0]]
    zone.affected_cells = tuple(p for p in zone.affected_cells if (p.x, p.y) != (cell.x, cell.y))
    record_zone_update(ctx.engine, zone)
    zones.sync_inside(ctx.engine, ctx.source)
    if not zone.affected_cells:
        zones.remove(ctx.engine, zone, 'CLEARED')


@effect('select_zone_terrain_enemies')
def select_terrain_enemies(ctx, row):
    """Choose hostile recipients of this activation's Difficult Terrain only."""
    from .. import zones
    from ..target_knowledge import can_see
    from .needle import ask, checkpoint_id
    from .retained_updates import record_zone_update
    zone = next((z for z in reversed(list(ctx.engine.state.zones.values()))
                 if z.active and z.owner_id == ctx.actor.entity_id and z.source_definition_id == ctx.source), None)
    if zone is None:
        return
    pool = [a for a in sorted(ctx.engine.state.actors.values(), key=lambda a:a.entity_id)
            if a.active and a.team_id != ctx.actor.team_id and can_see(ctx.engine,ctx.actor,a)
            and zones._inside(ctx.engine,a,zone)]
    ids = [a.entity_id for a in pool]
    picked = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'GROWTH_TERRAIN',ctx.source),ctx.actor,
                 'choice:needle.growth_terrain',ids,
                 labels={a.entity_id:f'{a.display_name}: growth becomes Difficult Terrain for this enemy' for a in pool},
                 preferred=ids,minimum=0,maximum=len(ids),allow_decline=True,default='all',default_count=len(ids),
                 name='Cultivated Overgrowth',prompt='Choose enemies in the growth whose movement costs twice as much. '
                 'You may choose none. All enemies still gain a Growth Mark when they enter or start their turn here.')
    zone.trigger_profile['difficult_target_ids'] = [aid for aid in picked if aid in ids]
    record_zone_update(ctx.engine,zone)
