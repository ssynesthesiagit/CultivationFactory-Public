import json
from collections import Counter

import pytest

from tools import rider_scope


def test_snapshot_totals():
    rows = rider_scope.entries()
    assert not list(rider_scope.stale(rows, rider_scope.authority()))
    assert Counter(row["class"] for row in rows) == {
        "HASNT": 6854, "CANT_TABLE": 2010,
        "DONE_ELSEWHERE": 228, "NEEDS_RULING": 178,
    }
    pending = [r for r in rows if r.get("pending_merge")]
    assert len(pending) == 11
    assert all(r["class"] == "HASNT" and r["pending_merge"] == "feat/lighting-s3"
               for r in pending)
    assert len(rider_scope.held()) == 129


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    # Classification snapshots and authority evolve independently. Exercise the
    # stale guard against a controlled authority, not the current live catalog.
    records = {
        "first": {"sphere_id": "tianxia.sphere.fire", "riders": ["current text", "unchanged"]},
        "second": {"sphere_id": "tianxia.sphere.water", "riders": ["other current text"]},
    }
    live = [
        {"mechanic_id": "first", "index": 1, "text60": "unchanged",
         "batch": "B01", "by": "pro", "class": "HASNT",
         "effect_kind": "damage", "pending_merge": "feat/example"},
        {"mechanic_id": "second", "index": 0, "text60": "other current text",
         "batch": "B02", "by": "pro", "class": "CANT_TABLE", "reason": "campaign"},
    ]
    held = [
        {"mechanic_id": "first", "index": 0, "text60": "old text",
         "batch": "B01", "by": "pro", "class": "HASNT",
         "effect_kind": "movement", "held": rider_scope.HELD_NOTE},
    ]
    monkeypatch.setattr(rider_scope, "DATA", tmp_path / "data")
    monkeypatch.setattr(rider_scope, "authority", lambda: records)
    rider_scope.write_entries(live, records)
    rider_scope.write_held(held)
    return records, live, held


def test_import_is_all_or_nothing_and_totals_match(tmp_path, inventory):
    records, live, held = inventory
    rows = rider_scope.entries()
    assert Counter(row["class"] for row in rows) == {"HASNT": 1, "CANT_TABLE": 1}
    assert not list(rider_scope.stale(rows, records))
    assert list(rider_scope.stale(held, records)) == held
    batch = {"batch": "B01", "riders": [
        {k: v for k, v in row.items() if k not in ("held", "pending_merge")}
        for row in live + held if row["batch"] == "B01"
    ]}
    batch["riders"][-1]["text60"] = "wrong"
    source = tmp_path / "batch.json"
    source.write_text(json.dumps(batch))
    before = {p.relative_to(rider_scope.DATA): p.read_bytes()
              for p in rider_scope.DATA.rglob("*.json")}
    with pytest.raises(ValueError):
        rider_scope.import_batch(source)
    assert {p.relative_to(rider_scope.DATA): p.read_bytes()
            for p in rider_scope.DATA.rglob("*.json")} == before

    batch["riders"][-1]["text60"] = records["first"]["riders"][0]
    source.write_text(json.dumps(batch))
    rider_scope.import_batch(source)
    imported = rider_scope.entries()
    assert Counter(row["class"] for row in imported) == {"HASNT": 2, "CANT_TABLE": 1}
    assert {(r["mechanic_id"], r["index"]): r["pending_merge"]
            for r in imported if r.get("pending_merge")} == {("first", 1): "feat/example"}


def test_held_riders_return_only_through_pro_reimport(tmp_path, inventory):
    records, live, held = inventory
    assert rider_scope.entries() == live and rider_scope.held() == held
    assert list(rider_scope.stale(held, records)) == held
    batch = [
        {k: v for k, v in row.items() if k not in ("held", "pending_merge")}
        for row in live + held if row["batch"] == "B01"
    ]
    batch[-1]["text60"] = records["first"]["riders"][0]
    source = tmp_path / "batch.json"
    source.write_text(json.dumps({"batch": "B01", "riders": batch}))
    rider_scope.import_batch(source)

    assert rider_scope.held() == []
    assert len(rider_scope.entries()) == len(live) + len(held)
    assert not list(rider_scope.stale(rider_scope.entries(), records))
    assert next(r for r in rider_scope.entries() if r["index"] == 1)["pending_merge"] == "feat/example"
