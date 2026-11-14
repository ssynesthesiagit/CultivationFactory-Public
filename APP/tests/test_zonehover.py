"""Forged table hovers describe the placed form before its primary's print."""
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.status_text import printed_rules
from tests.rider_sheet_support import sheet

LEFT, RIGHT = "actor:factory.zonehover-left", "actor:factory.zonehover-right"


def act(table, mid, label, destination=None):
    """Commit one accepted table action, or the same action placed on an exact square."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    placeable = bool(group.get("placement_picker")) or any(o.get("destination") for o in group["options"])
    if destination is not None and placeable:  # a shaped placeable form asks for its square; an aura does not
        from tests.r1i_service_support import place
        result = place(table, mid, label, destination)
    else:
        result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"])
    assert result["status"] == "COMMITTED", result


def owner_turn(table, mid):
    for _ in range(3):
        state = table.state(mid)
        if state["menu"]["actor_id"] == LEFT:
            return
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED", result
    raise AssertionError("owner turn not reached")

PRIMARY = "TAL_SPEAR_SPEAR_LIGHT_SEED"
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("form,size", [("zone", 20), ("aura", 10)])
@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("primary,name,cl", [
    (PRIMARY, "Spear-Light Seed", 10),
    ("TAL_AIR_HEAVEN_SPLITTING_GALE", "Heaven-Splitting Gale", 17),
], ids=["spear", "gale"])
def test_forged_area_hover_after_table_commit_and_reload(tmp_path, form, size, expanded, primary, name, cl):
    document = sheet([primary], cl=cl, dc=15)
    document["forged_techniques"] = [{
        "technique_id": "test.zonehover", "name": "Spear-Lightning Zone",
        "base_form": {"form_id": form}, "primary_sphere_effect": {"talent_id": primary},
        "cp_cost": {"final": 1},
        "augments": [{"augment_id": "expanded_area"}] if expanded else [],
    }]
    bundles = [compile_character(document, actor_id=LEFT), compile_character(sheet([]), actor_id=RIGHT)]
    service = CombatService(ROOT, tmp_path)
    mid = service._finish_factory_match(
        bundles, [LEFT, RIGHT], {LEFT: "team:left", RIGHT: "team:right"},
        {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}},
        service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT], [RIGHT], control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"},
        match_seed="ZONEHOVER", display_name="Hover regression", maximum_rounds=4)["match_id"]
    table = TabletopService(service, tmp_path)
    owner_turn(table, mid)
    act(table, mid, "Spear-Lightning Zone", {"x": 5, "y": 6})
    # Both the committed table view and a fresh service project the same hover.
    for view in (table, TabletopService(CombatService(ROOT, tmp_path), tmp_path)):
        row = next(z for z in view.state(mid)["presentation"]["zones"]
                   if z["display_name"] == "Spear-Lightning Zone")
        actual_size = size + (10 if expanded else 0)
        assert row["detail"].startswith(f"{form.title()}: {actual_size}-foot-radius sphere.")
        assert "Lasts" in row["detail"] and "concentrat" in row["detail"].lower()
        assert "60-foot line" not in row["detail"]
        assert row["hover"]["summary"] == row["detail"]
        assert row["hover"]["fields"] == []
        assert f"Based on: {name}" in row["source_detail"]
        assert "Original technique rules" in row["source_detail"]
        # The primary's own range line, read from the shipped print rather than quoted here: an exported copy
        # carries the same line with its prose reworded, and the number and unit are what the hover must keep.
        printed = printed_rules()[primary]
        assert next(line for line in printed.splitlines() if line.startswith("Range:")) in row["source_detail"]
        if primary != PRIMARY:
            assert "Original technique cost: 3 Qi (points from the paying Path resource pool)" in row["source_detail"]
            assert "CP" not in row["source_detail"]
        assert bool(row["trigger_profile"]["follows_owner"]) == (form == "aura")
        triggers = row["trigger_profile"]["triggers"]
        assert triggers and triggers[0]["on"] == ["enter", "start"] and triggers[0]["who"] == "hostile"


def test_unrelated_area_presentation_is_inert():
    from types import SimpleNamespace
    from combat.zone_hover import forged_area_hover

    engine = SimpleNamespace(action_catalog={})
    assert forged_area_hover(engine, {"detail": "Existing area rules"}) == {}
