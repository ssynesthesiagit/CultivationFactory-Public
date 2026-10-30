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
                 wanted_mode: str | None = None, *, resolve_bonus: bool = True,
                 support_receipts: list | None = None) -> dict[str, Any] | None:
    """Consume matching grants, preserving attribution and optional numeric support.

    Mode-only readers never select or spend numeric bonuses. Actual typed saves
    may also collect their provider receipts before next-save grants disappear.
    """
    code = str(ability or "").upper()[:3]
    wanted = {str(value).lower() for value in named or ()}
    modes, used, bonus = [], [], 0
    support_sources = []
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
        if mode == 'ADVANTAGE' and resolve_bonus:
            from ..support_values import condition_purpose, resolve_save_bonus
            from ..typed_executor import condition_rules
            purpose = condition_purpose(SimpleNamespace(condition_id='', data={'origin_save': {'named': sorted(wanted)}}))
            provider = engine.state.actors.get(condition.source_actor_id)
            if (purpose is not None and provider is not None
                    and not any(code in (row.get('no_save_advantage') or []) for row in condition_rules(subject))):
                bonus += resolve_save_bonus(engine, provider, subject, condition.source_definition_id, purpose)
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
    return {"bonus": bonus, "modes": modes} if modes else None


@hook('save_mode_contributions')
def native_advantage(engine: Any, subject: Any, ability: str, dc: int,
                     source_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Native repeated saves honor the same named-condition grants as typed saves.

    Typed next-save grants have already been consumed by their typed wrapper;
    persistent grants contribute the same mode again to the native mode set.
    Separate mode callbacks preserve Advantage/Disadvantage cancellation.
    """
    from ..typed_executor import condition_rules
    grant = stored_modes(engine, subject, ability, context.get('named') or (),
                         resolve_bonus=not context.get('mode_only', False))
    if grant is None:
        return None
    if any(ability.upper() in (row.get('no_save_advantage') or []) for row in condition_rules(subject)):
        grant['modes'] = [mode for mode in grant['modes'] if mode != 'ADVANTAGE']
    return grant
