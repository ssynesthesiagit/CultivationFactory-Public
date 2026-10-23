"""Qi-Tempered Concentration (Insights 7, 2026-10-13).

Owner's printed text (authority/typed_mechanics/rules_text.json,
``insight.qi-tempered-concentration``):

  "Reaction. Trigger: You fail a Constitution saving throw to maintain a
   Qi-powered feature. Cost: 2 Qi. Add your Proficiency Bonus to the saving
   throw, potentially turning failure into success. This is not saving throw
   proficiency and cannot modify the same saving throw more than once."

The Concentration save itself is the engine's own check
(``gate2_engine._concentration_check``, source ``system:combat.concentration``,
DC 10-30 from the damage). The Insight only adds its owner's Proficiency
Bonus to that saving throw, through the shared ``d20_bonus`` seam
(``combat/roll_checkpoints.py`` ``rewrite_d20``): the bonus is a signed
change to the effective total at the unlocked roll checkpoint, applied before
save-result events and outcome consumers. A failure the Bonus turns around
therefore succeeds in the record, and the Concentration is kept by the
ordinary save-success path -- no late outcome override, and the natural d20
is never redrawn (the printed text adds a modifier, not a reroll). Exactly
one subscriber's bonus lands on any one roll, so the same saving throw is
never modified twice by this Insight.

The Bonus is offered on the printed trigger -- a failed Constitution save
the creature is maintaining a Qi-powered feature through (a feature is
Qi-powered when the concentrating action's own costs draw from the Qi pool)
-- to the creature making the save, paying 2 Qi and the Reaction. A
computer-controlled seat prefers it when the Bonus turns the failure into
success, while every seat retains the legal expenditure; a player (or an Ask-me seat) decides from the prompt's roll
details, because the printed text only says "potentially".

Default-inert for every creature without the Insight's compiled
``d20_rewrite`` row (``feature_blocks.d/insights7.json``), and for every
save that is not a failed Constitution Concentration save, and for a
Concentration on a feature that costs no Qi.

Still unimplemented: the CL15 clause
improves "Independent Concentration" (it may then protect any maintained
cultivation feature, and its own success carries a choose-one follow-up: a
5-foot move, moving the Domain Armament 10 feet, or Temporary Hit Points
equal to the Proficiency Bonus). Independent Concentration is printed in
Nascent Soul; this provider implements only the Insight's 2-Qi reaction. The
Constitution/Intelligence/Charisma increase is character construction.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import ask, checkpoint_id
from .d20_rewrite import BLOCK, context_of

FEATURE = "insight.qi-tempered-concentration"
KIND = "qi_tempered_concentration"
CHOICE = "choice:needle.qi_tempered_concentration.maintain"
CHECKPOINT = "QI_TEMPERED_CONCENTRATION"
QI = "resource:core.qi"
CONCENTRATION = "system:combat.concentration"
COST = 2


@effect("qi_tempered_save_bonus", harmful=False)
def save_bonus_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Compile-time descriptor; the d20_bonus hook owns the benefit."""


def holder_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The creature's compiled ``d20_rewrite`` row of this Insight's kind, if any."""
    for store in ("typed_passive_rows", "typed_reaction_rows"):
        for row in (getattr(engine, store, None) or {}).get(actor.entity_id, ()):
            if not row.get("held_back") and row.get("block") == BLOCK and row.get("kind") == KIND:
                return row
    return None


def qi_powered_feature(engine: Any, actor: Any) -> str | None:
    """The display name of the feature ``actor`` is concentrating on, when its own
    costs draw from the Qi pool (the printed "Qi-powered feature")."""
    concentration = getattr(actor, "concentration", None)
    if concentration is None:
        return None
    action = (getattr(engine, "action_catalog", None) or {}).get(str(concentration.source_definition_id or ""))
    if action is None:
        return None
    costs = [(str(resource), amount) for resource, amount in (getattr(action, "costs", None) or ())]
    if not any(resource == QI for resource, _amount in costs):
        return None
    return str(getattr(action, "display_name", None) or concentration.source_definition_id)


@hook("d20_bonus")
def tempered_save(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Add the owner's Proficiency Bonus to a failed Constitution Concentration
    save on a Qi-powered feature (2 Qi, the Reaction)."""
    if roll.natural_result is None:
        return None
    rc = context_of(engine, roll)
    if rc is None or rc.kind != "save" or rc.ability != "CON" or rc.source_id != CONCENTRATION:
        return None
    actor = rc.roller
    row = holder_row(engine, actor)
    if row is None:
        return None
    feature_name = qi_powered_feature(engine, actor)
    if feature_name is None or rc.succeeded() or rc.dc is None:
        return None  # the save already stands; the printed trigger is a failure
    from .. import typed_reactions

    if not typed_reactions._can_react(engine, actor, row):
        return None
    if actor.resources.get(QI, 0) < COST:
        return None
    pb = int(row.get("pb", actor.proficiency_bonus or 2))
    # "Potentially turning failure into success": a computer-controlled seat
    # prefers to spend only when the Bonus actually turns this save around.
    # Eligibility stays separate: every controller still receives "maintain".
    bonus_total = int(rc.total) + pb
    turns_it = bonus_total >= int(rc.dc)
    outcome = ("This will turn the failure into success." if turns_it
               else "This save will still fail.")
    checkpoint = checkpoint_id(engine, CHECKPOINT, actor.entity_id)
    chosen = ask(engine, intent, checkpoint, actor, CHOICE, ["maintain"],
                 labels={"maintain": f"Add your Proficiency Bonus (+{pb}) to this save"},
                 allow_decline=True, default="decline", automatic=turns_it,
                 target_id=actor.entity_id, name="Qi-Tempered Concentration", feature_id=FEATURE,
                 prompt=(f"Qi-Tempered Concentration (your Reaction, 2 Qi): {actor.display_name} failed the "
                         f"Constitution save to maintain {feature_name} -- rolled {rc.total} against DC {rc.dc}. "
                         f"Add your Proficiency Bonus (+{pb}) for a total of {bonus_total}? {outcome}"))
    if not chosen or chosen[0] != "maintain":
        return None
    from ..paid_relocation import activation

    with activation(engine, actor, FEATURE):
        engine._spend_resource(actor, QI, COST, FEATURE)
        typed_reactions.open_reaction(engine, row, actor, (actor.entity_id,), checkpoint)
        note(engine, FEATURE, actor,
             f"Qi-Tempered Concentration: {actor.display_name} adds their Proficiency Bonus (+{pb}) to the "
             f"Constitution save to maintain {feature_name} (rolled {rc.total} against DC {rc.dc}, now "
             f"{int(rc.total) + pb}).", (actor,))
    return {"source_id": FEATURE, "bonus": pb}
