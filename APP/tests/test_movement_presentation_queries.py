"""Movement cards reuse read-only geometry within one real table answer only."""
import pytest

from combat import ext, movement_presentation, zones
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import ROOT, act, table_match


def test_table_cards_reuse_geometry_without_changing_menu_commit_or_reload(monkeypatch, tmp_path):
    combat, table, mid = table_match(tmp_path)
    ext.effects()

    def terrain(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED':
            from combat.typed_executor import Context
            from types import SimpleNamespace
            actor = engine.state.actors[kwargs['actor_id']]
            foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
            engine._apply_condition(actor, 'condition:typed.frightened', 'test:fear', foe.entity_id,
                                    expires_on='END_OF_HOLDER_NEXT_TURN')
            ctx = Context(engine, foe, SimpleNamespace(source_definition_id='test:terrain'),
                          None, {'numbers': {}}, [actor], actor, {})
            zones.create(ctx, {'name': 'Sticky ground', 'shape': 'sphere', 'size_ft': 10,
                               'difficult': 'hostile', 'duration': {}})
        elif event == 'MOVEMENT_COMMITTED':
            for zone in list(engine.state.zones.values()):
                if zone.source_definition_id == 'test:terrain':
                    zones.remove(engine, zone, 'TEST_TERRAIN_END')

    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), terrain])
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    # Count costly zone production, rather than a flaky wall-clock threshold.
    produced = []
    terrain_prices = []
    monkeypatch.setitem(ext._HOOKS, 'zones', [*ext._HOOKS.get('zones', []),
                                             lambda engine: produced.append(1) or []])
    monkeypatch.setitem(ext._HOOKS, 'difficult_zone_exempt',
                        [*ext._HOOKS.get('difficult_zone_exempt', []),
                         lambda engine, actor, zone: terrain_prices.append(1) or None])
    optimized = movement_presentation.for_menu
    counts = []

    def measured(function):
        def cards(*args):
            before = len(produced)
            prices_before = len(terrain_prices)
            result = function(*args)
            counts.append((len(produced) - before, len(terrain_prices) - prices_before))
            return result
        return cards

    monkeypatch.setattr(movement_presentation, 'for_menu', measured(optimized.__wrapped__))
    reference = table.state(mid)
    uncached_calls = counts[-1]
    monkeypatch.setattr(movement_presentation, 'for_menu', measured(optimized))
    actual = table.state(mid)
    assert actual == reference  # Includes every card, candidate ID and option.
    assert min(uncached_calls) >= 12 * 8
    assert counts[-1] == (1, 1)
    cards = actual['menu']['movement_explanation']
    assert any(r['code'] == 'FRIGHTENED_CLOSER' for r in cards['summary']['reasons'])
    assert any(r['code'] == 'DIFFICULT_TERRAIN' for r in cards['summary']['reasons'])
    move = next(m for m in actual['menu']['moves'] if not m['destination'].get('z'))
    menu = actual['menu']
    response = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'],
                         actual['last_sequence'])
    assert response['status'] == 'COMMITTED'
    assert not any(r['code'] == 'DIFFICULT_TERRAIN'
                   for r in response['state']['menu']['movement_explanation']['summary']['reasons'])
    fresh = CombatService(ROOT, tmp_path)
    reloaded = TabletopService(fresh, tmp_path).state(mid)
    assert reloaded['menu'] == response['state']['menu']
    session = fresh._load_session(mid)
    assert session.engine.state.actors[menu['actor_id']].position.model_dump(mode='json') == move['destination']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_card_query_exception_does_not_leave_a_read_cache(monkeypatch, tmp_path):
    from combat.read_queries import _FRAME
    from combat import movement_explanations
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')

    describe = movement_explanations.describe

    def broken(*args):
        describe(*args)  # Populate the read frame before the failure.
        raise ValueError('synthetic geometry failure')

    with monkeypatch.context() as patch:
        patch.setattr(movement_explanations, 'describe', broken)
        with pytest.raises(ValueError, match='synthetic geometry failure'):
            movement_presentation.for_menu(engine, state['menu'], {})
    assert _FRAME.get() is None
    assert engine.state.model_dump(mode='json') == before
    assert movement_presentation.for_menu(engine, state['menu'], {}) == state['menu']['movement_explanation']
