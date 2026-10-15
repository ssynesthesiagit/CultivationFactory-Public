"""Assigned Spirit consumers of the public native effect continuation seam.

Transport actual short-lived posture, pressure, passage and wing conditions;
never cast a feature, grant ownership or repeat an application trigger. Scene
records remain with spiritual_state. Ascending Beat must finish its native turn
so the existing safe-descent/falling procedure resolves before ordinary travel.
"""
import json
from fractions import Fraction

from . import hook
from .spiritual_state import journey_scene_id

KEY = 'spirit.effect_continuation'
SOURCES = {
    'tianxia.tradition.spirit.ancestral_channeler.feature.possession_by_the_past',
    'tianxia.tradition.spirit.boundary_walker.feature.deny_passage',
    'tianxia.tradition.spirit.soulstring_dancer.feature.threaded_step',
    'tianxia.tradition.spirit.equal_measure_scripture.feature.threefold_recompense',
    'tianxia.tradition.spirit.seraphic_molter.feature.wingless_ascent',
}


def exported(engine, actor):
    from .effect_durations import remaining_seconds
    for kind, instances in [('condition', actor.conditions.values()), ('modifier', actor.modifiers.values())]:
        for instance in instances:
            if instance.source_definition_id not in SOURCES:
                continue
            # The native end-of-turn removes flight and resolves safe descent.
            if kind == 'condition' and instance.condition_id == 'condition:typed.ascending_beat':
                continue
            remaining = remaining_seconds(engine, instance.expires_on, source_actor_id=instance.source_actor_id,
                                          holder_actor_id=actor.entity_id)
            if remaining is not None:
                yield kind, instance, remaining


def left(session, row):
    owner = row['source_actor']
    if row['scene'] and owner in session.state['actors'] and row['scene'] != journey_scene_id(session, owner):
        return Fraction(0)
    return max(Fraction(0), Fraction(*row['deadline']) - session.clock())


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    rows = list(exported(engine, actor))
    if not rows:
        return None
    result = actor.model_copy(deep=True)
    for kind, instance, _remaining in rows:
        (result.conditions if kind == 'condition' else result.modifiers).pop(
            instance.instance_id if kind == 'condition' else instance.modifier_id)
    return result


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature):
    rows = []
    for kind, instance, remaining in exported(engine, creature):
        deadline = session.clock() + remaining
        rows.append({'kind':kind, 'instance':instance.model_dump_json(),
                     'deadline':[deadline.numerator, deadline.denominator],
                     'source_actor':instance.source_actor_id or '',
                     'scene':str((getattr(instance, 'data', None) or {}).get('source_scene_id') or '')})
    saved = session.state['actors'][aid].setdefault('source_states', {})
    if rows:
        saved[KEY] = rows
    else:
        saved.pop(KEY, None)


@hook('journey_combat_setup')
def setup(session, aid):
    rows = session.state['actors'][aid].get('source_states', {}).get(KEY, [])
    if not rows:
        return None
    return {'spirit_effect_continuation':[{**row, 'remaining':[left(session,row).numerator, left(session,row).denominator]}
                                         for row in rows if left(session,row) > 0]}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from ..effect_continuation import restore_condition, restore_modifier
    from .effect_durations import expiry_after_seconds
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for row in (bundle.get('journey_setup') or {}).get('spirit_effect_continuation', []):
            function = restore_condition if row['kind'] == 'condition' else restore_modifier
            function(engine, actor, json.loads(row['instance']),
                     expires_on=expiry_after_seconds(engine, Fraction(*row['remaining'])))


@hook('journey_elapsed')
def elapsed(session, aid, previous, seconds, moving):
    saved = session.state['actors'][aid].get('source_states', {})
    rows = saved.get(KEY)
    if rows is None:
        return
    live = [row for row in rows if left(session,row) > 0]
    for row in rows:
        if row not in live:
            instance = json.loads(row['instance'])
            session.emit('SPIRIT_EFFECT_EXPIRED', aid,
                         instance_id=instance.get('instance_id', instance.get('modifier_id', '')),
                         text='A continued spiritual effect reaches its original deadline.')
    if live:
        saved[KEY] = live
    else:
        saved.pop(KEY, None)
