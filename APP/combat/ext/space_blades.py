"""Space Between Blades' printed "Then choose one" (AUTO23 Space sphere lane, 2026-10-04; AUTO23f1 fixes).

Owner text (authority/typed_mechanics/rules_text.json, tianxia.talent.space.space_between_blades):
"Reaction. Trigger: A creature misses you with a melee attack. Cost: 1 CP.
Teleport 5 feet to an unoccupied space you can see. Then choose one:
 - You may move 5 additional feet without provoking Opportunity Attacks from the attacker.
 - The attacker cannot make Opportunity Attacks against you until the start of your next turn.
 - The next melee attack you make against the attacker before the end of your next turn deals additional
   Force damage equal to your Proficiency Bonus."

The printed menu is three separate choices and it is *asked*, not pre-picked: the record carries it as
one ``choose_effects`` row (combat/ext/effect_choices.py, the shared post-resolution menu), so a player
is asked on their own turn and on an AI turn alike, an AI answers for itself, and an unanswered table
takes the printed default.  AUTO23 built this as three compiler options, which meant the table chose one
option *before* the fight (reaction plan) and the other two were unreachable at runtime.

What each choice does here:
* "move 5 additional feet without provoking Opportunity Attacks from the attacker" -- the shared
  ``rider_step`` effect (combat/ext/rider_step.py), which moves the creature at once through native
  granted movement and exempts the *target* of the row, which is the creature that just missed it.
  That is exactly "from the attacker": it is the same exemption Hammer Rebuke's "against you" uses.
  The row asks for the square, names the ability, the creature it answered and the creature affected.
* "The attacker cannot make Opportunity Attacks against you until the start of your next turn" --
  ``space_blades_no_oa`` puts on the engine's own ``no_opportunity_attacks`` rule with ``against`` set
  to this creature, so the attacker loses its Opportunity Attacks against this creature and against
  nobody else (the printed words limit it to "against you").  The turn limit is the start of the
  Space character's own next turn.  AUTO23 typed this as ``reaction_denied``, which took away *every*
  Reaction the attacker had.
* "The next melee attack you make against the attacker before the end of your next turn deals additional
  Force damage equal to your Proficiency Bonus" -- ``space_blades_bonus`` records one condition on the
  reactor naming the creature the bonus is bound to, and the ``attack_result`` hook spends it: the next
  melee attack that reactor makes against that creature spends it, and a landed one delivers Proficiency
  Bonus Force damage.  AUTO23r1f1: the hook used to be ``damage_dealt``, which only fires for a positive
  damage packet, so a miss or a hit whose ordinary damage was fully prevented left the bonus armed for a
  later attack and the printed Force damage never arrived.  The printed line says "the next melee attack
  you make against the attacker", not "the next attack that damages it", so the qualifying *attack* is
  what is tracked and the Force packet is delivered on its hit even when the ordinary one deals zero.
  The condition ends with the end of the reactor's own *next* turn, not this one: the engine's own
  ``END_OF_HOLDER_NEXT_TURN`` ends at whichever turn the holder is next on, which is this turn when the
  reactor is the one moving and the bonus was armed by an Opportunity Attack that missed it.  The printed
  words give the counter-qualified name (``END_OF_SOURCE_TURN_AT:<its next turn>``) instead.  Only
  strings and an integer go into the saved fight (the bound creature id, the bonus, the pill text), so a
  table commit and reload keep it and replay it.

AUTO23 typed the third choice as a deferred ``extra_damage`` row, which registered nothing at all: the
engine's later-hit reader looks the printed row up by the ability's catalog id, and a generic Reaction
has no catalog entry, so the bonus never reached a fight.

Inert without Space Between Blades: both effects only exist inside a choice of this record, and the
``damage_dealt`` handler answers only for a creature that is carrying this bonus condition.  Every
other fight, character and saved fight is untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

BONUS = "condition:typed.space_blades_bonus"
NO_OPPORTUNITY = "condition:typed.no_opportunity_attacks"
#: "until the start of your next turn": the start of the reactor's own next turn (it is the applier).
UNTIL_THEIR_NEXT_TURN = "START_OF_SOURCE_NEXT_TURN"
#: "before the end of your next turn" is read from the printed words below; the name it produces names the
#: reactor's own next turn by its turn counter, whatever turn armed the bonus (see next_melee_bonus).
BONUS_EVIDENCE = ("The next melee attack you make against the attacker before the end of your next turn deals additional "
                  "Force damage equal to your Proficiency Bonus.")


def _armed(actor: Any, target: Any) -> Any | None:
    """The reactor's one pending bonus, when this creature is the one it is bound to."""
    if target is None:
        return None
    for condition in actor.conditions.values():
        if condition.condition_id == BONUS and (condition.data or {}).get("against") == target.entity_id:
            return condition
    return None


