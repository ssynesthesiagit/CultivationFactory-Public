"""Medicinal Wax preparations, attached by the mandatory reviewed modifier.

Only new sealed wax_medicine rows create these conditions; old catalogs and
creatures without this talent remain unchanged. The existing save, speed and
final_damage seams own delivery, and exact-instance event removal owns reload.
Cooling/Numbing end on the caster's next turn; Stimulating ends on the recipient's.
Native repeats use the documented repeat_save_scope/save_mode seams; their
transient scope never enters saved state and unwinds on errors/player pauses.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id
from .rider_support import remove_instance
from .effect_durations import token

FEATURE = "TAL_WAX_MEDICINAL_WAX"
PREFIX = "condition:typed.wax_medicine."
_COOLING_REPEAT = ContextVar("wax_cooling_repeat", default=None)


def held(actor: Any, preparation: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == PREFIX + preparation]


def cooling_hazard(named: Any) -> bool:
    return bool({str(n).lower() for n in named or ()}
                & {"damage:fire", "damage:poison", "poisoned", "disease", "diseased"})


@effect("wax_medicine")
def prepare(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target or (ctx.targets[0] if ctx.targets else ctx.actor)
    labels = {
        "cooling": "Cooling Wax: Advantage on the next save against fire, poison or disease before your next turn ends",
        "stimulating": "Stimulating Wax: +10 feet Speed until the target's next turn ends",
        "numbing": f"Numbing Wax: reduce the next damage by {int(ctx.numbers.get('pb') or 0)} before your next turn ends",
    }
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "wax_medicine", ctx.source, target.entity_id),
                 ctx.actor, "choice:needle.wax_medicine", list(labels), labels=labels,
                 minimum=1, maximum=1, preferred=["numbing"], name="Medicinal Wax", feature_id=FEATURE,
                 target_id=target.entity_id,
                 prompt=f"Medicinal Wax: {ctx.actor.display_name} uses {ctx.action.display_name} on {target.display_name}. "
                        "Choose one preparation; it costs no additional Cultivation Points.")
    if not chosen:
        return
    preparation = chosen[0]
    speed_before = ctx.engine._effective_speed(target) if preparation == "stimulating" else 0
    # Reapplying this caster's preparation refreshes it without stacking.
    for old in held(target, preparation):
        if old.source_actor_id == ctx.actor.entity_id:
            remove_instance(ctx.engine, target, old.instance_id, FEATURE)
    clock = target if preparation == "stimulating" else ctx.actor
    ctx.engine._apply_condition(target, PREFIX + preparation, ctx.source, ctx.actor.entity_id,
                               expires_on=token("end", clock.entity_id, clock.turns_started + 1),
                               data={"pb": int(ctx.numbers.get("pb") or 0),
                                     "label": labels[preparation].replace("your next turn", ctx.actor.display_name + "'s next turn")
                                                                   .replace("the target's next turn", target.display_name + "'s next turn")})
    if preparation == "stimulating" and ctx.engine.state.current_actor_id == target.entity_id:
        # Match the existing mid-turn Speed-change convention (Encumbered/Mantles).
        # Refreshing an existing preparation grants no additional movement.
        change = ctx.engine._effective_speed(target) - speed_before
        if change:
            target.movement_remaining_ft = max(0, int(target.movement_remaining_ft) + change)
            ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=target.entity_id,
                                     payload={"distance_ft": change})


@hook("save")
def cooling(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None or not held(subject, "cooling"):
        return None
    if not cooling_hazard(named):
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("save_final")
def cooling_spent(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """A canceled save does not spend the next-roll benefit."""
    if subject is None or not cooling_hazard(named):
        return
    for condition in held(subject, "cooling"):
        remove_instance(ctx.engine, subject, condition.instance_id, FEATURE)


@hook("repeat_save_scope")
def cooling_repeat_scope(engine: Any, resolution: dict[str, Any]) -> Any:
    subject = engine.state.actors.get(resolution["holder_id"])
    if subject is None or not cooling_hazard(resolution["named"]):
        return None
    preparations = held(subject, "cooling")
    if not preparations:
        return None

    @contextmanager
    def bounded():
        token = _COOLING_REPEAT.set((engine, resolution))
        try:
            yield
            # Only a completed native roll spends the preparations present at
            # entry. Exceptions and player pauses skip this settlement.
            if resolution["roll"] is not None:
                for condition in preparations:
                    if condition.instance_id in subject.conditions:
                        remove_instance(engine, subject, condition.instance_id, FEATURE)
        finally:
            _COOLING_REPEAT.reset(token)

    return bounded()


@hook("save_mode")
def cooling_repeat_mode(engine: Any, subject: Any, ability: str, dc: int,
                        source_id: str, context: dict[str, Any]) -> str | None:
    current = _COOLING_REPEAT.get()
    if current is None or current[0] is not engine or not held(subject, "cooling"):
        return None
    resolution = current[1]
    if (resolution["roll"] is None
            and (subject.entity_id, ability, dc, source_id)
            == (resolution["holder_id"], resolution["ability"], resolution["dc"],
                resolution["source_definition_id"])
            and tuple(context.get("named") or ()) == resolution["named"]):
        return "ADVANTAGE"
    return None


@hook("speed")
def stimulating(engine: Any, actor: Any) -> Any:
    from ..speed_contributions import SpeedContribution

    return SpeedContribution([(FEATURE, "Stimulating Wax", 10)] if held(actor, "stimulating") else [])


@hook("final_damage")
def numbing(engine: Any, target: Any, amount: int, damage_type: str, source_id: str,
            source_actor_id: Any, intent: Any) -> dict[str, Any] | None:
    preparations = held(target, "numbing")
    if amount <= 0 or not preparations:
        return None
    reduction = min(amount, max(0, max(int(c.data.get("pb") or 0) for c in preparations)))

    def settle(applied: int) -> None:
        # Another defense may prevent the entire packet. Spend only when this
        # preparation actually reduces damage at the final-damage checkpoint.
        if applied > 0:
            for condition in preparations:
                if condition.instance_id in target.conditions:
                    remove_instance(engine, target, condition.instance_id, FEATURE)

    return {"reduction": reduction, "settle": settle}
