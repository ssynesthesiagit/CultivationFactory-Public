"""Paired native table captures: only the owned potency row differs.

The asserted deltas are the task behaviour diff, not a model-generated fight
or a comparison against private/history-dependent fixtures. Both sides commit
and cold-replay through the real service.
"""
import pytest

from tests.test_mgr_t15_qi_potency_routes import (
    OWNER, FOE, imported_fight, damage, receipts,
)
from tests.worker2_support import candidate, settle, reload


@pytest.mark.parametrize("kind,name,choice,expected_delta,cost", [
    ("volley", "Thousand-Spark Volley", "weapon", [4, 0], 2),
    ("volley", "Thousand-Spark Volley", "technique", [0, 4], 2),
    ("ray", "Scorching Ray Art", "technique", [4], 4),
    ("paid", "Qiang (Spear) attack", None, [0], 0),
])
def test_owned_potency_changes_one_roll_not_dice_cost_or_ordinary_weapons(
        tmp_path, kind, name, choice, expected_delta, cost):
    captures = []
    for enabled in (False, True):
        root = tmp_path / ("potency" if enabled else "control")
        combat, table, mid = imported_fight(root, kind=kind, potency=enabled)
        before = reload(root, mid).state.actors[OWNER].resources["resource:core.qi"]
        prompts = settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id,
                         choices={"choice:needle.qi_potency": choice,
                                  "choice:needle.paid_hit": None})
        engine = reload(root, mid)
        rolled = damage(engine)
        captures.append({
            "dice": [r.dice for r in rolled],
            "modifiers": [r.modifier for r in rolled],
            "spent": before - engine.state.actors[OWNER].resources["resource:core.qi"],
            "receipts": receipts(engine),
            "potency_prompts": [p for p in prompts
                                if p["context"]["reaction_source_id"] == "choice:needle.qi_potency"],
        })
    control, owned = captures
    assert control["dice"] and owned["dice"] == control["dice"]
    assert control["spent"] == owned["spent"] == cost
    assert len(control["modifiers"]) == len(owned["modifiers"])
    delta = [b - a for a, b in zip(control["modifiers"], owned["modifiers"])]
    assert len(delta) >= len(expected_delta)
    assert delta == expected_delta + [0] * (len(delta) - len(expected_delta))
    assert not control["receipts"] and not control["potency_prompts"]
    if choice is None:
        assert not owned["receipts"] and not owned["potency_prompts"]
    else:
        assert owned["receipts"] == [{"choice": choice, "used": True}]
        assert len(owned["potency_prompts"]) == (1 if kind == "volley" else 0)
