"""Bounded automatic transport; normal binding, consent and commits per step.

Used by the tabletop SSE endpoint. No engine is retained beyond this iterator.
The next step may reuse only a just-committed session with unchanged complete
mechanical/controller journals and ordinary presentation boundary validation.
Player/model decisions and consent prompts always return to the usual table.
"""
from hashlib import sha256


def journal_boundary(session):
    """Detect replacement/corruption anywhere, including an unchanged tail."""
    return tuple(sha256((session.store.match_dir / name).read_bytes()).digest()
                 for name in ('Journal.ndjson', 'ControllerJournal.ndjson'))


def prepare_continuation(combat, session):
    """Restore the event/control projections a verified disk load would use.

    Commits enrich event copies for replay. Subsequent AI knowledge must read
    those same durable events, including for later members of this batch.
    No mechanics, dice, candidates or scored decisions are changed here.
    """
    from .gate2_runtime_models import CombatEvent
    from .terrain_occlusion import saved_policy

    session = combat.presentation_session(session)
    if session is None:
        return None
    engine = session.engine
    commit = next(row for row in reversed(session.mechanical._records)
                  if row.get('record_type') == 'COMMIT')
    docs = commit['events']
    if docs:
        first = docs[0]['sequence']
        engine.events = [event for event in engine.events if event.sequence < first]
        engine.events.extend(CombatEvent.model_validate(doc) for doc in docs)
    engine.grid.bind_occluder_policy(saved_policy(engine.events))
    actor_id = engine.state.current_actor_id
    engine.placement_policies = {
        actor_id: combat.policies.for_actor(actor_id)[0].model_dump(mode='json')
    } if actor_id in engine.state.actors else {}
    return session


def auto_steps(table, match_id, after=0, decision_id=None, state_version=None, *, maximum_steps=8):
    """Yield committed event deltas, then one full deferred-menu state.

    Pulling the next item authorizes at most one further action. Closing the
    iterator/disconnecting stops future actions; an in-flight commit completes.
    The hard cap bounds work and lets other requests acquire the table locks.
    """
    session = None
    boundary = None
    try:
        for _ in range(max(1, min(int(maximum_steps), 8))):
            if session is not None:
                if journal_boundary(session) != boundary:
                    session = None
                else:
                    session = prepare_continuation(table.combat, session)
            if session is None:
                session = table.combat._load_session(match_id)
            state = session.engine.state
            metadata = table.combat._read_metadata(match_id, session)
            actor_id = state.pending_resolution.actor_id if state.pending_resolution else state.current_actor_id
            if (state.terminal_result is not None or metadata.get('paused')
                    or table.combat._mode_for_actor(metadata, session, actor_id) not in {'LOCAL_AUTO', 'API_AUTO'}):
                break
            committed = []
            result = table.auto_step(match_id, after, [], decision_id, state_version,
                                     defer_menu=True, _session=session, _include_state=False,
                                     _committed=committed.append)
            # Every subsequent step binds afresh, never reuses the first intent.
            decision_id = state_version = None
            if result.get('state') is not None or result['status'] != 'COMMITTED':
                yield result
                return
            session = committed[0] if committed else None
            boundary = journal_boundary(session) if session is not None else None
            after = result['events']['last_sequence']
            yield result
        # API Auto owns its execution session through the ordinary provider
        # dispatch. Reload its durable commit before deciding whether Play can
        # continue, including a Local/API transition at this request boundary.
        if session is None:
            session = table.combat._load_session(match_id)
        state = session.engine.state
        metadata = table.combat._read_metadata(match_id, session) if session is not None else {}
        actor_id = (state.pending_resolution.actor_id if state.pending_resolution else state.current_actor_id) if state else None
        more = bool(state and not state.terminal_result and not metadata.get('paused')
                    and table.combat._mode_for_actor(metadata, session, actor_id) in {'LOCAL_AUTO', 'API_AUTO'})
        yield {'status': 'BATCH_COMPLETE', 'continue_auto': more,
               'state': table.state(match_id, _session=session, include_menu=False, fog=True)}
    finally:
        # No cache of mutable execution engines across requests.
        session = None
