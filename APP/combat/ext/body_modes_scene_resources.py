"""Shared native Body scene identity, availability and paid-activation receipts.

Public contract (docs/contracts/body_modes_scene_resources.md):

* `body_mode_profiles(bundle)` providers declare one scene source: exactly one
  profile means this creature owns that Body scene. The default provider below
  derives participation from the compiled Body features, so no family module
  needs to register anything; a family may declare its own narrower source.
* `scene_record` is the creature's live `condition:typed.body_scene` for a
  source, carrying the table-owner scene id and the Source CL at entry. Records
  are evidence for consumers and are never shown to players.
* `effective_body_cl` and `available` read the live cultivation queries and
  any `condition:typed.cultivation_suppression`. A suppression never erases
  anatomy, resources, selection or spent allowances; it only makes the owning
  source unavailable until its exact recorded expiry.
* Suppression is a table-owner fact: it enters through
  `fact_consent_admission.declare_world` on the native journey admission hook
  (`journey_admission`), is carried into an encounter by
  `journey_combat_bundle`, expires on the round/slot clock, never by a rest, a
  rerolled match or a caller-supplied boolean, and is dropped from the
  continuation snapshot (`journey_snapshot_actor`) so the next encounter in the
  same journey re-derives it from the live fact and the current scene.
* `paid_activation_resolved(engine, actor, receipt)` is a strict notification
  derived from real native payment and completion events. Only positive net
  Stamina, the exact owning source and its event ancestry enter a receipt; the
  original action or reaction remains the sole payment authority.

Everything here is JSON and defaults to inert: no profile, no scene, no fact.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from . import hook, query, run_strict

SCENE = 'condition:typed.body_scene'
SUPPRESSION = 'condition:typed.cultivation_suppression'
AUTHORITY = 'system:body_modes_scene_resources'
STAMINA = 'resource:core.stamina'
BODY_PATH = 'tianxia.path.body_refining'
BODY_FEATURES = (BODY_PATH + '.feature.', 'tianxia.subpath.body.')
SUPPRESSION_KINDS = ('cultivation_suppression',)
HIDDEN = (SCENE, SUPPRESSION)


def bundle_of(engine, actor):
    return next((b for b in getattr(engine, 'typed_bundle_documents', ()) or ()
                 if b.get('actor_id') == actor.entity_id), {})


def owned_sources(bundle):
    """Every compiled mechanic id this bundle actually owns."""
    rows = set()
    for key in ('typed_passives', 'typed_reactions'):
        rows.update(row.get('feature_id') for row in bundle.get(key) or () if isinstance(row, dict))
    rows.update(((action.get('parameters') or {}).get('typed') or {}).get('source')
                for action in bundle.get('action_catalog') or ())
    return {row for row in rows if type(row) is str}


def profiles(bundle):
    """One entry per owned scene source; a provider returns a list or None."""
    return [p for reply in query('body_mode_profiles', bundle) for p in (reply or [])]


@hook('body_mode_profiles')
def compiled_body_profile(bundle):
    """Default participation: any compiled Body feature owns the Body scene.

    This is derived data, not a family claim, so every Body Refining creature
    shares the same scene contract without a per-family registration.
    """
    if not any(row.startswith(BODY_FEATURES) for row in owned_sources(bundle)):
        return None
    return [{'source': BODY_PATH, 'name': 'Body Refining'}]


def scene_id(engine):
    """The table-owner scene this encounter belongs to."""
    for bundle in getattr(engine, 'typed_bundle_documents', ()) or ():
        scene = (bundle.get('body_scene') or {}).get('scene_id')
        if scene:
            return str(scene)
    return 'match:' + str(engine.state.match_seed)


def turn_key(engine):
    """TURN_STARTED sequence distinguishes repeated or extra slots of an actor."""
    sequence = next((e.sequence for e in reversed(engine.events) if e.event_type == 'TURN_STARTED'), 0)
    return f'{engine.state.match_seed}:{engine.state.round_number}:{engine.state.current_actor_id}:{sequence}'


def unconscious(actor):
    return (not actor.active or actor.life_state in ('DYING', 'STABLE') or
            any(c.condition_id.rsplit('.', 1)[-1] in ('unconscious', 'life_unconscious', 'dream_sleep')
                for c in actor.conditions.values()))


def source_cl(engine, actor):
    """Compiled Body attainment, before any live suppression."""
    bundle = bundle_of(engine, actor)
    return int(bundle.get('body_mode_level', bundle.get('cl') or 1))


def effective_body_cl(engine, actor):
    values = []
    base = source_cl(engine, actor)
    values.extend(v for v in query('cultivation_effective_cl', engine, actor, BODY_PATH)
                  if type(v) is int and v >= 0)
    for condition in actor.conditions.values():
        if condition.condition_id != SUPPRESSION:
            continue
        data = condition.data
        if data.get('system') in ('body', BODY_PATH, 'all') and type(data.get('effective_cl')) is int:
            values.append(data['effective_cl'])
    return min([base, *values])


def available(engine, actor, feature, level, *, requires_conscious=True):
    """Whether the owning Body source still grants the feature at `level`."""
    if actor is None or (requires_conscious and unconscious(actor)):
        return False
    if effective_body_cl(engine, actor) < level:
        return False
    if any(v is False for v in query('cultivation_feature_available', engine, actor, feature)):
        return False
    for condition in actor.conditions.values():
        if condition.condition_id != SUPPRESSION:
            continue
        data = condition.data
        if data.get('body_remaining_num') == 0:
            continue
        if data.get('feature_id') == feature:
            return False
        if data.get('system') in ('body', BODY_PATH, 'all') and data.get('suppressed') == 1:
            return False
    return True


def scene_record(engine, actor, source):
    return next((c for c in actor.conditions.values()
                 if c.condition_id == SCENE and c.data.get('source') == source), None)


@hook('compile_bundle', priority=100)
def seal_body_level(bundle, info):
    """Cap the compiled Body attainment by its owning Path profile and sheet CL."""
    if not profiles(bundle):
        return
    sheet = info.get('owner_sheet') or {}
    rows = (sheet.get('path_and_subpath') or {}).get('paths') or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    body = next((r for r in rows if isinstance(r, dict) and r.get('path_id') == BODY_PATH), None)
    if body is None:
        return
    level = next((body[key] for key in ('effective_cl', 'attainment', 'owning_path_level')
                  if type(body.get(key)) is int and body[key] >= 0), None)
    if level is None:
        return
    return {**bundle, 'body_mode_level': min(level, int(bundle.get('cl') or 1))}


@hook('match_start', priority=-200)
def initialize_scene(engine):
    """One hidden record per source, for owners only; never another combatant's."""
    scene = scene_id(engine)
    for actor in engine.state.actors.values():
        for profile in profiles(bundle_of(engine, actor)):
            if scene_record(engine, actor, profile['source']) is not None:
                continue
            engine._apply_condition(actor, SCENE, AUTHORITY, actor.entity_id,
                                    expires_on='UNTIL_REMOVED',
                                    data={'source': profile['source'], 'scene_id': scene,
                                          'source_cl': effective_body_cl(engine, actor),
                                          'label': profile.get('name', 'Body') + ' scene'})


