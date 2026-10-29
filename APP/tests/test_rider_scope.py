import json
from collections import Counter

import pytest

from tools import rider_scope


def test_import_is_all_or_nothing_and_totals_match(tmp_path, monkeypatch):
    rows = rider_scope.entries()
    assert Counter(row["class"] for row in rows) == {
        "HASNT": 6961, "CANT_TABLE": 2021,
        "DONE_ELSEWHERE": 237, "NEEDS_RULING": 180,
    }
    assert not list(rider_scope.stale(rows, rider_scope.authority()))
    pending = [r for r in rows if r.get("pending_merge")]
    assert len(pending) == 14
    assert all(r["class"] == "HASNT" and r["pending_merge"] == "feat/lighting-s3" for r in pending)
    assert sum(r["class"] == "HASNT" and not r.get("pending_merge") for r in rows) == 6947

    data = tmp_path / "data"
    data.mkdir()
    batch_name = pending[0]["batch"]
    selected = [r for r in rows if r["batch"] == batch_name]
    original = json.dumps(selected)
    (data / "batch.json").write_text(original)
    monkeypatch.setattr(rider_scope, "DATA", data)
    batch = {"batch": batch_name, "riders": [dict(r) for r in selected]}
    original_text = batch["riders"][-1]["text60"]
    batch["riders"][-1]["text60"] = "wrong"
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(batch))
    with pytest.raises(ValueError):
        rider_scope.import_batch(source)
    assert (data / "batch.json").read_text() == original
    assert list(data.iterdir()) == [data / "batch.json"]

    batch["riders"][-1]["text60"] = original_text
    for row in batch["riders"]:
        row.pop("pending_merge", None)
    source.write_text(json.dumps(batch))
    rider_scope.import_batch(source)
    (data / "batch.json").unlink()  # The fixture file is not a real sphere group.
    imported = rider_scope.entries()
    expected = {(r["mechanic_id"], r["index"]): r["pending_merge"] for r in selected if r.get("pending_merge")}
    assert {(r["mechanic_id"], r["index"]): r["pending_merge"] for r in imported if r.get("pending_merge")} == expected
