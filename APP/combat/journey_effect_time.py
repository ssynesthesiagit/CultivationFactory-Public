"""Resolve continued native effect deadlines during ordinary journey time.

Sources supply exact deadlines of actual exported instances. No source means no
engine construction or change to journey behavior. Expiry executes the ordinary
condition/zone subscribers, falling, dice and reactions without creature turns.
The original journey command is retried with its owner's checkpoint answers;
an unanswered attempt commits neither elapsed time nor partial consequences.
"""
from copy import deepcopy
from fractions import Fraction

from . import ext
from .gate2_runtime_models import ActionIntent, ReactionDecision
from .journey_activity import ActivityEngine, NeedAnswer, replay_record, automatic_reaction


def command(session, aid, kind, payload, *, answers=(), intent_id=None):
    before = deepcopy(session.state)
    session.native_time_answers = tuple(answers)
    session.native_time_intent_id = intent_id or f"journey-time:{session.state['journey_id']}:{session.state['revision']}"
    try:
        session.command(aid, kind, payload)
    except NeedAnswer as pause:
        session.state = before
        session.state['native_activity_pending'] = dict(operation='journey_command', actor_id=aid,
            command_kind=kind, payload=deepcopy(payload), answers=list(answers), request=pause.request,
            intent_id=session.native_time_intent_id)
        session.emit('NATIVE_ACTIVITY_CHOICE_REQUIRED', aid, request=pause.request,
            text='Answer the named ability choice before time passes and its consequences resolve.')
    finally:
        session.native_time_answers = ()
        session.native_time_intent_id = None


def advance(session, seconds):
    """Called before the journey clock advances; no initiative or action use."""
    if not seconds or getattr(session, 'native_activity_advancing', False):
        return
    timers = [row for reply in ext.run_strict('journey_native_timers', session) for row in (reply or ())]
    due = [row for row in timers if Fraction(*row['remaining']) <= seconds]
    if not due:
        return
    from .journey import require
    from . import falling, zones
    from .gate3_reducer import enrich_committed_events
    from .ext.journey_setup import encounter_snapshot, encounter_incapacitated
    engine = ActivityEngine(session)
    restored = {}
    for event in engine.events:
        if event.event_type not in ('CONDITION_RESTORED', 'MODIFIER_RESTORED'):
            continue
        kind = 'condition' if event.event_type == 'CONDITION_RESTORED' else 'modifier'
        key = 'instance_id' if kind == 'condition' else 'modifier_id'
        for aid in event.target_ids:
            restored[aid, kind, event.payload['previous_instance_id']] = event.payload[key]
    for row in timers:
        row['runtime_instance_id'] = restored.get((row['actor_id'], row['kind'], row['instance_id']), row['instance_id'])
    actor_id = due[0]['actor_id']
    intent = ActionIntent(intent_id=getattr(session, 'native_time_intent_id', None)
            or f"journey-time:{session.state['journey_id']}:{session.state['revision']}",
        decision_id='system:journey.elapsed', candidate_id='system:journey.elapsed',
        state_version=engine.state.state_version, actor_id=actor_id)
    engine._active_intent = intent
    answers = [ReactionDecision.model_validate(row) for row in getattr(session, 'native_time_answers', ())]
    def provider(request):
        key = tuple(request[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
        matches = [row for row in answers if (row.checkpoint, row.reactor_id, row.reaction_source_id) == key]
        require(len(matches) <= 1, 'Answer each expiry checkpoint once.')
        if matches:
            return matches[0], None
        automatic = automatic_reaction(engine, request)
        if automatic is not None:
            return automatic
        raise NeedAnswer(deepcopy(request))
    engine.set_reaction_provider(provider)
    pre_state, first_event, first_roll = engine.state.model_dump_json(), len(engine.events), len(engine.rolls)
    with engine._transaction('system:journey.elapsed', intent.intent_id, actor_id):
        for row in sorted(due, key=lambda row: (Fraction(*row['remaining']), row['kind'] != 'zone', row['instance_id'])):
            actor = engine.state.actors.get(row['actor_id'])
            require(actor is not None, 'A continued effect must name its actual mapped creature.')
            kind, iid = row['kind'], row['runtime_instance_id']
            # A preceding exact-instance removal may already have ended this
            # dependent effect. A later recreated instance never shares its id.
            if kind == 'condition' and iid in actor.conditions:
                engine._remove_condition_instance(actor, iid, 'system:combat.expiration', expiring=True)
            elif kind == 'modifier' and iid in actor.modifiers:
                engine._remove_modifier_instance(actor, iid, 'system:combat.expiration', expiring=True)
            elif kind == 'zone' and iid in engine.state.zones and engine.state.zones[iid].active:
                zones.remove(engine, engine.state.zones[iid], 'DURATION_EXPIRED')
            elif kind not in ('condition', 'modifier', 'zone'):
                raise ValueError('Unsupported native continuation timer kind')
            falling.settle(engine, 'system:journey.elapsed', intent)
    record = dict(intent=intent.model_dump_json(),
        pre_state=pre_state, post_state=engine.state.model_dump_json(),
        events=list(enrich_committed_events(engine.events[first_event:], post_engine=engine)),
        rolls=[row.model_dump(mode='json') for row in engine.rolls[first_roll:]])
    replay_record(record)
    for aid, actor in session.state['actors'].items():
        native = engine.state.actors[aid]
        projected = ext.transform('journey_snapshot_actor', native, session, aid, engine)
        actor['encounter_snapshot'] = encounter_snapshot(projected)
        actor['incapacitated'] = int(encounter_incapacitated(actor['encounter_snapshot']))
        actor['resources'] = dict(native.resources)
        actor['position'] = native.position.model_dump(mode='json')
        ext.run_strict('journey_encounter_settled', session, aid, engine, native)
    # Surviving instances retain their original exact world deadlines; rebuilding
    # a native model must not round a fractional deadline into extra duration.
    ext.run_strict('journey_native_time_settled', session, timers)
    session.state['native_roll_counter'] = engine.roller.counter
    session.state['native_activity_serial'] = int(engine.state.rules['journey_activity_serial'])
    session.emit('NATIVE_ELAPSED_EFFECTS_COMMITTED', actor_id, **record, timer_references=timers,
        text='The effects end as their durations run out. Any fall, damage, or Reaction resolves before travel continues.')