@hook('presentation_hidden_conditions')
def private_scene_details(engine, actor):
    """Scene bookkeeping and recorded suppression are never player text."""
    return [c.instance_id for c in actor.conditions.values()
            if c.condition_id in HIDDEN and c.source_definition_id == AUTHORITY] or None


def paid_receipt(engine, actor, source, stop):
    """Net positive Stamina actually spent on `source` inside this transaction."""
    from .ability_source import mechanic_at
    canonical = mechanic_at(engine, source) or source
    events = []
    for event in reversed(engine.events):
        if event.event_type == stop and (stop == 'REACTION_WINDOW_OPENED' or event.actor_id == actor.entity_id):
            break
        events.append(event)
    paid = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == actor.entity_id
            and e.payload.get('resource_id') == STAMINA
            and (mechanic_at(engine, e.source_definition_id) or e.source_definition_id) == canonical
            and int(e.payload.get('amount') or 0) > 0]
    refunds = sum(int(e.payload.get('gained') or e.payload.get('amount') or 0)
                  for e in events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == actor.entity_id
                  and e.payload.get('resource_id') == STAMINA
                  and (mechanic_at(engine, e.source_definition_id) or e.source_definition_id) == canonical)
    amount = sum(int(e.payload['amount']) for e in paid) - refunds
    if amount <= 0:
        return None
    return {'source': canonical, 'paid': amount,
            'payment_sequences': sorted(e.sequence for e in paid),
            'completion_sequence': engine.state.event_sequence, 'turn': turn_key(engine),
            'round': int(engine.state.round_number), 'source_cl': effective_body_cl(engine, actor)}


def notify_paid(engine, actor, source, stop):
    """Notify once per paid transaction, whichever completion route arrives first."""
    if not profiles(bundle_of(engine, actor)):
        return
    receipt = paid_receipt(engine, actor, source, stop)
    if receipt is None:
        return
    key = (receipt['source'], tuple(receipt['payment_sequences']))
    seen = engine.__dict__.setdefault('_body_paid_notified', set())
    if key in seen:
        return
    seen.add(key)
    run_strict('paid_activation_resolved', engine, actor, receipt)


