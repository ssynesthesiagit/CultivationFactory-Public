"""Journey command/menu binding for the public native activity runtime.

Only explicitly opted-in sources enable it. All legal native choices remain
reachable; candidate legality is regenerated on submission. A pause discards the
attempt and records the exact native prompt without committing costs or rolls.
"""
from . import hook


@hook('fact_admission_schema')
def relationship_input(session, source, subject, kind):
    if source == 'system:journey.activity' and kind == 'relations' and subject == next(iter(session.state['actors'])):
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
            'label': 'Answer the pending outside-combat ability choice.', 'request': pending['request']}]
    engine = load(session)
    if engine.state.current_actor_id != aid:
        return None
    return [*({'id': candidate.candidate_id, 'kind': 'native_activity',
             'payload': {'candidate_id': candidate.candidate_id},
             'target_ids': list(candidate.target_ids),
             'label': candidate.display_name + (' — ' + ', '.join(engine.state.actors[t].display_name for t in candidate.target_ids) if candidate.target_ids else '')}
            for candidate in engine.legal_candidates()),
            *([{'id': 'native_activity:end', 'kind': 'native_activity_end', 'payload': {},
                'label': 'End outside-combat rounds: the remainder of this six-second round passes; effects keep their remaining durations.'}]
              if session.state.get('native_activity') is not None else [])]


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
        if 'procedure' in pending:
            from ..journey_activity import procedure
            procedure(session, pending['actor_id'], pending['procedure'], collected_answers=answers)
        else:
            act(session, pending['actor_id'], {'candidate_id': pending['candidate_id']}, collected_answers=answers)
        return True
    if kind == 'native_procedure':
        from ..journey_activity import procedure
        if session.state.get('native_activity_pending'):
            raise ValueError('Answer the pending source-procedure choice first.')
        procedure(session, aid, payload)
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
