"""Jester's printed creature passage, using native granted paths and passage hooks.

Painted Exit and Court-Hermit Step scope permission to their immediate move.
Dancing Fool owns its once-only crossing until the turn ends. Queries never
spend it; entry records the selected creature. Walls and endpoints stay native.
"""
from . import effect, hook

BLOCK = 'jester_passage'
T = 'tianxia.talent.jester.'


@hook('compile_block')
def compile_passage(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK}]
    return None


def dancing(engine, actor):
    return any(r.get('block') == BLOCK for r in
               engine.typed_passive_rows.get(actor.entity_id, []))


def size_allowed(engine, mover, occupant):
    from ..dynamic_size import CATEGORIES, current_category
    return CATEGORIES.index(current_category(engine, occupant)) <= CATEGORIES.index(current_category(engine, mover)) + 1


@hook('pass_through')
def passage(engine, mover, occupant):
    from ..relations import ALLY, ENEMY, relation
    side = relation(engine, mover, occupant)
    if getattr(engine, '_jester_passage_mover', None) == mover.entity_id:
        return 'difficult' if side == ENEMY and size_allowed(engine, mover, occupant) else None
    if not dancing(engine, mover) or not mover.turn_flags.get('disengaged'):
        return None
    if side == ALLY:
        return 'free'
    if side != ENEMY or not size_allowed(engine, mover, occupant):
        return None
    used = mover.turn_flags.get('jester_dancing_crossed')
    if not used or (used == occupant.entity_id and
                   set(engine._actor_volume(mover)) & set(engine._actor_volume(occupant))):
        return 'difficult'
    return None


@hook('pass_through_entered')
def crossed(engine, mover, occupant, intent):
    from ..relations import ENEMY, relation
    if (getattr(engine, '_jester_passage_mover', None) != mover.entity_id
            and dancing(engine, mover) and mover.turn_flags.get('disengaged')
            and relation(engine, mover, occupant) == ENEMY):
        mover.turn_flags['jester_dancing_crossed'] = occupant.entity_id
        engine._append_event('PASSIVE_TRIGGERED', T + 'dancing_fool', actor_id=mover.entity_id,
            target_ids=(occupant.entity_id,), payload={'log': f'{mover.display_name} uses Dancing Fool to cross {occupant.display_name} once this turn.'})


@effect('jester_passage_move')
def move(ctx, row):
    from .rider_step import step
    engine, mover = ctx.engine, ctx.actor
    token = row.get('distance_ft')
    feet = engine._effective_speed(mover)
    feet = feet // 2 if token == 'half_speed' else feet if token == 'speed' else int(token or 0)
    previous = getattr(engine, '_jester_passage_mover', None)
    engine._jester_passage_mover = mover.entity_id
    try:
        step(ctx, {'distance_ft': feet, 'no_oa': True, 'label': ctx.action.display_name})
    finally:
        engine._jester_passage_mover = previous


@hook('turn_end')
def dancing_ends(engine, ending):
    # Disengage obtained off-turn also ends with that turn, rather than the
    # next turn of its user. Clear only the passage owners' current grant.
    for actor in engine.state.actors.values():
        if dancing(engine, actor):
            actor.turn_flags.pop('disengaged', None)
            actor.turn_flags.pop('jester_dancing_crossed', None)
