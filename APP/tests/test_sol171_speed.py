"""Native volume reuse and service decisions without JSON revalidation."""
from copy import deepcopy

from combat import space, spatial_areas, volume_queries
from combat.canonical import canonical_bytes
from combat.footprints import ActorFootprintDefinition
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ME, duel
from tests.test_tabletop_speed import ROOT, _fight, _to_the_humans_turn


def test_native_volume_and_positions_reuse_exact_inputs(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    native = ActorFootprintDefinition.occupied_cells
    calls = []
    def counted(*args):
        calls.append(1)
        return native(*args)
    monkeypatch.setattr(ActorFootprintDefinition, 'occupied_cells', counted)
    before = canonical_bytes(engine.state.model_dump(mode='json'))
    first = spatial_areas.actor_positions(engine, actor)
    assert spatial_areas.actor_positions(engine, actor) is first
    assert len(calls) == 1
    assert canonical_bytes(engine.state.model_dump(mode='json')) == before
    clone = deepcopy(engine)
    assert spatial_areas.actor_positions(clone, clone.state.actors[ME]) == first
    assert len(calls) == 2  # copied authority is an independently bound input


def test_volume_binds_replaced_footprints_actual_anchor_and_altitude():
    engine = duel([])
    actor = engine.state.actors[ME]
    first = spatial_areas.actor_positions(engine, actor)
    actor.position = Position(x=actor.position.x+2, y=actor.position.y, z=2)
    assert spatial_areas.actor_positions(engine, actor) != first
    engine.actor_footprints[ME] = ActorFootprintDefinition.rectangle(
        2, 2, footprint_id='test:large', source_definition_id='test:large')
    actual = spatial_areas.actor_positions(engine, actor)
    assert len(actual) == 8
    assert actual == tuple(space.position(cell) for cell in space._volume(actor.position, engine._footprint(actor)))
    assert spatial_areas.actor_positions(engine, actor, at=Position(x=3, y=3)) != actual


def test_unknown_mutable_footprint_uses_native_derivation_each_time():
    class Custom:
        size = 1
        def occupied_cells(self, anchor):
            return tuple((anchor[0]+x, anchor[1]) for x in range(self.size))
    custom = Custom()
    assert space.volume((3, 3, 1), custom) == ((3, 3, 1),)
    custom.size = 2
    assert space.volume((3, 3, 1), custom) == ((3, 3, 1), (3, 3, 2), (4, 3, 1), (4, 3, 2))


def test_native_model_copy_with_mutable_cells_does_not_enter_the_index():
    fp = ActorFootprintDefinition.rectangle(1, 1, footprint_id='test:mutable', source_definition_id='test:mutable')
    cells = [Position(x=0, y=0)]
    unchecked = fp.model_copy(update={'occupied_relative_cells': cells})
    assert space.volume((3, 3, 1), unchecked) == ((3, 3, 1),)
    cells.append(Position(x=1, y=0))
    assert space.volume((3, 3, 1), unchecked) == ((3, 3, 1), (3, 3, 2), (4, 3, 1), (4, 3, 2))


def test_volume_index_entry_and_cell_budgets(monkeypatch):
    # Count the whole process-local index, which may contain other test inputs.
    monkeypatch.setattr(volume_queries, 'MAX_ENTRIES', 2)
    monkeypatch.setattr(volume_queries, 'MAX_VOLUME_CELLS', 16)
    fp = ActorFootprintDefinition.rectangle(2, 2, footprint_id='test:bound', source_definition_id='test:bound')
    for x in range(10):
        anchor = (x, 3, 1)
        assert space.volume(anchor, fp) == space._volume(anchor, fp)
        assert len(volume_queries._volumes) <= 2
        assert volume_queries._volume_cells <= 16


def test_large_and_non_native_position_sequences_fall_back():
    calls = []
    def native(cell):
        calls.append(cell)
        return space.position(cell)
    cells = tuple((x, 0, 0) for x in range(volume_queries.MAX_POSITION_VOLUME+1))
    assert volume_queries.positions(cells, native) == tuple(space.position(c) for c in cells)
    assert volume_queries.positions(cells, native) == tuple(space.position(c) for c in cells)
    assert len(calls) == 2*len(cells)
    assert volume_queries.positions([(1, 2, 3)], native) == (Position(x=1, y=2, z=3),)


def test_table_commit_uses_native_context_and_reload_is_exact(tmp_path, monkeypatch):
    combat, table, mid = _fight(tmp_path, seed='SOL171-TABLE')
    state, after = _to_the_humans_turn(table, mid)
    session = combat._load_session(mid)
    expected = combat.decision(mid, session=session)['context']
    response = combat.decision(mid, session=session)
    response['context']['legal_candidates'].clear()
    from combat.gate4_models import DecisionContext
    def forbidden(*args, **kwargs):
        raise AssertionError('server-built context must not be serialized and revalidated')
    monkeypatch.setattr(DecisionContext, 'model_validate', forbidden)
    menu = state['menu']
    result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], after)
    assert result['status'] == 'COMMITTED'
    native = combat._decision_model(session)
    assert native.legal_candidates
    assert canonical_bytes(native.model_dump(mode='json', by_alias=True)) == canonical_bytes(expected)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
    assert fresh.engine.state.state_version == result['state']['menu']['state_version']


def test_preview_copies_events_without_shared_payloads(tmp_path):
    combat, table, mid = _fight(tmp_path, seed='SOL171-CLONE')
    session = combat._load_session(mid)
    clone = combat._clone_engine(ROOT, session.engine)
    assert clone.events == session.engine.events and clone.rolls == session.engine.rolls
    clone.events[0].payload['test-only'] = ['detached']
    assert 'test-only' not in session.engine.events[0].payload


def test_automatic_table_header_preserves_full_view_without_context_serialization(tmp_path, monkeypatch):
    combat, table, mid = _fight(tmp_path, seed='SOL171-HEADER')
    state, _ = _to_the_humans_turn(table, mid)
    combat.set_controller_mode(mid, actor_id=state['menu']['actor_id'], controller_mode='LOCAL_AUTO')
    # Full context remains the default API contract, even for automatic actors.
    full = combat.decision(mid)
    expected = table._menu(full, {})
    expected = {key: expected[key] for key in ('decision_id', 'state_version', 'actor_id', 'control_mode', 'manual')}
    from combat.gate4_models import DecisionContext
    def forbidden(*args, **kwargs):
        raise AssertionError('automatic table must not serialize a discarded full context')
    monkeypatch.setattr(DecisionContext, 'model_dump', forbidden)
    fresh_table = type(table)(CombatService(ROOT, tmp_path), tmp_path)
    assert fresh_table.state(mid)['menu'] == expected
    fresh = combat._load_session(mid)
    assert combat._legal_candidates(fresh)  # native enumeration is retained, not shifted out of wait samples
