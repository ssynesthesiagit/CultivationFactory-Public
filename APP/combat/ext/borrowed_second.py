"""Borrowed Second's movement options and separate optional debt repayment.

Only newly reviewed actions containing borrowed_second_step enable these hooks;
old saved bundles and other characters remain inert. Manual owners choose through
the existing transport, including when an AI ends the preceding turn. AI owners
choose automatically. The payment condition persists its rules and holder-turn
expiry; forced movement does not remove it. Non-movement borrowing options remain
explicit GM riders, as before; no extra Action or turn is granted here.
"""

from ..paid_relocation import activation
from typing import Any

from . import effect, hook
from .movement_semantics import moves_user, primary_moves_user

SOURCE = "tianxia.tradition.spirit.well_of_hours.feature.borrowed_second"
DEBT = "resource:named.time_debt"
PAYMENT = "condition:typed.borrowed_second_payment"
PAYMENT_CONDITIONS = frozenset((PAYMENT, "condition:typed.paying_the_second_back"))


def _owned(engine: Any, actor: Any) -> Any:
    return next((action for action in engine.action_catalog.values()
                 if action.owner_id == actor.entity_id
                 and (action.parameters.get("typed") or {}).get("source") == SOURCE
                 and any(row.get("type") == "borrowed_second_step"
                         for row in (action.parameters.get("typed") or {}).get("effects", []))), None)


def _paying(actor: Any) -> bool:
    return any(c.condition_id in PAYMENT_CONDITIONS for c in actor.conditions.values())


@hook("compile_actions")
def manual_choice_owner(info: dict) -> None:
    if SOURCE not in info["owned_ids"]:
        return
    row = info["mechanics"].get(SOURCE) or {}
    if not any(e.get("type") == "borrowed_second_step" for e in row.get("effects", [])):
        return
    info["passives"].append({"feature_id": SOURCE, "name": "Borrowed Second", "choice_owner": True})


@effect("borrowed_second_step")
def borrowed_step(ctx: Any, row: dict) -> None:
    if ctx.typed.get("source") != SOURCE or _paying(ctx.actor):
        return
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    actor, engine = ctx.actor, ctx.engine
    speed = int(engine._effective_speed(actor))
    options = ["move"]
    prone = any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())
    if prone and speed > 0:
        options.append("stand")
    labels = {"move": f"Move up to {speed // 2} feet without provoking opportunity attacks; gain 1 Time Debt",
              "stand": "Stand from Prone and move up to 10 feet; gain 1 Time Debt"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "borrowed_second", actor.entity_id), actor,
                 "choice:needle.borrowed_second", options, labels=labels, name="Borrowed Second", feature_id=SOURCE,
                 preferred=["stand"] if "stand" in options else ["move"],
                 target_id=actor.entity_id,
                 prompt=f"Borrowed Second: {actor.display_name} spends 3 Resonance (Spirit technique energy). Choose a small movement now; gain 1 Time Debt to repay later.")
    if not picked:
        return
    distance = speed // 2
    if picked[0] == "stand":
        engine._remove_condition(actor, "condition:typed.prone", ctx.source)
        # Only the first printed option explicitly avoids opportunity attacks.
        # Grant this option's ordinary movement through the existing executor.
        from ..typed_executor import block_movement
        block_movement(ctx, {"type": "movement", "applies_to": "self", "distance_ft": 10})
        return
    paths = routes(engine, actor, distance)
    if not paths:
        return
    destination = ask(engine, ctx.intent, checkpoint_id(engine, "borrowed_second_destination", actor.entity_id), actor,
                      "choice:needle.borrowed_second_destination", sorted(paths),
                      labels={k: f"Move to {k.removeprefix('cell:')} without provoking opportunity attacks" for k in paths},
                      allow_decline=True, name="Borrowed Second", feature_id=SOURCE, target_id=actor.entity_id,
                      prompt=f"Borrowed Second: {actor.display_name} may move up to {distance} feet now without provoking opportunity attacks; no additional cost.")
    if destination:
        step(engine, actor, paths[destination[0]], ctx.source)


@hook("turn_start_choice")
def pay_back(engine: Any, actor: Any) -> None:
    action = _owned(engine, actor)
    debt = int(actor.resources.get(DEBT, 0))
    if action is None or not actor.active or debt <= 0:
        return
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    description = (f"Borrowed Second — Pay the Second Back: at the start of {actor.display_name}'s turn, remove up to 2 Time Debt "
                   f"(currently {debt}). Until the start of its next turn, its Speed is 0; it cannot take Reactions, "
                   "move voluntarily, teleport, use a power primarily to move itself, or use Borrowed Second. Forced movement is still possible.")
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "pay_the_second_back", actor.entity_id),
                 actor, "choice:needle.pay_the_second_back", ["pay"], labels={"pay": description},
                 name="Pay the Second Back", feature_id=SOURCE, target_id=actor.entity_id,
                 prompt=description, allow_decline=True)
    if not picked:
        return
    with activation(engine, actor, action.source_definition_id):
        engine._apply_condition(actor, PAYMENT, action.source_definition_id, actor.entity_id,
                                expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
                                data={"label": "Pay the Second Back: Speed 0; no Reactions, voluntary movement, teleporting or Borrowed Second until the start of your next turn",
                                      "rule": {"speed_zero": 1, "no_reactions": 1, "no_teleport": 1}})
        actor.reaction_available = False
        engine._spend_resource(actor, DEBT, min(2, debt), action.source_definition_id)


@hook("candidate_allowed")
def payment_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not _paying(actor):
        return None
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if str(typed.get("source") or "").startswith(SOURCE):
        return False
    if primary_moves_user(typed):
        return False
    return None


@hook("effect_allowed")
def payment_effects(ctx: Any, row: dict) -> bool | None:
    if not _paying(ctx.actor):
        return None
    if str(ctx.typed.get("source") or "").startswith(SOURCE):
        return False  # No partial borrowing/debt packet through a nested or free execution.
    if moves_user(row):
        return False
    return None


@hook("teleport_gate")
def payment_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    return False if _paying(ctx.actor) else None
