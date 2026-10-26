"""Compile a finished Factory character into a typed combat bundle the Gate 2 engine can load.

Owner 2026-09-24: combat is modular and rebuilt from current data, so this
compiler holds no per-character code.  Stats come from the owner character
sheet; weapons and armour from the constructed starting kit; abilities from
the typed mechanics authority (``factory_authoring.typed_mechanics``), each
becoming a ``TYPED`` action run by ``combat/typed_executor.py``.  Whatever the
bundle cannot automate yet is listed in its diagnostics and shown to the GM.

Rules applied, each from the rules text itself:
- AC: one calculation applies.  Worn armour replaces the sheet's unarmored AC
  (base calculations replace each other) and a carried Shield adds its +2; see
  combat/armour.py, the single reader of both equipment slots.
- Walking Speed: the sheet's speed, less 10 feet when the wearer falls short of
  the worn armour's Strength requirement (2024), and at most 5 feet over the
  carrying capacity.
- Saving throws: ability modifiers; the Paths grant no save proficiencies.
- Weapon attacks: PB + STR, or the better of STR/DEX for Finesse, plus the
  treasure's Refinement Bonus to attack and damage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import armour
from . import senses as _senses
from .authority_cache import read_authority as _read_compilation_authority
from .canonical import canonical_sha256
from .creature_types import from_record as printed_creature_types
from .display_text import augment_toggle_label
from .gate2_runtime_models import ActionDefinition, ActorTemplate, DiceSpec, EconomyKind, ResourceDefinition
from .typed_executor import ON_HIT_BONUS
from .ext.damage_labels import name_damage_effects

APP = Path(__file__).resolve().parents[1]
TYPED_AUTHORITY = APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
SCHEMA = "TianxiaTypedCharacterBundle.v1"
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
RESOURCE_IDS = {"qi": "resource:core.qi", "stamina": "resource:core.stamina", "resonance": "resource:core.resonance",
                "martial_focus": "resource:core.martial_focus"}
_HARMFUL = {"save", "attack", "damage", "extra_damage", "condition", "forced_movement", "reaction_denied"}


def _json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _modifiers(stats: dict[str, Any]) -> dict[str, int]:
    rows = _json(stats.get("abilities")) or []
    return {row["ability"]: int(row["modifier"]) for row in rows if isinstance(row, dict) and row.get("ability") in ABILITIES}


def _saving_throw_modifiers(stats: dict[str, Any], ability_modifiers: dict[str, int]) -> dict[str, int]:
    """Use the character record's final numeric save totals, including proficiency; fall back for legacy sheets."""
    recorded = _json(stats.get("saving_throws")) or {}
    return {ability: int(recorded.get(ability, ability_modifiers.get(ability, 0))) for ability in ABILITIES}



def _saving_throw_proficiencies(stats: dict[str, Any]) -> list[str]:
    """Explicit proficiency provenance, independent of final numeric save totals.

    Owner sheets may declare saving_throw_proficiencies as an ability-ID list
    (or its JSON encoding). Absent/None means no declared proficiency, matching
    the owner Path baseline; totals never establish provenance. Invalid supplied
    declarations fail compilation instead of silently changing eligibility.
    """
    declared = _json(stats.get("saving_throw_proficiencies"))
    if declared is None or declared == "None":
        return []
    if not isinstance(declared, list) or any(not isinstance(a, str) or a not in ABILITIES for a in declared):
        raise ValueError("saving_throw_proficiencies must be a list of STR, DEX, CON, INT, WIS, CHA")
    return [ability for ability in ABILITIES if ability in declared]

def _scores(stats: dict[str, Any]) -> dict[str, int]:
    rows = _json(stats.get("abilities")) or []
    return {row["ability"]: int(row["score"]) for row in rows if isinstance(row, dict) and row.get("ability") in ABILITIES}


_DAMAGE_TYPES = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC",
                 "RADIANT", "SLASHING", "THUNDER")


def _weapon_damage_types(text: str) -> list[str]:
    """'1d8 Piercing or Slashing' -> ['PIERCING', 'SLASHING']: the wielder picks per attack."""
    return [word.upper() for word in re.findall(r"[A-Za-z]+", text or "") if word.upper() in _DAMAGE_TYPES] or ["BLUDGEONING"]


def _dice(text: str) -> tuple[DiceSpec, str]:
    """'1d4 Piercing or Slashing' -> (1d4, 'PIERCING')."""
    match = re.match(r"^\s*(\d+)d(\d+)\s+([A-Za-z]+)", text or "")
    if not match:
        return DiceSpec(count=1, sides=4, modifier=0), "BLUDGEONING"
    return DiceSpec(count=int(match.group(1)), sides=int(match.group(2)), modifier=0), match.group(3).upper()


# An enchantment is automated only when it is plain on-hit damage; anything
# conditional or situational reaches the GM as a call on the hit.
_ON_HIT_DAMAGE = re.compile(
    r"^(?:Whenever|When) (?:you hit (?:(?:a creature|a target|an enemy) )?with (?:the|this) weapon|the weapon hits(?: a creature)?), "
    r"(?:it|the target|that creature|the attack) (?:takes|deals) an additional (\d+)d(\d+) (\w+) damage", re.I)
# "... and cannot regain Hit Points until the start of your next turn" (Moonless-Yin Inscription, forged-worker
# 2026-09-29): the same no-healing rider Unmaking's Execution already types (combat/unmaking.py); block_healing_reduction
# (combat/typed_executor.py) reads the evidence text itself, so the clause is passed through verbatim.
_NO_HEAL_CLAUSE = re.compile(r"\b(?:and )?(?:it |the target )?(?:can'?t|cannot) regain hit points[^.]*\.?", re.I)
# "... and its Speed is reduced by N feet until the start of your next turn" (Frost-Meridian Inscription): a real,
# refreshed-per-hit Speed penalty (combat/typed_executor.py block_speed); the printed stacking cap beyond one hit's
# worth (Frost-Meridian: "up to a maximum reduction of 15 feet") is not enforced here -- block_speed's own "refresh,
# don't stack" rule (multiple hits from the same weapon replace the modifier instead of adding it) undershoots the
# print rather than inventing a multi-hit counter, so the GM is told once per hit rather than trusted to add silently.
_SPEED_CLAUSE = re.compile(r"\b(?:and )?its speed is reduced by (\d+) feet?[^.]*\.", re.I)
# Ignite/extinguish toggles with no in-combat consequence on this table (Flame-Vein Inscription): automated as always
# lit rather than a rarely-touched free toggle button (forged-worker 2026-09-29's call) -- the bonus damage is a plain
# rider on top of the weapon's own type, not a light source anything here reacts to (no darkvision/stealth check keys
# off a wielded weapon's flame), so "extinguished" would only ever matter as flavor the GM already narrates freely.
_LIT_TOGGLE = re.compile(r"\byou can ignite or extinguish[^.]*\.\s*while extinguished[^.]*\.", re.I)
# "Whenever ... hits a creature/target/enemy that is X, Y, or Z, it takes an additional NdM TYPE damage" (Dream-Piercing
# Inscription): a real per-hit condition check (combat/ext/forged_treasure.py "conditional_damage"), for the conditions
# this table actually tracks; a clause this table cannot check (a sphere-specific state, "affected by a Dreams Sphere
# effect") stays a rider alongside it rather than silently applying or silently dropping.
_TARGET_STATE_DAMAGE = re.compile(
    r"^(?:Whenever|When) (?:you hit|the weapon hits) (?:a creature|a target|an enemy) that is (.+?), "
    r"(?:it|the target) takes an additional (\d+)d(\d+) (\w+) damage", re.I)
_KNOWN_TARGET_CONDITIONS = {"charmed", "frightened", "unconscious", "poisoned", "blinded", "deafened", "stunned",
                            "paralyzed", "restrained", "prone", "grappled", "incapacitated"}


def _enchantment_on_hit(enchantments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Typed on-hit effects for a treasure weapon's enchantments."""
    effects: list[dict[str, Any]] = []
    for row in enchantments or []:
        from . import ext

        reviewed = ext.run_strict("compile_weapon_enchantment", row)
        if len(reviewed) > 1:
            raise ValueError("Only one provider may compile a weapon enchantment")
        if reviewed:
            effects.extend(reviewed[0])
            continue
        text = " ".join(str(row.get("text") or "").split())
        match = _ON_HIT_DAMAGE.match(text)
        state_match = None if match else _TARGET_STATE_DAMAGE.match(text)
        if match:
            effects.append({"type": "damage", "dice": {"count": int(match.group(1)), "sides": int(match.group(2))},
                            "damage_types": [match.group(3).lower()], "applies_to": "target", "evidence": text[:200]})
            rest = re.sub(r"^(?:and|then)\s+", "", text[match.end():].lstrip(",. "), flags=re.I)
            heal_clause = _NO_HEAL_CLAUSE.search(rest)
            if heal_clause:
                effects.append({"type": "healing_reduction", "applies_to": "target", "evidence": heal_clause.group(0).lstrip("and ")})
                rest = (rest[:heal_clause.start()] + rest[heal_clause.end():]).strip()
            speed_clause = _SPEED_CLAUSE.search(rest)
            if speed_clause:
                effects.append({"type": "speed", "applies_to": "target", "flat": -int(speed_clause.group(1)),
                                "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                "evidence": f"{row.get('name')}: a further hit this round refreshes the -{speed_clause.group(1)} ft "
                                            "penalty rather than stacking it; watch a printed higher stacking cap by hand."})
                rest = (rest[:speed_clause.start()] + rest[speed_clause.end():]).strip()
            rest = _LIT_TOGGLE.sub("", rest).strip(" .,")
            if rest:
                effects.append({"type": "rider", "evidence": f"{row.get('name')}: {rest[:300]}"})
        elif state_match:
            clause, count, sides, damage_type = state_match.groups()
            names = [part.strip(" .").lower() for part in re.split(r",|\bor\b", clause) if part.strip(" .")]
            known = [name for name in names if name in _KNOWN_TARGET_CONDITIONS]
            unknown = [name for name in names if name not in _KNOWN_TARGET_CONDITIONS]
            if known:
                effects.append({"type": "conditional_damage", "applies_to": "target", "when_target_condition": known,
                                "dice": {"count": int(count), "sides": int(sides)}, "damage_types": [damage_type.lower()],
                                "evidence": text[:200]})
                tail = text[state_match.end():].strip(" .")
                pieces = [piece for piece in (f"also applies if {', '.join(unknown)}" if unknown else "", tail) if piece]
                if pieces:
                    effects.append({"type": "rider", "evidence": f"{row.get('name')}: {'; '.join(pieces)[:300]}"})
            else:
                effects.append({"type": "rider", "evidence": f"{row.get('name')}: {text[:300]}"})
        elif text:
            # Nothing dropped silently (owner 2026-09-29 audit: Balanced-Grip, Cloud-Riding and similar non-hit
            # enchantments used to vanish -- no automated effect and no GM line either -- whenever their printed text
            # never says "hit"). What bears on a hit specifically still reaches the GM on each hit (owner 2026-09-29
            # playtest: Ghost-Slaying, Returning and Soundless Edge inscriptions posted a GM line on every hit); a
            # passive property with no hit trigger is shown the same way, once per attack with the weapon, rather than
            # nowhere at all.
            effects.append({"type": "rider", "evidence": f"{row.get('name')}: {text[:300]}"})
    return effects


def _treasure_row(treasure: dict[str, Any], key: str) -> dict[str, Any]:
    return {"item_id": treasure["chassis"]["item_id"], "name": treasure.get("name") or treasure["chassis"]["name"],
            "damage": treasure["chassis"]["damage"], "properties": treasure["chassis"].get("properties") or "",
            "refinement": int(treasure.get("refinement_bonus") or 0), "treasure": True, "key": key,
            "enchantments": list(treasure.get("enchantments") or []),
            "inventory_key": treasure.get("inventory_key") or ("treasure_weapon" if key == "treasure" else f"given.{int(key.removeprefix('given')) - 1}")}


def _catalog_weapon(item_id: Any) -> dict[str, Any] | None:
    """A mundane weapon outside the treasure chassis list (a simple spear such as the duan qiang) as its SRD row.

    Without this a carried weapon gets no attack action at all, so its every option is silently unreachable.
    """
    from factory_authoring.starting_kits import item_definition
    definition = item_definition(str(item_id or "")) or {}
    if definition.get("category") != "weapon":
        return None
    return {"item_id": str(item_id), "name": definition.get("name") or str(item_id), "damage": definition.get("damage") or "",
            "properties": definition.get("properties") or ""}


def _weapon_rows(kit: dict[str, Any], given: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The treasure weapon first, then weapons the owner gave, then every mortal weapon in the kit."""
    from factory_authoring.treasure_weapons import chassis_options

    chassis = {row["item_id"]: row for row in chassis_options()}
    rows = []
    treasure = kit.get("resolved_treasure_weapon")
    if isinstance(treasure, dict) and treasure.get("chassis"):
        rows.append(_treasure_row(treasure, "treasure"))
    for index, item in enumerate(given or []):
        if isinstance(item, dict) and item.get("chassis"):
            rows.append(_treasure_row(item, f"given{index + 1}"))
    replaced = [row["item_id"] for row in rows]
    for item in kit.get("items") or []:
        if item.get("combat_item_key") and item.get("item_id") in replaced:
            replaced.remove(item["item_id"])
            continue  # the refined item is one physical copy, just as in carrying
        row = chassis.get(item.get("item_id")) or _catalog_weapon(item.get("item_id"))
        key = str(item.get("combat_weapon_key") or "")
        if row and all(existing["item_id"] != row["item_id"] or existing.get("treasure") or existing["key"] != key for existing in rows):
            rows.append({"item_id": row["item_id"], "name": item.get("combat_name") or row["name"], "damage": row["damage"],
                         "properties": row.get("properties") or "", "refinement": 0, "treasure": False, "key": key, "enchantments": [],
                         "inventory_key": item.get("combat_item_key") or row["item_id"]})
    return rows


_POUNDS_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?\s*lb", re.I)
_SIZE_CARRY = {"tiny": 0.5, "small": 1, "medium": 1, "large": 2, "huge": 4, "gargantuan": 8}


def _pounds(text: Any) -> float | None:
    if str(text or "").strip() in ("—", "-", "–"):
        return 0.0  # the book's "—": negligible (a bell, ink, paper)
    match = _POUNDS_RE.search(str(text or ""))
    if not match:
        return None
    return float(match.group(1)) / (float(match.group(2)) if match.group(2) else 1.0)


def _carrying(identity: dict[str, Any], kit: dict[str, Any], owner_items: list[dict[str, Any]], strength: int,
              base_ac: int | None = None, mods: dict[str, int] | None = None,
              armor_note: str | None = None) -> dict[str, Any]:
    """2024 Carrying Capacity (owner 2026-09-26: "we dont have weight limits on equipment and weight of items yet? we should
    probably do that as well"; Tianxia's books use the term without defining it): 15 x Strength pounds for a Small or
    Medium creature, doubled per size above. The kit's items (the mundane catalog's printed weights), the treasure weapon
    and armour (their base item's weight; a kit item of the same base counts once) and the items the owner gave.
    ``items`` lists each one with a stable key, for the table's Items panel and dropping things in a fight (owner
    2026-09-27: "we should have a tab for items and equipment. Dropping things should also be an option").

    ``base_ac``/``mods`` are the character's unarmored AC basis, so the "worn" marker here is the same decision
    combat/armour.py makes for the AC number; ``armor_note`` is the plain sentence for the sheet when the answer
    is "carried, not worn".  Without them this stays the plain kit listing.
    """
    from factory_authoring.starting_kits import _authorities

    catalog = _authorities()[1]
    carried: list[dict[str, Any]] = []
    treasures = [("treasure_weapon", row) for row in (kit.get("resolved_treasure_weapon"),) if isinstance(row, dict) and row.get("chassis")]
    treasures += [("treasure_armor", row) for row in (kit.get("resolved_treasure_armor"),) if isinstance(row, dict) and row.get("chassis")]
    treasures += [(f"given.{index}", row.get("record") or {}) for index, row in enumerate(owner_items)
                  if isinstance(row, dict) and (row.get("record") or {}).get("chassis")]
    replaced = [str(row["chassis"].get("item_id") or "") for _, row in treasures]
    seen: dict[str, int] = {}
    for item in kit.get("items") or []:
        if not isinstance(item, dict):
            continue
        quantity = int(item.get("quantity") or 1)
        if item.get("item_id") in replaced:  # the treasure is this item, refined
            replaced.remove(item["item_id"])
            quantity -= 1
        if quantity > 0:
            item_id = str(item.get("item_id") or item.get("name") or "item")
            seen[item_id] = seen.get(item_id, 0) + 1
            key = item.get("combat_item_key") or (item_id if seen[item_id] == 1 else f"{item_id}.{seen[item_id]}")
            carried.append({"key": key, "item_id": item_id, "name": str(item.get("combat_name") or item.get("name") or item_id), "quantity": quantity,
                            "printed": _item_weight(catalog, item.get("item_id")), "category": (catalog.get(item.get("item_id")) or {}).get("armor_category"),
                            "stealth": (catalog.get(item.get("item_id")) or {}).get("stealth"),
                            **({"combat_weapon_key": item["combat_weapon_key"]} if item.get("combat_weapon_key") else {})})
    for key, row in treasures:
        chassis = row["chassis"]
        carried.append({"key": key, "item_id": str(chassis.get("item_id") or ""), "name": str(row.get("name") or chassis.get("name")), "quantity": 1,
                        "printed": chassis.get("weight") or _item_weight(catalog, chassis.get("item_id")), "category": chassis.get("armor_category"),
                        "stealth": chassis.get("stealth"), "treasure": True, "attunement_slots": _treasure_slots(key, row)})
    # Wondrous Treasures bought at creation (owner 2026-09-28, attunement): listed so they can be attuned and dropped.
    for index, row in enumerate(((kit.get("resolved_treasure_purchases") or {}).get("wondrous")) or []):
        if isinstance(row, dict) and not row.get("_left"):
            carried.append({"key": f"wondrous.{index}", "item_id": str(row.get("treasure_id") or ""), "name": str(row.get("name") or "Wondrous Treasure"),
                            "quantity": 1, "printed": row.get("weight"), "category": None, "treasure": True,
                            "attunement_slots": int(row.get("attunement_slots") or 0)})
    worn = _worn_armor_key(carried, kit, base_ac, mods)
    weight, unweighed, items = 0.0, [], []
    for row in carried:
        pounds = _pounds(row["printed"])
        if pounds is None:
            unweighed.append(row["name"])
        else:
            weight += pounds * row["quantity"]
        items.append({"key": row["key"], "item_id": row["item_id"], "name": row["name"], "quantity": row["quantity"],
                      "weight_lb": f"{(pounds or 0) * row['quantity']:g}", "kind": "armor" if row["category"] else "item",
                      "worn": row["key"] == worn, **({"shield": 1} if row["category"] == "shield" else {}),
                      **({"treasure": True} if row.get("treasure") else {}),
                      **({"combat_weapon_key": row["combat_weapon_key"]} if row.get("combat_weapon_key") else {}),
                      **({"attunement_slots": row["attunement_slots"]} if row.get("attunement_slots") else {})})
    capacity = int(15 * int(strength or 10) * _SIZE_CARRY.get(str(identity.get("size") or "medium").lower(), 1))
    # Pounds as text: the bundle's canonical JSON carries no binary floats.
    # Armour that gives Disadvantage on Dexterity (Stealth) checks, worn: the Hide action rolls with it (combat/stealth.py).
    noisy = any(row["key"] == worn and str(row.get("stealth") or "").lower() == "disadvantage" for row in carried)
    return {"weight_lb": f"{weight:g}", "capacity_lb": capacity, "over": weight > capacity, "unweighed": sorted(set(unweighed)), "items": items,
            **({"armor_note": armor_note} if armor_note else {}),
            **({"stealth_disadvantage": True} if noisy else {})}


def equipment_list(owner_sheet: dict[str, Any], owner_items: list[dict[str, Any]] | None = None, attuned: Any = None) -> dict[str, Any]:
    """Everything the character owns, weighed, and which treasures it is attuned to (for the sheet's Items tab; nothing
    left behind)."""
    identity = owner_sheet.get("identity") or {}
    kit = next((row.get("starting_kit") for row in owner_sheet.get("equipment") or [] if isinstance(row, dict) and row.get("starting_kit")), {}) or {}
    kit = _combat_equipment(kit)
    from factory_authoring.owner_items import equipped_armour

    given_armour = equipped_armour(owner_items or [])
    if given_armour:
        kit = {**kit, "resolved_treasure_armor": given_armour}
    mods = _modifiers(owner_sheet["ability_scores_and_statistics"])
    _always_on, base_ac = armour.sheet_ac_bonuses(owner_sheet, kit, mods, [])
    listing = _carrying(identity, kit, list(owner_items or []), _scores(owner_sheet["ability_scores_and_statistics"]).get("STR", 10),
                        base_ac, mods, armour.carried_note(base_ac, kit, mods))
    attuning = attunement(kit, list(owner_items or []), attuned)
    listing["attunement"] = {"used": attuning["used"], "max": attuning["max"], "attuned": attuning["attuned"]}
    for item in listing["items"]:
        if item.get("attunement_slots"):
            item["attuned"] = item["key"] in attuning["attuned"]
    return listing


def _skill_bonus(owner_sheet: dict[str, Any], skill: str, fallback: int) -> int:
    """A skill's bonus as the sheet lists it, else its ability modifier."""
    rows = _json((owner_sheet.get("ability_scores_and_statistics") or {}).get("skills")) or []
    row = next((row for row in rows if isinstance(row, dict) and str(row.get("skill") or "").lower() == skill.lower()), None)
    try:
        return int(row["bonus"]) if row and row.get("bonus") is not None else int(fallback)
    except (TypeError, ValueError):
        return int(fallback)


def compiled_skill_sheet(owner_sheet: dict[str, Any], mechanic_ids: list[str], mechanics: dict[str, Any],
                         mods: dict[str, int], pb: int, notes: list[str]) -> tuple[dict[str, Any], list[str]]:
    """General opt-in skill projections before every compiler skill consumer.

    compile_skill_bonuses providers return changed named skill rows, diagnostic
    notes and wholly handled feature IDs. Explicit totals/ranks travel in the
    ordinary skill row format. Copy only after a contribution; caller input and
    old saved bundles are never changed. No replies preserve historical bytes.
    """
    from . import ext

    stats = owner_sheet["ability_scores_and_statistics"]
    original = _json(stats.get("skills")) or []
    replies = ext.run_strict("compile_skill_bonuses", {
        "skills": copy.deepcopy(original), "owned_ids": tuple(mechanic_ids), "mechanics": mechanics,
        "mods": dict(mods), "pb": pb,
    })
    if not replies:
        return owner_sheet, []
    rows = copy.deepcopy(original)
    handled: set[str] = set()
    for reply in replies:
        if not isinstance(reply, dict):
            raise ValueError("compile_skill_bonuses must return a skill projection dictionary")
        for proposed in reply.get("skills") or []:
            if not isinstance(proposed, dict) or not isinstance(proposed.get("skill"), str) or type(proposed.get("bonus")) is not int:
                raise ValueError("A compiled skill requires a name and an integer bonus")
            existing = next((index for index, row in enumerate(rows)
                             if isinstance(row, dict) and str(row.get("skill")).casefold() == proposed["skill"].casefold()), None)
            if existing is None:
                rows.append(copy.deepcopy(proposed))
            else:
                rows[existing] = {**rows[existing], **copy.deepcopy(proposed)}
        features = reply.get("handled_features") or []
        if any(not isinstance(source, str) or source not in mechanic_ids for source in features):
            raise ValueError("A compiled skill can claim only an owned feature")
        handled.update(features)
        for note in reply.get("notes") or []:
            if not isinstance(note, str):
                raise ValueError("Compiled skill diagnostic notes must be strings")
            notes.append(note)
    return {**owner_sheet, "ability_scores_and_statistics": {**stats, "skills": rows}}, sorted(handled)


def _worn_armor_key(carried: list[dict[str, Any]], kit: dict[str, Any] | None = None,
                    base_ac: int | None = None, mods: dict[str, int] | None = None) -> str | None:
    """The body armour being worn: the treasure armour, else the first body armour in the kit (a shield is carried).

    With the character's AC basis this also asks whether it is worn at all: armour carried because the unarmored
    defense beats it is listed but never marked worn, which is the same decision combat/armour.py makes.
    """
    body = [row for row in carried if row.get("category") and row["category"] != "shield"]
    treasure = next((row for row in body if row.get("treasure")), None)
    if kit is not None and base_ac is not None and mods is not None and armour.wearing(base_ac, kit, mods) is None:
        return None
    return (treasure or (body[0] if body else {})).get("key")


def _leave_behind(kit: dict[str, Any], owner_items: list[dict[str, Any]], keys: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The kit and given items without what the owner leaves behind for this fight (owner 2026-09-27, the sheet's
    Items tab): kit items by key (item id, or id.N for a second of the same), "treasure_weapon", "treasure_armor",
    "given.N"."""
    drop = {str(key) for key in keys or []}
    if not drop:
        return kit, owner_items
    kit = dict(kit)
    for slot, key in (("resolved_treasure_weapon", "treasure_weapon"), ("resolved_treasure_armor", "treasure_armor")):
        if key in drop:
            kit.pop(slot, None)
    purchases = kit.get("resolved_treasure_purchases") or {}
    if purchases.get("wondrous"):
        kit["resolved_treasure_purchases"] = {**purchases, "wondrous": [{**row, "_left": True} if f"wondrous.{index}" in drop and isinstance(row, dict) else row
                                                                         for index, row in enumerate(purchases["wondrous"])]}
    kept, seen = [], {}
    for item in kit.get("items") or []:
        item_id = str((item or {}).get("item_id") or (item or {}).get("name") or "item")
        seen[item_id] = seen.get(item_id, 0) + 1
        if (item.get("combat_item_key") or (item_id if seen[item_id] == 1 else f"{item_id}.{seen[item_id]}")) not in drop:
            kept.append(item)
    kit["items"] = kept
    return kit, [row for index, row in enumerate(owner_items) if f"given.{index}" not in drop]


def _treasure_slots(key: str, row: dict[str, Any]) -> int:
    """Attunement slots a treasure takes: the treasure weapon and armour one each (the creation plan's count,
    factory_authoring/treasure_catalog.py); a given item its own record's."""
    if key in ("treasure_weapon", "treasure_armor"):
        return 1
    return int(row.get("attunement_slots") or 0)


def attunement(kit: dict[str, Any], owner_items: list[dict[str, Any]], chosen: Any) -> dict[str, Any]:
    """Which treasures the character is attuned to (owner 2026-09-28: "attunement ... include that with the major stuff"):
    at most four slots. Nothing chosen yet means the creation plan (every treasure it bought, which fit in four); a choice
    keeps the items named, in the kit's order, while they fit."""
    from factory_authoring.treasure_catalog import ATTUNEMENT_SLOTS

    rows = []
    for key, slot in (("treasure_weapon", "resolved_treasure_weapon"), ("treasure_armor", "resolved_treasure_armor")):
        if isinstance(kit.get(slot), dict) and kit[slot].get("chassis"):
            rows.append((key, 1))
    for index, row in enumerate(((kit.get("resolved_treasure_purchases") or {}).get("wondrous")) or []):
        if isinstance(row, dict) and not row.get("_left") and int(row.get("attunement_slots") or 0) > 0:
            rows.append((f"wondrous.{index}", int(row["attunement_slots"])))
    for index, row in enumerate(owner_items or []):
        record = (row or {}).get("record") or {}
        if int(record.get("attunement_slots") or 0) > 0:
            rows.append((f"given.{index}", int(record["attunement_slots"])))
    wanted = {str(key) for key in chosen} if chosen is not None else None
    attuned, used = [], 0
    for key, slots in rows:
        if (wanted is None or key in wanted) and used + slots <= ATTUNEMENT_SLOTS:
            attuned.append(key)
            used += slots
    return {"attuned": attuned, "used": used, "max": ATTUNEMENT_SLOTS, "attunable": [key for key, _ in rows]}


def _unattuned(kit: dict[str, Any], owner_items: list[dict[str, Any]], attuned: set[str], attunable: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A treasure that needs attunement and isn't attuned fights as its base item: no refinement bonus, no enchantments."""
    def plain(row: dict[str, Any]) -> dict[str, Any]:
        name = re.sub(r"\s*\+\d+\b", "", str(row.get("name") or (row.get("chassis") or {}).get("name") or "Treasure")).strip()
        return {**row, "refinement_bonus": 0, "enchantments": [], "enhancements": [], "unattuned": True, "name": f"{name} (unattuned)"}
    kit = dict(kit)
    for key, slot in (("treasure_weapon", "resolved_treasure_weapon"), ("treasure_armor", "resolved_treasure_armor")):
        if key in attunable and key not in attuned and isinstance(kit.get(slot), dict):
            kit[slot] = plain(kit[slot])
    owner_items = [({**row, "record": plain(row["record"])} if f"given.{index}" in attunable and f"given.{index}" not in attuned
                    and isinstance((row or {}).get("record"), dict) else row) for index, row in enumerate(owner_items or [])]
    return kit, owner_items


def _item_weight(catalog: dict[str, Any], item_id: Any) -> Any:
    """The catalog's printed weight, or for an Item Book weapon without one, the 2024 weight of its SRD equivalent
    (combat/rules/weapon_specials.json, owner-editable)."""
    return (catalog.get(item_id) or {}).get("weight") or (weapon_specials().get(str(item_id)) or {}).get("weight")


def _carries_shield(kit: dict[str, Any], owner_items: list[dict[str, Any]] | None = None) -> bool:
    """Any Shield the kit holds, in either storage slot (combat/armour.py is the one reader)."""
    return armour.carries_shield(kit, owner_items)


def _worn_armor(kit: dict[str, Any], base_ac: int | None = None, mods: dict[str, int] | None = None) -> str | None:
    """The body armour's category ("light", "medium", "heavy"), None when unarmoured; a shield is not body armour.

    With the character's unarmored AC this is the *worn* answer: armour carried because it is worse than going
    without it grants no category, so "while not wearing armour" features (Dragon Scales, Stone Skin) apply.
    """
    return armour.worn_armor_category(kit, base_ac, mods)


WEAPON_SPECIALS_PATH = Path(__file__).resolve().parent / "rules" / "weapon_specials.json"
_WEAPON_SPECIALS: dict[str, Any] = {}


def _weapon_rules() -> dict[str, Any]:
    """The owner-editable weapon file (combat/rules/weapon_specials.json), re-read when it changes."""
    mtime = WEAPON_SPECIALS_PATH.stat().st_mtime_ns if WEAPON_SPECIALS_PATH.exists() else None
    if _WEAPON_SPECIALS.get("mtime") != mtime:
        data = json.loads(WEAPON_SPECIALS_PATH.read_text(encoding="utf-8")) if mtime is not None else {}
        _WEAPON_SPECIALS.update(mtime=mtime, data=data)
    return _WEAPON_SPECIALS["data"]


def weapon_specials() -> dict[str, Any]:
    return _weapon_rules().get("weapons") or {}


def _has_property(properties: str, name: str) -> bool:
    """A whole weapon property: "Heavy" is not "Heavy-Headed", "Light" is not "Lightning"."""
    return bool(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", properties or ""))


def _weapon_proficiency(owner_sheet: dict[str, Any], ids: list[str], weapons: list[dict[str, Any]], *, choices: bool = True) -> list[bool]:
    """Owner 2026-09-26 ("proficiency if applicable"): each Path's weapon training (a Path added later adds its
    own), plus the Sphere abilities, talents and Subpath features that grant a weapon group, all listed in
    combat/rules/weapon_specials.json. A grant that lets the player choose ("one saber-profile weapon", Sniper
    Training's one ranged weapon) is not recorded on the sheet, so it covers the weapons the character carries,
    the treasure weapon first."""
    from factory_authoring.starting_kits import _authorities

    rules = _weapon_rules().get("proficiency") or {}
    catalog = _authorities()[1]
    paths = (owner_sheet.get("path_and_subpath") or {}).get("path_record_ids") or []
    classes = {name for path in paths for name in (rules.get("classes_by_path") or {}).get(path, [])}
    owned = set(ids) | set((owner_sheet.get("spheres_and_talents") or {}).get("sphere_record_ids") or [])
    names = [weapon["item_id"].split(".")[-1] for weapon in weapons]
    proficient = [(catalog.get(weapon["item_id"]) or {}).get("proficiency") in classes for weapon in weapons]
    for key, grant in (rules.get("grants") or {}).items():
        if key not in owned:
            continue
        groups = [(rules.get("groups") or {}).get(name, []) for name in _grant_groups(grant)]
        members = "*" if "*" in groups else [name for group in groups if isinstance(group, list) for name in group]
        eligible = [index for index, name in enumerate(names) if members == "*" or name in members]
        if grant.get("choose") and not choices:
            continue
        if grant.get("choose"):
            picked: list[str] = []
            for index in eligible:
                if names[index] not in picked and len(picked) < int(grant["choose"]) and not proficient[index]:
                    picked.append(names[index])
            eligible = [index for index in eligible if names[index] in picked]
        for index in eligible:
            proficient[index] = True
    return proficient


def _meets(requirement: Any, proficient: bool) -> bool:
    """A mastery's or maneuver's prerequisite (combat/rules/weapon_specials.json): "proficiency" or none."""
    return proficient if requirement == "proficiency" else True


# The 2024 weapon mastery properties, as typed effects on the weapon's attacks (owner 2026-09-26).
_UNTIL_YOUR_NEXT_TURN = "START_OF_SOURCE_NEXT_TURN"


def _mastery_effects(mastery: str | None, ability_mod: int, damage_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(on-hit effects, on-miss effects). Nick changes the off-hand attack's economy instead (compile_character)."""
    if mastery == "Cleave":
        return [{"type": "cleave", "ability_mod": ability_mod}], []
    if mastery == "Graze":  # a miss still deals the ability modifier as the weapon's damage type
        return [], ([{"type": "damage", "flat": ability_mod, "damage_types": [damage_type], "applies_to": "target"}] if ability_mod > 0 else [])
    if mastery == "Push":  # "if it is Large or smaller"
        return [{"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target", "max_size_cells": 2}], []
    if mastery == "Sap":
        return [{"type": "disadvantage", "on": "its next attack roll", "applies_to": "target", "expires_on": _UNTIL_YOUR_NEXT_TURN}], []
    if mastery == "Slow":
        return [{"type": "speed", "amount": -10, "applies_to": "target", "expires_on": _UNTIL_YOUR_NEXT_TURN}], []
    if mastery == "Topple":
        return [{"type": "save", "ability": "CON", "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}]}], []
    if mastery == "Vex":  # Advantage on the next attack roll against that creature, until the end of your next turn
        return [{"type": "vex"}], []
    return [], []


def _maneuver_effect(maneuver: dict[str, Any]) -> dict[str, Any]:
    """A Pathfinder-style maneuver added to one hit: the target saves or suffers it."""
    if maneuver.get("pull_ft"):
        on_fail = [{"type": "forced_movement", "distance_ft": int(maneuver["pull_ft"]), "direction": "toward", "applies_to": "target"}]
    else:
        names = maneuver["condition"] if isinstance(maneuver["condition"], list) else [maneuver["condition"]]  # Pin: grappled and pinned
        on_fail = [{"type": "condition", "condition": str(name).lower(), "applies_to": "target",
                    **({"until_escape": True} if maneuver.get("until_escape") else {}),
                    **({"expires_on": _MANEUVER_ENDS[maneuver["ends"]]} if maneuver.get("ends") in _MANEUVER_ENDS else {})} for name in names]
    return {"type": "save", "ability": str(maneuver["save"]).upper(), "on_fail": on_fail, "first_hit_only": True,
            **({"max_size_larger": int(maneuver["max_size_larger"])} if maneuver.get("max_size_larger") is not None else {}),
            **({"advantage_if_larger": int(maneuver["advantage_if_larger"])} if maneuver.get("advantage_if_larger") is not None else {})}


_MANEUVER_ENDS = {"start_of_your_next_turn": "START_OF_SOURCE_NEXT_TURN", "end_of_its_next_turn": "END_OF_HOLDER_NEXT_TURN"}


def _melee_reach(properties: str) -> int:
    """Reach adds 5 feet (10 ft); "Reach 15" prints its own distance. Variable Reach is a handling tag, not Reach."""
    match = re.search(r"(?<!Variable )\bReach\b(?: (\d+))?", properties)
    return (int(match.group(1)) if match and match.group(1) else 10) if match else 5


def _maximum_hp(stats: dict[str, Any], diagnostics: list[str]) -> int:
    """Require a positive integer HP maximum before any fighter can be admitted."""
    hit_points = _json(stats.get("hit_points"))
    raw = hit_points.get("maximum") if isinstance(hit_points, dict) else None
    try:
        maximum = int(raw)
    except (TypeError, ValueError, OverflowError):
        maximum = 0
    if maximum > 0 and not isinstance(raw, (bool, float)):
        return maximum
    from app.core import FoundryError

    raise FoundryError("COMBAT_HIT_POINTS_INVALID",
                        "This character's sheet has no valid maximum Hit Points, so they cannot be sent into a fight. "
                        "Re-create the character, or ask the Game Master to fix their hit points.", status_code=409)


def _ac_basis(stats: dict[str, Any]) -> tuple[int, int]:
    """The sheet's two Armor Class numbers, read once: the base calculation and the always-on bonuses.

    The sheet publishes both (character_sheet/service.py): ``base_value`` is the chosen calculation on its own
    (10 + Dexterity, or a Path's own), and ``value`` is that calculation plus the bonuses it has already folded
    in.  They are kept apart because the owner amendment R1 (rule /rules/0) says "Explicit AC bonuses apply
    after selecting the calculation": the calculation may be replaced by worn armour, the bonuses may not be
    thrown away with it.  Reading ``base_value`` alone (what this did before AUDIT9 row 2) lost every always-on
    bonus.

    Returns ``(base, always_on)``.  A sheet that publishes only one number reports that number as the base with
    no bonus, which is the old behaviour.
    """
    ac = _json(stats.get("armor_class")) or {}
    if not isinstance(ac, dict):
        return int(ac or 10), 0
    base = int(ac.get("base_value") or ac.get("value") or 10)
    return base, int(ac.get("value") or base) - base


def _attack_ability(options, *, sheet, owned_ids, mods, source, kind):
    """General selection seam for typed attack options and owned ability grants."""
    from . import ext

    info = {"owner_sheet": sheet, "owned_ids": owned_ids, "mods": mods, "source": source, "kind": kind}
    selected = list(ext.run("compile_attack_ability", tuple(options), info))
    return selected[-1] if selected else max(options, key=lambda ability: mods.get(ability, 0))


def _combat_equipment(kit):
    """General equipment normalization seam, shared by compilation and item lists.

    Optional combat_item_key/combat_weapon_key retain individual item identities
    across inventory, attack variants, and leave-behind choices. With no hook,
    equipment is unchanged.
    """
    from . import ext

    for items in ext.run("compile_equipment_items", kit.get("items") or []):
        kit = {**kit, "items": items}
    return kit


def _typed_numbers(sheet: dict[str, Any], mods: dict[str, int], pb: int) -> dict[str, int]:
    stats = sheet["ability_scores_and_statistics"]
    key = str((sheet.get("identity") or {}).get("key_ability") or "INT").upper()[:3]
    identity = sheet.get("identity") or {}
    actual_cl = int(identity.get("cultivation_level") or identity.get("cl") or 1)
    # General admission seam for an explicitly recorded Realm suppression.
    # Missing effective level preserves ordinary compilation; suppression can
    # reduce source authority, never grant levels above the acquired level.
    effective_cl = identity.get("effective_cultivation_level", actual_cl)
    if type(effective_cl) is not int or not 1 <= effective_cl <= actual_cl:
        raise ValueError("Effective Cultivation Level must be between 1 and the acquired level")
    return {"pb": pb, "save_dc": int(stats.get("technique_save_dc") or 8 + pb), "attack_bonus": int(stats.get("technique_attack_bonus") or pb),
            "key_mod": mods.get(key, 0), "con_mod": mods.get("CON", 0),
            "cl": effective_cl}


def _is_self_teleport(effect: Any) -> bool:
    return isinstance(effect, dict) and (effect.get("type") == "teleport" or (effect.get("type") == "movement" and effect.get("mode") == "teleport")) \
        and effect.get("applies_to") in (None, "self")


_STAT_SEGMENT = re.compile(r"(Range|Cost|Duration|Area|Action Type|Use Limit)\s*:\s*([^.;:/]*)[.;]?\s*", re.I)
_PLAIN_COST = re.compile(r"\+?\d+ (?:CP|Qi|Stamina|Resonance)|None|Expend (?:your )?Martial Focus", re.I)
# A prerequisite the table settled at character creation: the character owns the ability or it does not, so no GM has
# anything to resolve mid-fight ("Prerequisite: CL 15+", "Prerequisite: Anchor Gate, CL 15", "Prerequisites: ...").
_RUNTIME_PREREQUISITE = re.compile(r"\b(?:target|creature|subject|self)\b|\bGM\b|\bDC\b|permission|approval", re.I)


def _creation_prerequisite(line: str) -> bool:
    """Whether a printed "Prerequisite:" line is character-creation information rather than a fight-time condition.

    133 printed mechanics carry such a line and none of them is the GM's to apply in a fight: the character sheet
    already says the character learned the talent, which is what the prerequisite decided. A prerequisite the table
    has to check when the ability is used -- "Prerequisite: The target is Bound, Grappled, Restrained, or attached to
    one of your Tethers", "... GM approval. DC: 32 or higher." -- is a fight-time condition and keeps its line.
    """
    head, separator, value = line.partition(":")
    if not separator or head.strip().lower() not in ("prerequisite", "prerequisites"):
        return False
    return not _RUNTIME_PREREQUISITE.search(value)


def _typed_stat_line(line: str, mechanic: dict[str, Any]) -> bool:
    """A line made only of stat entries ("Range: 60 feet. Cost: 2 CP.") whose every part the typing carries: an Area only
    when the area is typed, a Use Limit only when one is typed, a Cost only when plain (CP, Qi, Stamina, Resonance, Martial
    Focus) and typed -- "8 CP and three Reagent Stock" keeps its line."""
    position, parts = 0, []
    for match in _STAT_SEGMENT.finditer(line):
        if match.start() != position:
            return False
        parts.append((match.group(1).lower(), match.group(2).strip()))
        position = match.end()
    if not parts or position != len(line):
        return False
    for label, value in parts:
        if (label == "area" and not mechanic.get("area")) or (label == "use limit" and mechanic.get("use_limit") in (None, "", "none")):
            return False
        if label == "cost" and (not _PLAIN_COST.fullmatch(value) or (value.lower() != "none" and not mechanic.get("cost"))):
            return False
    return True


_CL_DAMAGE_LINE = re.compile(r"(?:The )?damage increases by \d+d\d+ at CL \d+(?:,? (?:and )?CL \d+)*\.?"
                             r"|(?:At CL \d+, the damage becomes \d+d\d+\.?\s*)+"
                             r"|(?:\w+ )?Damage by (?:CL|Cultivation Level)\b.*|Cultivation Level: \d+\s*[-–]\s*\d+[;,]?\s*Damage:.*"
                             # The same restatement in its other printed words: "Damage scales with Cultivation Level: 1-4: 1d8...",
                             # "Damage Reduction scales with Cultivation Level: ...", "The damage increases to 2d8 at CL 5, 3d8 at CL 11".
                             r"|.*\b(?:increases|scales|grows)\b.*\b(?:CL|Cultivation Level)\b.*", re.I)
# A note about the typing itself, left in a rider by whoever corrected it ("Was hard-coded to the CL1-10 bracket ...",
# "... is automated (combat/ext/bodyb_motion.py ...)", "Owner 2026-09-28 split: ..."): it says what the table already does,
# so it is not the GM's to apply. "Not automated: ..." lines stay.
_TYPING_HISTORY = re.compile(r"^(?:Was |Previously |The previous typing|Corrected (?:the|from) |Retyped |Recommend to the integrator|(?:Owner|Body|Integrator) 20\d\d-\d\d-\d\d\b)", re.I)
_TYPING_NOTE = re.compile(r"\b(?:is|are) (?:automated|enforced|implemented)\b|\b(?:[Aa]utomated|[Ii]mplemented|[Ee]nforced) (?:by|via|in) combat/", re.I)
# A note that also says what the table leaves out or changes stays: the GM or the owner needs it.
_STILL_THE_GMS = re.compile(r"\bGM\b|\bnot\b|n't\b|\bonly\b|\bcannot\b|approximat|BLOCKED|instead of the print", re.I)
_NOT_A_WEAPON_LINE = re.compile(r"[^.]{0,80}\bis (?:a Cultivation Attack, not a weapon attack|not an ordinary weapon attack, unarmed strike,"
                                r" spell, or Attack action)[^.]*\.?", re.I)


# The printed choices of a "choose one" menu, read from the owner's own text rather than from the typed
# options: "When you create the Current, choose one Vector:" then one "Lift: ...", "Press: ..." clause each.
# A clause that names one of these belongs to that choice alone, so the label set used to attribute a clause
# away from the other options includes every printed choice, not only the ones the table offers. Without it a
# printed choice with no button (hunt105 #1, AIR Gather Current's fifth Vector "Carry") failed the "is this a
# sibling option?" test, survived on every option, and was shown on all of them as if it were the pressed
# Vector's own caveat.
_CHOICE_CUE = re.compile(r"\bchoose\s+(?:one|up to one|a single|any one)\b[^:\n]*:", re.I)
_CHOICE_HEAD = re.compile(r"^[ \t>*#-]*([A-Z][A-Za-z0-9 \-\'()/]{0,38}?):\s")


def _printed_choices(mechanic: dict[str, Any]) -> set[str]:
    """Every choice name the printed text of a choose-one menu offers, lower-cased, whether or not the table
    implements it as an option. Empty for an ability that does not print a menu, so abilities without one are
    unaffected."""
    text = _rules_text().get(str(mechanic.get("mechanic_id") or ""), "")
    if not text or not (mechanic.get("options") or []):
        return set()
    choices: set[str] = set()
    armed = False
    for line in text.splitlines():
        if _CHOICE_CUE.search(line):
            armed = True
            continue
        if not armed:
            continue
        head = _CHOICE_HEAD.match(line)
        if head:
            choices.add(head.group(1).strip().lower())
        elif line.strip():
            armed = False  # the menu's own list ended; later prose is not a choice clause
    return choices


def _gm_lines(riders: list[Any], mechanic: dict[str, Any], effects: list[Any], option_label: str | None = None) -> list[str]:
    """The GM-only lines worth showing (playtest 2026-09-29: the owner sees every one in the fight log, and the table marks
    an action "partial" when it has any). Leftover printed lines the typing already carries are dropped: stat lines
    ("Range: 60 feet", "Cost: 2 Resonance", "Area: 30-foot cone" when the area is typed), CL damage tables when the damage
    scales by CL, "... is a Cultivation Attack, not a weapon attack", and notes about the typing itself. On one option of a choose-one menu, a line
    naming another option ("Scatter: ...") belongs to that option only."""
    labels = {str(option.get("label") or "").strip().lower() for option in mechanic.get("options") or [] if isinstance(option, dict)}
    labels |= _printed_choices(mechanic)
    scales = any(row.get("dice_by_cl") for row in _walk(effects))
    from .typed_reactions import rules as block_rules

    # Sentences a feature_blocks entry says the table now does ("covers": ["Structures and unattended objects take double damage."]).
    # A covers entry may also be a short tail phrase of the printed rider ("Formation Anchors take double damage."): the rider
    # sentence that ends with the phrase is the one the table resolves, so it is dropped from the GM-only lines. A whole-sentence
    # entry ends with itself and matches exactly as before.
    covers = [" ".join(str(text).lower().split()) for text in ((block_rules().get("features") or {}).get(str(mechanic.get("mechanic_id") or "")) or {}).get("covers") or []]
    kept = []
    for rider in riders or []:
        line = " ".join(str(rider).split())
        if covers:
            line = " ".join(part for part in re.split(r"(?<=[.;])\s+", line)
                            if not any(" ".join(part.lower().split()).endswith(cover) for cover in covers))
        head = line.split(":", 1)[0].strip().lower() if ":" in line else ""
        if not line or _typed_stat_line(line, mechanic) or _creation_prerequisite(line):
            continue
        if (scales and _CL_DAMAGE_LINE.fullmatch(line)) or _NOT_A_WEAPON_LINE.fullmatch(line):
            continue
        if (_TYPING_HISTORY.match(line) and not re.search(r"\bGM\b", line)) or (_TYPING_NOTE.search(line) and not _STILL_THE_GMS.search(line)):
            continue
        if option_label is not None and head in labels and head != option_label.strip().lower():
            continue
        kept.append(line if covers else rider)
    return kept


def _aims_at_a_foe(effect: dict[str, Any], reach_ft: int | None) -> bool:
    """Whether this row lands on another creature, the only thing that makes an ability a hostile one (offered next to a
    foe, cast at a foe). A row that says "self", "ally" or "allies" is not aimed at a foe whatever its type (a Condition the
    user takes on, a Saving Throw an ally makes), and "creatures in the area" / "the attacker" with no reach to aim them
    is an aura or a trigger around the user (hunt 3, bug 3: Demon Emperor Incarnation, Deep Root Stance and 50 more self
    and ally forms needed a foe in 5 feet to be used at all, then landed their buff or their save on that foe).  The one
    exception is a Reaction denied to "the attacker": "do not provoke Opportunity Attacks from one creature of your
    choice" (Furnace Step) names a creature the user picks, so it still needs one aimed at."""
    if effect.get("deferred"):
        return False  # a later "once per turn when you hit, add 1d6" rides the user's own hits (fight audit 2026-09-29)
    applies = effect.get("applies_to")
    if applies in ("self", "ally", "allies") or (applies in ("enemies_in_area", "creatures_in_area") and not reach_ft):
        return False
    if applies == "attacker" and not reach_ft and effect.get("type") != "reaction_denied":
        return False
    # A mark placed on another creature is aimed at it too (Astra's audit, 2026-09-26: Mark the Waning could only
    # target allies); a mark on yourself or an ally is not. "harmful": a plug-in's effect aimed at a foe (combat/ext).
    if effect.get("type") == "mark" and effect.get("once_per_creature"):
        return False  # book-keeping ("a creature can benefit only once"), not something done to a foe (Meridian Stitch: Restore CP)
    return bool(effect.get("type") in _HARMFUL or effect.get("harmful") or (effect.get("type") == "mark" and applies in ("target", None)))


def _reach_feet(reach: dict[str, Any] | None, cl: Any = 1) -> tuple[int | None, int | None]:
    """A row's printed reach in feet, and the level-dependent value when it has one. Shared by every reading of a
    row's Range so a target point and the area's own placement can never disagree: "Self"/"unlimited" is None, a
    reviewed level-dependent range (Soundwalk Step: 30 / 60 / 90 feet) wins, and "sight" is the table's 120 feet."""
    reach = reach or {}
    feet = reach.get("feet") if reach.get("kind") in {"feet", "touch", "reach"} else None
    scaled = next((int(value) for low, high, value in reach.get("feet_by_cl") or []
                   if int(low) <= int(cl or 1) <= int(high)), None)
    if scaled is not None:
        feet = scaled
    long = reach.get('long_feet')
    if type(feet) is int and type(long) is int and 0 < feet < long:
        feet = long  # Public targeting covers both bands; typed metadata keeps the normal band.
    if reach.get("kind") == "sight":
        feet = 120
    return feet, scaled


def _placed_at_aim(area: dict[str, Any] | None, feet: int | None) -> bool:
    """Whether a line or cone is laid down at the point its user aims at instead of running out from them.

    A printed Range longer than the shape's own length is a placement range, not a length: Earthbind Line is
    "Range: 60 feet ... Area: 20-foot line", so the user picks a point up to 60 feet away and the 20-foot line is
    laid down starting there (hunt 68). Two cases are NOT placed, and keep running from the caster: a shape the
    authority marks ``centered_on_self`` (an aura or an emanation), and a shape whose own length IS the range
    (Heaven-Splitting Gale: a 300-foot line with Range 300 feet -- aiming 300 feet away and running 300 feet
    further would double its printed reach)."""
    if not area or area.get("shape") not in ("line", "cone") or area.get("centered_on_self"):
        return False
    size = int(area.get("size_ft") or 0)
    return bool(feet) and size > 0 and int(feet) > size


def _aimed_area(mechanic: dict[str, Any], cl: Any = 1) -> dict[str, Any] | None:
    """The area as the shapes that are laid down at the aim point are marked for combat/typed_executor.py
    ``in_area``: a ``placed`` line or cone starts AT the point its user chose and runs on away from them, every
    other line and cone runs out from the user. The printed area is returned unchanged otherwise, so an unplaced
    ability's compiled data stays exactly what it was."""
    area = mechanic.get("area")
    feet, _ = _reach_feet(mechanic.get("range"), cl)
    return {**area, "placed": True} if _placed_at_aim(area, feet) else area


def _target_kind(mechanic: dict[str, Any], cl: Any = 1) -> tuple[str, int | None]:
    area, reach = mechanic.get("area"), mechanic.get("range") or {}
    feet, scaled = _reach_feet(reach, cl)
    # Explicit reviewed creature domains reuse native recipients.allowed;
    # sight, range, Charm and plug-in restrictions remain authoritative.
    target = mechanic.get("target")
    if isinstance(target, dict) and target.get("kind") == "any_creature":
        return "ANY_CREATURE", feet
    harmful = any(_aims_at_a_foe(effect, feet) for effect in mechanic.get("effects") or [])
    if not harmful and not (area and area.get("size_ft")) and any(_is_self_teleport(effect) for effect in mechanic.get("effects") or []):
        # "Teleport to an unoccupied space you can see within range" (Empty Step; owner 2026-09-28: "the only options are
        # on tokens and when i click them nothing happens"): the user picks a square (combat/gate4_engine.py
        # _action_candidates), not a creature; the reach is the teleport's own distance, else the printed range.
        distances = [int(effect["distance_ft"]) for effect in mechanic.get("effects") or []
                     if _is_self_teleport(effect) and str(effect.get("distance_ft") or "").isdigit() and int(effect["distance_ft"]) > 0]
        return "SELF", scaled if scaled is not None else max(distances) if distances else feet
    if area and area.get("size_ft"):
        if area.get("shape") in ("line", "cone"):
            # A separate numeric Range places the whole shape at a point within that distance (e.g. Earthbind Line:
            # Range 60 feet, Area 20-foot line), and _aimed_area marks the area so the shape is laid down there.
            # Self-origin shapes, and a line whose own length IS its range, are aimed by their own length.
            if _placed_at_aim(area, feet):
                return "CELL", int(feet)
            return "CELL", int(area["size_ft"])
        if feet:
            return "CELL", feet
        return "SELF", None
    if reach.get("kind") == "self" or (not harmful and not feet):
        return "SELF", None
    if harmful:
        return "HOSTILE_ENTITY", feet or 5
    return "ALLY_OR_SELF", feet or 5


PATH_POOLS = {"tianxia.path.body_refining": "stamina", "tianxia.path.qi_cultivation": "qi", "tianxia.path.spirit_awakening": "resonance"}


def _foundation_resource(owner_sheet: dict[str, Any]) -> dict[str, Any] | None:
    """The character's Foundation resource (e.g. Mirror Trace), owner 2026-09-25: a
    ``ResourceDefinition`` so a typed cost like "Spend 1 Mirror Trace" has a pool to
    spend from, kept with its printed name so ``_costs`` can recognize that cost text
    without teaching the shared parser every Foundation's own resource name."""
    resource = (owner_sheet.get("foundation") or {}).get("resource") or {}
    name, resource_id, maximum = resource.get("name"), resource.get("resource_id"), resource.get("maximum")
    if not name or not resource_id or maximum is None:
        return None
    initial = resource.get("current", resource.get("initial_current", 0))
    # The combat id carries the printed name, since the table shows resources by their id ("Mirror Trace",
    # not "Dream Mirror Soul Anchor V0 2B"); the sheet's own id stays on the sheet.
    combat_id = "resource:foundation." + re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return {"name": str(name), "resource_id": combat_id, "sheet_resource_id": str(resource_id),
            "definition": ResourceDefinition(resource_id=combat_id, initial=int(initial), maximum=int(maximum))}


def _named_list(named: Any) -> list[dict[str, Any]]:
    """The character's named resources, longest name first: its Foundation's pool and every Sphere or Path pool
    it uses (owner 2026-09-26). Accepts one Foundation resource (the older call sites) or the list."""
    rows = [named] if isinstance(named, dict) else list(named or [])
    return sorted(rows, key=lambda row: -len(row["name"]))


_NUMBER_WORDS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _named_match(text: str, named: Any) -> tuple[dict[str, Any], int | None] | None:
    """The named resource ``text`` mentions, with the number printed just before it ("Spend 2 Devoured Essence",
    "one Reagent Stock")."""
    text = str(text or "").replace("’", "'")
    for row in _named_list(named):
        for match in re.finditer(rf"(?:\b(\d+|one|two|three|four|five|a|an)\s+)?\b({re.escape(row['name'])})(?:e?s)?\b", text, re.I):
            before = text[:match.start(2)].split()
            if row["name"].lower() in _GENERIC_POOL_NAMES and before and before[-1][:1].isupper() and not before[-1].isdigit():
                continue  # "Mark" the pool is not the last word of "Waning Mark" (audit F6)
            number = match.group(1)
            return row, (int(number) if number and number.isdigit() else _NUMBER_WORDS.get((number or "").lower()))
    return None


def _named_amount(value: Any, numbers: dict[str, Any], default: int) -> int:
    if isinstance(value, bool) or value is None or value == "none":
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"pb\+\d+", value):  # "pb+3": Proficiency Bonus + 3 (Constellation Circuit)
        return int(numbers.get("pb") or 2) + int(value.split("+", 1)[1])
    return {"pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1), "half_pb": int(numbers.get("pb") or 2) // 2,
            "double_pb": 2 * int(numbers.get("pb") or 2),
            "key_ability_modifier": max(1, int(numbers.get("key_mod") or 1))}.get(str(value), default)


# A pool name this generic ("Mark", "Essence", "Momentum") is a word, not a resource of its own.
_GENERIC_POOL_NAMES = {"mark", "marks", "bearing", "essence", "momentum", "pattern", "calamity", "measure", "remnant", "charge", "debt",
                       "point", "die", "token", "trace", "seed", "spark", "strain", "stack", "pulse", "echo", "edge"}


def _owner_labels(ids: list[str], mechanics: dict[str, Any], sphere_names: dict[str, str]) -> set[str]:
    """The Spheres, Foundations, Paths and Subpaths a character's abilities come from, labelled as
    tools/type_resources.py labels a resource's owners."""
    labels = set()
    for key in ids:
        mechanic = mechanics.get(key) or {}
        if mechanic.get("sphere_id"):
            labels.add("Sphere: " + str(sphere_names.get(mechanic["sphere_id"]) or mechanic["sphere_id"]))
        for field, label in (("foundation_id", "Foundation"), ("subpath_id", "Subpath"), ("path_id", "Path")):
            if mechanic.get(field):
                labels.add(f"{label}: {mechanic[field]}")
    return labels


def _named_pools(ids: list[str], mechanics: dict[str, Any], resources: dict[str, Any], numbers: dict[str, Any],
                 foundation: dict[str, Any] | None, sphere_names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every named pool the character's own abilities gain, spend or cost (owner 2026-09-26: "we need the
    different resources to be generated and placed on characters"): Devoured Essence, Charges, Merit Dice...
    Their printed maximum and starting amount come from the authority's ``resources`` (tools/type_resources.py);
    a combat resource each, so gains land, costs are paid and nothing runs free."""
    texts: list[str] = []
    for key in dict.fromkeys(ids):
        mechanic = mechanics.get(key) or {}
        texts += [str((mechanic.get("activation") or {}).get("trigger") or "")]
        texts += [str(part.get("text") or part.get("resource") or "") for option in mechanic.get("cost") or [] for part in option]
        stack = [*(mechanic.get("effects") or []), *(effect for option in mechanic.get("options") or [] for effect in option.get("effects") or []),
                 *((mechanic.get("modifier") or {}).get("effects") or [])]
        while stack:
            effect = stack.pop()
            if isinstance(effect, dict):
                texts.append(str(effect.get("evidence") or ""))
                stack += [row for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects") for row in effect.get(branch) or []]
    text = " ".join(texts).replace("_", " ").replace("’", "'")
    owners = _owner_labels(ids, mechanics, sphere_names or {})
    rows = []
    for definition in resources.values():
        name = str(definition.get("name") or "")
        if definition.get("kind") != "pool" or not name or (foundation and name.lower() == foundation["name"].lower()):
            continue
        if not owners & set(definition.get("owners") or []):
            continue  # a pool of a Sphere/Foundation/Path this character does not have
        if not re.search(rf"\b{re.escape(name)}(?:e?s)?\b", text, re.I):
            continue
        maximum = _named_amount(definition.get("max"), numbers, 99)
        # A feature that raises the printed maximum while it runs (rider lane C7: Thousand-Hand Incarnation's "Battle Hands become
        # 2 x Proficiency Bonus"): the pool is compiled at the highest maximum for an owner of it; the feature's plug-in keeps the
        # ordinary maximum the rest of the time. {"max_if_owned": {feature id: amount}}; absent: unchanged.
        for feature_id, raised in (definition.get("max_if_owned") or {}).items():
            if feature_id in ids:
                maximum = max(maximum, _named_amount(raised, numbers, maximum))
        initial = maximum if definition.get("start") == "max" else min(maximum, _named_amount(definition.get("start"), numbers, 0))
        resource_id = "resource:named." + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        rows.append({"name": name, "resource_id": resource_id,
                     "definition": ResourceDefinition(resource_id=resource_id, initial=initial, maximum=maximum)})
    return rows


def background_alias(key: str, mechanics: dict[str, Any]) -> str:
    """A Background talent's own id ("tianxia.background_talent.music.captivating_melody") is not in the typed authority;
    the same talent is, under its sphere ("tianxia.talent.music.captivating_melody"; owner 2026-09-28: 23 Background
    talents across the characters compiled as nothing)."""
    if key in mechanics or not key.startswith("tianxia.background_talent."):
        return key
    rest = key.split(".", 2)[2]
    for candidate in (f"tianxia.talent.{rest}", f"tianxia.talent.{rest.replace('harvesting_and_gathering.', 'harvesting_gathering.')}"):
        if candidate in mechanics:
            return candidate
    return key


def _selected_insight_ids(block: dict[str, Any]) -> list[str]:
    """Read acquired canonical IDs, never the builder's preference list.

    Occurrences preserve acquisition provenance; repeated occurrences of one
    Insight do not multiply the same combat grant. Printed repeatable stacking
    needs its own reviewed occurrence-aware implementation.
    """
    values = block.get("cultivation_insight_record_ids") or []
    values = list(values) if isinstance(values, list) else []
    occurrences = block.get("cultivation_insight_occurrences") or []
    if isinstance(occurrences, list):
        values.extend(row.get("record_id") for row in occurrences if isinstance(row, dict))
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value.startswith("insight.")))


def _admit_insight_ids(ids: list[str], mechanics: dict[str, Any], diagnostics: list[str],
                       boundaries: dict[str, dict[str, Any]]) -> list[str]:
    """Apply one exact-source gate before any Insight reaches grants or hooks.

    Feature blocks are loaded through their ordinary merged reader. A stale
    block rejects the entire Insight, including a separate active component,
    so a reviewed effect cannot accidentally accompany an obsolete passive.

    ``boundaries`` collects, per owned Insight id, exactly how far the table got:
    what the fight applies by itself, what the Game Master still rules, what the
    reviewer only recorded about the record, and one plain sentence saying so. The
    sheet library reads it so a player can tell an automated resistance from a partly
    implemented one from a rule the fight skips; nothing here grants a benefit.
    Reasons and sentences carry no internal id, file name or build word: the machine
    id stays in the ``id`` field. ``reason`` keeps the rejection that stopped an
    Insight, so the sentence a player reads still says why instead of only that.
    """
    insight_ids = {key for key in ids if isinstance(key, str) and key.startswith("insight.")}
    if not insight_ids:
        return ids
    from factory_authoring.insight_sources import INSIGHT_KIND, current_insight_sources
    from .typed_reactions import rules as feature_block_rules

    failure = None
    try:
        current = current_insight_sources(APP)
        features = feature_block_rules().get("features") or {}
    except (OSError, ValueError, TypeError):
        current, features = {}, {}
        failure = "the fight cannot read this Insight's printed rules right now"
    allowed: set[str] = set()
    for key in sorted(insight_ids):
        mechanic = mechanics.get(key) or {}
        selected = current.get(key) or {}
        source = mechanic.get("source") or {}
        actual = selected.get("source") or {}
        text_sha = actual.get("text_sha256")
        reason = failure
        if reason is None and not selected:
            reason = "this Insight is not in the current rules text"
        elif reason is None and (selected.get("insight_selectable") is not True or mechanic.get("insight_selectable") is not True):
            reason = "a character cannot choose this Insight"
        elif reason is None and selected.get("owner_edit_problems"):
            reason = "an edit to its printed rules is still waiting to be checked"
        elif reason is None and (mechanic.get("kind") != INSIGHT_KIND or mechanic.get("typing_status") != "reviewed_final"):
            reason = "nobody has checked its rules against the fight yet"
        elif reason is None and (not text_sha or source.get("text_sha256") != text_sha
                                 or mechanic.get("insight_reviewed_text_sha256") != text_sha
                                 or source.get("record_id") != actual.get("record_id")
                                 or source.get("record_sha256") != actual.get("record_sha256")):
            reason = "its rules have changed since they were last checked"
        elif reason is None and key in features and (not isinstance(features[key], dict)
                                                    or features[key].get("text_sha256") != text_sha):
            reason = "its checked rules no longer match the printed text"
        name = str(selected.get("name") or mechanic.get("name") or "")
        label = name or "This Insight"  # an unknown id has no printed name; the sheet supplies its own
        # ``notes`` is what the reviewer recorded about the record, not a rule for the
        # Game Master: it never joins the manual list, so the boundary cannot tell the
        # Game Master to rule on a benefit the sentence just said the table applies.
        annotations = [str(row).strip() for row in mechanic.get("notes") or [] if isinstance(row, str) and row.strip()]
        if reason:
            text = selected.get("text") or _rules_text().get(key) or "\n".join(
                row for row in mechanic.get("riders") or [] if isinstance(row, str))
            printed = str(text or "").strip()
            note = f"{label}: {reason}. Manual rules: {printed or 'Consult its source-backed Insight entry.'}"
            if note not in diagnostics:
                diagnostics.append(note)
            boundaries[key] = {
                "id": key, "name": name, "status": "manual", "reason": reason,
                "table_applies": [], "notes": annotations,
                "gm_decides": [printed] if printed else ["Read this Insight in its printed rules."],
                "explanation": "",
            }
            continue
        allowed.add(key)
        riders = [str(row).strip() for row in mechanic.get("riders") or [] if isinstance(row, str) and row.strip()]
        if riders:
            note = f"{label}: remaining manual rules: " + "\n".join(riders)
            if note not in diagnostics:
                diagnostics.append(note)
        boundaries[key] = {
            "id": key, "name": name, "status": "reviewed" if riders else "unreviewed", "reason": "",
            "table_applies": [], "notes": annotations, "gm_decides": riders, "explanation": "",
        }
    return [key for key in ids if key not in insight_ids or key in allowed]


# What a compiled passive-traits row does, said the way a player reads it. The four
# kinds are the whole ``passive_trait`` block (combat/ext/passive_traits.py), so this
# table cannot fall out of step with the adapter that writes the rows.
_INSIGHT_TRAIT_PHRASES = {
    "forced_movement_reduction": "anything that pushes or pulls you moves you {distance_ft} feet less",
    "standing_cost": "standing up from Prone costs {cost_ft} feet of your movement",
    "effective_size": "you count as {steps} size step larger for {purposes}",
    "grapple_escape_mode": "a creature escaping your Grapple rolls with {mode}",
}
# "0 feet of your movement" reads as a bug on a sheet; "costs you no movement" reads as the rule.
_INSIGHT_ZERO_STANDING = "standing up from Prone costs you no movement"
# The engine's roll modes are upper case enum values; a sheet sentence needs the rules word.
_INSIGHT_ROLL_MODES = {"ADVANTAGE": "Advantage", "DISADVANTAGE": "Disadvantage"}
# The purposes combat/ext/passive_traits.py may name for a size comparison.
_INSIGHT_SIZE_PURPOSES = {"grapple": "grappling", "shove": "shoving", "forced": "being pushed or pulled",
                          "prone": "being knocked Prone", "comparison": "comparing sizes",
                          "brutal_shove": "a brutal shove", "overrun": "overrunning"}
# Printed condition and damage names, for "Advantage on saving throws against ...".
_INSIGHT_SAVE_SUBJECTS = {
    "poisoned": "the Poisoned condition", "damage:poison": "Poison damage",
    "frightened": "being Frightened", "charmed": "being Charmed", "prone": "being knocked Prone",
    "grappled": "being Grappled", "forced_movement": "being pushed or pulled",
    "blinded": "being Blinded", "deafened": "being Deafened", "restrained": "being Restrained",
    "bleeding": "Bleeding", "burning": "Burning", "exhaustion": "Exhaustion",
}
# When the fight offers a compiled reaction. Any other trigger keeps the generic words.
_INSIGHT_REACTION_TRIGGERS = {
    "attacked": "when a creature attacks you",
    "forced_moved": "when something forces you to move",
    "damaged": "when you take damage",
    "damaged_by_target": "when you are damaged",
    "target_damaged": "when your target is damaged",
    "ally_damaged": "when an ally is damaged",
    "creature_damaged": "when a creature is damaged",
    "save_failed": "when a creature fails a saving throw",
    "attack_declared": "when a creature declares an attack",
    "death": "when a creature dies",
    "turn_start": "at the start of a turn",
    "turn_end": "at the end of a turn",
}


def _insight_save_subject(value: str) -> str:
    return _INSIGHT_SAVE_SUBJECTS.get(value, str(value).split(":", 1)[-1].replace("_", " ").strip() or "that effect")


# Row types the phrase tables above already describe precisely. Their own printed
# sentence would only repeat the phrase, so it is not appended.
_INSIGHT_LABELLED_EFFECTS = {"path_passive", "resistance", "advantage"}
# Keys a typed effect tree can hide another effect under, so a choice inside a menu
# still names what the fight applies. The same walk the tests read.
_INSIGHT_EFFECT_KEYS = ("effects", "on_fail", "on_success", "on_hit", "on_miss", "options")


def _insight_effect_outcomes(effects: Any) -> list[str]:
    """The owner's own printed outcome for every effect this does not phrase itself.

    Checklist 13: a boundary sentence that names only a button, a trigger or a
    changed ability leaves the player guessing what the fight actually does. The
    sentence a reviewer typed into ``evidence`` is the owner's printed words, so it
    is used verbatim rather than a second guess at the same effect, and it is never
    shortened: a rule must not lose its end. An effect with no evidence contributes
    nothing, which keeps the boundary honest instead of padding it.
    """
    found: list[str] = []
    for row in effects if isinstance(effects, list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "") not in _INSIGHT_LABELLED_EFFECTS:
            text = " ".join(str(row.get("evidence") or "").split()).strip(" .")
            if text and text not in found:
                found.append(text)
        for key in _INSIGHT_EFFECT_KEYS:
            found.extend(row for row in _insight_effect_outcomes(row.get(key)) if row not in found)
    return found


def _insight_outcome_clause(outcomes: list[str]) -> str:
    """``"...: <what it does>"`` for the boundary sentence, or empty when nothing applies."""
    return (": " + "; ".join(outcomes)) if outcomes else ""


def _insight_grant_label(row: dict[str, Any], insight_name: str) -> str:
    """One plain phrase naming what the fight now does by itself for an Insight.

    Used only for the sheet's automation boundary sentence. A compiled row's own
    ``name`` is often the Insight's own name, which tells a player nothing, so the
    typed fields are read instead. Anything this does not recognise falls back to
    the row's name, and a row with neither says so rather than guessing. A Reaction
    or an always-on benefit that this cannot phrase also carries the printed outcome
    the reviewer's effect supplies, so the sentence says what it does and not only
    when it fires.
    """
    from .resource_labels import resource_name

    # A sealed passive may provide its complete player-facing outcome. This
    # general label overrides the fallback for custom and compound benefits.
    if isinstance(row.get("player_outcome"), str) and row["player_outcome"].strip():
        return row["player_outcome"].strip()
    block = str(row.get("block") or "")
    kind = str(row.get("kind") or row.get("type") or "")
    if block == "passive_trait" and kind in _INSIGHT_TRAIT_PHRASES:
        if kind == "standing_cost" and not int(row.get("cost_ft") or 0):
            return _INSIGHT_ZERO_STANDING
        values = dict(row)
        values["purposes"] = " or ".join(_INSIGHT_SIZE_PURPOSES.get(str(value), str(value)) for value in row.get("purposes") or [])
        values["mode"] = _INSIGHT_ROLL_MODES.get(str(row.get("mode") or ""), str(row.get("mode") or ""))
        return _INSIGHT_TRAIT_PHRASES[kind].format(**values)
    if kind == "resistance" and row.get("damage_types"):
        types = ", ".join(str(value).capitalize() for value in row["damage_types"])
        return f"damage of type {types} is halved"
    if kind == "save_advantage":
        subjects = [_insight_save_subject(str(value)) for value in row.get("against") or []]
        return ("Advantage on saving throws against " + ", ".join(subjects)) if subjects else "Advantage on the saving throws it lists"
    if block == "generic":
        trigger = _INSIGHT_REACTION_TRIGGERS.get(kind, "when its printed condition is met")
        paid = [f"{part['amount']} {resource_name(str(part['resource_id']))}" for part in row.get("costs") or []
                if isinstance(part, dict) and part.get("resource_id") and part.get("amount")]
        outcomes = _insight_effect_outcomes(row.get("effects"))
        return (f"a Reaction {trigger}" + (f" costing {', '.join(paid)}" if paid else "")
                + _insight_outcome_clause(outcomes))
    name = str(row.get("name") or "").strip()
    if name and name != insight_name:
        return name + _insight_outcome_clause(_insight_effect_outcomes(row.get("effects")))
    return f"an always-on {kind.replace('_', ' ')} benefit" if kind else name


def _insight_modifier_label(row: dict[str, Any], insight_name: str, modifier: dict[str, Any] | None = None) -> str:
    """One plain phrase naming the change an Insight makes to another ability.

    ``modifier`` is the record's own typed modifier from the built authority, so the
    sentence can say what the change does instead of naming only the ability it lands
    on (checklist 13). A modifier whose effects carry no printed outcome is reported
    by what it changes, which is what the fight then does with it.
    """
    what = ", ".join(dict.fromkeys(str(value) for value in row.get("targets") or [] if value))
    label = str(row.get("name") or "")
    prefix = f"{insight_name}: "
    detail = label[len(prefix):].strip() if label.startswith(prefix) else ""
    outcomes = _insight_effect_outcomes((modifier or {}).get("effects"))
    return f"a change to {what or 'another ability'}" + (f" ({detail})" if detail else "") \
        + _insight_outcome_clause(outcomes)


def _insight_action_label(action: ActionDefinition) -> str:
    """One plain phrase naming a compiled Insight button, its economy, price and effect."""
    from .resource_labels import resource_name

    economy = {"ACTION": "an Action", "BONUS_ACTION": "a Bonus Action", "REACTION": "a Reaction",
               "FREE": "a Free action", "NONE": "an always-available action"}.get(str(action.economy), "an action")
    paid = [f"{amount} {resource_name(resource)}" for resource, amount in action.costs if amount]
    typed = (action.parameters or {}).get("typed") or {}
    outcomes = _insight_effect_outcomes(typed.get("effects")) + _insight_effect_outcomes(typed.get("modifiers"))
    return (f"{economy} button for {action.display_name}" + (f", costing {', '.join(paid)}" if paid else "")
            + _insight_outcome_clause(outcomes))


_BOUNDARY_FIELDS = ("id", "name", "status", "table_applies", "gm_decides", "notes", "explanation")


def _insight_boundaries(boundaries: dict[str, dict[str, Any]], applied: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Settle each owned Insight's boundary once every grant has been compiled.

    ``applied`` maps an Insight id to the plain names of the things the fight now
    does by itself for it (an always-on benefit, a reaction, a button, a change to
    another ability). An Insight with nothing left for the Game Master and at
    least one such grant is fully automated; one that still carries printed manual
    clauses is partial; one that produced nothing is reported as not applied rather
    than claimed as automatic.

    An Insight the exact-source gate rejected keeps the reason it was rejected in
    its own sentence, so a player whose working Insight suddenly stopped can see
    what changed instead of only reading that the Game Master must rule it.
    """
    rows: list[dict[str, Any]] = []
    for key in sorted(boundaries):
        row = boundaries[key]
        names = list(dict.fromkeys(str(value) for value in applied.get(key) or [] if value))
        label = row["name"] or "This Insight"
        row["table_applies"] = names
        remaining = [value for value in row["gm_decides"] if value]
        reason = str(row.get("reason") or "")
        if names and not remaining:
            row["status"] = "automated"
            row["explanation"] = (f"{label} works by itself in a fight: " + "; ".join(names)
                                  + ". Nothing about it is left for your Game Master.")
        elif names:
            row["status"] = "partial"
            row["explanation"] = (f"{label} is partly run by the fight table: " + "; ".join(names)
                                  + ". These printed lines are not run at the table, so your Game Master rules them: "
                                  + " ".join(remaining))
        elif reason:
            row["status"] = "manual"
            row["explanation"] = (f"{label} is not run by the fight table: {reason}. Your Game Master rules it "
                                  "from the printed text.")
        elif row["status"] == "reviewed":
            row["status"] = "partial"
            row["explanation"] = (f"{label} has been checked, but the fight table does not run any part of "
                                  "it. Your Game Master decides: " + " ".join(remaining))
        else:
            row["status"] = "manual"
            row["explanation"] = (f"{label} is not run by the fight table. Your Game Master decides: "
                                  + " ".join(remaining or ["Read this Insight in its printed rules."]))
        rows.append({field: row[field] for field in _BOUNDARY_FIELDS})
    return rows


def _foundation_feature_ids(owner_sheet: dict[str, Any]) -> list[str]:
    """The character's Foundation contributes its stage's printed features (cumulative),
    owner 2026-09-25 -- on top of the numeric passives already folded into the sheet's
    own statistics at creation (non_sphere_authority/foundation_mechanics.py)."""
    from non_sphere_authority.foundation_features import features_for_stage

    foundation = owner_sheet.get("foundation") or {}
    return [row["id"] for row in features_for_stage(foundation.get("foundation_id"), foundation.get("stage"))]


def _insight_record_ids(owner_sheet: dict[str, Any]) -> list[str]:
    """The Cultivation Insight records this character took, in the order they were gained.

    Used by :func:`compile_character` to decide which Insights contribute fight
    rows.  The printed rule (authority/typed_mechanics/rules_text.json,
    ``tianxia.path.*.feature.ability_score_improvement_or_cultivation_insight``)
    lets the character choose one Insight at each of CL4, CL8, CL12, CL16 and
    CL19 instead of a normal ability score increase, so the sheet records them in
    ``spheres_and_talents``:

    * ``cultivation_insight_record_ids`` -- the owner sheet's list of Insight
      records (written by character_sheet/service.py), and
    * ``cultivation_insight_occurrences[].insight_id`` -- the same records per
      level, when only the occurrence rows are present.

    Both are read so the list is the same whichever surface carries it.
    """
    block = owner_sheet.get("spheres_and_talents") or {}
    ids = [value for value in block.get("cultivation_insight_record_ids") or [] if isinstance(value, str)]
    for occurrence in block.get("cultivation_insight_occurrences") or []:
        if not isinstance(occurrence, dict):
            continue
        record_id = occurrence.get("insight_id") or occurrence.get("record_id")
        if isinstance(record_id, str) and record_id and record_id not in ids:
            ids.append(record_id)
    return ids


def _choose_pool(mechanic: dict[str, Any], action_id: str, primary: str, pools: Any,
                 powering: dict[str, str] | None) -> tuple[str, str | None]:
    """Which Path pool pays a generic CP cost, and the pool name to record as the player's choice
    when this ability is genuinely choosable (owner 2026-09-25, "Powering Path Records" / Q19):
    (1) a Path feature always uses its own Path; (4) otherwise, with more than one pool, the
    player's saved choice when it names an available pool, else the primary pool."""
    own_pool = PATH_POOLS.get(str(mechanic.get("path_id") or ""))
    if own_pool in pools:
        return own_pool, None
    if len(pools) > 1:
        chosen = powering.get(action_id) if powering and powering.get(action_id) in pools else primary
        return chosen, chosen
    return primary, None


# A printed use limit that a fight can enforce (owner ruling 2026-09-29: "once per fight yes and the once per week can
# be once per day instead. So once per fight unless a saved state is brought to the fight with it being exhausted
# which will only apply in roleplaying"). A fight is one scene and shorter than a day, so every printed scene, combat,
# day, week and rest limit is the same thing in combat: one use per fight.  The authority keeps the printed text
# (the parser stores only the rest/day limits as keys and everything else as "text:..."; a reviewed override may
# carry a key such as once_per_scene), so this reads both forms.  "Once per target/creature per scene" is one use per
# creature per fight: the counter is widened and the creatures are listed by combat/ext/target_limits.py.  Deliberately not matched, left to the GM as printed:
# once per realm/month/campaign arc/cultivation session/major processing scene, once per item per scene, once per
# spend/triggering hit, and Blood Mending's "per target, not per use".
_FIGHT_LIMIT = re.compile(r"\bonce per (?:(?:target|creature) per )?(?:scene|combat|fight|encounter|day|week|short rest|long rest)\b")


def _fight_limited(mechanic: dict[str, Any]) -> bool:
    limit = str(mechanic.get("use_limit") or "").lower().removeprefix("text:").replace("_", " ")
    return bool(_FIGHT_LIMIT.search(limit))


def _use_counter(resource_id: str) -> ResourceDefinition:
    """A one-per-fight counter: a resource that starts at 1.  Every actor's resources start from the template's
    ``initial`` values when the fight is made, so a use is fresh by default; a character carrying an already-exhausted
    use into a fight (roleplay only) would start this at 0."""
    return ResourceDefinition(resource_id=resource_id, initial=1, maximum=1)


def _uses_of(action_id: str) -> tuple[ResourceDefinition, tuple[str, int]]:
    """The one-per-fight counter for an ability and its 1-use cost."""
    uses = f"resource:uses.{action_id}"
    return _use_counter(uses), (uses, 1)


def _one_way(mechanic: dict[str, Any], alternative: list[dict[str, Any]], primary: str, pb: int, action_id: str, pools: Any,
             powering: dict[str, str] | None, foundation_resource: dict[str, Any] | None) -> tuple[list[tuple[str, int]], str | None, list[str]]:
    """One printed alternative of a cost as (what it costs, the pool the player may pick for its generic CP, the parts of it
    combat has no resource for)."""
    costs: list[tuple[str, int]] = []
    unpaid: list[str] = []
    choice: str | None = None
    for part in alternative:
        resource = part.get("resource")
        amount = part.get("amount") if part.get("amount") is not None else (pb if part.get("amount_formula") == "pb" else None)
        if resource == "cp":
            resource, picked = _choose_pool(mechanic, action_id, primary, pools, powering)
            choice = choice or picked
        # A Foundation feature's cost text collapses to one "text" part (e.g. "Spend 1
        # Mirror Trace" or "Spend 1 Mirror Trace + Reaction"); match the character's own
        # Foundation resource name in it instead (owner 2026-09-25).
        # Any other named resource (owner 2026-09-26: Edge Momentum, Devoured Essence...) is paid the same way,
        # whether the parser kept the cost as text or as its own resource key.
        named_cost = (_named_match(part.get("text") or f"{amount if amount is not None else ''} {str(resource).replace('_', ' ')}",
                                   foundation_resource)
                      if resource not in RESOURCE_IDS and resource != "cp" and foundation_resource else None)
        if named_cost and (named_cost[1] or amount):
            costs.append((named_cost[0]["resource_id"], int(named_cost[1] or amount)))
            # "1 CP and one Reagent Stock", "2 Stamina and 3 Marks": every part is paid (audit F6).
            # "2 Path resource" is CP: "CP means the character's current Path resource" (Core Rules Reference v0_2C, Terms),
            # sys-resources-states 2026-09-29 -- Star-Sovereign Core State, Dream Mirror Domain, Iron Oath Boundary.
            for amount_text, pool_name in re.findall(r"\b(\d+)\s+(CP|Path resources?|Qi|Stamina|Resonance)\b", part.get("text") or "", re.I):
                if pool_name.upper() == "CP" or pool_name.lower().startswith("path"):
                    pool, picked = _choose_pool(mechanic, action_id, primary, pools, powering)
                    choice = choice or picked
                else:
                    pool = pool_name.lower()
                costs.append((RESOURCE_IDS[pool], int(amount_text)))
        elif resource in RESOURCE_IDS and amount is not None:
            costs.append((RESOURCE_IDS[resource], int(amount)))
        else:
            unpaid.append(str(part.get("text") or resource))
    return costs, choice, unpaid


def _held_resources(pools: Any, foundation_resource: Any) -> set[str] | None:
    """The resources this character can pay with: its Path pools, Martial Focus (every character has it) and its named pools;
    None when the pools are not known (a caller that passes none), which leaves every resource payable as it always was."""
    if not pools:
        return None
    return ({RESOURCE_IDS[name] for name in pools if name in RESOURCE_IDS} | {RESOURCE_IDS["martial_focus"]}
            | {row["resource_id"] for row in _named_list(foundation_resource)})


def _way_words(costs: list[tuple[str, int]], foundation_resource: Any) -> str:
    """What a way to pay costs, in words: "15 Qi", "Martial Focus", "1 Devoured Essence"."""
    named = {row["resource_id"]: row["name"] for row in _named_list(foundation_resource)}
    focus = RESOURCE_IDS["martial_focus"]
    return " + ".join(("Martial Focus" if amount == 1 else f"{amount} Martial Focus") if resource == focus
                      else f"{amount} {_POOL_NAMES.get(resource) or named.get(resource) or resource.rsplit('.', 1)[-1]}"
                      for resource, amount in costs)


def _cost_ways(mechanic: dict[str, Any], primary: str, pb: int, action_id: str, diagnostics: list[str], pools: Any = (),
               powering: dict[str, str] | None = None, *,
               foundation_resource: dict[str, Any] | None = None) -> tuple[list[tuple[int, list[tuple[str, int]], str]], str | None]:
    """Every way this character can pay the ability's printed cost, as (the printed alternative's number, its costs, them in
    words) in the order printed, and the pool the player may pick for its generic CP.

    The user pays ONE printed alternative -- "Cost: 15 Stamina or 15 CP" is two ways, not the price of both -- and ``cost``
    is the authority's own shape for that: a list of alternatives, each a list of parts, "cp" being whichever Path pool pays
    this ability (``_choose_pool``).  Only the first was ever read, so an ability whose first way was a pool the character
    lacks (Great Sage Equal to Heaven's Stamina, for a Qi character) could not be used at all (hunt 3, 2026-09-28: forced,
    only END_TURN offered).  A way that needs a pool the character does not have, or a resource combat does not model, is not
    theirs to choose; two ways that land on the same cost for this character (a Body Path's "15 Stamina" and "15 CP") are one.
    A cost with one alternative, or none this character can pay, is read as before: its first."""
    alternatives = mechanic.get("cost") or []
    readings = [(number, *_one_way(mechanic, alternative, primary, pb, action_id, pools, powering, foundation_resource))
                for number, alternative in enumerate(alternatives)] or [(0, [], None, [])]
    held = _held_resources(pools, foundation_resource)
    payable = [reading for reading in readings if not reading[3] and (held is None or all(resource in held for resource, _ in reading[1]))] \
        if len(readings) > 1 else []
    if not payable:
        number, costs, choice, unpaid = readings[0]
        diagnostics.extend(f"{mechanic['name']}: cost not automated ({text})" for text in unpaid)
        return [(number, costs, "")], choice
    ways: list[tuple[int, list[tuple[str, int]], str]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    for number, costs, _choice, _unpaid in payable:
        if tuple(sorted(costs)) not in seen:
            seen.add(tuple(sorted(costs)))
            ways.append((number, costs, _way_words(costs, foundation_resource)))
    # The pool the player picks for CP is offered even when two ways collapsed into one for the pool it now names: switching
    # it is what makes the other way a distinct one.
    return ways, next((reading[2] for reading in payable if reading[2]), None)


def _costs_and_ways(mechanic: dict[str, Any], primary: str, pb: int, action_id: str, diagnostics: list[str], pools: Any = (),
                    powering: dict[str, str] | None = None, *, foundation_resource: dict[str, Any] | None = None
                    ) -> tuple[list[tuple[str, int]], list[ResourceDefinition], str | None, list[tuple[int, list[tuple[str, int]], str]]]:
    """(the costs of the first way to pay, the resources its once-per-fight limit adds, the pool the player may pick for its CP,
    each other way to pay as (the printed alternative's number, its costs, in words)).  A limit is one use however it is paid,
    so every way spends the same ``resource:uses.<ability>``."""
    ways, choice = _cost_ways(mechanic, primary, pb, action_id, diagnostics, pools, powering, foundation_resource=foundation_resource)
    extra: list[ResourceDefinition] = []
    limit: list[tuple[str, int]] = []
    if _fight_limited(mechanic):  # owner ruling 2026-09-29: scene/day/week/rest limits are one use per fight
        counter, cost = _uses_of(action_id)
        extra.append(counter)
        limit = [cost]
    return [*ways[0][1], *limit], extra, choice, [(number, [*costs, *limit], words) for number, costs, words in ways[1:]]


def _costs(mechanic: dict[str, Any], primary: str, pb: int, action_id: str, diagnostics: list[str],
           pools: Any = (), powering: dict[str, str] | None = None, *,
           foundation_resource: dict[str, Any] | None = None) -> tuple[list[tuple[str, int]], list[ResourceDefinition], str | None]:
    """What using the ability costs, paid the first way this character can (see ``_cost_ways``); a caller that can offer the
    other ways too (the actions, ``_add_ways``) asks ``_costs_and_ways``."""
    costs, extra, choice, _others = _costs_and_ways(mechanic, primary, pb, action_id, diagnostics, pools, powering, foundation_resource=foundation_resource)
    return costs, extra, choice


def _add_ways(built: dict[str, dict[str, Any]], key: str, ways: list[tuple[int, list[tuple[str, int]], str]]) -> list[str]:
    """A row of the ability for each other way to pay it ("Great Sage Equal to Heaven (15 Qi)"), added to ``built`` beside its
    row; the built keys made.  Each is the same ability -- same effects, target and limits, ``way_of`` naming the row it copies
    -- so the talents that change it (apply_modifiers) change every way alike, and the way is the printed alternative's number
    in its id.  The first way keeps the ability's own name and id."""
    row, made = built[key], []
    for number, costs, words in ways:
        way_key = f"{key}#pay{number}"
        built[way_key] = {**row, "action_id": f"{row['action_id']}#pay{number}", "name": f"{row['name']} ({words})", "costs": list(costs),
                          "typed": copy.deepcopy(row["typed"]), "modifiers": [], "way_of": key}
        made.append(way_key)
    return made


def _resolve_resource_effects(effects: list[dict[str, Any]], *, mechanic: dict[str, Any], primary: str, pools: Any,
                              foundation_resource: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Which resource a gain_resource/spend_resource effect names, matched from its printed evidence
    text against the character's own resources (owner 2026-09-26): a Path pool the character actually
    has (by name, or the generic "CP" shorthand resolved the same way ``_choose_pool`` resolves a
    printed cost -- the ability's own Path pool if it has one, else the primary pool), Martial Focus,
    or the Foundation's own named resource -- the same idea as ``_costs``'s Foundation-resource-name
    match, so combat/typed_executor.py's blocks have a real id to spend/gain. Mutates and returns
    ``effects`` in place; unmatched effects (a homebrew counter this compiler does not know) are left
    for the executor's rider fallback rather than guessed."""
    for effect in effects:
        if isinstance(effect, dict):  # a save's or an attack's branches too (owner 2026-09-26: Demon Mark's on_fail)
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                if isinstance(effect.get(branch), list):
                    _resolve_resource_effects(effect[branch], mechanic=mechanic, primary=primary, pools=pools,
                                              foundation_resource=foundation_resource)
        if not isinstance(effect, dict) or effect.get("type") not in ("gain_resource", "spend_resource"):
            continue
        text = str(effect.get("evidence") or "")
        named_hit = _named_match(text, foundation_resource)
        if named_hit:
            effect["resource_id"] = named_hit[0]["resource_id"]
            continue
        if re.search(r"\bmartial focus\b", text, re.I):
            effect["resource_id"] = RESOURCE_IDS["martial_focus"]
            continue
        for name in pools:
            if re.search(rf"\b{re.escape(name)}\b", text, re.I):
                effect["resource_id"] = RESOURCE_IDS[name]
                break
        else:
            if re.search(r"\bcp\b", text, re.I):
                own_pool = PATH_POOLS.get(str(mechanic.get("path_id") or ""))
                effect["resource_id"] = RESOURCE_IDS[own_pool if own_pool in pools else primary]
    return effects


def _resolve_required_resource(name: str, *, primary: str, pools: Any, foundation_resource: dict[str, Any] | None) -> str | None:
    """The real resource id a "while you have X"/"already have X" trigger name (owner 2026-09-26)
    resolves to for this character -- the same places ``_resolve_resource_effects`` matches a
    gain/spend effect's evidence text against: the character's own Foundation resource, a Path pool
    it actually has, or Martial Focus. None when the character does not hold anything by that name (a
    stance/mode word like "Body Lightening", or another Foundation's resource)."""
    for row in _named_list(foundation_resource):
        if name.lower().rstrip("s") == row["name"].lower().rstrip("s"):
            return row["resource_id"]
    if name.lower() == "martial focus":
        return RESOURCE_IDS["martial_focus"]
    for pool_name in pools:
        if name.lower() == pool_name.lower():
            return RESOURCE_IDS[pool_name]
    return None


def _reaction_range_ft(mechanic_id: str, mechanic: dict[str, Any], trigger_range: int | None, cl: int) -> int | None:
    """A trigger's explicit distance wins; otherwise use the ability's Range.

    Generic reactions must not turn a printed numeric Range into unlimited
    reach just because the trigger says 'within range' or omits the number.
    Reviewed level bands override the header; printed realm range increases
    supply the same contract when the authority has only the base distance.
    Non-distance headers (Self, special, etc.) retain the trigger contract.
    """
    if trigger_range is not None:
        return trigger_range
    reach = mechanic.get("range") or {}
    scaled = next((int(feet) for low, high, feet in reach.get("feet_by_cl") or [] if low <= cl <= high), None)
    if scaled is not None:
        return scaled
    text = _rules_text().get(mechanic_id) or ""
    header = re.search(r"^Range:\s*(\d+)\s*feet\b", text, re.I | re.M)
    feet = int(header[1]) if header else reach.get("feet") if reach.get("kind") in {"feet", "touch", "reach"} else None
    realms = {"foundation": 5, "core formation": 10, "nascent soul": 15}
    for realm, value in re.findall(r"At (Foundation|Core Formation|Nascent Soul)(?: Realm)?,\s*(?:the |its )?range increases to (\d+) feet", text, re.I):
        if cl >= realms[realm.lower()]:
            feet = int(value)
    return feet


def _reaction_range_reference(kind: str, requires_mark: str | None, mark_on: str | None) -> str:
    """Creature measured by a printed Range when the trigger omits a distance.

    Attack/damage responses aimed at the triggering attacker measure the
    source. Ally responses protect the event's subject, except when the
    trigger names a marked source (not a marked subject). Movement,
    condition and creature-action events measure their triggering subject.
    Explicit trigger distances keep their existing hook contract.
    Shared with the runtime fallback for sealed legacy null-range rows.
    """
    if kind in {"attacked", "hit", "missed", "damaged", "critical_hit", "natural_1"}:
        return "source"
    if kind in {"ally_attacked", "ally_hit", "ally_missed", "ally_damaged"} and requires_mark and mark_on != "subject":
        return "source"
    return "subject"


def _generic_reaction(mechanic_id: str, mechanic: dict[str, Any], *, pb: int, numbers: dict[str, int], primary: str,
                      pools: Any, diagnostics: list[str],
                      powering: dict[str, str] | None = None,
                      foundation_resource: dict[str, Any] | None = None,
                      free: bool = False, option_pick: Any = None) -> tuple[list[dict[str, Any]], list[ResourceDefinition], tuple[str, str, str] | None] | None:
    """A reaction row the sealed engine's generic hooks can run (combat/typed_reactions.py), or None
    when its trigger is not one of the supported kinds (owner 2026-09-25: reactions must fire), or
    (owner 2026-09-26) names a "while you have X" resource this character does not actually hold --
    reported via ``diagnostics`` rather than compiled unrestricted.
    ``free`` (owner 2026-09-26) marks a Foundation resource-generation trigger (e.g. Generate Mirror
    Trace): a no_action printed effect, not a Reaction, so it never costs or requires one.
    ``option_pick`` (owner 2026-09-26, step 14): which option of a split "Choose one" menu the character's
    reaction plan picked; without one, _default_reaction_option's pick for the trigger.
    One row per trigger the reaction answers (owner 2026-09-26, "i want all the reactions usable": a reading in
    authority/typed_mechanics/trigger_readings.jsonl can name several, e.g. "knocked Prone or moved against your will");
    they share the feature id, so the reaction plan, costs and once-limits treat them as the one reaction."""
    from .reaction_triggers import classify_mechanic_all, classify_trigger

    printed = trigger = (mechanic.get("activation") or {}).get("trigger")
    if free and not trigger:
        # A generator printed as one sentence with no Trigger line ("when you hit ..., gain 1 Pack Echo"): the
        # sentence is the trigger (owner 2026-09-26, "we need the different resources to be generated").
        trigger = next((str(effect.get("evidence") or "") for effect in _walk(mechanic.get("effects") or [])
                        if effect.get("type") == "gain_resource" and effect.get("evidence")), None)
    # The same reading the reaction report counts (reaction_triggers.distribution): the normalized-trigger rewrites
    # and "you or an ally" included. The compiler read the phrase classifier alone, so 10 reactions the rewrites
    # make runnable were never compiled and 8 "you or an ally" ones covered only you (Astra's audit, 2026-09-26).
    matches = [match for match in (classify_mechanic_all(mechanic) if trigger == printed else [classify_trigger(trigger)]) if match.runnable]
    if not matches:
        return None
    match = matches[0]
    printed_match = classify_trigger(trigger)
    # Auto keeps its preset/default. Retain every resolved mode for manual
    # consent: eligibility must inspect the chosen effect tree, not the preset.
    options = [option for option in mechanic.get("options") or [] if isinstance(option, dict)]
    option_index = None
    if len(options) >= 2:
        picked = option_pick if isinstance(option_pick, int) and not isinstance(option_pick, bool) and 0 <= option_pick < len(options) else None
        option_index = picked if picked is not None else _default_reaction_option(options, match.kind)
        base_effects = list(options[option_index].get("effects") or [])
    else:
        base_effects = [*(mechanic.get("effects") or []), *(effect for option in options for effect in option.get("effects") or [])]
    if not base_effects:
        return None
    requires_resource = None
    needed = match.requires_resource or printed_match.requires_resource
    if needed:
        requires_resource = _resolve_required_resource(needed, primary=primary, pools=pools, foundation_resource=foundation_resource)
        if requires_resource is None:
            diagnostics.append(f"{mechanic['name']}: reaction requires \"{needed}\", not a resource this character holds")
            return None
    action_id = f"reaction:typed.{mechanic_id}"
    costs, extra, choice = _costs(mechanic, primary, pb, action_id, diagnostics, pools, powering, foundation_resource=foundation_resource)
    choice_entry = (action_id, mechanic["name"], choice) if choice else None
    def resolve_effects(raw):
        resolved = _resolve_resource_effects(name_damage_effects(raw, mechanic["name"]), mechanic=mechanic,
            primary=primary, pools=pools, foundation_resource=foundation_resource)
        # Reviewed distance scaling applies equally to preset and manual modes.
        for effect in _walk(resolved):
            for low, high, feet in effect.get("distance_ft_by_cl") or []:
                if low <= int(numbers.get("cl") or 1) <= high:
                    effect["distance_ft"] = feet
                    break
        return resolved

    effects = resolve_effects(base_effects)
    activation = mechanic.get("activation") or {}
    printed_text = str(activation.get("trigger") or "")
    # A reviewed row may type a qualifier its printed trigger does not spell out
    # (or spells in words the classifier can miss): activation.requires_sight /
    # requires_shield are general, default-inert flags. Their consumers are the
    # shared reaction_subject_allowed perception gate and shield_wielding.
    rows = [{
        "feature_id": mechanic_id, "block": "generic", "name": mechanic["name"], "kind": match.kind,
        **({"range_scale": mechanic["range_scale"]} if mechanic.get("range_scale") else {}),
        **({"subject_relation": mechanic["subject_relation"]} if mechanic.get("subject_relation") else {}),
        **({"allow_self_source": True} if mechanic.get("allow_self_source") is True else {}),
        "melee_only": match.melee_only, "ranged_only": match.ranged_only,
        "range_ft": _reaction_range_ft(mechanic_id, mechanic, match.range_ft, int(numbers.get("cl") or 1)),
        **({"requires_sight": True} if match.requires_sight or activation.get("requires_sight") is True else {}),
        **({"requires_shield": True} if activation.get("requires_shield") is True else {}),
        # "Moves at least 30 feet" (step 8, owner 2026-09-26): typed_reactions.on_creature_event checks the move's length.
        "min_move_ft": match.min_move_ft or int(next(iter(re.findall(r"\bmoves? at least (\d+) f(?:ee)?t", printed_text, re.I)), 0)),
        **({"movement_measure": "turn"} if match.kind == "moved" and re.search(r"\bduring (?:a|the|this) turn\b", printed_text, re.I) else {}),
        # "You or an ally ..." also covers the reactor itself (owner 2026-09-26 review).
        "includes_self": match.includes_self if match.includes_self is not None
        else bool(re.search(r"\byou or (?:an? |another |one )?(?:ally|allies|creature)", printed_text, re.I)),
        # A reading's limits (combat/reaction_triggers.py TriggerMatch, owner 2026-09-26).
        "any_subject": match.any_subject, "allies_only": match.allies_only, "self_only": match.self_only, "mark_on": match.mark_on,
        "opportunity_only": match.opportunity_only, "teleport_only": match.teleport_only, "source_within_reach": match.source_within_reach,
        "requires_hearing_technique": match.requires_hearing_technique, "rolls": sorted(match.rolls), "outcome": match.outcome,
        "toward": match.toward, "reading": match.reading, "economies": sorted(match.economies), "natural": sorted(match.natural),
        "action": match.action, "source_name": match.source_name, "min_cost": match.min_cost, "grappling": match.grappling,
        "costs": [{"resource_id": resource, "amount": amount} for resource, amount in costs],
        # Owner 2026-09-26: limits combat can now check (combat/reaction_triggers.py); empty/None means
        # the trigger named none on that axis, so the row is unrestricted there (unchanged behavior).
        # Runtime damage filters compare against uppercase engine damage identifiers.
        "save_abilities": sorted(match.save_abilities), "damage_types": sorted(kind.upper() for kind in match.damage_types),
        "conditions": sorted(match.conditions), "requires_resource": requires_resource,
        # A "bearing your <Mark>"/"a marked creature" subject (owner 2026-09-26): the printed name, or
        # "*" for any mark -- combat/typed_reactions.py resolves it against the reactor's own placed
        # marks at runtime, no per-character resolution needed here.
        # Reviewed trigger readings own their eligibility. A mark mentioned
        # in another printed alternative must not constrain every recipient.
        "requires_mark": match.requires_mark,
        **({"requires_zone_los": zone_name} if (zone_name := match.requires_zone_los or printed_match.requires_zone_los) else {}),
        # Trigger timing does not override action economy: named follow-ups can
        # themselves cost a Reaction. Only explicitly free activations ride it.
        "effects": effects, "numbers": numbers, "use_limit": mechanic.get("use_limit"), "free": free,
        # A printed once-per limit (owner 2026-09-26): a free generator has no Reaction to cap it; responses that share
        # one ("spend a Waning Mark once per round") share its group.
        "once": mechanic.get("once") or _once_limit(f"{trigger or ''} {mechanic.get('use_limit') or ''}"),
        "once_group": mechanic.get("once_group"), "requires_self_mark": mechanic.get("requires_self_mark"),
        # "After the triggering act resolves" (Yang's Overheat Force): run once the attack is over (audit F10).
        "after": mechanic.get("after"),
        # Optional recipient selection for a granted condition-reaction attack.
        # Absent metadata preserves source-bound reactions in saved bundles.
        **({"reaction_target": mechanic["reaction_target"]} if mechanic.get("reaction_target") else {}),
        # Optional printed CP-spend threshold; inert for rows without it.
        **({"min_cp_cost": int(mechanic["min_cp_cost"])} if mechanic.get("min_cp_cost") else {}),
        # A printed "Prerequisite: CL N+" gate, enforced at admission by activation_requirements.
        **({"min_cl": int(mechanic["min_cl"])} if mechanic.get("min_cl") else {}),
        # Deafened (2024, owner 2026-09-26): its targets must hear the reactor, or the reactor must hear the trigger.
        "requires_hearing": bool(mechanic.get("requires_hearing")),
        "reactor_hears": bool(re.search(r"\byou can (?:see or |perceive or )?hear\b", str(printed or ""), re.I)),
        # The menu and the option this row runs (step 14); the reaction plan lists them so the player can change it.
        **({"option_labels": [str(option.get("label") or f"Option {index + 1}") for index, option in enumerate(options)],
            "option": option_index} if option_index is not None else {}),
    } for match in matches]
    for row, match in zip(rows, matches):
        if match.range_ft is None and row["range_ft"] is not None:
            row["range_reference"] = _reaction_range_reference(match.kind, match.requires_mark, match.mark_on)
    for row in rows[1:]:  # each row its own copy: modifiers and runtime state attach per row
        row["effects"] = copy.deepcopy(row["effects"])
    if option_index is not None:
        modes = []
        for index, option in enumerate(options):
            mode_effects = resolve_effects(option.get("effects") or [])
            modes.append({"index": index, "label": rows[0]["option_labels"][index],
                          "effects": mode_effects})
        for row in rows:
            row["reaction_modes"] = copy.deepcopy(modes)
    return rows, extra, choice_entry


# What an option is worth to the AI's default pick, by effect type; the trigger's own answer counts extra
# (an AC bonus against an attack roll, a reduction against damage).
_OPTION_VALUE = {"damage": 5, "extra_damage": 5, "condition": 4, "temp_hp": 4, "healing": 4, "ac_bonus": 3, "attack_modifier": 3,
                 "advantage": 3, "disadvantage": 3, "resistance": 3, "immunity": 3, "damage_modifier": 3, "half_damage": 3,
                 "forced_movement": 2, "gain_resource": 2, "mark": 1, "movement": 1, "speed": 1}
_OPTION_ANSWERS = {"attacked": {"ac_bonus", "attack_modifier", "disadvantage"},
                   "hit": {"ac_bonus", "attack_modifier", "damage_modifier", "resistance", "immunity", "half_damage", "temp_hp"},
                   "damaged": {"damage_modifier", "resistance", "immunity", "half_damage", "temp_hp"},
                   # A push or pull about to land is answered by cutting it short (Anchor the Link's "reduce forced movement by 10 feet";
                   # rider lane C13): typed_reactions.on_forced_movement reduces the distance by a forced_movement row.
                   "forced_moved": {"forced_movement"}}

_HELPS_OTHERS = re.compile(r"\b(?:servant|summon|companion|construct|minion)s?\b", re.I)


def _default_reaction_option(options: list[dict[str, Any]], kind: str) -> int:
    """The option a reaction runs until the player picks one (step 14): the most valuable by effect type,
    the first printed on a tie."""
    answers = _OPTION_ANSWERS.get(kind.removeprefix("ally_"), set())

    def worth(effect: dict[str, Any]) -> int:
        # Help for a servant or an ally may have nobody to land on (Harvest the Fallen's "one Death servant
        # you control regains HP" for a character without one).
        if effect.get("applies_to") == "ally" or _HELPS_OTHERS.search(str(effect.get("evidence") or "")):
            return 1
        return _OPTION_VALUE.get(effect.get("type"), 0) + (4 if effect.get("type") in answers else 0)

    def value(option: dict[str, Any]) -> int:
        return sum(worth(effect) for effect in _walk(option.get("effects") or []))

    return max(range(len(options)), key=lambda index: (value(options[index]), -index))


def _once_limit(text: str) -> str | None:
    if re.search(r"\bonce (?:per|each) round\b|\bonce_per_round\b|\bthe first time each round\b", text, re.I):
        return "round"
    if re.search(r"\bonce (?:per|each|on each of your) turns?\b|\bonce_per_turn\b|\bthe first time each turn\b", text, re.I):
        return "turn"
    return None


# ------------------------------------------------------------------ Immortal Arts (owner 2026-09-26)
_ABILITY_WORDS = {"strength": "STR", "dexterity": "DEX", "constitution": "CON", "intelligence": "INT", "wisdom": "WIS", "charisma": "CHA"}
_DC_BASIS_RE = re.compile(r"\+\s*(\w+)\s+modifier", re.I)
_SPEED_FEET_TIMES_PB_RE = re.compile(r"(\d+)\s*feet\s*[×x*]\s*pb", re.I)
_PB_DICE_RE = re.compile(r"^\s*pb\s*d\s*(\d+)\s*$", re.I)


def _art_save_dc(dc_basis: Any, mods: dict[str, int], pb: int) -> int | None:
    """The art's own save DC when ``dc_basis`` (e.g. "8 + Proficiency Bonus + Wisdom modifier") names an
    ability, so an Immortal Art built on a different key ability than the character's usual technique save
    DC still uses its own printed formula (owner 2026-09-26)."""
    match = _DC_BASIS_RE.search(str(dc_basis or ""))
    ability = _ABILITY_WORDS.get(match.group(1).lower()) if match else None
    return 8 + pb + mods.get(ability, 0) if ability else None


def _art_factor_effects(art: dict[str, Any], pb: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Typed effect(s) for the art's own Factor layer(s) and the rider lines for what they printed but
    this compiler cannot run (owner 2026-09-26).  Only a Factor whose printed refinement is a plain
    number is mapped -- a flat Speed penalty (Fettered Movement) or a PBd<sides> temporary HP package
    (Fortification); everything else in the refinement, and any Factor this compiler does not recognize
    at all, becomes a rider so it is never silently dropped."""
    added: list[dict[str, Any]] = []
    riders: list[str] = []
    surface = art.get("action_surface") or {}
    application = surface.get("factor_application") or {}
    refinement = (application.get("effective_effect") or {}).get("factor_refinement")
    refinement = refinement if isinstance(refinement, dict) else {}
    primary_factor_id = str(application.get("factor_id") or "")
    for factor in art.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        factor_id = str(factor.get("factor_id") or "")
        display = str(factor.get("display_name") or factor_id or "Factor")
        if factor_id != primary_factor_id or not refinement:
            if factor.get("mechanical_chassis"):
                riders.append(f"{display} (not automated): {' '.join(str(factor['mechanical_chassis']).split())}"[:300])
            continue
        if factor_id == "speed_reduction":
            match = _SPEED_FEET_TIMES_PB_RE.search(str(refinement.get("failed_save") or ""))
            if match:
                added.append({"type": "speed", "amount": -int(match.group(1)) * pb, "applies_to": "target",
                              "evidence": f"{display}: {refinement.get('failed_save')}"})
            extra = "; ".join(f"{key}: {value}" for key, value in refinement.items() if key != "failed_save" and value)
            if extra:
                riders.append(f"{display} (not automated): {extra}"[:300])
        elif factor_id == "temporary_hp_fortification":
            dice_match = _PB_DICE_RE.match(str(refinement.get("temporary_hp") or ""))
            if dice_match:
                added.append({"type": "temp_hp", "dice": {"count_formula": "pb", "sides": int(dice_match.group(1))}, "applies_to": "self",
                              "evidence": f"{display}: {refinement.get('temporary_hp')} temporary HP"})
            extra = "; ".join(f"{key}: {value}" for key, value in refinement.items() if key != "temporary_hp" and value)
            if extra:
                riders.append(f"{display} (not automated): {extra}"[:300])
        else:
            riders.append(f"{display} (not automated): {factor.get('mechanical_chassis') or ''}"[:300])
    return added, riders


def _compile_immortal_arts(owner_sheet: dict[str, Any], mechanics: dict[str, Any], *, actor_id: str, short: str, pb: int,
                           mods: dict[str, int], numbers: dict[str, int], primary: str, pools: Any,
                           potency: dict[str, Any] | None, skipped: dict[str, list[str]], powering: dict[str, str] | None,
                           choosable: list[tuple[str, str, str]]) -> tuple[list[ActionDefinition], dict[str, dict[str, Any]], list[ResourceDefinition]]:
    """Immortal Arts, modelled on the Forged Technique loop above: each delivers its source talent's
    typed core (``source_record_id``, always a mechanic already in the authority) at the art's own
    action economy and its own printed activation cost (``activation_cp``, paid from the art's own Path
    pool); its Factor layer rides the source effects where ``_art_factor_effects`` can map it.  A
    reaction art only compiles when its source talent's trigger is one the engine already runs
    (``reaction_triggers.classify_trigger``); anything else -- an unsupported reaction, a passive, or an
    art with no typed source at all -- is a reported gap, never a silent drop (owner 2026-09-26)."""
    from .reaction_triggers import classify_trigger

    raw = owner_sheet.get("immortal_arts")
    arts = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    actions: list[ActionDefinition] = []
    reactions: dict[str, dict[str, Any]] = {}
    extra_resources: list[ResourceDefinition] = []
    for art in arts:
        if not isinstance(art, dict):
            continue
        name = str(art.get("display_name") or art.get("name") or "Immortal Art")
        surface = art.get("action_surface") or {}
        economy = str(surface.get("action_type") or "").strip().lower().replace(" ", "_")
        mechanic = mechanics.get(str(art.get("source_record_id") or ""))
        if mechanic is None or not mechanic.get("effects"):
            skipped["not_typed"].append(name)
            continue
        art_id = str(art.get("art_id") or art.get("record_id") or name)
        action_id = f"action:typed.{short}.immortal.{hashlib.sha256(art_id.encode('utf-8')).hexdigest()[:12]}"
        cp = int(art.get("activation_cp") or 0)
        pool, choice = _choose_pool(art, action_id, primary, pools, powering) if cp > 0 else (primary, None)
        costs: list[tuple[str, int]] = [(RESOURCE_IDS[pool], cp)] if cp > 0 else []
        if choice:
            choosable.append((action_id, name, choice))
        if _fight_limited(mechanic):
            uses, cost = _uses_of(action_id)
            extra_resources.append(uses)
            costs.append(cost)
        dc = _art_save_dc(surface.get("dc_basis"), mods, pb)
        action_numbers = {**numbers, "save_dc": dc} if dc is not None and dc != numbers.get("save_dc") else numbers
        resource_id = RESOURCE_IDS[pool] if cp > 0 else None
        if potency and resource_id == potency.get("resource_id"):
            action_numbers = {**action_numbers, "potency": potency["bonus_value"]}
        effects = name_damage_effects(mechanic.get("effects") or [], mechanic["name"])
        riders = list(mechanic.get("riders") or [])
        added, factor_riders = _art_factor_effects(art, pb)
        speed_adds = [row for row in added if row["type"] == "speed"]
        other_adds = [row for row in added if row["type"] != "speed"]
        if speed_adds:
            attached = _attach(effects, speed_adds, "failed_save")
            if attached:
                effects = attached
            else:
                factor_riders = [*factor_riders, *(f"Not automated (no matching save branch): {row['evidence']}" for row in speed_adds)]
        effects = [*effects, *other_adds]
        riders = [*riders, *factor_riders]
        effects = _resolve_resource_effects(effects, mechanic=mechanic, primary=primary, pools=pools, foundation_resource=None)
        if economy in {"action", "bonus_action"}:
            target_kind, range_ft = _target_kind(mechanic, numbers.get("cl"))
            typed = {"effects": effects, "riders": riders, "numbers": action_numbers, "weapon": None,
                     "duration": mechanic.get("duration") or {"kind": "instant"},
                     "area": _aimed_area(mechanic, numbers.get("cl")),
                     "range_ft": range_ft, "source": art_id, "typing_status": mechanic.get("typing_status"),
                     "coverage": mechanic.get("coverage"), "immortal_from": mechanic.get("mechanic_id") or "",
                     # A printed "Prerequisite: CL N+" gate, enforced at admission by activation_requirements.
                     **({"min_cl": int(mechanic["min_cl"])} if mechanic.get("min_cl") else {})}
            actions.append(ActionDefinition(
                source_definition_id=action_id, display_name=name, owner_id=actor_id,
                economy=EconomyKind.ACTION if economy == "action" else EconomyKind.BONUS_ACTION,
                resolution_kind="TYPED", target_kind=target_kind, range_ft=range_ft,
                radius_ft=(mechanic.get("area") or {}).get("size_ft"), costs=tuple(costs),
                concentration=bool((mechanic.get("duration") or {}).get("concentration")),
                parameters={"typed": typed, "expected_damage": _expected_damage(effects, action_numbers)},
            ))
        elif economy == "reaction":
            match = classify_trigger((mechanic.get("activation") or {}).get("trigger"))
            if not match.runnable:
                skipped["reaction"].append(name)
                continue
            reactions[art_id] = {
                "feature_id": art_id, "block": "generic", "name": name, "kind": match.kind,
                "immortal_from": mechanic.get("mechanic_id") or "",
                "melee_only": match.melee_only, "ranged_only": match.ranged_only, "range_ft": match.range_ft,
                "includes_self": bool(re.search(r"\byou or (?:an? |another |one )?(?:ally|allies|creature)",
                                                str((mechanic.get("activation") or {}).get("trigger") or ""), re.I)),
                "costs": [{"resource_id": resource, "amount": amount} for resource, amount in costs],
                "effects": effects, "numbers": action_numbers, "use_limit": mechanic.get("use_limit"), "free": False,
                **({"min_cl": int(mechanic["min_cl"])} if mechanic.get("min_cl") else {}),
            }
        else:
            skipped["passive"].append(name)
    return actions, reactions, extra_resources


def primary_resource(owner_sheet: dict[str, Any]) -> tuple[str, int, str]:
    """(resource id, maximum, label) of the character's Path resource (CP)."""
    resource = _json(owner_sheet["ability_scores_and_statistics"].get("primary_resource")) or {}
    name = str(resource.get("name") or "Qi")
    return RESOURCE_IDS.get(name.lower(), RESOURCE_IDS["qi"]), int(resource.get("maximum") or 0), name


def compile_character(owner_sheet: dict[str, Any], *, actor_id: str, typed_authority: dict[str, Any] | None = None,
                      owner_items: list[dict[str, Any]] | None = None, powering: dict[str, str] | None = None,
                      reaction_plan: dict[str, Any] | None = None, reaction_hold: str | None = None,
                      held_weapons: list[dict[str, Any]] | None = None, granted_spheres: list[str] | None = None,
                      summon_plan: dict[str, Any] | None = None, left_behind: list[str] | None = None,
                      attuned: list[str] | None = None) -> dict[str, Any]:
    """``summon_plan``: the owner's pick of this character's creatures (combat/summons.py: {group: count, "beasts": [...]}).
    ``held_weapons``: the other fighters' weapons in the same fight ({"owner_action", "row"} from their bundles'
    "weapons"), compiled with this character's own numbers and offered only while it holds one it took (owner
    2026-09-26: "we will need improvised weapons anyway so we will need that capability")."""
    if typed_authority:
        # Explicit authority injection keeps its existing mutable input and
        # file-provenance contract; only the default file parse is cached.
        authority = typed_authority
        authority_sha256 = hashlib.sha256(TYPED_AUTHORITY.read_bytes()).hexdigest()
    else:
        authority, authority_sha256 = _read_compilation_authority(TYPED_AUTHORITY)
    mechanics = authority["mechanics"]
    stats = owner_sheet["ability_scores_and_statistics"]
    identity = owner_sheet.get("identity") or {}
    mods, scores = _modifiers(stats), _scores(stats)
    pb = int(identity.get("proficiency_bonus") or 2)
    kit = next((row.get("starting_kit") for row in owner_sheet.get("equipment") or [] if isinstance(row, dict) and row.get("starting_kit")), {}) or {}
    kit = _combat_equipment(kit)
    # What the owner leaves behind for this fight (owner 2026-09-27, the sheet's Items tab).
    kit, owner_items = _leave_behind(kit, list(owner_items or []), left_behind)
    # Attunement (owner 2026-09-28): an unattuned treasure fights as its base item.
    attuning = attunement(kit, owner_items, attuned)
    kit, owner_items = _unattuned(kit, owner_items, set(attuning["attuned"]), set(attuning["attunable"]))
    # Items the owner gave (factory_authoring/owner_items.py): given weapons fight
    # beside the kit's, and an equipped given armour replaces the kit armour.
    from factory_authoring.owner_items import equipped_armour

    given_armour = equipped_armour(owner_items or [])
    if given_armour:
        kit = {**kit, "resolved_treasure_armor": given_armour}
    diagnostics: list[str] = []
    resource = _json(stats.get("primary_resource")) or {}
    primary_name = str(resource.get("name") or "Qi").lower()
    primary = primary_name if primary_name in RESOURCE_IDS else "qi"
    # Each Path keeps its own CP pool (a Body + Spirit character has Stamina and Resonance;
    # smoke test 2026-09-25: only the primary pool was built, so Stamina actions were unusable).
    pools = {primary: int(resource.get("maximum") or 0)}
    for definition in resource.get("definitions") or []:
        name = str((definition or {}).get("name") or "").lower()
        if name in RESOURCE_IDS and name not in pools and (definition.get("max") is not None or definition.get("maximum") is not None):
            pools[name] = int(definition.get("max") if definition.get("max") is not None else definition.get("maximum") or 0)
    foundation_resource = _foundation_resource(owner_sheet)
    resources = [
        ResourceDefinition(resource_id=RESOURCE_IDS[name], initial=maximum, maximum=maximum) for name, maximum in pools.items()
    ] + [
        ResourceDefinition(resource_id=RESOURCE_IDS["martial_focus"], initial=1, maximum=1),
    ] + ([foundation_resource["definition"]] if foundation_resource else [])
    numbers = _typed_numbers(owner_sheet, mods, pb)
    # The two AC numbers, read once for everything that depends on them (the AC itself, whether the armour is
    # worn, its Strength requirement, and the sheet's note).  One basis, so no reader can use a different one.
    base_ac, always_on_ac = _ac_basis(stats)
    always_on_ac, armor_choice_ac = armour.sheet_ac_bonuses(owner_sheet, kit, mods, [])
    short = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:10]
    actions: list[ActionDefinition] = []
    # Abilities whose generic CP cost the player may assign to a Path pool (owner 2026-09-25, Q19);
    # populated wherever ``_choose_pool`` actually had a choice to make.
    choosable: list[tuple[str, str, str]] = []

    # Talents, acquired Insights, automatic Sphere base abilities and Path features.
    block = owner_sheet.get("spheres_and_talents") or {}
    ids = list(block.get("learned_talent_record_ids") or [])
    ids += _selected_insight_ids(block)
    # Source-owning adapters transport other validated acquisition namespaces.
    # Providers validate their selection/provenance; absent providers add nothing.
    from . import ext
    for acquired in ext.run_strict("compile_acquisition_ids", owner_sheet):
        if not isinstance(acquired, (list, tuple)) or any(not isinstance(key, str) or not key for key in acquired):
            raise ValueError("compile_acquisition_ids must return nonempty record IDs")
        ids.extend(acquired)
    if block.get("background_talent_record_id"):
        ids.append(block["background_talent_record_id"])
    ids += list(block.get("automatic_sphere_component_record_ids") or [])
    paths = owner_sheet.get("path_and_subpath") or {}
    ids += list(paths.get("path_feature_record_ids") or [])
    ids += [row.get("feature_id") for row in paths.get("earned_feature_occurrences") or [] if isinstance(row, dict) and row.get("feature_id")]
    from .source_acquisition import acquired_feature_ids
    admission_ids = acquired_feature_ids(owner_sheet, actor_id=actor_id)
    ids += admission_ids
    ids += _foundation_feature_ids(owner_sheet)
    # A Cultivation Insight the character chose at CL4/CL8/CL12/CL16/CL19 is a
    # record the character owns, so an Insight with a typed combat effect fights
    # exactly like any other owned record.  Insights with no typed effect are not
    # listed here: the sheet's Insights tab already shows every Insight the
    # character took (its printed benefit may be a passive, and its printed
    # +1 ability is already in the ability scores), and the fight's
    # "not automated yet" lists name abilities, not internal ids.
    ids += [key for key in _insight_record_ids(owner_sheet) if key in mechanics]
    ids = [background_alias(key, mechanics) for key in ids]
    insight_boundaries: dict[str, dict[str, Any]] = {}
    ids = _admit_insight_ids(ids, mechanics, diagnostics, insight_boundaries)
    admitted_insights = {key for key in ids if key.startswith("insight.")}
    # A base ability that comes with another record (docket 2026-09-28: the Flower sphere's Fragrance, missing from the
    # catalog, comes with Fragrant Veil; tools/build_typed_mechanics_authority.py base_ability_sources.json).
    ids += [key for key, row in mechanics.items() if row.get("granted_with") and key not in ids and set(row["granted_with"]) & set(ids)]
    # A record printing several abilities under one heading compiles as those abilities (owner 2026-09-26, Yin's
    # "Marking a Creature"; tools/build_typed_mechanics_authority.py apply_splits).
    ids = [child for key in ids for child in ((mechanics.get(key) or {}).get("split_into", [key]))]
    if any(key.startswith("insight.") and key not in admitted_insights for key in ids):
        ids = _admit_insight_ids(ids, mechanics, diagnostics, insight_boundaries)
    owner_sheet, skill_features = compiled_skill_sheet(owner_sheet, ids, mechanics, mods, pb, diagnostics)
    stats = owner_sheet["ability_scores_and_statistics"]
    # Every other named pool the character's abilities use (owner 2026-09-26); from here on the Foundation's pool
    # and these are matched alike (``_named_list``).
    named_pools = _named_pools(ids, mechanics, authority.get("resources") or {}, numbers, foundation_resource, authority.get("sphere_names"))
    resources += [row["definition"] for row in named_pools]
    foundation_resource = [*([foundation_resource] if foundation_resource else []), *named_pools] or None
    skipped: dict[str, list[str]] = {"reaction": [], "passive": [], "not_typed": [], "not_in_authority": []}
    # Passives and reactions with a building block (combat/rules/feature_blocks.json).
    from . import ext
    from .typed_reactions import compile_blocks

    blocks = compile_blocks(ids, pb=pb, key_mod=int(numbers.get("key_mod") or 0), cl=int(numbers.get("cl") or 1),
                            saves={ability: mods.get(ability, 0) for ability in ABILITIES},
                            resource_ids={**RESOURCE_IDS, **({"foundation": own_pool["resource_id"]} if (own_pool := _foundation_resource(owner_sheet)) else {})},
                            armor=_worn_armor(kit, armor_choice_ac, mods), shield=_carries_shield(kit, owner_items), mechanics=mechanics)
    blocks["automated"].extend(skill_features)

    blocks["passives"] = ext.transform("compile_passives", blocks["passives"], {"owned_ids": ids, "numbers": numbers, "owner_sheet": owner_sheet, "mechanics": mechanics})
    always_on_ac, armor_choice_ac = armour.sheet_ac_bonuses(owner_sheet, kit, mods, blocks["passives"])
    # Features that print "your Armor Class equals ..." state an alternate calculation, not a bonus (owner
    # amendment R1), so they are resolved here and handed to armour.armor_class to choose between instead of
    # being added to the calculation the sheet already chose. Inert without such a feature.
    alternate_ac = armour.alternate_ac_calculations(blocks["passives"], mods)
    # Hand-made rows carry only a feature id; the fight log names them ("Stamina Guard", not the raw id).
    for row in [*blocks["reactions"], *blocks["passives"]]:
        if not row.get("name") and row.get("feature_id") in mechanics:
            row["name"] = mechanics[row["feature_id"]]["name"]
    potency = next((row for row in blocks["passives"] if row["block"] == "technique_potency"), None)
    # Extra Attack sets the attacks per Attack action; on-hit passives (e.g. Conductive Strike) ride every qualifying hit.
    attacks = max([1, *(row["attacks"] for row in blocks["passives"] if row["block"] == "extra_attack")])
    on_hit_passives = [row for row in blocks["passives"] if row["block"] == "on_hit_damage"]

    def passive_on_hit(kind: str) -> list[dict[str, Any]]:
        rows = []
        for row in on_hit_passives:
            if kind not in row["attack_kinds"]:
                continue
            count, _, sides = str(row["dice"]).lower().partition("d")
            effect = {"type": "damage", "flat": row["bonus_value"], "damage_types": [row["damage_type"]], "source_feature": row["feature_id"]}
            if count.isdigit() and sides.isdigit():
                effect["dice"] = {"count": int(count), "sides": int(sides)}
            if row["once_per_turn"]:
                effect["once_per_turn"] = row["feature_id"]
            rows.append(effect)
        return rows

    def on_hit_average(rows: list[dict[str, Any]]) -> int:
        """Average extra damage per Attack action (once-per-turn rows count once)."""
        total = 0
        for row in rows:
            dice = row.get("dice") or {}
            each = int(dice.get("count") or 0) * (int(dice.get("sides") or 0) + 1) // 2 + int(row.get("flat") or 0)
            total += each * (1 if row.get("once_per_turn") else attacks)
        return total

    # Weapon attacks: every weapon the kit carries.
    # Whether a shield takes the hand a Versatile weapon needs is the shared hand model's question, not a
    # second one here: the die is compiled for the character as compiled (a carried shield occupies a hand),
    # and combat/ext/hand_occupancy.py's versatile_die_sides() then follows the hands actually free at play --
    # both directions, so dropping that shield restores the two-handed die.
    shield = _carries_shield(kit, owner_items)
    # The owner may grant a Sphere to a finished character for combat (owner 2026-09-26: the Weapons Sphere for the
    # characters whose treasure weapon they could not use), kept with its table settings.
    spheres = {*((owner_sheet.get("spheres_and_talents") or {}).get("sphere_record_ids") or []), *(granted_spheres or [])}
    owned_ids = [*ids, *[sphere for sphere in granted_spheres or [] if sphere not in ids]]
    weapons = _weapon_rows(kit, [{**row["record"], "inventory_key": f"given.{index}"}
                                for index, row in enumerate(owner_items or []) if row.get("kind") == "weapon"])
    proficient = _weapon_proficiency(owner_sheet, owned_ids, weapons)
    own_count = len(weapons)
    taken = [dict(row["row"], held_from=row["owner_action"]) for row in held_weapons or [] if isinstance(row, dict) and row.get("row")]
    # A weapon taken mid-fight uses the character's own training, never a creation-time "choose" pick.
    proficient += _weapon_proficiency(owner_sheet, owned_ids, taken, choices=False)
    weapons = [*weapons, *taken]
    own_weapon_actions: list[dict[str, Any]] = []
    # Each own weapon's kind, for talents that attack with "a melee/ranged/thrown weapon" or "an axe weapon" (below).
    weapon_kinds: list[dict[str, Any]] = []
    # Light or Paired weapons (owner 2026-09-26: "light and paired for offhand attacks for dual wielding"): after
    # an Attack action with one, a Bonus Action attack with a different one -- or with a Paired weapon's twin.
    # Dual Wielding's Greater Blades: any one-handed melee weapon without Two-Handed counts as Light for pairing.
    greater_blades = "TAL_DUAL_WIELDING_GREATER_BLADES" in ids
    pairable = [index for index, weapon in enumerate(weapons) if index < own_count and (_has_property(weapon["properties"], "Light")
                or _has_property(weapon["properties"], "Paired") or (greater_blades and _one_handed_melee(weapon)))]
    ambidexterity, paired_rhythm = "TAL_DUAL_WIELDING_AMBIDEXTERITY" in ids, "TAL_DUAL_WIELDING_PAIRED_RHYTHM" in ids
    # Dual Wielding Pair and Rhythm talents (owner 2026-09-26: "go ahead with the dual wielding").
    synchronous, following, tandem = ("TAL_DUAL_WIELDING_SYNCHRONOUS_ACCURACY" in ids, "TAL_DUAL_WIELDING_FOLLOWING_STRIKE" in ids,
                                      "TAL_DUAL_WIELDING_TANDEM_OFFENSIVE" in ids)
    offhand_flag = lambda index: f"offhand:{index}"  # noqa: E731
    rules = _weapon_rules()
    weapon_abilities = {
        index: _attack_ability(("STR", "DEX") if "finesse" in weapon["properties"].lower() else ("STR",),
                              sheet=owner_sheet, owned_ids=owned_ids, mods=mods, source=weapon["item_id"], kind="weapon")
        for index, weapon in enumerate(weapons)
    }
    for index, weapon in enumerate(weapons):
        properties = weapon["properties"]
        special = weapon_specials().get(weapon["item_id"]) or {}
        printed_damage = str(special.get("damage") or weapon["damage"])  # e.g. the rope dart's 1d2 (owner 2026-09-26)
        ability = weapon_abilities[index]
        dice, damage_type = _dice(printed_damage)
        # Versatile (owner 2026-09-26): "the two-handed die unless a shield takes the other hand". The shield
        # question is the shared hand model's, not a second one here: this compiles the die for the character
        # as equipped (a carried shield occupies a hand), and combat/ext/hand_occupancy.py's versatile_die_sides()
        # follows the hands actually free at play in both directions -- so dropping that shield restores the
        # two-handed die and picking one up returns to the ordinary one.
        versatile = re.search(r"Versatile \(?(\d+)d(\d+)", properties)
        two_handed_versatile = bool(versatile and not shield)
        if two_handed_versatile:
            dice = DiceSpec(count=int(versatile.group(1)), sides=int(versatile.group(2)), modifier=0)
        bonus = mods.get(ability, 0) + weapon["refinement"]
        to_hit = (pb if proficient[index] else 0) + mods.get(ability, 0) + weapon["refinement"]
        # "Thrown 20/60" or a bow's "Range 150/600": a ranged attack out to the long range, with Disadvantage past
        # the normal one (typed_executor.block_attack).
        thrown = re.search(r"(?:Thrown|Range) (\d+)/(\d+)", properties)
        normal_ft, long_ft = (int(thrown.group(1)), int(thrown.group(2))) if thrown else (None, None)
        # A Thrown weapon of a melee class (a dagger, an axe) also strikes in melee (owner 2026-09-26); a bow, a
        # sling or a ranged-only thrown weapon does not.
        from factory_authoring.starting_kits import _authorities

        # A book row without a proficiency class (the simple Spear, duan qiang) is judged by its attack_kind: a spear
        # strikes in melee as well as thrown, so it must not become a ranged-only, thrown-and-lost attack.
        book_row = _authorities()[1].get(weapon["item_id"]) or {}
        weapon_class = str(book_row.get("proficiency_class") or "").lower()
        melee_kind = str(book_row.get("attack_kind") or "").lower() == "melee"
        also_thrown = bool(thrown) and "thrown" in properties.lower() and ("melee" in weapon_class or (not weapon_class and melee_kind))
        # Loading: one shot per action whatever Extra Attack allows. Heavy: Disadvantage without Strength 13 (melee)
        # or Dexterity 13 (ranged), as does the Item Book's "Strength 13" (2024 rules).
        count = 1 if _has_property(properties, "Loading") else attacks
        needs = "DEX" if _has_property(properties, "Heavy") and "ammunition" in properties.lower() else \
            "STR" if _has_property(properties, "Heavy") or "strength 13" in properties.lower() else None
        clumsy = bool(needs and scores.get(needs, 10) < 13)
        action_id = f"action:typed.{short}.weapon.{weapon['item_id'].split('.')[-1]}{'.' + weapon['key'] if weapon['key'] else ''}"
        held_from = weapon.get("held_from")
        if held_from:  # another fighter's weapon, usable only while held
            action_id = f"action:typed.{short}.weapon.held.{re.sub(r'[^a-z0-9]+', '_', held_from.split('action:typed.')[-1].lower())}"
        else:
            own_weapon_actions.append({"owner_action": action_id, "row": {key: weapon[key] for key in
                         ("item_id", "name", "damage", "properties", "refinement", "treasure", "key", "enchantments", "inventory_key")}})
        if not held_from:
            weapon_kinds.append({"action_id": action_id, "name": str(weapon["name"]), "item_id": weapon["item_id"],
                                 "melee": not thrown or also_thrown, "ranged": bool(thrown),
                                 "thrown": bool(thrown) and "thrown" in properties.lower(), "proficient": proficient[index],
                                 # A weapon a Qualifying Pair is made of (Cyclone Cut's "each weapon in your Qualifying Pair").
                                 "pairable": index in pairable and _one_handed_melee(weapon)})
        enchantment_hits = _enchantment_on_hit(weapon["enchantments"])
        extra_hits = passive_on_hit("weapon")
        save_dc = 8 + pb + mods.get(ability, 0)  # a mastery's or maneuver's save, as in the 2024 masteries
        reach = int(special.get("reach_ft") or 0) or _melee_reach(properties)
        # The weapon's mastery (owner 2026-09-26: "each weapon type to express in mechanics how they fight ... in line
        # with dnd 5e"): the 2024 property of its nearest 5e weapon, on every attack with it.
        mastery = special.get("mastery") if _mastery_allowed(rules, weapon["item_id"], proficient[index], spheres) else None
        mastery_hits, mastery_misses = _mastery_effects(mastery, mods.get(ability, 0), _weapon_damage_types(printed_damage)[0])
        on_hit = [{"type": "damage", "weapon_damage": True}, *enchantment_hits, *extra_hits, *mastery_hits]
        opens = [offhand_flag(other) for other in pairable if index in pairable
                 and (other != index or _has_property(properties, "Paired"))]
        # The normal attack, plus one button per maneuver the weapon allows (Pathfinder-style, where 5e has none):
        # the Attack action's hits deal their damage and the first one also tries the maneuver (owner 2026-09-26:
        # "they can be added to it, but only one").
        variants = [(action_id, f"{weapon['name']} attack", [], {}, EconomyKind.ACTION, {})]
        if also_thrown:
            variants.append((f"{action_id}#thrown", f"{weapon['name']} thrown", [], {"option_of": action_id, "option_label": "Thrown"},
                             EconomyKind.ACTION, {}))
        # A Sphere's own maneuver for every melee weapon (owner 2026-09-28: the Piercing Needle's Disarming Technique).
        granted = [name for sphere, names in (rules.get("sphere_maneuvers") or {}).items() if sphere in spheres for name in names] \
            if (not thrown or also_thrown) else []
        for name in dict.fromkeys([*(special.get("maneuvers") or []), *granted]):
            maneuver = (rules.get("maneuvers") or {}).get(name)
            if not maneuver or not _meets(maneuver.get("requires") or rules.get("maneuver_requires"), proficient[index]):
                continue
            variants.append((f"{action_id}#{re.sub(r'[^a-z0-9]+', '_', name.lower())}", f"{weapon['name']} attack: {name}",
                             [_maneuver_effect(maneuver)], {"option_of": action_id, "option_label": name}, EconomyKind.ACTION, {}))
        if "TAL_FENCING_LUNGE" in owned_ids and (not thrown or also_thrown):
            # Lunge (owner's Piercing Needle text): "While holding Martial Focus, ... increase your reach for melee attacks by 5 feet
            # until the end of the current turn. If you use Lunge, take a -2 penalty to attack rolls against targets within 5 feet
            # of you until the start of your next turn." The reach is this attack's; the penalty is combat/ext/needle_footwork.py.
            variants.append((f"{action_id}#lunge", f"{weapon['name']} attack: Lunge", [], {"option_of": action_id, "option_label": "Lunge"},
                             EconomyKind.ACTION, {"requires_resource": {RESOURCE_IDS["martial_focus"]: 1}, "lunge": True}))
        if "tianxia.sphere.weapons" in spheres:
            # Weapons Sphere, Apply Weapon Method: one method per turn that fits the weapon's tags (major: Martial Focus).
            for name, method in _weapon_methods(rules, weapon["item_id"], properties):
                rider = _method_rider(method, damage_type=_weapon_damage_types(printed_damage)[0], key=action_id)
                variants.append((f"{action_id}#method_{re.sub(r'[^a-z0-9]+', '_', name.lower())}", f"{weapon['name']} attack + {name}",
                                 [rider], {"option_of": action_id, "option_label": name}, EconomyKind.ACTION,
                                 {"blocked_by_turn_flag": "weapon_method",
                                  **({"requires_resource": {RESOURCE_IDS["martial_focus"]: 1}} if method.get("kind") == "major" else {})}))
        if not held_from and index in pairable and any(other != index or _has_property(properties, "Paired") for other in pairable):
            # Nick: the Light weapon's extra attack is part of the Attack action instead of a Bonus Action.
            variants.append((f"{action_id}#offhand", f"{weapon['name']} off-hand attack", [], {},
                             EconomyKind.NONE if mastery == "Nick" else EconomyKind.BONUS_ACTION, {}))
            if ambidexterity and mastery != "Nick":  # Martial Focus moves it into the Attack action (no extra attack)
                variants.append((f"{action_id}#offhand_ambidexterity", f"{weapon['name']} off-hand attack (Ambidexterity)", [], {},
                                 EconomyKind.NONE, {"requires_resource": {RESOURCE_IDS["martial_focus"]: 1}, "spend_focus": True}))
            if synchronous:
                # Synchronous Accuracy: after a Lead Weapon attack of the Attack action misses, expend Martial Focus and the
                # Paired Strike is two attacks with the Answering Weapon; once per turn.
                variants.append((f"{action_id}#offhand_synchronous", f"{weapon['name']} off-hand attack x2 (Synchronous Accuracy)", [], {},
                                 EconomyKind.NONE if mastery == "Nick" else EconomyKind.BONUS_ACTION,
                                 {"requires_resource": {RESOURCE_IDS["martial_focus"]: 1}, "spend_focus": True, "attack_count": 2,
                                  "requires_turn_flags": ["pair:lead_missed"], "blocked_by_turn_flag": "pair:synchronous_used",
                                  "marks_used": ["pair:synchronous_used"]}))
            if following:
                # Following Strike: one more Answering Weapon attack in the same Bonus Action after the Paired Strike, at a
                # creature other than the Paired Strike's, while a Lead attack went to a third one; once per turn. It is not
                # itself a Paired Strike.
                variants.append((f"{action_id}#following", f"{weapon['name']} Following Strike", [], {}, EconomyKind.NONE,
                                 {"requires_turn_flag": "pair:paired_strike_done", "blocked_by_turn_flag": "pair:following_used",
                                  "following_strike": True, "marks_used": ["pair:following_used"], "answer_damage": True}))
        for variant_id, display_name, maneuver, labels, economy, extra in variants:
            offhand = "#offhand" in variant_id
            answering = offhand or bool(extra.get("answer_damage"))
            ranged = bool(thrown) and (not also_thrown or variant_id.endswith("#thrown"))
            # The off-hand attack adds no ability modifier to its damage unless it is negative (2024 Light).
            damage_bonus = (min(0, mods.get(ability, 0)) + weapon["refinement"]) if answering else bonus
            attack = {"type": "attack", "attack_kind": "weapon", "count": int(extra.get("attack_count") or (1 if answering else count)),
                      "on_hit": [*copy.deepcopy(on_hit), *maneuver], **({"on_miss": copy.deepcopy(mastery_misses)} if mastery_misses else {})}
            typed = {
                "effects": [attack],
                "numbers": {**numbers, "attack_bonus": to_hit, "save_dc": save_dc},
                "weapon": {"damage": {"count": dice.count, "sides": dice.sides, "modifier": damage_bonus}, "damage_type": damage_type,
                           "damage_types": _weapon_damage_types(printed_damage),
                           "ability": ability, "ability_modifier": mods.get(ability, 0), "properties": properties,
                           "implement_id": weapon["item_id"], "weapon_family": weapon.get("weapon_family"),
                           # Delivery is per compiled variant: a thrown melee
                           # weapon has both a melee attack and a ranged throw.
                           "attack_delivery": "ranged" if ranged else "melee",
                           "omits_ability_damage": answering},
                "duration": {"kind": "instant"}, "range_ft": normal_ft if ranged else None, "long_range_ft": long_ft if ranged else None,
                "riders": [], "source": weapon["item_id"], **labels, "proficient": proficient[index], "mastery": mastery,
                **({"disadvantage": "Heavy"} if clumsy else {}), **({"opens": opens} if opens and not offhand else {}),
                **({"uses": [offhand_flag(index)]} if offhand else {}),
                **({"pair_role": "answer" if offhand else "lead", "paired_rhythm": paired_rhythm} if index in pairable and not extra.get("answer_damage") else {}),
                # Tandem Offensive: a Lead hit while holding Martial Focus lends its numeric bonus to the Answering Weapon.
                "magic_bonus": int(weapon["refinement"] or 0), **({"tandem": True} if tandem and index in pairable else {}),
                **({"marks_used": list(extra["marks_used"])} if extra.get("marks_used") else {}),
                # Ability-owned weapon traits use the general plug-in seam.
                "mundane": not weapon["refinement"] and not weapon["enchantments"],
            }
            from . import ext

            for traits in ext.run("compile_weapon_traits", {"owned_ids": ids, "weapon": weapon, "typed": typed,
                                                                    "actor_id": actor_id, "action_id": variant_id}):
                typed.update(traits)
            if extra.get("spend_focus"):  # Ambidexterity: the Martial Focus is expended when it is used
                typed["effects"].insert(0, {"type": "spend_resource", "resource_id": RESOURCE_IDS["martial_focus"], "flat": 1, "applies_to": "self"})
            per_hit = (dice.count * (dice.sides + 1)) // 2 + damage_bonus + sum(
                (row["dice"]["count"] * (row["dice"]["sides"] + 1) // 2
                 if row.get("type") == "damage" and row.get("dice") else int(row.get("expected_damage") or 0))
                for row in enchantment_hits)
            actions.append(ActionDefinition(
                source_definition_id=variant_id, display_name=display_name, owner_id=actor_id,
                economy=economy, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                range_ft=long_ft if ranged else reach + (5 if extra.get("lunge") else 0),
                parameters={"typed": typed, "expected_damage": attack["count"] * per_hit + on_hit_average(extra_hits),
                            **({"requires_turn_flag": offhand_flag(index)} if offhand else {}),
                            **({"requires_held_weapon": held_from} if held_from else {}),
                            **({"requires_hands": 2} if re.search(r"\bTwo-Handed(?: Method)?\b", properties, re.I) or two_handed_versatile else {}),
                            **({"free_primary": True} if economy == EconomyKind.NONE else {}),
                            **{key: value for key, value in extra.items() if key not in ("spend_focus", "attack_count", "marks_used", "answer_damage")}},
            ))
        if held_from:
            continue
        # Picking the weapon up after a Disarm (offered only then); the AI values it at the weapon's damage.
        actions.append(ActionDefinition(
            source_definition_id=f"{action_id}.pickup", display_name=f"Pick up {weapon['name']}", owner_id=actor_id,
            economy=EconomyKind[str(rules.get("pick_up_economy") or "BONUS_ACTION")], resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"effects": [{"type": "recover_weapon", "weapon": action_id}], "numbers": numbers,
                                  "duration": {"kind": "instant"}, "riders": [], "source": weapon["item_id"]},
                        "expected_damage": count * ((dice.count * (dice.sides + 1)) // 2 + bonus), "requires_disabled_action": action_id},
        ))
    # Escaping a grapple (owner 2026-09-26: "an ability/action that all grappled creatures get each turn"): an Action,
    # the better of Athletics or Acrobatics against the grappler's escape DC. That DC is the owner's printed one, not the
    # 2024 book value: rules_text.json WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC sets "8 + Strength modifier +
    # Proficiency Bonus" for both the Wrestling Save DC and the grapple escape DC, and typed_executor stores it on the hold.
    # combat/ext/escape_dc_text.py is what shows the number to the player.
    skills = {str(row.get("skill")): int(row.get("bonus") or 0) for row in (_json(stats.get("skills")) or []) if isinstance(row, dict)}
    escape_bonus = max(skills.get("Athletics", mods.get("STR", 0)), skills.get("Acrobatics", mods.get("DEX", 0)))
    actions.append(ActionDefinition(  # letting go of a grapple is free (2024), e.g. to move without dragging
        source_definition_id=f"action:typed.{short}.release_grapple", display_name="Release grapple", owner_id=actor_id,
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "release_grapple"}], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "requires_grappling": True, "free_primary": True},
    ))
    actions.append(ActionDefinition(
        source_definition_id=f"action:typed.{short}.escape_grapple", display_name="Escape grapple", owner_id=actor_id,
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "escape_grapple"}], "numbers": {**numbers, "escape_bonus": escape_bonus},
                              "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 1, "requires_condition": "condition:typed.grappled"},
    ))

    # Getting through a wall (owner 2026-09-27, combat/rules/terrain.json "breach"): offered only beside one it may try
    # (combat/gate4_engine.py legal_candidates).
    for label, ability, skill, result in (("Force through the wall", "STR", "Athletics", "collapse"),
                                          ("Work the Puzzle Wall", "INT", "Investigation", "opening")):
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.wall_{result}", display_name=label, owner_id=actor_id,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"effects": [{"type": "wall_breach", "result": result}],
                                  "numbers": {**numbers, "check_bonus": skills.get(skill, mods.get(ability, 0))},
                                  "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "requires_wall": result},
        ))

    built: dict[str, dict[str, Any]] = {}  # built key -> the action being built (modifiers change it below)
    # mechanic id -> the built key(s) it compiled to: one key normally, or one per option (owner
    # 2026-09-26) for a "Choose one" ability -- a modifier that names the ability by its printed name
    # (apply_modifiers below) must still find every one of them.
    option_index: dict[str, list[str]] = {}
    owned = [mechanic_id for mechanic_id in dict.fromkeys(ids) if mechanic_id in mechanics]
    generic_reactions: dict[str, dict[str, Any]] = {}  # mechanic id -> generic typed_reactions row
    for mechanic_id in dict.fromkeys(ids):
        mechanic = mechanics.get(mechanic_id)
        if mechanic is None:
            # A source-backed acquisition adapter can name a partial passive
            # whose remaining clauses are absent from typed authority.
            skipped["not_in_authority"].append(next((row["name"] for row in blocks["passives"]
                if row.get("feature_id") == mechanic_id and row.get("name")), mechanic_id))
            continue
        if mechanic_id in blocks["automated"]:
            continue
        economy = mechanic["activation"]["economy"]
        if economy not in {"action", "bonus_action"}:
            if economy == "reaction":
                compiled = _generic_reaction(mechanic_id, mechanic, pb=pb, numbers=numbers, primary=primary, pools=pools,
                                             diagnostics=diagnostics, powering=powering, foundation_resource=foundation_resource,
                                             option_pick=((reaction_plan or {}).get("options") or {}).get(mechanic_id))
                if compiled is not None:
                    rows, extra, choice_entry = compiled
                    for index, row in enumerate(rows):
                        row["ability_mods"] = dict(mods)  # "+ your Constitution modifier" (typed_reactions _generic_amount formulas)
                        generic_reactions[mechanic_id if index == 0 else f"{mechanic_id}#{index}"] = row
                    resources.extend(extra)
                    if choice_entry:
                        choosable.append(choice_entry)
                else:
                    skipped["reaction"].append(mechanic["name"])
            elif (economy == "no_action" or (economy == "passive" and not mechanic.get("modifier"))) and (mechanic.get("free") or (
                    # A costed passive trigger is an optional activation even when its effect is a rider the GM resolves.
                    # Compile its generic row so the activation cost gates the Ask-me window before those effects run.
                    economy == "passive" and bool(mechanic.get("cost"))
                    and bool((mechanic.get("activation") or {}).get("trigger"))
                    and bool(mechanic.get("effects"))) or any(
                    # bodya 2026-09-29: "hold_at_1hp" added alongside gain_resource/spend_resource -- a no_action
                    # "you would be reduced to 0 HP but are not killed outright" trigger (Body Refining's Blood Pump)
                    # is exactly this same "free printed effect, not a Reaction" shape (its own text says "Action:
                    # None"), and must not compete for the Reaction slot a damage_soak response (Stamina Guard) may
                    # already have spent on the same hit; without this it fell to skipped["passive"] and never fired.
                    isinstance(e, dict) and e.get("type") in ("gain_resource", "spend_resource", "hold_at_1hp") for e in _walk(mechanic.get("effects") or []))):
                # A Foundation's own resource-generation trigger (e.g. Generate Mirror Trace) is a free
                # printed effect, not a Reaction (owner 2026-09-26): compiled the same way as a generic
                # reaction when its trigger is one the engine can run, but flagged "free" so it never
                # costs or requires the Reaction (combat/typed_reactions.py).
                compiled = _generic_reaction(mechanic_id, mechanic, pb=pb, numbers=numbers, primary=primary, pools=pools,
                                             diagnostics=diagnostics, powering=powering, foundation_resource=foundation_resource,
                                             free=True)
                if compiled is not None:
                    rows, extra, choice_entry = compiled
                    for index, row in enumerate(rows):
                        row["ability_mods"] = dict(mods)  # "+ your Constitution modifier" (typed_reactions _generic_amount formulas)
                        # "free" describes Reaction economy only; paid triggers still need consent.
                        if row.get("costs"):
                            row["optional"] = True
                        generic_reactions[mechanic_id if index == 0 else f"{mechanic_id}#{index}"] = row
                    resources.extend(extra)
                    if choice_entry:
                        choosable.append(choice_entry)
                else:
                    skipped["passive"].append(mechanic["name"])
            elif not mechanic.get("modifier") and mechanic_id not in blocks["defended"]:
                skipped["passive"].append(mechanic["name"])
            continue
        options = mechanic.get("options") or []
        from .action_publication import grant_heading
        if grant_heading(mechanic, _rules_text().get(mechanic_id), mechanics):
            # Grant headings must leave before payment variants and augments:
            # an augment can otherwise give a do-nothing parent real effects.
            skipped["not_typed"].append(mechanic["name"])
            continue
        if not mechanic.get("effects") and not options:
            skipped["not_typed"].append(mechanic["name"])
        action_id = f"action:typed.{short}.{mechanic_id}"
        target_kind, range_ft = _target_kind(mechanic, numbers.get("cl"))
        costs, extra, choice, other_ways = _costs_and_ways(mechanic, primary, pb, action_id, diagnostics, pools, powering,
                                                           foundation_resource=foundation_resource)
        resources.extend(extra)
        if choice:
            choosable.append((action_id, mechanic["name"], choice))
        action_numbers = numbers
        if potency and (any(resource == potency["resource_id"] for resource, _ in costs) or mechanic.get("path_id") == potency.get("path_id")):
            action_numbers = {**numbers, "potency": potency["bonus_value"]}  # e.g. Qi Technique Potency
        if len(options) >= 2:
            # A "Choose one" ability (owner 2026-09-26, tools/type_options.py + factory_authoring
            # .typed_structure.build_options): one action per printed option, sharing the base
            # ability's economy/cost/range/area/limits; the all-options action is never compiled, so
            # nothing applies every option at once any more (the bug tonight's tournament found).
            # Reviewed printed branches can opt past the legacy menu cap. Keep
            # their original indices so existing action IDs do not move.
            picked = [(index, option) for index, option in enumerate(options)
                      if index < MAX_OPTIONS_PER_ABILITY or option.get("include_in_menu") is True]
            if len(options) > len(picked):
                diagnostics.append(f"{mechanic['name']}: {len(options)} options capped at {MAX_OPTIONS_PER_ABILITY}")
            keys = []
            for index, option in picked:
                option_effects = _resolve_resource_effects(name_damage_effects(option.get("effects") or [], mechanic["name"]), mechanic=mechanic, primary=primary,
                                                           pools=pools, foundation_resource=foundation_resource)
                # Each option is aimed by its own effects: an attacking option of a menu whose shared part is empty
                # compiled as an ally-only action (Astra's audit, 2026-09-26).
                option_area = option.get("area") or mechanic.get("area")  # its own area first (audit F1: Numbing Smoke)
                # ... and its own range (rider lane C11: "Range: Spear Line or 90 feet through Spear Light" is one range per option).
                option_range = option.get("range") or mechanic.get("range")
                # The option as the compiler reads it: its own effects, its own area and its own range, so the target
                # point and the area's placement are decided from the same row (never one from the option and one
                # from the ability).
                option_mechanic = {**mechanic, "effects": option_effects, "area": option_area, "range": option_range,
                                   "target": option.get("target") or mechanic.get("target")}
                target_kind, range_ft = _target_kind(option_mechanic, numbers.get("cl"))
                # An option may give its own "riders" (a reviewed_final option with a caveat specific to that
                # choice, e.g. one option of a multi-option ability needing an object-only caveat the other options
                # don't); falling back to the mechanic's shared riders keeps every existing reviewed entry working
                # unchanged (w4-roster 2026-09-28, Dust to Dust/Weight Shift: per-option riders stop every option of
                # a "choose one" from repeating every other option's caveat).
                option_riders = option.get("riders") if option.get("riders") is not None else mechanic.get("riders")
                typed = {"effects": option_effects, "riders": _gm_lines(option_riders, mechanic, option_effects, str(option.get("label") or "")),
                         "numbers": action_numbers,
                         "weapon": None, "duration": mechanic.get("duration") or {"kind": "instant"},
                         "area": _aimed_area(option_mechanic, numbers.get("cl")),
                         "range_ft": range_ft, "source": mechanic_id, "typing_status": mechanic.get("typing_status"),
                         "coverage": mechanic.get("coverage"), "option_of": mechanic_id, "option_label": str(option.get("label") or ""),
                         "sphere": mechanic.get("sphere_id"),
                         # A printed "Prerequisite: CL N+" gate, enforced at admission by activation_requirements.
                         **({"min_cl": int(mechanic["min_cl"])} if mechanic.get("min_cl") else {})}
                _target_mark(typed, mechanic)
                _printed_attack_ranges(typed, {**mechanic, 'range': option_range})
                option_key = f"{mechanic_id}#opt{index}"
                built[option_key] = {"action_id": f"{action_id}#opt{index}", "name": f"{mechanic['name']}: {option.get('label') or ''}",
                                     "economy": economy, "target_kind": target_kind, "range_ft": range_ft, "costs": list(costs),
                                     "typed": typed, "mechanic": mechanic, "modifiers": []}
                keys.append(option_key)
                keys += _add_ways(built, option_key, other_ways)  # "Cost: 15 Stamina or 15 CP": a row for each way to pay it
            option_index[mechanic_id] = keys
            continue
        action_effects = _resolve_resource_effects(name_damage_effects(mechanic.get("effects") or [], mechanic["name"]), mechanic=mechanic, primary=primary, pools=pools,
                                                   foundation_resource=foundation_resource)
        typed = {"effects": action_effects, "riders": _gm_lines(mechanic.get("riders"), mechanic, action_effects), "numbers": action_numbers,
                 "weapon": None, "duration": mechanic.get("duration") or {"kind": "instant"},
                 "area": _aimed_area(mechanic, numbers.get("cl")),
                 "range_ft": range_ft, "source": mechanic_id, "typing_status": mechanic.get("typing_status"),
                 "coverage": mechanic.get("coverage"), "sphere": mechanic.get("sphere_id"),
                 # A printed "Prerequisite: CL N+" gate, enforced at admission by activation_requirements.
                 **({"min_cl": int(mechanic["min_cl"])} if mechanic.get("min_cl") else {})}
        _target_mark(typed, mechanic)
        _printed_attack_ranges(typed, mechanic)
        built[mechanic_id] = {"action_id": action_id, "name": mechanic["name"], "economy": economy, "target_kind": target_kind,
                              "range_ft": range_ft, "costs": list(costs), "typed": typed, "mechanic": mechanic, "modifiers": []}
        option_index[mechanic_id] = [mechanic_id, *_add_ways(built, mechanic_id, other_ways)]

    # A compiled generic reaction, for a plug-in to re-key or reseal (owner
    # 2026-10-13: a Cadence talent keys Constitution, combat/ext/battle_musician.py).
    # Pure transform over one row; None retains it. The row carries its own
    # ``numbers`` copy, so a re-key never reaches the character's other talents.
    # Default-inert: with no subscriber every reaction keeps the row it compiled to.
    for _reaction_key in list(generic_reactions):
        _reaction_row = generic_reactions[_reaction_key]
        _reaction_mechanic_id = str(_reaction_row.get("feature_id") or "")
        generic_reactions[_reaction_key] = ext.transform("compile_reaction", _reaction_row,
            {"owner_sheet": owner_sheet, "owned_ids": owned_ids, "numbers": dict(numbers),
             "mechanic_id": _reaction_mechanic_id,
             "mechanic": mechanics.get(_reaction_mechanic_id)})

    # Owned recipes enter the base technique before its normal modifier pass.
    # Providers supply effect data, not ActionDefinitions or bespoke payment.
    from .recipe_options import contributions
    for release in contributions(owned, mechanics):
        base_keys = option_index.get(release.base_id) or []
        if not base_keys:
            raise ValueError('A recipe release requires a compiled base technique')
        first = base_keys[0]
        templates = [built[key] for key in base_keys if key == first or built[key].get('way_of') == first]
        for index, template in enumerate(templates):
            key = f'{release.base_id}#recipe.{release.recipe_id}' + (f'#way{index}' if index else '')
            recipe = mechanics[release.recipe_id]
            effects = _resolve_resource_effects(copy.deepcopy(release.effects), mechanic=recipe, primary=primary,
                                               pools=pools, foundation_resource=foundation_resource)
            typed = {**copy.deepcopy(template['typed']), 'effects': effects, 'area': copy.deepcopy(release.area),
                     'riders': [], 'recipe_id': release.recipe_id, 'option_label': recipe['name'],
                     'source': release.base_id, 'option_of': release.base_id}
            typed.pop('target_requires_mark', None)
            built[key] = {**copy.deepcopy(template), 'action_id': f'action:typed.{short}.{key}',
                          'name': f"{mechanics[release.base_id]['name']}: {recipe['name']}",
                          'typed': typed, 'target_kind': release.target_kind, 'modifiers': []}
            if index:
                built[key]['way_of'] = f'{release.base_id}#recipe.{release.recipe_id}'
            option_index[release.base_id].append(key)

    # A modifier that names a generic reaction (e.g. Draw Past / Hand on the Wrist -> Flowing Response)
    # attaches to it directly: it never enters ``built``, so apply_modifiers below cannot see it
    # (owner 2026-09-25).
    reaction_modifier_rows, reaction_modifier_ids = _attach_reaction_modifiers(generic_reactions, owned, mechanics, set(blocks["automated"]),
                                                                               primary=primary, pools=pools)

    # The Piercing Needle (owner 2026-09-28): Feint -- Help yourself against a creature within 5 feet; your next attack
    # against it has Advantage -- and Exploits, applied once a round on a qualifying melee hit (combat/typed_executor.py
    # apply_exploit), with a free pick among the ones it knows.
    if "tianxia.sphere.the_piercing_needle" in spheres:
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.feint", display_name="Feint", owner_id=actor_id, economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
            parameters={"typed": {"effects": [{"type": "needle_feint"}],  # combat/ext/needle_feint.py: Help, aimed at an enemy within 5 feet
                                  "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "feint": True}, "expected_damage": 0}))
    exploits = []
    for mid in owned_ids:
        mechanic = mechanics.get(mid) or {}
        if "Exploit" not in _talent_tags(mid) or mechanic.get("sphere_id") != "tianxia.sphere.the_piercing_needle":
            continue
        effects = copy.deepcopy(((mechanic.get("modifier") or {}).get("effects")) or mechanic.get("effects") or [])
        if effects:
            # "Cost: Expend Martial Focus" is paid when the Exploit lands (combat/ext/needle.py apply_exploit).
            focus = sum(int(part.get("amount") or 0) for part in ((mechanic.get("cost") or [[]])[0] or [])
                        if isinstance(part, dict) and part.get("resource") == "martial_focus")
            exploits.append({"id": mid, "name": mechanic["name"], "effects": effects, **({"focus": focus} if focus else {})})
    if exploits:
        blocks["passives"].append({"feature_id": "tianxia.sphere.the_piercing_needle.exploits", "block": "exploits", "name": "Exploits",
                                   "options": exploits})
        blocks["automated"].extend(row["id"] for row in exploits)
        skipped["passive"] = [name for name in skipped["passive"] if name not in {row["name"] for row in exploits}]
        for row in exploits:
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.exploit.{row['id'].split('.')[-1].lower()}", display_name=f"Exploit: {row['name']}",
                owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "pick_exploit", "exploit": row["id"], "name": row["name"]}], "numbers": numbers,
                                      "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}))
    # Talents that change other abilities (owner 2026-09-25): an always-on modifier becomes part of the
    # ability it changes; an optional one ("you may...") is its own choice, "Water Lash + Water Whip".
    modifier_rows = reaction_modifier_rows + apply_modifiers(built, owned, mechanics, primary, pools,
                                                             automated=set(blocks["automated"]) | reaction_modifier_ids,
                                                             foundation_resource=foundation_resource, option_index=option_index)
    for row in built.values():
        actions.append(_action_definition(row, actor_id, numbers))
        for variant in row["variants"]:
            actions.append(_action_definition(variant, actor_id, numbers))
        # Which augments the next use carries: a free toggle for each, and one to clear them (owner 2026-09-27, any number
        # of augments on one use; combat/zones.py augments_of).
        for augment in (row.get("loadout") or {}).get("augments") or []:
            for key, label, effect in ((augment["key"], augment["name"], {"type": "toggle_augment", "family": row["action_id"], "augment": augment["key"]}),):
                actions.append(ActionDefinition(
                    source_definition_id=f"{row['action_id']}.toggle.{hashlib.sha256(key.encode()).hexdigest()[:8]}",
                    display_name=augment_toggle_label(row["name"], label), owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                    target_kind="SELF", parameters={"typed": {"effects": [effect], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                                                    "expected_damage": 0, "player_only": True, "setting_only": True, "augment_toggle": row["action_id"], "augment_key": key,
                                                    "augment_name": label, "augment_family_name": row["name"]}))
        if row.get("loadout"):
            actions.append(ActionDefinition(
                source_definition_id=f"{row['action_id']}.toggle.none", display_name=augment_toggle_label(row["name"], None), owner_id=actor_id,
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"typed": {"effects": [{"type": "toggle_augment", "family": row["action_id"], "augment": None}], "numbers": numbers,
                                      "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "player_only": True, "setting_only": True, "augment_toggle": row["action_id"], "augment_key": None,
                            "augment_family_name": row["name"]}))

    # Forged Techniques (combat/forged.py; owner 2026-09-27): the Base Form carries the Primary Sphere Effect's typed
    # core -- a Strike with the character's weapon, a Burst as an area save, an Aura or Zone left on the map -- with
    # the Secondary Sphere Effects, Augments and Drawbacks applied, at its own activation and CP cost from the Path
    # pool. Each is registered as a mechanic, so weapon delivery and zones treat it like a printed talent.
    from . import forged as forged_rules

    forged_table = forged_rules.rules() if owner_sheet.get("forged_techniques") else None
    for technique in owner_sheet.get("forged_techniques") or []:
        if not isinstance(technique, dict):
            continue
        name = str(technique.get("name") or "Forged Technique")
        economy = str(technique.get("action_type") or "action").strip().lower().replace(" ", "_")
        if economy == "reaction":
            # A Counter or a Reaction-Activation technique runs as a reaction when its trigger is known (docket 2026-09-28,
            # combat/forged.py as_reaction): the record's own, or its Primary Sphere Effect's printed trigger.
            technique_id = str(technique.get("technique_id") or technique.get("record_id") or name)
            forged_mechanic = forged_rules.mechanic_for({**technique, "technique_id": technique_id}, mechanics, forged_table)
            reaction = forged_rules.as_reaction(technique, forged_mechanic, mechanics) if forged_mechanic else None
            compiled = _generic_reaction(technique_id, reaction, pb=pb, numbers=numbers, primary=primary, pools=pools, diagnostics=diagnostics,
                                         powering=powering, foundation_resource=foundation_resource,
                                         option_pick=((reaction_plan or {}).get("options") or {}).get(technique_id)) if reaction else None
            if compiled is None:
                skipped["reaction"].append(name)
                continue
            rows, extra, choice_entry = compiled
            for index, row in enumerate(rows):
                generic_reactions[technique_id if index == 0 else f"{technique_id}#{index}"] = {**row, "forged": True}
            resources.extend(extra)
            if choice_entry:
                choosable.append(choice_entry)
            continue
        if economy not in {"action", "bonus_action"}:
            skipped["passive"].append(name)
            continue
        technique_id = str(technique.get("technique_id") or technique.get("record_id") or name)
        mechanic = forged_rules.mechanic_for({**technique, "technique_id": technique_id}, mechanics, forged_table)
        if mechanic is None or not mechanic.get("effects"):
            skipped["not_typed"].append(name)
            continue
        mechanics = {**mechanics, technique_id: mechanic}
        action_id = f"action:typed.{short}.forged.{hashlib.sha256(technique_id.encode('utf-8')).hexdigest()[:12]}"
        target_kind, range_ft = _target_kind(mechanic, numbers.get("cl"))
        cp = int((technique.get("cp_cost") or {}).get("final") or 0)
        pool, choice = _choose_pool(mechanics[mechanic["forged_from"]], action_id, primary, pools, powering) if cp > 0 else (primary, None)
        resource_id = RESOURCE_IDS[pool]
        costs = [(resource_id, cp)] if cp > 0 else []
        if choice:
            choosable.append((action_id, name, choice))
        if any("once per" in str(limit).lower() for limit in technique.get("limits") or []):
            uses = f"resource:uses.{action_id}"
            resources.append(ResourceDefinition(resource_id=uses, initial=1, maximum=1))
            costs.append((uses, 1))
        riders = list(mechanic.get("riders") or [])
        if technique.get("backlash"):
            riders.append(f"Backlash: {technique['backlash']}")
        action_numbers = {**numbers, "potency": potency["bonus_value"]} if potency and cp > 0 and resource_id == potency["resource_id"] else numbers
        typed = {"effects": mechanic["effects"], "riders": riders, "numbers": action_numbers,
                 "weapon": None, "duration": mechanic.get("duration") or {"kind": "instant"},
                 "area": _aimed_area(mechanic, numbers.get("cl")),
                 "range_ft": range_ft, "source": technique_id, "typing_status": mechanic.get("typing_status"),
                 "coverage": mechanic.get("coverage"), "forged_from": mechanic["forged_from"], "base_form": mechanic["base_form"]}
        # Preserve printed ownership/limit provenance for opaque forged action
        # IDs. This is descriptive metadata; the existing fight-use policy and
        # costs above remain authoritative. Old bundles are never recompiled.
        limits = [limit.strip() for limit in technique.get("limits") or []
                  if isinstance(limit, str) and limit.strip()]
        if limits:
            typed["use_limit"] = "; ".join(limits)
        if mechanic.get("weapon_delivery"):
            # A Strike is "weapon or unarmed delivery": without a fitting weapon it is an Unarmed Strike (1 + Strength).
            strength = mods.get("STR", 0)
            typed["unarmed_fallback"] = {"attack_bonus": pb + strength, "weapon": unarmed_strike_weapon(strength)}
        actions.append(ActionDefinition(
            source_definition_id=action_id, display_name=name, owner_id=actor_id,
            economy=EconomyKind.ACTION if economy == "action" else EconomyKind.BONUS_ACTION,
            resolution_kind="TYPED", target_kind=target_kind, range_ft=range_ft,
            radius_ft=(mechanic.get("area") or {}).get("size_ft"), costs=tuple(costs),
            concentration=bool((mechanic.get("duration") or {}).get("concentration")),
            parameters={"typed": typed, "expected_damage": _expected_damage(mechanic["effects"], numbers)},
        ))

    # Immortal Arts: owner_sheet["immortal_arts"] is a list, a single dict, or null (owner 2026-09-26).
    immortal_actions, immortal_reactions, immortal_resources = _compile_immortal_arts(
        owner_sheet, mechanics, actor_id=actor_id, short=short, pb=pb, mods=mods, numbers=numbers, primary=primary,
        pools=pools, potency=potency, skipped=skipped, powering=powering, choosable=choosable)
    actions.extend(immortal_actions)
    resources.extend(immortal_resources)

    # Natural weapons (e.g. Iron Fist): an attack the character always has.
    for row in blocks["passives"]:
        if row["block"] != "natural_weapon":
            continue
        dice, _ = _dice(str(row.get("dice") or "1d4") + " Bludgeoning")
        ability = _attack_ability(row.get("abilities") or ["STR"], sheet=owner_sheet, owned_ids=owned_ids,
                                  mods=mods, source=row["feature_id"], kind="unarmed")
        bonus = mods.get(ability, 0)
        extra_hits = passive_on_hit("unarmed")
        typed = {"effects": [{"type": "attack", "attack_kind": "unarmed", "count": attacks,
                              "on_hit": [{"type": "damage", "weapon_damage": True}, *extra_hits]}],
                 "numbers": {**numbers, "attack_bonus": pb + bonus},
                 "weapon": {"ability": ability, "damage": {"count": dice.count, "sides": dice.sides, "modifier": bonus}, "damage_type": str(row.get("damage_type") or "BLUDGEONING")},
                 "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": row["feature_id"], "attack_action": True}
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.natural.{row['feature_id'].split('.')[-1]}", display_name=f"{row.get('name') or 'Unarmed'} attack",
            owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
            parameters={"typed": typed, "expected_damage": attacks * ((dice.count * (dice.sides + 1)) // 2 + bonus) + on_hit_average(extra_hits)},
        ))

    # The Iron Fist sphere's Unarmed Strike (owner 2026-09-28): the Iron Fist Die by Cultivation Level -- the larger die when
    # both hands are free and no shield is carried -- with Strength or Dexterity, whichever is higher. A Body Refining
    # natural weapon keeps its own attack and takes the larger die ("use the larger die").
    if any(row.get("block") == "opening" for row in blocks["passives"]):
        cl = int(numbers.get("cl") or 1)
        occupied, free = next(((one, two) for top, one, two in ((4, (1, 6), (1, 8)), (10, (1, 8), (1, 10)), (16, (1, 10), (1, 12)), (99, (1, 12), (2, 6)))
                               if cl <= top))
        armed = _carries_shield(kit, owner_items) or bool(weapon_kinds)
        count, sides = occupied if armed else free
        ability = _attack_ability(("STR", "DEX"), sheet=owner_sheet, owned_ids=owned_ids, mods=mods,
                                  source="tianxia.sphere.iron_fist", kind="unarmed")
        natural = next((row for row in actions if ".natural." in row.source_definition_id and row.owner_id == actor_id), None)
        if natural is not None:
            weapon = (natural.parameters.get("typed") or {}).get("weapon") or {}
            damage = weapon.get("damage") or {}
            if count * (sides + 1) > int(damage.get("count") or 1) * (int(damage.get("sides") or 4) + 1):
                typed = {**natural.parameters["typed"], "weapon": {**weapon, "damage": {**damage, "count": count, "sides": sides}}}
                actions[actions.index(natural)] = natural.model_copy(update={"parameters": {**natural.parameters, "typed": typed,
                                                                                          "expected_damage": _expected_damage(typed["effects"], typed["numbers"], weapon=typed.get("weapon"))}})
        else:
            bonus = mods.get(ability, 0)
            extra_hits = passive_on_hit("unarmed")
            typed = {"effects": [{"type": "attack", "attack_kind": "unarmed", "count": attacks, "on_hit": [{"type": "damage", "weapon_damage": True}, *extra_hits]}],
                     "numbers": {**numbers, "attack_bonus": pb + bonus},
                     "weapon": {"ability": ability, "damage": {"count": count, "sides": sides, "modifier": bonus}, "damage_type": "BLUDGEONING"},
                     "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": "tianxia.sphere.iron_fist", "attack_action": True}
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.natural.iron_fist_sphere", display_name="Unarmed Strike (Iron Fist)", owner_id=actor_id,
                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                parameters={"typed": typed, "expected_damage": attacks * ((count * (sides + 1)) // 2 + bonus) + on_hit_average(extra_hits)}))

    # Passives that grant an action of their own (owner 2026-09-28): Step Through Darkness's bonus-action teleport.
    for row in blocks["passives"]:
        if row.get("block") != "granted_action" or not isinstance(row.get("action"), dict):
            continue
        spec = row["action"]
        name = str(spec.get("name") or row.get("name") or "Granted action")
        typed = {"effects": copy.deepcopy(spec.get("effects") or []), "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                 "source": row["feature_id"], **({"teleport_where": spec["teleport_where"]} if spec.get("teleport_where") else {}),
                 **({"requires_inside": spec["requires_inside"]} if spec.get("requires_inside") else {})}
        base_id = f"action:typed.{short}.granted.{row['feature_id'].split('.')[-1].lower()}"
        economy = EconomyKind.BONUS_ACTION if spec.get("economy") == "bonus_action" else EconomyKind.ACTION
        actions.append(ActionDefinition(source_definition_id=base_id, display_name=name, owner_id=actor_id, economy=economy,
                                        resolution_kind="TYPED", target_kind="SELF", range_ft=None,
                                        parameters={"typed": typed, "expected_damage": 0}))
        for augment in spec.get("augments") or []:
            cp = int(augment.get("cp") or 0)
            actions.append(ActionDefinition(
                source_definition_id=f"{base_id}+{str(augment.get('key') or 'augment')}", display_name=f"{name} + {augment.get('name') or 'Augment'}",
                owner_id=actor_id, economy=economy, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
                costs=((RESOURCE_IDS[primary], cp),) if cp else (),
                parameters={"typed": {**typed, "effects": copy.deepcopy(augment.get("effects") or typed["effects"])}, "expected_damage": 0}))
    # Plug-ins' own actions (combat/ext compile_actions, owner 2026-09-28).
    from . import ext

    implemented_action_ids: set[str] = set()
    from .primary_intents import declare_free
    for made in ext.run("compile_actions", {"owner_sheet": owner_sheet, "spheres": spheres, "owned_ids": owned_ids, "mechanics": mechanics,
                                            "passives": blocks["passives"], "numbers": numbers, "short": short, "actor_id": actor_id, "pb": pb,
                                            "mods": mods, "save_proficiencies": _saving_throw_proficiencies(stats),
                                            "primary": primary, "pools": pools, "actions": list(actions),
                                            "weapon_kinds": weapon_kinds, "kit": kit, "owner_items": list(owner_items or [])}):  # actions so far (docket: wall attacks)
        actions.extend(declare_free(made))
        implemented_action_ids.update(action.source_definition_id for action in made)
    # Unmaking's Overdraw (owner 2026-09-28): a free choice, kept until changed, to Overdraw the next time an Unmaking
    # talent deals damage (once a turn; combat/unmaking.py).
    if "tianxia.sphere.unmaking" in spheres:
        for on, label in ((True, "Overdraw: ready"), (False, "Overdraw: no bonus Ruin damage (no self-damage or Black Vein Strain)")):
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.overdraw.{'on' if on else 'off'}", display_name=label, owner_id=actor_id,
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "toggle_overdraw", "on": on}], "numbers": numbers, "duration": {"kind": "instant"},
                                      "riders": []}, "expected_damage": 0, "player_only": True}))
    # Iron Fist's Open the Gate (owner 2026-09-28): which effect an Opening brings, a free choice kept until changed.
    if any(row.get("block") == "opening" for row in blocks["passives"]):
        for choice, label in (("centerline", "Centerline Impact"), ("hooking", "Hooking Step"), ("breath", "Breath-Checking Strike")):
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.open_the_gate.{choice}", display_name=f"Open the Gate: {label}", owner_id=actor_id,
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "open_the_gate", "choice": choice}], "numbers": numbers, "duration": {"kind": "instant"},
                                      "riders": []}, "expected_damage": 0, "player_only": True, "open_the_gate": choice}))
    # Every fighter's basic options (owner 2026-09-26): the opportunity attack (catalog only, used by the reaction),
    # the 2024 unarmed Grapple/Shove, taking a dropped weapon, and improvised weapons.
    opportunity = _opportunity_attack(actions, short, actor_id, numbers, pb, mods)
    # Optional basic actions see all feature actions before the shared modifier/binding passes.
    attack_profiles = {}
    for kind in ("unarmed", "weapon"):
        hits = passive_on_hit(kind)
        attack_profiles[kind] = {"on_hit": hits, "expected_extra_damage": on_hit_average(hits)}
    for made in ext.run("compile_basic_actions", {"actions": list(actions), "short": short, "actor_id": actor_id,
                                                 "owned_ids": owned_ids, "spheres": spheres,
                                                 "numbers": numbers, "pb": pb, "mods": mods,
                                                 "attack_count": attacks, "attack_profiles": attack_profiles}):
        actions.extend(declare_free(made))
        implemented_action_ids.update(action.source_definition_id for action in made)
    actions.extend(_unarmed_options(opportunity, short, actor_id, pb, mods, attacks, shield=_carries_shield(kit, owner_items),
                                    pick_up=str(_weapon_rules().get("pick_up_economy") or "BONUS_ACTION")))
    actions.extend(_improvised_weapon(short, actor_id, numbers, pb, mods, attacks, proficient=_improvised_proficient(owner_sheet, owned_ids)))
    actions.append(ActionDefinition(  # Tianxia Burn: "A creature may use an Action to extinguish one Burn affecting itself or an adjacent creature."
        source_definition_id=f"action:typed.{short}.extinguish", display_name="Extinguish flames", owner_id=actor_id,
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5,
        parameters={"typed": {"effects": [{"type": "remove_condition", "condition": "burning", "applies_to": "target_or_self"}],
                              "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "target_requires_condition": "condition:typed.burning"}))
    # Talents that change the Unarmed Strike or its Grapple and Shove options (owner 2026-09-28: the Iron Fist Form talents
    # found nothing to change -- those actions are built here, after the other abilities' modifiers).
    actions, core_rows = _core_modifier_pass([*actions, opportunity], owned, mechanics, primary, pools, automated=set(blocks["automated"]),
                                             foundation_resource=foundation_resource, actor_id=actor_id, numbers=numbers)
    opportunity = next(a for a in actions if a.source_definition_id == opportunity.source_definition_id)
    actions = [a for a in actions if a.source_definition_id != opportunity.source_definition_id]
    # Existing choice-owner metadata makes the reactor's manual choice visible
    # even when the active creature is controlled by AI.
    paid_owners = {choice["id"]: choice["name"] for action in [*actions, opportunity]
                  for choice in (action.parameters.get("typed") or {}).get("paid_hit_choices") or []}
    blocks["passives"].extend({"feature_id": key, "name": name, "block": "paid_hit", "choice_owner": True}
                              for key, name in paid_owners.items())
    if core_rows:
        by_id = {row["id"]: row for row in core_rows}
        modifier_rows = [(by_id.pop(row["id"]) if row.get("id") in by_id and row.get("status") != "applied" else row) for row in modifier_rows]
        modifier_rows.extend(row for row in by_id.values() if row.get("status") == "applied")
    # Core maneuvers a plug-in builds from the character's weapons and the talents that change them (docket 2026-09-28:
    # Batter, Snipe Shot, Barrage; combat/ext/docket_maneuvers.py), merged like the Unarmed Strike's above.
    from . import ext as _ext

    for made in _ext.run("maneuvers", {"actions": list(actions), "owned": owned, "mechanics": mechanics, "primary": primary, "pools": pools,
                                       "automated": set(blocks["automated"]), "foundation_resource": foundation_resource,
                                       "actor_id": actor_id, "numbers": numbers, "spheres": spheres}):
        actions.extend(declare_free(made.get("actions") or []))
        implemented_action_ids.update(action.source_definition_id for action in made.get("actions") or [])
        replaced = {row["id"] for row in made.get("rows") or [] if row.get("status") == "applied"}  # its rows replace the ones that found nothing
        modifier_rows = [row for row in modifier_rows if row.get("id") not in replaced or row.get("status") == "applied"]
        modifier_rows.extend(row for row in made.get("rows") or [] if row.get("status") == "applied")
    # Talents whose own delivery is a weapon attack (owner 2026-09-27 playtest: Hewing Strike "did nothing").
    actions = _deliver_with_weapons(actions, weapon_kinds, mechanics, diagnostics)
    actions = _bind_unarmed_strikes(actions)
    actions = _weapon_dice(actions, weapon_kinds, mechanics)
    # Areas an ability leaves on the map, and the talents that change them (owner 2026-09-27: Ashfall "had nothing
    # under it"; "we need a visual layer to show terrain effects").
    actions = _zone_abilities(actions, mechanics, owned_ids, authority.get("sphere_names") or {},
                              lambda mechanic_id, action_id: _costs(mechanics[mechanic_id], primary, pb, action_id, diagnostics, pools, powering,
                                                                    foundation_resource=foundation_resource)[0],
                              RESOURCE_IDS.get(primary, "resource:core.qi"))
    # Summoned creatures and companions (owner 2026-09-27, combat/summons.py): the ability that calls one now summons it
    # (it used to run the creature's own statistics on the summoner -- Ghost Lantern's AC 14 as a bonus, Painted Beast's
    # Ink Fang as Ning Kai's attack), and a commanded group gets its "Command" Bonus Action.
    from . import summons as summon_rules

    creatures, summoning = summon_rules.compile_summons(owned_ids, mechanics, owner_id=actor_id, short=short, numbers=numbers, pb=pb,
                                                        cl=int(numbers.get("cl") or 1), plan=summon_plan, mods=mods,
                                                        reaction_ask=bool((reaction_plan or {}).get("ask")),
                                                        owner_saves=_saving_throw_modifiers(stats, mods))
    summon_options = summoning.pop("_options")
    creature_value = {row["summon"]["group"]: int(row["summon"]["expected_damage"]) for row in creatures}
    for index, row in enumerate(actions):
        typed = row.parameters.get("typed")
        called = summoning.get(str((typed or {}).get("option_of") or (typed or {}).get("source") or "")) if isinstance(typed, dict) else None
        if isinstance(typed, dict) and typed.get("option_of") and typed.get("option_label"):
            # One form of a "Choose one" summon (Living Painting: Tiger, Crane ...): the source is keyed "<ability>#<form>".
            called = summoning.get(f"{typed['option_of']}#{str(typed['option_label']).lower()}") or called
        if row.resolution_kind != "TYPED" or called is None:
            continue
        typed = {**typed, "effects": [{"type": "summon", "group": called["group"]}], "area": None, "range_ft": None,
                 "duration": {**(typed.get("duration") or {"kind": "instant"}), "concentration": called["concentration"]}}
        value = creature_value.get(called["group"], 0)
        # Opt-in printed "choose an unoccupied space you can see": reuse the
        # general CELL placement contract for any single-creature summon.
        # Missing metadata preserves the historical SELF placement catalogue.
        placement = "placement_range_ft" in called
        # Worth a few of its attacks to the AI; one with no attack (the Ghost Lantern) is left to a player.
        actions[index] = row.model_copy(update={"target_kind": "CELL" if placement else "SELF",
                                                "range_ft": called["placement_range_ft"] if placement else None,
                                                "radius_ft": None, "concentration": called["concentration"],
                                                "parameters": {**row.parameters, "typed": typed, "summon_group": called["group"],
                                                               **({"cell_placement": {}} if placement else {}),
                                                               "expected_damage": value * 2, **({} if value else {"inert": True})}})
    for command in summon_rules.owner_actions(creatures, owner_id=actor_id, short=short, numbers=numbers):
        actions.append(command if command.parameters["expected_damage"] else
                       command.model_copy(update={"parameters": {**command.parameters, "inert": True}}))
    for row in actions:
        # Owner 2026-09-26 (step 11): an ability combat runs nothing for (Talisman Recall's bare save, Qi Sensing's
        # text) is kept off the AI's menu (combat/gate4_context.py); a player still sees and can use it.
        typed = row.parameters.get("typed")
        if row.resolution_kind == "TYPED" and isinstance(typed, dict) and typed.get("weapon") is None and not _does_something(typed.get("effects")) \
                and not typed.get("zone_spec"):  # an area left on the map does something (owner 2026-09-27)
            row.parameters["inert"] = True
            # Its text for the log when it is used (owner 2026-09-28: "when i click them nothing happens"): the GM
            # resolves it, and the table shows that the use happened.
            # General display seam for every manual ability: complete builder
            # prose, not the shortened source excerpt used for classification.
            # Keep _gm_text's build-choice use below on the original rules.
            from .player_text import plain as player_prose
            typed["gm_text"] = player_prose(_rules_text().get(str(typed.get("option_of") or typed.get("source") or "")))
        if isinstance(typed, dict) and (mechanics.get(str(typed.get("option_of") or typed.get("source") or "")) or {}).get("requires_hearing"):
            typed["requires_hearing"] = True  # Deafened (2024): its targets must hear the user
    carrying = _carrying(identity, kit, owner_items or [], scores.get("STR", 10), armor_choice_ac, mods,
                         armour.carried_note(armor_choice_ac, kit, mods))
    # Source-gated construction grants can scale carrying capacity before the
    # ordinary encumbrance decision. Saved bundles retain their sealed capacity.
    for scale in ext.run_strict("carrying_capacity_scale", {"owned_ids": owned_ids, "numbers": numbers,
                                                          "owner_sheet": owner_sheet}):
        if type(scale) is not int or scale < 1:
            raise ValueError("carrying_capacity_scale requires a positive integer or None")
        carrying["capacity_lb"] *= scale
        carrying["over"] = float(carrying["weight_lb"]) > carrying["capacity_lb"]
    carrying["attunement"] = {"used": attuning["used"], "max": attuning["max"], "attuned": attuning["attuned"]}
    for item in carrying["items"]:
        if item.get("attunement_slots"):
            item["attuned"] = item["key"] in attuning["attuned"]
    speed_ft = int((_json(stats.get("speed")) or {}).get("walking_ft") or 30)
    # 2024: falling short of the worn armour's Strength requirement costs 10 feet of Speed, not AC.  It is a property of
    # what the character wears, so it is in the compiled bundle the sheet and the fight both read.  Armour carried
    # rather than worn asks for no Strength at all.
    strength_penalty = armour.speed_penalty_ft(kit, scores.get("STR", 10), armor_choice_ac, mods)
    if strength_penalty:
        speed_ft = max(0, speed_ft - strength_penalty)
        diagnostics.append(f"Armour needs more Strength than this character has: Speed -{strength_penalty} ft")
    carrying["speed_ft"] = speed_ft  # unburdened; the template below is 5 when over capacity (combat/carry.py corrects it in a fight)
    by_id = {row.source_definition_id: row for row in actions}
    for item in carrying["items"]:
        # Items in a fight (owner 2026-09-27: "Dropping things should also be an option"; "we should have encumberance
        # update with the state of the time"): Drop is free (2024); a dropped weapon is disarmed until picked up again
        # (its own Pick up), anything else has its own Pick up. Worn armour is not dropped in a fight.
        if item["worn"]:
            continue
        attack = next((entry["owner_action"] for entry in own_weapon_actions
                       if entry["row"]["inventory_key"] == item["key"]
                       and by_id[entry["owner_action"]].parameters["typed"].get("inventory_key") == item["key"]), None)
        if attack is None:
            suffix = item["item_id"].split(".")[-1]
            attack = f"action:typed.{short}.weapon.{suffix}" + (".treasure" if item["key"] == "treasure_weapon" else "")
        if attack in by_id:
            item["weapon_action"] = attack
        key = hashlib.sha256(item["key"].encode("utf-8")).hexdigest()[:10]
        effect = {"type": "drop_item", "item": item["key"]}
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.item_drop.{key}", display_name=f"Drop {item['name']}", owner_id=actor_id,
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"effects": [effect], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "item_action": "drop", "item_key": item["key"], "free_primary": True},
        ))
        if not item.get("weapon_action"):
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.item_pickup.{key}", display_name=f"Pick up {item['name']}", owner_id=actor_id,
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"typed": {"effects": [{"type": "pickup_item", "item": item["key"]}], "numbers": numbers,
                                      "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "item_action": "pickup", "item_key": item["key"], "free_primary": True},
            ))
    # The Hide and Search actions (owner 2026-09-27: "i dont see a way to do a stealth check"; combat/stealth.py).
    stealth_bonus, perception_bonus = _skill_bonus(owner_sheet, "Stealth", mods.get("DEX", 0)), _skill_bonus(owner_sheet, "Perception", mods.get("WIS", 0))
    # Hide in Darkness: "While the target stands inside an area of your Darkness, it may take the Hide action even while
    # clearly visible" (owner 2026-09-27: "in pitch dark with pure darkness and hide in darkness hiding shouldnt be a problem").
    hide_inside = next((match.group(1) for talent in owned_ids for match in
                        [re.search(r"inside an area of your ([\w' -]+?), it may take the Hide action", _rules_text().get(talent) or "", re.I)] if match), None)
    for key, name, effect in (
        ("hide", "Hide", {"type": "hide", "bonus": stealth_bonus, **({"mode": "DISADVANTAGE"} if carrying.get("stealth_disadvantage") else {}),
                          **({"inside": hide_inside} if hide_inside else {})}),
        ("search", "Search", {"type": "search", "bonus": perception_bonus}),
    ):
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"effects": [effect], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True, "stealth": key, "basic": True,
                        **({"hide_inside": hide_inside} if key == "hide" and hide_inside else {})}))
    # Same immutable action-transform contract used by the newer rider lanes.
    for index, action in enumerate(actions):
        actions[index] = ext.transform("compile_action", action, {"owner_sheet": owner_sheet, "owned_ids": owned_ids,
                                    "numbers": numbers, "mods": mods, "pb": pb, "carrying": carrying, "mechanics": mechanics})
    from .ext.attack_modifiers import settings as attack_modifier_settings
    actions = attack_modifier_settings(actions)
    from .action_publication import has_resolution
    publication_info = {"owner_sheet": owner_sheet, "owned_ids": owned_ids, "mechanics": mechanics,
                        "actor_id": actor_id, "implemented_action_ids": implemented_action_ids}
    publication_statuses = feature_status()
    actions = [action for action in actions if has_resolution(action, publication_statuses, publication_info)]
    actions.sort(key=lambda row: row.source_definition_id)
    if carrying["over"]:
        # 2024 Carrying Capacity (owner 2026-09-26, "we should probably do that as well"): past it, Speed is at most 5 feet.
        speed_ft = min(speed_ft, 5)
        diagnostics.append(f"Carrying {carrying['weight_lb']} lb, over the {carrying['capacity_lb']} lb capacity: Speed 5 ft")
    carrying["template_speed_ft"] = speed_ft
    # A limited modifier's variant (apply_modifiers here, in the core pass, or in a plug-in) spends its counter far from
    # where _costs declares the others: every use counter an action spends exists, once.
    declared = {row.resource_id for row in resources}
    # Plug-ins' own pools (combat/ext compile_resources; rider lane 9: Talismans' Prepared Talisman Limit). A named pool the
    # typed rows declared is sized by the plug-in that owns its printed size (rider lane C10: Reagent Stock's prepared uses).
    named_ids = {row["resource_id"] for row in named_pools}
    for made in ext.run("compile_resources", {"owned_ids": owned_ids, "spheres": spheres, "numbers": numbers, "mods": mods, "pb": pb, "owner_sheet": owner_sheet}):
        for row in made:
            if row.resource_id not in declared:
                declared.add(row.resource_id)
                resources.append(row)
            elif row.resource_id in named_ids:
                resources = [row if old.resource_id == row.resource_id else old for old in resources]
    for action in actions:
        typed = action.parameters.get('typed')
        record = mechanics.get((typed or {}).get('source'), {})
        target = record.get('target')
        # Reviewed rows support both a plain target phrase and a structured one.
        target_text = str((target.get('text') if isinstance(target, dict) else target) or '')
        if typed is not None and 'you can see' in ' '.join(target_text.lower().split()):
            typed['requires_seen_target'] = True
        for resource_id, _amount in action.costs:
            if resource_id.startswith("resource:uses.") and resource_id not in declared:
                declared.add(resource_id)
                resources.append(_use_counter(resource_id))
    from .ext import target_limits

    resources = target_limits.per_target_counters(resources, mechanics)  # "once per creature per rest": the limit is kept per creature
    resources = ext.transform("compile_resource_definitions", resources, {
        "owner_sheet": owner_sheet, "owned_ids": owned_ids, "numbers": numbers,
        "mechanics": mechanics, "pb": pb})
    from .dynamic_size import category_name
    armor_terms: list[dict[str, Any]] = []
    # General equipment-bonus policy: quote once so AC and its passive receipt agree.
    shield_ac = armour.shield_ac_bonus(kit, owner_items)
    shield_ac = ext.transform('compile_shield_bonus', shield_ac,
        {'owner_sheet': owner_sheet, 'owned_ids': owned_ids, 'kit': kit, 'owner_items': owner_items})
    if type(shield_ac) is not int or shield_ac < 0:
        raise ValueError('compile_shield_bonus requires a nonnegative integer')
    # Cones never get an "include the cone's starting space" alternative: every cone starts on its user, so that
    # choice only meant hitting yourself (owner 2026-10-18: "theres no way anyone will want to hit themselves").
    # General final composition seam: providers see native and plug-in actions,
    # after target variants, before action IDs and the bundle hash are sealed.
    for made in ext.run("compose_actions", {"owner_sheet": owner_sheet, "owned_ids": owned_ids,
            "spheres": spheres, "passives": blocks["passives"], "actor_id": actor_id,
            "actions": list(actions)}):
        actions.extend(declare_free(made))
    from .ai_tiers import tier_for_sheet
    template = ActorTemplate(
        ai_tier=tier_for_sheet(owner_sheet),
        entity_id=actor_id, display_name=str(identity.get("name") or identity.get("display_name") or "Factory character"),
        creature_types=printed_creature_types(identity),
        team_id="team:factory", primary_combatant=True,
        # Dual Wielding's Twin-Weapon Training, Balanced Defense: +1 AC with a pair of one-handed melee weapons, no shield.
        armor_class=armour.armor_class(base_ac, kit, mods, diagnostics=diagnostics, owner_items=owner_items,
                                      always_on=always_on_ac, choice_ac=armor_choice_ac, calculations=alternate_ac, breakdown=armor_terms, shield_override=shield_ac) + (1 if "TAL_DUAL_WIELDING_TWIN_WEAPON_TRAINING" in ids
                                                                   and _qualifying_pair(weapons[:own_count], pairable) and not _carries_shield(kit, owner_items) else 0),
        maximum_hp=_maximum_hp(stats, diagnostics), speed_ft=speed_ft,
        initiative_bonus=int((_json(stats.get("initiative")) or {}).get("bonus") or mods.get("DEX", 0)),
        dexterity_score=scores.get("DEX", 10), proficiency_bonus=pb,
        strength_score=scores.get("STR", 10),
        size_category=category_name(identity.get("size")),
        saving_throws=_saving_throw_modifiers(stats, mods),
        resources=tuple(resources), action_ids=tuple(row.source_definition_id for row in actions), reaction_ids=(),
    )
    # Plug-ins that deliver a complete trigger (including its optional payment)
    # claim that feature explicitly; an inert typed marker must not pay again.
    claimed_triggers = {row["feature_id"] for row in blocks["passives"]
                        if isinstance(row.get("trigger_owner"), str) and row["trigger_owner"]}
    unclaimed_reactions = [row for row in generic_reactions.values() if row["feature_id"] not in claimed_triggers]
    reactions, reaction_plan = _reaction_plan([*blocks["reactions"], *unclaimed_reactions, *immortal_reactions.values(),
                                               {"feature_id": "opportunity_attack", "name": "Opportunity Attack", "block": "opportunity",
                                                "resource_id": "", "action_id": opportunity.source_definition_id,
                                                "reach_ft": int(opportunity.range_ft or 5)}],
                                              reaction_plan or ({"hold": reaction_hold} if reaction_hold else None), mechanics)
    # Value the delivered effects after weapon binding, variants and extension
    # transforms. Saved bundles are deserialized by register_bundle unchanged;
    # this hint is published only when a character is freshly compiled.
    actions = [_with_rider_utility(action) for action in actions]
    opportunity = ext.transform("compile_reaction_action", opportunity,
        {"owner_sheet": owner_sheet, "owned_ids": owned_ids, "numbers": numbers,
         "mods": mods, "pb": pb, "carrying": carrying, "mechanics": mechanics})
    opportunity = _with_rider_utility(opportunity)

    # How far the fight table actually got with each Insight this character owns.
    # Names, not ids: the sheet library shows these to a player.
    _insight_applied: dict[str, list[str]] = {}
    for row in [*blocks["passives"], *reactions]:
        feature_id = row.get("feature_id")
        if isinstance(feature_id, str) and feature_id.startswith("insight.") and feature_id in insight_boundaries:
            _insight_applied.setdefault(feature_id, []).append(
                _insight_grant_label(row, str(insight_boundaries[feature_id]["name"])))
    for row in actions:
        source = str(((row.parameters or {}).get("typed") or {}).get("source") or "")
        owner = next((key for key in insight_boundaries if source == key or source.startswith(key + "#")), "")
        if owner:
            _insight_applied.setdefault(owner, []).append(_insight_action_label(row))
    for row in modifier_rows:
        feature_id = str(row.get("id") or "")
        if feature_id.startswith("insight.") and feature_id in insight_boundaries and row.get("status") == "applied":
            _insight_applied.setdefault(feature_id, []).append(_insight_modifier_label(
                row, str(insight_boundaries[feature_id]["name"]),
                (mechanics.get(feature_id) or {}).get("modifier")))
    insights = _insight_boundaries(insight_boundaries, _insight_applied)
    from .ability_checks import skill_proficiency_ranks

    skill_ranks = skill_proficiency_ranks(_json((owner_sheet.get("ability_scores_and_statistics") or {}).get("skills")) or [])
    bundle = {
        "schema": SCHEMA,
        "actor_id": actor_id,
        "typed_authority_sha256": authority_sha256,
        "actor_template": template.model_dump(mode="json"),
        # Optional display provenance; register_bundle and saved fights ignore it.
        "armor_terms": armor_terms + ([{"source": "other compiled standing bonuses", "value": template.armor_class - sum(row["value"] for row in armor_terms)}]
                                       if template.armor_class != sum(row["value"] for row in armor_terms) else []),
        # The opportunity attack is in the catalog but not among the actor's actions: only the reaction uses it.
        "action_catalog": [row.model_dump(mode="json") for row in [*actions, opportunity]],
        # "insights" is present only for a character that owns one, so a fight without
        # an Insight keeps the byte-identical diagnostics it had before.
        "diagnostics": {"skipped": _sorted_skipped(skipped, actions, owned_ids, mechanics), "notes": diagnostics,
                        **({"insights": insights} if insights else {})},
        "carrying": carrying,
        # Generic roll provenance: explicit sheet/compiled Expertise ranks only.
        # Omitted for legacy totals; consumers must not guess from skill bonuses.
        **({"skill_proficiency": skill_ranks} if skill_ranks else {}),
        # Its skill bonuses as the sheet lists them (owner 2026-09-28: a Scoundrel Check is Sleight of Hand, opposed by
        # Athletics or Acrobatics); the sealed engine's fighters carry saving throws only. Read by combat/ext plug-ins.
        **({"skills": skills_} if (skills_ := {str(row.get("skill")): int(row["bonus"]) for row in (_json((owner_sheet.get("ability_scores_and_statistics") or {}).get("skills")) or [])
                                              if isinstance(row, dict) and row.get("skill") and isinstance(row.get("bonus"), int)}) else {}),
        # Clearsight (owner 2026-09-27): "immune to negative effects created by your Darkness talents" -- the kinds of area
        # whose talents do not touch this character when they are its own (combat/zones.py).
        **({"clearsight": sorted({match.group(1) for talent in owned_ids for match in
                                  [re.search(r"immune to negative effects created by your ([\w' -]+?) talents", _rules_text().get(talent) or "", re.I)] if match})}
           if any(re.search(r"immune to negative effects created by your", _rules_text().get(talent) or "", re.I) for talent in owned_ids) else {}),
        # Its senses (docket 2026-09-28, combat/senses.py): Darkvision, Blindsight, Tremorsense, Truesight and the spheres'
        # own (Bloodsense, Qi Sensing, Spiritual Sense), from the records it owns (combat/rules/senses.json), and its Melds.
        **({"senses": senses_} if (senses_ := _senses.compile_grants(owned_ids, int(numbers.get("cl") or 1))) else {}),
        "modifiers": [{**row, "status": "applied", "applied": row.get("applied") or ["the weapon pairing"]}
                      if row.get("id") in HANDLED_IN_CODE and row.get("status") != "applied" else row for row in modifier_rows],
        "typed_reactions": reactions,
        "reaction_plan": reaction_plan,
        # Its summoned creatures and companions, each a fighter of its own (combat/summons.py).
        "summons": creatures,
        "summon_options": summon_options,
        # "You can maintain a number of Rising Marks equal to your Proficiency Bonus" (step 8, owner 2026-09-26): each
        # capped mark's limit, enforced by typed_executor.block_mark (the oldest one ends).
        # A carried shield is a fact about the fighter (its +2 AC is inside the AC number): "cannot benefit from Shield AC" needs it
        # (combat/ext/guard_broken.py).
        "typed_passives": [*blocks["passives"], *([{"feature_id": "shield_ac", "block": "shield_ac", "amount": shield_ac}] if _carries_shield(kit, owner_items) else []),
                           {"feature_id": "mark_caps", "block": "mark_caps", "caps": {
            str(row["name"]).lower(): (pb if str(row.get("max")).lower() == "pb" else int(row["max"]))
            for row in (authority.get("resources") or {}).values()
            if row.get("kind") == "mark" and str(row.get("max") or "none").lower() not in ("none", "") and (str(row.get("max")).lower() == "pb" or str(row.get("max")).isdigit())}}],
        # Its own weapons, for the other fighters in a fight to compile as weapons they might take (held_weapons).
        "weapons": own_weapon_actions,
        # Which Path pool pays each choosable ability (owner 2026-09-25, Q19); empty "choices" for a
        # single-Path character, since there is nothing to choose.
        "powering": {"pools": [name.capitalize() for name in pools],
                    "choices": {action_id: {"name": name, "pool": pool.capitalize()} for action_id, name, pool in choosable}},
    }
    # Buffs it may have cast before a fight (owner 2026-09-29, combat/prefight.py): the options, and none picked; a fight
    # made by the combat service picks them (the player's, or the AI's best two).
    from . import prefight

    bundle["prefight"] = {"options": prefight.options(actions, actor_id),
                          "picks": [], "chosen": False}
    # Its Cultivation Level also supplies the explicitly configured legacy concentration ceiling.
    bundle["cl"] = int(numbers.get("cl") or 1)
    # Seal the general concentration capacity contract alongside this character;
    # subsequent rules edits must not change old saved fights' admission/replay.
    from . import concentration

    bundle["concentration_rules"] = {"capacity": str(concentration.rules().get("capacity") or "cultivation_level"),
                                     "limits_by_cl": copy.deepcopy(concentration.rules().get("limits_by_cl") or [[1, 1]])}
    bundle = ext.transform("compile_bundle", bundle, {
        "owner_sheet": owner_sheet, "kit": kit, "owner_items": list(owner_items or []),
        "numbers": numbers, "actor_id": actor_id, "primary": primary, "mechanics": mechanics,
        "owned_ids": owned_ids, "mods": mods})
    if admission_ids:
        bundle["source_acquisitions"] = copy.deepcopy(owner_sheet["combat_acquisitions"])
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


_FAMILY_WORDS = {"greatblade": ("greatsword", "great", "zhan ma dao", "da dao"), "axe": ("axe",),
                 "bow": ("bow",), "sword": ("sword", "jian"), "saber": ("saber", "dao"), "spear": ("spear", "qiang"), "staff": ("staff", "gun")}


def _fits(weapon: dict[str, Any], delivery: dict[str, Any]) -> bool:
    kind = delivery.get("kind") or "any"
    if kind == "melee" and not weapon["melee"] or kind == "ranged" and not weapon["ranged"] or kind == "thrown" and not weapon["thrown"]:
        return False
    family = delivery.get("family")
    if not family:
        return True
    # Source-defined families are not proficiency-name substrings. Providers
    # receive the authoritative item, never the possibly renamed action label.
    from factory_authoring.starting_kits import item_definition
    from . import ext
    item = item_definition(str(weapon.get("item_id") or ""))
    answers = ext.run_strict("weapon_source_family", item, family)
    if any(type(answer) is not bool for answer in answers):
        raise ValueError("weapon_source_family must return bool or None")
    if answers:
        return any(answers)
    name = weapon["name"].lower()
    return any(word in name for word in _FAMILY_WORDS.get(family, (family,)))


def _deliver_with_weapons(actions: list[ActionDefinition], weapon_kinds: list[dict[str, Any]], mechanics: dict[str, Any],
                          diagnostics: list[str]) -> list[ActionDefinition]:
    """A talent whose own delivery is a weapon attack ("Make a melee weapon attack with an axe weapon. On a hit, the
    attack deals its normal weapon damage", factory_authoring.typed_structure.weapon_delivery) attacks with the
    character's best fitting weapon: that weapon's attack bonus, damage, enchantments, mastery and reach, plus the
    talent's own on-hit effects. A Special Attack ("Parent Action: Attack") is one more way to make that weapon's
    Attack action: every attack of it (Extra Attack) with the talent's rider on the first hit. Without a fitting
    weapon the talent cannot be used, and is left off the menu."""
    by_id = {row.source_definition_id: row for row in actions}
    out = []
    for row in actions:
        typed = row.parameters.get("typed")
        mechanic = mechanics.get(str((typed or {}).get("option_of") or (typed or {}).get("source") or "")) if isinstance(typed, dict) else None
        delivery = (mechanic or {}).get("weapon_delivery") or ((mechanic or {}).get("range") or {}).get("weapon_delivery")
        if not delivery or typed.get("weapon") is not None or row.resolution_kind != "TYPED":
            out.append(row)
            continue
        # A thrown (or ranged) delivery with a melee weapon that can be thrown uses the weapon's thrown attack.
        thrown = delivery.get("kind") in ("thrown", "ranged")
        fitting = [by_id.get(f"{weapon['action_id']}#thrown") if thrown and weapon["melee"] and f"{weapon['action_id']}#thrown" in by_id
                   else by_id[weapon["action_id"]] for weapon in weapon_kinds if weapon["action_id"] in by_id and _fits(weapon, delivery)]
        if not fitting and typed.get("unarmed_fallback"):
            fallback = typed["unarmed_fallback"]
            effects = [{**effect, "attack_kind": "unarmed", "on_hit": [{"type": "damage", "weapon_damage": True}, *(effect.get("on_hit") or [])]}
                       if isinstance(effect, dict) and effect.get("type") == "attack" else effect for effect in typed.get("effects") or []]
            out.append(row.model_copy(update={"target_kind": "HOSTILE_ENTITY", "range_ft": 5, "radius_ft": None, "parameters": {
                **row.parameters, "typed": {**typed, "effects": effects, "weapon": copy.deepcopy(fallback["weapon"]),
                                            "numbers": {**(typed.get("numbers") or {}), "attack_bonus": fallback["attack_bonus"]}},
                "expected_damage": int(row.parameters.get("expected_damage") or 0) + int(fallback["weapon"]["fixed_damage"])}}))
            continue
        if not fitting:
            wanted = " ".join(part for part in (delivery.get("family"), delivery.get("kind") if delivery.get("kind") != "any" else None) if part)
            diagnostics.append(f"{row.display_name}: needs {'an' if (wanted or 'a')[0] in 'aeiou' else 'a'} {wanted or 'fitting'} weapon")
            continue
        base = max(fitting, key=lambda weapon: (int(weapon.parameters.get("expected_damage") or 0), weapon.source_definition_id))
        base_typed = base.parameters["typed"]
        base_attack = base_typed["effects"][0]
        weapon_hits = [hit for hit in base_attack.get("on_hit") or []]
        special = bool(delivery.get("special_attack"))
        effects = []
        for effect in typed.get("effects") or []:
            if not (isinstance(effect, dict) and effect.get("type") == "attack"):
                effects.append(effect)
                continue
            # The weapon deals its damage; the talent's own weapon-damage restatement is dropped, its extra dice kept.
            own = [hit for hit in effect.get("on_hit") or [] if isinstance(hit, dict)
                   and not (hit.get("type") == "damage" and (hit.get("weapon_damage") or not (hit.get("dice") or hit.get("dice_by_cl"))))]
            # A talent whose own on-hit already states a real replacement damage amount (Close Haft Strike's
            # "1d4 + ability modifier bludgeoning", not the weapon's own dice) means the printed text is not
            # "normal weapon damage, then X": drop the weapon's own flat damage hit so the two don't both land
            # (owner martial 2026-09-28; the weapon's other on-hit effects -- enchantments, mastery -- still ride).
            if any(isinstance(hit, dict) and hit.get("type") == "damage" and (hit.get("dice") or hit.get("dice_by_cl") or hit.get("flat"))
                   for hit in own):
                weapon_hits = [hit for hit in weapon_hits if not (isinstance(hit, dict) and hit.get("type") == "damage" and hit.get("weapon_damage"))]
            if special:
                own = [{**hit, "first_hit_only": True} for hit in own]
            effects.append({**effect, "attack_kind": "weapon", "count": int(base_attack.get("count") or 1) if special else int(effect.get("count") or 1),
                            "on_hit": [*copy.deepcopy(weapon_hits), *own],
                            **({"on_miss": copy.deepcopy(base_attack["on_miss"])} if base_attack.get("on_miss") else {})})
        new_typed = {**typed, "effects": effects, "weapon": copy.deepcopy(base_typed["weapon"]),
                     "numbers": {**(typed.get("numbers") or {}), "attack_bonus": int(base_typed["numbers"]["attack_bonus"]),
                                 "save_dc": int((typed.get("numbers") or {}).get("save_dc") or base_typed["numbers"].get("save_dc") or 10)},
                     "range_ft": base_typed.get("range_ft"), "long_range_ft": base_typed.get("long_range_ft"),
                     "mastery": base_typed.get("mastery"), "mundane": base_typed.get("mundane"), "delivered_by": base.source_definition_id}
        per_attack = int(base.parameters.get("expected_damage") or 0) // max(1, int(base_attack.get("count") or 1))
        from .ext.weapon_actions import delivery_range_ft
        delivery_range = delivery_range_ft(base)
        if (mechanic.get("range") or {}).get("overrides_weapon"):
            # A reviewed technique can print a shorter normal/long range than its delivering weapon.
            normal = int(mechanic["range"]["feet"])
            delivery_range = int(mechanic["range"].get("long_feet") or normal)
            new_typed.update(range_ft=normal, long_range_ft=delivery_range)
        count = sum(int(effect.get("count") or 1) for effect in effects if effect.get("type") == "attack") or 1
        out.append(row.model_copy(update={
            "display_name": f"{base.display_name}: {row.display_name}" if special else row.display_name,
            "target_kind": "HOSTILE_ENTITY", "range_ft": delivery_range, "radius_ft": None,
            "parameters": {**row.parameters, "typed": new_typed, "expected_damage": per_attack * count + int(row.parameters.get("expected_damage") or 0)}}))
    return out


def _bind_unarmed_strikes(actions: list[ActionDefinition]) -> list[ActionDefinition]:
    """Explicitly reviewed special Unarmed Strikes use the fighter's own natural attack.

    The ordinary weapon-delivery pass cannot select a natural attack. Reuse its compiled
    dice and attack bonus, including Iron Fist's level and occupied-hand rules.
    """
    natural = next((row for row in actions if ".natural." in row.source_definition_id
                    and (row.parameters.get("typed") or {}).get("weapon")
                    and not (row.parameters["typed"].get("modifier") or row.parameters["typed"].get("variant_of"))), None)
    if natural is None:
        return actions
    base = natural.parameters["typed"]
    result = []
    for row in actions:
        typed = row.parameters.get("typed") or {}
        if not any(effect.get("strike_with") == "unarmed" for effect in typed.get("effects") or []):
            result.append(row)
            continue
        typed = {**typed, "weapon": copy.deepcopy(base["weapon"]),
                 "numbers": {**typed["numbers"], "attack_bonus": base["numbers"]["attack_bonus"]}}
        result.append(row.model_copy(update={"parameters": {**row.parameters, "typed": typed}}))
    return result


def _weapon_dice(actions: list[ActionDefinition], weapon_kinds: list[dict[str, Any]], mechanics: dict[str, Any]) -> list[ActionDefinition]:
    """An ability that prints its damage in "weapon damage dice" ("ten weapon damage dice plus twice your ability modifier":
    Barrage's Heaven-Splitting Line, Hundred-Arrow Passage, Needle-Rain Burst, Ten-Thousand Projectile Rain, One Arrow
    Becomes Ten Thousand): the authority carries the printed dice count with ``dice.weapon``, and the die size and the damage
    type come from the weapon that ability is made with -- the weapon a weapon attack was delivered with, else the biggest
    ranged or thrown weapon the character carries (sweep sw-athletics: they had rolled no dice at all). With no such weapon
    the authority's own die size stands. A burst printed with "Range: Weapon range" is aimed within that weapon's range
    instead of being centred on the user.

    An ability that names its weapon ("one Bow weapon damage die", "the normal weapon damage die of each weapon in your Qualifying
    Pair") types ``dice.weapon_group`` next to ``dice.weapon``: a weapon-proficiency group of combat/rules/weapon_specials
    ("bow", "polearm", ...), ``melee`` for any melee weapon (a Draw Weapon, which the sheet does not record), or ``pair`` for the
    Qualifying Pair (the smaller of its two biggest dice when they differ, so the roll is never more than printed)."""
    by_id = {row.source_definition_id: row for row in actions}
    groups = (_weapon_rules().get("proficiency") or {}).get("groups") or {}

    def biggest(kinds: list[dict[str, Any]], *, thrown: bool) -> list[ActionDefinition]:
        """The attack rows of these weapons, the biggest die first (a melee weapon that can be thrown counts as its thrown attack)."""
        rows = []
        for kind in kinds:
            row = (by_id.get(f"{kind['action_id']}#thrown") if thrown and kind["thrown"] and kind["melee"] else None) or by_id.get(kind["action_id"])
            if row is not None and ((row.parameters.get("typed") or {}).get("weapon") or {}).get("damage", {}).get("sides"):
                rows.append(row)
        return sorted(rows, key=lambda row: (int(row.parameters["typed"]["weapon"]["damage"]["sides"]),
                                             int(row.parameters["typed"]["weapon"]["damage"].get("count") or 1)), reverse=True)

    best = next(iter(biggest([kind for kind in weapon_kinds if kind["ranged"] or kind["thrown"]], thrown=True)), None)
    grouped: dict[str, dict[str, Any] | None] = {}

    def weapon_of(group: Any) -> dict[str, Any] | None:
        """The weapon a ``dice.weapon`` is rolled with: the one named by its group, else the biggest ranged or thrown weapon."""
        if not group:
            return best.parameters["typed"]["weapon"] if best else None
        if str(group) not in grouped:
            members = [kind for kind in weapon_kinds if (kind["melee"] if group == "melee" else kind.get("pairable") if group == "pair"
                                                         else kind["item_id"].split(".")[-1] in groups.get(str(group), ()))]
            rows = biggest(members, thrown=False)
            weapon = copy.deepcopy(rows[0].parameters["typed"]["weapon"]) if rows else None
            if weapon and group == "pair":  # one die of each weapon, added: the pair's smaller die for both when they differ
                weapon["damage"]["sides"] = int(rows[min(1, len(rows) - 1)].parameters["typed"]["weapon"]["damage"]["sides"])
            grouped[str(group)] = weapon
        return grouped[str(group)]

    out = []
    for row in actions:
        typed = row.parameters.get("typed")
        if row.resolution_kind != "TYPED" or not isinstance(typed, dict) or not any(
                isinstance(effect.get("dice"), dict) and effect["dice"].get("weapon") for effect in _walk(typed.get("effects") or [])):
            out.append(row)
            continue
        typed = copy.deepcopy(typed)
        before = _expected_damage(row.parameters["typed"]["effects"], typed.get("numbers") or {}, weapon=row.parameters["typed"].get("weapon"))
        for effect in _walk(typed["effects"]):
            dice = effect.get("dice")
            if not (isinstance(dice, dict) and dice.get("weapon")):
                continue
            weapon = typed.get("weapon") or weapon_of(dice.get("weapon_group"))
            if (weapon or {}).get("damage", {}).get("sides"):
                dice["sides"] = int(weapon["damage"]["sides"])
                if not effect.get("damage_types"):
                    effect["damage_types"] = list(weapon.get("damage_types") or [str(weapon.get("damage_type") or "UNTYPED")])
        after = _expected_damage(typed["effects"], typed.get("numbers") or {}, weapon=typed.get("weapon"))
        update: dict[str, Any] = {"parameters": {**row.parameters, "typed": typed,
                                                 "expected_damage": int(row.parameters.get("expected_damage") or 0) + after - before}}
        mechanic = mechanics.get(str(typed.get("option_of") or typed.get("source") or "")) or {}
        if row.target_kind == "SELF" and best is not None and (mechanic.get("range") or {}).get("kind") == "weapon" and (mechanic.get("area") or {}).get("size_ft"):
            update.update(target_kind="CELL", range_ft=best.range_ft)
        out.append(row.model_copy(update=update))
    return out


_LASTING = ("minutes", "rounds", "hours", "scene", "until_start_of_next_turn", "until_end_of_next_turn", "until_end_of_your_next_turn", "turn", "special")
_ZONE_WORDS = re.compile(r"\bterrain\b|\barea becomes\b|\bremains? (?:where|in place)|\bobscured\b|\b(?:cloud|fog|mist|smoke|field|zone|"
                         r"domain|wall|pool|patch|ring|circle|sphere of|aura|fragrance|dreamscape)\b|\benters? (?:the|its|that) (?:area|zone|field)|"
                         r"\bstarts? (?:its|their) turn (?:in|inside|within)", re.I)
_ENTER = re.compile(r"\benter(?:s|ing)?\b(?!\s+(?:a|the)\s+space\s+within)", re.I)
_START = re.compile(r"\bstart(?:s|ing)? (?:its|their|a) turn\b|\bbegins? (?:its|their) turn\b", re.I)
_START_PRINTED = re.compile(r"\b(?:an? |each )?(?:hostile |enemy |allied )?(?:creature|enemy|enemies|ally|allies|target)s? (?:that )?"
                            r"(?:starts?|begins?) (?:its|their) turn (?:inside|in|within)\b", re.I)
_END = re.compile(r"\bends? (?:its|their) turn\b", re.I)
# Charge-worker 2026-09-28 (Earth's Earthbind Line, Set Foundation): a line-shaped zone's own "crosses the
# line" is a real geometric crossing (combat/zones.py's on_moved/_crosses_line), not the "enter" moment
# above (which fires on stepping onto the line's own cells and would also fire for a creature that steps
# on and stops, or backs out the way it came -- neither is "crossing" it).
_CROSS = re.compile(r"\bcrosses?\b|\bmoves? across\b", re.I)
# "Moves at least N feet across, out of, or through your Lattice/Foundation Spaces" (Ice's Crystallize
# Path, Earth's Set Foundation): the same shape as a named terrain's move_through (Ash Terrain), but for an
# ability's own area rather than a terrain.json entry, so it is read straight off the ability's own text.
_MOVE_ACROSS = re.compile(r"moves? at least (\d+) feet (?:across|out of|through)", re.I)
_NAMED_TERRAIN = re.compile(r"\b((?:[A-Z][a-z]+[- ]){0,2}[A-Z][a-z]+ Terrain)\b")
_MATERIAL_BY_SPHERE = {
    "ash": "ash", "magma": "lava", "lava": "lava", "fire": "fire", "flame": "fire", "ice": "ice", "frost": "frost", "cold": "frost",
    "water": "water", "tide": "water", "rain": "water", "earth": "stone", "stone": "stone", "mountain": "stone", "wood": "vines",
    "plant": "thorns", "thorn": "thorns", "flower": "vines", "poison": "poison", "venom": "poison", "disease": "miasma", "plague": "miasma",
    "lightning": "lightning", "thunder": "lightning", "storm": "lightning", "darkness": "darkness", "shadow": "darkness", "night": "darkness",
    "light": "radiance", "sun": "radiance", "moon": "radiance", "radiance": "radiance", "smoke": "smoke", "mist": "fog", "fog": "fog",
    "cloud": "fog", "air": "wind", "wind": "wind", "blood": "blood", "sand": "sand", "death": "grave", "grave": "grave", "bone": "grave",
    "metal": "metal", "iron": "metal", "formation": "glyphs", "array": "glyphs", "talisman": "glyphs", "ink": "glyphs", "seal": "glyphs",
    "spirit": "spirit", "soul": "spirit", "ghost": "spirit", "illusion": "illusion", "mirror": "illusion", "dream": "illusion",
    "stars": "stars", "star": "stars", "void": "stars", "sound": "sound", "music": "sound", "thread": "web", "silk": "web", "web": "web",
    "verdant": "vines",
    "puppetry": "web", "gravity": "stars", "karma": "glyphs", "fortune": "glyphs", "time": "glyphs", "space": "stars",
    "fate": "glyphs", "yang": "radiance", "yin": "darkness", "chains": "metal", "sword": "metal", "sabers": "metal", "force": "wind",
    "beauty": "radiance", "alchemy": "miasma", "glass": "glass", "wax": "wax", "candle": "wax", "guardian": "metal",
    "barrage": "metal", "spear": "metal", "pressure": "spirit", "salt": "sand", "lotus": "vines", "insect": "web", "swarm": "web",
    "venom": "poison", "rot": "miasma", "decay": "miasma", "bone": "grave", "sky": "wind", "cloud": "fog", "snow": "frost",
    "storm": "lightning", "heaven": "radiance", "dragon": "fire", "phoenix": "fire", "tiger": "stone", "unmaking": "darkness",
    "destruction": "rubble", "ruin": "rubble", "hunger": "blood", "daemonic": "blood", "shield": "metal", "berserker": "blood",
}
_TERRAIN_WORDS = re.compile(r"\b(?i:difficult terrain)\b|\b[A-Z][a-z]+ Terrain\b|\b(?i:rubble|crater\w*|cracked terrain)\b")
_TERRAIN_MADE = re.compile(r"\b(?:becomes?|is|are|creat\w*|treats?|counts? as|fills?|leav\w*|turns? (?:in)?to|collapses?)\b", re.I)
_TERRAIN_NOT_MADE = re.compile(r"\bignor\w*|\bdoes(?:n.t| not) (?:create|count|cost)|\bnot (?:real|create)|\bmov\w* through\b|\bpass\w* through\b|"
                               r"\bspaces? of\b|\bcreature.s space|\bcreature spaces\b|\bwithout treating\b|\bfor you\b|\bstanding on\b|\billus\w*|\bReview\b|\b(?:the|that) (?:creature|target) treats\b", re.I)


def _barred_actions(text: str) -> list[str]:
    """The actions an area's talent takes from the creatures inside it ("Creatures inside move at half Speed and cannot
    take the Dash or Disengage actions": Thick Darkness) -- "dash" and/or "disengage", as condition rules no_dash and
    no_disengage (combat/ext/no_dash.py)."""
    match = re.search(r"\bcreatures inside\b[^.]*?\bcannot take the (Dash|Disengage)(?: or (Dash|Disengage))? actions?", text, re.I)
    return [] if not match else [word.lower() for word in match.groups() if word]


def _left_terrain(text: str) -> dict[str, Any] | None:
    """Ground an ability changes and leaves changed (owner 2026-09-27: "cracked earth or other difficult terrain"):
    Earthshaking Blow's "Broken Ground: The area becomes difficult terrain until repaired", Heaven-Weight Descent's
    "Create a 10-foot-radius area of rubble or cratered terrain", Glass Desert Judgment's "Glass Terrain is Difficult
    Terrain". Not a creature's space passed "as difficult terrain", and not terrain one ignores. Returns the sentence,
    the size it names and how long the ground stays changed (the scene unless the sentence says less)."""
    for sentence in re.split(r"(?<=[.;])\s+|\n|\"", text):
        if not _TERRAIN_WORDS.search(sentence) or not _TERRAIN_MADE.search(sentence) or _TERRAIN_NOT_MADE.search(sentence):
            continue
        if re.match(r"\s*(?:if|when|whenever)\b", sentence, re.I):  # "If the target is terrain, it becomes Molten Terrain": not every use
            continue
        size = re.search(r"(\d+)-foot", sentence)
        if re.search(r"until the end of your next turn", sentence, re.I):
            duration = {"kind": "until_end_of_next_turn", "amount": 1}
        elif re.search(r"until the end of (?:the current|this|your) turn", sentence, re.I):
            duration = {"kind": "turn", "amount": 1}
        elif re.search(r"until the start of your next turn", sentence, re.I):
            duration = {"kind": "until_start_of_next_turn", "amount": 1}
        else:
            duration = {"kind": "scene", "amount": 1}
        return {"sentence": sentence.strip(), "size_ft": int(size.group(1)) if size else None, "duration": duration,
                "hostile": bool(re.search(r"\bhostile\b|\benem(?:y|ies)\b|\bfor them\b", sentence, re.I))}
    return None


_WALL_FIELDS = ("blocks_movement", "see_through", "obscures", "cover", "move_cost", "difficult", "thick_ft", "length_ft", "breach", "leaves", "enter",
                "object")  # object: a solid wall's AC and hit points (docket 2026-09-28, combat/ext/docket_walls.py)


def _wall_rule(names: list[str], pb: int, cl: int = 1) -> dict[str, Any] | None:
    """The wall an ability raises (combat/rules/terrain.json "walls"), by its name or a talent that reshapes it
    ("Darkness + Wall of Darkness"), with its length worked out (Humble Wall grows with CL)."""
    from .zones import terrain_rules

    walls = terrain_rules().get("walls") or {}
    for name in names:
        rule = walls.get(str(name or "").strip().lower())
        if rule:
            length = int(rule.get("length_ft") or 0) or (pb * 20 if rule.get("length_formula") == "pb*20" else 30)
            for least, feet in rule.get("length_by_cl") or []:
                if cl >= int(least):
                    length = int(feet)
            return {**rule, "length_ft": length, "name": name}
    return None


def _wall_fields(wall: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(wall[key]) for key in _WALL_FIELDS if key in wall}


def _area_size_for_cl(area: dict[str, Any], cl: Any) -> int | None:
    """An area's size in feet, CL-scaled the same way dice_by_cl scales damage (worker w4-spirit, 2026-09-28: Domain
    Pressure's cone is 15/30/60 feet by CL band). ``size_ft_by_cl`` rows are ``[low_cl, high_cl, feet]``; unset or a
    plain ``size_ft`` behaves exactly as before."""
    size = area.get("size_ft")
    for row in area.get("size_ft_by_cl") or []:
        low, high, feet = row
        if int(low) <= int(cl or 1) <= int(high):
            size = int(feet)
    return size


def _area_blocks_for_cl(area: dict[str, Any], cl: Any) -> int | None:
    """How many connected cubes an area is made of at this Cultivation Level, for a printed "the area becomes two
    connected 10-foot cubes" table. ``blocks_by_cl`` rows are ``[low_cl, high_cl, count]``, read the way
    ``_area_size_for_cl`` reads ``size_ft_by_cl``; unset, or a single cube, behaves exactly as before."""
    blocks = area.get("blocks")
    for row in area.get("blocks_by_cl") or []:
        low, high, count = row
        if int(low) <= int(cl or 1) <= int(high):
            blocks = int(count)
    return blocks


def _area_size(area: dict[str, Any], row: ActionDefinition) -> int:
    """The area's size in feet; special areas may name it in words.

    Reviewed area data can opt into ``preserve_size: true`` to keep its full size
    for a persistent zone of any shape. Actual cells are clipped to the map by
    area_cells, not to an assumed map width here. Omitted retains the legacy cap.
    """
    cl = ((row.parameters.get("typed") or {}).get("numbers") or {}).get("cl")
    size = int(_area_size_for_cl(area, cl) or row.radius_ft or 0)
    if not size:
        found = re.search(r"(\d+)-foot", str(area.get("text") or area.get("evidence") or ""))
        size = int(found.group(1)) if found else 0
    return size if area.get("preserve_size") else min(size, 60)


def _texts(mechanic: dict[str, Any]) -> str:
    parts = [str((mechanic.get("activation") or {}).get("trigger") or "")]
    description = mechanic.get("description")
    parts += list(description) if isinstance(description, list) else [str(description or "")]
    parts += [str(row) for row in mechanic.get("riders") or []]
    parts += [str(effect.get("evidence") or "") for tree in [mechanic, *(mechanic.get("options") or [])] for effect in _walk(tree.get("effects") or [])]
    return " ".join(part for part in parts if part)


_MATERIAL_BY_NAME = (("falling star", "crater"), ("meteor", "crater"), ("crater", "crater"), ("descent", "crater"), ("glass", "glass"),
                     ("wax", "wax"), ("candle", "wax"), ("shatter", "cracked"), ("crack", "cracked"), ("fractur", "cracked"),
                     ("earthshak", "cracked"), ("stomp", "cracked"), ("quake", "cracked"), ("earth beats", "cracked"),
                     ("spear", "metal"), ("dawn", "radiance"), ("noon", "radiance"), ("sun", "radiance"), ("golden", "radiance"),
                     ("burial", "grave"), ("flood", "water"), ("river", "water"), ("monsoon", "water"), ("overgrowth", "vines"),
                     ("briar", "thorns"), ("lantern", "radiance"), ("sea", "water"), ("mountain", "stone"), ("demon", "blood"),
                     ("beast", "mud"), ("monkey", "vines"), ("ribbon", "web"), ("seed", "vines"), ("elephant", "cracked"), ("darkness", "darkness"), ("shadow", "darkness"), ("light", "radiance"), ("radian", "radiance"), ("toxic", "poison"),
                     ("poison", "poison"), ("miasma", "miasma"), ("illusion", "illusion"), ("figment", "illusion"), ("mirror", "illusion"),
                     ("smoke", "smoke"), ("fog", "fog"), ("mist", "fog"), ("cloud", "fog"), ("ash", "ash"), ("ember", "fire"),
                     ("flame", "fire"), ("fire", "fire"), ("lava", "lava"), ("magma", "lava"), ("molten", "lava"), ("frost", "frost"),
                     ("ice", "ice"), ("snow", "frost"), ("storm", "lightning"), ("thunder", "lightning"), ("lightning", "lightning"),
                     ("charged", "lightning"), ("spark", "lightning"), ("wind", "wind"), ("gale", "wind"), ("cyclone", "wind"),
                     ("breath", "wind"), ("updraft", "wind"), ("turbulen", "wind"), ("sand", "sand"), ("dune", "sand"), ("mud", "mud"),
                     ("rut", "mud"), ("earth", "stone"), ("stone", "stone"), ("bearing ground", "stone"), ("grave", "grave"),
                     ("bone", "grave"), ("wither", "grave"), ("blood", "blood"), ("web", "web"), ("thread", "web"), ("string", "web"),
                     ("garden", "thorns"), ("thorn", "thorns"), ("impal", "thorns"), ("vine", "vines"), ("root", "vines"),
                     ("sword", "metal"), ("saber", "metal"), ("blade", "metal"), ("array", "glyphs"), ("seal", "glyphs"),
                     ("formation", "glyphs"), ("court", "glyphs"), ("bell", "sound"), ("song", "sound"), ("echo", "sound"),
                     ("star", "stars"), ("void", "stars"), ("dream", "illusion"), ("water", "water"), ("tide", "water"),
                     ("current", None), ("ink", "glyphs"),
                     # Domains and fields with no Sphere of their own (owner 2026-09-27: every zone should look like something)
                     ("drum", "sound"), ("mantra", "sound"), ("spoken", "sound"), ("taiji", "glyphs"), ("board", "glyphs"),
                     ("law", "glyphs"), ("hall", "glyphs"), ("dust", "sand"), ("weather", "wind"), ("sky", "wind"),
                     ("festival", "radiance"), ("heaven", "radiance"), ("witness", "radiance"), ("nightmare", "illusion"),
                     ("sleeping", "illusion"), ("missing", "illusion"), ("nonexist", "stars"), ("without between", "stars"),
                     ("handspan", "stars"), ("empty", "spirit"), ("stillness", "spirit"), ("meridian", "spirit"),
                     ("manifestation", "spirit"), ("treasury", "metal"), ("net", "web"), ("calamity", "radiance"),
                     ("pressure", "wind"), ("domain", "glyphs"),
                     # Complete authority spellings used with whole-word identity matching.
                     ("leaves", "vines"), ("foliage", "vines"),
                     ("dreamscape", "illusion"), ("turbulent", "wind"), ("cremation", "ash"), ("incenses", "smoke"),
                     ("incense", "smoke"), ("sandstorm", "sand"), ("waxen", "wax"), ("shattering", "cracked"),
                     ("impaling", "thorns"), ("moon", "stars"), ("cinder", "fire"), ("rain", "water"),
                     ("orchard", "vines"), ("dreams", "illusion"), ("strings", "web"), ("ashstorm", "ash"),
                     ("diagram", "glyphs"), ("sealing", "glyphs"), ("demons", "blood"), ("leaf", "vines"),
                     ("ribbons", "web"),
                     ("obsidian", "glass"), ("bloom", "vines"))
_GENERIC_ZONE_HINT_WORDS = frozenset({"cloud", "fog", "mist", "field", "area", "zone", "wall", "court", "domain",
                                      "hall", "garden", "seal", "formation", "array", "board", "pool", "patch",
                                      "ring", "circle", "aura", "weather", "heaven", "empty", "law", "demon", "calamity",
                                      "breath", "rain", "sealing"})
_MATERIAL_BY_GROUND = (("crater", "crater"), ("impact", "crater"), ("crack", "cracked"), ("fractur", "cracked"), ("broken", "cracked"),
                       ("rubble", "rubble"), ("glass", "glass"), ("wax", "wax"), ("molten", "lava"),
                       ("mud", "mud"), ("ice", "ice"), ("frozen", "ice"), ("sand", "sand"), ("water", "water"), ("flood", "water"),
                       ("thorn", "thorns"), ("root", "vines"), ("vine", "vines"))
_CREATES_DARKNESS = re.compile(r"\b(?:creates?|fills?|spreads?|becomes?|summons?|cloaks?)\b[^.,;]{0,40}\b(?:magical )?darkness\b|"
                               r"\b(?:magical )?darkness (?:fills|spreads|covers|within|in a|that)\b|\bheavily obscured by (?:magical )?darkness\b", re.I)
_DISPELS_DARKNESS = re.compile(r"\b(?:dispels?|ends?|suppress(?:es)?|pierces?|reveals?|through)\b[^.]{0,30}\bdarkness\b|"
                               r"\bdarkness\b[^.]{0,40}\b(?:is |are )?(?:suppressed|dispelled|ends?|revealed)\b", re.I)


def _zone_visual(mechanic: dict[str, Any], text: str, sphere_names: dict[str, str], obscured: str | None,
                 ground: str | None = None) -> dict[str, Any]:
    """How the table draws a zone: explicit visual, terrain it creates, then its identity (name, element, Sphere).

    Do not infer a material from the whole rules text: interaction clauses such as "Fire damage affects this" or
    "Cold damage destroys it" describe a counter to the zone, not what the zone looks like.
    """
    name = str(mechanic.get("name") or "").lower()
    sphere = str(sphere_names.get(str(mechanic.get("sphere_id") or ""), "") or "").lower()
    element = str(mechanic.get("element") or "").lower()
    subpath = str(mechanic.get("subpath") or mechanic.get("subpath_name") or mechanic.get("subpath_id") or "").lower()
    if subpath.startswith("tianxia."):
        # The namespace/classification prefix is not an appearance hint.
        subpath = subpath.rsplit(".", 1)[-1]
    subpath = re.sub(r"[._]+", " ", subpath)
    identity = " ".join((name, element, sphere, subpath))
    declared = (mechanic.get("visual") or {}).get("material")
    if not isinstance(declared, str) or not declared.strip():
        declared = None
    by_ground = next((value for word, value in _MATERIAL_BY_GROUND if re.search(rf"\b{word}", ground or "", re.I)), None)
    def mapped_name(value: str, *, generic: bool = False) -> str | None:
        return next((material for word, material in _MATERIAL_BY_NAME
                     if (word in _GENERIC_ZONE_HINT_WORDS) == generic
                     and re.search(rf"\b{re.escape(word)}\b", value)), None)

    def mapped_sphere(value: str) -> str | None:
        return next((material for word, material in _MATERIAL_BY_SPHERE.items()
                     if re.search(rf"\b{re.escape(word)}\b", value)), None)

    # Specific words in the printed ability name win first (Toxic Cloud is poison;
    # Volcanic Smoke is smoke). Element, subpath, then Sphere supply identity when
    # the name only says a broad form such as Court or Field. Match whole words so
    # Light cannot accidentally match Lightning.
    by_specific_name = mapped_name(name)
    by_element = mapped_name(element) or mapped_sphere(element)
    by_subpath = mapped_name(subpath) or mapped_sphere(subpath)
    by_sphere = mapped_sphere(sphere)
    by_form = mapped_name(identity, generic=True)
    material = declared or by_ground or by_specific_name or by_element or by_subpath or by_sphere or by_form or "generic"
    light = None
    lit = re.search(r"\b(bright|dim) light\b(?:[^.]{0,60}?(\d+)-foot)?", text, re.I) or re.search(r"(\d+)-foot[^.]{0,40}\b(bright|dim) light", text, re.I)
    if lit:
        groups = [group for group in lit.groups() if group]
        level = next((group.lower() for group in groups if group.lower() in ("bright", "dim")), "dim")
        radius = next((int(group) for group in groups if group.isdigit()), 20)
        light = {"radius_ft": radius, "level": level, "color": "#bfe8ff" if material in ("spirit", "grave", "frost", "ice") else "#ffd28a"}
    darkness = bool(_CREATES_DARKNESS.search(text)) and not _DISPELS_DARKNESS.search(text) or material == "darkness" and name.strip() == "darkness"
    return {"material": "darkness" if darkness else material, "obscured": obscured, "light": light, "darkness": darkness}


def _zone_spec(row: ActionDefinition, mechanic: dict[str, Any], sphere_names: dict[str, str]) -> dict[str, Any] | None:
    """Compile a lasting zone, with an optional effect-local area.

    A top-level zone effect may supply ``area`` when its persistent footprint
    differs from the action's targeting area. Absent retains the action area;
    this metadata applies to any ability and does not alter its target selection.
    A zone effect that states its own object ``duration`` also states how long the area
    lasts, which is the only place some printed talents print it: an ability whose modes
    each name their own length ("Create a 60-foot-radius field until the end of your next
    turn" inside one chosen mode) has no single action-level Duration line. Such a row
    applies only when the action's own duration is not already lasting, so an area whose
    lifetime the action states keeps the action's stated lifetime.
    """
    typed = row.parameters.get("typed") or {}
    local_area = next((effect["area"] for effect in typed.get("effects") or []
                       if effect.get("type") == "zone" and effect.get("area")), None)
    area = local_area or typed.get("area") or mechanic.get("area") or {}
    if area.get("size_ft_by_cl"):
        area = {**area, "size_ft": _area_size_for_cl(area, (typed.get("numbers") or {}).get("cl"))}
    size = _area_size(area, row)
    duration = typed.get("duration") or {}
    lasting = bool(duration.get("concentration")) or str(duration.get("kind") or "") in _LASTING
    row_duration = next((effect["duration"] for effect in typed.get("effects") or []
                         if effect.get("type") == "zone" and isinstance(effect.get("duration"), dict)
                         and str(effect["duration"].get("kind") or "") in _LASTING), None)
    if row_duration is not None and not lasting:
        duration, lasting = dict(row_duration), True
    has_zone = any(effect.get("type") == "zone" for effect in _walk(typed.get("effects") or []))
    text = _texts(mechanic)
    left = _left_terrain(text)
    if left and not lasting:  # an instant strike that leaves broken ground: the ground stays broken
        duration, lasting = dict(left["duration"]), True
    size = size or int((left or {}).get("size_ft") or 0) or (5 if left else 0)
    wall = _wall_rule([mechanic.get("name"), *str(row.display_name or "").split(" + ")], int((typed.get("numbers") or {}).get("pb") or 2),
                      int((typed.get("numbers") or {}).get("cl") or 1))
    if wall:
        size, lasting, left = int(wall["length_ft"]), True, None
        if str(duration.get("kind") or "") not in _LASTING and not duration.get("concentration"):
            duration = {"kind": "minutes", "amount": 1, "concentration": False}
        area = {"shape": "wall", "size_ft": size, "thick_ft": int(wall.get("thick_ft") or 5)}
    if not size or not lasting or not (has_zone or left or _ZONE_WORDS.search(text)):
        return None
    from .zones import terrain_rules

    rules = terrain_rules()
    known = rules.get("terrains", {})
    names: list[str] = []
    for found in _NAMED_TERRAIN.findall(text):  # "Reaction Shattered Glass Terrain" -> the longest known name
        words = found.lower().split()
        match = next((" ".join(words[index:]) for index in range(len(words) - 1) if " ".join(words[index:]) in known), None)
        if match and match not in names:
            names.append(match)
    # A reviewed zone may explicitly list the named terrain it creates. Empty
    # means none: merely ignoring or modifying an existing terrain does not
    # create that terrain throughout a new field. Omission retains inference.
    stated_terrain = next((effect['terrain'] for effect in typed.get('effects') or []
                           if effect.get('type') == 'zone' and 'terrain' in effect), None)
    if stated_terrain is not None:
        names = list(stated_terrain)
    terrain = [known[name] for name in names]
    lowered = text.lower()
    difficult = next((row_["difficult"] for row_ in terrain if row_.get("difficult")), None) or (
        ("hostile" if left["hostile"] else "all") if left and re.search(r"difficult terrain|rubble|crater", left["sentence"], re.I) else None) or (
        ("hostile" if re.search(r"difficult terrain for (?:hostile|enem)|hostile creatures[^.]{0,40}treat[^.]{0,30}difficult terrain", lowered) else "all")
        if "difficult terrain" in lowered else None)
    obscured = next((row_["obscured"] for row_ in terrain if row_.get("obscured")), None) or (
        "heavy" if "heavily obscured" in lowered else "light" if "lightly obscured" in lowered else None)
    stated = next((effect for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "zone" and "obscured" in effect), None)
    if stated is not None:  # a reviewed zone says whether it obscures (Ten-Thousand Motions only names "heavily obscured" as a mark trigger)
        obscured = stated["obscured"] or None
    stated_difficult = next((effect for effect in typed.get("effects") or []
                             if isinstance(effect, dict) and effect.get("type") == "zone" and "difficult" in effect), None)
    if stated_difficult is not None:  # including explicit false: "not difficult terrain"
        difficult = stated_difficult["difficult"] or None
    triggers = []
    # "cast_only" marks an effect of the moment the area is made ("When you create the Current, choose one creature ...",
    # Tidal Wave's wave): it is not what a creature entering the area meets later.
    effects = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict) and not effect.get("cast_only")
               and effect.get("type") not in ("zone", "spend_resource", "gain_resource", "movement", "teleport") and effect.get("applies_to") != "self"]
    moments = [moment for moment, pattern in (("enter", _ENTER), ("start", _START)) if pattern.search(text)]
    # The typing's evidence often leaves out "When an enemy starts its turn inside the Domain" (fight audit 2026-09-29: 24
    # domains and fields had their area but no start-of-turn save); the printed text says it.
    printed_start = _START_PRINTED.search(_rules_text().get(str(mechanic.get("mechanic_id") or ""), ""))
    if printed_start and "start" not in moments:
        moments.append("start")
        text = f"{text} {printed_start.group(0)}"  # who it names (an enemy, a hostile creature) decides "who" below
    if area.get("shape") == "line" and _CROSS.search(text):
        # Earthbind Line: "crosses the line" is its own moment (combat/zones.py's on_moved/_crosses_line),
        # not "enter" -- gated to a line-shaped area since "crosses" has no directional meaning for a blob.
        moments.append("cross")
    if effects and moments:  # the ability is already a zone: "enters the Updraft / the aura ... or starts its turn there"
        # "A creature that enters the area ... or starts its turn there makes a save": the ability's own effects again then.
        # "who" here is only the policy this reading of the prose gives the
        # trigger; it is not a reviewed roster. The reviewed roster, when the
        # authority data states one, is carried separately in "roster" so the
        # delayed-area recipient seam can tell the two apart.
        triggers.append({"id": f"{row.source_definition_id}:own", "name": mechanic.get("name"), "on": moments,
                         "who": "hostile" if re.search(r"\bhostile\b|\benem(?:y|ies)\b|\bunwilling\b", text, re.I)
                         else "ally" if re.search(r"\ball(?:y|ies)\b|\bwilling\b", text, re.I) else "any",
                         "effects": copy.deepcopy(effects)})
    for rule in (row_.get("enter_start") for row_ in terrain if row_.get("enter_start")):
        # A named terrain's own "entering ... or starting its turn there makes a save" (Fire Terrain; Molten Terrain's is
        # against the talent's own damage, half on a success).
        if rule.get("from_ability"):
            from .ext import terrain_damage

            # The terrain's save is against the ability's OWN listed damage (rules/terrain.json), so the
            # strike row counts and the patch keeps that damage. Another ability's rider grafted onto the
            # strike (Eruption Strike: 2 CP, once per turn, "You hit a creature") is skipped with its whole
            # subtree, or it would fire for every creature that later entered, with no attack and no cost.
            damage = terrain_damage.own_damage_rows(effects)
            if not damage:
                continue
            on_fail, on_success = damage, ([{"type": "half_damage"}] if rule.get("half") else [])
        else:
            on_fail, on_success = copy.deepcopy(rule.get("on_fail") or []), copy.deepcopy(rule.get("on_success") or [])
        triggers = [row_ for row_ in triggers if not row_["id"].endswith(":own")] if rule.get("from_ability") else triggers
        triggers.append({"id": f"{row.source_definition_id}:terrain", "name": " / ".join(name.title() for name in names), "on": ["enter", "start"],
                         "who": rule.get("who") or "hostile",
                         **({"roster": str(rule["who"]).strip().lower()} if rule.get("who") else {}),
                         "effects": [{"type": "save", "ability": rule.get("ability") or "DEX", "on_fail": on_fail, "on_success": on_success}]})
    if wall:  # a wall hides or blocks by its own rule (combat/zones.py sync_walls, attack_mode)
        difficult, obscured = wall.get("difficult"), None
        terrain, names = [], []
        if wall.get("enter") and not triggers and effects:
            # Wind Wall's Strength save, Monsoon Wall's push: the ability's own effects on a creature entering it.
            triggers = [{"id": f"{row.source_definition_id}:wall", "name": mechanic.get("name"), "on": list(wall["enter"].get("on") or ["enter"]),
                         "who": wall["enter"].get("who") or "any",
                         **({"roster": str(wall["enter"]["who"]).strip().lower()} if wall["enter"].get("who") else {}),
                         "effects": copy.deepcopy(effects)}]
    # A reviewed typing's own triggers for the zone it makes ("triggers" on the zone effect): Gravity Domain's and World as
    # Canvas's Strength saves belong to a creature starting its turn in (or entering) the area, not to the moment of casting,
    # which is when the ability's top-level effects run (fight audit 2026-09-29).
    made = [trigger for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "zone"
            for trigger in effect.get("triggers") or [] if isinstance(trigger, dict)]
    keep = any(isinstance(effect, dict) and effect.get("type") == "zone" and effect.get("keep_inferred_triggers") for effect in typed.get("effects") or [])
    if made and not keep:  # Explicit timing replaces the source-text inference, which may also collect creation-time buffs
        # (ally buffs are not hostile turn-start payloads). A zone marked keep_inferred_triggers holds its own payload in its
        # triggers, so what else the ability carries keeps the inferred moment (an augment's added save: Whirlpool Prison on
        # Shape Current's Pressure Basin, rider lane C13).
        triggers = [trigger for trigger in triggers if not trigger["id"].endswith(":own")]
    for index, trigger in enumerate(made):
        triggers.append({"id": f"{row.source_definition_id}:zone{index}", "name": mechanic.get("name"), "on": list(trigger.get("on") or ["enter", "start"]),
                         "who": trigger.get("who") or "hostile",
                         **({"roster": str(trigger["who"]).strip().lower()} if trigger.get("who") else {}),
                         "effects": copy.deepcopy(trigger.get("effects") or []),
                         **{key: copy.deepcopy(trigger[key]) for key in ("per_round", "first_each_round", "once_per_creature", "requires_mark", "requires_kind", "choice_owner") if key in trigger}})
    stated_zones = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "zone"]
    blocks = _area_blocks_for_cl(area, (typed.get("numbers") or {}).get("cl"))
    # The parts a choose-N menu's options give the area (combat/ext/menus.py zone_parts): the picked options' own rules for
    # who is inside, difficult ground, obscurement and enter/start effects.
    menu_parts = next((copy.deepcopy(effect["menu_parts"]) for effect in typed.get("effects") or []
                       if isinstance(effect, dict) and effect.get("type") == "zone" and effect.get("menu_parts")), None)
    if menu_parts:
        difficult = obscured = None  # its difficult ground and obscurement are the picked options' own, never the printed list's
    from . import zone_sources

    # Explicit point placement wins over a self-targeting activation. Some zones
    # originate from an external anchor even though their activation targets Self.
    self_centered = not wall and (bool(area["centered_on_self"]) if "centered_on_self" in area
                                  else row.target_kind == "SELF")
    return {"name": mechanic.get("name"), "shape": area.get("shape") or "sphere", "size_ft": size,
            "source_profile": zone_sources.compile_profile(typed, mechanic, duration),
            **({"blocks": int(blocks)} if int(blocks or 1) > 1 else {}),
            **({"width_ft": area["width_ft"]} if area.get("width_ft") else {}),
            **({"height_ft": area["height_ft"]} if area.get("height_ft") is not None else {}),
            **({"menu_parts": menu_parts} if menu_parts else {}),
            **({"wall": _wall_fields(wall)} if wall else {}),
            # A line or cone laid down at the aim point (Earthbind Line's 20-foot line placed up to 60 feet away)
            # stays laid down there when it is on the map (combat/zones.py _cells), and when it is re-centered.
            **({"placed": True} if area.get("placed") else {}),
            "centered_on_self": self_centered, "duration": dict(duration),
            **next(({"profile": copy.deepcopy(effect["profile"])} for effect in stated_zones
                    if isinstance(effect.get("profile"), dict)), {}),
            "terrain": names, "difficult": next((effect["difficult"] for effect in typed.get("effects") or []
                if effect.get("type") == "zone" and "difficult" in effect), difficult), "obscured": obscured,
            "color": next((row_["color"] for row_ in terrain if row_.get("color")), None) or rules.get("default_color"),
            # An area that is stated as following its owner says so in data, not by wording. The printed
            # shape carries the flag either on its stated zone effect ("aura centered on you") or on the
            # area itself when the row states the area without a zone effect (Ink Domain); the more
            # specific of the two wins. A typed emanation centered on its user is creature-anchored,
            # unlike a sphere merely placed at the user's current square. Explicit false keeps
            # exceptions fixed (for example a field whose printed center remains fixed).
            # This general anchoring seam applies only to newly compiled zones; saved profiles
            # keep their recorded follows_owner value. The wording remains a legacy fallback.
            "follows_owner": next((bool(effect["follows_owner"]) for effect in stated_zones if "follows_owner" in effect),
                                  bool(area["follows_owner"]) if "follows_owner" in area else
                                  bool(area.get("shape") == "emanation" and self_centered) or
                                  bool(re.search(r"\bmoves with you\b|\bcentered on you\b[^.]{0,40}\bmoves\b", text, re.I))),
            # "spreads around corners, and cannot extend through walls" (Darkness): it flows around a wall, never through
            # one (combat/typed_executor.py _spread); every other area stops at walls in a straight line.
            # Explicit reviewed geometry lets any typed area flow through connected
            # openings; the shared raster continues to block sealed barriers.
            **({"spreads": True} if any(effect.get("spreads") is True for effect in stated_zones)
               or re.search(r"spreads? around corners", f"{text} {_rules_text().get(str(mechanic.get('mechanic_id') or ''), '')}", re.I)
               else {}),
            "move_through": next((copy.deepcopy(effect["move_through"]) for effect in stated_zones if "move_through" in effect),
                next((row_["move_through"] for row_ in terrain if row_.get("move_through")), None) or (
                {"min_ft": int(_MOVE_ACROSS.search(text).group(1)),
                 "who": "hostile" if re.search(r"\bhostile\b|\benem(?:y|ies)\b", text, re.I) else "any",
                 "effects": copy.deepcopy(effects)}
                if effects and _MOVE_ACROSS.search(text) else None)),
            "visual": {**_zone_visual(mechanic, text, sphere_names, obscured, (left or {}).get("sentence")),
                       **({"material": wall["material"], "wall": True, "darkness": wall.get("material") == "darkness"} if wall else {}),
                       **({"material": next(row_["material"] for row_ in terrain if row_.get("material"))} if any(row_.get("material") for row_ in terrain) else {})},
            "triggers": triggers,
            "inside": [copy.deepcopy(rule) for effect in stated_zones for rule in effect.get("inside") or []]}


def _zone_abilities(actions: list[ActionDefinition], mechanics: dict[str, Any], owned: list[str], sphere_names: dict[str, str],
                    cost_of: Any, pool: str = "resource:core.qi") -> list[ActionDefinition]:
    """An ability that leaves an area on the map carries its zone (combat/zones.py); a talent that changes that area
    ("An Ashfall talent modifies an area created through Ashfall. Only one Ashfall talent normally modifies one Ashfall
    area": Soot in the Lungs, "a hostile creature entering Ashfall for the first time on a turn or starting its turn
    inside") is chosen before it is used -- "Shape Ashfall: Soot in the Lungs", a free choice that stays until changed
    (owner 2026-09-27) -- and paid for when the area is made (_zone_shapes, combat/zones.py _shaped)."""
    out: list[ActionDefinition] = []
    families: dict[str, dict[str, Any]] = {}
    shapes_for: dict[str, tuple[ActionDefinition, str, dict[str, Any], dict[str, Any]]] = {}
    for row in actions:
        typed = row.parameters.get("typed")
        mechanic = mechanics.get(str((typed or {}).get("option_of") or (typed or {}).get("source") or "")) if isinstance(typed, dict) else None
        spec = _zone_spec(row, mechanic, sphere_names) if mechanic and row.resolution_kind == "TYPED" and typed.get("weapon") is None else None
        if spec is None:
            out.append(row)
            continue
        # General seam (owner 2026-10-13, Body as Center): an action
        # that was compiled with its own zone_spec (combat/ext
        # compile_actions) keeps those entries here, so a plug-in may
        # center an area on its caster, make it ride its owner, or
        # attach its own profile without a per-ability case in this
        # file. The compiled spec stays authoritative for shape, size
        # and triggers; only the plug-in's own keys survive.
        spec = {**spec, **((typed or {}).get("zone_spec") or {})}
        if spec.get("wall"):
            # A wall is raised at a square in range, across the user's line to it (combat/zones.py wall_cells).
            typed = {**typed, "area": {"shape": "wall", "size_ft": spec["size_ft"], "thick_ft": spec["wall"].get("thick_ft", 5)}}
            row = row.model_copy(update={"target_kind": "CELL", "range_ft": row.range_ft or 60, "radius_ft": 0,
                                         "parameters": {**row.parameters, "typed": typed}})
        name = str(mechanic.get("name") or "")
        if name:
            # A talent that changes the ground of this area ("Your Darkness becomes difficult terrain": Thick Darkness;
            # "Hostile creatures treat your Patrol Zone as difficult terrain": Steel Hedge) applies whenever it is used.
            for linked_id in owned:
                linked = mechanics.get(linked_id)
                if not linked or linked_id == (typed.get("source") or "") or \
                        (linked.get("activation") or {}).get("economy") in ("action", "bonus_action", "reaction"):
                    continue
                linked_text = _texts(linked)
                ground = _left_terrain(linked_text)
                if ground and re.search(rf"\b{re.escape(name)}\b", linked_text, re.I) and re.search(r"difficult terrain|rubble|crater", ground["sentence"], re.I):
                    spec = {**spec, "difficult": spec.get("difficult") or ("hostile" if ground["hostile"] else "all"),
                            "modified_by": [*spec.get("modified_by", []), linked.get("name")]}
                    barred = _barred_actions(_rules_text().get(linked_id) or linked_text)  # the printed text: a reviewed typing may drop the rider
                    if barred:  # Thick Darkness: "Creatures inside ... cannot take the Dash or Disengage actions"
                        spec = {**spec, "inside": [*(spec.get("inside") or []), {
                            "id": linked_id, "name": linked.get("name"), "who": "any", "muffles": False,
                            "rule": {f"no_{word}": True for word in barred},
                            "reading": f"Cannot take the {' or '.join(word.title() for word in barred)} action{'s' if len(barred) > 1 else ''}."}]}
        if name and "#" not in row.source_definition_id.split(".")[-1]:
            family = str(mechanic.get("mechanic_id") or typed.get("option_of") or typed.get("source") or "")
            if family not in families:
                families[family] = _zone_shapes(name, family, mechanics, owned, typed, row, cost_of, pool)
            shaping = families[family]
            if shaping["shapes"]:
                spec = {**spec, "family": family, "shapes": shaping["shapes"], "pair": shaping["pair"], "default_shape": shaping["default"]}
                if family not in shapes_for or (shapes_for[family][2].get("variant_of") and not typed.get("variant_of")):
                    shapes_for[family] = (row, name, typed, shaping)  # listed under the plain ability, not an augmented one
        value = 4 + sum(_expected_damage(trigger["effects"], typed.get("numbers") or {}) for trigger in spec["triggers"])
        value += sum(_expected_damage(trigger["effects"], typed.get("numbers") or {})
                     for talent in spec.get("default_shape") or [] for trigger in spec["shapes"][talent]["triggers"])
        base = row.model_copy(update={"parameters": {**row.parameters, "typed": {**typed, "zone_spec": spec},
                                                     "expected_damage": max(int(row.parameters.get("expected_damage") or 0), value), "inert": False}})
        out.append(base)
        if not name or "#" in row.source_definition_id.split(".")[-1]:
            continue
        pb = int((typed.get("numbers") or {}).get("pb") or 2)
        for linked_id in owned if not spec.get("wall") else []:
            # A talent that shapes this area as a wall ("When you create Smoke Veil ... a wall": Wall of Smoke) is one
            # more way to use it, "Smoke Veil + Wall of Smoke", unless the modifiers already made that choice.
            linked = mechanics.get(linked_id)
            wall = _wall_rule([linked.get("name")], pb, int((typed.get("numbers") or {}).get("cl") or 1)) if linked else None
            label = f"{row.display_name} + {(linked or {}).get('name')}"
            if not wall or not re.search(rf"\b{re.escape(name)}\b", _texts(linked), re.I) or any(other.display_name == label for other in actions):
                continue
            size = int(wall["length_ft"])
            wall_spec = {**spec, "shape": "wall", "size_ft": size, "centered_on_self": False, "difficult": wall.get("difficult"), "obscured": None,
                         "terrain": [], "move_through": None, "wall": _wall_fields(wall),
                         "visual": {**spec["visual"], "material": wall["material"], "wall": True, "darkness": wall["material"] == "darkness"}}
            out.append(base.model_copy(update={
                "source_definition_id": f"{row.source_definition_id}+{hashlib.sha256(linked_id.encode()).hexdigest()[:8]}",
                "display_name": label, "target_kind": "CELL", "range_ft": row.range_ft or 60, "radius_ft": 0,
                "parameters": {**base.parameters, "typed": {**base.parameters["typed"], "zone_spec": wall_spec,
                                                            "area": {"shape": "wall", "size_ft": size, "thick_ft": wall_spec["wall"].get("thick_ft", 5)}}}}))
    # One free choice per kind of area: which of its talents the next one carries (owner 2026-09-27; combat/zones.py _shaped).
    # A "Darkness + Numbing Darkness" for every talent, augment and pairing would be dozens of abilities, each aimed at
    # every square in range.
    for family, (row, name, typed, shaping) in shapes_for.items():
        # The character's own short id ("action:typed.<short>.<ability>"): [2] was the ability, so two Darkness users in
        # one fight had the same "Shape Darkness" ids (TYPED_ACTION_ID_COLLISION, Mo Anbo 2026-09-29).
        short = row.source_definition_id.split(".")[1]
        options = [[], *[[talent] for talent in shaping["shapes"]]]
        pair = shaping["pair"]
        if pair and pair.get("any"):  # Layered Bouquet: any two different talents
            names_ = list(shaping["shapes"])
            options += [[first, second] for index, first in enumerate(names_) for second in names_[index + 1:]]
        elif pair:
            options += [[pair["with"], talent] for talent in shaping["shapes"] if talent != pair["with"]]
        for talents in options:
            label = " + ".join(shaping["shapes"][talent]["name"] for talent in talents) or f"plain {name}"
            need = zone_shape_costs({"shapes": shaping["shapes"], "pair": pair}, talents)
            key = hashlib.sha256(("|".join(talents) or "plain").encode()).hexdigest()[:8]
            rows = [shaping["shapes"][talent] for talent in talents]
            summary = _shape_summary(rows)
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.shape.{hashlib.sha256(family.encode()).hexdigest()[:8]}.{key}",
                display_name=f"Shape {name}: {label}", owner_id=row.owner_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                target_kind="SELF",
                parameters={"typed": {"effects": [{"type": "shape_zone", "zone": family, "zone_name": name, "talents": talents, "label": label}],
                                      "numbers": typed.get("numbers") or {}, "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "player_only": True, "setting_only": True, "zone_shape": family, "zone_name": name, "shape_talents": talents,
                            "shape_label": label, "shape_costs": need, "shape_default": talents == shaping["default"],
                            "shape_of": row.source_definition_id, "shape_summary": summary,
                            "shape_partial": any(not row_["triggers"] and not row_["inside"] and not row_.get("move_through") for row_ in rows)}))
    return out


def _shape_summary(rows: list[dict[str, Any]]) -> str:
    """What the chosen talents do, in a few words for the sheet ("Enter/start: CON save; Inside: Disadvantage on STR/DEX/CON
    saves & checks"); the rules text is on hover."""
    moments = {"enter": "enter", "start": "start"}
    parts = []
    for row in rows:
        for trigger in row["triggers"]:
            saves = sorted({f"{str(effect.get('ability') or '').upper()} save" for effect in trigger["effects"] if effect.get("type") == "save"})
            parts.append(f"{' or '.join(moments.get(on, on) for on in trigger['on']).capitalize().replace(' or starting a turn in it', '/start')}: "
                         f"{' or '.join(saves) or 'an effect'}")
        for rule in row["inside"]:
            modes: dict[str, list[str]] = {}
            for code, mode in (rule["rule"].get("save_mode") or {}).items():
                modes.setdefault(mode, []).append(code)
            checks = bool(rule["rule"].get("check_mode"))
            text = [f"{mode.title()} on {'/'.join(codes)} saves{' & checks' if checks else ''}" for mode, codes in modes.items()]
            if rule.get("muffles"):
                text.append("sound dimmed")
            parts.append(f"Inside: {'; '.join(text)}")
    return "; ".join(parts)


def zone_shape_costs(spec: dict[str, Any], talents: list[str]) -> dict[str, int]:
    from .zones import shape_costs

    return shape_costs(spec, talents)


_INSIDE_ABILITY_WORDS = (("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"), ("intelligence", "INT"), ("wisdom", "WIS"),
                         ("charisma", "CHA"))


def _rules_text() -> dict[str, str]:
    cached = globals().get("_RULES_TEXT_CACHE")
    if cached is None:
        path = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "rules_text.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        globals()["_RULES_TEXT_CACHE"] = cached
    return cached


_BUILD_CHOICE = re.compile(r"^(When you learn |When you (?:first )?gain the \w[\w -]* sphere, (?:choose|gain proficiency)|At (?:each listed CL|CL\d+), choose one|Choose one |When you enter [^.]{0,60}Realm[^.]*\.[^.]*\bChoose one)")
# Talents the compiler runs in its own code rather than through typed effects (the weapon pairing above).
HANDLED_IN_CODE = frozenset({"TAL_DUAL_WIELDING_GREATER_BLADES", "TAL_DUAL_WIELDING_AMBIDEXTERITY", "TAL_DUAL_WIELDING_PAIRED_RHYTHM",
                             "TAL_DUAL_WIELDING_SYNCHRONOUS_ACCURACY", "TAL_DUAL_WIELDING_FOLLOWING_STRIKE", "TAL_DUAL_WIELDING_TANDEM_OFFENSIVE",
                             "TAL_DUAL_WIELDING_TWIN_WEAPON_TRAINING"})
FEATURE_STATUS = Path(__file__).resolve().parent / "rules" / "feature_status.json"


def feature_status() -> dict[str, dict[str, str]]:
    """combat/rules/feature_status.json (owner-editable): features that are not fight mechanics, and why; every
    combat/rules/feature_status.d/*.json merged in."""
    extra = sorted((FEATURE_STATUS.parent / "feature_status.d").glob("*.json"))
    stamp = (FEATURE_STATUS.stat().st_mtime_ns if FEATURE_STATUS.is_file() else 0, tuple((path.name, path.stat().st_mtime_ns) for path in extra))
    cached = globals().get("_FEATURE_STATUS_CACHE")
    if not cached or cached[0] != stamp:
        data = dict(json.loads(FEATURE_STATUS.read_text(encoding="utf-8")).get("features") or {}) if stamp[0] else {}
        for path in extra:
            data.update(json.loads(path.read_text(encoding="utf-8")).get("features") or {})
        cached = (stamp, data or {})
        globals()["_FEATURE_STATUS_CACHE"] = cached
    return cached[1]


def _sorted_skipped(skipped: dict[str, list[str]], actions: list[ActionDefinition], owned: list[str], mechanics: dict[str, Any]) -> dict[str, list[str]]:
    """The sheet's "not automated yet" lists, honest (owner 2026-09-28: "still a bunch of stuff thats getting skipped"):
    an area talent the fight runs as a shape of its area (Numbing Darkness), and Clearsight, are not skipped; a choice
    made when the character is built (a Subpath, an Ability Score Improvement, a sphere's Training grants) is listed as
    "build" -- its result is already in the build; a ritual is "outside" fights."""
    shaped = {str(shape.get("name")) for row in actions for shape in ((((row.parameters or {}).get("typed") or {}).get("zone_spec") or {}).get("shapes") or {}).values()
              if shape.get("triggers") or shape.get("inside") or shape.get("move_through")}
    shaped |= {str(mechanics[mid].get("name")) for mid in owned if mid in mechanics
               and re.search(r"immune to negative effects created by your", _rules_text().get(mid) or "", re.I)}
    shaped |= {str(mechanics[mid].get("name")) for mid in owned if mid in mechanics and mid in HANDLED_IN_CODE}
    # An ability whose whole effect is the area it leaves (Darkness) has no typed effects but runs as a zone.
    shaped |= {str((mechanics.get(str(typed.get("option_of") or typed.get("source") or "")) or {}).get("name"))
               for row in actions for typed in [((row.parameters or {}).get("typed") or {})] if typed.get("zone_spec")}
    listed = feature_status()
    labels: dict[str, str] = {}  # name -> status, from the owner-editable file first
    for mid in owned:
        if mid in mechanics and mid in listed:
            labels.setdefault(str(mechanics[mid].get("name")), str(listed[mid].get("status") or ""))
    for mid in owned:
        if mid in mechanics:
            name = str(mechanics[mid].get("name"))
            if _BUILD_CHOICE.match(_gm_text(mid, 400)):
                labels.setdefault(name, "build")
            elif (mechanics[mid].get("activation") or {}).get("economy") == "ritual":
                labels.setdefault(name, "outside")
    out = {**skipped}
    sorted_out: dict[str, list[str]] = {"build": [], "outside": [], "definition": [], "table": []}
    for kind in ("passive", "reaction", "not_typed"):
        kept = []
        for name in skipped.get(kind) or []:
            status = labels.get(name)
            if name in shaped or status == "applied":
                continue
            if status in sorted_out:
                sorted_out[status].append(name)
            else:
                kept.append(name)
        out[kind] = kept
    return {**out, **sorted_out}


def _gm_text(mechanic_id: str, limit: int = 420) -> str:
    """An ability's printed text without its heading, shortened for a log line."""
    lines = str(_rules_text().get(mechanic_id) or "").splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        lines.pop(0)
    text = " ".join(" ".join(lines).replace("*", "").replace("#", "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _talent_tags(mechanic_id: str) -> list[str]:
    """The kinds a talent's printed heading gives it ("### Numbing Darkness - Darkness"; "Shadow Tag - Darkness, Meld")."""
    head = (_rules_text().get(mechanic_id) or "").split("\n", 1)[0]
    match = re.match(r"#+\s*(.+?)\s+-\s+(.+)$", head.strip())
    return [tag.strip() for tag in match.group(2).split(",")] if match else []


def _one_per(mechanic_id: str, mechanic: dict[str, Any]) -> dict[str, Any] | None:
    """The rule of a talent category of which only one applies to one use ("apply only one Response talent to one successful
    Flowing Response"; combat/rules/talent_categories.json), when this talent's printed heading puts it in one."""
    table = globals().get("_TALENT_CATEGORIES")
    if table is None:
        path = Path(__file__).resolve().parent / "rules" / "talent_categories.json"
        table = json.loads(path.read_text(encoding="utf-8")).get("one_per") or {} if path.is_file() else {}
        globals()["_TALENT_CATEGORIES"] = table
    rules_ = {tag.lower(): rule for tag, rule in (table.get(str(mechanic.get("sphere_id") or "")) or {}).items()}
    return next((rules_[tag.lower()] for tag in _talent_tags(mechanic_id) if tag.lower() in rules_), None) if rules_ else None


def _inside_rules(linked_id: str, linked: dict[str, Any]) -> list[dict[str, Any]]:
    """What an area talent does to creatures while they are inside ("Creatures inside your Darkness have Disadvantage on
    Strength, Dexterity, and Constitution ability checks and saving throws"; Pure Darkness's dimmed sound)."""
    rule: dict[str, Any] = {}
    muffles, readings = False, []
    for effect in _walk(linked.get("effects") or []):
        if effect.get("applies_to") != "creatures_in_area" or effect.get("type") not in ("advantage", "disadvantage"):
            continue
        on = str(effect.get("on") or "")
        if re.search(r"\bescape\b|\bmade to\b", on, re.I):
            continue  # a narrow case (Shadow Slick: "Dexterity checks made to escape the Grappled condition") is the GM's
        mode = str(effect["type"]).upper()
        abilities = [code for word, code in _INSIDE_ABILITY_WORDS if re.search(rf"\b{word}\b", on, re.I)]
        if abilities and re.search(r"saving throws?", on, re.I):
            rule.setdefault("save_mode", {}).update({code: mode for code in abilities})
        if abilities and re.search(r"ability checks?", on, re.I):
            rule.setdefault("check_mode", {}).update({code: mode for code in abilities})
        if re.search(r"perception[^.]*hearing", on, re.I):
            muffles = True
        readings.append(str(effect.get("evidence") or on))
    if not rule and not muffles:
        return []
    return [{"id": linked_id, "name": linked.get("name"), "who": "any", "rule": rule, "muffles": muffles, "reading": " ".join(readings)}]


# What a printed clause spends, requires or scales with is not what the area does to the creatures standing in it --
# the same material _gm_lines drops from an action's rider, dropped here for the same reason.
_NOT_A_CLAUSE = re.compile(r"^(?:#{1,6}\s|\*?\*?(?:Prerequisite|Requirement|Cost|Duration|Tags?|Tag|Note|Time|Action Type|"
                           r"Timing Detail|Type|Available At|Trigger|Range|Target|Effect|Size|AC|Hit Points|Attack or Save|"
                           r"Cultivation Level|Damage)\b|\s*\|)", re.I)
# A list label ("Inside the area:", "Allies") rather than a clause: the clauses under it are what the player reads.
_CLAUSE_LEAD = re.compile(r":$")
# The outcome half of a check the print already speaks for elsewhere ("Failed Check: Fall Prone." answers a rolled
# check whose own sentence the table shows), so it is not shown twice and never shown on its own.
_CLAUSE_OUTCOME = re.compile(r"^(?:(?:Failed|Successful|Unsuccessful|Success|Failure)\b[^.:]{0,30}:|On (?:a|an) (?:success|failure)\b)", re.I)
# A paid second copy of the talent, not a standing rule about the creatures inside it ("Augment - 1 CP: ...",
# "If you purchase Disorienting Darkness a second time, gain both augments below"): the paid option and the "If no
# other legal target exists" sentences that finish it are the buyer's business, not the area's.
_CLAUSE_PURCHASE = re.compile(r"^(?:Augment\b|If you (?:purchase|buy)\b|You (?:purchase|buy)\b)", re.I)
# A conditional that continues the dropped clause before it ("If no other legal target exists, the action is
# unaffected"), never a rule of its own.
_CLAUSE_CONTINUES = re.compile(r"^If\b", re.I)
_CLAUSE_VERB = re.compile(r"\b(?:is|are|was|were|be|become[sd]?|gain[sd]?|lose[sd]?|cannot|may|must|has|have|do|does|will|"
                          r"would|can|deal[sd]?|take[sd]?|make[sd]?|suffer[sd]?|fail[sd]?|succeed[sd]?|move[sd]?|attack[sd]?|"
                          r"enter[sd]?|start[sd]?|begin[s]?|end[s]?|reduces?|reduced|halves?|halved|doubled|instead|"
                          r"creatures?|allies?|enemies?|targets?|anyone|each|every|any|while|when|whenever|as long as)\b", re.I)
# A note about a second way of using the talent, not a rule about the creatures in the area (Shadow Tag on a Darkness
# card: "As a Meld talent, apply the same effect directly to one creature."). Keys on the printed form every talent
# uses, never on a talent id.
_NOT_AN_AREA_RULE = re.compile(r"^As an?\s[\w\s]{0,20}talent,", re.I)
_MIN_CLAUSE_CHARS = 12      # shorter than this is a fragment, not something a player can act on
_MIN_COVERED_CHARS = 20     # a carried fragment this long is evidence the print has already been spoken for


def _plain_clause(text: str) -> str:
    """A printed clause as the player reads it: no markdown, no list bullet, no doubled spaces."""
    clause = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", str(text or ""))
    return " ".join(clause.replace("*", "").replace("#", "").replace("`", "").split())


def _carried_clauses(linked_id: str, linked: dict[str, Any]) -> list[str]:
    """What a creature standing in the area is already shown by the area's own standing rules, in the fight's own words,
    so the leftover printed clauses are only the ones with no other place to appear.

    Only the standing surfaces count: the mechanical inside rows the zone card reads, and the ground rule it turns into
    ``trigger_profile["difficult"]``. The evidence of an effect that only ever fires as a trigger rider is deliberately
    NOT subtracted -- that is a ruling shown at the moment the trigger fires, not a rule the card tells a standing
    creature about. Subtracting it anyway was how Calming Perfume's "A hostile creature inside has Disadvantage on
    Charisma (Intimidation) checks" came off the card while appearing on no surface the player is shown (MMX114
    independent review, finding 2).
    """
    texts = [str(row.get("reading") or "") for row in _inside_rules(linked_id, linked)]
    texts += [str((_left_terrain(_texts(linked)) or {}).get("sentence") or "")]
    return [" ".join(part.split()).lower() for text in texts for part in re.split(r"(?<=[.;])\s+|\n", text)
            if len(" ".join(part.split())) >= _MIN_COVERED_CHARS]


def _already_carried(clause: str, carried: list[str]) -> bool:
    """Whether the fight already says this clause in its own words, so the leftover printed clauses are only the ones
    with no other place to appear."""
    plain = clause.lower()
    return plain in carried or any(fragment in plain for fragment in carried)


def _readable_clauses(block: str) -> list[list[tuple[str, bool]]]:
    """The printed clauses of one block, grouped by the printed line they are printed on, each readable on its own and
    paired with whether it is an outcome clause.

    A printed line is one rule, so a sentence that spells out the consequence of a check never leaves the line the check
    is on (Disorienting Darkness: "Failed Save: Roll 1d8 ... 1 is the intended direction; 2-8 rotate clockwise ... The
    creature moves as though the rolled direction were its intended route."). Grouping by line is what lets the caller
    show that whole conditional rule together, or not at all, rather than showing a bare continuation of a roll the
    player was never told happened. A bare list label ("Inside the area:", "Allies") becomes the lead-in of the clauses
    beneath it instead of an orphan fragment the player would never see.
    """
    out: list[list[tuple[str, bool]]] = []
    lead = ""
    for line in block.split("\n"):
        group: list[tuple[str, bool]] = []
        for unit in re.split(r"(?<=[.;])\s+", line):
            clause = _plain_clause(unit)
            if not clause or _NOT_A_CLAUSE.match(clause) or _NOT_AN_AREA_RULE.match(clause):
                continue
            if _CLAUSE_LEAD.search(clause) or (len(clause.split()) <= 2 and not _CLAUSE_VERB.search(clause)):
                lead = clause
                continue
            outcome = bool(_CLAUSE_OUTCOME.match(clause) or _CLAUSE_PURCHASE.match(clause))
            group.append((f"{lead} {clause}" if lead and not outcome else clause, outcome))
        if group:
            out.append(group)
    return out


def _inside_clauses(linked_id: str, linked: dict[str, Any], name: str) -> list[str]:
    """The printed clauses of an area talent that say what it does to creatures while they are inside, minus the ones
    the table already shows elsewhere (fight audit 2026-10-04, HUNT118 #1: Pure Darkness's "Darkvision is reduced to
    5 feet" and "all other senses ... reduced by half" were in no player text at all).

    General by construction, and keyed on no ability: a printed block under one heading is an inside-clause block when
    any clause in it puts a creature in the area ("inside your Darkness", "Inside the area", "in the Fragrance"), and
    every clause of that block counts. Scoping to the whole block rather than the single sentence is what catches the
    continuation that never repeats the word ("Darkvision is reduced to 5 feet inside your Darkness. / All other senses
    ... reduced by half."). A conditional rule is shown whole or not at all: a "Failed Save: ..." line whose consequence
    is new to the card is shown with its condition, never as the bare continuation of a roll the player was never told
    happened. This is text only: it never adds an effect, a condition or a save.
    """
    printed = str(_rules_text().get(linked_id) or "")
    body = "\n".join(line for line in printed.splitlines() if not re.match(r"^\s*#{1,6}\s", line))
    marker = re.compile(rf"\b(?:inside|within)\b|\b(?:in|within|through(?:out)?)\s+(?:the|your|this|that|an?)\s+{re.escape(name)}\b", re.I)
    carried = _carried_clauses(linked_id, linked)
    out: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        if not marker.search(block):
            continue
        kept: list[str] = []
        # A paid option is the buyer's business, not the area's, and neither is the "If no other legal target exists"
        # sentence that finishes one; it stays open until a line is actually shown.
        purchase_gap = False
        for group in _readable_clauses(block):
            head = group[0][0]
            if _CLAUSE_PURCHASE.match(head):
                purchase_gap = True
                continue
            if purchase_gap and _CLAUSE_CONTINUES.match(head):
                continue
            survivors = [clause for clause, _outcome in group
                         if len(clause) >= _MIN_CLAUSE_CHARS and not _barred_actions(clause)
                         and not _already_carried(clause, carried)]
            if not survivors:
                continue
            if survivors[0] != head and _CLAUSE_OUTCOME.match(head) and len(head) >= _MIN_CLAUSE_CHARS \
                    and not _barred_actions(head) and not _already_carried(head, carried):
                survivors.insert(0, head)
            kept.append(" ".join(survivors))
            purchase_gap = False
        text = " ".join(kept).strip()
        if text:
            out.append(text)
    return out


def _dedupe_saves(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One save per ability and outcome (a talent typed twice: Snagging Darkness's Dexterity save for Restrained)."""
    out, seen = [], set()
    for effect in effects:
        if effect.get("type") == "save":
            key = (str(effect.get("ability") or "").lower(),
                   tuple(sorted(str(row.get("condition") or row.get("type")) for row in effect.get("on_fail") or [] if isinstance(row, dict))))
            if key in seen:
                continue
            seen.add(key)
        out.append(effect)
    return out


def _zone_shapes(name: str, family: str, mechanics: dict[str, Any], owned: list[str], typed: dict[str, Any], row: ActionDefinition,
                 cost_of: Any, pool: str) -> dict[str, Any]:
    """The talents that change an area of this kind (owner 2026-09-27: "numbing darkness isnt showing up in actions"): an
    owned talent printed as one ("### Numbing Darkness - Darkness"), or one whose trigger names the area ("a hostile
    creature entering Ashfall": Soot in the Lungs). Each carries what it does to a creature entering or starting its turn
    inside, and what it does while a creature stays inside. A talent that lets one more apply ("Pitch Black: Apply Pure
    Darkness in addition to one other Darkness talent modifying the same area") makes the pairs. The default -- what an
    area carries until its user chooses, and what the AI's carries -- is the talent that does the most damage, a free one
    first (paid when the area is made; left off if it can't be)."""
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
    shapes: dict[str, Any] = {}
    pair = None
    for linked_id in owned:
        linked = mechanics.get(linked_id)
        if not linked or linked_id == family or (linked.get("activation") or {}).get("economy") in ("action", "bonus_action", "reaction"):
            continue
        text = _rules_text().get(linked_id) or ""
        match = re.search(r"Apply (.+?) in addition to one other (.+?) talent", text, re.I)
        if match and match.group(2).strip().lower() == name.lower():
            pair = {"via": linked_id, "with_name": match.group(1).strip(),
                    "costs": [list(cost) for cost in _talent_costs(linked_id, linked, row, cost_of, pool)]}
            continue
        # "Apply two Fragrance talents to one Fragrance instead of one. Pay the normal cost of both talents. The same
        # Fragrance talent cannot be applied twice." (Layered Bouquet, +2 CP; docket 2026-09-28): any two different ones.
        match = re.search(r"Apply two (.+?) talents to one (.+?) instead of one", text, re.I)
        if match and match.group(1).strip().lower() == name.lower():
            costs = [list(cost) for cost in _talent_costs(linked_id, linked, row, cost_of, pool)]
            printed = re.search(r"\bCost:\s*\+?(\d+)\s*CP\b", text, re.I)
            pair = {"via": linked_id, "any": True, "costs": costs or ([[pool, int(printed.group(1))]] if printed else [])}
            continue
        tags = _talent_tags(linked_id)
        trigger_text = " ".join([str((linked.get("activation") or {}).get("trigger") or ""),
                                 *([str(line) for line in linked.get("description") or []] if isinstance(linked.get("description"), list) else [])])
        tagged = any(tag.lower() in (name.lower(), f"{name.lower()} talent") for tag in tags)
        if not tagged and not pattern.search(trigger_text):
            continue
        if "Augment" in tags:
            continue  # Greater Darkness and the like change the area itself (the ability's own augmented versions)
        body = text.split("\n", 1)[1] if "\n" in text else ""
        moments = [moment for moment, rule in (("enter", _ENTER), ("start", _START)) if rule.search(trigger_text)] or \
            ([moment for moment, rule in (("enter", _ENTER), ("start", _START)) if rule.search(body)] if tagged else [])
        effects = _dedupe_saves([effect for effect in linked.get("effects") or [] if effect.get("applies_to") != "creatures_in_area"
                                 or effect.get("type") not in ("advantage", "disadvantage")])
        triggers = []
        if moments and effects:
            # Who meets it, from the sentence that says when ("A creature that enters ...": anyone; "a hostile creature").
            sentence = next((line for line in re.split(r"(?<=[.!?])\s+|\n", f"{trigger_text}\n{body}") if _ENTER.search(line) or _START.search(line)),
                            trigger_text)
            triggers = [{"id": linked_id, "name": linked.get("name"), "on": moments,
                         "who": "hostile" if re.search(r"\bhostile\b|\benem|\bunwilling\b", sentence, re.I)
                         else "ally" if re.search(r"\ball(?:y|ies)\b|\bwilling\b", sentence, re.I) else "any",
                         "effects": copy.deepcopy(effects),
                         # Hungry Darkness: "may take this damage only once per round" (combat/zones.py _run)
                         **({"per_round": True} if re.search(r"only once per round", text, re.I) else {})}]
        inside = _inside_rules(linked_id, linked)
        # A talent that fills the area so it hides ("the space is Lightly Obscured": Fragrant Veil; docket 2026-09-28).
        veil = "heavy" if re.search(r"\bheavily obscured\b", body, re.I) else "light" if re.search(r"\blightly obscured\b", body, re.I) else None
        if not tagged and not triggers:
            continue
        # What moving through the area does (Shadow Slick: "attempts to move more than half its Speed through the area");
        # typed as a "move_through" effect (combat/zones.py on_moved).
        through = next((copy.deepcopy(effect) for effect in linked.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "move_through"), None)
        clauses = _inside_clauses(linked_id, linked, name)
        shapes[linked_id] = {"name": linked.get("name"), "triggers": triggers, "inside": inside,
                             "costs": [list(cost) for cost in _talent_costs(linked_id, linked, row, cost_of, pool)],
                             **({"inside_text": clauses} if clauses else {}),
                             **({"obscured": veil} if veil else {}), **({"move_through": through} if through else {})}
        # A reviewed shape may state distinct recipient scopes and moments. Keep
        # the talent's compiled name/cost; snapshot its explicit runtime contract
        # instead of inferring one trigger from several unrelated prose clauses.
        explicit = [effect["shape_spec"] for effect in linked.get("effects") or []
                    if effect.get("type") == "zone" and isinstance(effect.get("shape_spec"), dict)]
        if len(explicit) == 1:
            for key in ("triggers", "inside", "obscured"):
                if key in explicit[0]:
                    value = copy.deepcopy(explicit[0][key])
                    if key == "triggers":
                        # These triggers are reviewed data too: keep their
                        # declared roster separate from the derived policy.
                        value = [{**row, **({"roster": str(row["who"]).strip().lower()} if row.get("who") else {})}
                                 if isinstance(row, dict) else row for row in value]
                    shapes[linked_id][key] = value
    if pair and not pair.get("any"):
        partner = next((talent for talent, shape in shapes.items() if str(shape["name"]).lower() == pair["with_name"].lower()), None)
        pair = {"with": partner, "via": pair["via"], "costs": pair["costs"]} if partner else None
    numbers = typed.get("numbers") or {}
    worth = lambda talent: sum(_expected_damage(trigger["effects"], numbers) for trigger in shapes[talent]["triggers"])  # noqa: E731
    firing = [talent for talent, shape in shapes.items() if shape["triggers"]]
    best = max([talent for talent in firing if not shapes[talent]["costs"]] or firing, key=worth, default=None)
    return {"shapes": shapes, "pair": pair, "default": [best] if best else []}


def _talent_costs(linked_id: str, linked: dict[str, Any], row: ActionDefinition, cost_of: Any, pool: str) -> list[tuple[str, int]]:
    costs = [tuple(cost) for cost in cost_of(linked_id, row.source_definition_id)]
    extra = int(((linked.get("modifier") or {}).get("extra_cp")) or 0)
    if not costs and extra:
        costs = [(pool, extra)]
    return [(str(resource), int(amount)) for resource, amount in costs if int(amount)]


def unarmed_strike_weapon(strength: int) -> dict[str, Any]:
    """The 2024 Unarmed Strike's damage: 1 + Strength modifier Bludgeoning, no die (a nominal die with a fixed total, never
    below 0). One payload for every plain unarmed strike: the basic action below, the opportunity attack without a melee
    weapon, a weapon-delivered Strike technique with no fitting weapon, and combat/ext/objects.py's unarmed attack on an
    object. The sealed roller deals ``fixed_damage`` plus
    the die's modifier, so Strength is counted once, in ``fixed_damage`` (hunt 53: a modifier of Strength here dealt
    1 + twice Strength); later damage bonuses add to the modifier as usual."""
    return {"damage": {"count": 1, "sides": 2, "modifier": 0}, "fixed_damage": max(0, 1 + strength),
            "damage_type": "BLUDGEONING", "damage_types": ["BLUDGEONING"]}


def _opportunity_attack(actions: list[ActionDefinition], short: str, actor_id: str, numbers: dict[str, int], pb: int,
                        mods: dict[str, int]) -> ActionDefinition:
    """Owner 2026-09-26: Factory fighters make opportunity attacks -- one attack with their best melee weapon (its
    reach, its mastery, no maneuver or off-hand), or an unarmed strike (1 + Strength modifier) without one."""
    melee = [row for row in actions if row.economy == EconomyKind.ACTION and "#" not in row.source_definition_id
             and not row.parameters.get("requires_held_weapon") and not row.parameters.get("requires_condition")
             and (row.parameters.get("typed") or {}).get("weapon") is not None and not (row.parameters.get("typed") or {}).get("range_ft")]
    per_hit = lambda row: int(row.parameters.get("expected_damage") or 0) / max(1, int(row.parameters["typed"]["effects"][0].get("count") or 1))  # noqa: E731
    best = max(melee, key=lambda row: (per_hit(row), row.source_definition_id), default=None)
    if best is not None:
        typed = copy.deepcopy(best.parameters["typed"])
        typed["effects"][0]["count"] = 1
        typed.pop("opens", None)
        typed["opportunity_of"] = best.source_definition_id
        reach, expected = int(best.range_ft or 5), int(per_hit(best))
    else:
        strength = mods.get("STR", 0)
        typed = {"effects": [{"type": "attack", "attack_kind": "unarmed", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": True}]}],
                 "numbers": {**numbers, "attack_bonus": pb + strength},
                 "weapon": unarmed_strike_weapon(strength),
                 "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": "unarmed_strike"}
        reach, expected = 5, 1 + strength
    return ActionDefinition(source_definition_id=f"action:typed.{short}.opportunity_attack", display_name="Opportunity Attack",
                            owner_id=actor_id, economy=EconomyKind.REACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                            range_ft=reach, parameters={"typed": typed, "expected_damage": expected})


# The printed names of the Unarmed Strike and its 2024 options, and the actions they are (typed "unarmed_option", or a
# natural weapon's attack).
_CORE_TARGETS = {"unarmed strike": ("natural", "grapple", "shove_push", "shove_prone"), "unarmed strikes": ("natural", "grapple", "shove_push", "shove_prone"),
                 "grapple": ("grapple",), "grapple option": ("grapple",), "shove": ("shove_push", "shove_prone"), "shove option": ("shove_push", "shove_prone"),
                 "melee weapon attack": ("melee_weapon",), "melee weapon attacks": ("melee_weapon",)}

# Only additive hit riders can move their payment after the roll. Geometry,
# replacement attacks, augment traits and future unknown fields retain variants.
_PAID_HIT_FIELDS = {"schema", "source", "targets", "scope", "when", "optional", "limit", "group", "precondition",
                    "extra_cp", "martial_focus", "cost", "effects", "options", "_choice"}


def _core_modifier_pass(actions: list[ActionDefinition], owned: list[str], mechanics: dict[str, Any], primary: str, pools: Any, *,
                        automated: set[str], foundation_resource: Any, actor_id: str, numbers: dict[str, Any]) -> tuple[list[ActionDefinition], list[dict[str, Any]]]:
    """Apply reviewed modifiers to core unarmed options and each melee weapon.

    Generic printed targets select delivery categories. Paid melee hit riders
    become transactional per-hit choices; other modifiers remain variants.
    No weapon target data means no weapon changes. See ext/__init__.py.
    """
    # Explicit structured attack selectors apply to native weapon actions too,
    # which are compiled outside the sphere-action dictionary.
    selectors = {mid for mid in dict.fromkeys(owned)
                 if mid not in automated and
                 ((mechanics.get(mid) or {}).get("modifier") or {}).get("scope") == "attack_or_sphere_technique"}
    wanted = [mid for mid in dict.fromkeys(owned) if mid not in automated and
              (mid in selectors or any(_norm_name(target) in _CORE_TARGETS
               for target in ((mechanics.get(mid) or {}).get("modifier") or {}).get("targets") or []))]
    if not wanted:
        return actions, []
    weapon_targets = any(_norm_name(target) in ("melee weapon attack", "melee weapon attacks")
                         for mid in wanted for target in mechanics[mid]["modifier"].get("targets") or [])
    roles: dict[str, str] = {}
    for action in actions:
        typed = (action.parameters or {}).get("typed") or {}
        role = typed.get("unarmed_option") or ("natural" if ".natural." in action.source_definition_id else None)
        if ((weapon_targets or selectors) and role is None and typed.get("weapon")
                and (selectors or not typed.get("range_ft")) and not typed.get("variant_of")
                and not typed.get("delivered_by")
                and any(e.get("type") == "attack" and e.get("attack_kind") == "weapon" for e in typed.get("effects") or [])):
            category = "ranged_weapon" if typed.get("range_ft") else "melee_weapon"
            role = f"{category}:{action.source_definition_id}"
        if role and role not in roles.values() and action.owner_id == actor_id:
            roles[action.source_definition_id] = role
    if not roles:
        return actions, []
    fake = {name: f"core:{name}" for name in _CORE_TARGETS}
    built: dict[str, dict[str, Any]] = {}
    for action in actions:
        role = roles.get(action.source_definition_id)
        if role is None:
            continue
        key = f"core-built:{role}"
        built[key] = {"action_id": action.source_definition_id, "name": action.display_name,
                      "economy": "action" if action.economy == EconomyKind.ACTION else "bonus_action", "target_kind": action.target_kind,
                      "range_ft": action.range_ft, "costs": list(action.costs), "typed": copy.deepcopy(action.parameters["typed"]),
                      "mechanic": {"name": action.display_name, "sphere_id": None, "duration": {"kind": "instant"}}, "modifiers": [], "variants": [],
                      "_action": action}
    core_mechanics = {**mechanics, **{core_key: {"name": name.title(), "sphere_id": None} for name, core_key in fake.items()}}
    # The core pass has explicit delivery-category targets, not Sphere actions.
    # Resolve those names through option_index even when the same modifier uses
    # any_attack for its Sphere abilities. A Sphere filter otherwise drops every
    # core weapon (whose sphere_id is None). Keep authority and the Sphere pass
    # untouched; only this delivery adapter narrows to its declared categories.
    for mid in wanted:
        mechanic = core_mechanics[mid]
        modifier = mechanic['modifier']
        core_mechanics[mid] = {**mechanic, 'modifier': {
            **modifier, 'scope': 'named',
            'targets': [target for target in modifier['targets'] if _norm_name(target) in _CORE_TARGETS]}}
    rows = []
    # "When you hit with an Unarmed Strike" changes the strike itself; "when a creature fails the saving throw against your
    # Unarmed Strike's Grapple or Shove option" changes those options -- never the other way round (owner 2026-09-28).
    for saves, group in ((False, [mid for mid in wanted if (mechanics[mid]["modifier"].get("when") or "use") != "failed_save"]),
                         (True, [mid for mid in wanted if mechanics[mid]["modifier"].get("when") == "failed_save"])):
        if not group:
            continue
        option_index = {core_key: [f"core-built:{role}" for category in _CORE_TARGETS[name] for role in roles.values()
                                   if role.split(":", 1)[0] == category
                                   and ((role != "natural" and not role.startswith("melee_weapon:")) == saves
                                        or name in ("grapple", "grapple option", "shove", "shove option"))]
                        for name, core_key in fake.items()}
        earlier = {key: list(row["variants"]) for key, row in built.items()}  # apply_modifiers starts each ability's list afresh
        rows += apply_modifiers(built, [*group, *fake.values()], core_mechanics, primary, pools, automated=automated,
                                foundation_resource=foundation_resource, option_index=option_index)
        for key, row in built.items():
            row["variants"] = [*earlier.get(key, []), *row["variants"]]
    out = []
    for action in actions:
        role = roles.get(action.source_definition_id)
        if role is None:
            out.append(action)
            continue
        row = built[f"core-built:{role}"]
        hit_choices: dict[str, dict[str, Any]] = {}
        remaining = []
        for variant in row["variants"]:
            composition = variant.get("_compose") or {}
            modifier = composition.get("modifier") or {}
            if (role.startswith("melee_weapon:") and composition.get("when") == "hit"
                    and _pays(modifier) and not modifier.get("precondition")
                    and modifier.get("limit") in (None, "none") and not modifier.get("group")
                    and composition.get("added") and not composition.get("traits")
                    and all(field in _PAID_HIT_FIELDS or not value for field, value in modifier.items())):
                key = composition["key"]
                choice = hit_choices.setdefault(key, {"id": key, "name": mechanics[key]["name"], "options": []})
                costs: dict[str, int] = {}
                for resource, amount in variant["costs"]:
                    costs[resource] = costs.get(resource, 0) + amount
                for resource, amount in action.costs:
                    costs[resource] = costs.get(resource, 0) - amount
                choice["options"].append({"id": variant["action_id"], "label": variant["name"].split(" + ", 1)[-1],
                    "costs": [[resource, amount] for resource, amount in costs.items() if amount > 0],
                    "effects": copy.deepcopy(composition["added"])})
            else:
                remaining.append(variant)
        if hit_choices:
            row["typed"]["paid_hit_choices"] = list(hit_choices.values())
            for group in row["typed"].get("attack_modifier_loadout") or []:
                if group["id"] in hit_choices:
                    group["legacy_paid"] = True
        # Weapon damage lives in typed.weapon, not the effect list. Preserve its
        # established AI score when the pass only adds post-hit choice metadata
        # (and when an unrelated core option has no matching modifier).
        expected = (action.parameters.get("expected_damage", 0)
                    if row["typed"]["effects"] == action.parameters["typed"]["effects"]
                    else _expected_damage(row["typed"]["effects"], numbers))
        out.append(action.model_copy(update={"parameters": {**action.parameters, "typed": row["typed"],
                                                             "expected_damage": expected}}))
        for variant in remaining:
            extra = {key: value for key, value in action.parameters.items() if key not in ("typed", "expected_damage")}
            made = _action_definition(variant, actor_id, numbers)
            if not ((variant.get("_compose") or {}).get("modifier") or {}).get("economy"):
                made = made.model_copy(update={"economy": action.economy})
            out.append(made.model_copy(update={"parameters": {**extra, **made.parameters}}))
    return out, [row for row in rows if row.get("id") in wanted]


def _unarmed_options(opportunity: ActionDefinition, short: str, actor_id: str, pb: int, mods: dict[str, int], attacks: int, *,
                    shield: bool, pick_up: str) -> list[ActionDefinition]:
    """Owner 2026-09-26 (2024 Unarmed Strike options): Grapple and Shove replace one attack of the Attack action; the
    target (no more than one size larger) makes a Strength or Dexterity save against 8 + Strength + PB. Grapple needs a
    free hand, queried at runtime through the shared occupancy plug-in. Also taking up someone else's
    dropped weapon within 5 ft."""
    follow = copy.deepcopy(opportunity.parameters["typed"])
    rest = [{**follow["effects"][0], "count": attacks - 1}] if attacks > 1 else []
    per_hit = int(opportunity.parameters.get("expected_damage") or 0)
    # The save is the Shove/Grapple's own: DC 8 + Strength + PB, never the template's weapon save DC. The attacks
    # that follow it are the *remaining attacks of the same Attack action*, and those keep the template's own
    # delivery -- its attack_bonus, attack_kind, weapon damage, damage ability, enchantments and mastery. They may
    # therefore be weapon attacks (2024 Attack action: make a weapon attack, an Unarmed Strike, Grapple or Shove,
    # one per attack), so overwriting attack_bonus with the unarmed bonus would pair a weapon's damage with an
    # unrelated to-hit. The template already falls back to the unarmed strike (pb + Strength, 1 + Strength) when
    # no melee weapon is in hand (:3330), so an unarmed character's remaining attacks are unarmed already.
    base = {**follow, "attack_action": True, "numbers": {**follow["numbers"], "save_dc": 8 + pb + mods.get("STR", 0)}}
    # Extra Attack follow-ups still use the delivering weapon. Retain its
    # general identity so execution-time equipment queries can check them
    # after the Grapple/Shove resolves, without gating the unarmed option.
    if source_weapon := base.pop("opportunity_of", None):
        base["weapon_source_id"] = source_weapon

    def option(key: str, name: str, on_fail: list[dict[str, Any]]) -> ActionDefinition:
        attempt = {"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1, "on_fail": on_fail}
        return ActionDefinition(source_definition_id=f"action:typed.{short}.unarmed.{key}", display_name=name, owner_id=actor_id,
                                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                                parameters={"typed": {**base, "effects": [attempt, *copy.deepcopy(rest)], "unarmed_option": key},
                                            "expected_damage": per_hit * (attacks - 1)})

    out = [option("shove_push", "Shove: Push 5 ft", [{"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}]),
           option("shove_prone", "Shove: Prone", [{"type": "condition", "condition": "prone", "applies_to": "target"}])]
    out.append(option("grapple", "Grapple", [{"type": "condition", "condition": "grappled", "applies_to": "target", "until_escape": True}]))
    out.append(ActionDefinition(
        source_definition_id=f"action:typed.{short}.take_weapon", display_name="Take a dropped weapon", owner_id=actor_id,
        economy=EconomyKind[pick_up], resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "take_weapon"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    # Catalog policy marker for the shared equipment plug-in,
                    # including initially unarmed actors who later take gear.
                    # Historical bundles remain immutable and unmarked.
                    "equipment_hands_model": 1,
                    "expected_damage": 0, "requires_dropped_nearby": True}))
    return out



def _one_handed_melee(weapon: dict[str, Any]) -> bool:
    properties = weapon["properties"]
    return not _has_property(properties, "Two-Handed") and not re.search(r"\bRange \d", properties) and "ammunition" not in properties.lower()


def _qualifying_pair(weapons: list[dict[str, Any]], pairable: list[int]) -> bool:
    """Two one-handed melee weapons that pair, or one Paired weapon (its own twin)."""
    melee = [index for index in pairable if index < len(weapons) and _one_handed_melee(weapons[index])]
    return len(melee) >= 2 or any(_has_property(weapons[index]["properties"], "Paired") for index in melee)


def _mastery_allowed(rules: dict[str, Any], item_id: str, proficient: bool, spheres: set[str]) -> bool:
    """Owner 2026-09-26: a weapon's mastery needs a feature granting it -- the Weapons Sphere for every weapon, a
    specialist Sphere (Sword, Spear, Sabers, Axes, Chains, Sniper, Monkey Style) for its own family."""
    requirement = rules.get("mastery_requires")
    if requirement != "sphere":
        return _meets(requirement, proficient)
    if not proficient:
        return False  # a mastery is used with a weapon one is trained with
    name = item_id.split(".")[-1]
    groups = (rules.get("proficiency") or {}).get("groups") or {}
    for sphere, group in (rules.get("mastery_spheres") or {}).items():
        members = "*" if group == "any" else groups.get(group, [])
        if sphere in spheres and (members == "*" or name in members):
            return True
    return False


_METHOD_SYNONYMS = {"hook": "hooking", "pin": "pinning", "disarm": "disarming"}


def _weapon_words(rules: dict[str, Any], item_id: str, properties: str) -> set[str]:
    """What a Weapon Method's requirement can name: the Item Book tags and properties, plus the weapon's kind."""
    from factory_authoring.starting_kits import _authorities

    info = _authorities()[1].get(item_id) or {}
    words = {tag.strip().lower() for tag in str(info.get("tags") or "").split(",") if tag.strip()}
    for prop in properties.split(","):
        prop = re.sub(r"\s+Method$", "", prop.strip())
        prop = re.sub(r"\s*\(.*?\)|\s+\d+(?:/\d+)?$", "", prop).strip()
        if prop:
            words.add(prop.lower())
    words |= {_METHOD_SYNONYMS[word] for word in list(words) if word in _METHOD_SYNONYMS}
    family = str(info.get("weapon_family") or "")
    name = item_id.split(".")[-1]
    groups = (rules.get("proficiency") or {}).get("groups") or {}
    words |= {kind for kind, test in (("long", family.startswith("Long")), ("projectile", family.startswith("Projectile")),
                                      ("staff", name in groups.get("staff", [])), ("staff-like", name in groups.get("staff", [])),
                                      ("spear", name in groups.get("spear", [])), ("fork", name in ("cha_hu_cha", "duan_cha")),
                                      ("polearm", name in groups.get("polearm", []))) if test}
    return words


def _weapon_methods(rules: dict[str, Any], item_id: str, properties: str) -> list[tuple[str, dict[str, Any]]]:
    words = _weapon_words(rules, item_id, properties)
    return [(name, method) for name, method in (rules.get("weapon_methods") or {}).items()
            if isinstance(method, dict) and words & {str(word).lower() for word in method.get("requires") or []}]


def _method_rider(method: dict[str, Any], *, damage_type: str, key: str) -> dict[str, Any]:
    """One Weapon Method on the Attack action's first hit (typed_executor.block_weapon_method, once per turn)."""
    def fill(rows: list[Any]) -> list[Any]:
        text = json.dumps(rows).replace("<weapon_damage_type>", damage_type).replace("<weapon>", key)
        return json.loads(text)

    effects = fill(method.get("effects") or [])
    if method.get("save"):
        effects = [{"type": "save", "ability": str(method["save"]).upper(), "on_fail": fill(method.get("on_fail") or []),
                    **({"advantage_if_larger": int(method["advantage_if_larger"])} if method.get("advantage_if_larger") is not None else {})}]
    if method.get("kind") == "major":
        effects = [{"type": "spend_resource", "resource_id": RESOURCE_IDS["martial_focus"], "flat": 1, "applies_to": "self"}, *effects]
    return {"type": "weapon_method", "first_hit_only": True, "effects": effects}


def _improvised_proficient(owner_sheet: dict[str, Any], ids: list[str]) -> bool:
    """Proficiency with improvised weapons: a grant naming the "improvised" group (Jester, Drunken Style, Monkey Style,
    Dual Wielding's Mixed Defense), in combat/rules/weapon_specials.json."""
    rules = _weapon_rules().get("proficiency") or {}
    owned = set(ids) | set((owner_sheet.get("spheres_and_talents") or {}).get("sphere_record_ids") or [])
    return any(key in owned and "improvised" in _grant_groups(grant) for key, grant in (rules.get("grants") or {}).items())


def _grant_groups(grant: dict[str, Any]) -> list[str]:
    group = grant.get("group")
    return [str(name) for name in group] if isinstance(group, list) else [str(group)]


def _improvised_weapon(short: str, actor_id: str, numbers: dict[str, int], pb: int, mods: dict[str, int], attacks: int, *,
                       proficient: bool) -> list[ActionDefinition]:
    """Owner 2026-09-26: "grabbing a stick or a table leg or a brass vase or whatever is usable". 2024 Improvised
    Weapons: 1d4 of a fitting type (Bludgeoning here), no proficiency bonus unless a feature grants it, thrown 20/60.
    Grabbing one is the turn's free object interaction; a thrown one is gone. The maps have no loose objects yet, so
    something is always at hand."""
    strength = mods.get("STR", 0)
    to_hit = strength + (pb if proficient else 0)
    weapon = {"damage": {"count": 1, "sides": 4, "modifier": strength}, "damage_type": "BLUDGEONING", "damage_types": ["BLUDGEONING"]}
    hit = [{"type": "damage", "weapon_damage": True}]
    def typed(effects: list[dict[str, Any]], *, attack_delivery: str = "melee", **extra: Any) -> dict[str, Any]:
        return {"effects": effects, "numbers": {**numbers, "attack_bonus": to_hit},
                "weapon": {**weapon, "attack_delivery": attack_delivery}, "duration": {"kind": "instant"},
                "riders": [], "source": "improvised_weapon", "proficient": proficient, "mundane": True, **extra}
    held = {"requires_condition": "condition:typed.improvised"}
    from .object_interaction import FLAG
    return [
        ActionDefinition(source_definition_id=f"action:typed.{short}.improvised.grab", display_name="Grab an improvised weapon",
                         owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                         parameters={"typed": typed([{"type": "grab_improvised"}]), "expected_damage": 0,
                                     "requires_absent_condition": "condition:typed.improvised", "blocked_by_turn_flag": FLAG, "free_primary": True}),
        ActionDefinition(source_definition_id=f"action:typed.{short}.improvised.attack", display_name="Improvised weapon attack",
                         owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                         parameters={"typed": typed([{"type": "attack", "attack_kind": "weapon", "count": attacks, "on_hit": hit}], range_ft=None),
                                     "expected_damage": attacks * (2 + strength), **held}),
        ActionDefinition(source_definition_id=f"action:typed.{short}.improvised.thrown", display_name="Improvised weapon thrown",
                         owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
                         parameters={"typed": typed([{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": hit},
                                                     {"type": "remove_condition", "condition": "improvised", "applies_to": "self"}],
                                                    range_ft=20, long_range_ft=60, attack_delivery="ranged"),
                                     "expected_damage": 2 + strength, **held}),
    ]


def _spends_reaction(row: dict[str, Any]) -> bool:
    """Whether a reaction row uses the character's Reaction (a Foundation's free trigger and a
    "no Reaction" save rescue do not)."""
    if row.get("block") == "generic":
        return not row.get("free")
    if row.get("block") == "save_rescue":
        return bool(row.get("reaction", True))
    return True


def _player_decision(row: dict[str, Any]) -> bool:
    """Reaction plans also govern optional paid triggers that use no Reaction."""
    return _spends_reaction(row) or bool(row.get("optional"))


# When each reaction answers (for the sheet's ordering list): the attack sequence is attack declared ->
# hit -> damage; the rest answer their own events.
_REACTION_WHEN = {
    "attacked": "when an attack is declared against you", "hit": "when you are hit", "missed": "when an attack misses you",
    "damaged": "when you take damage", "save": "on a saving throw", "ally_attacked": "when an ally is attacked",
    "ally_hit": "when an ally is hit", "ally_missed": "when an attack misses an ally", "ally_damaged": "when an ally takes damage",
    "drop_to_zero": "when you would drop to 0 HP", "bloodied": "when you are bloodied", "condition_gained": "when you would gain a condition",
    "critical_hit": "on a critical hit against you", "natural_1": "when an attacker rolls a 1", "technique_targets": "when a technique targets you",
    "technique_used": "when a technique is used", "hit_ac": "when you are hit", "damage_soak": "when you take damage",
    "opportunity": "when an enemy leaves your reach",
    "damage_reduction": "when you take damage", "save_rescue": "when you fail a saving throw",
}
# Auto's own order, the starting point when the owner switches to an order of their own: what soaks the
# damage first, then what turns a hit into a miss, then what fires before the roll, then the rest.
_AUTO_RANK = {"damage_soak": 0, "damage_reduction": 0, "damaged": 0, "hit_ac": 1, "hit": 1, "attacked": 2}


def _reaction_kind(row: dict[str, Any]) -> str:
    return str(row.get("kind") if row.get("block") == "generic" else row.get("block"))


def _reaction_plan(reactions: list[dict[str, Any]], plan: dict[str, Any] | None,
                   mechanics: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Which reactions the character uses and in what order of importance (owner 2026-09-26: "having
    multiple you can hold up and order of importance ... some dont apply"). ``plan`` is Auto (empty) or
    {"order": [ids, most important first], "off": [ids]}; the first version's {"hold": id} is "that one
    first, the rest off". A reaction set to off is held back; the others get a ``priority`` rank that
    combat/typed_reactions.py follows: at one moment the higher rank is tried first, and a lower-ranked
    reaction waits when a higher-ranked one can still answer the same attack later. Mandatory free
    triggers are never ranked or held back; optional paid triggers share the consent plan without
    spending a Reaction. Auto leaves the rows alone (its own rules are in typed_reactions.py).
    ``plan["options"]`` ({id: option index}, step 14) is read by _generic_reaction in either mode; the returned
    plan lists each "Choose one" reaction's menu and the option it runs. {"ask": true} is Ask me (step 16)."""
    names: dict[str, str] = {}
    kinds: dict[str, str] = {}
    menus: dict[str, dict[str, Any]] = {}
    for row in reactions:
        if _player_decision(row) and row.get("feature_id"):
            key = row["feature_id"]
            names.setdefault(key, row.get("name") or (mechanics.get(key) or {}).get("name")
                             or key.rsplit(".", 1)[-1].replace("_", " ").title())
            kinds.setdefault(key, _reaction_kind(row))
            if row.get("option_labels"):
                # A "Choose one" reaction's menu and the option it runs (step 14), changeable in the plan.
                menus.setdefault(key, {"options": list(row["option_labels"]), "option": row.get("option")})
    plan = dict(plan or {})
    if plan.get("hold") and not plan.get("order"):
        # A hold the character no longer has (a talent changed) is Auto, not "everything off".
        plan = {"order": [plan["hold"]], "off": [key for key in names if key != plan["hold"]]} if plan["hold"] in names else {}
    ask = bool(plan.get("ask"))
    order = [] if ask else [key for key in dict.fromkeys(plan.get("order") or []) if key in names]
    off = [] if ask else [key for key in names if key in set(plan.get("off") or []) and key not in order]
    custom = bool(order or off)
    if ask:
        # Ask me (step 16): while a player controls this character, each of these reactions stops the fight for a
        # Use or Pass (combat/typed_reactions.py _consent); under AI control they react as Auto.
        reactions = [{**row, "ask": True} if _player_decision(row) and row.get("feature_id") in names else row for row in reactions]
    if custom:
        ranked = order + [key for key in names if key not in order and key not in off]
        rank = {key: index for index, key in enumerate(ranked)}
        reactions = [({**row, "held_back": True} if row["feature_id"] in off else {**row, "priority": rank[row["feature_id"]]})
                     if _player_decision(row) and row.get("feature_id") in names else row for row in reactions]
    auto_order = sorted(names, key=lambda key: _AUTO_RANK.get(kinds[key], 3))
    return reactions, {
        "mode": "ask" if ask else ("custom" if custom else "auto"),
        "order": (order + [key for key in names if key not in order and key not in off]) if custom else auto_order,
        "off": off,
        "choices": [{"id": key, "name": names[key], "when": _REACTION_WHEN.get(kinds[key], ""), **menus.get(key, {})} for key in names],
        "options": {key: menu["option"] for key, menu in menus.items() if key in set((plan.get("options") or {}))},
    }


_NESTED_EFFECTS = ("on_fail", "on_success", "on_hit", "on_miss", "effects", "then", "else")
# Blocks that only deliver, pay for or gate other effects: on their own they change nothing.
# A "zone" line alone is only the area's marker: an ability does something with it when it carries a compiled zone
# (_zone_abilities marks those), not otherwise.
_NOT_AN_EFFECT = {"save", "spend_resource", "if_marked", "ignore_resistance", "zone"}


def _does_something(effects: Any) -> bool:
    """Whether combat/typed_executor.py runs anything for these effects: a known block other than a bare
    delivery or cost, directly or inside a save/attack branch, or a later trigger it registers. Anything
    else (riders, zone/damage_modifier text) is logged only."""
    from . import ext
    from .typed_executor import BLOCKS

    # A plug-in's own effect type (combat/ext) runs too (playtest 2026-09-29: Rolling Blackout, Steal Weapon, the choice
    # toggles were marked inert -- off the AI's menu, and "not automated" in the log when a player used them).
    plugged = ext.effects()
    for effect in effects or []:
        if not isinstance(effect, dict):
            continue
        kind = effect.get("type")
        if kind in plugged:
            return True
        if effect.get("deferred"):
            if (kind == "extra_damage" and ON_HIT_BONUS.search(str(effect.get("evidence") or ""))) or kind in ("gain_resource", "mark", "spend_mark"):
                return True
            continue
        if kind in BLOCKS and kind not in _NOT_AN_EFFECT:
            return True
        if any(_does_something(effect.get(key)) for key in _NESTED_EFFECTS if isinstance(effect.get(key), list)):
            return True
    return False


def _with_rider_utility(action: ActionDefinition) -> ActionDefinition:
    """Publish a typed scoring hint without changing any executable action data."""
    from .rider_value import estimate_rider_utility

    typed = action.parameters.get("typed")
    if action.resolution_kind != "TYPED" or not isinstance(typed, dict):
        return action
    disabled = any(action.parameters.get(key) or typed.get(key)
                   for key in ("inert", "player_only", "setting_only", "gm_only", "manual"))
    utility = estimate_rider_utility(typed, target_kind=action.target_kind,
                                     economy=action.economy.value, setting_only=disabled)
    if not disabled:
        from . import ext
        from .rider_value import MAX_RIDER_UTILITY
        for hint in ext.run_strict("compiled_rider_utility", action):
            if type(hint) is not int or not 0 <= hint <= MAX_RIDER_UTILITY:
                raise ValueError("compiled_rider_utility must return an integer from 0 to MAX_RIDER_UTILITY")
            utility = max(utility, hint)
    replacement = typed.get("replacement")
    if not disabled and isinstance(replacement, dict) and replacement.get("reliable"):
        # Preserve the existing reliable-replacement floor; its effect may also
        # be recognized by the general estimator, so never add the two hints.
        utility = max(utility, RELIABLE_RIDER_VALUE)
    parameters = dict(action.parameters)
    parameters.pop("rider_utility", None)  # do not carry a stale pre-transform hint
    if utility:
        parameters["rider_utility"] = utility
    return action.model_copy(update={"parameters": parameters}) if parameters != action.parameters else action


def _expected_damage(effects: list[dict[str, Any]], numbers: dict[str, int], *, weapon: dict[str, Any] | None = None) -> int:
    """Average damage of the typed effects, for the combat AI's scoring.

    This is a damage estimate and nothing else: a rider that deals no damage (a mark, a check penalty)
    contributes zero here, so the AI's enemy-HP finishing test (``gate4_controller``) never mistakes it
    for damage that could finish a wounded creature. What a replacement variant is worth choosing for
    is rider utility, not damage, and travels beside this number as ``rider_utility`` on the same
    compiled row (see ``RELIABLE_RIDER_VALUE`` and ``_replacement_summary``).
    """
    from factory_authoring.typed_mechanics import dice_for_cl

    total = 0
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        if effect.get("deferred") and not (effect.get("type") == "extra_damage" and ON_HIT_BONUS.search(str(effect.get("evidence") or ""))):
            continue  # a later trigger deals nothing on use; a "when you hit" bonus counts as one use (owner 2026-09-26)
        dice = dice_for_cl(effect.get("dice_by_cl"), numbers.get("cl")) or effect.get("dice")
        # "destructive_blast_damage" (combat/ext/destruction_blast.py, w4-destruction 2026-09-28): the actual dice
        # depend on a runtime Blast Type choice the compiler cannot see, so its own JSON carries the Unshaped Ruin
        # (1d8 by CL) table as a scoring estimate only -- without this the AI saw every Destructive Blast release
        # as dealing 0 expected damage and stopped choosing them.
        if effect.get("type") in {"damage", "extra_damage", "destructive_blast_damage"} and isinstance(dice, dict):
            count = dice.get("count") if dice.get("count") is not None else numbers.get("pb", 0)
            total += (int(count or 0) * (int(dice.get("sides") or 0) + 1)) // 2 + int(dice.get("bonus") or 0)
        if effect.get("type") in {"damage", "extra_damage"}:
            # Flat parts count too (e.g. Cutting Current's "+ your Proficiency Bonus"). "attack_ability_modifier"
            # resolves against the delivered weapon, exactly as combat/typed_executor.py's formula table does.
            attack_mod = (int(numbers.get("key_mod") or 0) if (weapon or {}).get("ability_modifier") is None
                          else int(weapon["ability_modifier"]))
            total += int(effect.get("flat") or 0) + {"pb": int(numbers.get("pb") or 0), "half_pb": int(numbers.get("pb") or 0) // 2,
                                                     "key_ability_modifier": int(numbers.get("key_mod") or 0),
                                                     "attack_ability_modifier": attack_mod,
                                                     "cl": int(numbers.get("cl") or 0)}.get(str(effect.get("formula") or ""), 0)
        for key in ("on_fail", "on_hit", "effects"):  # "effects" is if_marked's nested branch (owner 2026-09-26)
            total += _expected_damage(effect.get(key) or [], numbers, weapon=weapon)
    return total


# ------------------------------------------------------------------ modifiers (owner 2026-09-25)
MAX_VARIANTS_PER_ABILITY = 8
MAX_VARIANTS = 60
# A "Choose one" ability's printed menu, capped the same way as variants (owner 2026-09-26).
MAX_OPTIONS_PER_ABILITY = 6


def _norm_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower().replace("’", "'")).strip()


def _walk(effects: list[Any]):
    """Visit ordinary outcome branches and extension-owned nested effect lists.

    Modifiers on a save inside a delivery/conditional wrapper must see the same
    save as a top-level one. Zone triggers keep their separate opt-in traversal.
    """
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(effect.get(branch) or [])


# Bookkeeping the compiler stamps on an effect when it attaches a modifier: two effects that
# differ only here are the same printed effect, and must compare equal.
_EFFECT_BOOKKEEPING = ("source_modifier", "modifier_once")

# The lists an effect uses to hold further effects. They are left out of a comparison key so that
# replacing a save is not read as replacing the whole attack that carried it.
_EFFECT_BRANCHES = ("on_hit", "on_miss", "on_fail", "on_success", "effects")

# What the combat AI is willing to pay for a rider that now lands on every hit instead of only
# when the target fails a save (used by _replacement_summary). The controller already scores an
# optional rider at +8, so a guaranteed one uses the same scale. This is rider UTILITY, not damage:
# it is published on its own ``rider_utility`` key so the AI's enemy-HP finishing test keeps using
# ``expected_damage`` alone, and a mark that deals no damage can never look like a finishing blow
# (review LUNA74r2 finding 2).
RELIABLE_RIDER_VALUE = 8


def _effect_key(effect: dict[str, Any]) -> str:
    """A comparison key for one typed effect: itself, without its nested effects or compiler bookkeeping.

    Two effects share a key when they are the same printed effect, however differently their own
    outcomes are filled in. A replacement that empties a save changes the save's contents, not the
    attack that carried it, so only the save may read as removed.
    """
    return json.dumps({key: value for key, value in sorted(effect.items())
                       if key not in _EFFECT_BOOKKEEPING and key not in _EFFECT_BRANCHES},
                      sort_keys=True, default=str)


def _index_effects(effects: list[Any], save_gated: bool = False,
                   out: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Group a typed effect tree by effect, recording where each one sat.

    A ``save`` effect's own outcomes (``on_fail``/``on_success``) are gated; what an attack or an
    ability does on a hit is not. Placement is exactly what a replacement changes: it can move an
    effect out of a failed save and onto the hit itself, without changing the effect at all.
    """
    out = {} if out is None else out
    for effect in effects or []:
        if not isinstance(effect, dict):
            continue
        entry = out.setdefault(_effect_key(effect), {"effect": effect, "save_gated": False, "open": False})
        entry["save_gated"] = entry["save_gated"] or save_gated
        entry["open"] = entry["open"] or not save_gated
        for branch in _EFFECT_BRANCHES:
            _index_effects(effect.get(branch), save_gated or effect.get("type") == "save", out)
    return out


def _replacement_summary(base_effects: list[Any], variant_effects: list[Any], when: str | None) -> dict[str, Any] | None:
    """What an optional ``replace_*`` modifier removed from, and made unconditional in, its target ability.

    A replacement variant is printed as the base ability with part of it swapped out, so the variant
    keeps the base's own rules text -- which still promises the part that is now gone. Comparing the
    two effect trees once, here, gives presentation a record of the trade in ``typed["replacement"]``:
    ``removed`` (what the base did and the variant no longer does), ``reliable`` (a save-gated effect
    that now lands on every hit), and ``added`` (what the variant does that the base never did).
    ``save_gated`` marks which removed effects a FAILED SAVE used to grant, because only those may be
    explained to a player as "what a failed save would have given": a ``replace_healing`` variant
    removes ordinary immediate healing, which no failed save ever provided (review LUNA74r2 finding 3).
    Ordinary modifiers return None, so no other ability's compiled data or estimate changes.
    """
    if not str(when or "").startswith("replace_"):
        return None
    before, after = _index_effects(base_effects), _index_effects(variant_effects)
    removed = [(key, entry) for key, entry in before.items() if key not in after]
    reliable = [entry["effect"] for key, entry in after.items() if entry["open"] and before.get(key, {}).get("save_gated")]
    if not removed and not reliable:
        return None
    return {"when": str(when), "removed": [entry["effect"] for _key, entry in removed],
            "save_gated": [entry["effect"] for _key, entry in removed if entry["save_gated"]],
            "added": [entry["effect"] for key, entry in after.items() if key not in before],
            "reliable": reliable}


def _attach(effects: list[dict[str, Any]], added: list[dict[str, Any]], when: str, *, zone_saves: bool = False) -> list[dict[str, Any]]:
    """Where a modifier's effects land in the ability it changes. ``zone_saves``: a named modifier may ride a save that
    only the ability's zone triggers make (see below); broad modifiers (any technique) never do."""
    tree = copy.deepcopy(effects)
    if when == "replace_healing":
        return [row for row in tree if row.get("type") != "healing"] + added
    attack = next((row for row in _walk(tree) if row.get("type") == "attack"), None)
    save = next((row for row in _walk(tree) if row.get("type") == "save" and isinstance(row.get("on_fail"), list)), None)
    # An area whose save comes when a creature enters it or starts its turn there keeps that save in its zone triggers
    # (Shape Current's Pressure Basin). Only when the ability has no save elsewhere, a modifier about that save (failed_save,
    # save_result, replace_save) rides that one ("fails its saving throw against your Pressure Basin": Crushing Current;
    # rider lane C13). Hit, success and use modifiers keep their old landing.
    zone_rows = [trigger.get("effects") for row in _walk(tree) if row.get("type") == "zone"
                 for trigger in row.get("triggers") or [] if isinstance(trigger, dict) and isinstance(trigger.get("effects"), list)]
    if save is None and zone_saves and when in ("failed_save", "save_result", "replace_save"):
        save = next((row for rows in zone_rows for row in _walk(rows) if row.get("type") == "save" and isinstance(row.get("on_fail"), list)), None)
    # A contest standing in for its ability's attack or check (a row marked "success_branch": true, e.g. the Brutal Shove contest,
    # combat/ext/brute_shove.py; rider lane C16): a "hit" or "success" modifier rides on its on_success, as on a Scoundrel check.
    contest = next((row for row in _walk(tree) if row.get("success_branch")), None)
    check = next((row for row in _walk(tree) if row.get("type") == "scoundrel_check"), None) or contest
    if when == "replace_save" and save is not None:
        # Bitter Trace replaces Deliver the Dose's saving-throw effect, retaining its attack damage.
        for rows in [tree, *[row.get(branch) or [] for row in _walk(tree)
                            for branch in _EFFECT_BRANCHES], *zone_rows]:
            if save in rows:
                index = rows.index(save)
                rows[index:index + 1] = added
                return tree
    if when == "save_result" and save is not None:
        # Both reviews add one: a paired save-result addition, typed "save_result" (sw-monkey_style: Numbing Dose) or "save"
        # (sw-qiweaving: Solar Flare); only those rows count, whatever else the modifier carries.
        for addition in added:
            if addition.get("type") in ("save", "save_result"):
                for branch in ("on_fail", "on_success"):
                    save.setdefault(branch, []).extend(copy.deepcopy(addition.get(branch) or []))
        return tree
    if when == "success" and check is not None:
        # Scoundrel talents trigger only after the maneuver's contested check succeeds.
        check.setdefault("on_success", []).extend(added)
    elif when == "hit" and attack is not None:
        attack.setdefault("on_hit", []).extend(added)
    elif when == "hit" and contest is not None:
        contest.setdefault("on_success", []).extend(added)
    elif when == "miss" and attack is not None:
        attack.setdefault("on_miss", []).extend(added)
    elif when == "failed_save" and save is not None:
        save["on_fail"].extend(added)
    elif when in ("hit", "success") and (attack is not None or save is not None):
        (attack.setdefault("on_hit", []) if attack is not None else save["on_fail"]).extend(added)
    elif when == "success":
        tree.extend(added)  # No check of its own: success means the ability was used.
    elif when in ("hit", "miss", "failed_save"):
        return []  # the ability has no hit / save for this modifier to ride on
    else:
        tree.extend(added)
        _ride_damage_branch(tree, added, save, attack)
    return tree


_DAMAGE_ROW_TYPES = ("damage", "extra_damage")


def _branch_deals_damage(rows: Any) -> bool:
    """Whether this outcome deals damage now, rather than registering a later rider.

    Roll modifiers need an independent damage packet; neither a deferred rider
    nor another flat roll modifier can supply the roll they modify.
    """
    from .ext.roll_modifiers import is_roll_modifier

    for row in rows or ():
        if not isinstance(row, dict) or row.get("deferred") or row.get("applies_to") == "self":
            continue
        if row.get("type") in _DAMAGE_ROW_TYPES and not is_roll_modifier(row):
            return True
        # Delivery/conditional wrappers use ordinary nested effect lists. Their
        # packets remain eligible hosts; save/attack outcomes are placed below.
        if row.get("type") not in ("save", "attack") and _branch_deals_damage(row.get("effects")):
            return True
    return False


def _ride_damage_branch(tree: list[dict[str, Any]], added: list[dict[str, Any]],
                        save: dict[str, Any] | None, attack: dict[str, Any] | None) -> None:
    """Keep a modifier's own damage row on every printed outcome that damages.

    "add Proficiency Bonus to one damage roll" (Daemonic Augment) is typed ``when: "use"``, so its
    row lands on the top of the ability's effects. Most abilities damage whoever they reach, and
    there that is right. Conditional damage makes that roll only on its printed
    outcome. A deferred extra_damage instead registers a future trigger; it
    does not grant a damage roll on either outcome of the current save.

    Only the rows this modifier contributed (``added``) are moved, and only from the general
    ``tree.extend(added)`` landing the ``use`` timing produces. The ability's own rows are never
    touched, so unconditional damage, a printed self-cost that rides its own save (Star-Sundering
    Cut's "8d6 + your Cultivation Level"), and a top-level breach packet all keep firing exactly
    when the printed rules say they do -- unconditionally, once per activation, not once per
    creature that fails.

    Unconditional recipient damage takes precedence over conditional stages; a self-cost is not
    recipient damage. Modifier-owned self-costs also retain their original placement. Relocated
    rows carry damage_bonus_packet so attacks execute them as bonuses, not primary weapon damage.
    Alternative outcomes of one stage keep the bonus. When multiple stages can
    execute in sequence or one attack repeats, optional damage_bonus_group/stage metadata shares
    one activation-local roll across area recipients and prevents a later roll spending the same
    bonus again. The executor owns that general seam; no ability identity or persisted fight flag
    is involved.
    """
    rows = [row for row in added if isinstance(row, dict) and row.get("type") in _DAMAGE_ROW_TYPES
            and row.get("applies_to") != "self"]
    if not rows:
        return  # the modifier carries no damage of its own, so there is nothing to place
    carried = {id(row) for row in rows}
    if _branch_deals_damage([row for row in tree if id(row) not in carried]):
        return  # the bonus can ride an unconditional recipient packet, never a caster self-cost
    placements: list[tuple[list[dict[str, Any]], int, list[dict[str, Any]]]] = []
    # Snapshot holders before inserting rows, including nested and sequential attack/save stages.
    holders = [row for row in _walk(tree) if row.get("type") in ("save", "attack")]
    for stage, holder in enumerate(holders):
        branches = ("on_fail", "on_success") if holder.get("type") == "save" else ("on_hit", "on_miss")
        for branch in branches:
            # Native weapon/unarmed attacks may obtain their base dice from
            # typed.weapon without an explicit damage row. Match the executor's
            # implicit weapon-roll contract; condition-only Cultivation Attacks
            # and explicitly nondamaging attacks have no such roll to modify.
            implicit_weapon_hit = (holder.get("type") == "attack" and branch == "on_hit"
                                   and not holder.get("no_damage")
                                   and not str(holder.get("attack_kind") or "").startswith("cultivation"))
            if implicit_weapon_hit:
                holder.setdefault(branch, [])
            branch_rows = holder.get(branch)
            if not isinstance(branch_rows, list):
                continue
            if _branch_deals_damage(branch_rows) or implicit_weapon_hit:
                placements.append((branch_rows, stage, rows))
            elif branch == "on_success" and any(row.get("type") == "half_damage" for row in branch_rows):
                # The executor already halves plain damage riders from on_fail. Other damage
                # types need a success copy; never copy the plain rows a second time.
                extras = [row for row in rows if row.get("type") != "damage"]
                if extras and _branch_deals_damage(holder.get("on_fail")):
                    placements.append((branch_rows, stage, extras))
    if not placements:
        # "Add ... to one damage roll" cannot create a roll on a nondamaging
        # activation. Independent damage granted by a modifier keeps its own
        # packet; only roll modifiers with no immediate host are discarded.
        from .ext.roll_modifiers import is_roll_modifier

        orphaned = {id(row) for row in rows if is_roll_modifier(row) and not row.get("deferred")}
        tree[:] = [row for row in tree if id(row) not in orphaned]
        return
    sequential = len({stage for _, stage, _ in placements}) > 1
    # A stable per-attachment namespace prevents two different modifiers sharing a roll slot.
    namespace = 1 + sum(bool(row.get("damage_bonus_group")) for row in _walk(tree))
    contribution_ids = {id(row): index for index, row in enumerate(rows)}
    for branch_rows, stage, contributions in placements:
        insert_at = next((index + 1 for index, row in enumerate(branch_rows)
                          if row.get("type") in _DAMAGE_ROW_TYPES and row.get("applies_to") != "self"), len(branch_rows))
        for row in contributions:
            bonus = copy.deepcopy(row)
            # Relocated contributions are bonus packets, never an attack's primary damage.
            # Keep their flat amounts and normal effect eligibility even without a base packet.
            bonus["damage_bonus_packet"] = True
            # Even one attack node can make several rolls (count/count_by_cl).
            bonus.update(damage_bonus_group=f"use_bonus:{namespace}:{contribution_ids[id(row)]}",
                         damage_bonus_stage=stage)
            if sequential:
                branch_rows.insert(insert_at, bonus)
                insert_at += 1
            else:
                branch_rows.append(bonus)
    tree[:] = [row for row in tree if id(row) not in carried]


def _attach_reaction_modifiers(generic_reactions: dict[str, dict[str, Any]], owned: list[str], mechanics: dict[str, Any],
                               automated: set[str], primary: str | None = None, pools: Any = None) -> tuple[list[dict[str, Any]], set[str]]:
    """Named modifiers onto a generic reaction (e.g. Draw Past / Hand on the Wrist -> Flowing Response,
    both ``when: success``): a generic reaction with no attack/save node of its own has nothing for
    ``_attach`` to ride the modifier's effects on, so "success" (the reaction firing) or "use" just
    means "append these effects to what it does" (owner 2026-09-25).  Returns (report rows, the
    modifier mechanic ids consumed here so apply_modifiers does not also try them against ``built``)."""
    if not generic_reactions:
        return [], set()
    by_name: dict[str, list[str]] = {}
    for feature_id, row in generic_reactions.items():
        by_name.setdefault(_norm_name(row["name"]), []).append(feature_id)
    report: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for key in owned:
        mechanic = mechanics[key]
        modifier = mechanic.get("modifier")
        if not modifier or key in automated or mechanic["activation"].get("economy") in ("action", "bonus_action", "reaction"):
            continue
        if (modifier.get("scope") or "named") != "named":
            continue
        targets = list(dict.fromkeys(fid for name in modifier.get("targets") or [] for fid in by_name.get(_norm_name(name), [])))
        added = name_damage_effects(modifier.get("effects") or [], mechanic["name"])
        # A qualifier-only rider (Refined Moonspring Root carries requires_sight_of_subject but no effects of its
        # own) still attaches to its named reaction: the geometry/qualifier below is the whole correction.
        qualifier_only = bool(modifier.get("requires_sight_of_subject"))
        if not targets or not (added or qualifier_only):
            continue
        ways = [[{"resource_id": resource, "amount": amount} for resource, amount in costs]
                for _number, costs, _words in _modifier_payments(modifier, [], primary, pools) if costs] if primary and _pays(modifier) else []
        if ways:  # the talent's own cost is paid when the reaction runs it (combat/ext/paid_option.py; riders lane 2, 2026-09-29)
            added = [{"type": "paid_option", "talent": key, "name": mechanic.get("name"), "ways": ways,
                      "limit": modifier.get("limit"), "effects": added}]
        for feature_id in targets:
            row = generic_reactions[feature_id]
            from . import ext

            # Unconditional geometry modifiers affect the reaction's trigger
            # reach as well as the typed context it later resolves.
            if modifier.get("add_range_ft") and not modifier.get("optional") and row.get("range_ft") is not None:
                row["range_ft"] = max(0, int(row["range_ft"]) + int(modifier["add_range_ft"]))
            # A named rider that names the protected creature ("an ally you can see") marks its reaction row so the
            # shared sight provider (combat/ext/reaction_sight.py) tests perception of that creature, not the attacker.
            if modifier.get("requires_sight_of_subject") and not modifier.get("optional"):
                row["requires_sight_of_subject"] = True

            deferred = modifier.get("when") == "success" and any(ext.run("success_deferred", feature_id))
            def modified(effects):
                # Every retained mode owns its own attack/save tree. Apply the same
                # general modifier seam to manual choices and the automatic preset.
                if deferred:
                    return [*effects, {"type": "on_success", "talent": key, "effects": copy.deepcopy(added)}]
                has_hook = any(effect.get("type") in ("attack", "save") for effect in _walk(effects))
                return _attach(effects, copy.deepcopy(added), modifier.get("when") or "use") if has_hook else [*effects, *copy.deepcopy(added)]

            # Deferred success belongs to the reaction's own plug-in (e.g.
            # Flowing Response succeeds only after the attack misses).
            row["effects"] = modified(row["effects"])
            for mode in row.get("reaction_modes") or []:
                mode["effects"] = modified(mode["effects"])
        consumed.add(key)
        report.append({"id": key, "name": mechanic["name"], "when": modifier.get("when"), "optional": bool(modifier.get("optional")),
                       "precondition": modifier.get("precondition") or "", "targets": [generic_reactions[fid]["name"] for fid in targets],
                       "not_automated_targets": [], "applied": [generic_reactions[fid]["name"] for fid in targets], "variants": [],
                       "status": "applied"})
    return report, consumed


def _changed(effects: list[dict[str, Any]], modifier: dict[str, Any]) -> list[dict[str, Any]]:
    """General damage_die_steps maps old die sides to new sides, simultaneously.

    Only damage rows (including successful-save halves) change; healing and
    temporary HP keep their dice. CL tables preserve counts and level bounds.
    """
    tree = copy.deepcopy(effects)
    # A replacement changes only explicitly labelled effects, retaining damage
    # and unrelated passive riders. This also runs for composed augments.
    slot = modifier.get("replaces_effect_slot")
    if slot:
        def remove_slot(value):
            if isinstance(value, list):
                return [remove_slot(item) for item in value
                        if not (isinstance(item, dict) and item.get("effect_slot") == slot)]
            if isinstance(value, dict):
                return {key: remove_slot(item) for key, item in value.items()}
            return value
        tree = remove_slot(tree)
    for row in _walk(tree):
        steps = modifier.get("damage_die_steps") or {}
        if steps and row.get("type") in ("damage", "extra_damage", "half_damage"):
            def sides(value):
                return int(steps.get(str(value), value))
            if isinstance(row.get("dice"), dict) and row["dice"].get("sides"):
                row["dice"]["sides"] = sides(row["dice"]["sides"])
            elif isinstance(row.get("dice"), str):
                row["dice"] = re.sub(r"(?<=d)\d+", lambda m: str(sides(m.group())), row["dice"])
            if row.get("dice_by_cl"):
                row["dice_by_cl"] = [[*band[:3], sides(band[3])] for band in row["dice_by_cl"]]
        if modifier.get("damage_type") and row.get("type") in ("damage", "extra_damage") and not row.get("weapon_damage"):
            kinds = modifier["damage_type"]  # one type, or a list of types the hit may take instead (Soul Venom Method)
            row["damage_types"] = list(kinds) if isinstance(kinds, (list, tuple)) else [kinds]
        if modifier.get("extra_attacks") and row.get("type") == "attack":
            row["count"] = int(row.get("count") or 1) + int(modifier["extra_attacks"])
        # A self-teleport's printed "range" is its own distance_ft, not the action's otherwise-unused range_ft
        # (_target_kind); a non-optional add_range_ft modifier (Extended Fold on Fold Step) was being marked
        # "applied" while never actually lengthening the teleport (worker w2-support 2026-09-28).
        if modifier.get("add_range_ft") and _is_self_teleport(row) and str(row.get("distance_ft") or "").isdigit():
            row["distance_ft"] = int(row["distance_ft"]) + int(modifier["add_range_ft"])
    return tree


def _grow_area(typed: dict[str, Any], modifier: dict[str, Any]) -> None:
    """General add_area_ft grows an existing area, preserving shape/other fields.

    It does not create an area on a single-target action. Explicit zone specs
    follow the same growth so persistent effects agree with targeting geometry.
    """
    feet = int(modifier.get("add_area_ft") or 0)
    if not feet:
        return
    for key in ("area", "zone_spec"):
        area = typed.get(key)
        if isinstance(area, dict) and area.get("size_ft"):
            typed[key] = {**area, "size_ft": int(area["size_ft"]) + feet}


def _meets_requirements(row: dict[str, Any], requires: dict[str, Any] | None) -> bool:
    """A modifier's typed ``target_requires`` (general; any modifier may carry it): {"min_range_ft": N} -- the technique's range is
    at least N feet (Distant Modulation: "a sphere technique with a range of at least 10 feet"; self and touch are not);
    {"damage_types_any": [...]} -- one of its own (not weapon) damage rows deals one of these types (Retune Current)."""
    if not requires:
        return True
    if requires.get("concentration") and not ((row.get("typed") or {}).get("duration") or {}).get("concentration"):
        return False
    if requires.get("has_area") and not (row.get("typed") or {}).get("area"):
        return False
    if requires.get("min_range_ft") is not None and int(row.get("range_ft") or 0) < int(requires["min_range_ft"]):
        return False
    kinds = {str(kind).upper() for kind in requires.get("damage_types_any") or []}
    if kinds and not any(effect.get("type") in ("damage", "extra_damage") and not effect.get("weapon_damage")
                         and kinds & {str(kind).upper() for kind in effect.get("damage_types") or []}
                         for effect in _walk(row["typed"]["effects"])):
        return False
    return True


def _resolve_targets(modifier: dict[str, Any], modifier_mechanic: dict[str, Any], built: dict[str, dict[str, Any]],
                     owned_by_name: dict[str, list[str]], mechanics: dict[str, Any],
                     option_index: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """(compiled abilities it changes, names it changes that are not compiled actions, e.g. reactions).
    A named target that is a "Choose one" ability (owner 2026-09-26) resolves to every one of its
    compiled option actions -- ``option_index`` maps a mechanic id to its built key(s)."""
    scope = modifier.get("scope") or "named"
    # A Sphere talent's "any technique / any attack" modifier changes its own Sphere's abilities (owner
    # 2026-09-26 tournament check: Barrage's Battlefield Scavenger rode every Domain Armament use).
    home = modifier_mechanic.get("sphere_id")
    in_scope = (lambda row: row["mechanic"].get("sphere_id") == home) if home else (lambda row: True)
    if scope == "any_sphere_technique":
        # Typed flags (rider lane C11, Qiweaving Modulations): "any_sphere" -- the modifier changes a technique of any Sphere its
        # owner knows ("Apply Modulation: when you activate a sphere technique you know"), not only its own Sphere's;
        # "target_requires" -- the printed condition on the technique it changes (_meets_requirements).
        reach = (lambda row: True) if modifier.get("any_sphere") else in_scope
        return [key for key, row in built.items() if row["mechanic"].get("sphere_id") and reach(row)
                and _meets_requirements(row, modifier.get("target_requires"))], []
    if scope == "any_attack":
        return [key for key, row in built.items() if in_scope(row) and any(e.get("type") == "attack" for e in _walk(row["typed"]["effects"]))], []
    if scope == "attack_or_sphere_technique":
        # Reusable data-driven selector. A candidate qualifies when its typed
        # attack has a configured flag/family, or its active technique belongs
        # to a configured sphere. The mechanic names and IDs remain in reviewed data.
        selector = modifier.get("scope_filter") or {}
        flags = set(selector.get("attack_flags") or ())
        families = set(selector.get("weapon_families") or ())
        implements = set(selector.get("implement_ids") or ())
        spheres = set(selector.get("sphere_ids") or ())
        def qualifies(row: dict[str, Any]) -> bool:
            typed = row.get("typed") or {}
            attacks = [e for e in _walk(typed.get("effects") or []) if e.get("type") == "attack"]
            item = typed.get("weapon") or row.get("weapon") or {}
            attack_match = any(e.get("attack_kind") in flags for e in attacks) or (
                bool(attacks) and isinstance(item, dict) and (item.get("weapon_family") in families
                    or item.get("implement_id") in implements))
            sphere_match = bool(typed.get("effects")) and (row.get("mechanic") or {}).get("sphere_id") in spheres
            return attack_match or sphere_match
        return [key for key, row in built.items() if qualifies(row)], []
    if scope == "any_save":
        if all(isinstance(e, dict) and e.get("applies_to") == "self" for e in modifier.get("effects") or [{}]):
            # About the character's own saves (Meridian Reinforcement's advantage against poison, Broken Gourd
            # Recovery's reroll), not the techniques that force one (owner 2026-09-26 tournament: it rode every
            # Iron Voice and Wind Lash as a GM note).
            return [], []
        return [key for key, row in built.items() if in_scope(row) and any(e.get("type") == "save" for e in _walk(row["typed"]["effects"]))], []
    hits, elsewhere = [], []
    for target in modifier.get("targets") or []:
        candidates = owned_by_name.get(_norm_name(target), [])
        same_sphere = [key for key in candidates if mechanics[key].get("sphere_id") == modifier_mechanic.get("sphere_id")]
        if not candidates and home:
            # A printed short name ("a Shove" for Brutal Shove; "Mist Basin" for Basin: Mist): the one ability of the
            # talent's own Sphere whose name holds all of its words (owner 2026-09-27, the talent-category audit).
            words = set(_norm_name(target).split())
            near = [key for key, row in built.items() if row["mechanic"].get("sphere_id") == home and words and not row.get("way_of")
                    and words <= set(_norm_name(row["name"]).split())]
            if len(near) == 1:
                hits += [near[0], *(key for key, row in built.items() if row.get("way_of") == near[0])]  # each way to pay it changes alike
                continue
        for key in same_sphere or candidates:
            for built_key in option_index.get(key, [key]):
                (hits if built_key in built else elsewhere).append(built_key)
    return list(dict.fromkeys(hits)), list(dict.fromkeys(elsewhere))


MAX_VARIANTS_PER_BROAD_MODIFIER = 3
_DRAWBACK_TYPES = {"attack_modifier", "damage_modifier", "speed", "ac_bonus"}


def _grow_area(typed: dict[str, Any], modifier: dict[str, Any]) -> None:
    """General add_area_ft grows an existing area, preserving shape/other fields.

    It does not create an area on a single-target action. Explicit zone specs
    follow the same growth so persistent effects agree with targeting geometry.
    """
    feet = int(modifier.get("add_area_ft") or 0)
    if not feet:
        return
    for key in ("area", "zone_spec"):
        area = typed.get(key)
        if isinstance(area, dict) and area.get("size_ft"):
            typed[key] = {**area, "size_ft": int(area["size_ft"]) + feet}


def _pays(modifier: dict[str, Any]) -> bool:
    """A modifier with CP/Focus/alternative costs, or a named-pool ``replace_cost``."""
    return bool(modifier.get("extra_cp") or modifier.get("martial_focus") or modifier.get("cost") or modifier.get("replace_cost"))


def _free_and_harmless(modifier: dict[str, Any], spend: list[tuple[str, int]]) -> bool:
    """An option with no cost, no condition and no downside is simply always used (owner 2026-09-25:
    a separate "+ X" choice that is always better is clutter)."""
    if spend or _pays(modifier) or modifier.get("precondition"):
        return False
    # Replacing an effect removes part of the printed ability. Even when the
    # replacement is beneficial and costs nothing, choosing it is meaningful:
    # optional replacements must leave the original ability available.
    if str(modifier.get("when") or "").startswith("replace_"):
        return False
    if modifier.get("damage_type") or modifier.get("area_size_ft") or modifier.get("add_area_ft"):
        return False  # a real choice (e.g. cold instead of fire against a resistant foe)
    for row in _walk(modifier.get("effects") or []):
        if row.get("type") in _DRAWBACK_TYPES and int(row.get("flat") or 0) < 0:
            return False
        if row.get("applies_to") == "self" and row.get("type") in ("damage", "condition", "forced_movement"):
            return False
    return True


def _resource_spend(modifier: dict[str, Any], mechanic: dict[str, Any], foundation_resource: dict[str, Any] | None) -> list[tuple[str, int]]:
    """A cost printed in the modifier's condition or text ("Requires 1 Mirror Trace") becomes a real cost."""
    if not _named_list(foundation_resource):
        return []
    description = mechanic.get("description")
    text = " ".join([str(modifier.get("precondition") or ""), *(description if isinstance(description, list) else [str(description or "")])])
    for row in _named_list(foundation_resource):
        match = re.search(rf"(?:spend|requires?|expend)\s+(\d+)\s+{re.escape(row['name'])}", text, re.I)
        if match:
            return [(row["resource_id"], int(match.group(1)))]
    return []


def _modifier_spend(key: str, modifier: dict[str, Any], mechanic: dict[str, Any],
                    foundation_resource: dict[str, Any] | None) -> list[tuple[str, int]]:
    """What using a modifier costs: the resource it prints, and, when its talent or feature is limited to a scene, a day,
    a week or a rest (``_fight_limited``), the one use per fight.  Any cost makes a modifier its own choice rather than
    an always-on part of the ability it changes, so a limited one is chosen and spent, never applied on every use
    (Soul Severance's Stun rode every Iron Fist hit).  Its variants share the one counter, whichever ability they change."""
    spend = _resource_spend(modifier, mechanic, foundation_resource)
    return [*spend, _uses_of(key)[1]] if _fight_limited(mechanic) else spend


_POOL_NAMES = {RESOURCE_IDS["qi"]: "Qi", RESOURCE_IDS["stamina"]: "Stamina", RESOURCE_IDS["resonance"]: "Resonance"}


def _modifier_payments(modifier: dict[str, Any], base_costs: list[tuple[str, int]], primary: str,
                       pools: Any, foundation_resource: Any = None) -> list[tuple[int, list[tuple[str, int]], str]]:
    """Every distinct way to pay a modifier's own cost on top of its ability's, as (the printed alternative's number, the
    variant's full costs, what the modifier itself costs in words).

    The user pays ONE printed alternative: "spend 1 CP, 1 Stamina, or expend Martial Focus" is three choices, not the price
    of all three (sw-athletics report 2026-09-28: Hook the Giant's Knee cost Stamina 2 AND Martial Focus).  ``cost`` is the
    authority's own shape for this -- a list of alternatives, each a list of {"resource", "amount"} parts, "cp" being
    whichever Path pool pays this ability -- and each alternative becomes its own variant row, which is how a fight offers
    the choice (the player picks a row; the AI's ordinary scoring picks an affordable, cheap one) without the engine's
    all-or-nothing cost payment (gate2_engine._spend_costs) having to know about alternatives.  A way to pay that needs a
    pool the character does not have is not theirs to choose, and two alternatives that land on the same cost for this
    character (a Body Path's "1 CP" and "1 Stamina") are one.  A modifier with no ``cost`` pays what its two flags say
    (extra_cp and martial_focus), together, as it always did."""
    # General typed named-pool substitution, before affordability/payment. Each
    # replace_cost row names from/to pools and an integer amount; missing pools
    # or an insufficient printed base cost make that variant unavailable. This
    # can represent any prepared stock/token alternative, without engine edits.
    base_costs = list(base_costs)
    for replacement in modifier.get("replace_cost") or []:
        old = _named_match(str(replacement["from"]), foundation_resource)
        new = _named_match(str(replacement["to"]), foundation_resource)
        amount = int(replacement["amount"])
        if old is None or new is None or amount <= 0 or sum(due for resource, due in base_costs if resource == old[0]["resource_id"]) < amount:
            return []
        remaining = amount
        changed = []
        for resource, due in base_costs:
            taken = min(due, remaining) if resource == old[0]["resource_id"] else 0
            remaining -= taken
            if due > taken:
                changed.append((resource, due - taken))
        new_id = new[0]["resource_id"]
        if any(resource == new_id for resource, _due in changed):
            base_costs = [(resource, due + amount if resource == new_id else due) for resource, due in changed]
        else:
            base_costs = [*changed, (new_id, amount)]
    focus = RESOURCE_IDS["martial_focus"]
    pool = next((resource for resource, _ in base_costs if resource in RESOURCE_IDS.values() and resource != focus), RESOURCE_IDS[primary])

    def add(costs: list[tuple[str, int]], resource: str, amount: int) -> list[tuple[str, int]]:
        if resource == focus:
            return costs if any(paid == focus for paid, _ in costs) else [*costs, (focus, amount)]
        if any(paid == resource for paid, _ in costs):
            return [(paid, due + amount if paid == resource else due) for paid, due in costs]
        return [*costs, (resource, amount)]

    alternatives = modifier.get("cost")
    if not alternatives:
        costs = add(list(base_costs), pool, int(modifier["extra_cp"])) if modifier.get("extra_cp") else list(base_costs)
        return [(0, add(costs, focus, 1) if modifier.get("martial_focus") else costs, "")]
    payments: list[tuple[int, list[tuple[str, int]], str]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    for number, alternative in enumerate(alternatives):
        costs, paid, usable = list(base_costs), [], True
        for part in alternative:
            name, amount = part.get("resource"), part.get("amount")
            if name == "cp":
                resource = pool
            elif name == "martial_focus" or name == primary or name in pools:
                resource = RESOURCE_IDS.get(str(name))
            else:
                resource = None  # a pool this character does not have
            if resource is None or amount is None:
                usable = False
                break
            costs, paid = add(costs, resource, int(amount)), [*paid, (resource, int(amount))]
        if usable and tuple(sorted(costs)) not in seen:
            seen.add(tuple(sorted(costs)))
            words = [("Martial Focus" if amount == 1 else f"{amount} Martial Focus") if resource == focus
                     else f"{amount} {_POOL_NAMES.get(resource, resource)}" for resource, amount in paid]
            payments.append((number, costs, " + ".join(words)))
    return payments


def apply_modifiers(built: dict[str, dict[str, Any]], owned: list[str], mechanics: dict[str, Any],
                    primary: str, pools: Any, automated: set[str] = frozenset(),
                    foundation_resource: dict[str, Any] | None = None,
                    option_index: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    from factory_authoring.typed_structure import modifier_adds_something

    for row in built.values():
        row["variants"] = []
    owned_by_name: dict[str, list[str]] = {}
    for key in owned:
        owned_by_name.setdefault(_norm_name(mechanics[key].get("name")), []).append(key)
    report: list[dict[str, Any]] = []
    total = 0
    chosen: dict[str, int] = {}  # modifier choices on each ability: the ways to pay one choice are rows of it, not more choices
    # Named modifiers first, so a broad one ("any Sphere technique") cannot crowd them out.
    # A feature with its own building block (e.g. Qi Technique Potency, the automatic reactions) is
    # already applied by the engine; it is not also a modifier.
    ordered = sorted((key for key in owned if mechanics[key].get("modifier") and key not in automated
                      and mechanics[key]["activation"].get("economy") not in ("action", "bonus_action", "reaction")),
                     key=lambda key: ((mechanics[key]["modifier"].get("scope") or "named") != "named", key))
    resolved_options = option_index or {}
    work: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []  # (choice key, modifier id, mechanic, modifier)
    for key in ordered:
        mechanic, modifier = mechanics[key], mechanics[key]["modifier"]
        if _one_per(key, mechanic):
            modifier = {**modifier, "_choice": True}  # one of its category per use: a choice, never always-on (docket 2026-09-28)
        menu = modifier.get("options") or []
        if len(menu) < 2:
            work.append((key, key, mechanic, modifier))
            continue
        # A modifier whose printed text is a menu (Daemonic Augment: add PB to one damage roll, or Disadvantage
        # on one Concentration save, or 5 more feet of movement): one choice per option, never all at once
        # and never merged in always-on, since picking is the rule (owner 2026-09-26).
        for index, option in enumerate(menu[:MAX_OPTIONS_PER_ABILITY]):
            # A menu option may carry its own modifier fields (geometry, dice,
            # timing, etc.). Absent this optional overlay, legacy menus retain
            # their shared fields and append only the option's effects.
            selected = {**modifier, **(option.get("modifier") or {})}
            work.append((f"{key}#opt{index}", key, {**mechanic, "name": f"{mechanic['name']}: {option['label']}"},
                         {**selected, "effects": [*(selected.get("effects") or []), *(option.get("effects") or [])], "options": None, "_choice": True,
                          **({"limit": option["limit"]} if option.get("limit") else {})}))  # "You can use Weighted Knot only once per round": one option's limit
    # Always-on modifiers first: an optional choice copies the ability as it stands, so one processed before a later
    # always-on modifier missed it (Astra's audit, 2026-09-26). Stable, so the order is otherwise unchanged.
    def _is_choice(row: tuple[str, str, dict[str, Any], dict[str, Any]]) -> bool:
        _choice_key, choice_id, choice_mechanic, choice_modifier = row
        spend = _modifier_spend(choice_id, choice_modifier, choice_mechanic, foundation_resource)
        return bool((choice_modifier.get("optional") and not _free_and_harmless(choice_modifier, spend)) or _pays(choice_modifier)
                    or spend or choice_modifier.get("_choice"))

    work.sort(key=_is_choice)
    for choice_key, key, mechanic, modifier in work:
        targets, elsewhere = _resolve_targets(modifier, mechanic, built, owned_by_name, mechanics, resolved_options)
        # A target may be one option of a "Choose one" ability (owner 2026-09-26): its built row's own
        # name ("Ability: Option") is always right, unlike ``mechanics[t]`` which has no such key.
        entry = {"id": key, "name": mechanic["name"], "when": modifier.get("when"), "optional": bool(modifier.get("optional") or modifier.get("_choice")),
                 "precondition": modifier.get("precondition") or "", "targets": [built[t]["name"] for t in targets if not built[t].get("way_of")],
                 "not_automated_targets": [mechanics[t]["name"] for t in elsewhere], "applied": [], "variants": []}
        report.append(entry)
        if not modifier_adds_something(modifier) and not modifier.get("extra_cp") and not modifier.get("cost"):
            entry["status"] = "nothing typed to add"
            continue
        gate = f"{key}" if modifier.get("limit") in ("once_per_turn", "once_per_round") else None
        gate_fields = {"modifier_once": gate} if gate else {}
        if gate and modifier.get("limit") == "once_per_turn":
            from .turn_uses import modifier_period
            gate_fields["modifier_once_period"] = modifier_period(mechanic, modifier)
        added = [{**row, **gate_fields, "source_modifier": key} for row in name_damage_effects(modifier.get("effects") or [], mechanic["name"].split(":", 1)[0])]
        # A modifier's own resource gains/spends name the same resources (owner 2026-09-26: "gain 1 Edge Momentum").
        added = _resolve_resource_effects(added, mechanic=mechanic, primary=primary, pools=pools, foundation_resource=foundation_resource)
        spend = _modifier_spend(key, modifier, mechanic, foundation_resource)
        optional = (bool(modifier.get("optional")) and not _free_and_harmless(modifier, spend)) \
            or _pays(modifier) or bool(spend) or bool(modifier.get("_choice"))
        broad = (modifier.get("scope") or "named") != "named"
        if broad and optional and not modifier.get("all_targets"):
            # One choice per ability for a modifier of every technique clutters the bar: the strongest few (the ways to pay
            # one ability are one of them).
            ranked = sorted(targets, key=lambda t: -_expected_damage(built[t]["typed"]["effects"], built[t]["typed"].get("numbers") or {}))
            strongest = list(dict.fromkeys(built[t].get("way_of") or t for t in ranked))[:MAX_VARIANTS_PER_BROAD_MODIFIER]
            targets = [t for t in ranked if (built[t].get("way_of") or t) in strongest]
        decided: dict[str, bool] = {}  # per ability: whether this modifier still has room on it (the ways to pay it share the answer)
        counted: set[str] = set()
        for target in targets:
            base = built[target]
            family = base.get("way_of") or target
            # A range augmentation can increase at a printed CL threshold (Distant Modulation).
            modifier = copy.deepcopy(modifier)
            for low, high, feet in modifier.get("add_range_ft_by_cl") or []:
                if int(low) <= int((base["typed"].get("numbers") or {}).get("cl") or 1) <= int(high):
                    modifier["add_range_ft"] = int(feet)
            effects = _attach(base["typed"]["effects"], added, modifier.get("when") or "use", zone_saves=not broad) if added \
                else copy.deepcopy(base["typed"]["effects"])
            # An ability whose effect is its area (Darkness) has no typed effects, yet an augment still changes it: its
            # size, range, duration or cost (owner 2026-09-27).
            if not effects and not (optional and (modifier.get("area_size_ft") or modifier.get("add_area_ft") or modifier.get("add_range_ft") or _augment_traits(key, modifier))):
                continue
            effects = _changed(effects, modifier)
            if not optional:
                base["typed"]["effects"] = effects
                base["modifiers"].append(key)
                if not base.get("way_of"):
                    entry["applied"].append(base["name"])
                # A non-optional add_range_ft modifier (Distant Tamer on Beast Tamer; Extended Fold on the
                # self-teleport Fold Step) was marked "applied" while never actually widening the ability's own
                # range_ft -- the field gate4_engine.py and every range check actually reads (worker w2-support
                # 2026-09-28). Self-teleport also needs its effect's own distance_ft bumped (done in _changed above).
                if modifier.get("range_ft") and base.get("range_ft"):
                    # An absolute range replacement ("increase the range to 120 feet" -- Tremor Listening).
                    base["range_ft"] = int(modifier["range_ft"])
                    if base["typed"].get("range_ft"):
                        base["typed"]["range_ft"] = int(modifier["range_ft"])
                if modifier.get("add_range_ft") and base.get("range_ft"):
                    base["range_ft"] = int(base["range_ft"]) + int(modifier["add_range_ft"])
                    if base["typed"].get("range_ft"):  # the typed copy too (fight audit 2026-09-29: action 70 ft, typed 60 ft)
                        base["typed"]["range_ft"] = int(base["typed"]["range_ft"]) + int(modifier["add_range_ft"])
                _modifier_area_duration(modifier, base["typed"])
                _grow_area(base["typed"], modifier)
                continue
            if family not in decided:
                decided[family] = bool(modifier.get("all_targets")) or (chosen.get(family, 0) < MAX_VARIANTS_PER_ABILITY and total < MAX_VARIANTS)
            if not decided[family]:
                entry.setdefault("capped", []).append(base["name"])
                continue
            payments = _modifier_payments(modifier, list(base["costs"]), primary, pools, foundation_resource)
            if not payments:
                continue  # an unavailable substitution must not consume variant capacity
            typed = {**base["typed"], "effects": effects,
                     "riders": [*base["typed"]["riders"], *([f"{mechanic['name']}: {modifier['precondition']}"] if modifier.get("precondition") else [])],
                     "variant_of": base["action_id"], "modifier": {"id": key, "name": mechanic["name"], "precondition": modifier.get("precondition") or ""}}
            # An optional replacement is printed as the base ability with part of it swapped out, so the
            # variant inherits rules text describing the part that is now gone. Record the trade here (once,
            # from the two effect trees) for combat/ext/replacement_variants.py to present and the AI to score.
            replacement = _replacement_summary(base["typed"]["effects"], effects, modifier.get("when"))
            if replacement:
                typed["replacement"] = {**replacement, "base_name": base["name"]}
            range_ft, economy, traits = _optional_variant_fields(base, typed, modifier, key)
            for row, (way, costs, paying) in enumerate(payments):
                # The first way to pay keeps the name and id the modifier's variant always had; each other is "... (2 Stamina)".
                variant_id = f"{base['action_id']}+{hashlib.sha256((choice_key + (f'#pay{way}' if way else '')).encode('utf-8')).hexdigest()[:10]}"
                base["variants"].append({**base, "action_id": variant_id, "name": f"{base['name']} + {mechanic['name']}" + (f" ({paying})" if row else ""),
                                         "costs": [*costs, *spend], "typed": typed if not row else copy.deepcopy(typed), "range_ft": range_ft,
                                         "variants": [], "economy": economy,
                                         "_compose": {"key": key, "name": mechanic["name"], "added": added, "when": modifier.get("when") or "use",
                                                      "modifier": modifier, "spend": spend, "traits": traits}})
                entry["variants"].append(variant_id)
            if family not in counted:  # one choice on the ability, however many ways it can be paid
                counted.add(family)
                chosen[family] = chosen.get(family, 0) + 1
                total += 1
        entry["status"] = "applied" if entry["applied"] or entry["variants"] else ("reaction or passive target" if elsewhere else "no matching ability")
    for base in built.values():
        from .ext.attack_modifiers import capture
        capture(base)
        _augment_combinations(base, primary)
        from .recipe_options import compose_payment_variants
        compose_payment_variants(base,
            lambda modifier, costs: _modifier_payments(modifier, costs, primary, pools, foundation_resource),
            _compose_recipe_modifier)
    return report


def _optional_variant_fields(base, typed, modifier, key):
    """Geometry, duration and economy shared by single and recipe-paired modifiers.

    ``typed`` is a private copy with the modifier's effects already attached and
    transformed; the caller keeps ownership of payment and selection metadata.
    """
    range_ft = base['range_ft']
    # An absolute range_ft replacement ("increase the range to 120 feet" --
    # Tremor Listening) replaces the ability's own range outright, where
    # add_range_ft only ever adds to it.
    if modifier.get('range_ft') and range_ft:
        range_ft = int(modifier['range_ft'])
        typed['range_ft'] = range_ft
    if modifier.get('add_range_ft') and range_ft:
        range_ft = int(range_ft) + int(modifier['add_range_ft'])
        typed['range_ft'] = range_ft
    range_ft = _reach_fields(modifier, typed, range_ft, (typed.get('numbers') or {}).get('cl'))
    _modifier_area_duration(modifier, typed)
    _grow_area(typed, modifier)
    traits = _augment_traits(key, modifier)
    if traits:
        typed['duration'] = _augmented_duration(typed.get('duration') or base['mechanic'].get('duration') or {}, traits)
        typed['augments'] = [*(typed.get('augments') or []), key]
    return range_ft, modifier.get('economy') or base['economy'], traits


def _compose_recipe_modifier(variant, part):
    """Apply the full substitution modifier after the other selected modifier."""
    modifier = part['modifier']
    typed = copy.deepcopy(variant['typed'])
    typed['effects'] = _changed(_attach(typed['effects'], part['added'], part['when']), modifier)
    if modifier.get('precondition'):
        typed['riders'].append(f"{part['name']}: {modifier['precondition']}")
    range_ft, economy, _traits = _optional_variant_fields(variant, typed, modifier, part['key'])
    return {'typed': typed, 'range_ft': range_ft, 'economy': economy}


def _printed_attack_ranges(typed: dict[str, Any], mechanic: dict[str, Any]) -> None:
    """Keep declared normal/long ranges independently of weapon delivery.

    Any reviewed action can declare a positive ``range.feet/long_feet`` pair.
    Its public range still covers the long range; these typed fields let the
    executor apply long-range disadvantage. Absent a pair this is inert.
    """
    ranges = mechanic.get('range') or {}
    normal, long = ranges.get('feet'), ranges.get('long_feet')
    normal = next((int(value) for low, high, value in ranges.get('feet_by_cl') or []
                   if int(low) <= int((typed.get('numbers') or {}).get('cl') or 1) <= int(high)), normal)
    if type(normal) is int and type(long) is int and 0 < normal < long:
        typed.update(range_ft=normal, long_range_ft=long)


def _target_mark(typed: dict[str, Any], mechanic: dict[str, Any]) -> None:
    """A printed target that must already bear its user's mark (sw-athletics review 2026-09-28, Close Haft Strike: "When a
    creature within your reach has Bite from you, you may ... as a Bonus Action"; Lodged Axe Pull: "While the Bite lasts"):
    the mechanic's ``target.requires_mark`` becomes the same ``target_requires_mark`` a modifier's variant may carry
    (_reach_fields), which _action_definition turns into the engine's ``target_requires_condition``."""
    target = mechanic.get("target")
    if isinstance(target, dict) and target.get("requires_mark"):
        typed["target_requires_mark"] = str(target["requires_mark"])


def _modifier_area_duration(modifier: dict[str, Any], typed: dict[str, Any]) -> None:
    """Explicit reviewed area dimensions and duration, including Realm-sized Veils."""
    if modifier.get("area_size_ft"):
        area = {"shape": modifier.get("area_shape") or "sphere", "size_ft": int(modifier["area_size_ft"])}
        if modifier.get("area_size_ft_by_cl"):
            area["size_ft_by_cl"] = copy.deepcopy(modifier["area_size_ft_by_cl"])
            area["size_ft"] = _area_size_for_cl(area, (typed.get("numbers") or {}).get("cl"))
        if modifier.get("area_width_ft"):
            area["width_ft"] = int(modifier["area_width_ft"])
        typed["area"] = area
    if modifier.get("duration"):
        typed["duration"] = copy.deepcopy(modifier["duration"])


def _reach_fields(modifier: dict[str, Any], typed: dict[str, Any], range_ft: Any, cl: Any) -> Any:
    """The parts of a modifier that decide who its variant can be aimed at (typing pass 2026-09-28, Life-Seal Reach:
    "target a creature bearing your Pulse Seal within 30 feet instead of touching it; 60 feet at Core Formation, 120 at
    Nascent Soul"). ``range_ft_by_cl`` rows ``[low_cl, high_cl, feet]`` REPLACE the ability's reach rather than adding to
    it (``add_range_ft``); ``target_requires_mark`` names a mark its user placed that the target must bear
    (_action_definition turns it into the engine's ``target_requires_condition``). Returns the variant's range. Only a
    modifier that becomes its own variant reaches this code: keep a ``precondition`` (or a cost) in the modifier's data, or
    ``_free_and_harmless`` makes it always-on and its non-optional path applies ``add_range_ft`` alone."""
    for low, high, feet in modifier.get("range_ft_by_cl") or []:
        if int(low) <= int(cl or 1) <= int(high):
            range_ft = typed["range_ft"] = int(feet)
    if modifier.get("target_requires_mark"):
        typed["target_requires_mark"] = str(modifier["target_requires_mark"])
    return range_ft


MAX_AUGMENTS_COMBINED = 6  # 63 combinations at most per ability; only the chosen one is offered in a fight


def _augment_traits(key: str, modifier: dict[str, Any]) -> dict[str, bool]:
    """Whether a modifier is an augment (a talent headed "- Augment", "Augment - 1 CP" in its text, or typed in the
    Augment group), and what it does to the duration ("persists ... without Concentration"; "becomes permanent")."""
    text = _rules_text().get(key) or ""
    if not (any(tag.lower().endswith("augment") for tag in _talent_tags(key)) or re.search(r"\bAugment\s*[-\u2013]\s*\d+\s*CP", text)
            or str(modifier.get("group") or "").lower() == "augment"):
        return {}
    return {"augment": True, "no_concentration": bool(re.search(r"without Concentration", text, re.I)),
            "permanent": bool(re.search(r"\bpermanent\b", text, re.I))}


def _augmented_duration(duration: dict[str, Any], traits: dict[str, bool]) -> dict[str, Any]:
    if traits.get("permanent"):
        return {"kind": "scene", "amount": None, "concentration": False}  # the whole fight
    if traits.get("no_concentration"):
        return {**duration, "concentration": False}
    return dict(duration)


def _augment_combinations(base: dict[str, Any], primary: str) -> None:
    """Any number of augments on one use, each paid for (owner 2026-09-27: "Yes, any number"): every combination of an
    ability's augments is compiled once, and a fight offers only the one its user has chosen (combat/zones.py
    augments; Gate4ControllerEngine.legal_candidates)."""
    import itertools

    singles = [variant for variant in base["variants"] if (variant.get("_compose") or {}).get("traits")][:MAX_AUGMENTS_COMBINED]
    if not singles:
        return
    combos = {variant["_compose"]["key"]: variant["action_id"] for variant in singles}
    pool_ids = set(RESOURCE_IDS.values()) - {RESOURCE_IDS["martial_focus"]}
    for size in range(2, len(singles) + 1):
        for chosen in itertools.combinations(singles, size):
            parts = [variant["_compose"] for variant in chosen]
            effects = copy.deepcopy(base["typed"]["effects"])
            costs = list(base["costs"])
            typed = dict(base["typed"])
            duration = dict(typed.get("duration") or base["mechanic"].get("duration") or {})
            range_ft = base["range_ft"]
            for part in parts:
                modifier = part["modifier"]
                if part["added"]:
                    effects = _attach(effects, part["added"], part["when"],
                                      zone_saves=(modifier.get("scope") or "named") == "named")
                effects = _changed(effects, modifier)
                if modifier.get("extra_cp"):
                    pool = next((resource for resource, _ in costs if resource in pool_ids), RESOURCE_IDS[primary])
                    costs = [(resource, amount + (modifier["extra_cp"] if resource == pool else 0)) for resource, amount in costs]
                    if not any(resource == pool for resource, _ in costs):
                        costs.append((pool, int(modifier["extra_cp"])))
                if modifier.get("martial_focus") and not any(resource == RESOURCE_IDS["martial_focus"] for resource, _ in costs):
                    costs.append((RESOURCE_IDS["martial_focus"], 1))
                costs.extend(part["spend"])
                if modifier.get("add_range_ft") and range_ft:
                    range_ft = int(range_ft) + int(modifier["add_range_ft"])
                    typed["range_ft"] = range_ft
                range_ft = _reach_fields(modifier, typed, range_ft, (base["typed"].get("numbers") or {}).get("cl"))
                _modifier_area_duration(modifier, typed)
                _grow_area(typed, modifier)
                duration = _augmented_duration(modifier.get("duration") or duration, part["traits"])
            keys = [part["key"] for part in parts]
            names = [part["name"] for part in parts]
            typed = {**typed, "effects": effects, "duration": duration, "augments": keys,
                     "riders": [*base["typed"]["riders"], *[f"{part['name']}: {part['modifier']['precondition']}" for part in parts if part["modifier"].get("precondition")]],
                     "variant_of": base["action_id"], "modifier": {"id": "+".join(keys), "name": " + ".join(names), "precondition": ""}}
            action_id = f"{base['action_id']}+aug.{hashlib.sha256('|'.join(sorted(keys)).encode('utf-8')).hexdigest()[:10]}"
            base["variants"].append({**base, "action_id": action_id, "name": f"{base['name']} + {' + '.join(names)}", "costs": costs,
                                     "typed": typed, "range_ft": range_ft, "variants": []})
            combos["|".join(sorted(keys))] = action_id
    base["loadout"] = {"combos": combos, "augments": [{"key": variant["_compose"]["key"], "name": variant["_compose"]["name"],
                                                       "costs": [list(cost) for cost in variant["costs"] if cost not in base["costs"]]}
                                                      for variant in singles]}


def _action_definition(row: dict[str, Any], actor_id: str, numbers: dict[str, Any]) -> ActionDefinition:
    mechanic = row["mechanic"]
    area = row["typed"].get("area") or mechanic.get("area") or {}
    if area.get("size_ft_by_cl"):
        # CL-scaled radius_ft only (Domain Pressure): NOT written back into typed["area"], which resolve_typed reads
        # to decide *how* to pick targets (a geometric area needing an aimed destination vs. the target(s) chosen when
        # the candidate was built). A record with no base "size_ft" of its own compiled -- and is meant to keep
        # compiling -- as a direct target pick; giving it a size_ft here would silently switch it to area-aim targeting.
        area = {**area, "size_ft": _area_size_for_cl(area, numbers.get("cl"))}
    # An augment may end the need for Concentration (Persistent Darkness) or make it last (Eternal Darkness).
    duration = row["typed"].get("duration") if row["typed"].get("augments") else mechanic.get("duration")
    typed = {key: value for key, value in row["typed"].items() if key != "loadout"}
    # Final delivery (including forged forms and augments) shares recipient
    # metadata with execution and area-risk previews; no ability-specific cases.
    from .area_recipients import scoped_area
    if typed.get("area"):
        # Some typed descriptions omit the printed recipient sentence. Read
        # the cached authority once during compilation, never in menu refreshes.
        recipient_text = _rules_text().get(str(mechanic.get("mechanic_id") or ""), _texts(mechanic))
        typed["area"] = scoped_area(typed["area"], typed.get("effects"), recipient_text, typed=typed)
    parameters = {"typed": typed, "expected_damage": _expected_damage(row["typed"]["effects"], numbers)}
    if (row["typed"].get("replacement") or {}).get("reliable"):
        # What the guaranteed rider is worth choosing for, kept out of ``expected_damage`` so the AI's
        # enemy-HP finishing test still sees this ability's damage alone (review LUNA74r2 finding 2).
        parameters["rider_utility"] = RELIABLE_RIDER_VALUE
    if row.get("loadout"):
        parameters["augment_loadout"] = row["loadout"]  # the ability's augments and the action for each combination
    if row["typed"].get("augments"):
        parameters["augment_of"] = row["typed"]["variant_of"]
    if row["typed"].get("target_requires_mark"):
        from .typed_executor import mark_condition_id  # only creatures bearing the user's own mark can be aimed at

        parameters["target_requires_condition"] = mark_condition_id(row["typed"]["target_requires_mark"], actor_id)
    named = mechanic.get("target")
    if isinstance(named, dict) and named.get("requires_condition") and not parameters.get("target_requires_condition"):
        from .typed_executor import CONDITION_PREFIX  # a reviewed "Target: One creature Grappled by you" (Wrestling throws, Pin)

        parameters["target_requires_condition"] = CONDITION_PREFIX + str(named["requires_condition"])
    return ActionDefinition(
        source_definition_id=row["action_id"], display_name=row["name"], owner_id=actor_id,
        economy=EconomyKind.ACTION if row["economy"] == "action" else EconomyKind.BONUS_ACTION,
        resolution_kind="TYPED", target_kind=row["target_kind"], range_ft=row["range_ft"],
        radius_ft=area.get("size_ft"), costs=tuple(row["costs"]),
        concentration=bool((duration or {}).get("concentration")),
        parameters=parameters,
    )


def register_bundle(engine_templates: dict[str, ActorTemplate], engine_actions: dict[str, ActionDefinition], bundle: dict[str, Any]) -> str:
    """Add a compiled character to an engine's templates and action catalog before the match is created."""
    template = ActorTemplate.model_validate(bundle["actor_template"])
    for row in bundle["action_catalog"]:
        action = ActionDefinition.model_validate(row)
        if action.source_definition_id in engine_actions:
            raise ValueError(f"TYPED_ACTION_ID_COLLISION:{action.source_definition_id}")
        engine_actions[action.source_definition_id] = action
    engine_templates[template.entity_id] = template
    return template.entity_id
