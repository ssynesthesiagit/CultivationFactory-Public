"""SPEED2: pure enumeration indexes expire before any later menu or action."""
from copy import copy

import pytest

from combat import ext, rule_help
from combat.ext import objects
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.read_queries import candidate_pass
from tests.h1_support import duel, ME, ROOT


def _wall(engine):
    obj = RuntimeObjectState(object_id='object:speed2', object_kind='TEST',
        position=Position(x=1, y=1), unattended=True, flammable=False,
        ac=12, current_hp=10, maximum_hp=10, component={'blocks': True})
    engine.state.objects[obj.object_id] = obj
    return obj


def test_blocking_walls_are_built_once_per_enumeration_revision():
    engine = duel([])
    obj = _wall(engine)
    with candidate_pass(engine):
        first = objects.blocking_zones(engine)
        again = objects.blocking_zones(engine)
        assert first == again and first is not again
        assert first[0] is again[0], 'unchanged walls must not be reconstructed/validated per query'
        # Caller-owned lists cannot spoil the next query.
        again.clear()
        assert objects.blocking_zones(engine) == first
        obj.destroyed = True
        engine.state.event_sequence += 1
        assert objects.blocking_zones(engine) == []
    obj.destroyed = False  # unrecorded test edit: next scope must observe it
    with candidate_pass(engine):
        assert objects.blocking_zones(engine)[0] is not first[0]
    # Independent calls, engines and shallow projected states never inherit it.
    assert objects.blocking_zones(engine)[0] is not objects.blocking_zones(engine)[0]
    with candidate_pass(engine):
        view = copy(engine)
        assert objects.blocking_zones(view)[0] is not objects.blocking_zones(view)[0]


def test_owner_catalog_is_walked_once_and_rechecked_on_next_pass():
    from combat.catalog_queries import owned_actions
    engine = duel([])
    walks = []
    class Catalog(dict):
        def values(self):
            walks.append(1)
            return super().values()
    engine.action_catalog = Catalog(engine.action_catalog)
    with candidate_pass(engine):
        first = owned_actions(engine, ME)
        for _ in range(8):
            assert owned_actions(engine, ME) is first
        assert len(walks) <= 2
    for source in list(engine.action_catalog):
        engine.action_catalog[source] = engine.action_catalog.pop(source)
    # Reverse the whole catalog without advancing the recorded state clock.
    engine.action_catalog = Catalog(reversed(list(engine.action_catalog.items())))
    with candidate_pass(engine):
        assert owned_actions(engine, ME) == tuple(reversed(first))


def _probe(monkeypatch, point, functions):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, point, functions)
    monkeypatch.setattr(ext, '_FILTERED_POINTS', {*ext._FILTERED_POINTS, point})


def test_active_hook_index_is_ordered_and_revision_scoped(monkeypatch):
    engine = duel([])
    seen, checks = [], []
    def absent(*args):
        pytest.fail('an absent provider was dispatched')
    def first(*args):
        seen.append('first')
        return False
    def last(*args):
        seen.append('last')
        return True
    def present(e):
        checks.append(e.state.event_sequence)
        return False
    _probe(monkeypatch, 'speed2_probe', [first, absent, last])
    monkeypatch.setitem(ext._HOOK_PRESENT, ('speed2_probe', absent), present)
    with candidate_pass(engine):
        assert ext.any_false('speed2_probe', engine)
        assert ext.run('speed2_probe', engine) == [False, True]
        assert seen == ['first', 'last', 'first', 'last']  # no veto short circuit
        assert len(checks) == 1
        engine.state.event_sequence += 1
        assert ext.run_strict('speed2_probe', engine) == [False, True]
        assert len(checks) == 2
    with candidate_pass(engine):
        ext.run('speed2_probe', engine)
    assert len(checks) == 3


