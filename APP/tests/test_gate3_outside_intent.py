"""Outside-intent engine maintenance must survive a durable commit and replay."""

from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActionIntent, CandidateKind, CombatEvent
from combat.gate3_storage import Gate3Persistence

ROOT = Path(__file__).resolve().parents[1]


def end_turn(session, intent_id: str) -> None:
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.kind == CandidateKind.END_TURN)
    session.execute_intent(ActionIntent(
        intent_id=intent_id,
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
    ))


@pytest.mark.parametrize("prior_commit", [False, True], ids=["first-commit", "later-commit"])
def test_outside_intent_state_change_is_journaled_on_commit_and_reload(
    tmp_path: Path, prior_commit: bool,
) -> None:
    """Omitting pending maintenance events leaves a gap in replay from genesis."""
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="outside-intent-journal", maximum_rounds=20)
    if prior_commit:
        end_turn(session, "intent:baseline")
    assert sum(r["record_type"] == "COMMIT" for r in session._records) == int(prior_commit)

    engine = session.engine
    journal_base = engine.state.event_sequence
    target = engine.state.actors[engine.state.current_actor_id]
    amount = target.temporary_hp + 7
    event_start = len(engine.events)
    # Use the engine's real state mutation and event emitter, not a fabricated dict.
    engine._grant_temp_hp(target, amount, "test:maintenance", target.entity_id)
    outside_events = engine.events[event_start:]
    assert len(outside_events) == 1
    outside_event = CombatEvent.model_validate(outside_events[0])
    assert outside_event.event_type == "TEMP_HP_GRANTED"
    assert target.temporary_hp == amount

    end_turn(session, "intent:commit-maintenance")
    records, trailing = session.store.read_journal()
    assert trailing == b""
    commit = next(r for r in reversed(records) if r["record_type"] == "COMMIT")
    assert commit["event_sequence_start"] == journal_base + 1
    assert [e["sequence"] for e in commit["events"]] == list(
        range(journal_base + 1, commit["event_sequence_end"] + 1)
    )
    assert commit["events"][0]["event_type"] == outside_event.event_type
    assert commit["events"][0]["sequence"] == outside_event.sequence

    # Force the cold load to reduce GENESIS + journal, never a cached snapshot.
    for snapshot in session.store.snapshots_dir.glob("Snapshot_*.json"):
        snapshot.unlink()
    loaded = Gate3Persistence(ROOT, tmp_path / "UserData").load_match(session.match_id)
    assert loaded.engine.state == session.engine.state
    assert loaded.engine.state.actors[target.entity_id].temporary_hp == amount
    assert loaded.verify()["status"] == "PASS"

    events = loaded.replay()["events"]
    restored = next(e for e in events if e["sequence"] == outside_event.sequence)
    assert restored["event_type"] == "TEMP_HP_GRANTED"
    assert restored["source_definition_id"] == "test:maintenance"
    assert restored["target_ids"] == [target.entity_id]
    assert restored["payload"]["after"] == amount
    assert [e["sequence"] for e in events] == list(range(1, events[-1]["sequence"] + 1))
