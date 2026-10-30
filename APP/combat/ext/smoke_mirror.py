"""Smoke Mirror event traces and Soot's personal concealment exception.

Source-owned traces reuse the native mark implementation and cap. Optional
placements use no ordinary once-per-round placement allowance. Direction is
bound to the exact trace instance; replacement/spending ends that knowledge.
"""
from . import hook
from .smoke_riders import inside, VEIL, DOMAIN
from .fight_ownership import owns_feature
from .observer_information import bearing
from .needle import ask, checkpoint_id

MIRROR = 'TAL_SMOKE_SMOKE_MIRROR_TRAIL'
WITNESS = 'condition:typed.smoke_witness_reveal'
MIRROR_TRACE = 'condition:typed.smoke_mirror_trace'
ALLOWED = {'smoke', 'fog', 'mist', 'steam', 'nonmagical_darkness'}


@hook('compile_passives')
def ownership(passives, info):
    if MIRROR in info['owned_ids']:
        return [*passives, {'feature_id': MIRROR, 'block': 'smoke_mirror', 'kind': 'mirror'}]


@hook('hide_support_causes')
def smoke_support(engine, actor, inside_name):
    from .. import zones
    from ..spatial_areas import zone_contains
    result = []
    for zone in zones.typed_zones(engine):
        if zone_contains(engine, actor, zone) and any(s in zone.source_definition_id for s in (VEIL, DOMAIN)):
            result.append('smoke')
    return result or None


def witness_knows(engine, viewer, target):
    from ..senses import physical_sight
    if engine._distance_actor_to_actor(viewer, target) > 120 or not physical_sight(engine, viewer, target):
        return False
    if not any(c.condition_id == WITNESS and c.source_actor_id == viewer.entity_id for c in target.conditions.values()):
        return False
    hidden = [c for c in target.conditions.values() if c.condition_id == 'condition:typed.hidden']
    def supported(condition):
        causes = (condition.data.get('support_by_observer') or {}).get(viewer.entity_id, condition.data.get('support_causes'))
        return bool(causes) and set(causes) <= ALLOWED
    return bool(hidden) and all(supported(c) for c in hidden) and not any(
            c.condition_id == 'condition:typed.invisible' for c in target.conditions.values())


@hook('target_sight_bypass')
def witness_traced_target(engine, viewer, target, action):
    """The printed recipient is a bearer of your Trace, even while concealed.

    This grants only the Soot response's target permission; physical barriers,
    range, attack sight and every other ability retain their ordinary checks.
    """
    if action is None or (action.parameters.get('typed') or {}).get('source') != 'TAL_SMOKE_SOOT_MARKED_WITNESS':
        return None
    from ..typed_executor import bears_mark
    from ..senses import physical_sight
    from ..targeting import line_of_effect
    return bool(bears_mark(target, viewer.entity_id, 'Smoke Trace')
        and engine._distance_actor_to_actor(viewer, target) <= 120
        and physical_sight(engine, viewer, target) and line_of_effect(engine, viewer, target=target))


@hook('pinpoint_target')
def witness_location(engine, viewer, target):
    if witness_knows(engine, viewer, target):
        return True


@hook('masked_conditions')
def witness_hidden(engine, attacker, target):
    result = {}
    for viewer, seen in ((attacker, target), (target, attacker)):
        if witness_knows(engine, viewer, seen):
            result[seen.entity_id] = {iid for iid, c in seen.conditions.items() if c.condition_id == 'condition:typed.hidden'}
    return result or None


@hook('choice_reactors')
def mirror_choosers(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if owns_feature(engine, a, MIRROR))


