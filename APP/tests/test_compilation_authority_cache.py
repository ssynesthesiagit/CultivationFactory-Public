from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from combat import authority_cache
from tests.compilation_character_fixtures import owner_character_fixtures


@pytest.mark.parametrize('source,document', list(owner_character_fixtures(Path(__file__).resolve().parents[1])),
                         ids=lambda value: value if isinstance(value, str) else None)
def test_every_shipped_owner_snapshot_compiles_identically_with_and_without_cache(source, document):
    from combat import factory_compiler

    actor_id = 'actor:factory.cache_' + hashlib.sha256(source.encode()).hexdigest()[:12]
    try:
        expected = factory_compiler.compile_character(copy.deepcopy(document), actor_id=actor_id,
            typed_authority=json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes()))
    except AttributeError as exc:
        # Main ded5fcaa cannot compile this shipped Ning Kai snapshot: a string
        # target reaches the dictionary-only any-creature check. Keep the input
        # intact and verify the cache preserves the exact inherited failure.
        known_source = ('tests/fixtures/h52_turn_start/b95b3754-eeae-49d6-9dbd-6bbd4bb9d4f9/'
                        'current.zip:Tianxia_Owner_Character_Sheet_v1.json')
        if source != known_source or str(exc) != "'str' object has no attribute 'get'":
            raise
        for _ in range(2):
            with pytest.raises(AttributeError) as cached_error:
                factory_compiler.compile_character(copy.deepcopy(document), actor_id=actor_id)
            assert str(cached_error.value) == str(exc)
        pytest.xfail('Ning Kai fails identically on uncached main ded5fcaa; no compiled-output hash is available')
    cold = factory_compiler.compile_character(copy.deepcopy(document), actor_id=actor_id)
    warm = factory_compiler.compile_character(copy.deepcopy(document), actor_id=actor_id)
    assert expected == cold == warm, source


def test_content_hash_observes_same_size_same_mtime_edits(tmp_path, monkeypatch):
    path = tmp_path / "authority.json"
    first = b'{"mechanics":{"sample":{"effects":[{"flat":2}]}}}'
    second = first.replace(b'"flat":2', b'"flat":5')
    path.write_bytes(first)
    stamp = path.stat()
    cache = authority_cache._AuthorityCache()
    parse = authority_cache.json.loads
    calls = []

    def counted(source):
        calls.append(source)
        return parse(source)

    monkeypatch.setattr(authority_cache.json, "loads", counted)
    before, before_hash = cache.read(path)
    again, again_hash = cache.read(path)
    assert again is before
    assert again_hash == before_hash == hashlib.sha256(first).hexdigest()
    assert calls == [first]

    path.write_bytes(second)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert path.stat().st_size == len(first)
    assert path.stat().st_mtime_ns == stamp.st_mtime_ns
    after, after_hash = cache.read(path)
    assert after["mechanics"]["sample"]["effects"][0]["flat"] == 5
    assert before["mechanics"]["sample"]["effects"][0]["flat"] == 2
    assert after_hash == hashlib.sha256(second).hexdigest() != before_hash
    assert calls == [first, second]


def test_cache_reuses_content_across_paths_and_retains_only_one_entry(tmp_path, monkeypatch):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text('{"value":1}')
    b.write_bytes(a.read_bytes())
    cache = authority_cache._AuthorityCache()
    parse = authority_cache.json.loads
    calls = []

    def counted(source):
        calls.append(source)
        return parse(source)

    monkeypatch.setattr(authority_cache.json, "loads", counted)
    first, _ = cache.read(a)
    same, _ = cache.read(b)
    assert first is same
    b.write_text('{"value":2}')
    cache.read(b)
    reloaded, _ = cache.read(a)
    assert reloaded == first
    assert reloaded is not first
    assert len(calls) == 3


