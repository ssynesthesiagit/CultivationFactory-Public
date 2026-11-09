"""Native evidence for existing hand/body capacity; no synthetic limb grants."""

import json
from pathlib import Path

import pytest

from tests.hunt51_grapple_support import fight, grapple, on_turn, send
from tests.test_hunt51_grapple_persisted import holds, reload
from tests.test_shared_hand_occupancy import options


def test_grapple_capacity_runtime_input_is_shipped():
    """Retain the dynamically loaded owning feature in isolated CI exports."""
    root = Path(__file__).resolve().parents[1]
    features = json.loads((root / "combat/rules/feature_blocks.d/body.json").read_text())
    assert features["features"]["TAL_IRON_FIST_DRAGON_STEP_CLINCH"]["block"] == "body_dragon_step_clinch"


@pytest.mark.parametrize("body_feature", [False, True])
def test_readied_weapon_and_owned_body_hold_bound_capacity_after_reload(tmp_path, body_feature):
    user, service, table, match, ids = fight(
        tmp_path, "t14-capacity-" + str(body_feature), six=True,
        equipment=("tianxia.mortal.weapon.bi_shou",), dragon_clinch=body_feature)
    owner = ids[0]
    # Verify real compilation before testing capacity. A missing dynamic data
    # dependency must not masquerade as a missing legal Grapple candidate.
    engine = reload(user, service, match)
    assert any("Dragon-Step Clinch" in action.display_name
               for action in engine.action_catalog.values()
               if action.owner_id == owner) == body_feature
    # The readied dagger occupies one ordinary hand. Only the character who
    # actually acquired Dragon-Step Clinch may maintain an additional body hold.
    capacity = 2 if body_feature else 1
    for target in ids[3:3 + capacity]:
        on_turn(table, match, owner)
        send(table, match, grapple(target))
        engine = reload(user, service, match)
        rows = holds(engine, owner)
        assert len({row.data["grappling_part"] for row in rows}) == len(rows)
        assert len(rows) <= capacity
        send(table, match)
    on_turn(table, match, owner)
    engine = reload(user, service, match)
    parts = {row.data["grappling_part"] for row in holds(engine, owner)}
    assert len(parts) == capacity
    assert ("body:dragon_step_clinch" in parts) == body_feature
    # Reloaded state must drive the actual table menu, including equipment.
    assert not any(grapple(ids[3 + capacity])(option) for option in options(table, match))
    # Its other hand still holds the dagger: do not over-block legal attacks.
    assert any(".weapon.bi_shou" in option.get("source_definition_id", "")
               and option.get("target_ids") == [ids[3 + capacity]]
               for option in options(table, match))
    assert not holds(engine, ids[1])
