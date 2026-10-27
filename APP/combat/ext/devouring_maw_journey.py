"""Native journey callers for the Maw's one resource/state implementation.

Uses the fact/consent owner's scene and source-continuation contracts. Combat
exports actual records; travel never manufactures hostile damage or Essence.
The existing deterministic roll authority resolves the printed backlash. Only
this family's conditions are projected out of a terminal encounter snapshot.
"""
from copy import deepcopy
from fractions import Fraction
import json

from . import hook
from .devouring_maw import PREFIX, ESSENCE, TYPES_RECORD, DEVOUR, CAMPAIGN_POLICY, FARMING_EXCLUSION, records, restore_records

SOURCE = PREFIX.removesuffix('.feature.')
MODE = 'condition:typed.state.' + DEVOUR


def roles(actor):
    rows = actor['bundle'].get('typed_passives', [])
    out = {r['role']: r for r in rows if r.get('block') == 'path_rider' and r.get('kind') == 'devouring_maw'}
    profile = next((r for r in rows if r.get('block') == 'maw_family'), None)
    if profile is not None:
        out['family'] = profile
    return out


def source_state(session, actor_id):
    actor = session.state['actors'][actor_id]
    if not roles(actor):
        return None
    return actor.setdefault('source_states', {}).setdefault(SOURCE, {
        'records': [], 'mode_until_num': 0, 'mode_until_den': 1,
        'mode_cl': 0, 'used': 0, 'roll_counter': 0})


def mode_deadline(state):
    return Fraction(state['mode_until_num'], state['mode_until_den'])


def mode_action(actor):
    return next((a for a in actor['bundle'].get('action_catalog', [])
        if (a.get('parameters', {}).get('typed') or {}).get('source') == PREFIX + DEVOUR), None)


@hook('journey_initialize')
def initialize(session, actor_id):
    state = source_state(session, actor_id)
    if state is not None:
        session.state['actors'][actor_id]['resources'][ESSENCE] = len(state['records'])


@hook('journey_options')
def options(session, actor_id):
    actor = session.state['actors'][actor_id]
    if not roles(actor) or actor['incapacitated']:
        return None
    state = source_state(session, actor_id)
    out = []
    if state['records']:
        out.append({'id': 'maw_expel', 'kind': 'maw_expel', 'payload': {}, 'auto_select': 0,
            'label': f"Expel all {len(state['records'])} Devoured Essence: Action; take 1d6 Force damage directly to Hit Points per Essence"})
    action = mode_action(actor)
    if ('devour' in roles(actor) and action is not None and not state['used']
            and all(actor['resources'].get(pool, 0) >= amount for pool, amount in action['costs'])):
        out.append({'id': 'maw_devour', 'kind': 'maw_devour', 'payload': {}, 'auto_select': 0,
            'label': 'Devour Heaven and Earth: Bonus Action, 8 Stamina, once per scene; enhanced consumption and +3 Essence capacity for 1 minute'})
    return out


def calamity(session, actor_id, *, scene_scope=None):
    """One printed Force packet against the native continued health record."""
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec, ConditionInstance
    from .life_state import DEAD, UNCONSCIOUS, massive_threshold
    actor = session.state['actors'][actor_id]
    state = source_state(session, actor_id)
    if state is None or not state['records']:
        return
    count = len(state['records'])
    snapshot = actor.setdefault('encounter_snapshot', {
        'current_hp': actor['bundle']['actor_template']['maximum_hp'],
        'maximum_hp': actor['bundle']['actor_template']['maximum_hp'],
        'temporary_hp': 0, 'active': 1, 'life_state': '', 'conditions': {},
        'death_saves': {'ok': 0, 'bad': 0}})
    conditions = [ConditionInstance.model_validate(json.loads(row)) for row in snapshot['conditions'].values()]
    dead = any(c.condition_id == DEAD for c in conditions)
    # The printed exception requires positive campaign authority after death.
    # Absent that authority, death ends the records without a new consequence.
    if dead:
        from ..fact_consent_admission import read
        policy = read(session, SOURCE, actor_id, 'after_death_consequence',
                      scene_scope or session.state.get('scene_id', session.state['journey_id']), actor_id)
        if policy is None or policy['value'] != 1:
            state['records'] = []
            actor['resources'][ESSENCE] = 0
            session.emit('MAW_STATE_ENDED', actor_id, source=SOURCE, reason='Death; no campaign authority for an after-death consequence')
            return
    roller = DeterministicRollAuthority(session.state['journey_id'] + ':' + SOURCE + ':' + actor_id,
                                       counter=state['roll_counter'])
    roll = roller.roll(DiceSpec(count=count, sides=6), actor_id=actor_id, reason='Undigested Calamity')
    state['roll_counter'] = roller.counter
    before = snapshot['current_hp']
    snapshot['current_hp'] = max(0, before - roll.total)
    state['records'] = []
    actor['resources'][ESSENCE] = 0
    if snapshot['current_hp'] == 0 and not dead:
        death_saves = snapshot.setdefault('death_saves', {'ok': 0, 'bad': 0})
        if before == 0:
            death_saves['bad'] += 1
        else:
            death_saves.update(ok=0, bad=0)
        # Same massive-damage rule as combat (life_state.massive): the owner's own death_mode rows apply.
        massive = massive_threshold(snapshot['maximum_hp'], actor['bundle'].get('typed_passives', []))
        dies = roll.total - before >= massive or death_saves['bad'] >= 3
        snapshot['active'] = 0 if dies else 1
        snapshot['life_state'] = '' if dies else 'DYING'
        condition = ConditionInstance(instance_id=f"maw-health:{len(session.state['events'])}:{actor_id}",
            condition_id=DEAD if dies else UNCONSCIOUS, source_definition_id=PREFIX + 'swallow_hostile_power',
            source_actor_id=actor_id, target_id=actor_id, applied_sequence=len(session.state['events']) + 1,
            expires_on='UNTIL_REMOVED', data={'label': 'Dead' if dies else 'Unconscious at 0 Hit Points'})
        snapshot['conditions'][condition.instance_id] = condition.model_dump_json(exclude_none=True)
        actor['incapacitated'] = 1
    session.emit('UNAVOIDABLE_DAMAGE_COMMITTED', actor_id, source=SOURCE,
        damage_type='FORCE', essence_count=count, hp_before=before, remaining_hp=snapshot['current_hp'],
        temporary_hp_absorbed=0, roll=roll.model_dump(mode='json', exclude_none=True),
        text=f"Undigested Calamity: {actor['name']} loses all {count} Essence and takes {roll.total} Force damage directly to Hit Points.")


