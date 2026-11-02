"""Mud Lotus source-specific admission and recovery/consequence consumers.

All subjective rulings come from owner-recorded recovery facts. Payment,
choices, roll checkpoints, HP settlement and clocks use native public seams.
The compiled ownership row gates every benefit; another Foundation is inert.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from . import hook
from ..recovery_sources import facts_for, genuine, recovery_records, source_matches, event_qualifies, source_procedure_profile
from ..relations import relation, ALLY, ENEMY

PREFIX = 'foundation.mud_lotus_dantian_v0_2A.'
FOUNDATION = 'mud_lotus_dantian_v0_2A'
DEW = 'resource:foundation.lotus_dew'
GENERATE = PREFIX + 'generate_lotus_dew'
RESERVE = PREFIX + 'mud_lotus_reserve'
ROOT = PREFIX + 'lotus_root_recovery'
GUARD = PREFIX + 'mud_lotus_guard'
WITNESS = PREFIX + 'humble_medicine_witness'
FILTER = PREFIX + 'refined_muddy_filter_dantian'
REFINED = PREFIX + 'refined_lotus_recovery'
SHELTER = PREFIX + 'refined_pond_shelter_aura'
FILTER_USED = 'condition:typed.muddy_filter_used'
RECOVERY_SCENES = {'treatment', 'stabilization', 'suppression', 'sickness', 'minor_injury_challenge'}
METHODS = {'humble_recovery', 'living_water', 'lotus_root', 'poison_treatment',
    'disease_treatment', 'living_pollution', 'shared_medicine', 'hardship_recovery', 'growth_through_mud'}
SCOPED = {'acid', 'poison', 'poisoned', 'disease', 'rot', 'polluted_water', 'terrain_contamination',
    'living_terrain_contamination', 'sickness_exhaustion', 'failed_medicine', 'failed_medicine_backlash', 'similar_scoped'}
EXTRA_GUARD = {'poison', 'poisoned', 'disease', 'rot', 'polluted_water',
    'living_terrain_contamination', 'failed_medicine', 'failed_medicine_backlash'}


@hook('journey_native_activity')
def outside_combat(session):
    # The public journey runtime owns actors, turns, choice transport and replay.
    # This source only opts in actors with an actual compiled ownership row.
    return any(r.get('block') == 'mud_lotus_native' for actor in session.state['actors'].values()
               for r in actor['bundle'].get('typed_passives', ())) or None


@hook('journal_notice_types')
def notices():
    return ('LOTUS_RECOVERY_ACCEPTED',)


@hook('feature_access_policy')
def expression_access(feature_id):
    if feature_id in (FILTER, REFINED):
        return {'foundation': FOUNDATION, 'minimum_stage': 'Refined', 'minimum_cl': 1,
                'classification': 'Foundation expression', 'source_kinds': ('chosen', 'unlocked')}


@hook('compile_passives')
def seal(passives, info):
    owned = sorted(i for i in info['owned_ids'] if i.startswith(PREFIX))
    if not owned:
        return passives
    return [*passives, {'block': 'mud_lotus_native', 'owned': owned,
        'pb': int(info['numbers']['pb']), 'key_mod': int(info['numbers']['key_mod'])}]


def ownership(engine, actor, feature):
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                if r.get('block') == 'mud_lotus_native' and feature in r['owned']), None)
    if row is not None:
        from .activation_requirements import foundation_ready
        stage = 'Perfected' if feature.endswith('lotus_recovery_field') else 'Refined' if feature.rsplit('.', 1)[-1].startswith('refined_') else 'Awakened'
        if not foundation_ready(actor, FOUNDATION, stage, passive=feature == RESERVE):
            return None
    return row


@hook('declared_source_owned')
def declared_owned(engine, actor, source):
    return bool(ownership(engine, actor, source)) if source.startswith(PREFIX) else None


@hook('candidate_allowed')
def active_gate(engine, actor, candidate, action):
    source = action.parameters.get('typed', {}).get('source', '') if action else ''
    if source.startswith(PREFIX) and ownership(engine, actor, source) is None:
        return False


@hook('reaction_subject_allowed')
@hook('row_allowed')
def reaction_gate(engine, actor, *args):
    row = args[-1]
    source = row.get('feature_id', '')
    if source.startswith(PREFIX) and ownership(engine, actor, source) is None:
        return False


def declaration(engine, actor, source, target=None):
    for fact in reversed(recovery_records(engine, actor, source)):
        row = fact.recovery
        if row is None:
            continue
        bound = source_matches(engine, row.source_ids, source)
        if bound and (target is None or target in row.recipient_ids):
            return row
    return None


def scene(engine, actor, source, target=None):
    row = declaration(engine, actor, source, target)
    return row if row is not None and genuine(row) else None


def refined_bonus(engine, actor, source, target=None):
    row = ownership(engine, actor, REFINED)
    # The recovery spend may occur during the hostile source's action. Facts
    # bind the actual spend for Root and the actual triggering source otherwise.
    fact = scene(engine, actor, source, target)
    return int(row['pb']) if row and fact and fact.scene in RECOVERY_SCENES else 0


@hook('compile_action')
def recovery_recipients(action, info):
    if action.parameters.get('typed', {}).get('source') == ROOT:
        return action.model_copy(update={'target_kind': 'ANY_CREATURE'})
    if RESERVE in info['owned_ids']:
        typed = action.parameters.get('typed', {})
        sphere = (info['mechanics'].get(typed.get('source')) or {}).get('sphere_id')
        if sphere:
            return action.model_copy(update={'parameters': {**action.parameters,
                'typed': {**typed, 'recovery_source_sphere_id': sphere}}})


@hook('technique_declared')
def root_prepare(engine, actor, action, candidate, intent):
    if action.parameters.get('typed', {}).get('source') != ROOT:
        return None
    from ..typed_executor import Context
    subject = engine.state.actors[candidate.target_ids[0]] if candidate.target_ids else actor
    ctx = Context(engine, actor, action, intent, action.parameters['typed'], [subject], subject)
    if not recovery_allowed(ctx, subject):
        return {'source_id': ROOT, 'label': 'Lotus-Root Recovery was not accepted; no action or Lotus Dew is spent.',
                'cancel': True, 'spend_activation': False}
    engine._append_event('LOTUS_RECOVERY_ACCEPTED', ROOT, actor_id=actor.entity_id,
        target_ids=(subject.entity_id,), payload={'recipient_id': subject.entity_id})


def recovery_allowed(ctx, subject):
    if any(e.event_type == 'LOTUS_RECOVERY_ACCEPTED' and e.actor_id == ctx.actor.entity_id
           and subject.entity_id in e.target_ids and e.trigger_or_intent_id == ctx.engine._active_intent_id
           for e in reversed(ctx.engine.events)):
        return True
    records = list(facts_for(ctx.engine, ctx.actor, ctx.source, subject.entity_id))
    if records and set(records[-1][1].exclusions) & {
            'preserve_corruption', 'hide_rot', 'spread_plague', 'poison_flooding',
            'rot_worship', 'forbidden_consumption'}:
        return False
    if subject.entity_id == ctx.actor.entity_id:
        return True
    # Native consent is held by the recipient, including on another actor's or
    # an AI's turn. Friendship is never a willingness receipt.
    from .needle import ask, checkpoint_id
    accepted = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'LOTUS_ROOT_CONSENT', subject.entity_id),
        subject, 'choice:needle.lotus_root_consent', ['accept'],
        allow_decline=True, preferred=['accept'], automatic=True,
        name='Lotus-Root Recovery', feature_id=ROOT, target_id=subject.entity_id,
        labels={'accept': f'Accept Lotus-Root Recovery from {ctx.actor.display_name}'},
        prompt=f'Lotus-Root Recovery: {ctx.actor.display_name} offers {subject.display_name} temporary Hit Points '
               f"and Advantage on the next contamination or treatment-backlash save until {ctx.actor.display_name}'s next turn starts. "
               'Accepting costs you nothing; the healer spends a Bonus Action and 1 Lotus Dew.')
    return bool(accepted)


def save_event_allowed(ctx, subject):
    declared = list(facts_for(ctx.engine, ctx.actor, ctx.source, subject.entity_id))
    return not declared or genuine(declared[-1][1])


def eligible_method(engine, actor, source, recipient=None):
    fact = declaration(engine, actor, source, recipient)
    if fact is None or fact.method not in METHODS or set(fact.exclusions) & {
            'preserve_corruption', 'hide_rot', 'spread_plague', 'poison_flooding',
            'rot_worship', 'forbidden_consumption'}:
        return False
    if source == SHELTER and ownership(engine, actor, SHELTER) is not None:
        return True  # Acquired native rest utility; deliberately no combat action.
    action = next((a for a in engine.action_catalog.values()
                   if a.owner_id == actor.entity_id and (a.source_definition_id == source
                   or a.parameters.get('typed', {}).get('source') == source)), None)
    if action is None:
        return False
    if action.parameters.get('typed', {}).get('source') in {ROOT, GUARD, WITNESS, PREFIX + 'lotus_recovery_field'}:
        return True
    # Authored Medicine/Survival/herbalism/Cultivation procedures are their own
    # legal check sources. Sphere techniques must be actually acquired actions;
    # facts cannot create Sphere access or change the catalogue.
    procedure = action.parameters.get('source_procedure')
    if procedure:
        return procedure['kind'] == 'treatment' or procedure.get('skill', '').lower() in {
            'medicine', 'survival', 'herbalism', 'cultivation'}
    typed = action.parameters.get('typed', {})
    sphere = str(typed.get('recovery_source_sphere_id') or typed.get('sphere') or '').removeprefix('tianxia.sphere.')
    return sphere in {'water', 'life', 'verdant_growth', 'flowers', 'alchemy', 'protection',
        'harvesting_gathering', 'earth', 'disease', 'poison', 'music'}


def aligned(engine, actor, source, recipient=None):
    return ownership(engine, actor, RESERVE) is not None and eligible_method(engine, actor, source, recipient)


@hook('technique_alignment')
def alignment(engine, actor, action, recipient_id=None):
    return 'mud_lotus' if aligned(engine, actor, action.source_definition_id, recipient_id) else None


@hook('state_event')
def settled_recovery_event(engine, event):
    settled_recovery(engine, event.event_type, {'actor_id': event.actor_id,
        'source_definition_id': event.source_definition_id, 'target_ids': event.target_ids,
        'payload': event.payload, 'sequence': event.sequence})


def settled_recovery(engine, event_type, event):
    if event_type not in ('HEALING_APPLIED', 'TEMP_HP_GRANTED', 'SOURCE_PROCEDURE_RESOLVED'):
        return
    if not event_qualifies(engine):
        return
    actor = engine.state.actors.get(event.get('actor_id'))
    source = event.get('source_definition_id') or ''
    if actor is None:
        return
    payload = event.get('payload') or {}
    if event_type == 'SOURCE_PROCEDURE_RESOLVED':
        fact = scene(engine, actor, source)
        if fact is None:
            return
        completed = payload.get('treatment_completed') == 1
        qualifies = (payload.get('cp_paid', 0) > 0 and aligned(engine, actor, source)
                     and (payload.get('kind') != 'treatment' or completed)) or (
            completed and fact.scene == 'dangerous')
        if qualifies:
            from .foundations3 import queue_foundation_resource
            queue_foundation_resource(engine, actor, 'lotus', source)
        return
    before, after = payload.get('before'), payload.get('after')
    if type(before) is not int or type(after) is not int or after <= before:
        return
    for aid in event.get('target_ids') or ():
        subject = engine.state.actors.get(aid)
        fact = scene(engine, actor, source, aid)
        if subject is None or fact is None:
            continue
        treatment = fact.method in {'medicine', 'lotus_root', 'poison_treatment', 'disease_treatment', 'shared_medicine'}
        if not (eligible_method(engine, actor, source, aid) or event_type == 'HEALING_APPLIED' and treatment):
            continue
        for owner in engine.state.actors.values():
            if ownership(engine, owner, GENERATE) and relation(engine, owner, subject) == ALLY and engine._distance_actor_to_actor(owner, subject) <= 30:
                from .foundations3 import queue_foundation_resource
                queue_foundation_resource(engine, owner, 'lotus', source)


def field_recovery_receipt(engine, provider, subject, parent):
    """Credit an owned Field component of an actual accepted native THP offer.

    parent is the real TEMP_HP_GRANTED event, not a manufactured HP receipt.
    The Field producer supplies its actually applied pre-interception quote;
    the native receipt must show a positive accepted grant before Dew can queue.
    """
    from .mud_lotus_recovery import FIELD
    if (parent.event_type != 'TEMP_HP_GRANTED' or parent.payload.get('after', 0) <= parent.payload.get('before', 0)
            or ownership(engine, provider, FIELD) is None or not event_qualifies(engine)
            or not eligible_method(engine, provider, FIELD, subject.entity_id)):
        return
    for owner in engine.state.actors.values():
        if ownership(engine, owner, GENERATE) and relation(engine, owner, subject) == ALLY and engine._distance_actor_to_actor(owner, subject) <= 30:
            from .foundations3 import queue_foundation_resource
            queue_foundation_resource(engine, owner, 'lotus', FIELD)


def environmental_source(engine, actor, source, subject_id, *, hostile=False):
    """An explicitly authored environmental cause, never self-harm relabeled by a tag."""
    procedure = source_procedure_profile(engine, actor, source)
    return (procedure is not None and procedure.get('origin') == 'environmental_hazard'
            and (procedure.get('consequence') is not None or procedure.get('harm', 0) > 0)
            and procedure.get('hostility') != 'benign'
            and (not hostile or procedure.get('hostility') == 'hostile')
            and scene(engine, actor, source, subject_id) is not None)


@hook('intent_resolved')
def settled_payment(engine, actor, candidate, intent, start_sequence):
    action = engine.action_catalog.get(candidate.source_definition_id)
    # Source procedures settle under their exact selected event binding above.
    # An unrelated later scene declaration cannot reclassify that payment.
    if action and action.parameters.get('source_procedure'):
        return
    if not action or not aligned(engine, actor, action.source_definition_id) or scene(engine, actor, action.source_definition_id) is None:
        return
    from ..typed_executor import CP_POOLS
    from ..technique_costs import net_paid
    if sum(net_paid(engine, actor, action.source_definition_id, start_sequence, CP_POOLS).values()) > 0:
        from .foundations3 import generate_foundation_resource
        generate_foundation_resource(engine, actor, 'lotus', action.source_definition_id)


def witness_guard(engine, holder, rc):
    if rc.kind == 'save':
        fact = declaration(engine, holder.actor, rc.source_id, holder.actor.entity_id)
        if fact is None or fact.method not in METHODS or set(fact.exclusions) & {
                'preserve_corruption', 'hide_rot', 'spread_plague', 'poison_flooding',
                'rot_worship', 'forbidden_consumption'}:
            return False
        action = next((a for a in engine.action_catalog.values() if a.source_definition_id == rc.source_id
                       or a.parameters.get('typed', {}).get('source') == rc.source_id), None)
        if action is None:
            return False
        procedure = action.parameters.get('source_procedure')
        if procedure:
            return procedure.get('skill', '').lower() in {'medicine', 'survival', 'herbalism', 'cultivation'}
        sphere = str(action.parameters.get('typed', {}).get('sphere') or '').removeprefix('tianxia.sphere.')
        return sphere in {'water', 'life', 'flowers', 'alchemy', 'protection', 'disease', 'poison'}
    if not aligned(engine, holder.actor, rc.source_id):
        return False
    action = next((a for a in engine.action_catalog.values() if a.owner_id == holder.actor.entity_id
                   and (a.source_definition_id == rc.source_id or a.parameters.get('typed', {}).get('source') == rc.source_id)), None)
    if action and not action.parameters.get('source_procedure'):
        typed = action.parameters.get('typed', {})
        sphere = str(typed.get('recovery_source_sphere_id') or typed.get('sphere') or '').removeprefix('tianxia.sphere.')
        if sphere not in {'water', 'life', 'flowers', 'alchemy', 'protection', 'disease', 'poison'}:
            return False
    if rc.kind == 'check':
        return True
    return False


def witness_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        row = ownership(engine, actor, WITNESS)
        if row:
            yield Holder(actor, WITNESS, row, WITNESS, {'pb': row['pb']})


def witness_purpose(fact, actor_id):
    """The GM's roll-purpose ruling belongs to the actual Witness holder."""
    return actor_id in (fact.purpose_actor_ids or (fact.actor_id,)) and (
        fact.treats_another or fact.cleanses_source or fact.accepts_help or fact.humble_material)


