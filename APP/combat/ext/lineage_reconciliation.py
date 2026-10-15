"""Native Ancestral Ascension price and its source-specific reconciliation.

This producer supplies Possession by the Past's real Soul Anchor strain. An
accepted presence is an identity record, separate from its suppressible numeric
benefits. A table-owned scene boundary requests the printed withdrawal save;
the acquired actor resolves it through the native non-action procedure/replay path.
Only this cause of strain ends after the printed one-hour lineage rite.
"""
import json

from . import hook
from .ancestral_channeler import ASCENSION, ASCENDED, AUTHORITY_USED, CHANNELER_SOURCE

PRESENCE = 'condition:spirit.ancestral_presence'
STRAIN = 'condition:spirit.ancestral_reconciliation_strain'
ENDING = 'ancestral_withdrawal'
REQUEST = 'ancestral_scene_closing'
REVIEW_SOURCE = 'system:spirit.ancestral_withdrawal'
REVIEW_KIND = 'lineage_taboo_review'
EXCEPTIONS = ('none', 'complete_soul_destruction', 'lineage_anchor_severance', 'protected_successor_death', 'higher_ranked_duty')


def presence(actor):
    """The actual accepted ancestor, without granting its active benefits."""
    return next((c for c in actor.conditions.values() if c.condition_id == PRESENCE
                 and c.source_actor_id == actor.entity_id), None)


def strained(actor):
    """A native failed withdrawal; unrelated causes are deliberately separate."""
    return any(c.condition_id == STRAIN and c.source_definition_id == ASCENSION
               and c.source_actor_id == actor.entity_id for c in actor.conditions.values())


def saved_conditions(actor, kind):
    return [(key, json.loads(raw)) for key, raw in actor.get('encounter_snapshot', {}).get('conditions', {}).items()
            if json.loads(raw)['condition_id'] == kind and json.loads(raw)['source_definition_id'] == ASCENSION]


def begin_presence(ctx, office):
    from ..journey import require
    from .spiritual_state import scene_id
    require(presence(ctx.actor) is None, 'Resolve the previous Ancestral Ascension withdrawal before receiving another ancestor.')
    from .spiritual_state import read
    record = read(ctx.actor)
    scene = scene_id(ctx.engine, ctx.actor)
    higher_duty = (record.get('covenant', {}).get('higher_ranked_duty', '')
                   if record.get('covenant_scene') and record['covenant_scene'] != scene else '')
    ctx.engine._apply_condition(ctx.actor, PRESENCE, ASCENSION, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'office': office, 'scene_id': scene_id(ctx.engine, ctx.actor),
            'higher_ranked_duty': higher_duty,
            'label': 'Accepted ancestor: Ancestral Ascension; withdrawal is resolved when this scene ends.'})


@hook('presentation_hidden_conditions')
def private_presence(engine, actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == PRESENCE]


@hook('fact_admission_schema')
def review_schema(session, source, subject, kind):
    if source == REVIEW_SOURCE and kind == REVIEW_KIND:
        return {'value_type': 'document', 'authority': 'table_owner', 'combat': True,
            'validate_value': True, 'maximum_seconds': 86400,
            'description': 'Review actual acts during this accepted ancestor’s activation against the recorded Lineage Taboo and its printed exceptions.'}


@hook('fact_admission_value')
def validate_review(session, payload):
    if payload.get('source') != REVIEW_SOURCE or payload.get('kind') != REVIEW_KIND:
        return None
    from ..journey import require
    value = payload['value']
    if getattr(session, 'is_combat_fact_context', False):
        held = presence(session.engine.state.actors[payload['subject']])
        instance_id, data = (held.instance_id, held.data) if held else ('', {})
    else:
        rows = saved_conditions(session.state['actors'][payload['subject']], PRESENCE)
        instance_id, data = (rows[0][0], rows[0][1]['data']) if rows else ('', {})
    require(instance_id and payload['scope'] == instance_id,
        'Review the actual committed Ancestral Ascension presence, never a fabricated activation or another owner.')
    require(isinstance(value, dict) and set(value) == {'violated', 'sole_available_way', 'exception', 'acts', 'ruling'}
        and all(type(value[k]) is int and value[k] in (0, 1) for k in ('violated', 'sole_available_way'))
        and value['exception'] in EXCEPTIONS and all(type(value[k]) is str and value[k].strip() for k in ('acts', 'ruling')),
        'Record the actual acts, ruling, Taboo violation, sole-available-way finding and printed greater violation.')
    require(value['exception'] != 'higher_ranked_duty' or bool(data.get('higher_ranked_duty')),
        'This exception requires a higher-ranked Duty recorded before the scene began.')
    require(value['violated'] == 1 or (value['exception'] == 'none' and value['sole_available_way'] == 0),
        'A clean withdrawal does not declare a Taboo exception.')
    return True


