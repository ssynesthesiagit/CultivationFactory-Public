"""Vanishing's damage-only receipt path through table commits and cold reloads."""
import json
from pathlib import Path

import pytest

from tests.test_a2r09_review_fixes import add_fixture_action, NINPO
from tests.test_a2r09_round3 import held
from tests.worker2_support import fixture, candidate, settle, reload, OWNER, FOE


def test_ninpo_native_runtime_data_is_shipped():
    """Explicit fixture prerequisites also support older publication routers."""
    root = Path(__file__).resolve().parents[1]
    blocks = json.loads((root / "combat/rules/feature_blocks.d/tabik.json").read_text())
    assert blocks["features"][NINPO + "shadow_clone_array"]["block"] == "ninpo"
    concentration = json.loads((root / "combat/rules/concentration.json").read_text())
    assert concentration["capacity"] == "unlimited"


@pytest.mark.parametrize("damage", [3, 0])
def test_vanishing_temp_hp_damage_reveal_and_restore_after_reload(tmp_path, damage):
    def setup(bundles):
        add_fixture_action(bundles[0], "Grant buffer", [
            {"type": "temp_hp", "flat": 10, "applies_to": "target"}], target="ANY_CREATURE")
        add_fixture_action(bundles[0], "Damage only", [
            {"type": "damage", "flat": damage, "formula": "none",
             "damage_types": ["FIRE"], "applies_to": "target"}], target="ANY_CREATURE")

    combat, table, mid = fixture(
        tmp_path, [], owner_path="Qi Cultivation", seed="A2R09FXF2",
        owner_features=[NINPO + "vanishing_technique"], bundle_transform=setup,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    settle(table, mid, candidate(combat, mid, "Grant buffer", target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)
    before = reload(tmp_path, mid)
    assert before.state.actors[FOE].temporary_hp == 10
    assert held(before.state.actors[OWNER], "invisible")
    mark = len(before.events)
    settle(table, mid, candidate(combat, mid, "Damage only", target=FOE).candidate_id)
    after = reload(tmp_path, mid)
    events = after.events[mark:]
    assert not any(e.event_type in {"ATTACK_ROLLED", "SAVE_ROLLED", "CONDITION_APPLIED", "ZONE_CREATED"}
                   for e in events)
    receipts = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert receipts
    assert sum(e.payload["temporary_hp_absorbed"] for e in receipts) == damage
    assert all(e.payload["hp_damage"] == 0 for e in receipts)
    assert after.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp
    assert after.state.actors[FOE].temporary_hp == 10 - damage
    assert bool(held(after.state.actors[OWNER], "invisible")) == (damage == 0)
    assert held(after.state.actors[OWNER], "vanishing_state")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    restored = reload(tmp_path, mid).state.actors[OWNER]
    assert held(restored, "invisible")
    assert held(restored, "vanishing_state")
