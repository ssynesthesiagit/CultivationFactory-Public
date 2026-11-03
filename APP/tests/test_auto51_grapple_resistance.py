"""AUTO51 Court/Sovereign functional size also applies as the grapple target."""
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle, turn


def test_sovereign_weight_is_too_large_for_an_ordinary_creature_to_grapple(tmp_path):
    def prepare(bundles):
        bundles[0]['actor_template']['saving_throws'].update(STR=-100, DEX=-100)
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_SOVEREIGN_WEIGHT_INCARNATION'],
                               bundle_transform=prepare, foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Sovereign Weight Incarnation').candidate_id)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    start = len(before.events)
    settle(table, mid, candidate(combat, mid, 'Grapple', target=OWNER).candidate_id)
    e = reload(tmp_path, mid)
    assert e._footprint(e.state.actors[OWNER]).width_cells == 1
    assert not any(c.condition_id == 'condition:typed.grappled' for c in e.state.actors[OWNER].conditions.values())
    assert not any(x.event_type == 'SAVE_ROLLED' for x in e.events[start:])
