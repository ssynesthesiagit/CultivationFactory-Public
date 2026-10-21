"""Follow the Soot's source-owned tracking result and Soot-Scent escape.

Uses existing effect/turn_end/status_description hooks. The input Smoke Trace
is spent by the existing action; this separate result alone receives the longer
lifetime and the creature-owned escape choice. No passive/global tracking.
"""
from . import effect, hook
from .condition_ownership import refresh_owned, remove_instance
from .needle import CHOICE, ask, checkpoint_id, numbers_of
from ..typed_executor import bears_mark, resolve_opposed_check

TRACK = 'condition:typed.smoke_follow_soot'


@hook('candidate_allowed')
def traced_response(engine, actor, candidate, action):
    if not action or not action.source_definition_id.endswith('.smoke.follow_soot'):
        return None
    target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
    return bool(target and bears_mark(target, actor.entity_id, 'Smoke Trace'))


@effect('smoke_follow_soot')
def follow(ctx, row):
    if ctx.target is None:
        return
    refresh_owned(ctx.engine, ctx.target, TRACK, ctx.actor.entity_id, ctx.source)
    extended = int(row.get('extended', 0))
    ctx.engine._apply_condition(ctx.target, TRACK, ctx.source, ctx.actor.entity_id,
        expires_on=(f'START_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started + 10}' if extended
                    else 'START_OF_SOURCE_NEXT_TURN'),
        data={'extended': extended, 'save_dc': int(ctx.numbers['save_dc']),
              'label': 'Soot-Scent Trail: direction known within 120 feet for 1 minute; optional Stealth escape each turn end'
                       if extended else 'Follow the Soot: direction known within 120 feet until the caster’s next turn starts'})


@hook('turn_end')
def escape(engine, actor):
    from .placed import context
    for held in list(actor.conditions.values()):
        if held.condition_id != TRACK or not held.data.get('extended'):
            continue
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is None:
            continue
        # Declining emits no event: each held trace needs its own checkpoint even
        # when the same target answers several casters during one end-turn intent.
        checkpoint = checkpoint_id(engine, 'soot_scent_escape', actor.entity_id,
                                   held.source_actor_id, held.instance_id)
        chosen = ask(engine, None, checkpoint, actor, CHOICE + 'soot_scent_escape', ['stealth'],
            name='Soot-Scent Trail', target_id=actor.entity_id, allow_decline=True,
            labels={'stealth': 'Attempt Dexterity (Stealth) against the caster’s Smoke Save DC; success ends this tracking result'},
            prompt=f'Soot-Scent Trail: {actor.display_name} ends its turn while tracked by {owner.display_name}’s Follow the Soot. Try a Dexterity (Stealth) check to end that tracking? No action or points are spent.')
        if not chosen:
            continue
        ctx = context(engine, actor, held.source_definition_id, numbers_of(engine, actor), [owner])
        result = resolve_opposed_check(ctx, owner, {'kind': 'check', 'ability': 'dex', 'skill': 'stealth', 'label': 'Soot-Scent Trail escape'},
                                      {'kind': 'dc', 'dc': int(held.data['save_dc']), 'label': 'Smoke Save DC'})
        if result.success:
            remove_instance(engine, actor, held.instance_id, held.source_definition_id)


@hook('status_description')
def direction(engine, holder, row, data):
    if row.get('condition_id') != TRACK:
        return None
    owner = engine.state.actors.get(row.get('source_actor_id'))
    if owner is None or engine._distance_actor_to_actor(owner, holder) > 120:
        return {'handling': 'Outside the 120-foot tracking range; no direction is supplied.'}
    dx, dy = holder.position.x - owner.position.x, holder.position.y - owner.position.y
    ns = 'north' if dy < 0 else 'south' if dy > 0 else ''
    ew = 'west' if dx < 0 else 'east' if dx > 0 else ''
    return {'handling': 'Follow the Soot tells its caster the direction: ' + ('-'.join(x for x in (ns, ew) if x) or 'here') + '.'}
