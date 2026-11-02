"""Shared source-qualified ordinary holds for Abyssal Depths defenses, Trap escape choices
and wrestling_framework's physical-grip cleanup on incapacity.

Core Unarmed Grapple is ordinary physical. Trap supplies exact linked Net/Noose sources
through hold_source; linked_holds supplies opted-in Wrestling Pin sources. Other rows must explicitly declare
``hold_kind: ordinary_physical`` from their printed authority; a condition name alone is
insufficient (magical, Force and Formation holds are not ordinary). Unknown source CL
stays unknown. Helpers query catalogs only and do not change old saved fights.
"""

from typing import Any


def ordinary(typed: dict[str, Any], effect: dict[str, Any]) -> bool:
    name = str(effect.get("condition") or "").lower()
    return name in {"grappled", "restrained"} and (
        effect.get("hold_kind") == "ordinary_physical"
        or (name == "grappled" and typed.get("unarmed_option") == "grapple"))


def _conditions(rows: Any):
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("type") == "condition":
            yield row
        for key in ("effects", "on_hit", "on_fail", "on_success", "on_miss"):
            yield from _conditions(row.get(key))


def source(engine: Any, condition: Any) -> tuple[bool, int | None]:
    """Return ordinary-physical classification and the original action's compiled CL."""
    from . import run

    answers = [answer for answer in run("hold_source", engine, condition) if answer is not None]
    if len(answers) == 1:
        answer = answers[0]
        if (isinstance(answer, tuple) and len(answer) == 2 and type(answer[0]) is bool
                and (answer[1] is None or type(answer[1]) is int)):
            return answer
        return False, None
    if answers:
        return False, None  # conflicting classifiers never establish an ordinary hold
    action = engine.action_catalog.get(condition.source_definition_id)
    if action is None or action.owner_id != condition.source_actor_id:
        return False, None
    typed = (action.parameters or {}).get("typed") or {}
    name = condition.condition_id.removeprefix("condition:typed.")
    # Tracked rows require the runtime link supplied by hold_source; the catalog
    # alone must never promote an untracked legacy restraint to an ordinary hold.
    physical = any(not row.get("tracking") and str(row.get("condition") or "").lower() == name and ordinary(typed, row)
                   for row in _conditions(typed.get("effects")))
    cl = (typed.get("numbers") or {}).get("cl")
    return physical, int(cl) if cl is not None else None


def end_hold(ctx: Any, key: str) -> None:
    """End one hold and its linked bookkeeping markers (Abyssal Depths and Trap escape)."""
    from . import run

    actor = ctx.actor
    related = {key}
    for answer in run("hold_companions", ctx.engine, actor, key):
        if answer is not None:
            related.update(iid for iid in answer if isinstance(iid, str) and iid in actor.conditions)
    for iid in sorted(related):
        condition = actor.conditions.pop(iid, None)
        if condition is not None:
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id,
                                     target_ids=(actor.entity_id,), payload={"condition_id": condition.condition_id,
                                     "instance_id": iid, "reason": "ENDED"})
