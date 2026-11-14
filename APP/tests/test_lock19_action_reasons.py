"""Final shape-cost diagnostics after a rejected target, through a saved Table."""
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.granted_movement import resolve_path
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests import test_tabletop_hunt6 as H


def test_shape_cost_overrides_earlier_rejected_target_after_table_reload(monkeypatch, tmp_path):
    qi = 'resource:core.qi'
    def actions(info):
        return [ActionDefinition(source_definition_id='test:shape:' + info['actor_id'],
            display_name='Focused shape', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
            resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5,
            parameters={'shape_costs': {qi: 99}, 'typed': {'effects': []}})]
    install(monkeypatch, 'compile_actions', actions)
    def separate(engine):
        ally = engine.state.actors[H.ALLY]
        resolve_path(engine, ally, (ally.position, Position(x=3, y=6), Position(x=3, y=7)),
                     feet=10, source=H.HOLD, provokes=False, intent=engine._active_intent)
    H.on_hold(monkeypatch, separate)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[])
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == combat._load_session(mid).engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    engine = loaded.engine
    source = 'test:shape:' + H.LEFT
    native = [c for c in Gate2Engine.legal_candidates(engine) if c.source_definition_id == source]
    assert any(H.RIGHT in c.target_ids for c in native)
    assert not any(H.ALLY in c.target_ids for c in native)
    assert not any(c.source_definition_id == source for c in engine.legal_candidates())
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls)
    result = engine.action_availability(H.LEFT, source)
    assert result['code'] == 'COST' and not result['available']
    assert result['details']['costs'] == [[qi, 99]]
    assert f"99 Qi (you have {engine.state.actors[H.LEFT].resources[qi]})" in result['reason']
    assert before == (engine.state.model_dump(mode='json'), engine.events, engine.rolls)
