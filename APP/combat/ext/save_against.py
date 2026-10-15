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

from types import SimpleNamespace
from typing import Any

from . import hook
from ..typed_executor import is_active_typed_condition

CONDITION = "condition:typed.save_against"


@hook("save")
def save_against(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return stored_modes(ctx.engine, subject, ability, named,
                        support_receipts=getattr(ctx, 'save_support_sources', None))


def stored_modes(engine: Any, subject: Any, ability: str, named: Any,
                 wanted_mode: str | None = None, *, support_receipts: list | None = None) -> dict[str, Any] | None:
    """Read and consume matching grants at a real save; optionally one mode only."""
    code = str(ability or "").upper()[:3]
    wanted = {str(value).lower() for value in named or ()}
    modes, used, support_sources = [], [], []
    for instance_id, condition in subject.conditions.items():
        if not is_active_typed_condition(condition):
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("save_against") or {}
        against, abilities = set(rule.get("against") or []), list(rule.get("abilities") or [])
        if (not against and not abilities) or (abilities and code not in abilities) or (against and not against & wanted):
            continue
        mode = str(rule.get("mode") or "ADVANTAGE")
        if wanted_mode is not None and mode != wanted_mode:
            continue
        modes.append(mode)
        if mode == 'ADVANTAGE' and condition.source_actor_id and condition.source_definition_id:
            support_sources.append({'actor_id': condition.source_actor_id,
                                    'source_id': condition.source_definition_id})
        if rule.get("next"):
            used.append(instance_id)
    for instance_id in used:
        condition = subject.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": CONDITION, "instance_id": instance_id, "reason": "CONSUMED"})
    from ..typed_executor import condition_rules
    if any(code in (row.get('no_save_advantage') or []) for row in condition_rules(subject)):
        support_sources = []
    if support_receipts is not None:
        support_receipts.extend(s for s in support_sources if s not in support_receipts)
    return {"bonus": 0, "modes": modes} if modes else None


@hook('save_mode')
def native_advantage(engine: Any, subject: Any, ability: str, dc: int,
                     source_id: str, context: dict[str, Any]) -> str | None:
    """Native repeated saves honor the same named-condition grants as typed saves.

    Typed next-save grants have already been consumed by their typed wrapper;
    persistent grants contribute the same mode again to the native mode set.
    Separate mode callbacks preserve Advantage/Disadvantage cancellation.
    """
    if context.get("include_stored_save_bonuses") is True:
        return None  # The opted-in combined reader below owns consumption.
    from ..typed_executor import condition_rules
    grant = stored_modes(engine, subject, ability, context.get('named') or (), 'ADVANTAGE')
    if any(ability.upper() in (row.get('no_save_advantage') or []) for row in condition_rules(subject)):
        return None
    if grant:
        return 'ADVANTAGE'


@hook('save_mode')
def native_disadvantage(engine: Any, subject: Any, ability: str, dc: int,
                        source_id: str, context: dict[str, Any]) -> str | None:
    if context.get("include_stored_save_bonuses") is True:
        return None
    if stored_modes(engine, subject, ability, context.get('named') or (), 'DISADVANTAGE'):
        return 'DISADVANTAGE'
@hook("save_mode")
def native_save_against(engine: Any, subject: Any, ability: str, dc: int, source: str,
                        roll_context: dict[str, Any]) -> list[str] | None:
    """Apply typed next-save modes to native saves that explicitly opt in.

    The ordinary typed-save path continues to use the ``save`` hook above. A
    native caller must pass ``include_stored_save_bonuses`` in its roll context;
    this keeps typed saves from counting or consuming the same status twice.
    Matching one-use statuses are consumed by the same reader used for typed
    saves. Native condition repeats opt in at their single roll call. Every
    contribution is retained until the native engine cancels opposing modes.
    """
    if roll_context.get("include_stored_save_bonuses") is not True:
        return None
    answer = save_against(SimpleNamespace(engine=engine), subject, ability,
                          roll_context.get("named") or ())
    # Keep each stored contribution separate. The engine has already collected
    # ordinary and other-hook modes; collapsing opposing modes here would hide
    # the stored rows from that final cancellation and can leave an ordinary
    # Advantage or Disadvantage active by itself.
    modes = list((answer or {}).get("modes") or ())
    return modes or None