def witness_after(engine, holder, rc, result, amount):
    # Keep the exact roll receipt until this procedure's consequence resolves.
    engine._apply_condition(holder.actor, 'condition:typed.humble_medicine_witness', WITNESS,
        holder.actor.entity_id, expires_on='END_OF_CURRENT_TURN',
        data={'source_id': rc.source_id, 'roll_id': result.roll_id,
              'intent_id': engine._active_intent_id,
              'label': 'Humble Medicine Witness: this rolled treatment may reduce one Minor consequence.'})
    fact = declaration(engine, holder.actor, rc.source_id)
    if fact is None or not fact.gm_reduce_minor or not fact.gm_consequence_ids:
        return
    if not witness_purpose(fact, holder.actor.entity_id):
        return
    allowed = [(subject, c) for aid in fact.recipient_ids for subject in [engine.state.actors[aid]]
        for key, c in subject.conditions.items() if key in fact.gm_consequence_ids
        and c.data.get('classification') == 'Minor' and c.data.get('severity', 0) > 1
        and c.condition_id.startswith('condition:source.') and c.data.get('declaration')
        and c.data.get('category') in {'poison', 'disease', 'rot', 'polluted_water', 'terrain_contamination'}]
    if not allowed:
        return
    from .needle import ask, checkpoint_id
    picked = ask(engine, engine._active_intent, checkpoint_id(engine, 'WITNESS_MINOR', result.roll_id),
        holder.actor, 'choice:needle.humble_medicine_consequence', [c.instance_id for _, c in allowed],
        labels={c.instance_id: f"{subject.display_name}: {c.data['name']}, reduce one source-defined step"
                for subject, c in allowed}, allow_decline=True, automatic=True,
        name='Humble Medicine Witness', feature_id=WITNESS,
        prompt='Humble Medicine Witness: the GM permits reducing one of these actual Minor treatment consequences by one step. No additional Lotus Dew or action is spent.')
    if not picked:
        return
    subject, marker = next(pair for pair in allowed if pair[1].instance_id == picked[0])
    from ..typed_executor import Context
    from .source_procedures import reduce_existing
    action = next(a for a in engine.action_catalog.values()
                  if a.source_definition_id == rc.source_id or a.parameters.get('typed', {}).get('source') == rc.source_id)
    ctx = Context(engine, holder.actor, action, engine._active_intent, action.parameters['typed'], [subject], subject)
    if reduce_existing(ctx, subject, marker):
        engine._remove_condition(holder.actor, 'condition:typed.humble_medicine_witness', WITNESS)


