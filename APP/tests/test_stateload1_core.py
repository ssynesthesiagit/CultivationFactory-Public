"""Synthetic table checkpoint/cache and phone DOM regressions; no live data/model."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
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
    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged compact read loaded a fight or enumerated choices')
    monkeypatch.setattr(combat, '_legal_candidates', forbidden)
    expected = table.state(session.match_id, fog=True, fog_view='own', include_menu=False)
    hits = table._state_reuse.hits
    assert table.state(session.match_id, fog=True, fog_view='own', include_menu=False) == expected
    assert table._state_reuse.hits == hits + 1
    assert expected['menu'] is None and expected['shapes'] == expected['button_states'] == {}


def test_checkpoint_suffix_matches_full_load_and_corrupt_snapshot_falls_back(tmp_path, monkeypatch):
    combat, session = setup(tmp_path)
    checkpoint = session.mechanical.explicit_snapshot()
    before = session.engine.state.state_version
    execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    table = TabletopService(combat, tmp_path)
    expected = table.state(session.match_id, fog=True, include_menu=False)
    actual = combat.read_presentation_session(session.match_id)
    assert actual.__class__.__name__ == 'PresentationSession'
    assert actual.engine.state.state_version > before
    assert actual.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')
    monkeypatch.setattr(combat, 'read_presentation_session', combat._load_session)
    table._state_reuse._entries.clear()
    table._state_reuse._bytes = 0
    assert json.dumps(table.state(session.match_id, fog=True, include_menu=False), sort_keys=True) == json.dumps(expected, sort_keys=True)
    monkeypatch.undo()
    checkpoint.write_text('{}')
    fallback = combat.read_presentation_session(session.match_id)
    assert fallback.__class__.__name__ != 'PresentationSession'
    assert fallback.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')


def test_checkpoint_engine_inputs_are_validated_once(tmp_path, monkeypatch):
    from combat import factory_compiler
    combat, session = setup(tmp_path)
    session.mechanical.explicit_snapshot()
    original = factory_compiler.register_bundle
    calls = []
    def counted(templates, actions, bundle):
        calls.append(bundle['actor_id'])
        return original(templates, actions, bundle)
    monkeypatch.setattr(factory_compiler, 'register_bundle', counted)
    loaded = combat.read_presentation_session(session.match_id)
    assert loaded.__class__.__name__ == 'PresentationSession'
    assert sorted(calls) == sorted(row['actor_id'] for row in loaded.engine.typed_bundle_documents)
    assert loaded.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')


def test_falsy_saved_inputs_are_not_silently_treated_as_missing(tmp_path):
    import pytest
    from combat.gate3_storage import TYPED_BUNDLES_FILE, ARENA_FILE
    from combat.portable_runtime_authority import RUNTIME_AUTHORITY_FILE
    from combat.saved_fight_format import UnsupportedSavedFight
    from combat.snapshot_read import _engine_inputs
    cases = [(TYPED_BUNDLES_FILE, None), (ARENA_FILE, None), (ARENA_FILE, {}), (RUNTIME_AUTHORITY_FILE, {})]
    for index, (name, document) in enumerate(cases):
        directory = tmp_path / str(index)
        directory.mkdir()
        (directory / name).write_text(json.dumps(document))
        with pytest.raises(UnsupportedSavedFight):
            _engine_inputs(directory)


def test_compact_cache_is_copied_bounded_and_invalidated_by_inputs_and_viewers(tmp_path):
    from combat.table_state_cache import StateReuse
    source, data = tmp_path / 'source', tmp_path / 'data'
    (source / 'combat').mkdir(parents=True)
    directory = data / 'match'
    directory.mkdir(parents=True)
    journal = directory / 'Journal.ndjson'
    journal.write_text('first')
    combat = SimpleNamespace(_match_dir=lambda mid: directory, _fingerprint=lambda mid: journal.read_text())
    reuse = StateReuse(per_match=8)
    inputs = lambda: (combat._fingerprint('fight'),)
    built = {'count': 0}

    def build_for(key):
        def build():
            built['count'] += 1
            return {'presentation': {'round': 1}, 'key': list(key)}
        return build

    key = ('fight', True, 'own', ('player',))
    first = reuse.read(key, build_for(key), inputs)
    first['presentation']['round'] = 99
    again = reuse.read(key, build_for(key), inputs)
    assert again['presentation']['round'] == 1
    assert built['count'] == 1
    reuse.read(('fight', False, 'own', ('player',)), build_for(key), inputs)
    reuse.read(('fight', True, 'own', ('other',)), build_for(key), inputs)
    assert built['count'] == 3
    journal.write_text('second')
    reuse.read(key, build_for(key), inputs)
    assert built['count'] == 4
    for index in range(12):
        reuse.read(('fight', index), build_for(('fight', index)), inputs)
    assert len([k for k in reuse._entries if k[0] == 'fight']) <= 8


def test_compact_cache_detects_journal_prefix_rewrite_with_real_fingerprint(tmp_path):
    import pytest
    from combat.gate5_service import CombatServiceError
    from combat.saved_fight_format import UNSUPPORTED_CODE
    combat, session = setup(tmp_path)
    # Persist a genuine journal event; setup may end on the player's initial turn.
    execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    session.mechanical.explicit_snapshot()
    table = TabletopService(combat, tmp_path)
    warm = table.state(session.match_id, fog=False, include_menu=False)
    journal_path = combat._match_dir(session.match_id) / 'Journal.ndjson'
    original_bytes = journal_path.read_bytes()
    assert len(original_bytes) > 512
    # Same length, same inode, same final bytes: only an earlier record changes.
    rewritten = b'!' * 64 + original_bytes[64:]
    assert len(rewritten) == len(original_bytes)
    assert rewritten[-512:] == original_bytes[-512:]
    hits = table._state_reuse.hits
    journal_path.write_bytes(rewritten)
    try:
        # The kept answer is never served for a journal whose prefix changed: the read reports the damaged record
        # instead of showing the old fight. Without the whole-journal identity this read would return the kept copy.
        with pytest.raises(CombatServiceError) as failure:
            table.state(session.match_id, fog=False, include_menu=False)
        assert failure.value.diagnostic.code == UNSUPPORTED_CODE
        assert table._state_reuse.hits == hits, 'a same-size journal prefix rewrite was answered from the kept copy'
    finally:
        journal_path.write_bytes(original_bytes)
    # The untouched fight rebuilds to exactly what it said before the rewrite.
    assert TabletopService(combat, tmp_path).state(session.match_id, fog=False, include_menu=False) == warm


def test_presentation_queries_share_only_one_unchanged_engine_and_reset_on_error():
    import pytest
    from combat.read_queries import memo, presentation_pass, pure
    first = SimpleNamespace(state=SimpleNamespace(state_version=1, event_sequence=2))
    second = SimpleNamespace(state=SimpleNamespace(state_version=1, event_sequence=2))
    calls = []

    @pure
    def query(engine):
        def compute():
            calls.append(engine)
            return object()
        return memo(engine, 'state-display', compute)

    with pytest.raises(RuntimeError), presentation_pass(first):
        shared = query(first)
        assert query(first) is shared
        query(second)
        with presentation_pass(first):
            assert query(first) is shared
        raise RuntimeError('projection failed')
    assert len(calls) == 2
    assert query(first) is not shared
    assert len(calls) == 3


def test_phone_paints_before_its_deferred_menu_and_ignores_late_reads(capsys):
    require_runtime_assets()
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
        str(Path(__file__).with_name('stateload1.test.mjs'))], capture_output=True, text=True, timeout=120)
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
