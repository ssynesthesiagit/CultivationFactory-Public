"""A saved-fight load cost 1.19 s at 612 events: it replayed twice and parsed
the controller journal three times, and every turn pays the load cost.
"""
from pathlib import Path

import combat.gate4_persistence as gate4
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_storage import Gate3Persistence

ROOT = Path(__file__).resolve().parents[1]


def test_saved_load_replays_once_and_parses_controller_journal_at_most_twice(tmp_path, monkeypatch):
    persistence = gate4.Gate4Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="POOLCOST3", maximum_rounds=20)
    for index in range(4):
        candidate = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
        session.submit_intent(ActionIntent(
            intent_id=f"poolcost3:{index}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination, option_ids=candidate.option_ids,
        ), primary_decision_record=None, reaction_provider=None)
    session.mechanical.explicit_snapshot()
    records, _ = session.store.scan_journal(recover_trailing_partial=False)
    snapshots, _ = session.store.valid_snapshots(records)
    assert snapshots
    assert session.controller_journal_path.stat().st_size > 0

    counts = {"replay": 0, "controller": 0}
    replay = Gate3Persistence._replay_from
    read_jsonl = gate4._read_jsonl

    def counted_replay(self, *args, **kwargs):
        counts["replay"] += 1
        return replay(self, *args, **kwargs)

    def counted_read(path):
        if path == session.controller_journal_path:
            counts["controller"] += 1
        return read_jsonl(path)

    monkeypatch.setattr(Gate3Persistence, "_replay_from", counted_replay)
    monkeypatch.setattr(gate4, "_read_jsonl", counted_read)
    persistence.load_match(session.match_id)
    assert counts["replay"] == 1
    assert counts["controller"] <= 2
