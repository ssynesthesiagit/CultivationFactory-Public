"""A persisted harmful wall update is not its owner's new activation."""
from tests.cw2_service_support import add_action, seal
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.worker2_support import OWNER, FOE, candidate, reload, settle, turn


def prepare(bundles):
    # Scenario wall persists independently, so the owner can also concentrate
    # on Vanishing. Its wall and damage still use the shipped Lava Wall code.
    wall = next(a for a in bundles[0]["action_catalog"] if a["display_name"] == "Lava Wall")
    wall["parameters"]["typed"]["duration"]["concentration"] = False
    seal(bundles[0])
    foe = bundles[2]
    add_action(foe, "Wall breaker", [{"type": "wall_attack", "count": 1}], target="CELL",
               typed={"wall_weapon": {"fixed_damage": 10, "damage_type": "BLUDGEONING"},
                      "numbers": {"pb": 4, "cl": 15, "key_mod": 2, "attack_bonus": 100}})
    next(a for a in foe["action_catalog"] if a["display_name"] == "Wall breaker")["parameters"].update(
        any_cell=True, wall_attack=True)
    seal(foe)


def test_enemy_damages_surviving_wall_without_revealing_owner(tmp_path):
    combat, table, mid = setup(tmp_path, ["TAL_MAGMA_LAVA_WALL"], bundle_transform=prepare,
                              foe_position={"x": 8, "y": 6})
    settle(table, mid, candidate(combat, mid, "Lava Wall", at=(6, 6)).candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    activate(combat, table, mid)
    before = reload(tmp_path, mid)
    wall = next(z for z in before.state.zones.values() if z.active and z.trigger_profile.get("wall"))
    assert held(before.state.actors[OWNER], "invisible")
    turn(table, mid, FOE)
    mark = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Wall breaker", at=(6, 6)).candidate_id)
    after = reload(tmp_path, mid)
    updates = [e for e in after.events[mark:] if e.event_type == "ZONE_CREATED"
               and e.payload.get("zone", {}).get("zone_id") == wall.zone_id]
    assert updates and updates[-1].payload["zone"]["trigger_profile"].get("wall_damage", 0) > 0
    assert after.state.zones[wall.zone_id].active
    assert held(after.state.actors[OWNER], "invisible")
