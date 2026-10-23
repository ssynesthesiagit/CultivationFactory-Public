"""Printed-text caching must preserve live edits and complete saved AI journals."""
import json
import os
from pathlib import Path

import pytest

from combat import rule_help
from combat.canonical import canonical_bytes
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import _install

ROOT = Path(__file__).resolve().parents[1]


def test_repeated_printed_text_lookup_does_not_resolve_paths(monkeypatch):
    resolve = Path.resolve
    calls = []

    def counted(path, *args, **kwargs):
        calls.append(path)
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', counted)
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    for key, text in texts.items():
        assert rule_help.printed_rule_text(key) == str(text or '')
    key = next(iter(texts))
    for _ in range(100):
        assert rule_help.printed_rule_text(key) == str(texts[key] or '')
    assert calls == []


def test_printed_text_cache_keys_include_path_and_same_mtime_replacement(tmp_path, monkeypatch):
    one = tmp_path / 'one.json'
    two = tmp_path / 'two.json'
    one.write_text('{"key":"one"}')
    two.write_text('{"key":"two"}')
    stamp = one.stat().st_mtime_ns
    os.utime(two, ns=(stamp, stamp))
    monkeypatch.setattr(rule_help, 'RULES_PATH', one)
    assert rule_help.printed_rule_text('key') == 'one'
    monkeypatch.setattr(rule_help, 'RULES_PATH', two)
    assert rule_help.printed_rule_text('key') == 'two'
    replacement = tmp_path / 'replacement.json'
    replacement.write_text('{"key":"new"}')
    os.utime(replacement, ns=(stamp, stamp))
    replacement.replace(two)
    assert rule_help.printed_rule_text('key') == 'new'
    assert rule_help.printed_rule_text('missing') == ''
    two.write_text('{"key":"edit"}')
    os.utime(two, ns=(stamp, stamp))
    assert rule_help.printed_rule_text('key') == 'edit'
    two.unlink()
    with pytest.raises(FileNotFoundError):
        rule_help.printed_rule_text('key')  # no stale text after deletion


def test_cached_printed_rules_match_stock_ai_events_after_table_commit_and_reload(tmp_path, monkeypatch):
    path = ROOT / 'authority/typed_mechanics/rules_text.json'
    stock_texts = json.loads(path.read_text())
    cached = rule_help.printed_rule_text
    journals = []
    path_resolutions = []
    resolve = Path.resolve

    def counted(path, *args, **kwargs):
        if path == Path(rule_help.__file__):
            path_resolutions.append(path)
        return resolve(path, *args, **kwargs)

    for name, lookup in [('stock', lambda key: str(stock_texts.get(key) or '')), ('cached', cached)]:
        monkeypatch.setattr(rule_help, 'printed_rule_text', lookup)
        if name == 'cached':
            monkeypatch.setattr(Path, 'resolve', counted)
        user = tmp_path / name
        _install(user, 'left')
        _install(user, 'right')
        service = CombatService(ROOT, user)
        table = TabletopService(service, user)
        mid = service.create_factory_match(project_ids=['left'],
            opponent_actor_ids=['actor:factory.right'], match_seed='SOL96-STOCK', maximum_rounds=1)['match_id']
        state = table.state(mid)
        for step in range(50):
            if state['presentation'].get('terminal'):
                break
            response = table.auto_step(mid, state['last_sequence'], [])
            assert response['status'] in ('COMMITTED', 'TERMINAL')
            state = response['state']
            if step == 1:
                service = CombatService(ROOT, user)
                table = TabletopService(service, user)
                assert table.state(mid)['last_sequence'] == state['last_sequence']
        assert state['presentation'].get('terminal')
        session = service._load_session(mid)
        assert session.verify()['status'] == 'PASS'
        assert session.mechanical.replay()['status'] == 'PASS'
        journals.append(canonical_bytes([event.model_dump(mode='json') for event in session.engine.events]))
    assert journals[0] == journals[1]
    assert path_resolutions == []  # candidate admission must not repeat filesystem traversal
