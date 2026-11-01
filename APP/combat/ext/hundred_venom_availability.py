"""Hundred-Venom scaling and dormant effects, on the shared Body availability API.

Shared helpers for hundred_venom and hundred_venom_journey: feature_levels reads
compiled ownership, effective_body_pb uses the seam's live CL, and
retained_effect_batch restores linked Venom components atomically. No scene or
suppression is declared, copied, persisted or expired here: all gates read
body_modes_scene_resources.available/effective_body_cl.
"""
from contextlib import contextmanager

from . import hook, query
from .body_modes_scene_resources import available, bundle_of, effective_body_cl, owned_sources
from .hundred_venom_acquisition import FEATURES, LEVELS

DORMANCY = 'tianxia.subpath.body.hundred_venom_body'


def feature_levels(bundle):
    owned = owned_sources(bundle)
    return {f: n for f, n in zip(FEATURES, LEVELS) if f in owned}


def effective_body_pb(engine, actor):
    base = int(actor.proficiency_bonus or 2)
    bundle = bundle_of(engine, actor)
    attained = int(bundle.get('hundred_venom_body_attainment', bundle.get('cl') or 1))
    effective = effective_body_cl(engine, actor)
    return min(base, 2 + (max(1, effective) - 1) // 4) if effective < attained else base


@hook('path_rider_rows')
def gate_path_riders(engine, actor, kind, rows):
    levels = feature_levels(bundle_of(engine, actor))
    if levels:
        return [r for r in rows if r.get('feature_id') not in levels
                or available(engine, actor, r['feature_id'], levels[r['feature_id']])]


@hook('reaction_rows')
def gate_reactions(engine, actor_id, block, rows):
    actor = engine.state.actors.get(actor_id)
    if actor is None:
        return
    levels = feature_levels(bundle_of(engine, actor))
    if not levels:
        return
    result = []
    for row in rows:
        source = row.get('feature_id')
        if source not in levels:
            result.append(row)
            continue
        policies = query('cultivation_row_available', engine, actor, block, row)
        if False not in policies and (True in policies or available(engine, actor, source, levels[source])):
            result.append(row)
    return result


@hook('damage_type_grant_available')
def granted_type_available(ctx, source):
    levels = feature_levels(bundle_of(ctx.engine, ctx.actor))
    if source in levels:
        return available(ctx.engine, ctx.actor, source, levels[source])


@hook('resolution_numbers')
def venom_resolution_numbers(ctx, numbers):
    from .ability_source import mechanic_of
    if ctx.typed.get('source_cl_locked') == 1:
        return
    if mechanic_of(ctx.action) not in feature_levels(bundle_of(ctx.engine, ctx.actor)):
        return
    level = effective_body_cl(ctx.engine, ctx.actor)
    pb = effective_body_pb(ctx.engine, ctx.actor)
    compiled_pb = int(numbers.get('pb') or ctx.actor.proficiency_bonus or 2)
    if level == int(numbers.get('cl') or level) and pb == compiled_pb:
        return
    result = {**numbers, 'cl': level, 'pb': pb}
    for key in ('save_dc', 'attack_bonus'):
        if key in result:
            result[key] = int(result[key]) - compiled_pb + pb
    return result


@hook('state_event', priority=150)
def reconcile_dormant_effects(engine, event):
    """Keep actual Venom models and clocks while their owning feature is dormant."""
    if getattr(engine, '_venom_retained_batch', 0):
        return
    if event.event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED', 'CONDITION_UPDATED',
                                'MODIFIER_APPLIED', 'MODIFIER_REMOVED', 'TURN_STARTED', 'ROUND_STARTED'):
        return
    from .benefit_suppression import SUPPRESSED, restore_document, suppress
    from .suppressed_effects import alive, saved_lifetime
    from .ability_source import mechanic_at
    for holder in list(engine.state.actors.values()):
        for marker in list(holder.conditions.values()):
            binding = marker.data.get('resume_when') if marker.condition_id == SUPPRESSED else None
            if marker.source_definition_id != DORMANCY or marker.data.get('until') != 'source_available' or not binding:
                continue
            owner = engine.state.actors.get(binding['owner'])
            if owner is None:
                continue
            if not alive(engine, marker.data['lifetime']):
                engine._remove_condition_instance(holder, marker.instance_id, DORMANCY, expected=marker)
            elif available(engine, owner, binding['feature'], binding['level'], requires_conscious=False):
                clock = saved_lifetime(holder, marker)
                if engine._remove_condition_instance(holder, marker.instance_id, DORMANCY, expected=marker):
                    restore_document(engine, holder, marker.data, clock, DORMANCY)
        for kind, collection in (('condition', holder.conditions), ('modifier', holder.modifiers)):
            for item in list(collection.values()):
                owner = engine.state.actors.get(item.source_actor_id)
                if owner is None:
                    continue
                source = mechanic_at(engine, item.source_definition_id) or item.source_definition_id
                levels = feature_levels(bundle_of(engine, owner))
                if source not in levels or (kind == 'condition' and item.condition_id in (
                        'condition:typed.swallowed_poison', 'condition:typed.swallowed_poison_continuation')):
                    continue
                bindings = [b for b in query('cultivation_effect_binding', engine, holder, item) if b is not None]
                if len(bindings) > 1:
                    raise ValueError('An effect has conflicting cultivation source bindings.')
                if bindings:
                    source = bindings[0]['feature']
                if source not in levels:
                    continue
                if not available(engine, owner, source, levels[source], requires_conscious=False):
                    key = item.instance_id if kind == 'condition' else item.modifier_id
                    suppress(engine, owner, holder, kind + ':' + key, 'source_available', DORMANCY,
                             label='Dormant Hundred-Venom effect',
                             resume_when={'owner': owner.entity_id, 'feature': source, 'level': levels[source]})


@contextmanager
def retained_effect_batch(engine):
    """Defer only family dormancy while its linked native components are restored."""
    old = getattr(engine, '_venom_retained_batch', 0)
    engine._venom_retained_batch = old + 1
    try:
        yield
    finally:
        engine._venom_retained_batch = old
        if not old and engine.events:
            reconcile_dormant_effects(engine, engine.events[-1])


@hook('state_event')
def consume_dormant_next_roll(engine, event):
    if event.event_type not in ('ATTACK_ROLLED', 'SAVE_ROLLED'):
        return
    from .benefit_suppression import SUPPRESSED, cancel
    holder = engine.state.actors.get(event.actor_id)
    if holder is None:
        return
    ability = str(event.payload.get('ability') or event.payload.get('reason', '').rsplit(':', 1)[-1]).upper()
    for marker in list(holder.conditions.values()):
        data = marker.data
        if marker.condition_id != SUPPRESSED or marker.source_definition_id != DORMANCY or data.get('until') != 'source_available':
            continue
        model = data.get('model') or {}
        consume = (event.event_type == 'ATTACK_ROLLED' and data.get('kind') == 'modifier'
                   and model.get('target_field') == 'attack_mode' and model.get('applies_to') == 'NEXT_ATTACK')
        rule = (model.get('data', {}).get('rule') or {}).get('save_against') or {}
        if (event.event_type == 'SAVE_ROLLED' and data.get('kind') == 'condition'
                and rule.get('next') and not rule.get('against') and ability in rule.get('abilities', ())):
            consume = True
        if consume:
            cancel(engine, holder, 'condition:' + marker.instance_id, DORMANCY)
