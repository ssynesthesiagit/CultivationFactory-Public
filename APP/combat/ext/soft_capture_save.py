"""Soft Capture: the creature the response catches chooses Strength or Dexterity for its save.

Rules text (…85Spheres.md:31712, record TAL_FLOWING_RIVER_SOFT_CAPTURE): "When your Flowing Response succeeds
against a creature within reach, the triggering creature makes a Strength or Dexterity saving throw, choosing
which, against your Cultivation Save DC." The who/reach/free-hand requirement, the Grappled consequence and the
"you may move 5 feet" step are native in combat/ext/flowing_river.py; what was missing was the chooser. The
reviewed rider save says "STR_OR_DEX" with no target_choice flag (authority/typed_mechanics/reviewed_final.d/
review_sw-fire.json), so combat/typed_executor.py answered it with the target's better ability -- the engine
deciding for the target, where the printed rule gives the decision to the target.

This plug-in puts that decision to the subject through the existing save_choice seam (documented in
combat/ext/__init__.py). That seam is opt-in per save row (save_choices answers rows with target_choice=True); a
rider has no compiled catalog row of its own, so this module opts in by context instead: Flowing River seals the
chosen Response talent on the executing effect context (typed["_rider_response_talent"], see _succeed) and this
module answers only for Soft Capture's own STR-or-DEX save against the subject. Every other save, every other
Flowing Response talent, and every fight whose character does not own Soft Capture are untouched. When nobody
answers (no choice transport, an old saved fight), it returns None and the executor's existing better-ability
selector stands unchanged, which is what those fights have always done.

Enrollment (choice_reactors) — and its cost: the triggering creature is whoever attacks and misses the Soft
Capture owner, so the potential chooser can be any participant. A fight in which some creature owns Soft Capture
therefore enrolls every participant, mirroring save_choices' shape for a smaller set of fights; a fight with no
Soft Capture owner enrolls nobody and stays inert. The cost in an enrolled fight is the service's ordinary ask-me
work: an AI-controlled actor's step is run once on a probe clone to find the prompts it reaches
(combat/gate5_service.py _ask_during_ai_step), and each enrolled participant is in the service's ask-me reactor
set (_ask_reactors), so their multi-mode reaction rows are offered as one option per mode and their prompts hold
the fight until answered. No stored state, no new field, no expiry token.
"""
from __future__ import annotations

from typing import Any

from . import hook

TALENT = "TAL_FLOWING_RIVER_SOFT_CAPTURE"
ABILITIES = {"STR": "Strength", "DEX": "Dexterity"}


def owns(engine: Any, actor_id: str) -> bool:
    """Whether this character owns Soft Capture (a "when: success" rider riding Flowing Response's row)."""
    rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(actor_id, []),
            *(getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])]
    return any(not row.get("held_back") and any(
        isinstance(effect, dict) and effect.get("type") == "on_success" and effect.get("talent") == TALENT
        for effect in row.get("effects") or []) for row in rows)


@hook("choice_reactors")
def potential_savers(engine: Any) -> tuple[str, ...]:
    """Every participant of a fight in which someone owns Soft Capture (cost in the module docstring)."""
    return tuple(engine.state.actors) if any(owns(engine, actor_id) for actor_id in engine.state.actors) else ()


def _failure_text(effect: dict[str, Any], responder: str) -> str:
    """The printed failed-save consequence, in plain player words, read from the row itself."""
    for row in effect.get("on_fail") or []:
        if isinstance(row, dict) and row.get("type") == "condition" and row.get("condition"):
            condition = str(row["condition"]).replace("_", " ")
            until = (f" until the start of {responder}'s next turn"
                     if row.get("duration") == "until_start_of_next_turn" else "")
            return f" A failed save leaves you {condition.capitalize()}{until}."
    return ""


@hook("save_choice")
def target_chooses_ability(ctx: Any, subject: Any, effect: dict[str, Any], options: list[str]) -> str | None:
    """Soft Capture's save belongs to the caught creature: it picks Strength or Dexterity, not the engine."""
    if (ctx.typed or {}).get("_rider_response_talent") != TALENT:
        return None
    if subject is not ctx.target or effect.get("applies_to") != "target" or len(options) < 2:
        return None
    from .needle import CHOICE, ask, checkpoint_id

    responder = ctx.actor.display_name
    preferred = max(options, key=lambda option: subject.saving_throws.get(option, 0))
    selected = ask(ctx.engine, ctx.intent,
                   checkpoint_id(ctx.engine, "soft_capture_save_choice", ctx.source, subject.entity_id),
                   subject, CHOICE + "save_choice", options, preferred=[preferred],
                   labels={option: f"{ABILITIES.get(option, option)} saving throw "
                                   f"({subject.saving_throws.get(option, 0):+d})" for option in options},
                   name="Soft Capture", feature_id=TALENT, target_id=subject.entity_id, default="decline",
                   prompt=f"Soft Capture: {responder}'s {ctx.action.display_name} caught {subject.display_name}. "
                          f"Choose Strength or Dexterity for the saving throw against your Cultivation Save DC; "
                          f"this choice costs no action or resource. "
                          + _failure_text(effect, responder))
    return selected[0] if selected else None
