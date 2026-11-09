"""Pure read scopes remain bounded and preserve gameplay through cold reload."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import read_queries, recipients, senses, target_knowledge, targeting, zones
from combat.canonical import canonical_bytes
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def test_target_reason_shares_sight_and_resets_after_unversioned_input_changes(monkeypatch):
    # A real stock engine, with no disk writes needed for its construction.
    from combat.gate4_engine import Gate4ControllerEngine
    engine = Gate4ControllerEngine(ROOT, match_seed='SOL134-sight')
    viewer, target = list(engine.state.actors.values())[:2]
    viewer.position, target.position = Position(x=1, y=1), Position(x=2, y=1)
    calls = []
    original = senses.perceives
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(senses, 'perceives', counted)
    action = engine.action_catalog['system:combat.dodge'].model_copy(update={'target_kind': 'CREATURE'})
    assert targeting.reason(engine, viewer, target, action) is None
    assert len(calls) == 1  # previously three identical perceptions per target
    version = engine.state.state_version
    viewer.active = False
    assert targeting.reason(engine, viewer, target, action) == "Can't target: no line of sight."
    assert len(calls) == 2
    assert engine.state.state_version == version
    viewer.active = True
    assert targeting.reason(engine, viewer, target, action) is None
    assert len(calls) == 3
    recipient = action.model_copy(update={'target_kind': 'ANY_CREATURE', 'range_ft': 30})
    calls.clear()
    assert recipients.allowed(engine, viewer, target, recipient)
    assert len(calls) == 1  # targeting and knowledge formerly repeated this read


def test_fog_projection_collects_zones_once_and_resets_for_next_call(monkeypatch):
    from combat.gate4_engine import Gate4ControllerEngine
    engine = Gate4ControllerEngine(ROOT, match_seed='SOL134-fog')
    viewer = next(iter(engine.state.actors.values()))
    count = []
    original = zones._hooked_zones
    def hooked(e):
        count.append(1)
        return original(e)
    monkeypatch.setattr(zones, '_hooked_zones', hooked)
    first = senses.perception(engine, viewer)
    assert first['cells']
    assert len(count) == 1
    assert senses.perception(engine, viewer) == first
    assert len(count) == 2


def test_zone_queries_reuse_only_inside_pure_call_and_return_new_lists(monkeypatch):
    engine = SimpleNamespace(state=SimpleNamespace(zones={}))
    calls = []
    monkeypatch.setattr(zones, 'map_zones', lambda e: [])
    def hooked(e):
        calls.append(1)
        return [len(calls)]
    monkeypatch.setattr(zones, '_hooked_zones', hooked)
    @read_queries.pure
    def query(e):
        a = zones.typed_zones(e)
        a.clear()
        return zones.typed_zones(e)
    assert query(engine) == [1]
    assert query(engine) == [2]
    assert zones.typed_zones(engine) == [3]
    assert zones.typed_zones(engine) == [4]


def test_scopes_separate_engines_projected_objects_and_reset_on_error(monkeypatch):
    a, b = SimpleNamespace(), SimpleNamespace()
    viewer = SimpleNamespace(entity_id='viewer')
    target = SimpleNamespace(entity_id='target', position=1)
    projection = SimpleNamespace(entity_id='target', position=2)
    monkeypatch.setattr(senses, 'perceives', lambda e, v, t, **kw: t.position == 1)
    @read_queries.pure
    def query(e):
        assert target_knowledge.can_see(e, viewer, target)
        assert not target_knowledge.can_see(e, viewer, projection)
        assert read_queries.memo(e, ('same',), lambda: 'outer') == 'outer'
        assert nested(b) == 'inner'
        assert read_queries.memo(e, ('same',), lambda: 'wrong') == 'outer'
        raise ValueError('query failed')
    @read_queries.pure
    def nested(e):
        return read_queries.memo(e, ('same',), lambda: 'inner')
    with pytest.raises(ValueError, match='query failed'):
        query(a)
    assert read_queries.memo(a, ('same',), lambda: 'fresh') == 'fresh'
    target.position = 2
    assert not target_knowledge.can_see(a, viewer, target)


@pytest.mark.parametrize('component', ['action_origin_frame', 'state_version', 'event_sequence'])
def test_candidate_pass_key_separates_action_origin_and_recorded_changes(monkeypatch, component):
    engine = SimpleNamespace(state=SimpleNamespace(state_version=1, event_sequence=1),
                             _shot_geometry={})
    viewer = SimpleNamespace(entity_id='viewer')
    target = SimpleNamespace(entity_id='target', position=1)
    calls = []
    def perceives(e, v, t, **kwargs):
        calls.append(1)
        return t.position == 1
    monkeypatch.setattr(senses, 'perceives', perceives)
    with read_queries.candidate_pass(engine):
        assert target_knowledge.can_see(engine, viewer, target)
        assert target_knowledge.can_see(engine, viewer, target)
        assert len(calls) == 1
        target.position = 2
        if component == 'action_origin_frame':
            engine._shot_geometry = {}  # a different action or projected origin
        else:
            setattr(engine.state, component, 2)
        assert not target_knowledge.can_see(engine, viewer, target)
        assert len(calls) == 2
    assert not target_knowledge.can_see(engine, viewer, target)
    assert len(calls) == 3


def test_table_state_fog_and_sheet_match_uncached_reads_after_commit_reload(tmp_path, monkeypatch):
    from tests import h48_table_support as support
    owner = 'actor:factory.00000000-0000-0000-0000-000000000134'
    monkeypatch.setattr(support, 'OWNER', owner)
    combat, table, mid, send, commit = support.fixture(tmp_path, [], seed='SOL134-table')
    def capture():
        service = CombatService(ROOT, tmp_path)
        fresh = TabletopService(service, tmp_path)
        return canonical_bytes({'fog_off': fresh.state(mid, fog=False),
                                'fog_on': fresh.state(mid, fog=True),
                                'sheet': fresh.sheet(owner.removeprefix('actor:factory.'))})
    before = capture()
    with monkeypatch.context() as uncached:
        uncached.setattr(read_queries, 'memo', lambda e, k, compute: compute())
        uncached.setattr(target_knowledge, 'memo', lambda e, k, compute: compute())
        assert capture() == before
    commit(table.state(mid)['menu']['end_turn'])
    after = capture()
    with monkeypatch.context() as uncached:
        uncached.setattr(read_queries, 'memo', lambda e, k, compute: compute())
        uncached.setattr(target_knowledge, 'memo', lambda e, k, compute: compute())
        assert capture() == after
    support.assert_reload_verify_replay(combat, mid, tmp_path)
