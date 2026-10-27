"""A manual Basin beneficiary remains the chooser across a native AI turn end."""
import json
from combat.gate4_adapters import ManualControllerAdapter
from tests.test_mgr_t15_close_cleansing_water import ALLY, setup, turn, move, settle, cold


def test_ai_turn_end_asks_manual_basin_beneficiary(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, ALLY)
    move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': None})
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 0
    order = e.state.initiative_order
    previous = order[(order.index(ALLY) - 1) % len(order)]
    turn(table, mid, previous)
    cid = table.state(mid)['menu']['end_turn']
    native = combat.controller

    class ScenarioController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(native, name)

    combat.controller = ScenarioController()
    combat.set_controller_mode(mid, actor_id=previous, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, cid, {'choice:needle.water_cleansing': 'cleanse'}, auto=True)
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    text = json.dumps(prompts)
    assert 'Cleansing Water' in text and 'Tobin' in text
    assert 'turn start' in text or 'End turn' in text
    e = cold(tmp_path, mid)
    assert e.state.current_actor_id == ALLY
    assert e.state.actors[ALLY].temporary_hp == 5
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke'
                   for c in e.state.actors[ALLY].conditions.values())