@hook('fact_admission_schema')
def campaign_policy(session, source, subject, kind):
    if source == SOURCE and kind == 'resource_farming' and any(roles(a) for a in session.state['actors'].values()):
        return {'value_type': 'flag', 'authority': 'table_owner', 'maximum_seconds': 86400,
                'description': 'This creature is being used in a deliberately staged or harmless interaction to farm Devoured Essence; it cannot generate Essence while this declaration applies.'}
    if source != SOURCE or kind != 'after_death_consequence' or not roles(session.state['actors'][subject]):
        return None
    return {'value_type': 'flag', 'authority': 'table_owner', 'maximum_seconds': 86400,
            'description': 'The governing campaign rule permits Undigested Calamity after this creature has died.'}


@hook('journey_command')
def command(session, actor_id, kind, payload):
    if kind not in ('maw_expel', 'maw_devour'):
        return None
    from ..journey import require
    offered = options(session, actor_id) or []
    require(not payload and any(o['kind'] == kind for o in offered), 'Choose an available Maw action with no extra parameters.')
    actor = session.state['actors'][actor_id]
    state = source_state(session, actor_id)
    if kind == 'maw_expel':
        calamity(session, actor_id)
    else:
        action = mode_action(actor)
        for pool, amount in action['costs']:
            actor['resources'][pool] -= amount
            session.emit('RESOURCE_SPENT', actor_id, source=PREFIX + DEVOUR, resource_id=pool, amount=amount,
                         remaining=actor['resources'][pool])
        deadline = session.clock() + 60
        state.update(mode_until_num=deadline.numerator, mode_until_den=deadline.denominator,
                     mode_cl=int((action['parameters']['typed']['numbers'])['cl']), used=1)
        session.emit('MAW_MODE_STARTED', actor_id, source=PREFIX + DEVOUR, duration_seconds=60,
                     text=f"{actor['name']} uses Devour Heaven and Earth for 1 minute, spending 8 Stamina and the scene use.")
    return True


@hook('journey_elapsed')
def elapsed(session, actor_id, previous, seconds, moving_ids):
    state = source_state(session, actor_id)
    if state is not None and mode_deadline(state) and session.clock() >= mode_deadline(state):
        state.update(mode_until_num=0, mode_until_den=1)
        session.emit('MAW_MODE_ENDED', actor_id, source=PREFIX + DEVOUR,
                     text='Devour Heaven and Earth ends; excess Essence remains, but prevents further gains while above capacity.')


