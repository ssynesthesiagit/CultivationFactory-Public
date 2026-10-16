"""Restricted Scripture acquisition through native source/authority contracts.

The generic owner supplies authenticated table declarations and durable source
acquisition. This provider owns only Hundred-Hand access, its five thresholds,
and the installed-sheet continuation. It never accepts a caller's feature list.
"""
from copy import deepcopy
import json
from . import hook
from ..journey import require
from .hundred_hands import PREFIX, BODY, LEVELS

PARENT = PREFIX.removesuffix('.feature.')


def attainment(sheet):
    paths = sheet.get('path_and_subpath') or {}
    rows = [r for r in paths.get('paths', []) if r.get('path_id') == BODY]
    if not rows:
        return 0
    values = [rows[0][key] for key in ('attained_cl', 'attainment', 'owning_path_level') if key in rows[0]]
    require(values and all(type(n) is int for n in values) and len(set(values)) == 1,
            'Record consistent acquired Body Path attainment; overall CL cannot grant this progression.')
    level = values[0]
    require(0 <= level <= int(sheet['identity']['cultivation_level']), 'Body attainment cannot exceed overall CL.')
    return level


def saved(actor):
    return actor.get('source_states', {}).get(PARENT, {})


@hook('fact_admission_schema')
def access_schema(session, source, subject, kind):
    if source != PARENT or kind != 'scripture_access' or subject not in session.state['actors']:
        return None
    return {'value_type': 'document', 'maximum_seconds': 2592000, 'authority': 'table_owner',
            'description': 'Actual access to the controlled Hundred-Hand Battle Mandala Restricted Scripture. Access does not grant Body attainment, proficiency or another Subpath.'}


@hook('journey_acquisition')
def acquire(session, aid, source, payload, sheet):
    if source != PARENT:
        return None
    from ..fact_consent_admission import read, canonical
    require(set(payload) == {'access_scope'}, 'Choose the recorded Restricted Scripture access.')
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'A conscious practitioner must acquire the scripture.')
    access = read(session, PARENT, aid, 'scripture_access', payload['access_scope'], aid)
    require(access is not None, 'Record actual Restricted Scripture access through native table-owner input first.')
    value = access['value']
    require(set(value) == {'scripture', 'instruction', 'source_rule'} and value['scripture'] == PARENT
            and all(type(value[key]) is str and value[key].strip() for key in ('instruction', 'source_rule')),
            'Name this scripture, its actual controlled instruction, and the governing access Source Rule.')
    cl = attainment(sheet)
    require(cl >= 3, 'Hundred-Hand Battle Mandala requires acquired Body attainment 3.')
    paths = sheet.setdefault('path_and_subpath', {})
    require(BODY in paths.get('path_record_ids', []), 'Acquire the Body Refining Path before its Subpath.')
    selected = set(paths.get('subpath_record_ids') or []) | {paths.get('subpath_record_id')}
    require(PARENT not in selected and not saved(actor).get('acquired_sheet'), 'Hundred-Hand is already acquired; acquisition cannot reset its limits.')
    require(not any(type(s) is str and s.startswith('tianxia.subpath.body.') for s in selected),
            'One Body Subpath progression is legal; resolve an explicit replacement before acquisition.')
    keys = ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids', 'advancement_feature_record_ids')
    current = {s for key in keys for s in paths.get(key, [])}
    current.update(r.get('feature_id') for r in paths.get('earned_feature_occurrences', []))
    require(not any(type(s) is str and s.startswith('tianxia.subpath.body.') for s in current), 'Do not retain a competing Body Subpath progression.')
    earned = [PREFIX + slug for slug, threshold in LEVELS.items() if threshold <= cl]
    paths['path_feature_record_ids'] = list(dict.fromkeys([*paths.get('path_feature_record_ids', []), *earned]))
    paths['subpath_record_id'] = PARENT
    paths['subpath_record_ids'] = [s for s in selected if s and not s.startswith('tianxia.subpath.body.')] + [PARENT]
    paths['subpath_acquisition'] = {'source': PARENT, 'access_receipt': access['receipt_id'], 'path_level': cl}
    actor.setdefault('source_states', {}).setdefault(PARENT, {})['acquired_sheet'] = canonical(sheet)
    session.emit('HUNDRED_HAND_ACQUIRED', aid, source=PARENT, access_receipt=access['receipt_id'], body_attainment=cl, features=earned)
    return {'sheet': sheet, 'acquisition_id': access['receipt_id']}


