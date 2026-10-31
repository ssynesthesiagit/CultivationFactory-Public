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

Shared public consumers: qi_path and mgr_reserve_tribulation_vessel_gather_calamity
use effective_cl, available, qualified_source, journey_effective_cl,
journey_available and turn_key. Availability-only Qi profiles acquire no Body
scene or paid-Stamina participation. Facts retain one admission history and
main's rational deadline settlement, never a parallel source-state authority.
Everything here is JSON and defaults to inert: no profile, no scene, no fact.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from weakref import WeakKeyDictionary
from . import hook, query, run_strict

SCENE = 'condition:typed.body_scene'
SUPPRESSION = 'condition:typed.cultivation_suppression'
AUTHORITY = 'system:body_modes_scene_resources'
STAMINA = 'resource:core.stamina'
BODY_PATH = 'tianxia.path.body_refining'
BODY_FEATURES = (BODY_PATH + '.feature.', 'tianxia.subpath.body.')
QI_PATH = 'tianxia.path.qi_cultivation'
QUALIFIED = 'condition:typed.qualified_body_source'
SOURCE_KINDS = ('cultivation_suppression', 'qualified_source')
SUPPRESSION_KINDS = SOURCE_KINDS[:1]
HIDDEN = (SCENE, SUPPRESSION, QUALIFIED)

# ``technique_used`` runs inside one foreground typed Action, before that same
# Action's ``resolution_final``. This marker bridges the two, so it is
# activation-local transient state: it is keyed weakly by the engine that runs
# both hooks, is never serialized and never part of fight state, and
# ``activation_end`` discards it. A table commit plus cold reload cannot happen
# between the two hooks, so a reloaded fight starts with no marker and cannot
# replay an earlier use's paid notification.
_RESOLVED_USES: WeakKeyDictionary = WeakKeyDictionary()


def _resolved_uses(engine, *, create=False):
    try:
        if create:
            return _RESOLVED_USES.setdefault(engine, set())
        return _RESOLVED_USES.get(engine) or set()
    except TypeError:
        # A projected engine that cannot be weak-keyed keeps no marker; the
        # native hooks below then stay inert rather than raising.
        return set()


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


def profiles(bundle, *, availability=False):
    """Owned scene sources, or all source profiles for availability queries.

    Qi providers opt into the same fact owner without acquiring a Body scene.
    The automatic compiled Body profile remains the default.
    """
    return [p for reply in query('body_mode_profiles', bundle) for p in (reply or [])
            if availability or not p.get('availability_only')]


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


def path_systems(path_id):
    """Accepted declaration aliases for one owning cultivation Path."""
    return {'all', path_id, 'qi' if path_id == QI_PATH else 'body'}


def effective_cl(engine, actor, path_id, compiled_level):
    """Shared Path reader used by Body consumers and Tribulation Vessel."""
    values = [v for v in query('cultivation_effective_cl', engine, actor, path_id)
              if type(v) is int and v >= 0]
    for condition in actor.conditions.values():
        data = condition.data
        if condition.condition_id != SUPPRESSION or data.get('system') not in path_systems(path_id):
            continue
        if data.get('suppressed') == 1:
            values.append(0)
        if type(data.get('effective_cl')) is int:
            values.append(data['effective_cl'])
    return min([compiled_level, *values])


def effective_body_cl(engine, actor):
    """Compiled Body attainment folded with the same live source facts."""
    return effective_cl(engine, actor, BODY_PATH, source_cl(engine, actor))


def available(engine, actor, feature, level, *, requires_conscious=True,
              path_id=BODY_PATH, compiled_level=None):
    """Owning-Path availability; suppression never changes the chassis."""
    if actor is None or (requires_conscious and unconscious(actor)):
        return False
    base = source_cl(engine, actor) if compiled_level is None else compiled_level
    if effective_cl(engine, actor, path_id, base) < level:
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
        if data.get('system') in path_systems(path_id) and data.get('suppressed') == 1:
            return False
    return True


