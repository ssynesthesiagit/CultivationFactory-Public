"""Advantage or Disadvantage on saves against named effects, for as long as the ability says (roster playtest 2026-09-29:
Weight Shift's Body Heavying "Advantage on resisting Shove, Grapple, forced movement, and effects that would knock you
Prone", Consecrated Boundary "Advantage on saving throws against Charmed, Frightened ...", Gather Charge "Advantage on the
next Dexterity saving throw ..." were GM lines).

typed_executor.block_advantage gives the subject the condition "condition:typed.save_against" carrying
{"save_against": {"mode", "against": [conditions, "forced_movement"], "abilities": ["DEX", ...], "next": bool}}. At each typed
save (block_save) it changes the roll when the save's ability is one it names (or it names none) and what a failure would
impose is one it names (or it names none, but then it must name an ability). A "next" one is used up by that save.
"""

from __future__ import annotations

from typing import Any

from . import hook
from ..typed_executor import is_active_typed_condition

CONDITION = "condition:typed.save_against"


@hook("save")
def save_against(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    code = str(ability or "").upper()[:3]
    wanted = {str(value).lower() for value in named or ()}
    modes, used = [], []
    for instance_id, condition in subject.conditions.items():
        if not is_active_typed_condition(condition):
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("save_against") or {}
        against, abilities = set(rule.get("against") or []), list(rule.get("abilities") or [])
        if (not against and not abilities) or (abilities and code not in abilities) or (against and not against & wanted):
            continue
        modes.append(str(rule.get("mode") or "ADVANTAGE"))
        if rule.get("next"):
            used.append(instance_id)
    for instance_id in used:
        condition = subject.conditions.pop(instance_id)
        ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": CONDITION, "instance_id": instance_id, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": modes} if modes else None