from .d20_rewrite import Rule, register
register(Rule('mud_lotus_witness', 'Humble Medicine Witness', rolls=('check', 'save'),
    when='any', op='bonus', finder=witness_holders, guard=witness_guard,
    costs=(((('lotus_dew', 1)),),), before_outcome=True,
    bonus=lambda e, h, rc: int(h.numbers['pb']) + refined_bonus(e, h.actor, rc.source_id),
    ai=lambda e, h, rc: True, after_bonus=witness_after))


def choose(engine, owner, source, name, label, target, options=('use',), *, automatic_options=None):
    from .needle import ask, checkpoint_id
    return ask(engine, engine._active_intent,
        checkpoint_id(engine, name, owner.entity_id, target.entity_id), owner,
        'choice:needle.' + source.rsplit('.', 1)[-1], list(options),
        allow_decline=True, preferred=[options[0]], automatic=True,
        automatic_options=automatic_options,
        name=name, feature_id=source, target_id=target.entity_id,
        labels={key: label if key == 'use' else key.replace('_', ' ').title() + ': ' + label for key in options},
        prompt=name + ': ' + label)


@hook('consequence_pending')
def minor_consequence(ctx, subject, consequence):
    result = dict(consequence)
    fact = declaration(ctx.engine, ctx.actor, ctx.source, subject.entity_id)
    if fact is None or result['classification'] != 'Minor' or set(fact.exclusions) & {
            'preserve_corruption', 'hide_rot', 'spread_plague', 'poison_flooding',
            'rot_worship', 'forbidden_consumption'}:
        return None
    # Witness is an optional GM ruling bound to the actual paid roll.
    witness_owner, witness = next(((holder, c) for holder in (ctx.actor, subject)
        for c in holder.conditions.values() if c.condition_id == 'condition:typed.humble_medicine_witness'
        and c.data.get('source_id') == ctx.source and c.data.get('intent_id') == ctx.engine._active_intent_id), (None, None))
    if witness and fact.gm_reduce_minor and not fact.gm_consequence_ids and witness_purpose(fact, witness_owner.entity_id):
        if result['category'] in {'poison', 'disease', 'rot', 'polluted_water', 'terrain_contamination'} and result['steps'] and result['severity'] > 1:
            result['severity'] = max(0, result['severity'] - 1)
            ctx.engine._remove_condition(witness_owner, witness.condition_id, WITNESS)
    row = ownership(ctx.engine, subject, FILTER)
    used = any(c.condition_id == FILTER_USED for c in subject.conditions.values())
    if row and not used and result['severity'] > 0 and result['category'] in {
            'poison', 'poisoned', 'disease', 'hunger', 'alchemy', 'medicine', 'impurity', 'pill_impurity'}:
        options = ('reduce_step', 'ignore') if result['steps'] and result['severity'] > 1 else ('ignore',)
        picked = choose(ctx.engine, subject, FILTER, 'Muddy Filter Dantian',
            f"{ctx.action.display_name} would give {subject.display_name} {result['name']}, a Minor consequence. "
            'Reduce one source-defined step or ignore it; once per long rest, no action or resource cost.', subject, options)
        if picked:
            result['severity'] = 0 if picked[0] == 'ignore' else max(0, result['severity'] - 1)
            ctx.engine._apply_condition(subject, FILTER_USED, FILTER, subject.entity_id,
                expires_on='UNTIL_REMOVED', data={'label': 'Muddy Filter Dantian used; recharges after a long rest.'})
    if result['severity'] > 0 and result['kind'] == 'hidden_injury' and result.get('strain') and result['category'] in {'poison', 'disease', 'rot', 'polluted_water', 'failed_medicine'}:
        from .mud_lotus_recovery import fields, FIELD
        for owner, condition in fields(ctx.engine, subject, any_creature=True):
            if condition.data.get('injury_used'):
                continue
            if choose(ctx.engine, owner, FIELD, 'Lotus Recovery Field',
                    f"{ctx.action.display_name} would give {subject.display_name} a Minor Hidden Injury ({result['name']}). "
                    'Replace it with Strain once during this field, at no additional cost.', subject):
                strain = result['strain']
                from ..typed_executor import effect_expiry
                result.update(kind='strain', name='Strain', severity=1,
                    mechanical_effect=strain['mechanical_effect'], effects=strain['effects'],
                    step_effects=[], step_replacement_effects=[], steps=[], recovery_mode=strain['recovery_mode'],
                    duration=strain['duration'], expires=effect_expiry(ctx,
                        {'duration': {'kind': strain['duration_kind']}}, subject, condition=True))
                ctx.engine._update_condition_data(owner, condition,
                    {**condition.data, 'injury_used': 1}, FIELD)
                break
    return result




