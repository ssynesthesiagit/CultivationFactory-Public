"""Gate 5 empty-menu recovery and its transactional, replayable explanation.

Gate 5 uses recovery_candidates for system choices only. The event subscriber
records provenance after INTENT_ACCEPTED, never while a menu is being listed.
No ability is singled out and ordinary, non-vetoed system choices are inert.
"""
from typing import Any

from . import hook, note, vetoing_hooks
from ..fight_setup import SOURCE as SETUP


def recovery_candidates(engine: Any) -> tuple[Any, ...]:
    """Copy base setup/End Turn choices with a pure receipt for the empty menu.

    The service calls this only after native filtering returns no choices. Attach
    provenance to transient candidate metadata, not engine state: event acceptance
    changes sequence-based candidate IDs, so attribution must travel with the
    selected pre-state candidate rather than be recomputed inside the transaction.
    """
    from ..gate2_engine import Gate2Engine

    recovered = []
    for candidate in Gate2Engine.legal_candidates(engine):
        if candidate.source_definition_id != SETUP and candidate.kind.value != 'END_TURN':
            continue
        actor = engine.state.actors[candidate.actor_id]
        vetoes = vetoing_hooks('candidate_allowed', engine, actor, candidate,
                              engine.action_catalog.get(candidate.source_definition_id))
        choice = 'Finish fight setup' if candidate.source_definition_id == SETUP else 'End Turn'
        receipt = {'recovery': 'empty_candidate_menu', 'recovered_source': candidate.source_definition_id,
                   'vetoing_plugins': list(vetoes),
                   'log': f'{choice} was restored for {actor.display_name} because a game rule hid every available choice. '
                          'Only this setup or turn-ending choice was restored; no ability or resource cost was changed.'}
        recovered.append(candidate.model_copy(update={'metadata': {
            **candidate.metadata, 'system_candidate_recovery': receipt}}))
    return tuple(recovered)


def recovery_provenance(engine: Any, candidate: Any) -> dict[str, Any] | None:
    """Pure receipt for Gate 5's decision record and the accepted-intent event."""
    if candidate is None or not (candidate.source_definition_id == SETUP or candidate.kind.value == 'END_TURN'):
        return None
    receipt = candidate.metadata.get('system_candidate_recovery')
    if receipt is None:
        return None
    return {**receipt, 'vetoing_plugins': list(receipt['vetoing_plugins'])}


@hook('event')
def record_recovery(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != 'INTENT_ACCEPTED':
        return
    candidate = getattr(engine, '_active_candidate', None)
    provenance = recovery_provenance(engine, candidate)
    if provenance is not None:
        provenance = dict(provenance)
        log = provenance.pop('log')
        note(engine, 'system:combat.candidate_recovery', candidate.actor_id, log, **provenance)
