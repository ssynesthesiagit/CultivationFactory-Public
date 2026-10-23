"""Unbroken Rim: the Shield refuses the one thing that would end it (AUTO55, 2026-10-05).

Sphere Compendium, Shield (owner's text: ``APP/authority/typed_mechanics/rules_text.json``):

  Unbroken Rim, TAL_SHIELD_UNBROKEN_RIM
    "Prerequisite: CL 7+. When your Shield would break, be disarmed, become suppressed, or be destroyed by an
     ordinary effect, expend Martial Focus. Choose one: the Shield remains intact and equipped; the Shield becomes
     cracked but functional until the end of your next turn; immediately catch and re-equip the Shield after it is
     disarmed."

What the table did before: the talent compiled to nothing at all (its record typed no effect, only three rider
lines), so a fighter who had taken it lost their Shield the first time anything broke, dropped or took it. Every way
a Shield leaves a fighter's hands is already a recorded event in this fight, so this plug-in watches those two and
asks the printed question:

* ``condition_attempt`` -- the moment anything is about to break the Shield (``condition:typed.shield_broken``, from
  Sacrificial Shield or any other printed break);
* ``event`` on ``CONDITION_APPLIED`` -- the Shield being dropped or taken out of the fighter's hands (a condition
  carrying its inventory key), which is the Disarm and "Open Hand" path.

Shared helper: shield_riders uses owning to route destruction through this prevention.

Both read the same helper, :func:`offer`, which spends 1 Martial Focus, asks which of the three printed results the
player wants, and does it. Inert without the talent's own compiled row
(combat/rules/feature_blocks.d/auto55_shield.json) and for a fighter out of Martial Focus: that is the printed cost.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "auto55_shield"
UNBROKEN = "TAL_SHIELD_UNBROKEN_RIM"
FOCUS = "resource:core.martial_focus"
BROKEN = "condition:typed.shield_broken"
CRACKED = "condition:typed.shield_cracked"
ARMED = "condition:typed.unbroken_rim"

LABELS = {"intact": "The Shield stays intact and equipped",
          "cracked": "The Shield is cracked but still works, until the end of your next turn",
          "catch": "Catch the Shield and put it straight back in your hand"}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Unbroken Rim's compiled marker (combat/rules/feature_blocks.d/auto55_shield.json)."""
    if block != BLOCK or str(spec.get("kind") or "") != "unbroken_rim":
        return None
    return [{**row, "block": BLOCK, "kind": "unbroken_rim"}]


