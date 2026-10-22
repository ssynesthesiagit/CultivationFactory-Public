"""Actual Needle mark -> actual weapon use -> matching roll and cold replay."""
import pytest

from combat.ext.ice_fracture import BASE, LOCK, marked
from combat.item_use_checkpoint import possessions
from tests.worker2_support import OWNER, FOE, fixture as build_fixture, candidate, settle, reload
from tests.mgr_t14_acquisition_support import acquire_declared
from tests.test_mgr_t14_fracture_service import RESPONSE, QUIET, mark_with_needle, prepare
from tests.test_a2_ice_service import settle_path
from tests.test_auto116_ice import reach


def test_untracked_result_is_inert_without_optional_item_fields():
    """Public notification boundary, not claimed as native delivery evidence."""
    from types import SimpleNamespace
    from combat.ext.item_use_notifications import item_attack_result
    item_attack_result(SimpleNamespace(), None, False, False)


def test_item_roll_and_receipt_reject_missing_native_identity_and_roll(tmp_path):
    """Negative API guard over actual acquired actors; it grants no benefit."""
    from combat.item_use_checkpoint import pending_roll, complete_attack
    from combat.typed_executor import Context
    service, table, mid = build_fixture(tmp_path, [BASE], cl=1,
        owner_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}},
        sheet_edit=acquire_declared('tianxia.sphere.ice'))
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values()
        if a.owner_id == OWNER and a.source_definition_id.endswith('.weapon.dao'))
    ctx = Context(engine, actor, action, None, action.parameters.get('typed') or {}, [], None)
    with pytest.raises(ValueError, match='actual current possession'):
        pending_roll(ctx, {'object': 'unowned:phantom'}, 'attack')
    item = possessions(engine, actor)[0]
    ctx.damage_cache['_pending_item_attack'] = item
    count = len(engine.events)
    with pytest.raises(ValueError, match='actual native attack roll'):
        complete_attack(ctx, {'roll_id': 'uncommitted:phantom'}, True, False)
    assert len(engine.events) == count


@pytest.mark.parametrize('weapon', ['dao', 'fu'])
@pytest.mark.parametrize('accept', [False, True])
def test_actual_item_use_places_lock_before_the_same_matching_attack_roll(tmp_path, weapon, accept):
    kit = {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1},
        {'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 1}]}}
    service, table, mid = build_fixture(tmp_path, [BASE], cl=1, named=True, foe_kit=kit,
        ally_position={'x': 1, 'y': 1},
        bundle_transform=prepare, sheet_edit=acquire_declared('tianxia.sphere.ice'))
    mark_with_needle(service, table, mid)
    reach(table, mid, FOE, QUIET)
    settle_path(table, mid, FOE, [{'x': 6, 'y': 6, 'z': 0}, {'x': 5, 'y': 6, 'z': 0},
        {'x': 4, 'y': 6, 'z': 0}], QUIET)
    before = reload(tmp_path, mid)
    action = next(a for a in before.action_catalog.values()
        if a.owner_id == FOE and a.source_definition_id.endswith('.weapon.' + weapon))
    actual = next(item for item in possessions(before, before.state.actors[FOE])
        if item.get('weapon_action') == action.source_definition_id)
    # Crack Aim is independently offered first. Decline it; Lock Grip then
    # answers the actual item-use checkpoint, before the native d20 is drawn.
    prompts = settle(table, mid, candidate(service, mid, action.display_name, target=OWNER).candidate_id,
        {RESPONSE: (None, 'lock') if accept else None})
    after = reload(tmp_path, mid)
    events = after.events[len(before.events):]
    attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    assert attack.payload['mode'] == ('DISADVANTAGE' if accept else 'NORMAL')
    lock_prompts = [p for p in prompts if p['context']['reaction_source_id'] == RESPONSE
        and any(o['id'] == 'lock' for o in (p.get('choice') or {}).get('options', []))]
    assert lock_prompts and all(p['context']['reactor_id'] == OWNER for p in lock_prompts)
    assert all(action.display_name in str(p) and 'Lock Grip' in str(p) for p in lock_prompts)
    assert marked(after.state.actors[FOE], OWNER) is (not accept)
    assert not any(c.condition_id == LOCK for c in after.state.actors[FOE].conditions.values())
    receipt = next(e for e in events if e.payload.get('checkpoint') == 'ITEM_USE_COMMITTED')
    assert receipt.payload['item_identity'] == actual['object']
    assert receipt.payload['attack_roll_id'] == attack.payload['roll_id']
    assert receipt.payload['purpose'] == 'attack'
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert after.state.actors[OWNER].reaction_available == before.state.actors[OWNER].reaction_available
