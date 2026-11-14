"""Build-time roll selectors for Advantage/Disadvantage and save-reaction bonuses.

Used by tools.build_typed_mechanics_authority, not by combat execution.
The executor, area compiler and rider preview historically had distinct readings;
preserve those readings as data rather than making one silently override another.
Explicit reviewed roll_target values (including null) always win.
"""
from __future__ import annotations

import re
from typing import Any

from combat.roll_mode_semantics import require_roll_target

ROLL_TARGET_TYPES = ("advantage", "disadvantage", "attack_modifier")

_CHECK_ABILITIES = (("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"),
                    ("intelligence", "INT"), ("wisdom", "WIS"), ("charisma", "CHA"))
_SKILLS = ("Acrobatics", "Animal Handling", "Arcana", "Athletics", "Deception", "History", "Insight",
           "Intimidation", "Investigation", "Medicine", "Nature", "Perception", "Performance", "Persuasion",
           "Religion", "Sleight of Hand", "Stealth", "Survival")
_SAVE_AGAINST = (("shove", "forced_movement"), ("forced movement", "forced_movement"), ("pushed", "forced_movement"),
                 ("moved against your will", "forced_movement"), ("prone", "prone"), ("grappl", "grappled"),
                 ("restrain", "restrained"), ("charm", "charmed"), ("frighten", "frightened"), ("poison", "poisoned"),
                 ("paraly", "paralyzed"), ("stun", "stunned"), ("blind", "blinded"), ("deafen", "deafened"),
                 ("incapacitat", "incapacitated"), ("petrif", "petrified"), ("exhaustion", "exhaustion"))
_OPPORTUNITY_ATTACK_MADE_BY_HOLDER = re.compile(r"\bopportunity attacks? (?:it|that creature|they) makes?\b")


def _save_against_keys(on: str) -> list[str]:
    """Legacy named-save vocabulary; also used by the unchanged Warleader add-ons."""
    return sorted({key for word, key in _SAVE_AGAINST if word in on})


def _names_a_save(on: str) -> bool:
    return bool(re.search(r"saving throws?|\bsaves?\b|\bresist", on)) and "concentration" not in on and \
        bool(_save_against_keys(on) or any(word in on for word, _ in _CHECK_ABILITIES))


def _check_keys(on: str) -> list[str]:
    """Skills narrow an ability; a bare 'ability checks' covers every check."""
    skills = [skill for skill in _SKILLS if skill.lower() in on]
    if skills:
        return skills
    codes = [code for word, code in _CHECK_ABILITIES if re.search(rf"\b{word}\b", on)]
    return codes or (["ALL"] if re.fullmatch(r"(?:all |its |their |your )?ability checks?", on.strip()) else [])


def derive_roll_target(effect: dict[str, Any]) -> dict[str, Any] | None:
    """The old text interpreter, run once when building authority, never in a block."""
    if effect.get("type") == "attack_modifier":
        return {"kind": "save"} if "sav" in str(effect.get("on") or effect.get("evidence") or "").lower() else None
    on = str(effect.get("on") or "").lower()
    save_spec = effect.get("save_against")
    if save_spec is None and re.fullmatch(
            r"(?:the next |one )?attacks? (?:made )?against (?:it|the target|you|them|that creature)", on.strip()):
        on = on.replace("attack", "attack roll", 1)
    incoming = save_spec is None and "attack roll" in on and any(
        word in on for word in ("against it", "against the target", "against you"))
    # The explicit save selector suppresses text only in the executor, as before.
    dispatch = "" if save_spec is not None else on
    checked = _check_keys(dispatch)
    if "death sav" in dispatch:
        kind = "death_save"
    elif incoming:
        kind = "incoming_attack"
    elif _OPPORTUNITY_ATTACK_MADE_BY_HOLDER.search(dispatch):
        kind = "opportunity_attack"
    elif "attack roll" in dispatch:
        kind = "attack"
    elif re.search(r"\bchecks?\b", dispatch) and checked:
        kind = "check"
    elif "concentration" in dispatch and re.search(r"saving throws?|\bsaves?\b|\bchecks?\b", dispatch):
        kind = "concentration"
    elif save_spec is not None or _names_a_save(dispatch):
        kind = "save"
    else:
        kind = None
    result: dict[str, Any] = {"kind": kind}
    if kind in ("opportunity_attack", "concentration", "save"):
        result["next"] = bool(re.search(r"\bnext\b", dispatch))
    if kind == "death_save":
        result["first"] = "first" in dispatch or "next" in dispatch
    if kind == "check":
        result["checks"] = checked
    if kind == "save":
        result.update({"against": list(save_spec.get("against") or []),
                       "abilities": list(save_spec.get("abilities") or []), "next": bool(save_spec.get("next"))}
                      if save_spec is not None else
                      {"against": _save_against_keys(dispatch),
                       "abilities": [code for word, code in _CHECK_ABILITIES if word in dispatch]})
    # Conservative utility is deliberately not the executor's branch precedence.
    preview_kind = None
    if isinstance(effect.get("on"), str):
        if "attack roll" in on:
            preview_kind = "attack"
        elif ("concentration" in on and any(word in on for word in ("saving throw", "save", "check"))) or _names_a_save(on):
            preview_kind = "save"
        elif "check" in on and _check_keys(on):
            preview_kind = "check"
    if preview_kind:
        # Equality-only token: preserve cancellation grouping without runtime prose.
        group = "attack" if "attack roll" in on else on.strip()
        result["preview"] = {"kind": preview_kind, "group": group}
    raw = str(effect.get("on") or "")
    if not re.search(r"\bescape\b|\bmade to\b", raw, re.I):
        abilities = [code for word, code in _CHECK_ABILITIES if re.search(rf"\b{word}\b", raw, re.I)]
        inside = {}
        if abilities and re.search(r"saving throws?", raw, re.I):
            inside["saves"] = abilities
        if abilities and re.search(r"ability checks?", raw, re.I):
            inside["checks"] = abilities
        if re.search(r"perception[^.]*hearing", raw, re.I):
            inside["muffles"] = True
        if inside:
            result["inside"] = inside
    else:
        result["inside"] = {"exclude": True}
    return result if kind is not None or len(result) > 1 else None


def seal_roll_targets(value: Any, source_id: str | None = None) -> None:
    """Seal every nested effect after overlays; absent and explicit null differ."""
    if isinstance(value, list):
        for child in value:
            seal_roll_targets(child, source_id)
    elif isinstance(value, dict):
        if value.get("type") in ROLL_TARGET_TYPES:
            if "roll_target" not in value:
                value["roll_target"] = derive_roll_target(value)
            require_roll_target(value, source_id)
        for key, child in list(value.items()):
            if key != "roll_target":
                seal_roll_targets(child, source_id or value.get("source_id") or
                                  (key if isinstance(child, dict) and "effects" in child else None))
