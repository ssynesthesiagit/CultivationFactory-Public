"""Shared table fixtures for forged-technique button tests.

The fixtures build real portable characters and a real TabletopService fight, so a
test can ask what the player actually reads on a forged ability's button.
"""
from __future__ import annotations

import json
import zipfile

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, PROJECTS

PRIMARY = "TAL_AIR_DOWNBURST_SEAL"
MARKDOWN_TALENT = "TAL_UNMAKING_BLACK_TRACE"   # "**Action Type:**", "**Range:**", "**Target:**", "**Cost:** None"
TARGET_TALENT = "AIR_BASE_WIND_LASH"           # a bare "Target:" line, then "Cost: None" after it


def _technique(name="Destruction Cone of Air", form="cone", cp=9, talent=PRIMARY, augments=(), drawbacks=()):
    """One forged technique: a Base Form carrying a talent the character knows."""
    return {
        "technique_id": f"tianxia.constructed.forged_technique.test.{name.replace(' ', '_')}",
        "name": name, "action_type": "bonus_action", "base_form": {"form_id": form},
        "primary_sphere_effect": {"talent_id": talent}, "secondary_sphere_effects": [],
        "augments": [{"augment_id": name_} for name_ in augments],
        "drawbacks": [{"drawback_id": name_} for name_ in drawbacks],
        "table_choices": {},
        "limits": [], "cp_cost": {"final": cp},
    }


def _fight(tmp_path, *, talents, forged, kit=None, starts=None):
    for name in PROJECTS:
        doc = sheet(talents if name == "left" else ["BEASTMASTERY_BASE_RIDER_PACKAGE"], cl=15,
                    kit=kit if name == "left" else None)
        doc["identity"]["display_name"] = name.title()
        if forged and name == "left":
            doc["forged_techniques"] = forged
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "MMX107 yard", "width_squares": 16, "height_squares": 12,
                               "walls": [], "starts": starts or {"team1": [[4, 4], [4, 7]], "team2": [[7, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]],
                                      opponent_actor_ids=[RIGHT],
                                      control_modes={LEFT: "MANUAL", PROJECTS["ally"]: "LOCAL_AUTO",
                                                    RIGHT: "LOCAL_AUTO"},
                                      arena_id="battlefield:map.mmx107-yard",
                                      match_seed="MMX107-TEXT")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            return combat, table, mid
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("Left never got a turn")


def _button(table, mid, label):
    for group in table.state(mid)["menu"]["actions"]:
        if group["label"] == label:
            return group["description"]
    raise AssertionError(f"no button named {label!r}")


def _compiled_typed(combat, mid, label):
    """The compiled row the ENGINE will use for this button (the values the text must match)."""
    for action in combat._load_session(mid).engine.action_catalog.values():
        if action.display_name == label:
            return (action.parameters or {}).get("typed") or {}
    raise AssertionError(f"no compiled action named {label!r}")


def _compiled_area(combat, mid, label):
    return _compiled_typed(combat, mid, label).get("area") or {}