def owning(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Ownership query shared with shield_riders to route actual breakage through prevention."""
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == "unbroken_rim"), None)


@effect("unbroken_rim")
def armed(ctx: Any, eff: dict[str, Any]) -> None:
    """The talent's own marker. Unbroken Rim is answered at the moment the Shield is about to be lost
    (``condition_attempt`` and ``event`` below), so this records that the rescue is standing by; the two hooks read
    the compiled row, so a fighter whose talent is only a passive row still answers."""
    ctx.engine._apply_condition(ctx.actor, ARMED, UNBROKEN, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Unbroken Rim: 1 Martial Focus keeps your Shield the next time something takes it"})


def shield_key(engine: Any, actor: Any) -> str | None:
    from .. import armour

    return armour.shield_item_key(engine, actor)


def offer(engine: Any, actor: Any, cause: str, detail: str, *, choices: tuple[str, ...] = ("intact", "cracked", "catch")) -> bool:
    """Spend 1 Martial Focus and apply one of the printed results. True when the Shield was kept."""
    if actor is None or not actor.active or owning(engine, actor) is None:
        return False
    if int(actor.resources.get(FOCUS, 0)) < 1:
        return False
    from .choice_costs import Payment
    from .choice_prompt import action_context

    intent = getattr(engine, '_active_intent', None)
    source = getattr(engine, '_active_action_source_id', '') or ''
    trigger_actor = engine.state.actors.get(getattr(intent, 'actor_id', ''))
    payment = Payment(FOCUS, 1)
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "UNBROKEN_RIM", actor.entity_id),
                 actor, CHOICE + "unbroken_rim", list(choices), labels=LABELS, allow_decline=True,
                 target_id=actor.entity_id,
                 prompt=f"{detail} -- Unbroken Rim: spend 1 Martial Focus to keep your Shield?",
                 name="Unbroken Rim", feature_id=UNBROKEN, payment=payment,
                 prompt_context=action_context(engine, trigger_actor, source, actor))
    if not picked:
        return False
    payment.pay(engine, actor, UNBROKEN)
    choice = picked[0]
    _recover(engine, actor, repair=choice != 'catch')
    if choice == "cracked":
        engine._remove_condition(actor, BROKEN, UNBROKEN)
        from .effect_durations import next_owner_turn, token
        engine._apply_condition(actor, CRACKED, UNBROKEN, actor.entity_id, expires_on=token("end", actor.entity_id, next_owner_turn(actor)),
                                data={"label": "Unbroken Rim: the cracked Shield works until the end of your next turn, then breaks"})
        text = f"{actor.display_name}'s Shield is cracked, but it still works until the end of their next turn."
    elif choice == "catch":
        text = f"{actor.display_name} catches the Shield and puts it straight back in their hand."
    else:
        engine._remove_condition(actor, BROKEN, UNBROKEN)
        engine._remove_condition(actor, CRACKED, UNBROKEN)
        text = f"{actor.display_name}'s Shield stays intact and equipped."
    note(engine, UNBROKEN, actor, f"Unbroken Rim ({cause}): {text}")
    return True


@hook('effect_expiring_choice')
def cracked_functionality_ends(engine: Any, holder: Any, condition: Any) -> None:
    """The timed cracked choice postpones breakage; only the intact choice repairs it.

    The turn-counted expiry sweep calls this before removing the cracked marker.
    Ordinary removal (a later intact rescue) does not trigger this deadline.
    """
    if getattr(condition, 'condition_id', None) != CRACKED:
        return
    from .shield_breakage import resume

    resume(engine, holder, condition, UNBROKEN)
    if any(c.condition_id == BROKEN for c in holder.conditions.values()):
        note(engine, UNBROKEN, holder,
             f"Unbroken Rim: {holder.display_name}'s cracked Shield stops working at the end of their next turn.")


def _recover(engine: Any, actor: Any, *, repair: bool) -> None:
    """Re-equip the Shield; catching it preserves existing damage and its deadline.

    The intact/cracked choices restore functionality. Catching merely restores
    possession and must not erase a previous cracked Shield's expiry token.
    """
    from .. import carry

    if repair:
        engine._remove_condition(actor, BROKEN, UNBROKEN)
        engine._remove_condition(actor, CRACKED, UNBROKEN)
    key = shield_key(engine, actor)
    if key is None:
        return
    holders = set()
    for iid, condition in list(actor.conditions.items()):
        if (condition.data or {}).get("item_key") == key and ((condition.data or {}).get("held_by")
                                                              or (condition.data or {}).get("dropped_at")):
            if condition.data.get('held_by'):
                holders.add(condition.data['held_by'])
            del actor.conditions[iid]
            engine._append_event('CONDITION_REMOVED', UNBROKEN, actor_id=actor.entity_id,
                                 target_ids=(actor.entity_id,),
                                 payload={'condition_id': condition.condition_id, 'instance_id': iid})
    carry.refresh(engine, actor, UNBROKEN)
    for holder_id in holders:
        holder = engine.state.actors.get(holder_id)
        if holder is not None:
            carry.refresh(engine, holder, UNBROKEN)


@hook("condition_attempt", priority=10)
def keep_the_shield_from_breaking(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """False stops the break: Unbroken Rim already paid for the Shield to survive.

    Run after ordinary prevention, including the optional Never Falls rescue,
    so an already prevented break cannot spend Focus, regardless of import order.
    """
    if str((effect or {}).get("condition") or "") != "shield_broken":
        return None
    if effect.get('shield_rescue_excluded') == UNBROKEN:
        return None
    if not offer(ctx.engine, subject, "the Shield breaking", effect.get('shield_breakage_trigger') or
                 f"{subject.display_name}'s Shield would break"):
        return None
    return False


@hook("event")
def catch_a_lost_shield(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Disarm / Open Hand / Drop path: a newly applied condition carrying the Shield's inventory key."""
    if event_type != "CONDITION_APPLIED":
        return
    instance = str((kwargs.get("payload") or {}).get("instance_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or owning(engine, actor) is None:
            continue
        condition = actor.conditions.get(instance)
        key = shield_key(engine, actor)
        if condition is None or key is None or str((condition.data or {}).get("item_key") or "") != key:
            continue
        if not ((condition.data or {}).get("held_by") or (condition.data or {}).get("dropped_at")):
            continue
        offer(engine, actor, "the Shield being taken out of your hands",
              f"{actor.display_name}'s Shield is leaving their hands", choices=("catch", "intact", "cracked"))
