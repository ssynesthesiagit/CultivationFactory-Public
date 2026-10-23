"""Follow the Soot's source-owned tracking result and Soot-Scent escape.

Uses existing effect/turn_end/status_description hooks. The input Smoke Trace
is spent by the existing action; this separate result alone receives the longer
lifetime and the creature-owned escape choice. No passive/global tracking.

The bearing is read from combat/ext/tracking_direction.py, shared with Smoke
Mirror Trail (combat/ext/smoke_sound_residual.py), so both tracking lines give
the same answer for the same positions.
"""
from . import effect, hook
from .condition_ownership import refresh_owned
from .tracking_direction import TRACKING_REACH_FT, compass
from ..typed_executor import bears_mark

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
    if row.get('extended'):
        # ironclad_smoke owns the extended result and its end-turn escape.
        # Keep one result and one prompt rather than two independent trails.
        from .ironclad_smoke import soot_scent_trace
        soot_scent_trace(ctx, row)
        return
    refresh_owned(ctx.engine, ctx.target, TRACK, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(ctx.target, TRACK, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'label': 'Follow the Soot: direction known within 120 feet until the caster’s next turn starts'})


@hook('status_description')
def direction(engine, holder, row, data):
    from .ironclad_smoke import TRACE_CONDITION

    if row.get('condition_id') == TRACK:
        owner = engine.state.actors.get(row.get('source_actor_id'))
        target = holder
    elif row.get('condition_id') == TRACE_CONDITION:
        owner = holder
        target = engine.state.actors.get(data.get('target_id'))
    else:
        return None
    if owner is None or target is None or engine._distance_actor_to_actor(owner, target) > TRACKING_REACH_FT:
        return {'handling': f'Outside the {TRACKING_REACH_FT}-foot tracking range; no direction is supplied.'}
    return {'handling': 'Follow the Soot tells its caster the direction: ' + compass(owner, target) + '.'}