def test_invalid_or_deleted_source_never_falls_back_to_a_cached_value(tmp_path):
    path = tmp_path / "authority.json"
    path.write_text('{"value":1}')
    cache = authority_cache._AuthorityCache()
    valid, digest = cache.read(path)
    path.write_text('{"value":')
    with pytest.raises(json.JSONDecodeError):
        cache.read(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        cache.read(path)
    path.write_text('{"value":1}')
    restored, restored_digest = cache.read(path)
    assert restored is valid
    assert restored_digest == digest


def test_parser_and_provenance_preserve_original_raw_bytes_contract(tmp_path):
    path = tmp_path / "authority.json"
    cache = authority_cache._AuthorityCache()
    text = '{\n"value":1\n}'
    sources = [text.encode(), text.replace("\n", "\r\n").encode(), text.replace("\n", "\r").encode(),
               text.encode("utf-8-sig"), text.encode("utf-16")]
    digests = set()
    for source in sources:
        path.write_bytes(source)
        value, digest = cache.read(path)
        # The original compiler used json.loads(read_bytes()), not read_text.
        assert value == json.loads(source) == {"value": 1}
        assert digest == hashlib.sha256(source).hexdigest()
        digests.add(digest)
    assert len(digests) == len(sources)


def test_cached_nested_values_are_read_only_and_deepcopy_is_independent(tmp_path):
    path = tmp_path / "authority.json"
    source = {"mechanics": {"sample": {"effects": [{"flat": 2, "tags": ["fire"]}]}}}
    path.write_text(json.dumps(source))
    cache = authority_cache._AuthorityCache()
    value, _ = cache.read(path)
    effects = value["mechanics"]["sample"]["effects"]
    assert isinstance(value, dict) and isinstance(effects, list)
    with pytest.raises(TypeError, match="read-only"):
        effects[0]["flat"] = 100
    with pytest.raises(TypeError, match="read-only"):
        effects.append({"flat": 100})
    with pytest.raises(TypeError, match="read-only"):
        effects[0]["tags"] += ["cold"]
    with pytest.raises(TypeError, match="read-only"):
        value |= {"mechanics": {}}
    assert value == source
    assert json.loads(json.dumps(value)) == source

    independent = copy.deepcopy(value)
    assert type(independent) is dict
    assert type(independent["mechanics"]["sample"]["effects"]) is list
    assert type(independent["mechanics"]["sample"]["effects"][0]) is dict
    independent["mechanics"]["sample"]["effects"][0]["flat"] = 100
    independent["mechanics"]["sample"]["effects"].append({"flat": 200})
    assert cache.read(path)[0] == source


def _assert_plain_containers(value):
    if isinstance(value, dict):
        assert type(value) is dict
        for child in value.values():
            _assert_plain_containers(child)
    elif isinstance(value, list):
        assert type(value) is list
        for child in value:
            _assert_plain_containers(child)


def test_cached_compiler_matches_uncached_authority_and_returns_independent_bundles():
    from combat import factory_compiler
    from tests.test_factory_combat_compiler import ACTOR, SHEET

    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())
    source_before = copy.deepcopy(authority)
    expected = factory_compiler.compile_character(copy.deepcopy(SHEET), actor_id=ACTOR, typed_authority=authority)
    assert authority == source_before
    first = factory_compiler.compile_character(copy.deepcopy(SHEET), actor_id=ACTOR)
    second = factory_compiler.compile_character(copy.deepcopy(SHEET), actor_id=ACTOR)
    assert first == second == expected
    _assert_plain_containers(first)
    first["actor_template"]["action_ids"].clear()
    first["action_catalog"][0]["display_name"] = "changed by one test"
    first["action_catalog"].append({"test": "only one bundle"})
    assert second == expected
    assert factory_compiler.compile_character(copy.deepcopy(SHEET), actor_id=ACTOR) == expected


def test_explicit_authority_input_still_bypasses_the_default_cache(monkeypatch):
    from combat import factory_compiler
    from tests.test_factory_combat_compiler import ACTOR, SHEET

    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())

    def unexpected(_path):
        raise AssertionError("explicit authority must not use the default parsed cache")

    monkeypatch.setattr(factory_compiler, "_read_compilation_authority", unexpected)
    result = factory_compiler.compile_character(copy.deepcopy(SHEET), actor_id=ACTOR, typed_authority=authority)
    assert result["actor_id"] == ACTOR
    assert result["typed_authority_sha256"] == hashlib.sha256(factory_compiler.TYPED_AUTHORITY.read_bytes()).hexdigest()