@hook('journey_source_sheet')
def acquired_sheet(sheet, session, aid):
    text = saved(session.state['actors'][aid]).get('acquired_sheet')
    if not text:
        return None
    old = json.loads(text)['path_and_subpath']
    result = deepcopy(sheet)
    paths = result.setdefault('path_and_subpath', {})
    selected = set(paths.get('subpath_record_ids') or []) | {paths.get('subpath_record_id')}
    existing = {value for key in ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids', 'advancement_feature_record_ids')
                for value in paths.get(key, [])}
    existing.update(row.get('feature_id') for row in paths.get('earned_feature_occurrences', []))
    require(not any(type(value) is str and value.startswith('tianxia.subpath.body.')
                    and value != PARENT and not value.startswith(PREFIX) for value in selected | existing),
            'Resolve the existing Body Subpath replacement before continuing; two progressions cannot be granted together.')
    cl = attainment(sheet)
    paths['path_feature_record_ids'] = list(dict.fromkeys([s for s in paths.get('path_feature_record_ids', []) if not s.startswith(PREFIX)]
        + [PREFIX + slug for slug, threshold in LEVELS.items() if threshold <= cl]))
    for key in ('subpath_record_id', 'subpath_record_ids', 'subpath_acquisition'):
        paths[key] = deepcopy(old[key])
    return result

# Source-specific continuation over the shared journey source_states contract.
from fractions import Fraction
from .hundred_hands import HANDS, STATE
INCARNATION = PREFIX + 'thousand_hand_incarnation'


def incarnation_action(actor):
    return next((a for a in actor['bundle']['action_catalog']
                 if (a.get('parameters', {}).get('typed') or {}).get('source') == INCARNATION), None)


def journey_level(session, aid):
    from .path_authority import journey_cl
    actor = session.state['actors'][aid]
    learned = int(actor['bundle'].get('hundred_hand_profile', {}).get('body_cl', 0))
    return min(learned, journey_cl(session, aid, BODY, learned))


def journey_pb(session, aid):
    actor = session.state['actors'][aid]
    level = journey_level(session, aid)
    value = actor['bundle']['actor_template'].get('proficiency_bonus')
    base = int(value) if type(value) is int else 2
    ruling = actor.get('source_states', {}).get('path_authority', {}).get(BODY, {})
    return min(base, ruling.get('proficiency_bonus', base))


def incarnation_record(actor):
    return actor.setdefault('source_states', {}).setdefault(PARENT, {}).setdefault('incarnation', {})


def remaining(session, aid):
    record = saved(session.state['actors'][aid]).get('incarnation', {})
    if not record.get('active'):
        return Fraction(0)
    return max(Fraction(0), Fraction(record['expires_num'], record['expires_den']) - session.clock())


def journey_incarnation_active(session, aid):
    return bool(incarnation_action(session.state['actors'][aid]) and journey_level(session, aid) >= 18 and remaining(session, aid))


def sync_incarnation(session, aid):
    from ..canonical import canonical_sha256
    actor = session.state['actors'][aid]
    if not actor['bundle'].get('hundred_hand_profile'):
        return
    cap = journey_pb(session, aid) * (2 if journey_incarnation_active(session, aid) else 1)
    if HANDS in actor['resources']:
        actor['resources'][HANDS] = min(actor['resources'][HANDS], cap)
        for pool in actor['bundle']['actor_template']['resources']:
            if pool['resource_id'] == HANDS:
                pool['maximum'] = cap
                pool['initial'] = min(pool['initial'], cap)
    if incarnation_action(actor) is None:
        actor['bundle'].pop('bundle_sha256', None)
        actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])
        return
    record = incarnation_record(actor)
    left = remaining(session, aid)
    if record.get('active') and not left:
        record['active'] = 0
        session.emit('MANDALA_INCARNATION_ENDED', aid, source=INCARNATION,
                     expiry_num=record['expires_num'], expiry_den=record['expires_den'])
    if not record.get('active'):
        record['extra_reaction_ready'] = 0
    record.update(remaining_num=left.numerator, remaining_den=left.denominator,
                  clock_journey=session.state['journey_id'])
    cap = journey_pb(session, aid) * (2 if journey_incarnation_active(session, aid) else 1)
    if HANDS in actor['resources']:
        actor['resources'][HANDS] = min(actor['resources'][HANDS], cap)
    actor['bundle']['journey_hundred_hand'] = deepcopy(record)
    actor['bundle'].pop('bundle_sha256', None)
    actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


