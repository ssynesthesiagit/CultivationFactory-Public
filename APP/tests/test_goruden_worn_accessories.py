"""Golden Sheen still protects an unarmored fighter wearing an attuned treasure."""

from combat import carry
from factory_authoring.treasure_catalog import authority
from tests.cw2_service_support import add_action
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle, turn


def test_attuned_belt_does_not_disable_golden_sheen(tmp_path):
    belt = next(row for row in authority()["wondrous"] if row["name"] == "Belt of Giant Might (+2)")
    kit = {"starting_kit": {"items": [], "resolved_treasure_purchases": {"wondrous": [belt]}}}

    def setup(bundles):
        add_action(bundles[2], "Corrosion", [{"type": "save", "ability": "con",
                   "save_categories": ["corrosion"], "on_fail": [
                       {"type": "damage", "flat": 1, "damage_types": ["acid"], "applies_to": "target"},
                   ]}])

    combat, table, mid = fixture(tmp_path, [], primary="Stamina", owner_path="Body Refining",
                                 owner_features=["tianxia.subpath.body.goruden.feature.golden_sheen"],
                                 owner_kit=kit, bundle_transform=setup)
    engine = reload(tmp_path, mid)
    carrying = carry.carrying_of(engine, OWNER)
    [item] = carrying["items"]
    assert item["worn"] and item["key"] in carrying["attunement"]["attuned"]
    assert engine._ac_modifier(engine.state.actors[OWNER]) == 1

    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Corrosion", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    save = next(roll for roll in reversed(engine.rolls)
                if roll.actor_id == OWNER and roll.reason.startswith("SAVE:"))
    assert save.mode == "ADVANTAGE"