def test_pure_hook_replies_are_keyed_by_actor_action_and_projection(monkeypatch):
    from combat.hook_queries import actor_action
    engine = duel([])
    actor = engine.state.actors[ME]
    action = engine.action_catalog[actor.action_ids[0]]
    calls = []
    def provider(e, a, candidate, action):
        calls.append((a.position, action))
        return False
    _probe(monkeypatch, 'speed2_reply', [provider])
    monkeypatch.setitem(ext._HOOK_QUERY_KEYS, ('speed2_reply', provider), actor_action)
    with candidate_pass(engine):
        assert ext.run('speed2_reply', engine, actor, None, action) == [False]
        assert ext.any_false('speed2_reply', engine, actor, object(), action)
        assert len(calls) == 1
        original = actor.position
        actor.position = Position(x=original.x + 1, y=original.y)
        ext.run('speed2_reply', engine, actor, None, action)
        assert len(calls) == 2
        actor.position = original
        engine.state = engine.state.model_copy()
        ext.run('speed2_reply', engine, actor, None, action)
        assert len(calls) == 3
    ext.run('speed2_reply', engine, actor, None, action)
    assert len(calls) == 4


@pytest.mark.parametrize('error', [RuntimeError, ext.CheckpointError, ext.ControllerPause])
def test_errors_and_player_pauses_are_never_cached(monkeypatch, error):
    engine = duel([])
    calls = []
    def broken(*args):
        calls.append(1)
        raise error('probe')
    _probe(monkeypatch, 'speed2_error', [broken])
    monkeypatch.setitem(ext._HOOK_QUERY_KEYS, ('speed2_error', broken), lambda *a: ())
    monkeypatch.setattr(ext, '_log', lambda *a: None)
    with candidate_pass(engine):
        for _ in range(2):
            if error is RuntimeError:
                assert ext.run('speed2_error', engine) == []
            else:
                with pytest.raises(error):
                    ext.run('speed2_error', engine)
    assert len(calls) == 2


def test_invalid_cache_metadata_cannot_bypass_a_provider_veto(monkeypatch):
    engine = duel([])
    calls = []
    def provider(*args):
        calls.append(1)
        return False
    _probe(monkeypatch, 'speed2_bad_key', [provider])
    monkeypatch.setitem(ext._HOOK_QUERY_KEYS, ('speed2_bad_key', provider), lambda *a: [])
    with candidate_pass(engine):
        assert ext.any_false('speed2_bad_key', engine)
        assert ext.any_false('speed2_bad_key', engine)
    assert len(calls) == 2


def test_editable_text_is_read_once_but_refreshes_on_the_next_menu(tmp_path, monkeypatch):
    path = tmp_path / 'rules.json'
    path.write_text('{"ability":"first"}')
    monkeypatch.setattr(rule_help, 'RULES_PATH', path)
    engine = duel([])
    with candidate_pass(engine):
        assert rule_help.printed_rule_text('ability') == 'first'
        path.write_text('{"ability":"next"}')
        assert rule_help.printed_rule_text('ability') == 'first'
    assert rule_help.printed_rule_text('ability') == 'next'
    with candidate_pass(engine):
        assert rule_help.printed_rule_text('ability') == 'next'


def test_real_service_menu_constructs_walls_once_then_commits_and_reloads(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import ZoneState
    from tests.worker2_support import fixture, settle
    native = CombatService.factory_arenas
    def arenas(self, **kwargs):
        result = native(self, **kwargs)
        key = 'battlefield:factory_pillar_arena'
        result[key] = {**result[key], 'map_objects': [{'id': 987, 'kind': 'door', 'x': 1, 'y': 1}]}
        return result
    monkeypatch.setattr(CombatService, 'factory_arenas', arenas)
    combat, table, mid = fixture(tmp_path, ['DARK_BASE_DARKNESS'])
    session = combat._load_session(mid)
    assert any(obj.component.get('blocks') for obj in session.engine.state.objects.values())
    calls = []
    init = ZoneState.__init__
    def counted(self, *args, **kwargs):
        if kwargs.get('zone_id', '').startswith('zone:object:'):
            calls.append(kwargs['zone_id'])
        init(self, *args, **kwargs)
    monkeypatch.setattr(ZoneState, '__init__', counted)
    candidates = CombatService(ROOT, tmp_path)._legal_candidates(session)
    assert any(c.destination is not None and c.kind.value != 'MOVE' for c in candidates)
    assert calls and len(calls) == len(set(calls)), 'walls rebuilt inside one service menu'
    hold = next(c.candidate_id for c in candidates if c.source_definition_id == 'system:combat.hold_position')
    settle(table, mid, hold)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert table.state(mid)['menu']
