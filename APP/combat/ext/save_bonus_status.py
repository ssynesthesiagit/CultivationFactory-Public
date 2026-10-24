"""A flat bonus to saving throws for as long as an ability says (lane 1 automation, 2026-09-29: Calming Heart Pill "+1 to
saving throws against the Charmed condition, the Frightened condition ...", Warding Talisman "+1 to saving throws using that
ability" for 1 hour -- both were GM lines because nothing gave a save a flat number for a duration).

Effect type "save_bonus" (an ability's typed effect): {"type": "save_bonus", "applies_to": "self" | "target" | "ally",
"flat": 1, "abilities": ["DEX"] (none = every ability), "against": ["charmed", "frightened"] (none = every save; the names a
save's failure imposes, as combat/ext/save_against.py reads them), "family": "warding_talisman" (a new bonus of the same
family replaces the old on that creature), "duration": ...}. It puts the condition "condition:typed.save_bonus" on the
subject, expiring as any typed effect does (typed_executor.effect_expiry; "for 1 hour" lasts the fight).

Hook use: "save" (ctx, subject, ability, named) -> {"bonus": n, "modes": []}, before a typed save is rolled; it adds the
bonus of every such condition on the subject that covers the save (the bonuses add, as the engine sums every save hook).
Native save_bonus uses the same reader for native saves, including escape_options
Action repeat saves. active_save_pending excludes typed saves whose bonus was
already applied by the save hook, so it never adds a second copy. Native named
hazards are read only from that save's d20_context; an unknown hazard cannot
qualify a condition-specific bonus. Both readers are pure and default-inert.
Determinism: the condition is applied and removed only through the engine's evented _apply_condition / _remove_condition.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

CONDITION = "condition:typed.save_bonus"


def _label(amount: int, abilities: list[str], against: list[str]) -> str:
    return f"+{amount} to saving throws" + (f" ({'/'.join(abilities)})" if abilities else "") + \
        (f" against {', '.join(against)}" if against else "")


@effect("save_bonus")
def save_bonus(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    amount = int(eff.get("flat") or eff.get("amount") or 0)
    if not amount:
        return
    abilities = [str(value).upper()[:3] for value in eff.get("abilities") or [] if str(value).strip()]
    against = [str(value).lower() for value in eff.get("against") or []]
    family = str(eff.get("family") or "")
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is None or not subject.active:
            continue
        if family:  # "A creature can benefit from only one Warding Talisman at a time": the new one replaces the old
            for condition in list(subject.conditions.values()):
                if condition.condition_id == CONDITION and \
                        (((condition.data or {}).get("rule") or {}).get("save_bonus") or {}).get("family") == family:
                    ctx.engine._remove_condition(subject, condition.condition_id, ctx.source)
        ctx.engine._apply_condition(
            subject, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
            data={"rule": {"save_bonus": {"bonus": amount, "abilities": abilities, "against": against, "family": family}},
                  "label": _label(amount, abilities, against)})


@hook("save")
def save_bonus_rolls(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    total = _bonus(subject, ability, named)
    return {"bonus": total, "modes": []} if total else None


def _bonus(subject: Any, ability: str, named: Any) -> int:
    code = str(ability or "").upper()[:3]
    wanted = {str(value).lower() for value in named or ()}
    total = 0
    for condition in subject.conditions.values():
        if condition.condition_id != CONDITION:
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("save_bonus") or {}
        abilities, against = list(rule.get("abilities") or []), {str(v).lower() for v in rule.get("against") or []}
        if (abilities and code not in abilities) or (against and not against & wanted):
            continue
        total += int(rule.get("bonus") or 0)
    return total


# Native repeated saving throws do not pass through typed_executor.block_save.
# Bound the existing status reader to that exact native repeat resolution so a
# direct typed save (which already adds these bonuses) cannot count them twice.
from contextvars import ContextVar
from contextlib import contextmanager
_REPEAT = ContextVar('save_bonus_status_native_repeat', default=None)


@hook('repeat_save_scope')
@contextmanager
def native_repeat_scope(engine: Any, resolution: dict[str, Any]):
    token = _REPEAT.set((engine, resolution['holder_id'], resolution['source_definition_id']))
    try:
        yield
    finally:
        _REPEAT.reset(token)


@hook("save_bonus")
def native_save_bonus(engine: Any, subject: Any, ability: str, dc: int,
                      source_id: str, intent: Any) -> int | None:
    """Apply statuses to repeat/legacy saves; the typed route already applies them."""
    from ..typed_executor import active_save_pending

    if active_save_pending(engine, source_id, subject.entity_id):
        return None
    context = engine.d20_context() or {}
    result = save_bonus_rolls(None, subject, ability, context.get("named") or ())
    return result["bonus"] if result else None
