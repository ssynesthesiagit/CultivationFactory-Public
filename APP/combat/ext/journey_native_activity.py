"""Journey command/menu binding for the public native activity runtime.

Only explicitly opted-in sources enable it. All legal native choices remain
reachable; candidate legality is regenerated on submission. A pause discards the
attempt and records the exact native prompt without committing costs or rolls.
"""
from . import hook
from contextlib import nullcontext


@hook('fact_admission_schema')
def relationship_input(session, source, subject, kind):
    if source == 'system:journey.activity' and kind == 'relations' and subject == min(session.state['actors']):
        return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'description': 'Public native actor relationships for outside-combat actions; this is not willingness or consent.'}


@hook('journey_options')
def options(session, aid):
    from ..journey_activity import enabled, load
    if session.state['phase'] != 'travel' or not enabled(session):
        return None
    pending = session.state.get('native_activity_pending')
    if pending:
        if pending['request']['reactor_id'] != aid:
            return []
        return [{'id': 'native_activity:answer', 'kind': 'native_activity_answer',
            'payload': {},
            'label': 'Answer the pending ability choice before continuing.', 'request': pending['request']}]
    engine = load(session, initiator=aid)
    if engine.state.current_actor_id != aid:
        return None
    from ..candidate_knowledge import query
    scope = query(engine) if session.state['actors'][aid]['control_mode'] == 'LOCAL_AUTO' else nullcontext()
    with scope:
        offered = [*({'id': candidate.candidate_id, 'kind': 'native_activity',
             'payload': {'candidate_id': candidate.candidate_id},
             'target_ids': list(candidate.target_ids),
             'destination': candidate.destination.model_dump(mode='json') if candidate.destination is not None else None,
             'option_ids': list(candidate.option_ids),
             'choice_domains': [domain.model_dump(mode='json') for domain in candidate.choice_domains],
             'details': str((engine.action_catalog.get(candidate.source_definition_id).parameters or {}).get('description') or '')
                        if candidate.source_definition_id in engine.action_catalog else '',
             'label': candidate.display_name + (' — ' + ', '.join(engine.state.actors[t].display_name for t in candidate.target_ids) if candidate.target_ids else '')}
            for candidate in engine.legal_candidates()),
            *([{'id': 'native_activity:end', 'kind': 'native_activity_end', 'payload': {},
                'label': 'End outside-combat rounds: the remainder of this six-second round passes; effects keep their remaining durations.'}]
              if session.state.get('native_activity') is not None else [])]
    return offered


@hook('journey_auto_blocked')
def pending_owner_choice(session, aid):
    return True if session.state.get('native_activity_pending') else None


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind == 'native_activity_answer':
        from ..journey_activity import act
        from ..journey import require
        from ..gate2_runtime_models import ReactionDecision
        pending = session.state.get('native_activity_pending')
        require(pending is not None and pending['request']['reactor_id'] == aid,
            'Only the creature receiving this native choice may answer it.')
        request = pending['request']
        decision = ReactionDecision.model_validate(payload)
        require((decision.checkpoint, decision.reactor_id, decision.reaction_source_id) ==
            tuple(request[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')),
            'Answer the exact pending ability checkpoint.')
        answers = [*pending['answers'], decision.model_dump(mode='json')]
        session.emit('NATIVE_ACTIVITY_CHOICE_ANSWERED', aid, decision=decision.model_dump_json())
        if pending.get('operation') == 'journey_command':
            from ..journey_effect_time import command as replay_command
            session.state.pop('native_activity_pending')
            replay_command(session, pending['actor_id'], pending['command_kind'], pending['payload'],
                answers=answers, intent_id=pending['intent_id'])
            return True
        act(session, pending['actor_id'], pending['payload'], collected_answers=answers)
        return True
    if kind == 'native_activity_end':
        from ..journey_activity import close
        if payload:
            raise ValueError('Ending outside-combat rounds takes no extra parameters')
        close(session, aid)
        return True
    if kind != 'native_activity':
        return None
    from ..journey_activity import act, enabled
    if not enabled(session):
        raise ValueError('No acquired source enables outside-combat native actions')
    if session.state.get('native_activity_pending'):
        raise ValueError('The named creature must answer the pending native choice first')
    act(session, aid, payload)
    return True


@hook('journey_command_gate')
def command_gate(session, aid, kind, payload):
    if session.state.get('native_activity_pending') and kind != 'native_activity_answer':
        raise ValueError('The named creature must answer the pending native ability choice first.')
    if session.state.get('native_activity') is not None and kind not in ('native_activity', 'native_activity_answer', 'native_activity_end'):
        raise ValueError('End outside-combat rounds before changing journey state.')


@hook('journey_transition_gate')
def transition_gate(session, kind):
    if session.state.get('native_activity') is not None or session.state.get('native_activity_pending'):
        raise ValueError('Finish outside-combat rounds and their pending choices before changing the scene or starting combat.')


@hook('journey_time_gate')
def time_gate(session, seconds):
    if session.state.get('native_activity') is not None and not getattr(session, 'native_activity_advancing', False):
        raise ValueError('End outside-combat rounds before advancing ordinary journey time.')