@hook('recovery_declaration')
def corruption(engine, fact):
    row = fact.recovery
    if not set(row.exclusions) & {'preserve_corruption', 'hide_rot', 'spread_plague'}:
        return
    end_corrupt_field(engine, engine.state.actors[row.actor_id], row)


@hook('intent_resolved')
def corrupt_manifestation(engine, actor, candidate, intent, start_sequence):
    """A declared corrupt purpose also ends a field created after admission."""
    from .mud_lotus_recovery import FIELD
    action = engine.action_catalog.get(candidate.source_definition_id)
    if action and (action.parameters.get('typed') or {}).get('source') == FIELD:
        # technique_used precedes the effects: only settled native resolution
        # has an actual manifested field to end, with its cost already paid.
        row = declaration(engine, actor, FIELD)
        if row and set(row.exclusions) & {'preserve_corruption', 'hide_rot', 'spread_plague'}:
            end_corrupt_field(engine, actor, row)


def end_corrupt_field(engine, owner, row):
    """Settle the printed corruption boundary for an actually manifested field."""
    from .mud_lotus_recovery import FIELD, CONDITION
    condition = next((c for c in owner.conditions.values() if c.condition_id == CONDITION), None)
    if condition is None or not ownership(engine, owner, FIELD):
        return
    if not any(engine.action_catalog.get(sid) and engine.action_catalog[sid].parameters.get('typed', {}).get('source') == FIELD for sid in row.source_ids):
        return
    from .. import zones
    zone = engine.state.zones.get(condition.data['zone_id'])
    if zone is not None and zone.active:
        zones.remove(engine, zone, FIELD)
    engine._remove_condition(owner, CONDITION, FIELD)
    if any(c.condition_id == 'condition:typed.muddy_stagnation' for c in owner.conditions.values()):
        return
    engine._apply_condition(owner, 'condition:typed.muddy_stagnation', FIELD, owner.entity_id,
        expires_on='UNTIL_REMOVED', data={'severity': 1, 'label': 'Muddy Stagnation, severity 1: the field ended after preserving corruption.'})


