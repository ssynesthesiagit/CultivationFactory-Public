"""A creature's next attack roll deals reduced damage (riders lane 2, 2026-09-29: Bell-Ringing Body Shot, "the target's next attack
roll before the end of its next turn deals reduced damage equal to twice your Proficiency Bonus").

    {"type": "next_attack_damage", "applies_to": "target", "amount": "twice_pb", "duration": "until_end_of_next_turn"}

puts the condition ``condition:typed.next_attack_damage`` on the affected creature (``amount``: a number, "pb" or "twice_pb" -- the
Proficiency Bonus is the user's).  Its next attack roll is the first one it makes after that: a miss uses it up; a hit has its damage
reduced (the attack's own damage, the first packet it deals, never below 0) and uses it up; it also ends at the printed deadline.
Only an attack roll is affected -- a save technique or a damage-over-time tick the creature causes is not.

The reduction is taken in ``source_damage_reduction`` (combat/typed_reactions.defend), before transfers or recipient defenses.
The engine runs that hook for a Factory fighter that is
hit, so an attacker that is a Factory fighter or an NPC is reduced the same way; a hit on an NPC target is not reduced (the
engine's own damage commit does not run the hook there).

Deterministic and evented: the condition is applied and removed with the engine's own methods; the "this attack was already rolled
once" note is a turn flag whose key contains ``_round_`` (restored on reload).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance, refresh_owned

CONDITION = "condition:typed.next_attack_damage"
SEEN = "_round_next_attack_damage_seen"


def _amount(ctx: Any, row: dict[str, Any]) -> int:
    value = row.get("amount")
    pb = int(ctx.numbers.get("pb") or 2)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "pb").lower().replace(" ", "_")
    return pb * 2 if text in ("twice_pb", "2pb", "double_pb") else pb


@effect("next_attack_damage")
def apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    amount = _amount(ctx, row)
    for target in _default_subject(ctx, row, harmful=True):
        refresh_owned(ctx.engine, target, CONDITION, ctx.actor.entity_id, ctx.source)
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, row, target, condition=True),
                                    data={"amount": amount, "label": f"Its next attack roll deals {amount} less damage"})


def _held(actor: Any) -> Any | None:
    return next((condition for condition in actor.conditions.values() if condition.condition_id == CONDITION), None)


@hook("event")
def roll_seen(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The holder's attack roll: a second one finds the condition already used (no roll it made is affected but the first); a miss
    uses it up now."""
    if event_type != "ATTACK_ROLLED":
        return
    from .attack_scope import current
    holder = engine.state.actors.get(kwargs.get("actor_id") or "")
    if holder is None:
        return
    seen = set(str(holder.turn_flags.get(SEEN) or "").split("|"))
    pending = []
    for held in list(holder.conditions.values()):
        if held.condition_id != CONDITION:
            continue
        if held.instance_id in seen and held.data.get("attack_roll_id"):
            if current(engine) is None:
                remove_instance(engine, holder, held.instance_id, "system:next_attack_damage.consumed")
                continue
            # A nested roll cannot steal a reduction bound to its parent roll.
            pending.append(held.instance_id)
            continue
        if held.instance_id in seen or not (kwargs.get("payload") or {}).get("provisional_hit"):
            remove_instance(engine, holder, held.instance_id, "system:next_attack_damage.consumed")
        else:
            pending.append(held.instance_id)
    if pending:
        holder.turn_flags[SEEN] = "|".join(pending)
        payload = kwargs.get("payload") or {}
        for instance_id in pending:
            if holder.conditions[instance_id].data.get("attack_roll_id"):
                continue
            holder.conditions[instance_id].data.update(
                attack_roll_id=str(payload["roll_id"]),
                attack_source=str(payload["reason"]).removeprefix("ATTACK:").rsplit(":", 1)[0],
                attack_target=str(next(iter(kwargs.get("target_ids") or ()), "")))
    else:
        holder.turn_flags.pop(SEEN, None)

@hook("source_damage_reduction")
def reduce(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str | None, source_actor_id: str | None) -> int:
    holder = engine.state.actors.get(source_actor_id or "")
    if holder is None:
        return 0
    seen = set(str(holder.turn_flags.get(SEEN) or "").split("|"))
    held = [c for c in holder.conditions.values() if c.condition_id == CONDITION and c.instance_id in seen]
    if not held:
        return 0
    from .attack_scope import current

    attack = current(engine)
    # Legacy engine attacks lack the typed scope. Retain their supported
    # non-recursive delivery using the holder's exact roll, never another
    # actor's latest roll or an arbitrary event window.
    roll_id = attack["roll_id"] if attack is not None else next(
        (e.payload.get("roll_id") for e in reversed(engine.events)
         if e.event_type == "ATTACK_ROLLED" and e.actor_id == holder.entity_id), "")
    held = [c for c in held if c.data.get("attack_source") == source_definition_id
            and c.data.get("attack_target") == target.entity_id
            and c.data.get("attack_roll_id") == roll_id]
    if not held:
        return 0
    # Preserve non-stacking magnitude while consuming every instance whose
    # printed next attack occurred. Never leave another caster's first-use
    # condition to penalize a later attack.
    cut = min(max(int(c.data.get("amount") or 0) for c in held), max(0, int(amount)))
    for c in held:
        remove_instance(engine, holder, c.instance_id, "system:next_attack_damage.consumed")
    holder.turn_flags.pop(SEEN, None)
    return cut


@hook("attack_roll_finished")
def finish(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    """A rolled attack consumes the benefit even if a defense cancels its damage."""
    if not roll_id:
        return
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id == CONDITION and held.data.get("attack_roll_id") == roll_id:
            remove_instance(ctx.engine, ctx.actor, held.instance_id, "system:next_attack_damage.consumed")
    remaining = [c.instance_id for c in ctx.actor.conditions.values()
                 if c.condition_id == CONDITION and c.data.get("attack_roll_id")]
    if remaining:
        ctx.actor.turn_flags[SEEN] = "|".join(remaining)
    else:
        ctx.actor.turn_flags.pop(SEEN, None)