@hook('journey_initialize')
def initialize_continuation(session, aid):
    actor = session.state['actors'][aid]
    if incarnation_action(actor) is None:
        sync_incarnation(session, aid)
        return
    record = incarnation_record(actor)
    if record.get('clock_journey') not in (None, session.state['journey_id']):
        left = Fraction(record.get('remaining_num', 0), record.get('remaining_den', 1))
        end = session.clock() + left
        record.update(expires_num=end.numerator, expires_den=end.denominator)
    sync_incarnation(session, aid)


@hook('journey_options')
def incarnation_options(session, aid):
    actor = session.state['actors'][aid]
    action = incarnation_action(actor)
    if session.state['phase'] != 'travel' or actor['incapacitated'] or action is None or journey_level(session, aid) < 18:
        return None
    if any(actor['resources'].get(resource, 0) < amount for resource, amount in action['costs']):
        return None
    return [{'id': INCARNATION, 'kind': 'mandala_incarnation', 'payload': {}, 'auto_select': 0,
             'label': actor['name'] + ': Thousand-Hand Incarnation; Bonus Action, 7 Stamina, once per scene, lasts 1 minute.'}]


@hook('journey_command')
def activate_incarnation(session, aid, kind, payload):
    if kind != 'mandala_incarnation':
        return None
    require(not payload and incarnation_options(session, aid), 'Acquire Thousand-Hand Incarnation, sufficient Stamina and an unused scene activation while conscious and unsuppressed.')
    actor = session.state['actors'][aid]
    action = incarnation_action(actor)
    for resource, amount in action['costs']:
        session.spend_resource(aid, resource, amount, INCARNATION)
    end = session.clock() + 60
    record = incarnation_record(actor)
    record.update(active=1, expires_num=end.numerator, expires_den=end.denominator,
                  activated_num=session.clock().numerator, activated_den=session.clock().denominator,
                  source_cl=journey_level(session, aid), source_pb=journey_pb(session, aid), scene_used=1, extra_reaction_ready=0)
    actor['resources'][HANDS] = 2 * journey_pb(session, aid)
    sync_incarnation(session, aid)
    session.emit('MANDALA_INCARNATION_ACTIVATED', aid, source=INCARNATION, stamina=7,
                 expires_num=end.numerator, expires_den=end.denominator)
    return True


@hook('journey_elapsed')
def incarnation_elapsed(session, aid, previous, seconds, moving):
    if incarnation_action(session.state['actors'][aid]) is not None:
        sync_incarnation(session, aid)


@hook('journey_state_changed')
def incarnation_changed(session, aid):
    actor = session.state['actors'][aid]
    if incarnation_action(actor) is None:
        sync_incarnation(session, aid)
        return
    snapshot = actor.get('encounter_snapshot', {})
    conditions = [json.loads(raw) for raw in snapshot.get('conditions', {}).values()]
    unconscious = snapshot.get('life_state') in ('DYING', 'STABLE') or any(
        c['condition_id'] in ('unconscious', 'condition:typed.unconscious', 'condition:core.unconscious', 'condition:typed.life_unconscious') for c in conditions)
    if unconscious:
        incarnation_record(actor)['active'] = 0
    sync_incarnation(session, aid)


@hook('journey_scene_end')
def incarnation_new_scene(session, previous, current):
    for aid, actor in session.state['actors'].items():
        action = incarnation_action(actor)
        if action is None:
            continue
        for resource, amount in action['costs']:
            if resource.startswith('resource:uses.'):
                actor['resources'][resource] = 1
        incarnation_record(actor)['scene_used'] = 0
        sync_incarnation(session, aid)