@hook('action_completed', priority=90)
def completed(engine, actor, economy, source):
    notify_paid(engine, actor, source, 'INTENT_ACCEPTED')


@hook('state_event')
def completed_reaction(engine, event):
    if event.event_type != 'REACTION_RESOLVED':
        return
    actor = engine.state.actors.get(event.actor_id)
    if actor is not None:
        notify_paid(engine, actor, event.source_definition_id, 'REACTION_WINDOW_OPENED')


@hook('fact_admission_schema')
def world_schema(session, source, subject, kind):
    """Only a compiled Body owner can receive a Body suppression fact."""
    if source != AUTHORITY or kind not in SUPPRESSION_KINDS:
        return None
    actor = session.state['actors'].get(subject) or {}
    if not profiles(actor.get('bundle') or {}):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'subject_access': True,
            'description': 'A printed source rule, its authority and an explicit effective Body CL.'}


@hook('fact_admission_validate')
def validate_body_fact(session, source, subject, kind, value):
    if source != AUTHORITY or kind not in SUPPRESSION_KINDS:
        return None
    from ..journey import require, integer
    require(type(value.get('source_rule')) is str and bool(value['source_rule'].strip())
            and integer(value.get('source_cl')),
            'Record a printed source rule and its explicit Source CL.')
    require(value.get('system') in ('body', BODY_PATH, 'all')
            and (integer(value.get('effective_cl')) or value.get('suppressed') == 1
                 or type(value.get('feature_id')) is str),
            'Name a complete Body suppression, an effective CL or one specific feature.')
    return True


@hook('journey_admission')
def admit_body_suppression(session, aid, kind, payload, reason):
    """Table-owner declaration: `body_suppression` with its recorded scope."""
    if kind != 'body_suppression':
        return None
    from ..journey import require, integer
    from ..fact_consent_admission import declare_world
    actor = session.state['actors'][aid]
    require(profiles(actor['bundle']), 'This creature owns no Body scene source.')
    require(set(payload) == {'scope', 'value', 'seconds'}, 'Choose a suppression scope, value and duration.')
    require(type(payload['scope']) is str and 0 < len(payload['scope']) <= 240,
            'Name the source scope this suppression belongs to.')
    require(integer(payload['seconds'], 1), 'Choose a positive whole-second duration.')
    expires = int(session.clock()) + payload['seconds']
    receipt = declare_world(session, {'source': AUTHORITY, 'subject': aid,
                                      'kind': SUPPRESSION_KINDS[0], 'scope': payload['scope'],
                                      'value': deepcopy(payload['value']), 'expires_at': expires,
                                      'readers': list(session.state['actors'])})
    session.emit('BODY_SOURCE_ADMITTED', aid, receipt_id=receipt,
                 kind_name=SUPPRESSION_KINDS[0], scope=payload['scope'], reason=reason)
    return True


def live_suppressions(session, aid):
    """Still-live table-owner suppression facts for this creature, in order."""
    from ..fact_consent_admission import read
    scopes = []
    for row in session.state.get('fact_consent_admission', ()):
        if (row['source'], row['subject'], row['kind']) == (AUTHORITY, aid, SUPPRESSION_KINDS[0]):
            if row['scope'] not in scopes:
                scopes.append(row['scope'])
    out = []
    for scope in scopes:
        fact = read(session, AUTHORITY, aid, SUPPRESSION_KINDS[0], scope, aid)
        if fact is None:
            continue
        value = fact['value']
        deadline = (Fraction(value['body_deadline_num'], value['body_deadline_den'])
                    if type(value.get('body_deadline_num')) is int
                    and type(value.get('body_deadline_den')) is int
                    else Fraction(fact['expires_at']))
        if deadline > session.clock():
            out.append(fact)
    return out


@hook('journey_combat_bundle')
def journey_to_combat(bundle, session, aid):
    """Carry the table-owner scene and its live suppression into the encounter."""
    if not profiles(bundle):
        return None
    clock = session.clock()
    facts = live_suppressions(session, aid)
    bundle['body_scene'] = {'scene_id': session.state.get('scene_id') or session.state['journey_id'],
                            'clock_num': clock.numerator, 'clock_den': clock.denominator,
                            'suppressions': [{'scope': f['scope'], 'value': deepcopy(f['value']),
                                              'receipt_id': f['receipt_id'], 'expires_at': f['expires_at'],
                                              'remaining_num': (deadline - clock).numerator,
                                              'remaining_den': (deadline - clock).denominator}
                                             for f in facts
                                             for deadline in [(
                                                 Fraction(f['value']['body_deadline_num'],
                                                          f['value']['body_deadline_den'])
                                                 if type(f['value'].get('body_deadline_num')) is int
                                                 and type(f['value'].get('body_deadline_den')) is int
                                                 else Fraction(f['expires_at']))]]}


