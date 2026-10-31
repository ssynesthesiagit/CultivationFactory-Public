import json
from collections import Counter

import pytest

from tools import rider_scope


def test_import_is_all_or_nothing_and_totals_match(tmp_path, monkeypatch):
    rows = rider_scope.entries()
    # 60 riders were moved to the held list when the authority rebuild on main changed their text (see test_held_riders_return_only_through_pro_reimport).
    assert Counter(row["class"] for row in rows) == {
        "HASNT": 6913, "CANT_TABLE": 2015,
        "DONE_ELSEWHERE": 232, "NEEDS_RULING": 179,
    }
    assert not list(rider_scope.stale(rows, rider_scope.authority()))
    pending = [r for r in rows if r.get("pending_merge")]
    assert len(pending) == 11
    assert all(r["class"] == "HASNT" and r["pending_merge"] == "feat/lighting-s3" for r in pending)
    assert sum(r["class"] == "HASNT" and not r.get("pending_merge") for r in rows) == 6902

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


def test_held_riders_return_only_through_pro_reimport(tmp_path, monkeypatch):
    records = rider_scope.authority()
    live, held = rider_scope.entries(), rider_scope.held()
    assert len(held) == 60 and all(r.get("held") for r in held)
    assert len(list(rider_scope.stale(held, records))) == 60

    data = tmp_path / "data"
    monkeypatch.setattr(rider_scope, "DATA", data)
    rider_scope.write_entries(live, records)
    rider_scope.write_held(held)
    assert rider_scope.entries() == live and rider_scope.held() == held

    name = held[0]["batch"]
    held_in_batch = [r for r in held if r["batch"] == name]
    rows = [r for r in live + held if r["batch"] == name]
    riders = []
    for r in rows:
        row = {k: v for k, v in r.items() if k not in ("held", "pending_merge")}
        row["text60"] = records[r["mechanic_id"]]["riders"][r["index"]][:60]  # Pro re-reviewed against the current text.
        riders.append(row)
    source = tmp_path / "batch.json"
    source.write_text(json.dumps({"batch": name, "riders": riders}))
    rider_scope.import_batch(source)

    assert not [r for r in rider_scope.held() if r["batch"] == name]
    assert len(rider_scope.held()) == len(held) - len(held_in_batch)
    assert len(rider_scope.entries()) == len(live) + len(held_in_batch)
    assert not list(rider_scope.stale(rider_scope.entries(), records))
    expected = {(r["mechanic_id"], r["index"]): r["pending_merge"] for r in rows if r.get("pending_merge")}
    assert {(r["mechanic_id"], r["index"]): r["pending_merge"]
            for r in rider_scope.entries() if r["batch"] == name and r.get("pending_merge")} == expected
