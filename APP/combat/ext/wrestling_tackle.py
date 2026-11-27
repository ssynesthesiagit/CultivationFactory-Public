"""Tackle (Wrestling, Hold): "When taking the Dash action as your Action, use a Bonus Action before the end of the turn to attempt
to Grapple one creature within reach."

The Dash Action leaves the engine's ``dash_used`` turn flag. This gives the fighter a Bonus Action Grapple -- the Unarmed Strike
Grapple option of combat/factory_compiler.py ``_unarmed_options`` (Strength or Dexterity save against 8 + Strength + PB, a
creature up to one size larger, needs a free hand, the grapple ends by escape or release), with the attack it replaces taken
out -- that the engine offers only in a turn that has the Dash. The Bonus Action is the engine's own: a Dash spent as a Bonus
Action (a talent that grants one) leaves none for the Tackle.
"""

from __future__ import annotations

from typing import Any

from . import hook

TACKLE = "TAL_WRESTLING_TACKLE"
FLAG = "dash_used"


@hook("maneuvers")
def tackle_grapple(info: dict[str, Any]) -> dict[str, Any] | None:
    if TACKLE not in info["owned"]:
        return None
    import copy

    from ..gate2_runtime_models import EconomyKind

    grapple = next((row for row in info["actions"] if str(row.source_definition_id).endswith(".unarmed.grapple")), None)
    if grapple is None:
        return None
    typed = copy.deepcopy((grapple.parameters or {}).get("typed") or {})
    typed["effects"] = typed.get("effects", [])[:1]  # the Grapple attempt alone, not the rest of the Attack action
    typed["riders"] = [*(typed.get("riders") or []), "Tackle: a Bonus Action after taking the Dash action as your Action."]
    extra = {key: value for key, value in grapple.parameters.items() if key not in ("typed", "expected_damage")}
    clone = grapple.model_copy(update={
        "source_definition_id": f"{grapple.source_definition_id}.tackle", "display_name": "Tackle: Grapple",
        "economy": EconomyKind.BONUS_ACTION,
        "parameters": {**extra, "typed": typed, "expected_damage": 0, "requires_turn_flag": FLAG},
    })
    return {"actions": [clone]}
