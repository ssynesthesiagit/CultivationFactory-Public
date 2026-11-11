"""Synthetic regression: typed-number lookups reuse one parsed authority view between file changes."""
import json
import os

from combat import typed_numbers


def _write(path, value):
    path.write_text(json.dumps({"mechanics": {"R": {"name": value, "effects": []}}}), encoding="utf-8")
    stamp = (1_700_000_000 + len(value)) * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def test_repeated_lookups_read_the_authority_once_and_follow_edits(tmp_path, monkeypatch):
    path = tmp_path / "authority.json"
    _write(path, "first")
    monkeypatch.setattr(typed_numbers, "AUTHORITY_PATH", path)
    reads = []
    real = typed_numbers.read_record_authority

    def counted(target):
        reads.append(target)
        return real(target)

    monkeypatch.setattr(typed_numbers, "read_record_authority", counted)
    assert typed_numbers.authority_mechanics()["R"]["name"] == "first"
    for _ in range(3):
        assert typed_numbers.authority_mechanics()["R"]["name"] == "first"
    assert len(reads) == 1

    _write(path, "second-edit")
    assert typed_numbers.authority_mechanics()["R"]["name"] == "second-edit"
    assert len(reads) == 2


def test_missing_authority_is_an_empty_view(tmp_path, monkeypatch):
    monkeypatch.setattr(typed_numbers, "AUTHORITY_PATH", tmp_path / "absent.json")
    assert typed_numbers.authority_mechanics() == {}
