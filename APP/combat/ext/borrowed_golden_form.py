"""Borrowed Golden Form (Tianxia Qi Cultivation Insight, CL16).

The recorded bloodline of the Golden Core is not the only one the cultivator
can touch: for one scene, 4 Qi buys the use of a Golden Core Form the
cultivator does not possess, in its unperfected state.

The insight compiles one free, hash-gated passive row (combat/ext/__init__.py
``compile_block`` seam) that carries ownership and the compiled numbers, and
one Bonus Action (4 Qi, once per scene). The action's effect asks which
unpossessed Form to borrow -- a player-owned decision on the player's turn;
an AI actor decides automatically -- and records the borrowed Form on the
shared Golden Core Form condition (combat/ext/qi_path.py ``FORM``) with the
Form's own Perfected state set false, so every Golden Core benefit reader
(combat/ext/qi_path.py ``form_state``) grants the unperfected amounts
until the scene ends. A borrowed Golden Core Reservoir therefore begins
unused and its once-per-scene use is spent like any other Reservoir; the
borrow ends only with the scene, so the shared ledger keeps its printed
meaning for the whole fight.

The plug-in is inert for every character that does not own this Insight:
the compile hooks return early unless the actor owns the row, and the
borrow effect refuses a Form the character already records (the printed
"you do not currently possess").
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .passive_rows import row_of
from .qi_path import FORMS, FORM, GOLDEN, forms

INSIGHT = "insight.borrowed-golden-form"
BLOCK = "borrowed_golden_form"
QI = "resource:core.qi"
SCENE_USED = "borrowed_golden_round_scene_used"  # once per scene: retained fight state


def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, BLOCK) is not None


@hook("compile_block")
def compile_borrowed(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": BLOCK, "numbers": dict(numbers)}]


@hook("compile_actions")
def borrowed_actions(info: dict[str, Any]) -> list[Any] | None:
    if INSIGHT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.borrowed_golden_form",
        display_name="Borrowed Golden Form", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        costs=(),
        parameters={"typed": {"source": INSIGHT, "numbers": dict(info["numbers"]),
                              "duration": {"kind": "instant"}, "riders": [],
                              "effects": [{"type": "borrowed_golden_choice"}]},
                    "expected_damage": 0,
                    "description": "Bonus Action, 4 Qi, once per scene: choose one Golden Core Form you do not "
                                    "possess until the scene ends. Gain its unperfected benefits, or its Perfected "
                                    "benefits at CL20 if you permanently possess two Perfected Forms."})]


@hook("candidate_allowed")
def borrowed_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The borrow exists only while an unpossessed Form remains, the scene has not spent it, and 4 Qi is there to pay."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if not any(effect_row.get("type") == "borrowed_golden_choice" for effect_row in typed.get("effects") or []):
        return None
    if not owned(engine, actor) or actor.turn_flags.get(SCENE_USED):
        return False
    if int(actor.resources.get(QI, 0) or 0) < 4:
        return False
    return any(key not in (forms(actor) or ("stable",)) for key in FORMS)


@effect("borrowed_golden_choice")
def borrow(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not owned(engine, actor) or actor.turn_flags.get(SCENE_USED):
        return
    unpossessed = [key for key in FORMS if key not in (forms(actor) or ("stable",))]
    if not unpossessed:
        return
    from .choice_costs import Payment
    from .needle import ai_controlled, ask, checkpoint_id, CHOICE
    from .qi_path import form_state

    # "At CL20, when you permanently possess two Perfected Forms, Borrowed Golden Form
    # may grant the third Form in its Perfected state for the scene": the permanent
    # (not borrowed) Forms are all Perfected and there are two of them, so the borrow
    # may perfect the Form it grants. Perfected is strictly the larger printed benefit,
    # so no separate question is asked.
    permanent = forms(actor, permanent_only=True)
    perfected_grant = (int(ctx.numbers.get("cl") or 1) >= 20 and len(permanent) >= 2
                       and all(form_state(engine, actor, key) for key in dict.fromkeys(permanent)))
    payment = Payment(QI, 4)
    if ai_controlled(engine, actor):
        key = unpossessed[0]  # a beneficial choice for its own side: the first Form it lacks
        payment.pay(engine, actor, INSIGHT)
    else:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "borrowed_golden_form", actor.entity_id),
                     actor, CHOICE + "borrowed_golden_form", unpossessed,
                     labels={key: FORMS[key] for key in unpossessed},
                     preferred=[unpossessed[0]], allow_decline=True,
                     name="Borrowed Golden Form", feature_id=INSIGHT, payment=payment,
                     prompt=("Borrowed Golden Form: choose one Golden Core Form you do not possess. "
                             f"You gain its {'Perfected' if perfected_grant else 'unperfected'} benefits "
                             "until the scene ends, for 4 Qi (once per scene)."))
        if not picked:
            return
        payment.pay(engine, actor, INSIGHT)
        key = picked[0]
    # Stable is the permanent default when no choice was recorded. Preserve it
    # before adding a temporary Form, which would otherwise hide that fallback.
    # This records the existing first choice; the borrow uses no permanent slot.
    if not forms(actor):
        engine._apply_condition(actor, FORM, GOLDEN, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"form": "stable", "label": "Golden Core Form: Stable Golden Core"})
    actor.turn_flags[SCENE_USED] = True
    engine._apply_condition(actor, FORM, INSIGHT, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"form": key, "perfected": perfected_grant, "borrowed": True,
                                  "label": (f"Borrowed {FORMS[key]} "
                                            f"({'Perfected' if perfected_grant else 'unperfected'}, until the scene ends)")})
    note(engine, INSIGHT, actor,
         f"{actor.display_name} borrows the {FORMS[key]} until the scene ends "
         f"({'Perfected' if perfected_grant else 'its unperfected benefits'}).", (actor,))