def turn_key(engine):
    actor = engine.state.actors[engine.state.current_actor_id]
    return f'{engine.state.round_number}:{actor.entity_id}:{actor.turns_started}'


def hostile_fields(engine, actor, target, source, extra_categories=()):
    if (source_procedure_profile(engine, actor, source) or {}).get('hostility') == 'benign':
        return
    if target is None or (relation(engine, actor, target) != ENEMY and not environmental_source(
            engine, actor, source, target.entity_id, hostile=True)):
        return
    fact = scene(engine, actor, source, target.entity_id)
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and (a.source_definition_id == source or a.parameters.get('typed', {}).get('source') == source)), None)
    def categories(effects):
        result = set()
        for eff in effects:
            result.update(eff.get('save_categories', ()))
            result.update(eff.get('damage_types', ()))
            for key in ('on_hit', 'on_fail', 'on_success'):
                result.update(categories(eff.get(key, ())))
        return result
    named = set(extra_categories)
    named.update(fact.categories if fact else categories(action.parameters.get('typed', {}).get('effects', ())) if action else ())
    if action and action.damage_type:
        named.add(str(action.damage_type).lower())
    if not named & {'poison', 'poisoned', 'disease', 'rot', 'polluted_water', 'pollution'}:
        return
    from .mud_lotus_recovery import fields
    for owner, condition in fields(engine, target, any_creature=True):
        if relation(engine, owner, actor) == ENEMY and condition.data.get('hostile_turn') != turn_key(engine):
            yield owner, condition


