"""Transactional native effect choices; absent capture is inert."""
from contextlib import contextmanager
from copy import deepcopy
from . import hook
from ..journey import require
from ..journey_native import KEY, PENDING, DecisionNeeded, answer_key


@hook('journey_command_scope')
def scope(session, aid, kind, payload):
    if KEY not in session.state:
        return None
    return transaction(session, aid, kind, payload)


@contextmanager
def transaction(session, aid, kind, payload):
    before = deepcopy(session.state)
    session._native_occurrences = {}
    try:
        yield
    except DecisionNeeded as pause:
        session.state.clear()
        session.state.update(before)
        original = getattr(session, '_native_original', {'actor_id':aid, 'kind':kind, 'payload':deepcopy(payload),
                                                        'revision':before['revision']})
        session.state[PENDING] = {'original':original, 'answers':deepcopy(getattr(session, '_native_answers', {})),
                                  'request':deepcopy(pause.request)}
        session.emit('NATIVE_EFFECT_CHOICE_REQUIRED', pause.request['reactor_id'],
                     source=pause.request['reaction_source_id'])
    finally:
        session.__dict__.pop('_native_original', None)
        session.__dict__.pop('_native_answers', None)
        session.__dict__.pop('_native_revision', None)
        session.__dict__.pop('_native_occurrences', None)


@hook('journey_before_command', priority=-100)
def clear_pending(session, aid, kind, payload):
    if kind == 'finish' and KEY in session.state:
        state = json_state(session)
        # Only creatures continuing with this journey hold its clocks. Summons or
        # other captured encounter actors cannot expire here and must not veto Finish.
        require(not any(row.get('expires_on') not in (None,'UNTIL_REMOVED')
                        for aid, actor in state['actors'].items() if aid in session.state['actors']
                        for row in [*actor['conditions'].values(), *actor.get('modifiers',{}).values()]),
                'Resolve the timed ongoing effects before finishing this journey. Continue their clock or enter combat first.')
    if kind in ('native_effect_answer', 'native_effect_pick') or PENDING not in session.state:
        return
    # A reached damage/save checkpoint has already disclosed its native roll.
    # Resolve it before another action; otherwise changing plans can erase the
    # triggering damage after seeing it. All later legal options remain offered.
    require(False, 'Answer the ongoing Burning Brand damage or saving-throw choice before another action. '
                   'Extinguishing, travel and combat entry remain available after that response.')


