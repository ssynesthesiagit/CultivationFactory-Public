"""Blood sphere: the generic ``if_bloodied`` gate (sweep sw-blacksmith 2026-09-28).

Shared public is_bloodied helper: used by riders_metal for White Tiger Severance.
Several printed lines act only on a creature that is Bloodied: Blood Thread's "If the target is Bloodied, add your
Proficiency Bonus to one damage roll", Crimson Court's and Blood Emperor Incarnation's "When a Bloodied enemy starts its
turn ..." saving throw. The typed rows carried those as unconditional damage (Crimson Court dealt an unsaved 2d8 to every
hostile creature at every start of its turn, Blood Thread added its Proficiency Bonus to every hit). ``if_bloodied`` runs its
nested ``effects`` only against the creatures that are Bloodied -- at or below half their maximum HP, the same reading
combat/unmaking.py uses for "Bloodied" -- so a reviewed_final row can wrap exactly the part of the line the condition
qualifies. The subjects are the activation's own target(s) or, inside a zone trigger, the creature the trigger fired for.

``before_damage: true`` (Blood Thread) tests the creature as it stood when the attack was rolled. The sealed engine commits an
attack's first ``damage`` row inside ``_resolve_attack_spec``, and every other on-hit row -- this gate and what it wraps --
runs after it; the printed bonus is part of that damage roll, so it is decided by the HP the target had before the hit, and a
hit that carries a creature across the halfway mark does not earn it. Without the flag the creature is tested as it stands
(a zone trigger fires at the start of the creature's turn, with no damage in between).

Mirrors combat/ext/bodya_berserker.py's ``if_condition`` (a named condition) and typed_executor.block_if_marked (a placed
mark); nothing here writes state beyond the nested effects' own evented calls.
"""

from __future__ import annotations

from typing import Any

from . import effect

# How far back the event log is read for the attack that just resolved; an attack, its damage and every reaction it
# provokes (combat/typed_executor.block_attack) sit well inside it.
LOOKBACK = 80


def is_bloodied(creature: Any, hp: int | None = None) -> bool:
    """Bloodied: still active and at or below half its maximum HP (combat/unmaking.py's test); ``hp``: HP to test instead of its current."""
    if creature is None or not creature.active or creature.maximum_hp <= 0:
        return False
    return (creature.current_hp if hp is None else hp) * 2 <= creature.maximum_hp


def hp_before_attack(ctx: Any, target: Any) -> int:
    """The target's HP when the attack that is resolving was rolled: its HP now plus what that attack's own damage took.

    Read from the events like Batter's Exertion (combat/ext/gu_berserker.py); with no attack roll of this actor against this
    target in the window (the gate used outside an attack) its HP now is returned.
    """
    lost = 0
    for event in reversed(ctx.engine.events[-LOOKBACK:]):
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id and target.entity_id in (event.target_ids or ()):
            return target.current_hp + lost
        if event.event_type == "DAMAGE_COMMITTED" and target.entity_id in (event.target_ids or ()):
            lost += int((event.payload or {}).get("hp_damage") or 0)
    return target.current_hp


@effect("if_bloodied")
def if_bloodied(ctx: Any, eff: dict[str, Any]) -> None:
    """Generic gate: run the nested ``effects`` only against those of this activation's subjects that are Bloodied."""
    from ..typed_executor import Context, run_effects

    nested = eff.get("effects") or []
    if not nested:
        return
    pool = [ctx.target] if ctx.target is not None else list(ctx.targets)
    if eff.get("before_damage"):
        subjects = [subject for subject in pool if is_bloodied(subject, hp_before_attack(ctx, subject))]
    else:
        subjects = [subject for subject in pool if is_bloodied(subject)]
    if not subjects:
        return
    inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, subjects, subjects[0] if len(subjects) == 1 else None, ctx.damage_cache)
    run_effects(inner, nested)
