"""Area origin permissions are bound once per rules_text.json version (AREAPERMCACHE1).

Every engine construction runs the match_start hook, which used to re-read and
re-scan the 4.6 MB prose file. These checks pin one read across constructions,
a recompute when the file version changes, and a result that callers cannot
mutate into the next call. The rule text is synthetic except the construction test.
"""
import json
import os

from combat import area_knowledge
from combat.gate4_persistence import Gate4Persistence
from tests.h1_support import ROOT

RULES_TEXT = 'authority/typed_mechanics/rules_text.json'


def _rules_root(tmp_path, prose):
    root = tmp_path / 'source'
    path = root / RULES_TEXT
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(prose))
    return root, path


def _spy_reads(monkeypatch):
    """Record each read of the rules prose; the binding must not repeat it."""
    reads = []
    real = area_knowledge.printed_rules

    def spy(root):
        reads.append(root)
        return real(root)

    monkeypatch.setattr(area_knowledge, 'printed_rules', spy)
    return reads


def test_two_engine_constructions_read_rules_text_once(tmp_path, monkeypatch):
    reads = _spy_reads(monkeypatch)
    monkeypatch.setattr(area_knowledge, '_BINDINGS', {})
    first = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='area-perm-cache-first')
    second = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='area-perm-cache-second')
    assert len(reads) == 1
    assert (area_knowledge.saved_origin_permissions(first.engine.events)
            == area_knowledge.saved_origin_permissions(second.engine.events))


def test_binding_recomputes_when_the_file_version_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(area_knowledge, '_BINDINGS', {})
    reads = _spy_reads(monkeypatch)
    root, path = _rules_root(tmp_path, {'CLOUD': 'Create a cloud anywhere within range.'})
    assert area_knowledge.bind_origin_permissions(root) == {'CLOUD': 0}
    assert area_knowledge.bind_origin_permissions(root) == {'CLOUD': 0}
    assert len(reads) == 1
    # Same bytes, newer mtime: this is a new file version, so it is read again.
    later = path.stat().st_mtime_ns + 10 ** 9
    os.utime(path, ns=(later, later))
    assert area_knowledge.bind_origin_permissions(root) == {'CLOUD': 0}
    assert len(reads) == 2
    # New text: the binding follows the printed rule.
    path.write_text(json.dumps({'CLOUD': 'Create a cloud at a point you can see within range.'}))
    assert area_knowledge.bind_origin_permissions(root) == {}
    assert len(reads) == 3


def test_result_is_a_fresh_copy_equal_to_the_uncached_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(area_knowledge, '_BINDINGS', {})
    root, _ = _rules_root(tmp_path, {
        'CLOUD': 'Create a cloud anywhere within range.',
        'FLAME': 'Create a flame at a point you can see within range.',
        'GLOW': 'Make an object glow.'})
    expected = area_knowledge.origin_permissions_from_prose(area_knowledge.printed_rules(root))
    assert expected == {'CLOUD': 0}
    got = area_knowledge.bind_origin_permissions(root)
    assert got == expected
    got['CLOUD'] = 1
    got['EXTRA'] = 0
    assert area_knowledge.bind_origin_permissions(root) == expected
