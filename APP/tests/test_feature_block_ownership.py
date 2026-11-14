"""Sharding feature data must not let filename order choose an ability's behavior."""
import json
from pathlib import Path

import pytest

from combat import typed_reactions


def _write(path, features):
    path.write_text(json.dumps({"features": features}), encoding="utf-8")


def _rules_files(tmp_path, monkeypatch):
    main = tmp_path / "feature_blocks.json"
    shards = tmp_path / "feature_blocks.d"
    shards.mkdir()
    monkeypatch.setattr(typed_reactions, "RULES_PATH", main)
    monkeypatch.setattr(typed_reactions, "_CACHE", {})
    return main, shards


@pytest.mark.parametrize("duplicate_main", [True, False])
@pytest.mark.parametrize("same_value", [True, False])
def test_duplicate_feature_owner_is_rejected_even_when_rows_match(tmp_path, monkeypatch, duplicate_main, same_value):
    main, shards = _rules_files(tmp_path, monkeypatch)
    original = {"block": "defense", "amount": 1}
    replacement = original if same_value else {"block": "redirect"}
    _write(main, {"test:feature": original} if duplicate_main else {})
    first = main if duplicate_main else shards / "first.json"
    if not duplicate_main:
        _write(first, {"test:feature": original})
    last = shards / "last.json"
    _write(last, {"test:feature": replacement})
    with pytest.raises(ValueError, match="test:feature") as result:
        typed_reactions.rules()
    assert str(first) in str(result.value)
    assert str(last) in str(result.value)
    assert typed_reactions._CACHE == {}


def test_failed_reload_does_not_publish_partial_feature_map(tmp_path, monkeypatch):
    main, shards = _rules_files(tmp_path, monkeypatch)
    _write(main, {"test:one": {"block": "defense"}})
    _write(shards / "first.json", {"test:two": {"block": "resistance"}})
    previous = typed_reactions.rules()
    stamp = typed_reactions._CACHE["mtime"]
    _write(shards / "last.json", {"test:one": {"block": "redirect"}})
    with pytest.raises(ValueError, match="test:one"):
        typed_reactions.rules()
    assert typed_reactions._CACHE["data"] is previous
    assert typed_reactions._CACHE["mtime"] == stamp
    assert previous["features"] == {"test:one": {"block": "defense"}, "test:two": {"block": "resistance"}}


def test_repository_feature_files_have_one_owner_each():
    root = Path(__file__).resolve().parents[1] / "combat" / "rules"
    owners = {}
    for path in [root / "feature_blocks.json", *sorted((root / "feature_blocks.d").glob("*.json"))]:
        for key in json.loads(path.read_text(encoding="utf-8"))["features"]:
            assert key not in owners, f"{key}: {owners.get(key)} and {path}"
            owners[key] = path
    assert owners