@effect("space_blades_no_oa")
def no_opportunity_attacks_against_me(ctx: Any, row: dict[str, Any]) -> None:
    """"The attacker cannot make Opportunity Attacks against you until the start of your next turn"."""
    from ..typed_executor import stated_expiry

    attacker = ctx.target
    if attacker is None or attacker is ctx.actor or not attacker.active:
        return
    label = (f"{ctx.actor.display_name} dodged this attack and slipped 5 feet away: it cannot make an "
             f"Opportunity Attack against {ctx.actor.display_name} until the start of its next turn.")
    expires = stated_expiry(ctx, {"expires_on": UNTIL_THEIR_NEXT_TURN}, attacker, condition=True)
    ctx.engine._apply_condition(attacker, NO_OPPORTUNITY, ctx.source, ctx.actor.entity_id,
                                expires_on=expires, data={"against": ctx.actor.entity_id, "label": label})
    note(ctx.engine, ctx.source, attacker, label, (ctx.actor,))


@effect("space_blades_bonus")
def next_melee_bonus(ctx: Any, row: dict[str, Any]) -> None:
    """"The next melee attack you make against the attacker ... deals additional Force damage"."""
    from ..typed_executor import stated_expiry

    engine, reactor, attacker = ctx.engine, ctx.actor, ctx.target
    if attacker is None or attacker is reactor or not attacker.active:
        return
    amount = int(ctx.formula("pb"))
    engine._remove_condition(reactor, BONUS, ctx.source)  # choosing it again replaces the one it had
    # "before the end of your next turn", read from the printed words by the shared reader: it names the
    # end of the reactor's own next turn by its turn counter. The engine's own END_OF_HOLDER_NEXT_TURN would
    # end with whichever turn the holder is next on -- this one, when a missed Opportunity Attack armed the
    # bonus during the reactor's own movement -- so that name is not the printed deadline.
    expires = stated_expiry(ctx, {"evidence": BONUS_EVIDENCE}, reactor, condition=True)
    engine._apply_condition(reactor, BONUS, ctx.source, reactor.entity_id, expires_on=expires,
                            data={"against": attacker.entity_id,
                                  "label": (f"Space Between Blades: {reactor.display_name}'s next melee attack on "
                                            f"{attacker.display_name}, before the end of {reactor.display_name}'s "
                                            f"next turn, deals {amount} extra Force damage even if the attack's own "
                                            f"damage is stopped. That attack uses the bonus up whether or not it "
                                            f"lands, and the bonus never lasts past the end of "
                                            f"{reactor.display_name}'s next turn.")})
    note(engine, ctx.source, reactor,
         f"Space Between Blades: {reactor.display_name}'s next melee attack on {attacker.display_name}, before the "
         f"end of {reactor.display_name}'s next turn, deals {amount} extra Force damage, and uses the bonus up "
         f"whether or not it lands.")


@hook("attack_result")
def bonus_force_damage(ctx: Any, subject: Any, hit: bool, critical: bool) -> None:
    """Spend the printed bonus on the next melee attack the reactor makes against the creature it is bound to.

    ``attack_result`` is the one settled-attack notification that fires for a hit, a miss and a hit whose
    ordinary damage was fully prevented, so the printed "the next melee attack you make against the attacker"
    is tracked as the *attack*, not as a damage packet: it is spent by that attack, and a landed one
    delivers the Force damage whatever its ordinary packet did. It is transactional (a choice pause unwinds
    the attack), and a Factory fighter's Opportunity Attack resolves through the same typed attack path, so
    the printed "melee attack" needs no separate reaction reader.
    """
    from ..typed_executor import ranged_attack_now, run_effects

    condition = _armed(ctx.actor, subject)
    if condition is None or not subject.active or ranged_attack_now(ctx):
        return  # a different creature, a creature that is no longer there, or a ranged attack
    ctx.engine._remove_condition(ctx.actor, BONUS, ctx.source)  # spent first, so this attack cannot chain
    if not hit:
        note(ctx.engine, ctx.source, ctx.actor,
             f"Space Between Blades: {ctx.actor.display_name}'s attack on {subject.display_name} missed, so the "
             f"extra Force damage it had earned is used up.")
        return
    run_effects(ctx.on_hit_context(subject), [{"type": "extra_damage", "applies_to": "target", "formula": "pb",
                                               "damage_types": ["force"], "evidence": BONUS_EVIDENCE}])