@hook('journey_properties')
def incarnation_properties(session, aid):
    actor = session.state['actors'][aid]
    if incarnation_action(actor) is None:
        return None
    left = remaining(session, aid)
    return {'mandala_incarnation_active': int(journey_incarnation_active(session, aid)),
            'mandala_remaining_num': left.numerator, 'mandala_remaining_den': left.denominator,
            'battle_hands_maximum': journey_pb(session, aid) * (2 if journey_incarnation_active(session, aid) else 1),
            'circle_extra_reaction_available': int(journey_incarnation_active(session, aid) and
                saved(actor).get('incarnation', {}).get('extra_reaction_ready', 0))}


@hook('match_initialize', priority=-100)
def restore_incarnation(engine):
    from .states import PREFIX as STATE_PREFIX
    for bundle in engine.typed_bundle_documents:
        data = bundle.get('journey_hundred_hand')
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None or not data or not data.get('active'):
            continue
        left = Fraction(data.get('remaining_num', 0), data.get('remaining_den', 1))
        if left <= 0:
            continue
        slots = max(1, len(engine.state.initiative_order))
        boundary = (left * slots / 6).__ceil__()
        expiry = f'START_OF_SLOT_AT:{1 + boundary // slots}:{boundary % slots}'
        action = next(a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                      and (a.parameters.get('typed') or {}).get('source') == INCARNATION)
        engine._apply_condition(actor, STATE_PREFIX + STATE, action.source_definition_id, actor.entity_id,
            expires_on=expiry, data={'name': STATE, 'label': 'Thousand-Hand Incarnation', 'source_admission': True,
                'ends_if_unconscious': True, 'hundred_hand_extra_after_turn': 0 if data.get('extra_reaction_ready') else 1,
                'numbers': {'cl': data.get('source_cl', 18), 'pb': data.get('source_pb', actor.proficiency_bonus)},
                'remaining_at_entry_num': left.numerator, 'remaining_at_entry_den': left.denominator})


@hook('journey_snapshot_actor')
def separate_incarnation(actor, session, aid, engine):
    from .states import PREFIX as STATE_PREFIX
    if incarnation_action(session.state['actors'][aid]) is None:
        return None
    keys = {key for key, condition in actor.conditions.items() if condition.condition_id == STATE_PREFIX + STATE}
    if not keys:
        return None
    result = actor.model_copy(deep=True)
    result.conditions = {key: condition for key, condition in result.conditions.items() if key not in keys}
    return result


@hook('journey_encounter_settled')
def return_incarnation(session, aid, engine, actor):
    from .states import PREFIX as STATE_PREFIX
    from .effect_durations import parse_round
    if incarnation_action(session.state['actors'][aid]) is None:
        return
    record = incarnation_record(session.state['actors'][aid])
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE_PREFIX + STATE), None)
    left = Fraction(0)
    if held:
        slots = max(1, len(engine.state.initiative_order))
        now = Fraction(engine.state.round_number - 1) * 6 + Fraction(engine.state.current_slot_index * 6, slots)
        if 'remaining_at_entry_num' in held.data:
            left = max(Fraction(0), Fraction(held.data['remaining_at_entry_num'], held.data['remaining_at_entry_den']) - now)
        elif (end := parse_round(held.expires_on)) is not None:
            left = max(Fraction(0), Fraction(end[0] - 1) * 6 + Fraction(end[1] * 6, slots) - now)
    end = session.clock() + left
    from .reaction_economy import grant_unused
    grant = next((row for row in engine.typed_passive_rows.get(aid, [])
                  if row.get('block') == 'reaction_economy' and row.get('feature_id') == INCARNATION
                  and row.get('grant') == 'extra'), None)
    deadline = held.data.get('hundred_hand_extra_after_turn') if held else None
    ready = bool(left and grant is not None and type(deadline) is int and actor.turns_started >= deadline
                 and grant_unused(engine, actor, grant))
    record.update(active=int(bool(left)), expires_num=end.numerator, expires_den=end.denominator,
                  extra_reaction_ready=int(ready), source_pb=int((held.data.get('numbers') or {}).get('pb', actor.proficiency_bonus)) if held else actor.proficiency_bonus,
                  source_cl=int((held.data.get('numbers') or {}).get('cl', 18)) if held else 18)
    sync_incarnation(session, aid)


