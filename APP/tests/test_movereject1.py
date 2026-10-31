"""Menu-issued movement must bind and execute on the exact preview runtime."""
import pytest

from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, duel
from tests.test_lock10_flight_movement import grant


@pytest.mark.parametrize('seed', ['MOVEREJECT-1', 'MOVEREJECT-2'])
@pytest.mark.parametrize('flying', [False, True])
def test_offered_moves_execute(seed, flying):
    engine = duel([], seed=seed)
    if flying:
        grant(engine, engine.state.actors[ME], 20)
    candidates = [c for c in engine.legal_candidates() if c.kind == 'MOVE']
    assert candidates
    failures = []
    for candidate in candidates:
        probe = CombatService._clone_engine(ROOT, engine)
        probe.set_reaction_provider(lambda r: (ReactionDecision(checkpoint=r['checkpoint'],
            reactor_id=r['reactor_id'], reaction_source_id=r['reaction_source_id'], selection='DECLINE'), None))
        intent = ActionIntent(intent_id='move-check', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, destination=candidate.destination)
        try:
            probe.execute_intent(intent)
        except Exception as exc:
            diagnostic = getattr(exc, 'diagnostic', None)
            failures.append((candidate.model_dump(mode='json'), getattr(diagnostic, 'code', None), str(exc)))
            if len(failures) == 3:
                break
    assert not failures, failures
