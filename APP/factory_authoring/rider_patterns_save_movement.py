"""Conservative, source-backed save and movement rider conversions.

These recipes do not infer a missing primary effect or a trigger.  Repeated
saves attach only to the sole condition in the sole original save's failure
branch.  A successful repeat therefore removes that condition instance, never
another caster's matching condition or the initial-success branch.

The no-opportunity-attack recipe distinguishes forced movement (the native
forced path already does not provoke) from an immediate self step.  The latter
uses ``rider_step``'s separately capped native path, not turn-wide Disengage or
an allowance which a later, unrelated move could consume.  Source-specific
exemptions, ally movement, deferred steps and ambiguous antecedents stay riders.

The owning conversion tool additionally verifies the exact source hash and the
complete unconverted mechanic digest before applying these authoring recipes.
"""

from __future__ import annotations

import copy
import re
from typing import Any


def _normal(text: str) -> str:
    return " ".join(text.replace("\u2019", "'").split()).casefold()


_REPEAT_AT_END = re.compile(
    r"(?:the (?:creature|target) repeats the saving throw at the end of each of its turns"
    r"|at the end of each of its turns, (?:it|the (?:affected creature|target)|an unwilling creature) "
    r"repeats the (?:(?:strength|dexterity|constitution|intelligence|wisdom|charisma) )?sav(?:e|ing throw))"
    r", ending the (?P<ends>effect|[a-z]+ condition)(?: on itself)? on a success\.?"
)
_ABILITY_WORD = {
    "strength": "STR", "dexterity": "DEX", "constitution": "CON",
    "intelligence": "INT", "wisdom": "WIS", "charisma": "CHA",
}
_FORCED_NO_OA = {
    "this forced movement does not provoke opportunity attacks.",
    "this movement is forced movement and does not provoke opportunity attacks.",
}
_SELF_NO_OA = {
    "this movement does not provoke opportunity attacks.",
    "does not provoke opportunity attacks",
    "you do not provoke opportunity attacks during this movement",
}