def qualified_source(engine, actor, source_actor):
    """Latest live table-owner source declaration, never inferred hostility."""
    rows = [c.data for c in actor.conditions.values()
            if c.condition_id == QUALIFIED and c.data.get('kind') == 'qualified_source'
            and c.data.get('source_actor_id') == source_actor.entity_id]
    return max(rows, key=lambda row: row.get('sequence', 0), default=None)


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
            saved = ((bundle_of(engine, actor).get('body_scene') or {}).get('records') or {}).get(profile['source'], {})
            retained = deepcopy(saved) if saved.get('scene_id') == scene else {}
            engine._apply_condition(actor, SCENE, AUTHORITY, actor.entity_id,
                                    expires_on='UNTIL_REMOVED',
                                    data={**retained, 'source': profile['source'], 'scene_id': scene,
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


@hook('technique_used',priority=10000)
def resolved_typed_use(ctx):
    # This native notification is absent for a pre-resolution veto/counter.
    # Retain only its causal identity; payment still comes from actual events.
    if ctx.intent is None or not profiles(bundle_of(ctx.engine,ctx.actor)):return
    _resolved_uses(ctx.engine,create=True).add((ctx.actor.entity_id,ctx.action.source_definition_id,ctx.intent.intent_id))


@hook('resolution_final',priority=10000)
def completed_typed_use(engine,actor,action,candidate,intent):
    key=(actor.entity_id,action.source_definition_id,intent.intent_id)
    resolved=_resolved_uses(engine)
    if key not in resolved:return
    resolved.discard(key)
    # Unlike action_completed, this native boundary still runs when this use
    # ended combat. Combat ending is not an implicit end of the source scene.
    notify_paid(engine,actor,action.source_definition_id,'INTENT_ACCEPTED')


@hook('activation_end',priority=10000)
def clear_resolved_typed_use(engine,actor,action,candidate,intent):
    _resolved_uses(engine).discard((actor.entity_id,action.source_definition_id,intent.intent_id))


@hook('action_completed', priority=90)
def completed(engine, actor, economy, source):
    action = engine.action_catalog.get(source)
    if action is not None and action.resolution_kind == 'TYPED':
        return
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
    """Only an owned scene or availability profile admits cultivation facts."""
    if source != AUTHORITY or kind not in SOURCE_KINDS:
        return None
    actor = session.state['actors'].get(subject) or {}
    if not profiles(actor.get('bundle') or {}, availability=True):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'subject_access': True,
            'description': 'A printed source rule, its Source CL and explicit cultivation scope.'}


@hook('fact_admission_validate')
def validate_body_fact(session, source, subject, kind, value):
    if source != AUTHORITY or kind not in SOURCE_KINDS:
        return None
    from ..journey import require, integer
    require(type(value.get('source_rule')) is str and bool(value['source_rule'].strip())
            and integer(value.get('source_cl')),
            'Record a printed source rule and its explicit Source CL.')
    if kind == 'cultivation_suppression':
        require(value.get('system') in ('body', BODY_PATH, 'qi', QI_PATH, 'all')
                and (integer(value.get('effective_cl')) or value.get('suppressed') == 1
                     or type(value.get('feature_id')) is str),
                'Name complete cultivation suppression, an effective CL or one specific feature.')
    else:
        require(value.get('source_actor_id') in session.state['actors']
                and type(value.get('hostile')) is int and value['hostile'] in (0, 1)
                and type(value.get('staged')) is int and value['staged'] in (0, 1),
                'Name the actual source, hostility and staged-interaction facts.')
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
    deadline = session.clock() + payload['seconds']
    value = deepcopy(payload['value'])
    value['body_deadline_num'] = deadline.numerator
    value['body_deadline_den'] = deadline.denominator
    expires = max((deadline.numerator + deadline.denominator - 1) // deadline.denominator,
                  int(session.clock()) + 1)
    receipt = declare_world(session, {'source': AUTHORITY, 'subject': aid,
                                      'kind': SUPPRESSION_KINDS[0], 'scope': payload['scope'],
                                      'value': value, 'expires_at': expires,
                                      'readers': list(session.state['actors'])})
    session.emit('BODY_SOURCE_ADMITTED', aid, receipt_id=receipt,
                 kind_name=SUPPRESSION_KINDS[0], scope=payload['scope'], reason=reason)
    return True


def fact_deadline(fact):
    """Main's exact deadline, with integer expiry for ordinary world inputs."""
    value = fact['value']
    return (Fraction(value['body_deadline_num'], value['body_deadline_den'])
            if type(value.get('body_deadline_num')) is int
            and type(value.get('body_deadline_den')) is int
            else Fraction(fact['expires_at']))


def live_source_facts(session, aid, *, kind=None):
    """Latest live facts from the single admission history; no shadow state."""
    from ..fact_consent_admission import read
    identities = dict.fromkeys((row['kind'], row['scope'])
                              for row in session.state.get('fact_consent_admission', ())
                              if row['source'] == AUTHORITY and row['subject'] == aid
                              and row['kind'] in SOURCE_KINDS
                              and (kind is None or row['kind'] == kind))
    out = []
    for fact_kind, scope in identities:
        fact = read(session, AUTHORITY, aid, fact_kind, scope, aid)
        if fact is not None and fact_deadline(fact) > session.clock():
            out.append(fact)
    return out


def live_suppressions(session, aid):
    """Body and Qi suppressions use the same authority and rational clock."""
    return live_source_facts(session, aid, kind='cultivation_suppression')


@hook('journey_command')
def accept_world_state(session, aid, kind, payload):
    """Select an existing world fact; never copy it into a second authority."""
    if kind not in ('body_source_state', 'cultivation_source_state'):
        return None
    from ..journey import require
    require(set(payload) == {'scope', 'kind'}, 'Choose a declared source record and its kind.')
    require(any(f['kind'] == payload['kind'] and f['scope'] == payload['scope']
                for f in live_source_facts(session, aid)),
            'The table owner must first record this source and its authority.')
    session.emit('BODY_SOURCE_ADMITTED', aid, kind_name=payload['kind'], scope=payload['scope'])
    run_strict('journey_state_changed', session, aid)
    return True


@hook('journey_combat_bundle')
def journey_to_combat(bundle, session, aid):
    """Carry the one scene and its live source facts into the encounter."""
    if not profiles(bundle, availability=True):
        return None
    clock = session.clock()
    state = session.state['actors'][aid].get('source_states', {}).get(AUTHORITY, {})
    bundle['body_scene'] = {
        'scene_id': session.state.get('scene_id') or session.state['journey_id'],
        'clock_num': clock.numerator, 'clock_den': clock.denominator,
        'records': deepcopy(state.get('records', {})),
        'sources': [{**deepcopy(f),
                     'remaining_num': (fact_deadline(f) - clock).numerator,
                     'remaining_den': (fact_deadline(f) - clock).denominator}
                    for f in live_source_facts(session, aid)]}


@hook('journey_encounter_settled')
def settle_suppression_time(session, aid, engine, actor):
    """Main's rational settlement applies to every admitted cultivation source."""
    from ..fact_consent_admission import declare_world
    owned = profiles(bundle_of(engine, actor))
    if owned:
        state = session.state['actors'][aid].setdefault('source_states', {}).setdefault(AUTHORITY, {})
        state['records'] = {p['source']: deepcopy(record.data) for p in owned
                            if (record := scene_record(engine, actor, p['source'])) is not None}
    slots = max(1, len(engine.state.initiative_order))
    now_round, now_slot = engine.state.round_number, engine.state.current_slot_index
    now = session.clock()
    for fact in live_source_facts(session, aid):
        condition = next((c for c in actor.conditions.values()
                          if c.condition_id in (SUPPRESSION, QUALIFIED)
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
        expires = max((deadline.numerator + deadline.denominator - 1) // deadline.denominator,
                      int(now) + 1)
        declare_world(session, {'source': AUTHORITY, 'subject': aid,
                                'kind': fact['kind'], 'scope': fact['scope'],
                                'value': value, 'expires_at': expires,
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
    """Apply each latest fact once, using main's exact remaining scene time."""
    for actor in engine.state.actors.values():
        transfer = bundle_of(engine, actor).get('body_scene') or {}
        for fact in transfer.get('sources') or ():
            remaining = Fraction(fact['remaining_num'], fact['remaining_den'])
            if remaining <= 0:
                continue
            condition_id = SUPPRESSION if fact['kind'] == 'cultivation_suppression' else QUALIFIED
            engine._apply_condition(actor, condition_id, AUTHORITY, actor.entity_id,
                                    expires_on='UNTIL_REMOVED',
                                    data={**deepcopy(fact['value']), 'kind': fact['kind'],
                                          'scope': fact['scope'], 'receipt_id': fact['receipt_id'],
                                          'sequence': fact['sequence'],
                                          'label': 'Recorded cultivation source state',
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


def journey_effective_cl(session, aid, path_id, compiled_level, *, at=None):
    """Travel-mode Path CL from the same live facts, not copied source states."""
    now = session.clock() if at is None else at
    level = compiled_level
    for fact in live_suppressions(session, aid):
        if fact_deadline(fact) <= now:
            continue
        value = fact['value']
        if value.get('system') in path_systems(path_id):
            if value.get('suppressed') == 1:
                return 0
            level = min(level, int(value.get('effective_cl', level)))
    return level


def journey_available(session, aid, feature, level, *, requires_conscious=True,
                      at=None, path_id=BODY_PATH, compiled_level=None):
    """Travel-mode availability from the same live facts; no encounter needed."""
    actor = session.state['actors'][aid]
    if requires_conscious and actor['incapacitated']:
        return False
    now = session.clock() if at is None else at
    base = (int(actor['bundle'].get('body_mode_level', actor['bundle'].get('cl') or 1))
            if compiled_level is None else compiled_level)
    for fact in live_suppressions(session, aid):
        if fact_deadline(fact) > now and fact['value'].get('feature_id') == feature:
            return False
    return journey_effective_cl(session, aid, path_id, base, at=at) >= level


@hook('journey_time_boundaries')
def source_time_boundaries(session, before, after):
    """Split elapsed consumers at the single authority's rational deadlines."""
    return sorted({fact_deadline(fact) for aid in session.state['actors']
                   for fact in live_source_facts(session, aid)
                   if before < fact_deadline(fact) <= after})