# Guard and reaction-denial results retain their printed next-turn clock through
# encounter exit. This adapter owns only effects created by this family; it does
# not classify another source's timed state or clear unsupported encounter data.
def timed_results(actor):
    return actor.setdefault('source_states', {}).setdefault(PARENT, {}).setdefault('timed_results', {})


def sync_results(session, aid):
    from ..canonical import canonical_sha256
    actor = session.state['actors'][aid]
    records = timed_results(actor)
    for key, row in list(records.items()):
        left = max(Fraction(0), Fraction(row['expires_num'], row['expires_den']) - session.clock())
        row.update(remaining_num=left.numerator, remaining_den=left.denominator)
        if not left:
            records.pop(key)
            session.emit('MANDALA_RESULT_EXPIRED', aid, source=row['source'], instance=key)
    actor['bundle']['journey_hundred_hand_results'] = deepcopy(records)
    actor['bundle'].pop('bundle_sha256', None)
    actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


def family_timed(model):
    return (model.source_definition_id.startswith(PREFIX) and model.expires_on not in (None, 'UNTIL_REMOVED')
            and not getattr(model, 'condition_id', '').endswith('.state.' + STATE))


@hook('journey_snapshot_actor')
def separate_timed_results(actor, session, aid, engine):
    modifiers = {key for key, m in actor.modifiers.items() if family_timed(m)}
    conditions = {key for key, c in actor.conditions.items() if family_timed(c)}
    if not modifiers and not conditions:
        return None
    copy = actor.model_copy(deep=True)
    copy.modifiers = {key: m for key, m in copy.modifiers.items() if key not in modifiers}
    copy.conditions = {key: c for key, c in copy.conditions.items() if key not in conditions}
    return copy


@hook('journey_encounter_settled')
def retain_timed_results(session, aid, engine, actor):
    candidates = [(kind, key, model) for kind, models in (('modifier', actor.modifiers), ('condition', actor.conditions))
                  for key, model in models.items() if family_timed(model)]
    if not candidates and not saved(session.state['actors'][aid]).get('timed_results'):
        return
    records = timed_results(session.state['actors'][aid])
    records.clear()
    slots = max(1, len(engine.state.initiative_order))
    for kind, models in (('modifier', actor.modifiers), ('condition', actor.conditions)):
        for key, model in models.items():
            if not family_timed(model):
                continue
            bound = model.expires_actor_id or model.source_actor_id
            target = engine.state.actors.get(bound)
            if target is None or bound not in engine.state.initiative_order:
                continue
            # These printed results expire at the next start, not at a new
            # encounter or scene. Preserve the exact fractional slot distance.
            index = engine.state.initiative_order.index(bound)
            delta = (index - engine.state.current_slot_index) % slots
            if delta == 0 and engine.state.current_actor_id == bound:
                delta = slots
            left = Fraction(delta * 6, slots)
            end = session.clock() + left
            document = model.model_dump(mode='json')
            if kind == 'modifier':
                document['value'] = actor.turn_flags.get('_round_mandala_guard_values', {}).get(key, model.value)
            records[key] = {'kind': kind, 'model': json.dumps(document, sort_keys=True), 'source': model.source_definition_id,
                'bound': bound, 'expires_num': end.numerator, 'expires_den': end.denominator,
                'clock_journey': session.state['journey_id']}
    if records or 'journey_hundred_hand_results' in session.state['actors'][aid]['bundle']:
        sync_results(session, aid)


@hook('journey_initialize')
def initialize_results(session, aid):
    actor = session.state['actors'][aid]
    records = saved(actor).get('timed_results')
    if records is None:
        return
    for row in records.values():
        if row.get('clock_journey') != session.state['journey_id']:
            end = session.clock() + Fraction(row['remaining_num'], row['remaining_den'])
            row.update(expires_num=end.numerator, expires_den=end.denominator, clock_journey=session.state['journey_id'])
    sync_results(session, aid)


@hook('journey_elapsed')
def elapsed_results(session, aid, previous, seconds, moving):
    if saved(session.state['actors'][aid]).get('timed_results'):
        sync_results(session, aid)


