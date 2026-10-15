"""Native actions in an explicitly entered outside-combat round context.

This is an actor/effect runtime, not an encounter: no initiative, opponent,
victory, match store, combat start or fabricated packet. Native sealed actions,
costs, deterministic rolls, reactions and conditions execute unchanged. The
existing journey owns elapsed time, persistence and authority. Sources opt in
through journey_native_activity; no provider changes legacy journeys.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .gate4_engine import Gate4ControllerEngine
from .gate2_runtime_models import MatchState, ActionIntent, ReactionDecision
from .canonical import canonical_sha256
from . import ext


def initial_state(engine, actors, order, seed):
    saved = engine.activity_context.get('state')
    if saved:
        state = MatchState.model_validate_json(saved)
        if set(state.actors) != set(actors) or state.match_seed != seed or state.terminal_result is not None:
            raise ValueError('The native activity continuation does not match this journey')
        engine.roller.counter = state.roll_counter
        return state
    from .gate2_engine import GATE1_REGISTRY_SHA256
    return MatchState(match_id='activity:' + canonical_sha256({'seed': seed, 'actors': list(order)})[:24],
        match_seed=seed, gate1_registry_snapshot_sha256=GATE1_REGISTRY_SHA256,
        mechanics_lock_sha256=engine.mechanics_lock_sha256,
        universal_defaults_lock_sha256=engine.universal_defaults_lock_sha256,
        initiative_order=list(order), current_actor_id=order[0], actors=actors, maximum_rounds=1000000000,
        relations=engine.activity_context.get('relations'), rules=engine.activity_context.get('rules', {}))


class ActivityEngine(Gate4ControllerEngine):
    """A configured native engine subclass; no runtime class/method patches."""
    def __init__(self, session, *, state=None):
        self.activity_context = {'state': state}
        if state is None:
            for aid in session.state['actors']:
                ext.run_strict('journey_encounter_prepare', session, aid)
            from .fact_consent_admission import read
            from .relation_models import Relations
            aid = next(iter(session.state['actors']))
            receipt = read(session, 'system:journey.activity', aid, 'relations', session.state['journey_id'], aid)
            if receipt is not None:
                relations = Relations.model_validate(receipt['value'])
                involved = set(relations.actors) | {right for pairs in relations.actors.values() for right in pairs}
                if relations.teams or not involved <= set(session.state['actors']) or set(receipt['readers']) != set(session.state['actors']):
                    raise ValueError('Declare public relationships only between the mapped creatures')
                self.activity_context.update(relations=relations,
                    rules={'journey_relationship_receipt': receipt['receipt_id']})
        bundles = []
        for aid, actor in session.state['actors'].items():
            bundle = deepcopy(actor['bundle'])
            for pool in bundle['actor_template']['resources']:
                pool['initial'] = actor['resources'].get(pool['resource_id'], pool['initial'])
            bundle['journey_setup'] = {'incapacitated': actor['incapacitated'], 'exhaustion': actor['exhaustion']}
            if actor.get('encounter_snapshot') is not None:
                bundle['journey_setup']['encounter_snapshot'] = deepcopy(actor['encounter_snapshot'])
            if state is None:
                for supplied in ext.run_strict('journey_combat_setup', session, aid):
                    if set(bundle['journey_setup']) & set(supplied):
                        raise ValueError('Native activity setup providers must own distinct fields')
                    bundle['journey_setup'].update(supplied)
            bundles.append(bundle)
        order = list(session.state['actors'])
        super().__init__(Path(__file__).resolve().parents[1], match_seed=session.state['journey_id'],
            typed_bundles=tuple(bundles), battlefield=session.state['battlefield'],
            roster_setup={'primary_actor_ids': order,
                # Travelling together establishes neither alliance nor consent.
                'team_by_actor': {aid: 'team:neutral' for aid in order},
                'starting_positions': {aid: actor['position'] for aid, actor in session.state['actors'].items()}})
        self.typed_control_modes = {aid: actor['control_mode'] for aid, actor in session.state['actors'].items()}

    def _check_victory(self):
        """An outside-combat activity has no victory/defeat terminal condition."""


def load(session):
    from .gate2_runtime_models import CombatEvent, RollRecord
    saved = session.state.get('native_activity') or {}
    engine = ActivityEngine(session, state=saved.get('state'))
    if saved.get('unstarted_turn'):
        engine.activity_context['unstarted_turn'] = True
    if saved:
        engine.events = [CombatEvent.model_validate_json(row) for row in saved['events']]
        engine.rolls = [RollRecord.model_validate_json(row) for row in saved['rolls']]
    engine._persistent_match_created = False
    return engine


def cursor(engine):
    return (engine.state.round_number - 1) * len(engine.state.initiative_order) + engine.state.current_slot_index


def replay_record(record):
    """Pure native mechanical replay of one committed outside-combat action."""
    from .gate3_reducer import Gate3EventReducer, canonical_state_sha256
    previous = MatchState.model_validate_json(record['pre_state'])
    expected = MatchState.model_validate_json(record['post_state'])
    result = Gate3EventReducer().apply_events(previous, record['events'])
    result.state_version = expected.state_version
    result.roll_counter = expected.roll_counter
    if canonical_state_sha256(result) != canonical_state_sha256(expected):
        raise ValueError('Outside-combat mechanical replay does not match committed state')
    return result


def save(session, engine, *, before_cursor, event_start, roll_start, intent, pre_state):
    from .gate3_reducer import enrich_committed_events
    # Same native event enrichment as combat persistence: cold replay consumes
    # exact post-state snapshots, never re-runs a roll or payment on reopening.
    events = list(enrich_committed_events(engine.events[event_start:], post_engine=engine))
    session.state['native_activity'] = {'state': engine.state.model_dump_json(),
        'events': [row.model_dump_json() for row in engine.events],
        'rolls': [row.model_dump_json() for row in engine.rolls],
        'unstarted_turn': int(bool(engine.activity_context.get('unstarted_turn')))}
    for aid, actor in session.state['actors'].items():
        native = engine.state.actors[aid]
        actor['resources'] = dict(native.resources)
        actor['position'] = native.position.model_dump(mode='json')
    delta = cursor(engine) - before_cursor
    if delta:
        session.native_activity_advancing = True
        try:
            session.tick(Fraction(delta * 6, len(engine.state.initiative_order)))
        finally:
            session.native_activity_advancing = False
    record = dict(intent=intent.model_dump_json(), events=events,
        rolls=[row.model_dump(mode='json') for row in engine.rolls[roll_start:]],
        pre_state=pre_state, post_state=engine.state.model_dump_json())
    replay_record(record)
    session.emit('NATIVE_ACTIVITY_COMMITTED', intent.actor_id, source=intent.candidate_id,
        **record,
        text='The outside-combat action resolves with its actual rolls and paid costs.')


class NeedAnswer(ext.ControllerPause):
    def __init__(self, request):
        self.request = request


def act(session, aid, payload, *, collected_answers=()):
    from . import ext
    from .journey import require
    require(session.state['phase'] == 'travel' and set(payload) == {'candidate_id'}
            and isinstance(payload.get('candidate_id'), str), 'Choose an offered outside-combat action.')
    engine = load(session)
    require(aid == engine.state.current_actor_id, 'Wait for this creature’s outside-combat turn.')
    answers = [ReactionDecision.model_validate(row) for row in collected_answers]
    def provider(request):
        key = tuple(request[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
        rows = [answer for answer in answers if (answer.checkpoint, answer.reactor_id, answer.reaction_source_id) == key]
        if len(rows) > 1:
            raise ValueError('Answer each native checkpoint once')
        if rows:
            return rows[0], None
        raise NeedAnswer(deepcopy(request))
    engine.set_reaction_provider(provider)
    before_cursor, first_event, first_roll = cursor(engine), len(engine.events), len(engine.rolls)
    pre_state = engine.state.model_dump_json()
    candidate = next((row for row in engine.legal_candidates() if row.candidate_id == payload['candidate_id']), None)
    require(candidate is not None and candidate.actor_id == aid, 'Refresh the legal outside-combat actions.')
    intent_id = (session.state.get('native_activity_pending') or {}).get('intent_id') or f"journey:{session.state['revision']}:{candidate.candidate_id}"
    intent = ActionIntent(intent_id=intent_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=engine.state.state_version, actor_id=aid, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=candidate.option_ids,
        reaction_decisions=tuple(answers))
    try:
        # Source start-of-turn decisions use the same actual intent and native
        # checkpoint transport before the first action, rather than a GM flag.
        if engine.state.actors[aid].turns_started == 0:
            engine._active_intent = intent
            with engine._transaction('system:journey.activity', intent.intent_id + ':start', aid):
                engine._system_start_turn(initial=True)
            bound = next((row for row in engine.legal_candidates()
                if row.source_definition_id == candidate.source_definition_id and row.kind == candidate.kind
                and row.target_ids == candidate.target_ids and row.destination == candidate.destination), None)
            require(bound is not None, 'The start-of-turn effects changed this action; refresh its legal choices.')
            intent = intent.model_copy(update={'state_version': engine.state.state_version,
                'candidate_id': bound.candidate_id, 'decision_id': bound.decision_id})
        engine.execute_intent(intent)
    except (NeedAnswer, ext.ControllerPause) as pause:
        request = getattr(pause, 'request', None)
        if request is None:
            raise
        # The attempt is discarded; no effects, rolls or costs are committed.
        session.state['native_activity_pending'] = {'actor_id': aid, 'candidate_id': payload['candidate_id'],
            'intent_id': intent_id, 'request': request, 'answers': [row.model_dump(mode='json') for row in answers]}
        session.emit('NATIVE_ACTIVITY_CHOICE_REQUIRED', aid, request=request,
            text='Answer the named ability’s native choice before the action resolves.')
        return
    session.state.pop('native_activity_pending', None)
    save(session, engine, before_cursor=before_cursor, event_start=first_event, roll_start=first_roll, intent=intent,
         pre_state=pre_state)


def enabled(session):
    from . import ext
    return any(answer is True for answer in ext.query('journey_native_activity', session))


def procedure(session, aid, payload, *, collected_answers=()):
    """Resolve one registered source's non-action procedure, with native replay.

    Source handlers validate an actual obligation and its timing/ownership;
    registration never grants an action, a turn, a power or an automatic result.
    This permits printed ending saves even for unconscious creatures. Choices
    pause atomically, exactly as ordinary native activity intents do.
    """
    from .journey import require
    require(session.state['phase'] == 'travel' and aid in session.state['actors']
        and set(payload) == {'source', 'procedure'} and all(type(v) is str and v for v in payload.values()),
        'Choose a registered source’s actual outside-combat procedure.')
    require(not session.state.get('native_activity'), 'Finish outside-combat rounds before resolving a separate source procedure.')
    engine = load(session)
    engine.activity_context['unstarted_turn'] = True
    answers = [ReactionDecision.model_validate(row) for row in collected_answers]
    def provider(request):
        key = tuple(request[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
        matching = [a for a in answers if (a.checkpoint, a.reactor_id, a.reaction_source_id) == key]
        require(len(matching) <= 1, 'Answer each source-procedure checkpoint once.')
        if matching:
            return matching[0], None
        raise NeedAnswer(deepcopy(request))
    engine.set_reaction_provider(provider)
    identity = (session.state.get('native_activity_pending') or {}).get('intent_id') or f"journey:{session.state['revision']}:{aid}:{payload['source']}:{payload['procedure']}"
    intent = ActionIntent(intent_id=identity, decision_id=identity,
        candidate_id='procedure:' + payload['source'] + ':' + payload['procedure'],
        actor_id=aid, state_version=engine.state.state_version, reaction_decisions=tuple(answers))
    engine._active_intent = intent
    pre_state, event_start, roll_start = engine.state.model_dump_json(), len(engine.events), len(engine.rolls)
    try:
        with engine._transaction(payload['source'], identity, aid):
            claimed = ext.run_strict('journey_native_procedure', engine, engine.state.actors[aid], payload['source'], payload['procedure'], intent)
            require(claimed == [True], 'Exactly one acquired source must validate and resolve this actual procedure.')
    except (NeedAnswer, ext.ControllerPause) as pause:
        request = getattr(pause, 'request', None)
        if request is None:
            raise
        session.state['native_activity_pending'] = {'actor_id': aid, 'procedure': deepcopy(payload),
            'intent_id': identity, 'request': request, 'answers': [a.model_dump(mode='json') for a in answers]}
        session.emit('NATIVE_ACTIVITY_CHOICE_REQUIRED', aid, request=request,
            text='Answer the source’s printed procedure choice before it resolves.')
        return
    session.state.pop('native_activity_pending', None)
    save(session, engine, before_cursor=cursor(engine), event_start=event_start, roll_start=roll_start,
         intent=intent, pre_state=pre_state)
    # No round or turn was started by this non-action procedure.
    close(session, aid, round_started=False)


def close(session, aid, *, round_started=True):
    """Export actual instances; completing the partial round prevents free turns."""
    from .ext.journey_setup import encounter_snapshot, encounter_incapacitated
    from .journey import require
    require(session.state.get('native_activity') is not None and not session.state.get('native_activity_pending'),
        'Resolve the pending ability choice before ending outside-combat rounds.')
    engine = load(session)
    for actor_id, actor in session.state['actors'].items():
        native = engine.state.actors[actor_id]
        projected = ext.transform('journey_snapshot_actor', native, session, actor_id, engine)
        actor['encounter_snapshot'] = encounter_snapshot(projected)
        actor['incapacitated'] = int(encounter_incapacitated(actor['encounter_snapshot']))
        ext.run_strict('journey_encounter_settled', session, actor_id, engine, native)
    del session.state['native_activity']
    if round_started:
        session.tick(Fraction((len(engine.state.initiative_order) - engine.state.current_slot_index) * 6,
                              len(engine.state.initiative_order)))
    session.emit('NATIVE_ACTIVITY_ENDED', aid,
        text=('Outside-combat rounds end. The remaining round time passes; ongoing effects keep only their remaining durations.'
              if round_started else 'The non-action source procedure resolves without starting a turn or advancing the round clock.'))
