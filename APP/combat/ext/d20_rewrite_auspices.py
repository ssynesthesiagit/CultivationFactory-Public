"""Fate's Auspices that rewrite a d20 (automation lane H1, 2026-09-29): Harmonizing Cup Auspice and Empty Road Auspice, on
combat/ext/d20_rewrite.py. (Complete Mandala Auspice's floor is combat/ext/d20_floor.py.)

Owner text (authority/typed_mechanics/rules_text.json; Tianxia Sphere Compendium, Fate, Auspices):
  * Auspices: "If the Auspice is active on a willing creature, that creature can end it as a Reaction to gain the Release effect. If the
    creature is Incapacitated, it can release an Auspice only if the talent explicitly permits it." Cast on one willing creature by touch,
    Concentration up to 1 hour.
  * Harmonizing Cup Auspice (CL 5, 2 CP): "When the target rolls a natural 1 on an attack roll, ability check, or saving throw, it may
    reroll the d20. It must use the new result. This reroll can occur only once per round. Release: The target releases this Auspice
    after a creature within 30 feet makes an attack roll, ability check, or saving throw. That creature rerolls the d20 and must use the
    new result."
  * Empty Road Auspice (1 CP): "The target has Disadvantage on saving throws, but gains a +5 bonus to saving throws. Release: When the
    target fails a saving throw, it releases this Auspice to reroll the saving throw without the Disadvantage or +5 bonus from this
    Auspice. It must use the new roll."

Effect type "d20_auspice" (an ability's typed effect): {"type": "d20_auspice", "auspice": "harmonizing_cup" | "empty_road", "applies_to":
"target", "duration": "concentration"}. It puts ``condition:typed.d20_auspice`` on the subject, lasting as any typed effect does (it ends
with the caster's Concentration), and the two Release rules read it. Releasing ends the Auspice (the caster's Concentration on it and the
condition), as Complete Mandala's Release does.

How each runs.
  * Harmonizing Cup: the bearer's own natural 1 is rerolled at once (no cost, once a round; a player is asked). The Release is the bearer's
    Reaction: a creature within 30 feet has rolled a d20 that is bad for the bearer's side (an ally's failure, a foe's success), and the
    bearer ends the Auspice to make it roll again.
  * Empty Road: the +5 and the Disadvantage are added to the bearer's typed saving throws (the ``save`` hook; an engine save that is not
    a typed effect -- concentration, a zone -- has neither, and its Release rerolls a plain roll). The Release rerolls a failed save as a
    single die and takes the +5 back, which for a typed save is the R6 outcome override.

Judgment calls: "within 30 feet" is measured from the bearer to the roller (the bearer's own rolls count); the Release is offered only
against a roll the reroll can help, so a player is not asked about every d20 near the bearer; Complete Mandala Auspice's Release is not
touched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .d20_rewrite import Holder, Rule, RollCtx, condition_holders, register, save_extras
from .d20_rewrite_fate import good_for_us
from .d20_rewrite_rules import rider  # noqa: F401

CONDITION = "condition:typed.d20_auspice"
AUSPICES = {"harmonizing_cup": "Harmonizing Cup Auspice", "empty_road": "Empty Road Auspice"}


def _rule(condition: Any) -> str:
    from ..typed_executor import is_active_typed_condition

    if not is_active_typed_condition(condition):
        return ""
    return str(((condition.data or {}).get("rule") or {}).get("d20_auspice", {}).get("auspice") or "")


def _reading(auspice: str) -> str:
    if auspice == "harmonizing_cup":
        return ("When it rolls a natural 1 on an attack roll, ability check or saving throw it may reroll the d20 (once a round). Release "
                "(a Reaction, ending the Auspice): after a creature within 30 feet rolls a d20, that creature rerolls it.")
    return ("Disadvantage on saving throws, but +5 to them. Release (a Reaction, ending the Auspice): when it fails a saving throw it rerolls it "
            "without the Disadvantage or the +5.")


@effect("d20_auspice")
def grant(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    auspice = str(eff.get("auspice") or "")
    if auspice not in AUSPICES:
        return
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is None or not subject.active:
            continue
        for iid, condition in list(subject.conditions.items()):  # a second Auspice of the kind replaces the first
            if condition.condition_id == CONDITION and condition.source_definition_id == ctx.source and condition.source_actor_id == ctx.actor.entity_id:
                ctx.engine._remove_condition(subject, condition.condition_id, ctx.source)
        ctx.engine._apply_condition(
            subject, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
            data={"rule": {"d20_auspice": {"auspice": auspice}}, "label": AUSPICES[auspice], "reading": _reading(auspice)})
        note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} lays {AUSPICES[auspice]} on {subject.display_name}.", (subject,))


def bearing(auspice: str):
    base = condition_holders(CONDITION)

    def find(engine: Any) -> list[Holder]:
        return [holder for holder in base(engine)
                if _rule(engine.state.actors[holder.actor.entity_id].conditions[holder.key]) == auspice]
    return find


def _release(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    from .d20_floor import end_auspice

    condition = holder.actor.conditions.get(holder.key)
    if condition is not None:
        end_auspice(engine, holder.actor, condition, "RELEASED")


def _bad_for_bearer(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    return good_for_us(holder, rc, rc.natural) is False


register(Rule("harmonizing_cup_nat1", "Harmonizing Cup Auspice", rolls=("attack", "save", "check"), when="nat1", limit="round", finder=bearing("harmonizing_cup")))
register(Rule("harmonizing_cup_release", "Harmonizing Cup Auspice (Release)", rolls=("attack", "save", "check"), who="any", range_ft=30, when="any", reaction=True,
              checkpoint="D20_REROLL_ALLY", priority=60, finder=bearing("harmonizing_cup"), guard=_bad_for_bearer, ai=lambda engine, holder, rc: True, after=_release))


@hook("save")
def empty_road_static(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """The +5 and the Disadvantage of Empty Road on the bearer's typed saving throws."""
    if not any(_rule(c) == "empty_road" for c in subject.conditions.values() if c.condition_id == CONDITION):
        return None
    save_extras(ctx.engine)["empty_road"] = 5
    return {"bonus": 5, "modes": ["DISADVANTAGE"]}


register(Rule("empty_road_release", "Empty Road Auspice (Release)", rolls=("save",), reaction=True, op="normal", priority=60, finder=bearing("empty_road"),
              drop_modifier=lambda engine, holder, rc: int(save_extras(engine).get("empty_road") or 0), after=_release))
