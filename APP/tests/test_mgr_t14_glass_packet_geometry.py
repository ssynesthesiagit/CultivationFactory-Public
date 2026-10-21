"""Acquired pane -> real thrown attack -> committed path -> choice/cold replay."""
import pytest

from combat.ext.glass_refraction import marked
from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, reload, turn
from tests.test_mgr_t14_glass_object_contacts import native_pane
from tests.test_mgr_t14_weighted_strike import local_primary

KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 1}]}}
CHOICE = 'choice:needle.glass_surface_mark'


@pytest.mark.parametrize('crossing,armor,automatic,accept', [
    (True, 0, False, True), (True, 100, False, True),
    (True, 0, True, True), (True, 0, False, False),
    (False, 0, False, True), (False, 0, True, True),
])
def test_real_attack_path_places_only_the_surface_owners_optional_mark(
        tmp_path, crossing, armor, automatic, accept):
    combat, table, mid, pane_id = native_pane(tmp_path, foe_kit=KIT, owner_ac=armor,
        ally_position={'x': 2, 'y': 9})
    before = reload(tmp_path, mid)
    target = OWNER if crossing else ALLY
    use = next(c for c in before.legal_candidates()
        if c.source_definition_id.endswith('.weapon.fu#thrown') and c.target_ids == (target,))
    assert not marked(before.state.actors[FOE], OWNER)
    if automatic:
        local_primary(combat, use.candidate_id)
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, use.candidate_id, auto=automatic,
        choices={CHOICE: ['mark'] if accept else None, 'choice:needle.refraction_response': None})
    after = reload(tmp_path, mid)
    events = after.events[len(before.events):]
    attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    if armor == 100:
        assert attack.payload['natural_result'] != 20
        assert attack.payload['provisional_hit'] is False
    receipts = [e for e in events if e.payload.get('checkpoint') == 'PACKET_GEOMETRY_COMMITTED']
    offers = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert bool(receipts) is crossing
    assert bool(offers) is crossing
    assert all(p['context']['reactor_id'] == OWNER for p in offers)
    assert all('through, across, or against your Glass Surface' in p['moment'] for p in offers)
    assert marked(after.state.actors[FOE], OWNER) is (crossing and accept)
    if crossing:
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.payload['attack_roll_id'] == attack.payload['roll_id']
        assert receipt.payload['attack_sequence'] == attack.sequence
        geometry = receipt.payload['geometry']
        assert geometry['target_id'] == target and geometry['source_id'] == attack.source_definition_id
        assert geometry['actor_id'] == FOE
        assert [5, 6, 0] in geometry['segments'][0]['cells']
        assert not geometry['surface_contacts']
    # A hit can end its creator's Concentration and retire the pane. Passing
    # through it is not an object damage packet, regardless of that lifetime.
    assert not any(e.event_type == 'OBJECT_UPDATED' and pane_id in e.target_ids
        and e.payload.get('damage') for e in events)
    assert after.state.actors[OWNER].reaction_available
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources


def test_no_owned_surface_adds_no_geometry_receipt_to_an_actual_throw(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=1, foe_kit=KIT)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    use = next(c for c in before.legal_candidates()
        if c.source_definition_id.endswith('.weapon.fu#thrown') and c.target_ids == (OWNER,))
    settle(table, mid, use.candidate_id)
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in after.events[len(before.events):])
    assert not any(e.payload.get('checkpoint') == 'PACKET_GEOMETRY_COMMITTED' for e in after.events)
