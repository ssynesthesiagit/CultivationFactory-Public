"""Source quoting keeps verified text while sharing immutable cached lines."""

import hashlib
import os

import pytest

from character_creation.constructed_arts import sources


@pytest.fixture(autouse=True)
def source_cache():
    sources._verified_source_lines.cache_clear()
    yield
    sources._verified_source_lines.cache_clear()


def _source(path, data, anchor="line:2:column:1"):
    path.write_bytes(data)
    return {"path": path.name, "source_hash": hashlib.sha256(data).hexdigest(), "anchor": anchor}


def test_quoted_text_matches_list_reader_and_does_not_mutate_shared_lines(tmp_path, monkeypatch):
    source = _source(
        tmp_path / "rules.md",
        b"# Arts\r\n## First\r\nEffect: \xe7\x81\xab / caf\xc3\xa9.\r\n"
        b"### Detail\r\nPrinted replacement: \xff\r\n\r\n## Second\r\nOther effect.\r\n",
    )
    shared = sources._source_lines(tmp_path, source["path"], source["source_hash"])
    expected = "## First\nEffect: 火 / café.\n### Detail\nPrinted replacement: \ufffd"
    assert sources.published_block(tmp_path, source) == expected
    assert sources.published_block(tmp_path, {**source, "anchor": "line:7"}) == "## Second\nOther effect."
    assert sources._source_lines(tmp_path, source["path"], source["source_hash"]) is shared
    assert isinstance(shared, tuple)
    assert sources._verified_source_lines.cache_info().misses == 1
    with pytest.raises(TypeError):
        shared[0] = "changed"

    # Exercise the exact previous container contract through the same reader.
    immutable_reader = sources._source_lines
    def old_list_reader(*args):
        lines = immutable_reader(*args)
        return None if lines is None else list(lines)
    monkeypatch.setattr(sources, "_source_lines", old_list_reader)
    assert sources.published_block(tmp_path, source) == expected
    assert shared[0] == "# Arts"


def test_same_size_tamper_invalidates_cached_source_and_restore_is_verified(tmp_path):
    path = tmp_path / "rules.md"
    original = b"# Arts\n## First\nOriginal text.\n"
    tampered = b"# Arts\n## First\nTampered text.\n"
    assert len(tampered) == len(original)
    source = _source(path, original)
    original_lines = sources._source_lines(tmp_path, path.name, source["source_hash"])
    before = path.stat()
    path.write_bytes(tampered)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    assert sources.published_block(tmp_path, source) == ""
    assert sources.published_block(tmp_path, {
        **source, "source_hash": hashlib.sha256(tampered).hexdigest(),
    }) == "## First\nTampered text."
    assert original_lines == ("# Arts", "## First", "Original text.")

    path.write_bytes(original)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000))
    assert sources.published_block(tmp_path, source) == "## First\nOriginal text."


@pytest.mark.parametrize("override", [
    {"path": "missing.md"},
    {"path": "."},
    {"path": "../rules.md"},
    {"source_hash": "0" * 64},
    {"anchor": "line:0"},
    {"anchor": "line:100"},
    {"anchor": "not-an-anchor"},
])
def test_unverifiable_or_out_of_bounds_source_never_quotes(tmp_path, override):
    root = tmp_path / "pack"
    root.mkdir()
    data = b"# Arts\n## First\nPrinted effect.\n"
    source = _source(root / "rules.md", data)
    (tmp_path / "rules.md").write_bytes(data)
    assert sources.published_block(root, {**source, **override}) == ""
