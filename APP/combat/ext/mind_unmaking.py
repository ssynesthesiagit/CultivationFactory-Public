"""Unmaking talents owned by characters other than Tabik Damu who also have the sphere (owner 2026-09-28: "we need to
automate every aspect before another playtest"); the rest of the sphere's runtime is combat/unmaking.py.

  Black Star Vessel   a free toggle ("Black Star Vessel: Arm" / "Disarm") kept until changed; when armed and the
                      holder would next suffer Ruin Backlash, combat/unmaking.py's after_strain_gained turns that
                      Backlash into the Black Star Vessel state instead (its own damage and healing-lock; see that
                      module's docstring for what stays a GM-only rider). The built-in AI never arms it -- the state is
                      a bet against your own HP, not a default any opponent should make for it.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

_LABELS = {"arm": "Black Star Vessel: Arm", "disarm": "Black Star Vessel: Disarm"}


@hook("compile_actions")
def black_star_toggle(info: dict[str, Any]) -> list[Any] | None:
    if not any(row.get("block") == "unmaking" and row.get("kind") == "black_star_vessel" for row in info["passives"]):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.black_star_vessel.{key}", display_name=label,
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "black_star_vessel_toggle", "arm": key == "arm", "evidence": label}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True})
        for key, label in _LABELS.items()]


@effect("black_star_vessel_toggle")
def black_star_vessel_toggle(ctx: Any, eff: dict[str, Any]) -> None:
    from ..unmaking import BLACK_STAR_ARMED

    ctx.engine._remove_condition(ctx.actor, BLACK_STAR_ARMED, ctx.source)
    if eff.get("arm"):
        ctx.engine._apply_condition(ctx.actor, BLACK_STAR_ARMED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Black Star Vessel armed: the next Ruin Backlash becomes it instead"})


@hook("candidate_allowed")
def black_star_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Hide "Arm" once armed or active, and "Disarm" unless armed."""
    if action is None or not str(getattr(action, "source_definition_id", "")).startswith("action:typed.") or "black_star_vessel." not in action.source_definition_id:
        return None
    from ..unmaking import BLACK_STAR_ACTIVE, BLACK_STAR_ARMED

    armed = any(c.condition_id == BLACK_STAR_ARMED for c in actor.conditions.values())
    active = any(c.condition_id == BLACK_STAR_ACTIVE for c in actor.conditions.values())
    if action.source_definition_id.endswith(".arm"):
        return not armed and not active
    return armed and not active
