"""Bark-Splitting Cast's explicit object targets, using the shared object resolver.

The printed Axes rules allow Cast Axe to target an object. Splinter Cast adds
Proficiency Bonus damage against its listed objects; Bark-Splitting Cast
adds one weapon die and treats long range as normal range. Clone that compiled
throw only, preserving its weapon, attack bonus, costs and single attack.
Combine the extra die with the weapon dice so the shared objects.object_action
resolver applies criticals, thresholds, immunities and other object talents once.
Attended targets qualify only where both printed riders explicitly name them:
wooden barriers, ropes, vines and banner poles.
No eligibility is inferred from a display name, or from wood alone.
Shock Cast also uses this resolver without Splinter's PB damage. Map objects
cannot take Reactions, so its reaction restriction needs no creature condition.
No creature effect is dispatched against an object. Lodging/Turning Cast and the
Foundation restraint/creature clause remain GM riders, not inferred object links.
"""
from __future__ import annotations

import copy
import re

from . import hook

BARK = "TAL_AXES_BARK_SPLITTING_CAST"
CAST = "TAL_AXES_CAST_AXE"
KEY = "axes_bark_cast"


@hook("compile_actions")
def object_casts(info):
    from factory_authoring.starting_kits import item_definition
    from .weapon_actions import weapon_attacks

    if not {BARK, CAST} <= set(info.get("owned_ids") or []):
        return None
    out = []
    # compile_actions precedes technique weapon delivery. Use its public base
    # weapon query, selecting only catalogued axes with an actual thrown profile.
    for action, typed, _attack, kind in weapon_attacks(info.get("actions") or [], info["actor_id"]):
        family = item_definition(str(typed.get("source") or "")).get("weapon_family") or ""
        if kind != "thrown" or "axe" not in re.findall(r"[a-z]+", family.lower()):
            continue
        weapon = copy.deepcopy(typed.get("weapon") or {})
        damage = weapon.get("damage")
        if not damage or not typed.get("long_range_ft"):
            continue
        damage["count"] = int(damage["count"]) + 1
        damage["modifier"] = int(damage.get("modifier") or 0) + int(info.get("pb") or 2)
        reach = int(typed["long_range_ft"])
        splinter = action.model_copy(update={
            "source_definition_id": action.source_definition_id + "." + KEY,
            "display_name": action.display_name + ": Cast Axe: Splinter Cast + Bark-Splitting Cast (object)",
            "target_kind": "OBJECT", "range_ft": reach,
            "parameters": {
                KEY: True, "object_attack": True,
                "expected_damage": int(action.parameters.get("expected_damage") or 0)
                                   + int(damage["sides"]) // 2 + 1 + int(info.get("pb") or 2),
                "description": f"Use an Action (0 CP) to throw this axe with Splinter Cast at an unattended object, wooden barrier, "
                               f"rope, vine or banner pole within {reach} feet, even if someone is holding or guarding that target. "
                               "Long range causes no Disadvantage. On a hit, deal the axe's damage plus one weapon die "
                               "and your Proficiency Bonus, applying the object's defenses. The GM handles restraint links "
                               "and avoiding harm to a restrained creature at Foundation Realm. The GM also tracks retrieving "
                               "the thrown axe; the table does not remove thrown weapons from your hand.",
                "typed": {**copy.deepcopy(typed), "source": CAST, "delivered_by": action.source_definition_id,
                          "sphere": "tianxia.sphere.axes", "weapon": None,
                          "effects": [{"type": "object_attack", "count": 1}],
                          "object_weapon": weapon, "object_weapon_group": "axe", "object_melee": False,
                          "range_ft": reach, "riders": [], "coverage": "CORE_WITH_RIDERS"},
            },
        })
        out.append(splinter)
        # Shock is a separate printed choice, not an additional Splinter rider.
        # Objects have no reaction economy: never apply a creature condition or
        # spend another actor's reaction to model this inherently inert clause.
        shock_weapon = copy.deepcopy(weapon)
        shock_weapon["damage"]["modifier"] -= int(info.get("pb") or 2)
        shock_typed = copy.deepcopy(splinter.parameters["typed"])
        shock_typed["object_weapon"] = shock_weapon
        out.append(splinter.model_copy(update={
            "source_definition_id": splinter.source_definition_id + ".shock",
            "display_name": action.display_name + ": Cast Axe: Shock Cast + Bark-Splitting Cast (object)",
            "parameters": {**splinter.parameters, "typed": shock_typed,
                "expected_damage": splinter.parameters["expected_damage"] - int(info.get("pb") or 2),
                "description": f"Use an Action (0 CP) to throw this axe with Shock Cast at an unattended object, wooden barrier, "
                               f"rope, vine or banner pole within {reach} feet, even if someone is holding or guarding that target. "
                               "Long range causes no Disadvantage. On a hit, deal the axe's damage plus one weapon die, "
                               "applying the object's defenses. Shock Cast prevents the target from taking Reactions against you "
                               "until the start of your next turn; map objects cannot take Reactions, and this does not affect "
                               "a creature holding the object. This choice does not add Splinter Cast's Proficiency Bonus damage. "
                               "The GM handles restraint links and avoiding harm to a restrained creature at Foundation Realm, "
                               "and tracks retrieving the thrown axe; the table does not remove it from your hand."},
        }))
    return out or None


@hook("candidate_allowed")
def eligible_object_held_axe(engine, actor, candidate, action):
    if action is None or not (action.parameters or {}).get(KEY):
        return None
    from .weapon_hits import available_weapons

    delivered = action.parameters["typed"]["delivered_by"].split("#", 1)[0]
    if delivered not in available_weapons(engine, actor):
        return False
    targets = getattr(candidate, "target_ids", ()) or ()
    return bool(targets) and all(
        target in engine.state.objects and splinter_bark_target(engine.state.objects[target]) for target in targets)


def splinter_bark_target(obj):
    """Targets explicitly shared by Splinter Cast and Bark; similar objects stay GM-resolved."""
    from ..object_rules import has_tag

    return bool(obj.unattended) or any(has_tag(obj, kind) for kind in ("rope", "vine", "banner")) or (
        has_tag(obj, "wooden") and any(has_tag(obj, kind) for kind in ("wall_section", "barricade", "door", "gate")))
