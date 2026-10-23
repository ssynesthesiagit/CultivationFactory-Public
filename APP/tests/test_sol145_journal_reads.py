"""Exact controller presentation, including edits and committed reloads."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import journal_reads
from combat.gate4_persistence import _read_jsonl
from combat.gate5_service import CombatService
from combat.weapon_delivery import available_weapons


@pytest.fixture(autouse=True)
def clear_cache():
    journal_reads._CACHE.clear()
    yield
    journal_reads._CACHE.clear()


def test_append_only_decodes_new_rows_and_returns_independent_values(tmp_path, monkeypatch):
    path = tmp_path / 'journal'
    path.write_text('\n'.join(json.dumps({'n': n, 'nested': [n]}) for n in range(30)) + '\n')
    expected = _read_jsonl(path)[-12:]
    result = journal_reads.read_tail(path)
    assert result == expected
    result[0]['nested'].append('changed')
    original = json.loads
    calls = []
    def tracked(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(journal_reads.json, 'loads', tracked)
    assert journal_reads.read_tail(path) == expected
    assert calls == []
    with path.open('a') as stream:
        stream.write(' \n{"n": 30, "nested": [30]}\n')
    assert journal_reads.read_tail(path) == (expected + [{'n': 30, 'nested': [30]}])[-12:]
    assert len(calls) == 1


@pytest.mark.parametrize('contents', [
    '{"n":1}\n{"n":2}\n', '{"n":1}\r\n \r\n{"n":2}\r\n',
    '{"n":1}\r{"n":2}', '{"n":1}\u2028{"n":2}\n', '', '\n \n',
])
@pytest.mark.parametrize('limit', [0, -1, 1, 12, 30])
def test_limits_newlines_and_partial_final_rows(tmp_path, contents, limit):
    path = tmp_path / 'journal'
    path.write_text(contents)
    for _ in range(2):
        assert journal_reads.read_tail(path, limit) == _read_jsonl(path)[-limit:]
    with path.open('a') as stream:
        stream.write('\n{"n":3}\n')
    assert journal_reads.read_tail(path, limit) == _read_jsonl(path)[-limit:]


def test_prefix_rewrites_truncation_replacement_missing_and_invalid_rows(tmp_path):
    path = tmp_path / 'journal'
    for text in ('{"n":1}\n{"n":2}\n', '{"n":9}\n{"n":2}\n', '{"n":9}\n'):
        path.write_text(text)
        assert journal_reads.read_tail(path) == _read_jsonl(path)
    replacement = tmp_path / 'replacement'
    replacement.write_text('{"n":8}\n')
    replacement.replace(path)
    assert journal_reads.read_tail(path) == [{'n': 8}]
    path.write_text('bad\n' + '{"n":0}\n' * 20)
    with pytest.raises(json.JSONDecodeError):
        journal_reads.read_tail(path)  # Invalid early rows cannot hide outside the tail.
    path.write_text('{"n":4}\n')
    assert journal_reads.read_tail(path) == [{'n': 4}]
    path.unlink()
    assert journal_reads.read_tail(path) == []


def test_cache_budget_and_larger_tail(tmp_path, monkeypatch):
    path = tmp_path / 'journal'
    path.write_text('\n'.join(json.dumps({'n': n}) for n in range(40)) + '\n')
    for limit in (1, 20, 3):
        assert journal_reads.read_tail(path, limit) == _read_jsonl(path)[-limit:]
    monkeypatch.setattr(journal_reads, '_BUDGET', 1)
    assert journal_reads.read_tail(path) == _read_jsonl(path)[-12:]
    assert not journal_reads._CACHE


def test_weapon_query_skips_foreign_metadata_and_keeps_possession_live():
    class Foreign:
        owner_id = 'other'
        @property
        def parameters(self):
            raise AssertionError('foreign weapon metadata must not be inspected')
    own = SimpleNamespace(owner_id='a', source_definition_id='own.weapon.one',
                          parameters={'typed': {'weapon': { 'properties': 'Light'}}}, display_name='Sword')
    actor = SimpleNamespace(entity_id='a', conditions={})
    engine = SimpleNamespace(action_catalog={'foreign': Foreign(), 'own': own},
                             state=SimpleNamespace(actors={'a': actor}))
    assert available_weapons(engine, actor) == {'own.weapon.one': own}
    actor.conditions['drop'] = SimpleNamespace(data={'disables_action': own.source_definition_id, 'dropped_at': [1, 1]}, condition_id='drop')
    assert available_weapons(engine, actor) == {}
    assert available_weapons(engine, actor, include_busy=True) == {}
    actor.conditions.clear()
    assert available_weapons(engine, actor, ('sword',)) == {'own.weapon.one': own}


def test_controller_tail_after_table_commit_and_fresh_reload(tmp_path):
    from tests.hunt51_grapple_support import fight, send
    _, service, table, mid, _ = fight(tmp_path, 'sol145', ask=False)
    session = service._load_session(mid)
    assert service._controller_rows(session) == _read_jsonl(session.controller_journal_path)[-12:]
    send(table, mid)
    loaded = CombatService(Path(__file__).resolve().parents[1], service.userdata_root)._load_session(mid)
    assert service._controller_rows(loaded) == _read_jsonl(loaded.controller_journal_path)[-12:]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