def review(actor, instance_id):
    from ..fact_consent_admission import CONDITION
    for condition in sorted(actor.conditions.values(), key=lambda c: c.applied_sequence, reverse=True):
        if condition.condition_id == CONDITION:
            receipt = json.loads(condition.data['record'])
            if (receipt['source'], receipt['kind'], receipt['scope']) == (REVIEW_SOURCE, REVIEW_KIND, instance_id):
                return receipt['value']


@hook('journey_scene_closing')
def closing(session, scene, reason):
    waiting = [aid for aid, actor in session.state['actors'].items() if saved_conditions(actor, PRESENCE)]
    if not waiting:
        session.state.pop(REQUEST, None)
        return None
    session.state[REQUEST] = {'scene_id': scene, 'reason': reason}
    session.emit('ANCESTRAL_WITHDRAWAL_REQUIRED', waiting[0], actors=waiting,
        text='Before the scene ends, each accepted ancestor must withdraw through Ancestral Ascension’s Wisdom save.')
    return False


@hook('journey_encounter_prepare')
def prepare(session, aid):
    request = session.state.get(REQUEST)
    session.state['actors'][aid]['bundle'][REQUEST] = request or {}


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    held = scene_instances(actor)
    if not held:
        return None
    result = actor.model_copy(deep=True)
    for kind, instance in held:
        (result.conditions if kind == 'condition' else result.modifiers).pop(
            instance.instance_id if kind == 'condition' else instance.modifier_id)
    return result


def scene_instances(actor):
    """Actual active scene benefits; accepted identity and strain stay separate."""
    return [('modifier', m) for m in actor.modifiers.values() if m.source_definition_id == ASCENSION
            and m.source_actor_id == actor.entity_id and m.expires_on == 'UNTIL_REMOVED'] + [
        ('condition', c) for c in actor.conditions.values() if c.condition_id in (ASCENDED, AUTHORITY_USED)
        and c.source_actor_id == actor.entity_id and c.source_definition_id == ASCENSION]


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature):
    from .spirit_traditions import row
    saved = session.state['actors'][aid].setdefault('source_states', {})
    if presence(creature) is None:
        saved.pop('ancestral_scene_effects', None)
    elif row(engine, creature, 'ancestral_ascension') is not None:
        saved['ancestral_scene_effects'] = [{'kind': kind, 'instance': instance.model_dump_json()}
            for kind, instance in scene_instances(creature)]
    # A suppressed source keeps the exact dormant record. It grants no active
    # benefit and is not erased merely by entering another native context.


@hook('journey_combat_setup')
def setup(session, aid):
    rows = session.state['actors'][aid].get('source_states', {}).get('ancestral_scene_effects', [])
    if rows:
        return {'ancestral_scene_effects': rows}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from ..effect_continuation import restore_condition, restore_modifier
    from .spirit_traditions import row
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is not None and presence(actor) is not None and row(engine, actor, 'ancestral_ascension') is not None:
            for saved in bundle.get('journey_setup', {}).get('ancestral_scene_effects', []):
                function = restore_condition if saved['kind'] == 'condition' else restore_modifier
                function(engine, actor, json.loads(saved['instance']), expires_on='UNTIL_REMOVED')


@hook('journey_native_procedure')
def procedure(engine, actor, source, name, intent):
    if (source, name) != (ASCENSION, ENDING):
        return None
    from types import SimpleNamespace
    from .spirit_traditions import numbers
    bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id)
    withdraw(SimpleNamespace(engine=engine, actor=actor,
        numbers=bundle.get('spiritual_path_numbers') or numbers(engine, actor)))
    return True


def withdraw_for_replacement(ctx):
    """An actual paid Ascension can replace a presence, resolving its old price.

    Public caller: ancestral_channeler.ascend. No declaration or menu flag can
    invoke this path, and ordinary recasts/Office Authority remain reachable.
    """
    if presence(ctx.actor) is None:
        return
    from ..journey import require
    from .spirit_traditions import feature_of
    require(ctx.intent.actor_id == ctx.actor.entity_id and feature_of(ctx.action) == ASCENSION
        and any(row.get('type') == 'ancestral_ascend' for row in (ctx.action.parameters.get('typed') or {}).get('effects', [])),
        'Only a real Ancestral Ascension activation can replace the accepted ancestor.')
    withdraw(ctx, replacement=True)


