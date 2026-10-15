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
is never redrawn (the printed text adds a modifier, not a reroll). This
provider contributes once per roll, so the same saving throw is never
modified twice by this Insight.

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

Independent Concentration uses the same native bonus checkpoint, with its own
1-Qi cost, Reaction and once-per-round receipt. At CL15 the owned Insight expands
that reaction to maintained cultivation features and supplies exactly one benefit
after its accepted bonus turns failure into success. d20_finalized correlates
that benefit by roll ID; native movement and public Armament helpers own geometry.
The Constitution/Intelligence/Charisma increase is character construction.
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
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"
INDEPENDENT = "independent_concentration"
INDEPENDENT_CHOICE = "choice:needle.independent_concentration"
BENEFIT_CHOICE = "choice:needle.qi_tempered_benefit"
MOVE_CHOICE = "choice:needle.qi_tempered_move"
ARMAMENT_CHOICE = "choice:needle.qi_tempered_armament"
USED = "independent_concentration_round_used"


@hook("compile_passives")
def independent_row(passives, info):
    # Keep the native save_rescue descriptor in the reaction plan, with no
    # abilities to deliver a second bonus. This marker is the sole resolver.
    if NASCENT not in info["owned_ids"]:
        return None
    return [*passives, {"feature_id": NASCENT, "block": INDEPENDENT, "kind": INDEPENDENT,
        "pb": int(info["numbers"]["pb"]), "cl": int(info["numbers"]["cl"]),
        "player_outcome": "Independent Concentration: Reaction and 1 Qi to add your Proficiency Bonus to a failed Constitution save maintaining a Qi feature, once per round."}]


def maintained_action(engine, actor):
    """The actual maintained source action; absent provenance grants nothing."""
    held = getattr(actor, "concentration", None)
    return engine.action_catalog.get(str(held.source_definition_id or "")) if held else None


def cultivation_feature(action):
    """Explicit Path/Sphere provenance, rather than guessing from display text."""
    typed = (action.parameters or {}).get("typed") or {}
    return bool(typed.get("sphere") or str(typed.get("source") or action.source_definition_id).startswith(
        ("tianxia.path.", "tianxia.talent.", "TAL_")))


@hook("d20_bonus")
def independent_save(engine, roll, intent):
    from .passive_rows import row_of
    from .. import typed_reactions
    from ..paid_relocation import activation
    rc = context_of(engine, roll)
    if (roll.natural_result is None or rc is None or rc.kind != "save" or rc.ability != "CON"
            or rc.source_id != CONCENTRATION or rc.succeeded() or rc.dc is None):
        return None
    actor = rc.roller
    row = row_of(engine, actor.entity_id, INDEPENDENT, INDEPENDENT)
    plan_row = next((r for r in engine.typed_reaction_rows.get(actor.entity_id, ()) if r.get("feature_id") == NASCENT), None)
    action = maintained_action(engine, actor)
    improved = row is not None and int(row["cl"]) >= 15 and holder_row(engine, actor) is not None
    if (row is None or plan_row is None or plan_row.get("held_back") or action is None or not (qi_powered_feature(engine, actor)
            or (improved and cultivation_feature(action))) or actor.resources.get(QI, 0) < 1
            or actor.turn_flags.get(USED) == engine.state.round_number
            or not typed_reactions._can_react(engine, actor, plan_row)):
        return None
    pb = int(row["pb"])
    checkpoint = checkpoint_id(engine, "INDEPENDENT_CONCENTRATION", roll.roll_id)
    picked = ask(engine, intent, checkpoint, actor, INDEPENDENT_CHOICE, ["maintain"],
        labels={"maintain": f"Add your Proficiency Bonus (+{pb}) to this save"},
        allow_decline=True, default="decline", automatic=int(rc.total) + pb >= rc.dc,
        target_id=actor.entity_id, name="Independent Concentration", feature_id=NASCENT,
        prompt=f"Independent Concentration: {actor.display_name} failed the Constitution save to maintain "
               f"{action.display_name} (total {rc.total}, DC {rc.dc}). Spend your Reaction and 1 Qi to add "
               f"your Proficiency Bonus (+{pb})? Once per round."
               + (" Qi-Tempered Concentration grants one free benefit if this turns failure into success." if improved else ""))
    if not picked:
        return None
    with activation(engine, actor, NASCENT):
        engine._spend_resource(actor, QI, 1, NASCENT)
        typed_reactions.open_reaction(engine, plan_row, actor, (actor.entity_id,), checkpoint)
        actor.turn_flags[USED] = int(engine.state.round_number)
        note(engine, NASCENT, actor,
             f"Independent Concentration: {actor.display_name} adds +{pb} to the Constitution save for {action.display_name}.",
             accepted_roll_id=roll.roll_id, improved=int(improved), prior_total=int(rc.total), pb=pb, dc=int(rc.dc))
    return {"source_id": NASCENT, "bonus": pb}


