"""Flight read frames reuse area inputs and expire before the next position."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from combat import ext, flight, flight_decision, zones, menu_rank
from combat.gate2_runtime_models import Position
from tests.h1_support import ME, duel
from tests.test_ai_flight_options import flyer_fight


def test_flight_condition_gates_share_zones_only_during_one_profile(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    for i in range(4):
        engine._apply_condition(actor, 'condition:typed.test_flight', f'test:{i}', ME,
                                expires_on='END_OF_CURRENT_TURN', data={'fly_speed_ft': 30})
    original = ext.run_strict
    collections = []
    original_map = zones.map_zones
    def collect(e):
        collections.append(e.state.actors[ME].position)
        return original_map(e)
    def gates(name, *args, **kwargs):
        if name == 'flight_grant_allowed':
            zones.typed_zones(args[0])
            zones.typed_zones(args[0])
        return original(name, *args, **kwargs)
    monkeypatch.setattr(zones, 'map_zones', collect)
    monkeypatch.setattr(ext, 'run_strict', gates)
    before = deepcopy(engine.state.model_dump(mode='json'))
    expected = getattr(flight.profile, '__wrapped__', flight.profile)(engine, actor)
    reference_calls = len(collections)
    collections.clear()
    assert flight.profile(engine, actor) == expected
    assert len(collections) == 1 < reference_calls
    actor.position = actor.position.model_copy(update={'z': 2})
    flight.profile(engine, actor)
    assert collections == [Position(**before['actors'][ME]['position']), actor.position]
    # Unrecorded input changes are visible immediately; no state-version cache.
    actor.conditions.clear()
    assert flight.profile(engine, actor).speed_ft == actor.fly_speed_ft


def test_position_safety_shares_inputs_but_never_leaks_after_error(monkeypatch):
    from combat import falling
    engine = duel([])
    actor = engine.state.actors[ME]
    collections = []
    monkeypatch.setattr(zones, 'map_zones', lambda e: collections.append(actor.position) or [])
    def required(e, a):
        zones.typed_zones(e)
        return False
    def profile(e, a):
        zones.typed_zones(e)
        return flight.Profile(speed_ft=30)
    monkeypatch.setattr(falling, 'required', required)
    monkeypatch.setattr(flight, 'profile', profile)
    assert flight_decision._position_safety(engine, actor, True) == (False, flight.Profile(speed_ft=30))
    assert len(collections) == 1
    def abort(e, a):
        zones.typed_zones(e)
        raise RuntimeError('aborted projection')
    monkeypatch.setattr(falling, 'required', abort)
    with pytest.raises(RuntimeError):
        flight_decision._position_safety(engine, actor, True)
    zones.typed_zones(engine)
    assert len(collections) == 3


def test_table_flight_response_matches_unscoped_queries_and_reloads(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **k: None))
    combat, table, mid, runner = flyer_fight(tmp_path, height=2)
    from tests.test_agent_seats import raw_state
    expected = raw_state(runner, mid)
    with monkeypatch.context() as m:
        m.setattr(flight, 'profile', flight.profile.__wrapped__)
        m.setattr(flight_decision, '_position_safety', flight_decision._position_safety.__wrapped__)
        combat._derived.clear()
        combat._menu_rank_scores.clear()
        assert raw_state(runner, mid) == expected
    combat._derived.clear()
    assert raw_state(runner, mid) == expected
    # Execute a normal table action and verify the recorded boundary reloads.
    menu = expected['menu']
    table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], expected['last_sequence'], [])
    assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_terrain_source_reads_once_per_nested_request_and_refreshes(tmp_path, monkeypatch):
    from pathlib import Path
    from combat.tabletop_service import _one_at_a_time
    path = tmp_path / 'terrain.json'
    path.write_text('{"version": 1}')
    monkeypatch.setattr(zones, 'RULES_PATH', path)
    original = Path.read_text
    reads = []
    def counted(p, *args, **kwargs):
        if p == path:
            reads.append(1)
        return original(p, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', counted)
    class Table:
        @_one_at_a_time
        def nested(self, mid):
            return zones.terrain_rules()
        @_one_at_a_time
        def request(self, mid):
            first = self.nested(mid)
            path.write_text('{"version": 2}')
            assert all(zones.terrain_rules() is first for _ in range(100))
            assert self.nested(mid) is first
            return first
    table = Table()
    assert table.request('test')['version'] == 1
    assert len(reads) == 1
    assert table.nested('test')['version'] == 2
    with pytest.raises(RuntimeError), zones.terrain_snapshot():
        assert zones.terrain_rules()['version'] == 2
        raise RuntimeError('request failed')
    path.write_text('{"version": 3}')
    assert zones.terrain_rules()['version'] == 3
    # Outside a request, callers retain fresh independent mutable documents.
    zones.terrain_rules()['version'] = 4
    assert zones.terrain_rules()['version'] == 3
