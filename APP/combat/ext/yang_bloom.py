"""Unfinished Bloom's selected combat mode and area-owned Rising Mark.

Existing zone triggers own start-turn recipient limits, terrain, concentration
and replay. The area mark shares the owner's ordinary Rising Mark cap and expires
at the end of its next turn without ending the still-concentrated Bloom. Suitable
natural medium and spending marks on non-creature subjects remain explicit gaps.
Only freshly compiled ``yang_bloom`` rows opt into these rules.
"""
from __future__ import annotations

from . import effect, hook

BLOOM = 'TAL_YANG_UNFINISHED_BLOOM'
AREA_MARK = 'yang_bloom_mark'


@hook('compile_action')
def bloom_target(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if not any(e.get('type') == 'yang_bloom' for e in typed.get('effects') or []):
        return None
    return action.model_copy(update={'target_kind': 'CELL', 'radius_ft': 0,
        'parameters': {**action.parameters, 'any_cell': True}})


def area_marks(engine, owner):
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id
            and (z.trigger_profile.get('profile') or {}).get(AREA_MARK)]


def end_area_mark(engine, zone):
    from .retained_updates import record_zone_update
    zone.trigger_profile['profile'][AREA_MARK] = 0
    record_zone_update(engine, zone)


def enforce_limit(ctx):
    from ..typed_executor import mark_capacity, mark_condition_id
    owner, engine = ctx.actor, ctx.engine
    cap = mark_capacity(ctx, 'Kindled Mark')
    if not cap:
        return
    ids = {mark_condition_id(m, owner.entity_id) for m in ('Kindled Mark', 'Overkindled Mark')}
    marks = [(c.applied_sequence, 'creature', holder, c) for holder in engine.state.actors.values()
             for c in holder.conditions.values() if c.condition_id in ids]
    marks += [(int(z.trigger_profile['profile']['mark_sequence']), 'area', z, None)
              for z in area_marks(engine, owner)]
    for _, kind, holder, condition in sorted(marks, key=lambda r: r[0])[:max(0, len(marks) - cap)]:
        if kind == 'area':
            end_area_mark(engine, holder)
        else:
            holder.conditions.pop(condition.instance_id)
            engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
                actor_id=owner.entity_id, target_ids=(holder.entity_id,),
                payload={'condition_id': condition.condition_id, 'instance_id': condition.instance_id,
                         'reason': 'MARK_LIMIT'})


@effect('yang_bloom')
def bloom(ctx, row):
    from . import needle
    from .choice_costs import quote
    from .. import zones
    price = quote(ctx.action.costs)
    mode = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'unfinished_bloom', ctx.source),
        ctx.actor, 'choice:needle.unfinished_bloom', ['grasping', 'nourishing'], allow_decline=False,
        labels={'grasping': 'Grasping Bloom: enemies face Difficult Terrain and gain a mark at turn start '
                           'that one of your Overkindled Responses may spend to hinder or hurt them',
                'nourishing': f'Nourishing Bloom: allies gain {ctx.numbers["pb"]} Temporary HP at turn start'},
        name='Unfinished Bloom', feature_id=BLOOM,
        prompt='Unfinished Bloom: choose a mode for this 10-foot-radius area of soil, roots, seeds, moss, fertile mud '
               f'or living wood. The Action spends {price} from your cultivation resource pool '
               'and needs Concentration for up to 1 minute. '
               'Grasping hinders enemies and marks them for one of your Overkindled Responses; '
               'Nourishing protects allies at turn start.')
    if not mode:
        return
    grasping = mode[0] == 'grasping'
    payload = ({'type': 'mark', 'mark': 'Overkindled Mark', 'applies_to': 'target',
                'duration': {'kind': 'until_end_of_your_next_turn'}} if grasping else
               {'type': 'temp_hp', 'formula': 'pb', 'applies_to': 'target'})
    zone = zones.create(ctx, {'name': 'Unfinished Bloom: ' + ('Grasping' if grasping else 'Nourishing'),
        'shape': 'sphere', 'size_ft': 10, 'centered_on_self': False,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True},
        'difficult': 'hostile' if grasping else None, 'obscured': None,
        'triggers': [{'id': ctx.source + ':bloom', 'name': 'Unfinished Bloom', 'on': ['start'],
                      'who': 'hostile' if grasping else 'ally', 'effects': [payload]}],
        'profile': {AREA_MARK: 1, 'marker_turn': int(ctx.actor.turns_started),
                    'mark_sequence': int(ctx.engine.state.event_sequence + 1)}})
    if zone is not None:
        enforce_limit(ctx)


@hook('mark_applied')
def creature_shares_area_limit(ctx, name, subject):
    if name.lower() in ('kindled mark', 'overkindled mark') and area_marks(ctx.engine, ctx.actor):
        enforce_limit(ctx)


@hook('turn_end')
def area_mark_expiry(engine, actor):
    for zone in area_marks(engine, actor):
        if actor.turns_started > int(zone.trigger_profile['profile']['marker_turn']):
            end_area_mark(engine, zone)