@hook('match_initialize', priority=-90)
def restore_results(engine):
    from ..gate2_runtime_models import ModifierInstance, ConditionInstance
    from .retained_updates import record_instance_update
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for key, row in bundle.get('journey_hundred_hand_results', {}).items():
            bound = engine.state.actors.get(row['bound'])
            if bound is None or Fraction(row['remaining_num'], row['remaining_den']) <= 0:
                continue
            model = (ModifierInstance if row['kind'] == 'modifier' else ConditionInstance).model_validate(json.loads(row['model']))
            model.expires_on = 'START_OF_SOURCE_NEXT_TURN'
            model.expires_actor_id = bound.entity_id
            model.expires_turn_count = bound.turns_started + 1
            (actor.modifiers if row['kind'] == 'modifier' else actor.conditions)[key] = model
            record_instance_update(engine, actor, row['kind'], key, model)

    from .hundred_hands import reconcile_guard_dormancy
    reconcile_guard_dormancy(engine, 'MODIFIER_APPLIED', {})



def cycle_record(actor):
    return actor.setdefault('source_states', {}).setdefault(PARENT, {}).setdefault('hand_cycle', {})


def sync_hand_cycle(session, aid):
    actor = session.state['actors'][aid]
    if HANDS not in actor['resources'] or not actor['bundle'].get('hundred_hand_profile'):
        return
    sync_incarnation(session, aid)
    record = cycle_record(actor)
    now = session.clock()
    if not record:
        end = now + 6
        record.update(next_num=end.numerator, next_den=end.denominator, clock_journey=session.state['journey_id'])
    elif record['clock_journey'] != session.state['journey_id']:
        end = now + Fraction(record['remaining_num'], record['remaining_den'])
        record.update(next_num=end.numerator, next_den=end.denominator, clock_journey=session.state['journey_id'])
    end = Fraction(record['next_num'], record['next_den'])
    if now >= end:
        cycles = int((now - end) // 6) + 1
        end += 6 * cycles
        snapshot = actor.get('encounter_snapshot', {})
        if journey_level(session, aid) >= 3 and snapshot.get('active', 1):
            before = actor['resources'][HANDS]
            actor['resources'][HANDS] = journey_pb(session, aid) * (2 if journey_incarnation_active(session, aid) else 1)
            session.emit('MANDALA_HANDS_REFRESHED', aid, source=PARENT, cycles=cycles,
                         before=before, after=actor['resources'][HANDS], next_num=end.numerator, next_den=end.denominator)
        if incarnation_action(actor) is not None:
            incarnation_record(actor)['extra_reaction_ready'] = int(journey_incarnation_active(session, aid))
            sync_incarnation(session, aid)
        record.update(next_num=end.numerator, next_den=end.denominator)
    left = end - now
    record.update(remaining_num=left.numerator, remaining_den=left.denominator)


@hook('journey_initialize')
def initialize_hand_cycle(session, aid):
    sync_hand_cycle(session, aid)


@hook('journey_acquired')
def acquire_hand_cycle(session, aid, source, receipt):
    if source == PARENT:
        sync_hand_cycle(session, aid)


@hook('journey_elapsed')
def elapsed_hand_cycle(session, aid, previous, seconds, moving):
    sync_hand_cycle(session, aid)


@hook('journey_encounter_settled')
def resume_hand_cycle(session, aid, engine, actor):
    target = session.state['actors'][aid]
    if HANDS not in target['resources'] or not target['bundle'].get('hundred_hand_profile'):
        return
    slots = max(1, len(engine.state.initiative_order))
    offset = (engine.state.initiative_order.index(aid) - engine.state.current_slot_index) % slots
    if offset == 0 and engine.state.current_actor_id == aid:
        offset = slots
    end = session.clock() + Fraction(offset * 6, slots)
    cycle_record(target).update(next_num=end.numerator, next_den=end.denominator, clock_journey=session.state['journey_id'])
    sync_hand_cycle(session, aid)


@hook('journey_properties')
def normal_hand_properties(session, aid):
    actor = session.state['actors'][aid]
    if actor['bundle'].get('hundred_hand_profile') and incarnation_action(actor) is None:
        return {'battle_hands_maximum': journey_pb(session, aid)}
    return None
