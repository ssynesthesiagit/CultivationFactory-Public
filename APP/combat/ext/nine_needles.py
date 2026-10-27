"""Heaven-Returning Nine Needles, mode Return the Living (Meridian Physician CL18: Action, touch, 8 Qi, once per scene):
"Regains Hit Points equal to half its Hit Point maximum. Regains Cultivation Points equal to twice your Proficiency Bonus. Ends
Charmed, Frightened, Poisoned, ordinary disease, ordinary Bleeding, and ordinary paralysis ... Stands without spending movement."

One effect on the creature touched (the user, or an ally): half its maximum HP restored (through the healing reductions every
heal meets), twice the healer's PB in Cultivation Points to its Path pool, the five named conditions ended, and Prone ended
(standing costs no movement). The rest -- a creature at 0 HP (out of the fight on this table), a maximum-HP or maximum-CP
reduction, a seal or blockage, the higher-CL check, the 10-foot step, the other three modes, the Physician's Burden price and the
Nine Needles Field -- stays with the GM as riders.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

ENDS = ("charmed", "frightened", "poisoned", "bleeding", "paralyzed", "prone")


@hook("button_description")
def living_description(row: dict[str, Any]) -> str | None:
    if any(eff.get("type") == "return_the_living" for eff in ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []):
        return "Restore half the touched creature's maximum HP and twice your Proficiency Bonus in Cultivation Points, end ordinary listed ailments and let it stand; recovery from 0 HP is resolved by the GM."
    return None


@effect("return_the_living")
def return_the_living(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import CP_POOLS, stored_healing_reductions, condition_rules, healing_activation

    engine = ctx.engine
    subject = ctx.target if ctx.target is not None else ctx.actor
    if not subject.active:
        ctx.rider(f"Return the Living: {subject.display_name} is at 0 Hit Points and out of the fight; the GM decides the recovery.")
        return
    healed = stored_healing_reductions(engine, subject, subject.maximum_hp // 2, healer=ctx.actor, source=ctx.source,
                                       sphere=str((ctx.typed or {}).get("sphere") or ""),
                                       power_resources=tuple(str(r) for r, _ in (ctx.action.costs or ())),
                                       eligible_recipients=(subject,), action_name=ctx.action.display_name,
                                       activation_id=f"{id(ctx.intent)}:{ctx.source}")
    with healing_activation(engine, f"{id(ctx.intent)}:{ctx.source}"):
        engine._heal(subject, healed, ctx.source, ctx.actor.entity_id)
    pool = next((rid for rid in CP_POOLS if rid in subject.resources and subject.resource_maximums.get(rid, 0) > 0), None)
    points = 2 * int(ctx.numbers.get("pb", 0))
    if pool is not None and points > 0:
        if any(row.get("no_cp_regain") for row in condition_rules(subject)):
            ctx.rider(f"{subject.display_name} cannot regain CP right now: {points} not regained.")
        else:
            engine._gain_resource(subject, pool, points, ctx.source)
    for name in ENDS:
        engine._remove_condition(subject, f"condition:typed.{name}", ctx.source)
