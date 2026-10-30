"""Physical Grapple occupancy, keyed by the body part that maintains each hold.

Physical Unarmed Strike Grapple and newly compiled grants marked
typed.physical_grapple=True opt in. Magical and projectile effects using
Grappled retain their own printed lifetimes and consume no part.

Shared helper maintains_on_incapacity(engine, actor) is consumed by this
module and wrestling_framework before automatic physical-hold release. It
queries the strict pure maintain_grapples_incapacitated hook, defaults to False
and never preserves holds for inactive holders or grants actions/reactions.
"""

from __future__ import annotations

from typing import Any

from . import hook

GRAPPLED = "condition:typed.grappled"
BODY_PART_PREFIX = "body:"


def _physical_grapple(ctx: Any, effect: dict[str, Any]) -> bool:
    if effect.get("grappling_part") or (effect.get("condition_data") or {}).get("grappling_part"):
        return True
    typed = getattr(ctx, "typed", {}) or {}
    return typed.get("unarmed_option") == "grapple" or typed.get("physical_grapple") is True


def _holds(engine: Any, actor: Any) -> list[tuple[Any, Any]]:
    from .hand_occupancy import physical_holds
    return physical_holds(engine, actor)


def _is_physical_row(engine: Any, row: Any) -> bool:
    from .hand_occupancy import physical_row
    return physical_row(engine, row)


def _parts(engine: Any, actor: Any) -> list[dict[str, str]]:
    from .hand_occupancy import hand_parts
    parts = [{"id": part, "label": part.removeprefix("hand:").replace("_", " ").title() + " hand"}
             for part in hand_parts(engine, actor)]
    from . import query

    for result in query("grappling_body_parts", engine, actor):
        if isinstance(result, (list, tuple)):
            parts.extend(part for part in result if isinstance(part, dict) and isinstance(part.get("id"), str))
    return parts


def _eligible_parts(engine: Any, actor: Any) -> list[dict[str, str]]:
    # Each owning feature supplies only its currently eligible body parts.
    return _parts(engine, actor)


def _free_parts(engine: Any, actor: Any) -> list[dict[str, str]]:
    from .hand_occupancy import occupancy, free_hands
    occupied = occupancy(engine, actor)
    hands = free_hands(engine, actor, occupied=occupied)
    return [part for part in _eligible_parts(engine, actor) if part["id"] not in occupied
            and (part["id"].startswith(BODY_PART_PREFIX) or part["id"] in hands)]


def _choose_part(ctx: Any, subject: Any, effect: dict[str, Any]) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    explicit = effect.get("grappling_part") or (effect.get("condition_data") or {}).get("grappling_part")
    parts = _free_parts(engine, actor)
    if isinstance(explicit, str):
        return explicit if any(part["id"] == explicit for part in parts) else None
    if not parts:
        return None
    body_options = [part for part in parts if part["id"].startswith(BODY_PART_PREFIX)]
    if not body_options:
        return parts[0]["id"]
    # The owning body feature supplies its part. The player chooses that part
    # at the failed Grapple save; AI uses the first available option.
    from .needle import CHOICE, ask, checkpoint_id

    ids = [part["id"] for part in parts]
    labels = {part["id"]: part["label"] for part in parts}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "grapple_part", actor.entity_id, subject.entity_id), actor,
                 CHOICE + "grapple_part", ids, labels=labels,
                 name="Choose what maintains the Grapple",
                 prompt=f"{ctx.action.display_name} affects {subject.display_name}. Choose which free hand or eligible body part maintains it.",
                 target_id=subject.entity_id, preferred=[ids[0]], automatic=True, default="first")
    return picked[0] if picked else None


@hook("candidate_allowed")
def hide_grapple_without_part(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("unarmed_option") != "grapple" and typed.get("physical_grapple") is not True:
        return None
    return False if not _free_parts(engine, actor) else None


@hook("condition_state")
def record_grappling_part(ctx: Any, subject: Any, effect: dict[str, Any]) -> dict[str, Any] | bool | None:
    if effect.get("condition") != "grappled" or not _physical_grapple(ctx, effect):
        return None
    part = _choose_part(ctx, subject, effect)
    if part is None:
        return False
    from . import run

    data = {"grapple_source": "physical", "grappling_part": part}
    for extra in run("grappling_part_selected", ctx, subject, part):
        if isinstance(extra, dict):
            data.update(extra)
    return {"data": data}


def _remove_part_holds(engine: Any, actor: Any, unavailable: set[str] | None, reason: str) -> None:
    for target, row in _holds(engine, actor):
        if unavailable is not None and (row.data or {}).get("grappling_part") not in unavailable:
            continue
        target.conditions.pop(row.instance_id, None)
        engine._append_event("CONDITION_REMOVED", row.source_definition_id, actor_id=actor.entity_id,
                             target_ids=(target.entity_id,), payload={"condition_id": row.condition_id,
                             "instance_id": row.instance_id, "reason": reason})


def maintains_on_incapacity(engine: Any, actor: Any) -> bool:
    """Pure public exception query shared by physical-hold lifecycle consumers.

    Removing an inactive/dead holder still ends its holds. An active holder may
    preserve them through Incapacitated, without gaining actions or reactions.
    """
    from . import run_strict
    if not actor.active:
        return False
    replies = run_strict("maintain_grapples_incapacitated", engine, actor)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError("maintain_grapples_incapacitated must return bool or None")
    return True in replies


@hook("became_incapacitated")
def release_holds_on_incapacity(engine: Any, actor: Any, event: dict[str, Any]) -> None:
    if not maintains_on_incapacity(engine, actor):
        _remove_part_holds(engine, actor, None, "GRAPPLER_INCAPACITATED")


@hook("event")
def reconcile_body_eligibility(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    condition_id = payload.get("condition_id")
    if condition_id not in {"condition:typed.prone", "condition:typed.restrained"}:
        return
    for actor_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(actor_id)
        if actor is not None:
            reconcile_feature_parts(engine, actor)


@hook("grapple_eligibility_changed")
def reconcile_feature_parts(engine: Any, actor: Any, released: tuple[str, ...] = ()) -> None:
    eligible = {part["id"] for part in _eligible_parts(engine, actor)}
    held_body_parts = {(row.data or {}).get("grappling_part") for _, row in _holds(engine, actor)}
    _remove_part_holds(engine, actor, {part for part in held_body_parts
                                      if isinstance(part, str) and part.startswith(BODY_PART_PREFIX)
                                      and (part not in eligible or part in released)},
                       "MAINTAINING_PART_UNAVAILABLE")
