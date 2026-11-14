"""Source-bound denial of named typed effects (Canon's command sign first user).

``deny_effects`` stores effect type strings until the ordinary source expiry.
Candidate and reaction filters avoid offering wholly prohibited commands;
effect_allowed also protects nested/free executions. No ability IDs, inferred
speech/command tags, or existing benefits are removed. New users may supply
their own explicit effect types through reviewed data.
"""
from typing import Any

from . import effect, hook

CONDITION = "condition:typed.denied_effects"


def denied_types(actor: Any) -> set[str]:
    """Union independent, still-active source instances without consuming them."""
    return {kind for state in actor.conditions.values() if state.condition_id == CONDITION
            for kind in (state.data or {}).get("effect_types", [])}


def contains_denied(value: Any, denied: set[str]) -> bool:
    if isinstance(value, dict):
        return value.get("type") in denied or any(contains_denied(child, denied) for child in value.values())
    if isinstance(value, list):
        return any(contains_denied(child, denied) for child in value)
    return False


@effect("deny_effects")
def apply(ctx: Any, eff: dict) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    if not ctx.typed.get("source") or not eff.get("effect_types"):
        return
    for target in _default_subject(ctx, eff, harmful=True):
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, eff, target, condition=True),
            data={"effect_types": list(eff["effect_types"]), "label": str(eff.get("evidence") or ctx.action.display_name)})


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    denied = denied_types(actor)
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if denied and contains_denied(typed.get("effects") or [], denied):
        return False
    return None


@hook("reaction_subject_allowed")
@hook("reaction_ally_allowed")
def reaction_allowed(engine: Any, reactor: Any, other: Any, row: dict) -> bool | None:
    denied = denied_types(reactor)
    if denied and contains_denied(row, denied):
        return False
    return None


@hook("effect_allowed")
def effect_allowed(ctx: Any, eff: dict) -> bool | None:
    if eff.get("type") in denied_types(ctx.actor):
        return False
    return None
