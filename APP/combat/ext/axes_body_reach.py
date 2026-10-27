"""Mountain-Felling Axe Body's +5-foot axe reach (rider lane 3).

The form creates a timed state. Compiled melee axe actions have an additional
reach variant, offered only while that state remains. Opportunity attacks use
the same variant through opportunity_action, including their eligibility reach.
Ranged axe attacks and other weapons keep their ordinary range.
"""
from typing import Any

from . import effect, hook

FORM = "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"
STATE = "condition:typed.axes_body_reach"
SUFFIX = ".axes_body_reach"


@hook('compile_weapon_traits')
def hewing_traits(info: dict[str, Any]) -> dict[str, Any] | None:
    """Hewing Intent affects only its owner's axe weapon actions."""
    from ..factory_compiler import _fits

    if 'TAL_AXES_HEWING_INTENT' in info['owned_ids'] and _fits(info['weapon'], {'family': 'axe'}):
        return {'mundane': False}
    return None


def active(actor: Any) -> bool:
    return any(c.condition_id == STATE for c in actor.conditions.values())


@effect("axes_body_reach")
def activate(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, STATE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, row, ctx.actor, condition=True))


@hook("compile_actions")
def reach_variants(info: dict[str, Any]) -> list[Any] | None:
    if FORM not in info["owned_ids"] or not any(
            row.get("type") == "axes_body_reach" for row in info["mechanics"][FORM].get("effects") or []):
        return None
    made = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        attacks = [e for e in typed.get("effects") or [] if e.get("type") == "attack"]
        if not typed.get("weapon") or not attacks or typed.get("long_range_ft") or any(
                e.get("attack_kind") in ("ranged", "cultivation_ranged", "cultivation_thrown") for e in attacks):
            continue
        if not (typed.get("sphere") == "tianxia.sphere.axes" or any(
                word in action.display_name.lower() for word in ("axe", "hatchet", "francisca", "tomahawk"))):
            continue
        made.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + SUFFIX,
            "display_name": action.display_name + " (Mountain-Felling reach)",
            "range_ft": int(action.range_ft or 5) + 5,
            "parameters": {**action.parameters, "axes_body_reach": True},
        }))
    return made


@hook("candidate_allowed")
def candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "parameters", None) or {}).get("axes_body_reach"):
        return None if active(actor) else False
    return None


@hook("opportunity_action")
def opportunity(engine: Any, actor: Any, action: Any) -> Any | None:
    base = ((action.parameters or {}).get("typed") or {}).get("opportunity_of")
    # The compiler may choose the longer variant as the fighter's best weapon.
    # Normalize its reach while the form is inactive, and never add twice.
    if str(base).endswith(SUFFIX):
        return action if active(actor) else action.model_copy(update={"range_ft": int(action.range_ft or 10) - 5})
    if not active(actor):
        return None
    extended = engine.action_catalog.get(str(base) + SUFFIX)
    if extended is None:
        return None
    return action.model_copy(update={"range_ft": extended.range_ft})
