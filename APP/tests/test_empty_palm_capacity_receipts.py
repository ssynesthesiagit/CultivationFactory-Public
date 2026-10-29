"""Hollow suppresses compiled shield capacity, with table expiry and cold replay."""
import json

import pytest

from combat import armour, carry
from combat.canonical import canonical_sha256
from tests import test_mgr_empty_palm as P
from tests import worker2_support as W
from tests.h1_support import ROOT, sheet

acquired = P.acquired


@pytest.mark.parametrize("save", [-50, 50])
def test_hollow_suppresses_and_restores_shield_carrying_capacity(acquired, tmp_path, monkeypatch, save):
    from combat.gate2_rolls import DeterministicRollAuthority

    # Exercise the real attack/save pipeline, without a seed accidentally
    # producing a natural-1 miss or a critical. Replay uses the same dice.
    original = DeterministicRollAuthority._die

    def ordinary_d20(roller, sides):
        if sides == 20:
            counter = roller.counter
            roller.counter += 1
            return 15, counter
        return original(roller, sides)

    monkeypatch.setattr(DeterministicRollAuthority, "_die", ordinary_d20)
    service, project = acquired
    authority = json.loads((ROOT / "authority/Tianxia_Treasure_Armor_Authority_R1.json").read_text())
    shield = next(row for row in authority["chassis"] if row["armor_category"] == "shield")
    shell = next(row for row in authority["enhancements"]
                 if row["enhancement_id"].endswith(".immovable_mountain_grand_shell"))
    fid = shell["enhancement_id"]
    kit = {"items": [{"item_id": "tianxia.mortal.gear.rations", "name": "Rations", "quantity": 97}],
           "resolved_treasure_armor": {"name": "Mountain shield", "chassis": shield,
                                      "enhancements": [shell], "refinement_bonus": 0}}
    foe_doc = sheet([], cl=P.CL, score=10, kit={"starting_kit": kit})

    def transform(bundles):
        foe = next(b for b in bundles if b["actor_id"] == W.FOE)
        foe["actor_template"].update(armor_class=1, maximum_hp=400,
                                     saving_throws={"CHA": save})
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    combat, table, mid = W.fixture(
        tmp_path, [], cl=P.CL, owner_bundle=P.bundle(service, project), foe_sheet=foe_doc,
        bundle_transform=transform, seed=f"HOLLOW-CAPACITY-{save}",
        positions={W.OWNER: {"x": 3, "y": 6}, W.FOE: {"x": 4, "y": 6},
                   W.ALLY: {"x": 12, "y": 12}})

    def state(capacity, speed, over):
        engine = W.reload(tmp_path, mid)
        foe = engine.state.actors[W.FOE]
        status = carry.status(engine, foe)
        assert status["weight_lb"] == "200"
        assert status["capacity_lb"] == capacity and status["over"] is over
        assert engine._effective_speed(foe) == speed
        assert armour.shield_bonus_earning(engine, foe) == 2
        assert carry.holds(engine, foe, "treasure_armor")
        # The same effective values reach the native table's item panel.
        panel = table.state(mid)["carrying"][W.FOE]
        assert panel["capacity_lb"] == capacity and panel["over"] is over
        return engine

    before = state(300, 30, False)
    sealed = carry.carrying_of(before, W.FOE)
    W.settle(table, mid, W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id,
             picks={P.DAMAGE_TYPE_PROMPT: ["FORCE"],
                    P.ITEM_PROMPT: [f"{W.FOE}|treasure_armor"], P.PROPERTY_PROMPT: [fid]})
    engine = state(150, 5, True)
    assert any(c.condition_id == P.palm.HOLLOWED_ITEM and c.data.get("property_id") == fid
               for c in engine.state.actors[W.FOE].conditions.values())
    assert carry.carrying_of(engine, W.FOE) == sealed  # no bundle mutation
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"])
    if save < 0:
        state(150, 5, True)  # failed save lasts beyond this turn's end
        W.turn(table, mid, W.OWNER)
    engine = state(300, 30, False)
    assert not any(c.condition_id == carry.ENCUMBERED for c in engine.state.actors[W.FOE].conditions.values())
