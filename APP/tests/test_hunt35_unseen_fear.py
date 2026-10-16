"""Astra regression: the locked native filter must use current sight, not memory."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.target_knowledge import can_see, knowledge
from tests.hunt15_support import LEFT, RIGHT, act, fight, reload, turn


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('frightened,invisible', [
    pytest.param(True, True, id='unseen-fear'),
    pytest.param(True, False, id='visible-fear'),
    pytest.param(False, True, id='unseen-without-fear'),
])
def test_unseen_fear_source_allows_approach_commit_and_reload(tmp_path, ai, frightened, invisible):
    effects = []
    if invisible:
        effects.append({'type': 'condition', 'condition': 'invisible', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'})
    if frightened:
        effects.append({'type': 'condition', 'condition': 'frightened', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'})
    combat, table, mid = fight(tmp_path, effects=effects, target='HOSTILE_ENTITY', seed='HUNT35-UNSEEN-FEAR',
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 5, 'y': 6}})
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Test setup', target_id=LEFT)['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    observer, source = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert can_see(engine, observer, source) is not invisible
    if invisible:
        assert knowledge(engine, observer, source).mode == 'LAST_OBSERVED'
    assert any(c.condition_id == 'condition:typed.frightened' for c in observer.conditions.values()) is frightened
    # Check the menu through a fresh service, not only the original session.
    fresh_combat = CombatService(combat.source_root, combat.userdata_root)
    fresh_table = TabletopService(fresh_combat, combat.userdata_root)
    assert fresh_table.state(mid)['menu']['moves'] == table.state(mid)['menu']['moves']
    assert fresh_combat._load_session(mid).verify()['status'] == 'PASS'
    # The xfail covers only the demonstrated native exclusion, not transaction
    # or replay failures once Astra admits the move.
    moves = table.state(mid)['menu']['moves']
    approach = {'x': 4, 'y': 6}
    allowed = not frightened or invisible
    if frightened and invisible and approach not in [m['destination'] for m in moves]:
        pytest.xfail('Astra lock item: native movement discards approaches to unseen fear sources')
    assert (approach in [m['destination'] for m in moves]) is allowed
    destination = approach if allowed else {'x': 2, 'y': 6}
    cid = next(m['candidate_id'] for m in moves if m['destination'] == destination)
    if ai:
        original = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(original, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        result = table.auto_step(mid, table.state(mid)['last_sequence'])
    else:
        state = table.state(mid)
        menu = state['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert result['status'] == 'COMMITTED'
    loaded = reload(combat, mid)
    actor = loaded.state.actors[LEFT]
    assert actor.position.x == destination['x'] and actor.position.y == destination['y']
    assert any(c.condition_id == 'condition:typed.frightened' for c in actor.conditions.values()) is frightened
    assert can_see(loaded, actor, loaded.state.actors[RIGHT]) is not invisible
    assert CombatService(combat.source_root, combat.userdata_root)._load_session(mid).verify()['status'] == 'PASS'