@hook('attack_mode_contribution')
def hostile_attack(engine, attacker, target):
    context = engine.d20_context() or {}
    source = context.get('source_id')
    current = _hostile_attack.get()
    extra = ()
    if current and current[:2] == (engine, attacker.entity_id):
        source, extra = current[2:]
    if next(hostile_fields(engine, attacker, target, source or '', extra), None):
        return 'DISADVANTAGE'


_hostile_attack = ContextVar('mud_lotus_hostile_attack', default=None)


@hook('attack_resolution_scope')
def attack_source(engine, actor, target, spec, intent):
    @contextmanager
    def scope():
        typed = spec.get('typed') or (spec.get('parameters') or {}).get('typed') or {}
        source = spec.get('source_definition_id') or typed.get('source', '')
        token = _hostile_attack.set((engine, actor.entity_id, source,
                                    (str(spec.get('damage_type', '')).lower(),)))
        try:
            yield
        finally:
            _hostile_attack.reset(token)
    return scope()


_hostile_contest = ContextVar('mud_lotus_hostile_contest', default=None)


@hook('contest_resolution_scope')
def contest_source(ctx, target, actor_check, target_check):
    @contextmanager
    def scope():
        # The native resolver identifies printed Save DC contests; an ordinary
        # skill check or opposed check must not spend this field allowance.
        value = ((ctx.engine, ctx.actor.entity_id, target.entity_id, ctx.source)
                 if target_check.get('kind') == 'dc' else None)
        token = _hostile_contest.set(value)
        try:
            yield
        finally:
            _hostile_contest.reset(token)
    return scope()


