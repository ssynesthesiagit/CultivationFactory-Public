"""Disarm protects only the weapon actually knocked away, through table reload."""
import pytest

from combat.canonical import canonical_sha256
from tests import worker2_support as w
from tests.test_a2_body_subpaths_3 import seal
from tests.test_redokensei_initiative_blade import BLADE, KIT
from tests.test_redokensei_integrated_authority import HEAVENLY, REFINED


@pytest.mark.parametrize("taken", [True, False])
def test_heavenly_fist_checks_actual_disarmed_weapon(tmp_path, taken):
    def actions(bundles):
        seal(bundles[2], "Mundane Disarm",
             [{"type": "condition", "condition": "disarmed", "applies_to": "target"}],
             target="HOSTILE_ENTITY")
        bundles[2]["action_catalog"][-1]["parameters"].update(free_primary=True)
        bundles[2]["action_catalog"][-1]["parameters"]["typed"]["mundane"] = True
        if taken:
            weapon = next(a["source_definition_id"] for a in bundles[2]["action_catalog"]
                          if ".weapon.dao" in a["source_definition_id"] and "#" not in a["source_definition_id"]
                          and not a["source_definition_id"].endswith(".pickup")
                          and not a["parameters"].get("requires_held_weapon"))
            seal(bundles[2], "Weapon already taken", [{"type": "condition",
                 "condition": "disarmed", "applies_to": "self", "duration": "until_removed",
                 "condition_data": {"disables_action": weapon, "held_by": w.OWNER}}])
            bundles[2]["action_catalog"][-1]["parameters"].update(free_primary=True)
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])

    combat, table, mid = w.fixture(tmp_path, [], owner_features=[BLADE, REFINED, HEAVENLY],
        owner_path="Body Refining", primary="Stamina", cl=18, owner_kit=KIT, foe_kit=KIT,
        bundle_transform=actions)
    w.turn(table, mid, w.FOE)
    if taken:
        w.settle(table, mid, w.candidate(combat, mid, "Weapon already taken").candidate_id)
        before = w.reload(tmp_path, mid)
        assert any(c.data.get("held_by") == w.OWNER
                   for c in before.state.actors[w.FOE].conditions.values())

    w.settle(table, mid, w.candidate(combat, mid, "Mundane Disarm", target=w.OWNER).candidate_id)
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    # The integrated Dao stays wieldable in both branches.
    assert not any(c.condition_id == "condition:typed.disarmed" for c in owner.conditions.values())
    from combat.ext.hand_occupancy import weapon_grips
    assert weapon_grips(engine, owner)
    if taken:
        dropped = [c for c in engine.state.actors[w.FOE].conditions.values()
                   if c.condition_id == "condition:typed.disarmed"]
        assert len(dropped) == 1
        assert "held_by" not in dropped[0].data
        assert dropped[0].data["dropped_at"] == owner.position.model_dump(mode="json")