@hook("d20_finalized")
def independent_benefit(engine, roll, intent):
    accepted = next((e for e in reversed(engine.events) if e.event_type == "PASSIVE_TRIGGERED"
        and e.source_definition_id == NASCENT and e.payload.get("accepted_roll_id") == roll.roll_id), None)
    if (accepted is None or not accepted.payload.get("improved")
            or int(accepted.payload["prior_total"]) + int(accepted.payload["pb"]) < int(accepted.payload["dc"])):
        return
    rc = context_of(engine, roll)
    if rc is None or not rc.succeeded() or any(e.source_definition_id == FEATURE
            and e.payload.get("benefit_roll_id") == roll.roll_id for e in engine.events):
        return
    from .granted_movement import choices, move
    from .qi_path import armament_destinations, move_armament
    actor, pb = rc.roller, int(accepted.payload["pb"])
    moves = {c.candidate_id: c for c in choices(engine, actor, 5)}
    arms = armament_destinations(engine, actor, 10)
    options = ["temporary_hp"] + (["move"] if moves else []) + (["armament"] if arms else [])
    chosen = ask(engine, intent, checkpoint_id(engine, "QI_TEMPERED_BENEFIT", roll.roll_id), actor,
        BENEFIT_CHOICE, options, allow_decline=False, preferred=["temporary_hp"],
        labels={"temporary_hp": f"Gain {pb} Temporary Hit Points", "move": "Move up to 5 feet without Opportunity Attacks",
                "armament": "Move your Domain Armament up to 10 feet"},
        name="Qi-Tempered Concentration", feature_id=FEATURE,
        prompt=f"Qi-Tempered Concentration: Independent Concentration kept {actor.display_name}'s "
               f"{maintained_action(engine, actor).display_name}. Choose one benefit for yourself; no extra action or Qi cost.")
    if chosen[0] == "temporary_hp":
        engine._grant_temp_hp(actor, pb, FEATURE, actor.entity_id)
    elif chosen[0] == "move":
        picked = ask(engine, intent, checkpoint_id(engine, "QI_TEMPERED_MOVE", roll.roll_id), actor, MOVE_CHOICE,
            list(moves), allow_decline=False,
            labels={key: f"{c.metadata.get('movement_mode', 'walk').replace('_', ' ').capitalize()} to ({c.destination.x}, {c.destination.y}), {c.destination.z * 5} feet high"
                    for key, c in moves.items()},
            prompt=f"Qi-Tempered Concentration: choose {actor.display_name}'s legal 5-foot move; no Opportunity Attacks or extra cost.")
        c = moves[picked[0]]
        move(engine, actor, c, intent, 5, [], name="Qi-Tempered Concentration", nonprovoking=True)
    else:
        choices = {f"cell:{p.x},{p.y}": p for p in arms}
        picked = ask(engine, intent, checkpoint_id(engine, "QI_TEMPERED_ARMAMENT", roll.roll_id), actor, ARMAMENT_CHOICE,
            list(choices), allow_decline=False, labels={key: f"Move Armament to ({p.x}, {p.y})" for key, p in choices.items()},
            prompt=f"Qi-Tempered Concentration: choose {actor.display_name}'s Domain Armament point, up to 10 feet away; no extra cost.")
        if not move_armament(engine, actor, choices[picked[0]], FEATURE, distance_ft=10, require_clear_route=True):
            note(engine, FEATURE, actor, "Qi-Tempered Concentration: your Domain Armament could not reach the selected point.")
    note(engine, FEATURE, actor, f"Qi-Tempered Concentration: {actor.display_name} receives the selected free benefit.",
         benefit_roll_id=roll.roll_id, benefit=chosen[0])


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
