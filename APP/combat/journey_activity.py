"""Native actions in an explicitly entered outside-combat round context.

This is an actor/effect runtime, not an encounter: no initiative, opponent,
victory, match store, combat start or fabricated packet. Native sealed actions,
costs, deterministic rolls, reactions and conditions execute unchanged. The
existing journey owns elapsed time, persistence and authority. Sources opt in
through journey_native_activity; no provider changes legacy journeys.
"""
from copy import deepcopy
import json
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
        from . import ext
        bundles = []
        for aid, actor in session.state['actors'].items():
            bundle = deepcopy(actor['bundle'])
            for pool in bundle['actor_template']['resources']:
                pool['initial'] = actor['resources'].get(pool['resource_id'], pool['initial'])
            from .ext.journey_setup import travel_incapacitation
            bundle['journey_setup'] = {'incapacitated': travel_incapacitation(actor), 'exhaustion': actor['exhaustion']}
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
        from .controller_choices import manual_choice_reactors
        self.typed_ask_reactors = manual_choice_reactors(self, self.typed_control_modes)

    def _check_victory(self):
        """An outside-combat activity has no victory/defeat terminal condition."""


def load(session):
    from .gate2_runtime_models import CombatEvent, RollRecord
    saved = session.state.get('native_activity') or {}
    engine = ActivityEngine(session, state=saved.get('state'))
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
        'rolls': [row.model_dump_json() for row in engine.rolls]}
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
    for aid, native in engine.state.actors.items():
        # Reuse the published source-owned continuation boundary. Timed source
        # ledgers now refer to the post-action journey clock, not stale exports
        # from before an earlier encounter or a previously held resource.
        ext.run_strict('journey_encounter_settled', session, aid, engine, native)
    document = intent if isinstance(intent, dict) else json.loads(intent.model_dump_json())
    record = dict(intent=json.dumps(document, sort_keys=True), events=events,
        rolls=[row.model_dump(mode='json') for row in engine.rolls[roll_start:]],
        pre_state=pre_state, post_state=engine.state.model_dump_json())
    replay_record(record)
    session.emit('NATIVE_ACTIVITY_COMMITTED', document['actor_id'],
        source=document.get('candidate_id', document.get('source_id')),
        **record,
        text='The outside-combat action resolves with its actual rolls and paid costs.')


def commit_utility(session, actor_id, source_id, command, apply):
    """Resolve effects of an already accepted native journey utility command.

    The caller owns validation, consent, source rules and elapsed utility time.
    This shares the real actor runtime and mechanical journal without fabricating
    an action candidate, initiative, combat, or an action-economy payment.
    """
    engine = load(session)
    pre_state = engine.state.model_dump_json()
    first_event, first_roll, before = len(engine.events), len(engine.rolls), cursor(engine)
    document = {'actor_id': actor_id, 'source_id': source_id, 'journey_command': command,
                'revision': session.state['revision']}
    with engine._transaction(source_id, 'journey:utility:' + str(session.state['revision']), actor_id):
        apply(engine)
    save(session, engine, before_cursor=before, event_start=first_event, roll_start=first_roll,
         intent=document, pre_state=pre_state)
    return engine


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
        # An installed human provider must not seize an automatic creature's
        # inline choice. Returning no override retains the native source's
        # ordinary AI/default policy and complete legal option set.
        if engine.typed_control_modes.get(request['reactor_id']) == 'LOCAL_AUTO':
            return None, None
        shown = deepcopy(request)
        chooser = engine.state.actors[request['reactor_id']]
        shown['reactor_name'] = chooser.display_name
        trigger = shown.get('choice_trigger') or {}
        if trigger.get('d20_rewrite_name') and trigger.get('action_name'):
            shown['prompt'] = (f"{trigger['d20_rewrite_name']}: {chooser.display_name} may improve the roll "
                f"for {trigger['action_name']}. Costs {trigger.get('cost') or 'the stated ability cost'}. "
                'Use this ability or decline before the outcome is finalized.')
        raise NeedAnswer(shown)
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
                and row.target_ids == candidate.target_ids and row.destination == candidate.destination
                and row.option_ids == candidate.option_ids), None)
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


def close(session, aid):
    """Export actual instances; completing the partial round prevents free turns."""
    from .ext.journey_setup import encounter_snapshot, journey_incapacitated
    from .journey import require
    require(session.state.get('native_activity') is not None and not session.state.get('native_activity_pending'),
        'Resolve the pending ability choice before ending outside-combat rounds.')
    engine = load(session)
    for actor_id, actor in session.state['actors'].items():
        native = engine.state.actors[actor_id]
        projected = ext.transform('journey_snapshot_actor', native, session, actor_id, engine)
        actor['encounter_snapshot'] = encounter_snapshot(projected)
        ext.run_strict('journey_encounter_settled', session, actor_id, engine, native)
        actor['incapacitated'] = int(journey_incapacitated(actor))
        if not actor['incapacitated'] and 'declared_travel_incapacitated' in actor:
            actor['declared_travel_incapacitated'] = 0
    del session.state['native_activity']
    session.tick(Fraction((len(engine.state.initiative_order) - engine.state.current_slot_index) * 6,
                          len(engine.state.initiative_order)))
    session.emit('NATIVE_ACTIVITY_ENDED', aid,
        text='Outside-combat rounds end. The remaining round time passes; ongoing effects keep only their remaining durations.')
