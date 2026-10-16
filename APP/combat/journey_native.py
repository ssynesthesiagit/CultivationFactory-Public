"""Native effect continuation helpers used by Jigoku Brand and journey choices.

These are opt-in helpers, not a second damage/save implementation. Providers
capture a verified encounter, resolve native effects, and commit its results.
The journey command ledger replays the same native rolls and player answers.
"""
from copy import deepcopy
import json

from .journey import require
from .ext import ControllerPause

KEY = 'native_effect_continuation'
PENDING = 'native_effect_choice'


class DecisionNeeded(ControllerPause):
    def __init__(self, request):
        self.request = request


def capture(session, engine):
    from .ext import transform
    from .gate2_runtime_models import ConditionInstance
    state = engine.state.model_copy(deep=True)
    for aid in session.state['actors']:
        state.actors[aid] = transform('journey_snapshot_actor', state.actors[aid], session, aid, engine)
        actor = state.actors[aid]
        snapshot = session.state['actors'][aid].get('encounter_snapshot')
        if snapshot:
            actor.current_hp, actor.maximum_hp = snapshot['current_hp'], snapshot['maximum_hp']
            actor.temporary_hp = snapshot['temporary_hp']
            actor.conditions = {i:ConditionInstance.model_validate_json(row) for i,row in snapshot['conditions'].items()}
            # The validated continuation snapshot admits no encounter modifiers;
            # it already records any explicit GM resolution of such effects.
            actor.modifiers.clear()
            actor.concentration = None
    session.state[KEY] = {'state': state.model_dump_json(),
        'bundles': [json.dumps(b, sort_keys=True) for b in engine.typed_bundle_documents],
        'battlefield': json.dumps(engine.battlefield_document or json.loads(
            (engine.source_root/'combat_gate1/generated/Battlefield.json').read_text())),
        'root': str(engine.source_root), 'counter': engine.roller.counter,
        'round': state.round_number, 'seconds': str(session.clock())}


def load(session, aid):
    from .gate4_engine import Gate4ControllerEngine
    from .gate2_runtime_models import MatchState, ConditionInstance, Position, ActionIntent, ReactionDecision
    from .ext import run_strict
    saved = session.state[KEY]
    state = MatchState.model_validate_json(saved['state'])
    bundles = tuple(json.loads(row) for row in saved['bundles'])
    engine = Gate4ControllerEngine(saved['root'], match_seed=state.match_seed, typed_bundles=bundles,
        battlefield=json.loads(saved['battlefield']), roster_setup={
            'primary_actor_ids': [i for i in state.initiative_order if state.actors[i].primary_combatant],
            'team_by_actor': {i: a.team_id for i, a in state.actors.items()},
            'starting_positions': {i: a.position.model_dump(mode='json') for i, a in state.actors.items()}})
    engine.state = state
    engine.state.terminal_result = None
    # Effect continuation has no combat round limit; it is not another match.
    engine.state.maximum_rounds = max(state.maximum_rounds, state.round_number+1_000_000)
    engine.events.clear()
    engine.rolls.clear()
    engine._gate4_reaction_cache.clear()
    engine.gate4_reaction_decision_records.clear()
    engine.roller.counter = saved['counter']
    engine.state.current_actor_id = aid
    engine.state.current_slot_index = state.initiative_order.index(aid)
    engine.typed_control_modes = {i: a['control_mode'] for i, a in session.state['actors'].items()}
    for who, record in session.state['actors'].items():
        actor = state.actors[who]
        snapshot = record.get('encounter_snapshot')
        if snapshot:
            actor.current_hp, actor.temporary_hp = snapshot['current_hp'], snapshot['temporary_hp']
            actor.active, actor.life_state = bool(snapshot['active']), snapshot['life_state'] or None
            actor.conditions = {i: ConditionInstance.model_validate_json(row) for i, row in snapshot['conditions'].items()}
        actor.position = Position.model_validate(record['position'])
        actor.resources = deepcopy(record['resources'])
    run_strict('journey_native_loaded', session, engine)
    intent = ActionIntent(intent_id='journey:'+str(getattr(session, '_native_revision', session.state['revision'])), decision_id='journey',
        candidate_id='journey', state_version=state.state_version, actor_id=aid)
    engine._active_intent = intent
    engine._active_intent_id = intent.intent_id

    def provider(request):
        key = json.dumps([request[k] for k in ('checkpoint','reactor_id','reaction_source_id')])
        answers = getattr(session, '_native_answers', {})
        if key in answers:
            return ReactionDecision.model_validate(answers[key]), None
        record = session.state['actors'].get(request['reactor_id'])
        if record and record['control_mode'] != 'LOCAL_AUTO':
            raise DecisionNeeded(deepcopy(request))
        spec = request.get('extension_choice')
        if spec:
            preferred = spec.get('preferred_option_ids') or spec['option_ids']
            count = max(1, spec['minimum_selections'])
            options = tuple(preferred[:count]) if spec.get('automatic_use', True) else ()
            decision = ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE' if options else 'DECLINE', option_ids=options)
            return decision, None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='DECLINE'), None

    engine.set_reaction_provider(provider)
    return engine


def commit(session, engine):
    from .ext.journey_setup import encounter_incapacitated
    from .ext.life_state import encounter_death_saves
    from .ext.forged_exhaustion import level
    from .ext import run_strict, transform
    stored = engine.state.model_copy(deep=True)
    for aid, record in session.state['actors'].items():
        actor = engine.state.actors[aid]
        projected = transform('journey_snapshot_actor', actor, session, aid, engine)
        stored.actors[aid] = projected
        # Native-generated timed follow-ups keep their exact native clocks in
        # this opted-in continuation. The import subscriber rebases round clocks
        # and retains creature turn counters at the next encounter boundary.
        record['encounter_snapshot'] = {'current_hp':projected.current_hp,'maximum_hp':projected.maximum_hp,
            'temporary_hp':projected.temporary_hp,'active':int(projected.active),'life_state':projected.life_state or '',
            'conditions':{i:c.model_dump_json() for i,c in projected.conditions.items()},
            'death_saves':encounter_death_saves(projected)}
        record['exhaustion'] = level(projected)
        record['incapacitated'] = int(encounter_incapacitated(record['encounter_snapshot']))
        record['resources'] = {k: int(v) for k, v in actor.resources.items()}
    saved = session.state[KEY]
    saved['state'], saved['counter'] = stored.model_dump_json(), engine.roller.counter
    for event in engine.events:
        session.emit('NATIVE_EFFECT_EVENT', event.actor_id or '', event=event.model_dump_json())
        if event.event_type == 'DAMAGE_COMMITTED':
            for aid in event.target_ids:
                run_strict('journey_native_damage', session, aid, event)


def answer_key(request):
    return json.dumps([request[k] for k in ('checkpoint','reactor_id','reaction_source_id')])