@hook('journey_scene_end')
def scene_end(session, previous, current):
    for aid, actor in session.state['actors'].items():
        state = source_state(session, aid)
        if state is None:
            continue
        calamity(session, aid, scene_scope=previous)
        state.update(mode_until_num=0, mode_until_den=1, used=0)
        action = mode_action(actor)
        if action is not None:
            for pool, amount in action['costs']:
                if pool != 'resource:core.stamina':
                    initial = next(r['initial'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == pool)
                    actor['resources'][pool] = initial


@hook('journey_snapshot_actor')
def snapshot(actor, session, actor_id, engine):
    if not roles(session.state['actors'][actor_id]):
        return None
    copied = actor.model_copy(deep=True)
    copied.conditions = {key: c for key, c in copied.conditions.items() if c.condition_id not in (TYPES_RECORD, MODE, CAMPAIGN_POLICY, FARMING_EXCLUSION)}
    return copied


@hook('journey_encounter_settled')
def encounter_settled(session, actor_id, engine, creature):
    from .effect_durations import parse_round
    state = source_state(session, actor_id)
    if state is None:
        return
    state['records'] = records(creature)
    mode = next((c for c in creature.conditions.values() if c.condition_id == MODE), None)
    if mode is not None:
        deadline = parse_round(mode.expires_on)
        if deadline is None:
            raise ValueError('The Maw form requires its native counted duration for continuation')
        n = len(engine.state.initiative_order)
        slots = max(0, (deadline[0] - engine.state.round_number) * n + deadline[1] - engine.state.current_slot_index)
        end = session.clock() + Fraction(slots * 6, n)
        state.update(mode_until_num=end.numerator, mode_until_den=end.denominator,
                     mode_cl=int(mode.data['numbers']['cl']))
    else:
        state.update(mode_until_num=0, mode_until_den=1)
    action = mode_action(session.state['actors'][actor_id])
    if action is not None:
        state['used'] = int(any(pool != 'resource:core.stamina' and creature.resources[pool] < amount
                               for pool, amount in action['costs']))


@hook('journey_combat_setup')
def setup(session, actor_id):
    state = source_state(session, actor_id)
    if state is None:
        return None
    actor = session.state['actors'][actor_id]
    maximum = next(r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == ESSENCE)
    retained = {ESSENCE: len(state['records'])} if len(state['records']) > maximum else {}
    left = max(Fraction(0), mode_deadline(state) - session.clock())
    from ..fact_consent_admission import read
    policy = read(session, SOURCE, actor_id, 'after_death_consequence',
                  session.state.get('scene_id', session.state['journey_id']), actor_id)
    exclusions = []
    for source_actor_id in session.state['actors']:
        declaration = read(session, SOURCE, source_actor_id, 'resource_farming',
                           session.state.get('scene_id', session.state['journey_id']), source_actor_id)
        if declaration is not None and declaration['value'] == 1:
            remaining = Fraction(declaration['expires_at']) - session.clock()
            exclusions.append({'actor_id': source_actor_id, 'seconds_num': remaining.numerator,
                               'seconds_den': remaining.denominator, 'receipt_id': declaration['receipt_id']})
    return {'devouring_maw': {'records': deepcopy(state['records']), 'mode_seconds_num': left.numerator,
                             'mode_seconds_den': left.denominator, 'mode_cl': state['mode_cl'],
                             'excluded_sources': exclusions,
                             'after_death': int(policy is not None and policy['value'] == 1)},
            **({'resource_retained_excess': retained} if retained else {})}


@hook('match_initialize')
def restore(engine):
    from .effect_durations import SLOT_AT
    initialized = False
    for bundle in engine.typed_bundle_documents:
        data = (bundle.get('journey_setup') or {}).get('devouring_maw')
        actor = engine.state.actors.get(bundle.get('actor_id'))
        if data is None or actor is None:
            continue
        restore_records(engine, actor, data['records'])
        if data.get('after_death') == 1:
            engine._apply_condition(actor, CAMPAIGN_POLICY, SOURCE, actor.entity_id, expires_on='UNTIL_REMOVED',
                data={'label': 'Campaign rule permits Undigested Calamity after death'})
        for exclusion in data.get('excluded_sources', []):
            n = len(engine.state.initiative_order)
            seconds = Fraction(exclusion['seconds_num'], exclusion['seconds_den'])
            slots = -(-(seconds * n) // 6)
            deadline, slot = divmod(engine.state.round_number * n + engine.state.current_slot_index + slots, n)
            engine._apply_condition(actor, FARMING_EXCLUSION, SOURCE, actor.entity_id,
                expires_on=f'{SLOT_AT}:{deadline}:{slot}', data={'source_actor_id': exclusion['actor_id'],
                    'receipt_id': exclusion['receipt_id'], 'label': 'This source cannot generate Devoured Essence'})
        left = Fraction(data['mode_seconds_num'], data['mode_seconds_den'])
        if left > 0:
            n = len(engine.state.initiative_order)
            slots = -(-(left * n) // 6)
            deadline, slot = divmod(engine.state.round_number * n + engine.state.current_slot_index + slots, n)
            engine._apply_condition(actor, MODE, PREFIX + DEVOUR, actor.entity_id,
                expires_on=f'{SLOT_AT}:{deadline}:{slot}',
                data={'name': DEVOUR, 'label': 'Devour Heaven and Earth',
                      'rule': {'effect_kind': 'transformation'},
                      'numbers': {'cl': data['mode_cl'], 'pb': actor.proficiency_bonus}})
        initialized = True
    return True if initialized else None