@hook('resolution_final')
def mirror_events(engine, actor, action, candidate, intent):
    from ..gate2_runtime_models import Position
    from ..typed_executor import Context, block_mark, mark_condition_id
    from ..senses import physical_sight, perceives
    start = max((e.sequence for e in engine.events if e.event_type == 'INTENT_ACCEPTED'
                 and e.trigger_or_intent_id == intent.intent_id), default=engine.state.event_sequence)
    events = [e for e in engine.events if e.sequence > start]
    for owner in engine.state.actors.values():
        if not owner.active or not owns_feature(engine, owner, MIRROR):
            continue
        for event in events:
            target = None
            trigger = ''
            if event.event_type == 'CONDITION_APPLIED' and event.payload.get('condition_id') in ('condition:typed.hidden', 'condition:typed.invisible'):
                target = engine.state.actors.get((event.target_ids or ('',))[0])
                if target and owner.entity_id in event.payload.get('smoke_mirror_owners', []):
                    trigger = 'successfully Hides' if event.payload['condition_id'].endswith('hidden') else 'becomes Invisible'
            elif event.event_type == 'MOVEMENT_COMMITTED' and (event.payload.get('teleport') or event.payload.get('forced')):
                target = engine.state.actors.get(event.actor_id)
                path = event.payload.get('path') or []
                if target and path:
                    previous = target.model_copy(update={'position': Position.model_validate(path[0])})
                    if owner.entity_id in event.payload.get('smoke_mirror_owners', []):
                        trigger = 'teleports' if event.payload.get('teleport') else 'leaves the veil without normal movement'
            if not trigger or target is None:
                continue
            before_target = target
            if event.event_type == 'CONDITION_APPLIED':
                before_target = target.model_copy(update={'conditions': {iid: c for iid, c in target.conditions.items()
                    if iid != event.payload.get('instance_id')}})
            elif event.event_type == 'MOVEMENT_COMMITTED':
                before_target = previous
            automatic = owner.entity_id in event.payload.get('smoke_mirror_observed', [])
            pick = ask(engine, intent, checkpoint_id(engine, 'smoke_mirror', owner.entity_id, str(event.sequence)),
                owner, 'choice:needle.smoke_mirror', ['trace'], name='Smoke Mirror Trail', allow_decline=True,
                target_id=target.entity_id, automatic=automatic, default='decline',
                labels={'trace': 'Place a Smoke Trace without using your ordinary once-per-round placement'},
                prompt=f'Smoke Mirror Trail: {target.display_name} {trigger} in your Smoke Veil during {action.display_name}. Place your free Smoke Trace? It lets you know its direction within 120 feet until that trace ends.')
            if not pick:
                continue
            owned_action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id), None)
            if owned_action is None:
                continue
            from .needle import numbers_of
            ctx = Context(engine, owner, owned_action, intent, {'source': MIRROR, 'numbers': numbers_of(engine, owner),
                'duration': {'kind': 'instant'}}, [target], target).with_source('passive:' + MIRROR)
            block_mark(ctx, {'type': 'mark', 'mark': 'Smoke Trace', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}})
            mark = next((c for c in target.conditions.values() if c.condition_id == mark_condition_id('Smoke Trace', owner.entity_id)), None)
            if mark:
                engine._apply_condition(target, MIRROR_TRACE, ctx.source, owner.entity_id, expires_on=mark.expires_on or 'UNTIL_REMOVED',
                    data={'trace_instance': mark.instance_id, 'label': 'Smoke Mirror Trail: its owner knows the direction within 120 feet until this Smoke Trace ends'})


@hook('observer_information')
def trace_directions(engine, viewer):
    result = []
    for target in engine.state.actors.values():
        if engine._distance_actor_to_actor(viewer, target) > 120:
            continue
        if any(c.condition_id == MIRROR_TRACE and c.source_actor_id == viewer.entity_id
               and c.data.get('trace_instance') in target.conditions for c in target.conditions.values()):
            result.append({'ability': 'Smoke Mirror Trail', 'direction': bearing(viewer, target.position),
                           'text': 'Smoke Mirror Trail: the traced creature is to the ' + bearing(viewer, target.position) + '.'})
    return result


@hook('event_observation')
def mirror_receipt(engine, event):
    """Capture trigger membership and actual observers before later effects move it."""
    from ..gate2_runtime_models import Position
    from ..senses import perceives, physical_sight
    target = None
    previous = None
    if event.event_type == 'CONDITION_APPLIED' and event.payload.get('condition_id') in ('condition:typed.hidden', 'condition:typed.invisible'):
        target = engine.state.actors.get((event.target_ids or ('',))[0])
        if target is not None:
            previous = target.model_copy(update={'conditions': {iid: c for iid, c in target.conditions.items()
                if iid != event.payload.get('instance_id')}})
    elif event.event_type == 'MOVEMENT_COMMITTED' and (event.payload.get('forced') or event.payload.get('teleport')):
        target = engine.state.actors.get(event.actor_id)
        path = event.payload.get('path') or []
        if target is not None and path:
            previous = target.model_copy(update={'position': Position.model_validate(path[0])})
    if target is None or previous is None:
        return None
    owners = [a for a in engine.state.actors.values() if owns_feature(engine, a, MIRROR)]
    if not owners:
        return None
    eligible, observed = [], []
    for owner in owners:
        before = previous
        if event.event_type == 'MOVEMENT_COMMITTED' and not event.payload.get('teleport'):
            for start, end in zip(path, path[1:]):
                old = target.model_copy(update={'position': Position.model_validate(start)})
                new = target.model_copy(update={'position': Position.model_validate(end)})
                if inside(engine, old, owner.entity_id) and not inside(engine, new, owner.entity_id):
                    before = old
                    break
            else:
                continue
        if not owner.active or not inside(engine, before, owner.entity_id) or not physical_sight(engine, owner, before):
            continue
        if event.event_type == 'MOVEMENT_COMMITTED' and not event.payload.get('teleport') and inside(engine, target, owner.entity_id):
            continue
        eligible.append(owner.entity_id)
        if owner is target or perceives(engine, owner, before) or perceives(engine, owner, target):
            observed.append(owner.entity_id)
    return {'smoke_mirror_owners': eligible, 'smoke_mirror_observed': observed}


@hook('event')
def ended_trace(engine, event_type, kwargs):
    if event_type != 'CONDITION_REMOVED':
        return
    removed = (kwargs.get('payload') or {}).get('instance_id')
    if not removed:
        return
    from .riders_shared import remove_benefit_condition
    for target in engine.state.actors.values():
        for condition in list(target.conditions.values()):
            if condition.condition_id == MIRROR_TRACE and condition.data.get('trace_instance') == removed:
                remove_benefit_condition(engine, target, condition, 'TRACE_ENDED')