@hook('journey_command')
def answer(session, aid, kind, payload):
    if kind not in ('native_effect_answer', 'native_effect_pick'): return None
    from ..gate2_runtime_models import ReactionDecision
    pending = session.state.get(PENDING)
    require(pending is not None and aid == pending['request']['reactor_id'], 'Only the creature facing this choice can answer it.')
    if kind == 'native_effect_pick':
        spec = pending['request'].get('extension_choice') or {}
        require(set(payload) == {'option'} and payload['option'] in spec.get('option_ids', ()), 'Choose an offered option.')
        picks = pending.setdefault('picks', [])
        if payload['option'] in picks: picks.remove(payload['option'])
        else:
            require(len(picks) < spec['maximum_selections'], 'Remove a selected option before choosing another.')
            picks.append(payload['option'])
        session.emit('NATIVE_EFFECT_SELECTION_CHANGED', aid)
        return True
    require(set(payload) == {'selection','spend','option_ids'}, 'Choose an offered response and its cost.')
    request = pending['request']
    decision = ReactionDecision(**{k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')}, **payload)
    if request.get('extension_choice'):
        from ..choice_checkpoints import validate
        from ..gate4_models import ExtensionChoice
        validate(decision, ExtensionChoice.model_validate(request['extension_choice']))
    else:
        require(decision.spend in ([0] if decision.selection=='DECLINE' else request.get('spend_options') or [0])
                and set(decision.option_ids) <= set(request.get('legal_option_ids', []))
                and (decision.selection != 'DECLINE' or not decision.option_ids), 'Choose a legal native reaction response.')
    session._native_answers = deepcopy(pending['answers'])
    session._native_answers[answer_key(request)] = decision.model_dump(mode='json')
    session._native_original = deepcopy(pending['original'])
    del session.state[PENDING]
    original = session._native_original
    session._native_revision = original['revision']
    session._command(original['actor_id'], original['kind'], deepcopy(original['payload']))
    return True


@hook('journey_options')
def options(session, aid):
    pending = session.state.get(PENDING)
    if not pending or pending['request']['reactor_id'] != aid: return None
    r = pending['request']; spec = r.get('extension_choice'); trigger = r.get('choice_trigger', {})
    presentation = r.get('journey_presentation', {})
    title = trigger.get('prompt') or presentation.get('prompt') or 'Respond to the ongoing Burning Brand damage or saving throw'
    labels = trigger.get('labels', {})
    rows = []
    if spec:
        if spec['maximum_selections'] > 1:
            picks = pending.get('picks', [])
            # Incremental selection keeps every combination and ordering reachable
            # without materializing a factorial number of plans in the menu.
            offered = [{'id':'native:pick:'+str(i),'kind':'native_effect_pick','auto_select':0,
                'payload':{'option':option},'label':title+' — '+('Remove ' if option in picks else 'Select ')+labels.get(option,option)}
                for i,option in enumerate(spec['option_ids']) if option in picks or len(picks)<spec['maximum_selections']]
            if spec['minimum_selections'] <= len(picks) <= spec['maximum_selections']:
                rows.append(('USE',0,list(picks),'Confirm selected options'))
        else:
            offered = []
            if spec['minimum_selections']==0: rows.append(('USE',0,[],'Continue without choosing a benefit'))
            for pick in spec['option_ids']: rows.append(('USE',0,[pick],labels.get(pick,pick)))
        decline = spec['allow_decline']
    else:
        offered = []
        for spend in r.get('spend_options') or [0]:
            cost = spend or presentation.get('cost', 0)
            payment = f"; spend {cost} {presentation['resource']}" if cost else ''
            rows.append(('USE',spend,r.get('legal_option_ids',[]),
                         f"Use {presentation.get('name', 'the reaction')} (Reaction{payment})"))
        decline = True
    if decline: rows.append(('DECLINE',0,[],'Decline'))
    return offered + [{'id':'native:answer:'+str(i),'kind':'native_effect_answer','auto_select':0,
             'payload':{'selection':selection,'spend':spend,'option_ids':picks}, 'label':title+' — '+label}
            for i,(selection,spend,picks,label) in enumerate(rows)]


@hook('journey_auto_blocked')
def block(session, aid):
    if session.state.get(PENDING): return True


@hook('journey_tick_limit')
def followup_limit(session, remaining):
    if session.state['phase'] != 'travel' or KEY not in session.state: return None
    from fractions import Fraction
    # Reactions to a pulse can create next-turn defenses or marks. Their native
    # expiration continues even if the Brand's save succeeds on that pulse.
    state = json_state(session)
    if any(a.get('modifiers') or any(c.get('expires_on') not in (None,'UNTIL_REMOVED')
            for c in a['conditions'].values()) for a in state['actors'].values()):
        return min(remaining, 6-(session.clock()-Fraction(session.state[KEY]['seconds'])) % 6)


def json_state(session):
    import json
    return json.loads(session.state[KEY]['state'])


@hook('journey_elapsed')
def expire_followups(session, aid, before, seconds, moving):
    if session.state['phase'] != 'travel' or KEY not in session.state: return
    from fractions import Fraction
    from ..journey_native import load, commit
    from .effect_durations import sweep
    saved = session.state[KEY]
    now = session.clock()-Fraction(saved['seconds'])
    if now % 6: return
    state = json_state(session)
    target = state['actors'].get(aid)
    if not target or not any(a.get('modifiers') or any(c.get('expires_on') not in (None,'UNTIL_REMOVED')
            for c in a['conditions'].values()) for member, a in state['actors'].items()
            if member in session.state['actors']): return
    engine = load(session, aid)
    actor = engine.state.actors[aid]
    stamp = int(saved['round'])+int(now//6)
    engine.state.round_number = stamp
    if actor.turn_flags.get('_round_journey_expiry') == stamp: return
    actor.turn_flags['_round_journey_expiry'] = stamp
    actor.turns_started += 1
    engine._expire_for_checkpoint('START_OF_TURN', aid, nominal=True)
    sweep(engine, actor, 'START_OF_TURN')
    engine._expire_for_checkpoint('END_OF_TURN', aid, nominal=True)
    sweep(engine, actor, 'END_OF_TURN', ending_id=aid)
    commit(session, engine)


@hook('journey_combat_bundle')
def combat_clock(bundle, session, aid):
    if KEY not in session.state: return None
    import json
    state = json_state(session)
    record = state['actors'].get(aid)
    if not record: return None
    bundle = deepcopy(bundle)
    bundle['native_effect_clock'] = {'round':state['round_number'],
        'turns':record['turns_started'], 'modifiers':json.dumps(record['modifiers']),
        'condition_ids':list(record['conditions'])}
    return bundle


@hook('match_initialize', priority=100)
def restore_clock(engine):
    import json
    from ..gate2_runtime_models import ModifierInstance
    from .effect_durations import parse_round, round_token
    for bundle in engine.typed_bundle_documents:
        clock = bundle.get('native_effect_clock'); actor=engine.state.actors.get(bundle['actor_id'])
        if not clock or actor is None: continue
        actor.turns_started = clock['turns']
        modifiers = {i:ModifierInstance.model_validate(m) for i,m in json.loads(clock['modifiers']).items()}
        actor.modifiers.update(modifiers)
        for row in [*(c for i,c in actor.conditions.items() if i in clock['condition_ids']), *modifiers.values()]:
            parsed = parse_round(row.expires_on)
            if parsed:
                row.expires_on = round_token(engine, max(0, parsed[0]-clock['round']))