@hook('contest_check_mode')
def hostile_contest(ctx, subject, opponent, spec):
    if (_hostile_contest.get() == (ctx.engine, subject.entity_id, opponent.entity_id, ctx.source)
            and next(hostile_fields(ctx.engine, subject, opponent, ctx.source), None)):
        return 'DISADVANTAGE'


@hook('d20_finalized')
def consume_hostile_roll(engine, roll, intent):
    from .d20_rewrite import context_of
    rc = context_of(engine, roll)
    if rc is None or rc.kind not in ('attack', 'check') or rc.target is None:
        return
    if rc.kind == 'check' and _hostile_contest.get() != (
            engine, rc.roller.entity_id, rc.target.entity_id, rc.source_id):
        return
    from .mud_lotus_recovery import FIELD
    for owner, condition in hostile_fields(engine, rc.roller, rc.target, rc.source_id):
        engine._update_condition_data(owner, condition,
            {**condition.data, 'hostile_turn': turn_key(engine)}, FIELD)


@hook('shared_rest_beneficiaries')
def shelter_beneficiaries(session, aid, recipient_ids):
    """Every beneficiary group Pond-Shelter Aura may name at start: up to PB distinct recipients, including none.

    Inert (None) for creatures without the owned Refined row or without the Refined foundation.
    """
    from itertools import combinations
    from .activation_requirements import journey_foundation_ready
    actor = session.state['actors'][aid]
    row = next((r for r in actor['bundle'].get('typed_passives', ())
                if r.get('block') == 'mud_lotus_native' and SHELTER in r['owned']), None)
    if row is None or not journey_foundation_ready(actor, FOUNDATION, 'Refined'):
        return None
    return [group for size in range(min(row['pb'], len(recipient_ids)) + 1)
            for group in combinations(recipient_ids, size)]


