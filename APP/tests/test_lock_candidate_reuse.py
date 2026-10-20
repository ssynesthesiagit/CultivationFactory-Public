from contextlib import contextmanager
import sys

import pytest

from combat.canonical import canonical_bytes
from combat.diagnostics import CombatGate1Error
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_storage import Gate3Persistence
from tests.test_auto_tabik import _engine, ROOT, ME
from tests.test_combat_gate3_persistence import exact_intent, SEED


@contextmanager
def generation_calls(engine):
    """Observe fresh generation without replacing any engine method."""
    calls = []
    def observed(frame, event, arg):
        if (event == 'call' and frame.f_code.co_name == '_generate_legal_candidates'
                and frame.f_code.co_filename.endswith('/gate2_engine.py')
                and frame.f_locals.get('self') is engine):
            calls.append(frame.f_locals.get('intent'))
    previous = sys.getprofile()
    try:
        sys.setprofile(observed)
        yield calls
    finally:
        sys.setprofile(previous)


def test_persistent_acceptance_generates_fresh_choices_without_full_enumeration(tmp_path):
    persistence = Gate3Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed=SEED, maximum_rounds=20)
    request = exact_intent(session, 1)
    # SOL177r1 deliberately removed reuse. PREPARE binds a fresh choice and
    # resolution validates it again after the persistence checkpoint, using
    # two targeted passes and zero full-menu enumerations for this valid intent.
    with generation_calls(session.engine) as calls:
        session.execute_intent(request)
    assert calls == [request, request]
    assert session.engine._prepared_candidates is None
    assert session.replay()["status"] == "PASS"


def test_reuse_preserves_stale_rejection_and_does_not_escape_scope(monkeypatch):
    e, _ = _engine([])
    candidates = e.legal_candidates()
    c = next(c for c in candidates if c.kind == "END_TURN")
    request = ActionIntent(intent_id="test:stale", candidate_id=c.candidate_id, decision_id=c.decision_id,
                           state_version=c.state_version-1, actor_id=ME)
    with e._reuse_legal_candidates(candidates):
        with pytest.raises(Exception, match="stale"):
            e.execute_intent(request)
    assert e._prepared_candidates is None


def test_persistent_resolution_revalidates_after_prepare_mutation(tmp_path):
    persistence = Gate3Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed=SEED, maximum_rounds=20)
    move = next(c for c in session.engine.legal_candidates() if c.kind == 'MOVE')
    request = ActionIntent(intent_id='test:prepare-mutation', candidate_id=move.candidate_id,
                           decision_id=move.decision_id, state_version=move.state_version,
                           actor_id=move.actor_id, target_ids=move.target_ids, destination=move.destination)
    actor = session.engine.state.actors[move.actor_id]
    position = actor.position
    version = session.engine.state.state_version
    def mutate(stage, payload):
        if stage == 'after_prepare_flush':
            # Direct nested writes need not advance versions. PREPARE's issued
            # choice must never authorize resolution after this legality change.
            actor.movement_remaining_ft = 0
    with generation_calls(session.engine) as calls:
        with pytest.raises(Exception, match='not legal'):
            session.execute_intent(request, failure_injector=mutate)
    assert calls == [request, request, None]
    assert session.engine.state.state_version == version
    assert session.engine.state.actors[move.actor_id].position == position
    assert session._records[-1]['record_type'] == 'ABORT'
    assert session.engine._prepared_candidates is None


def test_changed_state_regenerates_instead_of_accepting_cached_choices():
    e, _ = _engine([])
    candidates = e.legal_candidates()
    c = next(c for c in candidates if c.kind == "END_TURN")
    request = ActionIntent(intent_id="test:changed", candidate_id=c.candidate_id, decision_id=c.decision_id,
                           state_version=c.state_version, actor_id=ME)
    with e._reuse_legal_candidates(candidates):
        e.state.state_version += 1
        before = canonical_bytes(e.state.model_dump(mode='json'))
        with generation_calls(e) as calls:
            with pytest.raises(CombatGate1Error, match='not legal'):
                e.execute_intent(request)
        assert canonical_bytes(e.state.model_dump(mode='json')) == before
    # The stale identity has no fresh targeted match, so native full fallback
    # must also reject it. Merely accepting the old issued row fails this test.
    assert calls == [request, None]
    assert e._prepared_candidates is None
