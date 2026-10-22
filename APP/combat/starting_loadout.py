"""Starting equipment selection shared by equipment_hands and character-sheet previews.

Only fresh Factory bundles seal this plan. Runtime Draw/Stow overrides it; losing
an item never selects a replacement. Saved choices use inventory keys (or item /
action ids): primary_weapon, wielded, or last_loadout on the sheet/kit/equipment
row, and wielded/equipped flags on individual kit/given items.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from .ext.hand_occupancy import resting_hands, weapon_requirement
from .weapon_delivery import physical_weapon_id, weapon_variant_base


def physical_weapons(actions: list[Any], actor_id: str) -> list[Any]:
    """One base attack per owned physical weapon, never a delivered technique."""
    out = []
    for action in actions:
        key = action.source_definition_id
        typed = action.parameters.get("typed") or {}
        if (action.owner_id == actor_id and ".weapon." in key and typed.get("weapon")
                and physical_weapon_id(key, action.parameters) == key
                and not any(typed.get(field) for field in ("delivered_by", "opportunity_of", "weapon_source_id", "maneuver_of"))
                and not action.parameters.get("requires_held_weapon") and not weapon_variant_base(action.parameters)):
            out.append(action)
    return out


def saved_choices(sheet: dict, kit: dict, given: list[dict]) -> list[str]:
    """Read explicit equipment choices, not signature ability/action loadouts."""
    out = []
    for row in [sheet, *[r for r in sheet.get("equipment") or [] if isinstance(r, dict)], kit]:
        for field in ("primary_weapon", "wielded", "last_loadout"):
            value = row.get(field)
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out.extend(key for key in value if isinstance(key, str))
    for row in kit.get("items") or []:
        if row.get("wielded") or row.get("equipped"):
            out.append(str(row.get("combat_item_key") or row.get("item_id") or ""))
    if (kit.get("resolved_treasure_weapon") or {}).get("wielded"):
        out.append("treasure_weapon")
    for index, row in enumerate(given):
        if row.get("wielded") or row.get("equipped"):
            out.append(f"given.{index}")
    return list(dict.fromkeys(out))


def select_loadout(actions: list[Any], carrying: dict, actor_id: str, preferences=(), *, hands: int = 2) -> dict:
    """Choose a primary by proficiency, attack, damage, then treasure on ties.

    Budget the primary's attacking hands, not just its resting grip. Versatile
    weapons may use one hand with a shield/explicit companion; Two-Handed and
    Paired follow the engine's existing requirement helper. No legal primary
    means empty hands and an explanatory note, never an unusable armed loadout.
    """
    weapons = physical_weapons(actions, actor_id)
    catalog = SimpleNamespace(action_catalog={a.source_definition_id: a for a in actions})
    items = carrying.get("items") or []
    by_weapon = {item["weapon_action"]: item for item in items if item.get("weapon_action")}
    def aliases(action):
        item = by_weapon.get(action.source_definition_id, {})
        typed = action.parameters.get("typed") or {}
        return {action.source_definition_id, str(item.get("key") or ""), str(item.get("item_id") or ""),
                str(typed.get("source") or "")}
    def preference(action):
        # Sheet previews and imported characters may have a different actor id;
        # the physical weapon/copy suffix is stable across those compilations.
        return next((i for i, key in enumerate(preferences) if key and
                     (key in aliases(action) or
                      (key.startswith("action:typed.") and ".weapon." in key
                       and action.source_definition_id.endswith(".weapon." + key.split(".weapon.", 1)[1])))),
                    len(preferences))
    def rank(action):
        typed = action.parameters.get("typed") or {}
        return (int(bool(typed.get("proficient"))), int((typed.get("numbers") or {}).get("attack_bonus") or 0),
                int(action.parameters.get("expected_damage") or 0),
                int(bool(by_weapon.get(action.source_definition_id, {}).get("treasure") or not typed.get("mundane", True))))
    def need(action):
        properties = str((action.parameters.get("typed", {}).get("weapon") or {}).get("properties") or "")
        flexible = "versatile" in properties.lower() and not re.search(r"\bTwo-Handed\b", properties, re.I)
        return max(resting_hands(action), 1 if flexible else (weapon_requirement(catalog, action) or ("", 1))[1])
    ordered = sorted(weapons, key=lambda a: (preference(a), *(-v for v in rank(a)), a.source_definition_id))
    primary = next((action for action in ordered if need(action) <= hands), None)
    from factory_authoring.starting_kits import item_definition
    shields = [item for item in items if item.get("shield")]
    focuses = [item for item in items if not item.get("weapon_action")
               and (item_definition(str(item.get("item_id") or "")) or {}).get("category") == "focus"]
    held, held_items = [], []
    if primary is not None:
        held.append(primary.source_definition_id)
        remaining = hands - need(primary)
        # A saved off-hand choice wins over anything ranked below it.
        explicit = [a for a in ordered if a != primary and need(a) <= remaining
                    and preference(a) < len(preferences)]
        if explicit:
            held.append(explicit[0].source_definition_id)
            remaining -= need(explicit[0])
        # Then a shield, a Light companion the primary opens, the caster's focus,
        # and every other weapon the remaining hands can actually hold. Only what
        # cannot be held at once is stowed. The companion comes before the focus:
        # both Light weapons must stay in hand for the off-hand attack.
        if remaining and shields:
            held_items.append(shields[0]["key"])
            remaining -= 1
        companions = [a for a in ordered if a != primary and a.source_definition_id not in held
                      and need(a) == 1
                      and "Light" in str((a.parameters.get("typed", {}).get("weapon") or {}).get("properties") or "")
                      and (primary.parameters.get("typed") or {}).get("opens")]
        if remaining and companions:
            held.append(companions[0].source_definition_id)
            remaining -= 1
        if remaining and focuses:
            held_items.append(focuses[0]["key"])
            remaining -= 1
        for action in ordered:
            if remaining <= 0:
                break
            if action.source_definition_id in held:
                continue
            need_hands = need(action)
            if 0 < need_hands <= remaining:
                held.append(action.source_definition_id)
                remaining -= need_hands
        names = [a.display_name.removesuffix(" attack") for a in weapons if a.source_definition_id in held]
        names += [item["name"] for item in items if item["key"] in held_items]
        note = "Starts wielding " + " and ".join(names) + "."
        if len(held) < len(weapons):
            note += " Other weapons are carried; draw them before attacking."
    elif weapons:
        note = "Starts with hands free: none of the carried weapons can be used with the available hands. Weapons remain carried."
    else:
        if hands and shields:
            held_items.append(shields[0]["key"])
        note = ("Starts with " + shields[0]["name"] + " and no weapon drawn; Unarmed Strike is available."
                if held_items else "Starts with hands free; no weapon is carried. Unarmed Strike is available.")
    return {"weapons": held, "held_items": held_items,
            "primary_weapon": primary.source_definition_id if primary else "", "note": note}