def withdraw(ctx, *, replacement=False):
    from ..journey import require
    from .forged_exhaustion import level, set_level
    held = presence(ctx.actor)
    bundle = next(b for b in ctx.engine.typed_bundle_documents if b['actor_id'] == ctx.actor.entity_id)
    require(held is not None and (replacement or bundle.get(REQUEST, {}).get('scene_id') == held.data.get('scene_id')),
        'Only the actual table-requested Ancestral Ascension withdrawal can resolve.')
    # A taboo exception is an external historical fact, never inferred from
    # team membership, damage, a favorable die, or the actor's convenience.
    finding = review(ctx.actor, held.instance_id)
    require(finding is not None, 'The table owner must review the actual Ascension’s recorded Lineage Taboo and printed exceptions before withdrawal.')
    for condition in list(ctx.actor.conditions.values()):
        if condition.condition_id in (ASCENDED, AUTHORITY_USED, PRESENCE) and condition.source_actor_id == ctx.actor.entity_id:
            del ctx.actor.conditions[condition.instance_id]
            ctx.engine._append_event('CONDITION_REMOVED', ASCENSION, actor_id=ctx.actor.entity_id,
                target_ids=(ctx.actor.entity_id,), payload={'condition_id': condition.condition_id,
                    'instance_id': condition.instance_id, 'reason': 'ANCESTRAL_WITHDRAWAL'})
    for key, modifier in list(ctx.actor.modifiers.items()):
        if modifier.source_definition_id == ASCENSION and modifier.source_actor_id == ctx.actor.entity_id and modifier.expires_on == 'UNTIL_REMOVED':
            del ctx.actor.modifiers[key]
            ctx.engine._append_event('MODIFIER_REMOVED', ASCENSION, actor_id=ctx.actor.entity_id,
                target_ids=(ctx.actor.entity_id,), payload={'modifier_id': key, 'reason': 'ANCESTRAL_WITHDRAWAL'})
    from .benefit_suppression import SUPPRESSED, cancel
    for condition in list(ctx.actor.conditions.values()):
        model = condition.data.get('model', {})
        if condition.condition_id == SUPPRESSED and model.get('source_definition_id') == ASCENSION and model.get('source_actor_id') == ctx.actor.entity_id:
            cancel(ctx.engine, ctx.actor, 'condition:' + condition.instance_id, ASCENSION)
    automatic = finding['violated'] == 1 and not (finding['sole_available_way'] == 1 and finding['exception'] != 'none')
    dc = int(ctx.numbers['save_dc'])
    roll = None if automatic else ctx.engine._roll_save(ctx.actor, 'WIS', dc, ASCENSION,
        roll_context={'source_actor_id': ctx.actor.entity_id})
    failed = automatic or roll.total < dc
    if failed:
        set_level(ctx.engine, ctx.actor, level(ctx.actor) + 1, ASCENSION)
        if not strained(ctx.actor):
            ctx.engine._apply_condition(ctx.actor, STRAIN, ASCENSION, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'scene_id': held.data['scene_id'], 'label':
                    'Soul Anchor Strained: reconcile with your lineage for one hour. Possession by the Past costs 1 extra Resonance.'})
    ctx.engine._append_event('PASSIVE_TRIGGERED', ASCENSION, actor_id=ctx.actor.entity_id,
        payload={'checkpoint': 'ANCESTRAL_WITHDRAWAL', 'failed': int(failed), 'automatic_failure': int(automatic)})


@hook('journey_options')
def rite_options(session, aid):
    if session.state['phase'] != 'travel':
        return None
    out = []
    if session.state.get(REQUEST) and saved_conditions(session.state['actors'][aid], PRESENCE):
        out.append({'id': 'lineage:withdrawal', 'kind': 'native_procedure',
            'payload': {'source': ASCENSION, 'procedure': ENDING},
            'label': 'Ancestral Ascension: the scene is ending. Resolve the ancestor’s withdrawal with a Wisdom save against your own Cultivation Save DC. Failure causes 1 Exhaustion and Soul Anchor strain; no action or resource cost.'})
    if saved_conditions(session.state['actors'][aid], STRAIN):
        out.append({'id': 'lineage:reconciliation', 'kind': 'lineage_reconciliation', 'payload': {},
            'label': 'Reconcile with your lineage for one hour: end the Soul Anchor strain caused by Ancestral Ascension. No Resonance recovery or other cost.'})
    return out or None


@hook('journey_command')
def reconcile(session, aid, kind, payload):
    if kind != 'lineage_reconciliation':
        return None
    from ..journey import require
    actor = session.state['actors'][aid]
    rows = saved_conditions(actor, STRAIN)
    require(not payload and rows and not actor['incapacitated'], 'An acting creature must complete its actual one-hour lineage reconciliation.')
    session.tick(3600)
    for key, _ in rows:
        del actor['encounter_snapshot']['conditions'][key]
    session.emit('LINEAGE_RECONCILIATION_COMPLETED', aid, source=ASCENSION, seconds=3600,
        text='The one-hour lineage reconciliation ends only the Soul Anchor strain caused by Ancestral Ascension.')
    return True
