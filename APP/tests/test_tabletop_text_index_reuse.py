"""Reuse existing text projections without broadening freshness or source inputs."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import pytest

from combat import factory_compiler, tabletop


@pytest.fixture
def authority(tmp_path, monkeypatch):
    path = tmp_path / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    rules = path.parent / "typed_mechanics" / "rules_text.json"
    rules.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mechanics": {
        "first": {"name": " Twin  Art ", "kind": "talent", "sphere_id": "sphere:test",
                  "activation": {"economy": "action"}, "coverage": "FULL", "description": ["Fallback first"]},
        "second": {"name": "Twin Art", "description": ["Fallback second", "Another line"]},
        "unnamed": {"name": None},
    }}), encoding="utf-8")
    rules.write_text(json.dumps({"first": "The full printed rule."}), encoding="utf-8")
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    for name in ("_AUTHORITY_INDEX", "_MECHANIC_NAMES", "_TOGGLE_OWNERS", "_OWNED_KEYS"):
        monkeypatch.setattr(tabletop, name, {})
    return path, rules


def count_authority_reads(monkeypatch, path):
    reads = []
    original = Path.read_text

    def read(source, *args, **kwargs):
        if source == path:
            reads.append(source)
        return original(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    return reads


def test_existing_authority_projection_supplies_names_without_another_read(authority, monkeypatch):
    path, _rules = authority
    reads = count_authority_reads(monkeypatch, path)
    index = tabletop._authority_index()
    names = tabletop._mechanic_names()
    assert len(reads) == 1
    assert index["first"] == {"name": " Twin  Art ", "kind": "talent", "sphere_id": "sphere:test",
                              "economy": "action", "coverage": "FULL", "description": "The full printed rule."}
    assert index["second"]["description"] == "Fallback second\nAnother line"
    assert names == {"first": "twin art", "second": "twin art", "unnamed": ""}
    assert tabletop._mechanic_key("twin art") == "first", "duplicate names preserve source order"
    assert tabletop._authority_index() is index
    assert tabletop._mechanic_names() is names
    assert len(reads) == 1, "warm indexes retain their existing behavior"


def test_names_first_keeps_its_independent_source_and_both_orders_agree(authority, monkeypatch):
    path, rules = authority
    reads = count_authority_reads(monkeypatch, path)
    printed = rules.read_bytes()
    rules.write_bytes(b"\xff")
    names_first = dict(tabletop._mechanic_names())
    assert len(reads) == 1, "a name-only request must not require readable printed rules"
    with pytest.raises(UnicodeDecodeError):
        tabletop._authority_index()
    rules.write_bytes(printed)
    index = tabletop._authority_index()
    tabletop._MECHANIC_NAMES.clear()
    reads.clear()
    assert tabletop._mechanic_names() == names_first
    assert tabletop._authority_index() is index
    assert reads == [], "once the authority index exists its names need no new read"


def test_same_size_and_mtime_edit_cannot_reuse_old_projected_names(authority, monkeypatch):
    path, _rules = authority
    old = tabletop._authority_index()
    stamp = path.stat()
    identity = tabletop._text_file_identity(path)
    path.write_bytes(path.read_bytes().replace(b"Twin", b"Wind", 1))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert path.stat().st_size == stamp.st_size
    assert tabletop._text_file_identity(path) != identity
    reads = count_authority_reads(monkeypatch, path)
    assert tabletop._mechanic_names()["first"] == "wind art"
    assert len(reads) == 1, "the old projection does not belong to this file identity"
    assert old["first"]["name"] == " Twin  Art "
    assert tabletop._authority_index()["first"]["name"] == " Wind  Art "


def test_source_switch_cannot_borrow_another_files_projection(authority, monkeypatch, tmp_path):
    path, _rules = authority
    tabletop._authority_index()
    other = tmp_path / "other-authority.json"
    other.write_bytes(path.read_bytes().replace(b"Twin", b"Wind", 1))
    stamp = path.stat()
    os.utime(other, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", other)
    assert tabletop._mechanic_names()["first"] == "wind art"
    assert tabletop._mechanic_key("twin art") == "second"


@pytest.mark.parametrize("replacement,exception", [
    (b"{bad JSON", json.JSONDecodeError),
    (b"\xff", UnicodeDecodeError),
    (b'\xef\xbb\xbf{"mechanics":{}}', json.JSONDecodeError),
    ('{"mechanics":{}}'.encode("utf-16"), UnicodeDecodeError),
    (b"{}", KeyError),
    (None, FileNotFoundError),
])
def test_invalid_source_still_raises_despite_an_existing_projection(authority, replacement, exception):
    path, _rules = authority
    tabletop._authority_index()
    if replacement is None:
        path.unlink()
    else:
        changed = path.with_suffix(".replacement")
        changed.write_bytes(replacement)
        changed.replace(path)
    with pytest.raises(exception):
        tabletop._mechanic_names()
    assert "rows" not in tabletop._MECHANIC_NAMES


def test_active_request_keeps_its_rows_and_first_match_after_another_request_refreshes(authority):
    path, _rules = authority
    with tabletop.text_snapshot():
        old_index = tabletop._authority_index()
        old_names = tabletop._mechanic_names()
        path.write_bytes(path.read_bytes().replace(b"Twin", b"Wind", 1))

        def other_request():
            with tabletop.text_snapshot():
                index = tabletop._authority_index()
                names = tabletop._mechanic_names()
                return index, names, tabletop._mechanic_key("twin art")

        with ThreadPoolExecutor(max_workers=1) as pool:
            new_index, new_names, new_first = pool.submit(other_request).result()
        assert new_index["first"]["name"] == " Wind  Art "
        assert new_names["first"] == "wind art"
        assert new_first == "second"
        assert tabletop._authority_index() is old_index
        assert tabletop._mechanic_names() is old_names
        assert tabletop._mechanic_key("twin art") == "first"
    assert tabletop._authority_index() is new_index
    assert tabletop._mechanic_names() is new_names


def test_reusing_projection_keeps_conservative_source_impact_dependency(authority, monkeypatch):
    from tools import record_impact_pytest

    recorder = record_impact_pytest.TraceRecorder()
    monkeypatch.setattr(record_impact_pytest, "_ACTIVE", recorder)
    tabletop._authority_index()
    assert ("*", "*") in recorder.dependencies
    tabletop._mechanic_names()
    assert ("*", "*") in recorder.dependencies
