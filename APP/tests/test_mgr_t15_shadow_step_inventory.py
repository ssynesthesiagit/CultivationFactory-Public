"""Shadow Step must offer actual musical tools and treasure gear, not name guesses."""
import pytest

from combat import carry
from combat.ext.hand_occupancy import occupancy
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from factory_authoring.treasure_catalog import authority
from tests.test_mgr_t15_shadow_step import (
    CHOICE, ME, act, cold, group, press, setup, step, turn, veil,
)

# Dynamic authority dependency for the public CI exporter.
INPUTS = ('authority/Tianxia_Treasure_Catalog_Authority_R1.json',)
INSTRUMENT = 'tianxia.mortal.instrument.dizi'
INKSTONE = 'tianxia.treasure.wondrous.038.talisman_inkstone_of_even_flow'
TALISMAN = 'tianxia.treasure.wondrous.085.thunder_script_escape_talisman'


@pytest.mark.parametrize('item_id', [INSTRUMENT, INKSTONE, TALISMAN])
def test_printed_inventory_can_draw_then_stow_with_pending_and_settled_cold_replay(tmp_path, item_id):
    treasure = [row for row in authority()['wondrous'] if row['treasure_id'] == item_id]
    _, table, mid = setup(tmp_path, gear=[INSTRUMENT], treasure=treasure)
    veil(table, mid)
    before = cold(tmp_path, mid)
    cid = group(table, mid, 'Shadow Step')['options'][0]['candidate_id']
    destination = press(table, mid, cid)['reaction']
    answer = {**destination['context'], 'selection': 'USE', 'option_ids': ['cell:4,6']}
    pending = press(table, mid, cid, [answer])
    assert pending['status'] == 'REACTION_REQUIRED'
    choice = pending['reaction']
    assert choice['context']['reaction_source_id'] == CHOICE
    # Selection uses the physical identity, not an item's mutable display name.
    key = 'wondrous.0' if treasure else item_id
    option = next(o['id'] for o in choice['choice']['options'] if key + '|hand:' in o['id'])
    assert cold(tmp_path, mid).state.model_dump(mode='json') == before.state.model_dump(mode='json')
    # Reopen both services before answering the uncommitted gear decision.
    from tests.h1_support import ROOT
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert press(fresh, mid, cid, [answer, {**choice['context'], 'selection': 'USE', 'option_ids': [option]}])['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert carry.owned_item_location(actor, key).startswith('hand:')
    assert sum('object:' + key in values for values in occupancy(engine, actor).values()) == 1
    assert {k: (a.attack_bonus, a.parameters) for k, a in engine.action_catalog.items()} == {
        k: (a.attack_bonus, a.parameters) for k, a in before.action_catalog.items()}
    assert press(fresh, mid, fresh.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    turn(fresh, mid, ME)
    step(fresh, mid, destination='cell:3,6', item=key + '|carried')
    settled = cold(tmp_path, mid)
    assert carry.owned_item_location(settled.state.actors[ME], key) == 'carried'
    assert all('object:' + key not in values for values in occupancy(settled, settled.state.actors[ME]).values())
