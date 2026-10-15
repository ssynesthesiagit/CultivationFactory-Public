"""Synthetic table checkpoint/cache and phone DOM regressions; no live data/model."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.snapshot_cache import SnapshotCache
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.stateload1_node_support import require_runtime_assets

ME = 'actor:factory.a0000000-0000-4000-8000-000000000001'
FOE = 'actor:factory.a0000000-0000-4000-8000-000000000002'


def execute(session, candidate):
    return session.mechanical.execute_intent(ActionIntent(intent_id=f'stateload-{session.engine.state.state_version}',
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))


def setup(tmp_path):
    document = sheet([], cl=1)
    combat = CombatService(ROOT, tmp_path)
    arena = to_battlefield(normalize_map({'display_name': 'Snapshot courtyard', 'width_squares': 12,
        'height_squares': 12, 'objects': [{'id': 1, 'kind': 'door', 'name': 'Wooden door',
            'x': 4, 'y': 6, 'interaction': 'simple_door', 'door_open': 0,
            'door_locked': 0, 'door_jammed': 0}]}))
    bundles = [compile_character(document, actor_id=actor) for actor in (ME, FOE)]
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME:'team:a', FOE:'team:b'},
        {ME:{'x':3,'y':6}, FOE:{'x':6,'y':6}}, arena, [ME], [FOE],
        control_modes={ME:'MANUAL',FOE:'MANUAL'}, match_seed='STATELOAD1',
        display_name='Snapshot courtyard', maximum_rounds=5)['match_id']
    session = combat._load_session(mid)
    if session.engine.state.current_actor_id != ME:
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    return combat, session


def test_snapshot_read_has_no_candidates_and_unchanged_read_does_not_load_again(tmp_path, monkeypatch):
    combat, session = setup(tmp_path)
    session.mechanical.explicit_snapshot()
    table = TabletopService(combat, tmp_path)
    expected = table.state(session.match_id, fog=True, fog_view='own', include_menu=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged compact read loaded a fight or enumerated choices')
    monkeypatch.setattr(combat, 'read_presentation_session', forbidden)
    monkeypatch.setattr(combat, '_legal_candidates', forbidden)
    assert table.state(session.match_id, fog=True, fog_view='own', include_menu=False) == expected
    assert expected['menu'] is None and expected['shapes'] == expected['button_states'] == {}


def test_checkpoint_suffix_matches_full_load_and_corrupt_snapshot_falls_back(tmp_path, monkeypatch):
    combat, session = setup(tmp_path)
    checkpoint = session.mechanical.explicit_snapshot()
    execute(session, next(c for c in session.engine.legal_candidates()
                         if c.source_definition_id.startswith('system:door.open.')))
    table = TabletopService(combat, tmp_path)
    expected = table.state(session.match_id, fog=True, include_menu=False)
    actual = combat.read_presentation_session(session.match_id)
    assert actual.__class__.__name__ == 'PresentationSession'
    assert actual.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')
    monkeypatch.setattr(combat, 'read_presentation_session', combat._load_session)
    table._snapshot_cache.rows.clear()
    assert json.dumps(table.state(session.match_id, fog=True, include_menu=False), sort_keys=True) == json.dumps(expected, sort_keys=True)
    monkeypatch.undo()
    checkpoint.write_text('{}')
    fallback = combat.read_presentation_session(session.match_id)
    assert fallback.__class__.__name__ != 'PresentationSession'
    assert fallback.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')


def test_compact_cache_is_copied_bounded_and_invalidated_by_inputs_and_viewers(tmp_path):
    source, data = tmp_path / 'source', tmp_path / 'data'
    (source / 'combat').mkdir(parents=True)
    directory = data / 'match'
    directory.mkdir(parents=True)
    journal = directory / 'Journal.ndjson'
    journal.write_text('first')
    combat = SimpleNamespace(_match_dir=lambda mid: directory, _fingerprint=lambda mid: journal.read_text())
    cache = SnapshotCache(source, data)
    key = lambda **kw: cache.key(combat, 'fight', kw.get('fog', True), 'own', kw.get('viewers', ('player',)))
    first = key()
    cache.put(first, {'presentation': {'round':1}})
    cache.get(first)['presentation']['round'] = 99
    assert cache.get(first)['presentation']['round'] == 1
    assert key(fog=False) != first and key(viewers=('other',)) != first
    for path in (directory / 'controls.json', directory / 'pending.json', source / 'combat' / 'new_rule.json'):
        previous = key()
        path.write_text('{}')
        assert key() != previous
    previous = key()
    journal.write_text('second')
    assert key() != previous
    for index in range(12):
        cache.put((index,), {'index':index})
    assert len(cache.rows) == 8


def test_phone_paints_before_its_deferred_menu_and_ignores_late_reads(capsys):
    require_runtime_assets()
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
        str(Path(__file__).with_name('stateload1.test.mjs'))], capture_output=True, text=True, timeout=120)
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