def _effects(value: Any, path: str = ""):
    """Yield effect rows and exact JSON pointers without treating prose as code."""
    if isinstance(value, dict):
        if isinstance(value.get("type"), str):
            yield path, value
        for key, child in value.items():
            yield from _effects(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _effects(child, path + "/" + str(index))


def _repeat(mechanic: dict[str, Any], rider: str) -> list[str]:
    match = _REPEAT_AT_END.fullmatch(_normal(rider))
    if match is None or mechanic.get("modifier") or mechanic.get("options"):
        return []
    # A second save or lasting failure member needs a group-aware recovery
    # protocol.  In particular an empty failure is not a condition to recover.
    saves = [(path, row) for path, row in _effects(mechanic) if row.get("type") == "save"]
    if len(saves) != 1:
        return []
    path, save = saves[0]
    ability = str(save.get("ability") or "").upper()
    if ability not in _ABILITY_WORD.values() or save.get("applies_to") not in (None, "target"):
        return []
    for word, named in _ABILITY_WORD.items():
        if re.search(rf"repeats the {word} sav(?:e|ing throw)\b", _normal(rider)) and named != ability:
            return []
    failures = save.get("on_fail") or []
    if len(failures) != 1 or not isinstance(failures[0], dict):
        return []
    condition = failures[0]
    name = str(condition.get("condition") or "")
    if condition.get("type") not in ("condition", "ongoing") or name in ("", "none") \
            or condition.get("applies_to") not in (None, "target") \
            or condition.get("deferred") or condition.get("mark"):
        return []
    ending = match.group("ends")
    if ending != "effect" and ending != name.lower() + " condition":
        return []
    previous = condition.get("repeat_save") or {}
    if not isinstance(previous, dict) or set(previous) - {"ability", "when"} \
            or str(previous.get("ability", ability)).upper() != ability \
            or previous.get("when", "end") != "end":
        return []
    # The runtime stores this action's actual save DC with the condition and
    # retains source_actor_id and the instance id in ordinary replayable events.
    condition["repeat_save"] = {"ability": ability, "when": "end"}
    return [path + "/on_fail/0/repeat_save"]


def _movement(mechanic: dict[str, Any], rider: str, source_text: str) -> tuple[list[str], str]:
    normalized = _normal(rider)
    rows = list(_effects(mechanic))
    motion = [(path, row) for path, row in rows if row.get("type") in ("movement", "forced_movement", "rider_step", "teleport")]
    if normalized in _FORCED_NO_OA:
        # Every represented movement must be forced.  The sentence cannot be
        # attached to a different self step or teleport in the same ability.
        if not motion or any(row.get("type") != "forced_movement" for _, row in motion):
            return [], ""
        if any(type(row.get("distance_ft")) is not int or row["distance_ft"] <= 0
               or row.get("applies_to") not in (None, "target", "creatures_in_area") for _, row in motion):
            return [], ""
        # Do not turn a sole rider into FULL while an explicit size prerequisite
        # on the represented movement is still only prose in its modifier.
        precondition = _normal(str((mechanic.get("modifier") or {}).get("precondition") or ""))
        if "no more than one size larger" in precondition and any(row.get("max_size_larger") != 1 for _, row in motion):
            return [], ""
        for _, row in motion:
            row["no_opportunity_attacks"] = True
        return [path + "/no_opportunity_attacks" for path, _ in motion], \
            "combat.typed_executor.block_forced_movement -> combat.movement_paths.forced_steps (existing non-provoking forced traversal)"
    if normalized not in _SELF_NO_OA or len(motion) != 1 \
            or mechanic.get("modifier") or mechanic.get("options"):
        return [], ""
    path, movement = motion[0]
    # Standalone, immediate self movement only.  Deferred movement, movement
    # inside a save/attack branch, ally moves and source-only immunity need
    # different timing/ownership, which this recipe does not guess.
    if not re.fullmatch(r"/effects/\d+", path) or movement.get("type") != "movement" \
            or movement.get("applies_to") not in (None, "self") or movement.get("deferred") \
            or movement.get("mode") in ("teleport", "dash") \
            or type(movement.get("distance_ft")) is not int or movement["distance_ft"] <= 0 \
            or mechanic.get("activation", {}).get("economy") not in ("action", "bonus_action"):
        return [], ""
    evidence = _normal(str(movement.get("evidence") or ""))
    # A parser's "Speed increases" is not a step; the movement's actual clause
    # must be present in the current printed text, not just a matching number.
    if not evidence or evidence not in _normal(source_text) or not re.match(r"(?:you )?(?:may )?move\b", evidence):
        return [], ""
    movement["type"] = "general_rider_step"
    movement["no_oa"] = True
    if "visible" in evidence or "you can see" in evidence:
        movement["visible_destination"] = True
    return [path], "combat.ext.general_save_movement -> rider_step/native granted movement (no_oa, one separately capped path)"


def convert(mechanic: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a copy with complete, verified rider sentences converted to data.

    Records identify the original rider pointer and changed effect pointers.
    Existing unrelated riders and every nonmatching mechanic remain unchanged.
    """
    converted = copy.deepcopy(mechanic)
    records: list[dict[str, Any]] = []
    retained: list[Any] = []
    source = _normal(source_text)
    for index, rider in enumerate(mechanic.get("riders") or []):
        if not isinstance(rider, str) or not _normal(rider) or _normal(rider) not in source:
            retained.append(rider)
            continue
        paths = _repeat(converted, rider)
        if paths:
            pattern = "repeat_save_end_turn"
            seam = "condition/ongoing.repeat_save -> native end-of-holder-turn repeat save and exact-instance removal"
            original_rows = dict(_effects(mechanic))
            behavior = "verified_restatement" if all(
                original_rows[path.removesuffix("/repeat_save")].get("repeat_save") for path in paths
            ) else "repaired_behavior"
        else:
            paths, seam = _movement(converted, rider, source_text)
            pattern = "movement_no_opportunity_attacks"
            behavior = "verified_restatement" if _normal(rider) in _FORCED_NO_OA else "repaired_behavior"
        if not paths:
            retained.append(rider)
            continue
        records.append({"pattern": pattern, "rider": rider, "path": f"/riders/{index}",
                        "effect_paths": paths, "engine_seam": seam, "behavior": behavior})
    if records:
        converted["riders"] = retained
    return converted, records
