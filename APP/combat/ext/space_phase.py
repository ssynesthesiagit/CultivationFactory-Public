"""Phase Step's partial step outside ordinary space (AUTO23 Space sphere lane, 2026-10-04; AUTO23f1 fixes).

Owner text (authority/typed_mechanics/rules_text.json, tianxia.talent.space.phase_step):
"You partially step outside ordinary space. Until the end of your turn:
 - you may move through creatures and objects as Difficult Terrain;
 - you ignore Opportunity Attacks;
 - you gain Resistance to Bludgeoning, Piercing and Slashing damage;
 - you cannot be Grappled or Restrained by ordinary physical means."

What this module resolves, and how:
* "you ignore Opportunity Attacks" -- the ``opportunity_allowed`` query is asked for every creature
  that would make one; a phased creature moving inside them gets no opportunity attack until the end
  of its own turn.
* "you cannot be Grappled or Restrained by ordinary physical means" -- the ``condition_attempt``
  query refuses those two conditions while the state lasts, and only when an *ordinary physical
  hold* is what is putting them on.  That is the shared source-qualified reader
  ``combat/ext/physical_holds.ordinary``: the ordinary Grapple (the compiler's own unarmed option,
  arm's length) and any reviewed row that declares ``hold_kind: ordinary_physical`` from its printed
  words -- a thrown net or rope, say.  AUTO23r1f1: the first version read "ordinary physical means" as
  "a confirmed hit", which was wrong twice over.  An ordinary Grapple is a Strength-or-Dexterity
  *save* whose condition sits in the failure branch, so it never has a confirmed hit and got through
  the immunity; and a hit says nothing about magic, so a magical grapple that landed would have been
  refused.  A spell, a zone, a conjured hand or a magical grip is not an ordinary physical means and
  still takes hold (AUTO23f1 had already narrowed it from "every grapple whatever put it on").
  An existing grapple or restraint is not cancelled either: the printed words say "cannot be", not
  "is no longer".
* The Resistance row is ordinary typed data on the same record (combat/typed_executor.py block_resistance),
  so it needs nothing here.

A2SPACE uses the existing documented pass_through hook for creature passage.
Only a newly reviewed effect with creature_passage=true writes the integer
condition marker that enables this grant; old saved rows and conditions retain
their behavior and wording. Native passage owns observed occupancy, whole-body
transit, double movement cost, forbidden occupied endpoints and interruption.
Passing through solid objects, sealed boundaries and ending inside an object
still needs native boundary support and remains a lock-round item.

The state is one condition on the user until the end of the user's own turn (``END_OF_CURRENT_TURN``,
a name the engine removes), so a table commit and reload keep it and nothing lasts the rest of the
fight by accident.  Both hooks ask for that condition first and return None without it, so every
other creature, every other fight and every saved fight are untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

PHASE = "condition:typed.space_phase"
LABEL = ("Phase Step, until the end of this turn: no Opportunity Attack can be made against this creature, "
         "and it cannot be Grappled or Restrained by ordinary physical means -- an ordinary grapple with "
         "the hands, or a net or rope thrown around it. A spell, a conjured hand or any other magical hold "
         "still takes hold. It also has Resistance to bludgeoning, piercing and slashing damage.")
BLOCKED = ("grappled", "restrained")


def _phased(actor: Any) -> bool:
    return any(condition.condition_id == PHASE for condition in actor.conditions.values())


@hook("pass_through")
def phased_creature_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    """The printed creature portion; default-inert for legacy saved packets."""
    return "difficult" if any(c.condition_id == PHASE and c.data.get("creature_passage") == 1
                              for c in mover.conditions.values()) else None


def _ordinary_physical(ctx: Any, row: dict[str, Any]) -> bool:
    """"by ordinary physical means": what is doing the holding, read from the row that is trying.

    The shared classifier is ``combat/ext/physical_holds.ordinary`` (used by Abyssal Depthsfluid
    defenses, the Trap escape menu and the wrestling framework), because "which creature is being held
    by ordinary physical means" is one question with one answer: the compiler's own unarmed Grapple
    option (an Action at arm's length, a Strength-or-Dexterity save, Grappled in the failure branch) or
    a row that declares ``hold_kind: ordinary_physical`` from its printed authority.  It answers
    ``False`` for a spell, a zone, a conjured hand and any other magical grip, which is what the
    printed line means by "ordinary physical".
    """
    from .physical_holds import ordinary

    return ordinary(getattr(ctx, "typed", None) or {}, row or {})


@effect("space_phase")
def phase_step(ctx: Any, eff: dict[str, Any]) -> None:
    """Phase Step (Bonus Action, 3 CP): the printed state until the end of the user's turn."""
    engine, actor = ctx.engine, ctx.actor
    engine._remove_condition(actor, PHASE, ctx.source)
    data = {"label": LABEL}
    if eff.get("creature_passage"):
        data.update(creature_passage=1, label=LABEL +
                    " It may pass through visible creatures' spaces at double movement cost, "
                    "but must finish in an unoccupied space; solid objects still block movement.")
    engine._apply_condition(actor, PHASE, ctx.source, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data=data)
    from . import note

    note(engine, ctx.source, actor,
         f"{actor.display_name} steps partly outside ordinary space until the end of this turn: "
         f"no Opportunity Attack can be made against it, an ordinary grapple, net or rope cannot hold it, "
         f"and it has Resistance to bludgeoning, piercing and slashing damage.")


@hook("opportunity_allowed")
def phased_ignores_opportunity_attacks(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"you ignore Opportunity Attacks" (Phase Step): nobody may make one against a phased creature."""
    return False if _phased(mover) else None


@hook("condition_attempt")
def phased_cannot_be_held(ctx: Any, subject: Any, effect_row: dict[str, Any] | None) -> bool | None:
    """"you cannot be Grappled or Restrained by ordinary physical means" (Phase Step)."""
    row = effect_row or {}
    if subject is None or not _phased(subject):
        return None
    if str(row.get("condition") or "").lower() not in BLOCKED or not _ordinary_physical(ctx, row):
        return None
    ctx.rider(f"{subject.display_name} is partly outside ordinary space: an ordinary physical hold cannot "
              f"{'Grapple' if str(row.get('condition')).lower() == 'grappled' else 'Restrain'} it, so "
              f"{str(row.get('condition')).lower()} does not take hold.")
    return False
