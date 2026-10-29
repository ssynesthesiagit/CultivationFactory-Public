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

    data = tmp_path / "data"
    data.mkdir()
    selected = [r for r in rows if r["batch"] == "B01"]
    original = json.dumps(selected)
    (data / "batch.json").write_text(original)
    monkeypatch.setattr(rider_scope, "DATA", data)
    batch = {"batch": "B01", "riders": [dict(r) for r in selected]}
    batch["riders"][-1]["text60"] = "wrong"
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(batch))
    with pytest.raises(ValueError):
        rider_scope.import_batch(source)
    assert (data / "batch.json").read_text() == original
    assert list(data.iterdir()) == [data / "batch.json"]
