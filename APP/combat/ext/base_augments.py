"""In-text augments of Sphere base abilities that change one use and have no talent record of their own (rider lane C13,
2026-09-30; owner: "i want everything we can automated, keep going until its only the non-combat ones left").

An augment printed inside a base ability ("##### Overheat - Ignite / Augment - 1 CP: Roll one additional damage die for Ignite.
After the attack resolves, take Fire damage equal to your Proficiency Bonus.") has no mechanic id, so the compiler's
augment variants (combat/factory_compiler._augment_traits, which read a *talent's* modifier) never see it. This module adds the
augmented version of each compiled action of that ability: "<action> + <augment>", the same action with the augment's extra
cost, extra damage dice on its own damage rows and the printed effects that follow the attack. Choosing the button is choosing
the augment when the ability is used, as printed.

AUGMENTS below is the data: per ability, the augment's printed name, its CP, how many damage dice or extra rays it adds, any
printed width change, and the typed rows run after the ability's own effects. Default-inert: only a character whose catalog
holds that ability gets the buttons. A talent's own printed Overheat is in the same table (AUTO77, 2026-10-05: Scorching Ray
Art's extra ray, Fireball Art's and Incinerating Lance's extra damage, and the line's printed 10-foot width; the width is the
area's own ``width_ft``, so the printed creatures in the extra 5 feet are actually reached, AUTO77f1).

Hooks: compile_actions. No hooks added to the framework.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook

AUGMENTS = {
    "FIRE_BASE_IGNITE": {
        "name": "Overheat", "cp": 1, "extra_dice": 1,
        "after": [{"type": "damage", "applies_to": "self", "flat": 0, "formula": "pb", "damage_types": ["fire"],
                   "evidence": "Overheat: After the attack resolves, take Fire damage equal to your Proficiency Bonus."}],
        "evidence": "Augment - 1 CP: Roll one additional damage die for Ignite.",
    },
    "FIRE_TAL_SCORCHING_RAY_ART": {
        "name": "Overheat", "cp": 1, "extra_rays": 1,
        "after": [{"type": "damage", "applies_to": "self", "flat": 0, "formula": "pb", "damage_types": ["fire"],
                   "evidence": "Overheat: After all rays resolve, take Fire damage equal to your Proficiency Bonus."}],
        "evidence": "Augment - 1 CP: Create one additional ray.",
    },
    "FIRE_TAL_FIREBALL_ART": {
        "name": "Overheat", "cp": 2, "extra_dice": 2,
        "after": [{"type": "damage", "applies_to": "self", "flat": 0, "formula": "double_pb", "damage_types": ["fire"],
                   "evidence": "Overheat: After the attack resolves, take Fire damage equal to twice your Proficiency Bonus."}],
        "evidence": "Augment - 2 CP: Increase damage by 2d6.",
    },
    "FIRE_TAL_INCINERATING_LANCE": {
        "name": "Overheat", "cp": 2, "extra_dice": 2, "width_ft": 10,
        "after": [{"type": "damage", "applies_to": "self", "flat": 0, "formula": "double_pb", "damage_types": ["fire"],
                   "evidence": "Overheat: After the talent resolves, take Fire damage equal to twice your Proficiency Bonus."}],
        "evidence": "Augment - 2 CP: The line becomes 10 feet wide and damage increases by 2d8.",
    },
}


def _augmented(rows: list[Any], spec: dict[str, Any]) -> list[Any]:
    """One augmented copy of an ability's own effect rows: its printed extra damage dice, its printed extra ray or
    attack, and nothing else."""
    dice, rays = int(spec.get("extra_dice") or 0), int(spec.get("extra_rays") or 0)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        row = copy.deepcopy(row)
        if row.get("type") in ("damage", "extra_damage") and row.get("applies_to", "target") != "self" and dice:
            if row.get("dice_by_cl"):
                row["dice_by_cl"] = [[low, high, int(count) + dice, sides] for low, high, count, sides in row["dice_by_cl"]]
            if isinstance(row.get("dice"), dict) and row["dice"].get("count"):
                row["dice"] = {**row["dice"], "count": int(row["dice"]["count"]) + dice}
        if row.get("type") == "attack" and rays:
            if row.get("count_by_cl"):
                row["count_by_cl"] = [[low, high, int(count) + rays] for low, high, count in row["count_by_cl"]]
            elif row.get("count"):
                row["count"] = int(row["count"]) + rays
        for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
            if isinstance(row.get(key), list):
                row[key] = _augmented(row[key], spec)
        out.append(row)
    return out


@hook("compile_actions")
def augmented_variants(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS

    out = []
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    for action in info.get("actions") or []:
        typed = (action.parameters or {}).get("typed") or {}
        ability = str(typed.get("option_of") or typed.get("source") or "")
        spec = AUGMENTS.get(ability)
        if spec is None or action.owner_id != info["actor_id"] or "+" in str(action.source_definition_id).rsplit("#", 1)[-1]:
            continue
        effects = _augmented(typed.get("effects") or [], spec) + copy.deepcopy(spec.get("after") or [])
        update: dict[str, Any] = {}
        if spec.get("width_ft"):  # "The line becomes 10 feet wide"
            # typed_executor.in_area reads a line's half-width from area["width_ft"] and its reach from
            # area["size_ft"]; typed["radius_ft"] is display metadata and never moves a creature. The
            # printed length is kept: only the width changes (AUTO77f1).
            area = copy.deepcopy(typed.get("area") or {})
            if area.get("width_ft"):
                area["width_ft"] = int(spec["width_ft"])
                update["area"] = area
        costs = list(action.costs or ())
        if any(resource == pool for resource, _ in costs):
            costs = [(resource, amount + int(spec["cp"]) if resource == pool else amount) for resource, amount in costs]
        else:
            costs.append((pool, int(spec["cp"])))
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}+{spec['name'].lower()}",
            "display_name": f"{action.display_name} + {spec['name']} ({spec['cp']} CP)",
            "costs": tuple(costs),
            "parameters": {**action.parameters,
                           "typed": {**typed, **update, "effects": effects, "augments": [spec["name"]]},
                           "base_augment": ability}}))
    return out or None
