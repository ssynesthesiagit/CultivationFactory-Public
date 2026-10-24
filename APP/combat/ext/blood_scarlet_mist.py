"""Scarlet Mist Form's two movement clauses (the Blood sphere's mist body).

Scarlet Mist Form (CL 10, Bonus Action, Concentration up to 1 minute, 6 CP) prints, under
"Transform partially into blood mist. Gain:":

  Fly Speed 30 feet and Hover                            (typed data)
  Resistance to nonmagical Bludgeoning, Piercing, Slashing (typed data)
  ability to move through occupied spaces as difficult terrain
  ability to pass through openings as narrow as 1 inch
  Advantage on checks to escape Grappled or Restrained    (typed data)
  ability to apply Blood Thread automatically to one creature whose space you move through,
  once per turn

The two movement clauses were GM lines. Both are the engine's own creature-passage seam
(combat/ext/__init__.py "Creature passage", combat/creature_passage.py), so nothing new was
added to the movement core:

  pass_through(engine, mover, occupant) -> 'difficult'   occupied spaces cost double movement,
                                                         never free, never a blocked-space bypass
  pass_through_entered(engine, mover, occupant, intent)  a transactional notice after first
                                                         entering a creature footprint

The Thread is the Blood Thread mark, placed through the ordinary typed ``mark`` row, so
Coagulate, Blood Mending, Bloodletting Strike, Crimson Mark's own extension offer and every
other reader of ``mark_condition_id("Blood Thread", owner)`` see a real Thread. Scarlet Mist
Form prints "automatically" and prints no saving throw, so the Thread it applies needs none
(the unwilling branch's save belongs to Blood Thread's own attack, which this line replaces).
The paid hour Crimson Mark offers on top of it is a separate printed line of that talent, and
it asks the crossed creature whether it will bear that longer Thread -- combat/ext/blood_riders.py
thread_bearer_agrees is that question, not this plug-in, so an ally is free to refuse it and an
enemy is free to accept it. The announcement below reads the mark back after the extension has
answered, so it never tells a player their new Thread ends at the start of their next turn when
it actually lasts an hour.

"one creature ... once per turn" is the user's decision, not the engine's. The printed line is
unlimited as to whom: any creature the user moves through counts, ally or enemy, and the table
asks whether to spend the turn's use on the creature just crossed. Declining keeps the use for a
later creature the same turn; taking it applies the Thread through the ordinary mark row, which
also refreshes a creature that already bears one (and keeps a Crimson Mark hour, see blood_riders.
preserve_extended_thread). The AI takes the printed automatic application, so an AI Blood
cultivator threads the first creature it crosses. The use itself is the shared per-turn clock
(combat/turn_uses.py), so it is available again at the start of the next creature's turn -- the
printed "once per turn" says nothing about whose turn it is.

Not automated, and left as the printed GM's call (they stay GM text in the fight):
  "ability to pass through openings as narrow as 1 inch" -- this table's map has no gap,
    door or squeeze rule to satisfy; combat/creature_passage.py refuses to let any grant
    cross a wall, which is what the printed "You cannot pass through sealed barriers or
    solid objects" already means.
  "Transform partially into blood mist" -- flavour, and the printed appearance question.

Inert for anyone without the talent: every hook answers None unless the mover holds the
marker, and the marker exists only because the talent's own typed row placed it.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

MIST = "condition:typed.scarlet_mist_form"
THREAD = "Blood Thread"
SPHERE = "tianxia.sphere.blood"
# The printed "once per turn", on the shared all-creature clock (combat/turn_uses.py): it clears
# at the start of every creature's turn, so a move made between turns can still use it.
USE = "typed_once_turn:scarlet_mist_form:blood_thread"
EVIDENCE = ("ability to apply Blood Thread automatically to one creature whose space you move through, "
            "once per turn")


@effect("mist_form")
def mist_form(ctx: Any, eff: dict[str, Any]) -> None:
    """"Transform partially into blood mist": the timed marker the two passage hooks below answer for.

    It lasts as the ability lasts (Concentration, up to 1 minute), so it ends with the form.
    """
    from ..typed_executor import effect_expiry

    ctx.engine._apply_condition(ctx.actor, MIST, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, eff, ctx.actor, condition=True),
                                data={"label": "Scarlet Mist Form: you move through creatures' spaces as difficult terrain "
                                               "(twice the movement), and once per turn you can apply your Blood Thread to "
                                               "one creature whose space you move through."})


def _mist(mover: Any) -> dict[str, Any] | None:
    return next((condition for condition in mover.conditions.values() if condition.condition_id == MIST), None)


@hook("pass_through")
def mist_pass_through(engine: Any, mover: Any, occupant: Any) -> str | None:
    """"ability to move through occupied spaces as difficult terrain"."""
    return "difficult" if _mist(mover) is not None else None


@hook("pass_through_entered")
def mist_thread_crossing(engine: Any, mover: Any, occupant: Any, intent: Any) -> None:
    """"ability to apply Blood Thread automatically to one creature whose space you move through,
    once per turn" -- asked of the player, taken automatically by the AI, spent only on the
    application the user chose. Any creature counts, ally or enemy."""
    condition = _mist(mover)
    if condition is None or not mover.active or not occupant.active or occupant.entity_id == mover.entity_id:
        return
    if mover.turn_flags.get(USE):
        return
    action = engine.action_catalog.get(condition.source_definition_id)
    if action is None:
        return
    from ..typed_executor import Context, run_effects
    from . import needle

    source = condition.source_definition_id
    choice = needle.CHOICE + "scarlet_mist_thread"
    checkpoint = needle.checkpoint_id(engine, "SCARLET_MIST_THREAD", mover.entity_id, occupant.entity_id)
    picked = needle.ask(engine, intent, checkpoint, mover, choice, ["thread", "keep"],
                        labels={"thread": f"Apply your Blood Thread to {occupant.display_name} "
                                          f"(free; it lasts until the start of your next turn)",
                                "keep": f"Do not thread {occupant.display_name}; keep this turn's use for a later creature"},
                        prompt=f"Scarlet Mist Form: {mover.display_name} is blood mist and moves through "
                               f"{occupant.display_name}'s space. Once per turn you may apply your Blood Thread to a "
                               f"creature you move through. Apply your Blood Thread to {occupant.display_name} now?",
                        preferred=["thread"], allow_decline=True, automatic=True, default="first",
                        name="Scarlet Mist Form", feature_id=source, target_id=occupant.entity_id)
    if not picked or picked[0] != "thread":
        # Only a player who was asked and said no gets a line: a fight nobody answers applied the printed
        # automatic Thread, which is not a decision worth reading about.
        if needle.answered(engine, checkpoint, mover, choice):
            needle.say(engine, source, mover,
                       f"Scarlet Mist Form: {mover.display_name} moves through {occupant.display_name}'s space without "
                       f"applying your Blood Thread, so this turn's use is still available.",
                       target_ids=(occupant.entity_id,))
        return
    mover.turn_flags[USE] = True
    typed = (action.parameters or {}).get("typed") or {}
    rows = [{"type": "mark", "mark": THREAD, "applies_to": "target",
             "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": EVIDENCE}]
    run_effects(Context(engine, mover, action, intent, {**typed, "source": source}, [occupant], occupant, {}),
                rows)
    needle.say(engine, source, mover,
               f"Scarlet Mist Form: {mover.display_name} passes through {occupant.display_name}, who now bears "
               f"{mover.display_name}'s Blood Thread{_deadline(engine, mover, occupant)}.",
               target_ids=(occupant.entity_id,))


def _deadline(engine: Any, mover: Any, occupant: Any) -> str:
    """What the Thread this crossing just applied actually lasts, in words, or nothing at all.

    The mark row may hand the creature straight to Crimson Mark's paid hour (combat/ext/blood_riders.py
    crimson_mark_extension runs from the same ``mark`` row), and a retained hour keeps its own later
    deadline, so the ordinary Thread's printed end is not always what the creature now carries. This
    announcement is the last word on the crossing, so it reads the stored mark back through the
    table's shared expiry vocabulary (combat/history_text.py) instead of quoting the mist row's own
    duration. A deadline this vocabulary cannot read is left out rather than guessed at.
    """
    from ..history_text import expiry_text
    from .blood_riders import thread_mark

    mark = next((condition for condition in occupant.conditions.values()
                 if condition.condition_id == thread_mark(mover)), None)
    if mark is None:
        return ""
    deadline = expiry_text(mark.expires_on, {actor.entity_id: actor.display_name for actor in engine.state.actors.values()},
                           mover.display_name, occupant.display_name)
    return f" {deadline}" if deadline else ""
