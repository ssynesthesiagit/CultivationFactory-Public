"""Combo Maneuvers (auto-lane4 2026-09-29): "When you would make your Paired Strike, replace it with one Unarmed Strike used
only for its Grapple or Shove option. Use the ordinary 5.5e rules for that Unarmed Strike: a Shove does not require a free
hand; a Grapple requires a free hand; Combo Maneuvers does not allow a weapon to maintain a Grapple; you may use Dual Draw or
another legal rule to unequip a weapon before attempting the Grapple."

The Paired Strike is the off-hand attack the compiler gives a Light or Paired weapon after the Attack action ("<weapon>
off-hand attack": a Bonus Action, or part of the Attack action for a Nick weapon; combat/factory_compiler.py, the ``#offhand``
variants). For each of those this hook offers a copy of each of the character's own 2024 Unarmed Strike options (Shove: Push
5 ft, Shove: Prone, Grapple: the same save, the same DC, and every talent already folded into them) that takes the off-hand
attack's place: same economy, same "an Attack-action attack was made" gate, and the same once-a-turn flag, so the maneuver
and the off-hand attack can never both be made. A Grapple's free hand is not tracked in this table (the plain Grapple option
only checks for a shield), and neither is which hand holds the weapon that "maintains" a Grapple.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import hook
from ..gate2_runtime_models import ActionDefinition

COMBO = "TAL_DUAL_WIELDING_COMBO_MANEUVERS"
OPTIONS = ("shove_push", "shove_prone", "grapple")


@hook("maneuvers")
def combo_maneuvers(info: dict[str, Any]) -> dict[str, Any] | None:
    """(The ``maneuvers`` hook runs once the Unarmed Strike's options exist and the talents that change them are folded in.)"""
    if COMBO not in info["owned"]:
        return None
    actions = list(info.get("actions") or ())
    offhands = [action for action in actions if str(action.source_definition_id).endswith("#offhand")]
    options = [action for action in actions if (action.parameters.get("typed") or {}).get("unarmed_option") in OPTIONS]
    made: list[ActionDefinition] = []
    for number, offhand in enumerate(offhands):
        flag = offhand.parameters.get("requires_turn_flag")
        weapon = re.sub(r"\s*\(.*\)$", "", str(offhand.display_name).removesuffix(" off-hand attack"))
        for option in options:
            parameters = copy.deepcopy(option.parameters)
            typed = parameters["typed"]
            typed["effects"] = typed["effects"][:1]  # the save attempt itself; the Attack action's remaining strikes stay theirs
            typed["riders"] = [*(typed.get("riders") or []),
                               f"Combo Maneuvers: in place of the {weapon} off-hand attack (your Paired Strike)."]
            if (offhand.parameters.get("typed") or {}).get("uses"):
                typed["uses"] = list((offhand.parameters["typed"]).get("uses") or [])
            # Provenance (ext/__init__.py typed.replaces_attack): limits on the replaced attack (Nick's once per turn,
            # combat/ext/weapon_mastery.py) apply to this replacement too.
            mastery = (offhand.parameters.get("typed") or {}).get("mastery")
            typed["replaces_attack"] = {"source_definition_id": offhand.source_definition_id,
                                        **({"mastery": mastery} if mastery else {})}
            parameters["expected_damage"] = 0
            if flag:
                parameters["requires_turn_flag"] = flag
            suffix = f" ({weapon})" if len(offhands) > 1 else ""
            made.append(ActionDefinition(
                source_definition_id=f"{option.source_definition_id}.combo_maneuvers.{number}", display_name=f"Combo Maneuvers: {option.display_name}{suffix}",
                owner_id=option.owner_id, economy=offhand.economy, resolution_kind=option.resolution_kind, target_kind=option.target_kind,
                range_ft=option.range_ft, parameters=parameters))
    return {"actions": made} if made else None