@hook('shared_short_rest_completed')
def pond_shelter(session, aid, roster, facts, selected):
    from .activation_requirements import journey_foundation_ready
    actor = session.state['actors'][aid]
    row = next((r for r in actor['bundle'].get('typed_passives', ())
                if r.get('block') == 'mud_lotus_native' and SHELTER in r['owned']), None)
    rest_exclusions = {'staged', 'farmed', 'training', 'sterile', 'hostile_rest', 'dry',
                       'preserve_corruption', 'hide_rot', 'spread_plague'}
    if (row is None or not journey_foundation_ready(actor, FOUNDATION, 'Refined')
            or facts.reality != 'genuine' or rest_exclusions.intersection(facts.exclusions) or facts.method not in {
            'food', 'medicine', 'living_water', 'humble_shelter', 'shared_medicine'}):
        return
    from ..journey import require
    require(len(set(selected)) == len(selected) and len(selected) <= row['pb'],
            'Pond-Shelter Aura supports at most your Proficiency Bonus distinct resting creatures.')
    require(set(selected) <= set(roster), 'Every chosen creature must willingly complete this shared rest.')
    from ..journey_activity import commit_utility
    from ..table_facts import apply
    from ..recovery_sources import recovery_event
    from ..fact_consent_admission import read
    from .shared_rests import SOURCE as REST_SCENE
    declaration = read(session, REST_SCENE, aid, 'recovery_scene', session.state['journey_id'], aid)
    require(declaration is not None, 'The table-owner recovery scene must remain current through this rest.')
    def resolve(engine):
        # This is the actual protected GM scene declaration and completed roster,
        # imported into the existing native observation contract, not an outcome.
        record_id = 'shared_rest:' + str(session.state['revision'])
        document = {'record_id': record_id, 'subject_id': aid,
            'subject_name': actor['name'], 'subject_kind': 'creature',
            'position': actor['position'], 'source_reference': facts.evidence,
            'witness_ids': sorted({aid, *declaration['readers']}), 'valid_through_round': engine.state.round_number,
            'answers': {}, 'recovery': facts.model_dump(mode='json')}
        apply(engine, document)
        with recovery_event(engine, record_id):
            for target_id in selected:
                engine._grant_temp_hp(engine.state.actors[target_id], row['pb'], SHELTER, aid)
            # The utility has fully resolved; use the same public settled-event
            # queue as techniques. A grant never spends its own new Dew.
            from .foundations3 import flush_foundation_resources
            flush_foundation_resources(engine)
    commit_utility(session, aid, SHELTER, 'finish_shared_rest', resolve)


@hook('journey_rest')
def filter_recharges(session, aid):
    actor = session.state['actors'][aid]
    snapshot = actor.get('encounter_snapshot')
    if snapshot is not None:
        snapshot['conditions'] = {key: raw for key, raw in snapshot['conditions'].items()
            if json.loads(raw).get('condition_id') != FILTER_USED}
    # Restore only the owned field's actual compiled daily-use pool. Ordinary
    # CP and unrelated abilities keep the recovery contracts of their owners.
    maxima = {r['resource_id']: r['maximum'] for r in actor['bundle']['actor_template']['resources']}
    for action in actor['bundle'].get('action_catalog', ()):
        if action.get('parameters', {}).get('typed', {}).get('source') != PREFIX + 'lotus_recovery_field':
            continue
        for resource, amount in action.get('costs', ()):
            if resource.startswith('resource:uses.') and amount > 0 and resource in maxima:
                before = int(actor['resources'].get(resource, 0))
                actor['resources'][resource] = int(maxima[resource])
                if before != actor['resources'][resource]:
                    session.emit('RESOURCE_RESTORED', aid, resource_id=resource,
                        before=before, after=actor['resources'][resource], source_id=PREFIX + 'lotus_recovery_field')