@hook('journey_encounter_settled')
def settle_suppression_time(session, aid, engine, actor):
    """Persist encounter-consumed suppression time back to its scene fact."""
    from ..fact_consent_admission import declare_world
    slots = max(1, len(engine.state.initiative_order))
    now_round, now_slot = engine.state.round_number, engine.state.current_slot_index
    now = session.clock()
    for fact in live_suppressions(session, aid):
        condition = next((c for c in actor.conditions.values()
                         if c.condition_id == SUPPRESSION
                         and c.data.get('receipt_id') == fact['receipt_id']), None)
        remaining = Fraction(0)
        if condition is not None:
            elapsed = Fraction(((now_round - condition.data['body_created_round']) * slots
                                + now_slot - condition.data['body_created_slot']) * 6, slots)
            remaining = max(Fraction(0), Fraction(condition.data['body_expires_num'],
                                                   condition.data['body_expires_den']) - elapsed)
        value = deepcopy(fact['value'])
        deadline = now + remaining
        value['body_deadline_num'] = deadline.numerator
        value['body_deadline_den'] = deadline.denominator
        seconds = max(1, (remaining.numerator + remaining.denominator - 1) // remaining.denominator)
        declare_world(session, {'source': AUTHORITY, 'subject': aid,
                                'kind': SUPPRESSION_KINDS[0], 'scope': fact['scope'],
                                'value': value, 'expires_at': int(now) + seconds,
                                'readers': list(fact['readers'])})


@hook('journey_snapshot_actor')
def strip_records(actor, session, aid, engine):
    """Scene and suppression records are re-derived, never imported from a fight."""
    managed = [key for key, condition in actor.conditions.items()
               if condition.condition_id in HIDDEN and condition.source_definition_id == AUTHORITY]
    if not managed:
        return None
    stripped = actor.model_copy(deep=True)
    for key in managed:
        stripped.conditions.pop(key)
    return stripped


@hook('match_start', priority=-190)
def bind_world_sources(engine):
    """Apply each recorded suppression with its exact remaining scene time."""
    for actor in engine.state.actors.values():
        transfer = (bundle_of(engine, actor).get('body_scene') or {})
        for fact in transfer.get('suppressions') or ():
            remaining = Fraction(fact['remaining_num'], fact['remaining_den'])
            if remaining <= 0:
                continue
            engine._apply_condition(actor, SUPPRESSION, AUTHORITY, actor.entity_id,
                                    expires_on='UNTIL_REMOVED',
                                    data={**deepcopy(fact['value']), 'kind': SUPPRESSION_KINDS[0],
                                          'scope': fact['scope'], 'receipt_id': fact['receipt_id'],
                                          'label': 'Recorded cultivation suppression',
                                          'body_expires_num': remaining.numerator,
                                          'body_expires_den': remaining.denominator,
                                          'body_created_round': engine.state.round_number,
                                          'body_created_slot': engine.state.current_slot_index})


@hook('turn_start', priority=-200)
def source_clock(engine, actor):
    """Recorded facts expire on the round/slot clock, never on a rest or reroll."""
    slots = max(1, len(engine.state.initiative_order))
    for subject in engine.state.actors.values():
        for condition in list(subject.conditions.values()):
            data = condition.data
            if 'body_expires_num' not in data:
                continue
            elapsed = Fraction(((engine.state.round_number - data['body_created_round']) * slots
                                + engine.state.current_slot_index - data['body_created_slot']) * 6, slots)
            if elapsed >= Fraction(data['body_expires_num'], data['body_expires_den']):
                engine._remove_condition_instance(subject, condition.instance_id, AUTHORITY, expected=condition)


def journey_available(session, aid, feature, level, *, requires_conscious=True, at=None):
    """Travel-mode availability from the same live facts; no encounter required."""
    actor = session.state['actors'][aid]
    if requires_conscious and actor['incapacitated']:
        return False
    now = session.clock() if at is None else at
    level_now = int(actor['bundle'].get('body_mode_level', actor['bundle'].get('cl') or 1))
    for fact in live_suppressions(session, aid):
        value = fact['value']
        deadline = (Fraction(value['body_deadline_num'], value['body_deadline_den'])
                    if type(value.get('body_deadline_num')) is int
                    and type(value.get('body_deadline_den')) is int
                    else Fraction(fact['expires_at']))
        if deadline <= now:
            continue
        if value.get('feature_id') == feature:
            return False
        if value.get('system') in ('body', BODY_PATH, 'all'):
            if value.get('suppressed') == 1:
                return False
            level_now = min(level_now, int(value.get('effective_cl', level_now)))
    return level_now >= level
