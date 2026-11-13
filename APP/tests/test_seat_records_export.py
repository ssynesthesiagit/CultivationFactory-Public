"""Size-capped rotation for seat decision records, and the exporter's training rows."""
import json

from agent_seats import decision_records
from tools.seat_records_export import export


def test_rotation_moves_full_file_aside(tmp_path):
    assert decision_records.append(tmp_path, {"n": 1}, max_bytes=10)
    assert decision_records.append(tmp_path, {"n": 2}, max_bytes=10)
    assert json.loads((tmp_path / "seat_decisions.jsonl.1").read_text())["n"] == 1
    assert json.loads((tmp_path / "seat_decisions.jsonl").read_text())["n"] == 2


def test_exporter_writes_live_rows_with_label_and_teacher(tmp_path):
    record = {"match_id": "m1", "decision_id": "d", "kind": "TURN", "provider_id": "d1", "prompt": "P",
              "options": {"A": "Move", "B": "End turn here"}, "answers": {}, "chosen_id": "A",
              "built_in_id": "B", "fallback": False, "probabilities": {"A": 1.0, "B": 0.0}}
    decision_records.append(tmp_path, record)
    out = tmp_path / "rows.jsonl"
    assert export(tmp_path, out) == 1
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["source"] == "live" and row["state"] == "P"
    assert row["label"] == "A" and row["teacher_label"] == "B"
    assert row["options"] == {"A": "Move", "B": "End turn here"}
