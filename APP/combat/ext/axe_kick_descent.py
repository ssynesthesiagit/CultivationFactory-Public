"""Axe-Kick Descent: the 2d6 needs a real descent earlier that turn, once per descent.

``TAL_IRON_FIST_AXE_KICK_DESCENT`` prints: "When you fall at least 10 feet, jump down,
or descend from a higher space and hit a creature with an Unarmed Strike before the end
of the turn, add 2d6 Bludgeoning or Force damage."  The reviewed rider row carries that
condition as free text in ``precondition`` (APP/authority/typed_mechanics/
reviewed_final.d/riders_lane2.json), which the compiler only prints for the rider list;
nothing evaluated it, so the rider rode every unarmed hit of every turn.

The rider is one packet with two rows -- the 2d6 and "If the target was already Opened,
it makes a Strength saving throw" -- and both carry ``source_modifier`` set to this talent,
so the gate below answers for the whole packet rather than for the damage alone. Gating
only the damage left the save and its Prone reaching a target that was never descended on.

``record_descent`` listens for the movement the printed text names -- a fall of at least
10 feet, a jump down, or any drop to a lower elevation -- and leaves a turn stamp on the
mover.  It subscribes with ``nested=True`` because a real descent is often committed from
inside another hook: ending Featherfall during the turn-start hook removes the flight
condition and settles the fall while the turn is still dispatching, and a root-only
subscriber never sees that movement.

``descent_needs_one`` is a pure query. A successfully resolved rider records its actor,
target and attack roll in a transaction-owned integer receipt; ``attack_damage_final`` spends the
descent after all attached rows finish, before the next attack or table commit. A vetoed
packet never enters its block, so it cannot spend the descent. Another actor's attack
cannot consume that receipt.

Inert for anyone who does not own the Form: every hook answers only for the rider's own
``passive:`` effect source, and the movement listener only stamps actors whose compiled
bundle lists the talent.
"""
from __future__ import annotations

from typing import Any
from contextlib import contextmanager

from . import hook
from .descent_steps import dropped as _dropped, held as _held, stamp as _stamp, turn_stamp as _turn_stamp

TALENT = "TAL_IRON_FIST_AXE_KICK_DESCENT"
RIDER = f"passive:{TALENT}"
FLAG = "axe_kick_descent"
SPENT = "axe_kick_descent_spent"
# Integer receipts in actor state roll back with the transaction and are removed at completion.
PENDING = "_axe_kick_descent_pending"


def _owns(engine: Any, actor: Any) -> bool:
    """True when this fighter's own compiled bundle lists Axe-Kick Descent."""
    if actor is None:
        return False
    for bundle in (getattr(engine, "typed_bundle_documents", None) or ()):
        if (bundle.get("actor_id") or "") != actor.entity_id:
            continue
        for group in ("melds", "abilities", "talents", "forms", "passives"):
            if TALENT in (bundle.get(group) or []):
                return True
        if any(row.get("id") == TALENT for row in bundle.get("modifiers") or ()):
            return True
    return False


def _unspent(engine: Any, actor: Any) -> bool:
    """True when this turn holds a descent the actor has not already spent on a hit."""
    return _held(engine, actor, FLAG, SPENT)


@hook("event", nested=True)
def record_descent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Stamp the mover when they fall at least 10 feet, jump down, or drop in elevation."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active or not _owns(engine, mover):
        return
    if not _dropped(kwargs.get("payload") or {}):
        return
    _stamp(engine, mover, FLAG, SPENT)


@hook("effect_allowed")
def descent_needs_one(ctx: Any, effect: dict[str, Any]) -> bool | None:
    """Allow the whole Axe-Kick packet only while this turn holds an unspent descent.

    Pure: it reads the turn flags and changes nothing, so asking twice gives the same
    answer and a later veto cannot leave the descent already spent.
    """
    if effect.get("source_modifier") != TALENT:
        return None
    engine, actor = ctx.engine, ctx.actor
    if not _owns(engine, actor):
        return None
    return None if _unspent(engine, actor) else False


@hook("effect_resolution_scope")
def rider_resolved(ctx: Any, effect: dict[str, Any]) -> Any:
    """Record only an accepted packet of this actor's explicitly attributed attack."""
    if effect.get("source_modifier") != TALENT or effect.get("type") not in ("extra_damage", "if_marked"):
        return None
    if not _owns(ctx.engine, ctx.actor):
        return None
    provenance = ctx.attack_damage_context
    if provenance is None or provenance.attacker_id != ctx.actor.entity_id:
        return None
    return _accepted_packet(ctx, provenance)


def _attack_key(provenance: Any) -> str:
    return f"{PENDING}:{provenance.attacker_id}:{provenance.target_id}:{provenance.roll_id}"


@contextmanager
def _accepted_packet(ctx: Any, provenance: Any):
    stamp = _turn_stamp(ctx.engine)
    yield
    ctx.actor.turn_flags[_attack_key(provenance)] = stamp


@hook("attack_damage_final")
def spend_descent(engine: Any, actor: Any, target: Any, provenance: Any, intent: Any) -> None:
    """Spend for the originating completed attack, before another hit or disk save."""
    if not _owns(engine, actor) or provenance.attacker_id != actor.entity_id:
        return
    stamp = actor.turn_flags.pop(_attack_key(provenance), None)
    if stamp is not None and stamp == _turn_stamp(engine):
        actor.turn_flags[SPENT] = stamp
