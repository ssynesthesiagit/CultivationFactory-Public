"""Hidden Eye talents that regain Martial Focus (eye, 2026-09-28): Hidden Focus, Adroit Focus."""

from __future__ import annotations

from typing import Any

from . import hook
from .eye_common import FOCUS, analyzed_by, has

HIDDEN_FOCUS = "TAL_THE_HIDDEN_EYE_HIDDEN_FOCUS"
ADROIT_FOCUS = "TAL_THE_HIDDEN_EYE_ADROIT_FOCUS"


# ---------------------------------------------------------------- Hidden Focus
@hook("compile_actions")
def hidden_focus_action(info: dict[str, Any]) -> list[Any] | None:
    if HIDDEN_FOCUS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.hidden_focus", display_name="Hidden Focus: Regain Martial Focus",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=120,
        parameters={"typed": {"effects": [{"type": "gain_resource", "resource_id": FOCUS, "applies_to": "self", "flat": 1, "formula": "none"}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0})]


@hook("candidate_allowed")
def hidden_focus_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not str(getattr(action, "source_definition_id", "")).endswith(".hidden_focus"):
        return None
    from .. import stealth

    if actor.resources.get(FOCUS, 0) >= 1:
        return False  # already holds it
    from .riders14_eye import stalker_active

    return stalker_active(engine, actor)  # Greater Stalker supplies its additional printed eligibility states.


# ---------------------------------------------------------------- Adroit Focus
@hook("event")
def adroit_focus_ready(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"When a creature Analyzed by you is reduced to 0 Hit Points, you may regain Martial Focus" -- by anyone's
    attack, not just the Adroit Focus holder's own; watched generically off every damage event."""
    if event_type != "DAMAGE_COMMITTED":
        return None
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        # DAMAGE_COMMITTED fires with the target's HP already at (or below) 0, but the engine does not flip its own
        # "active" bookkeeping flag off until a later ENTITY_DEFEATED step -- so "reduced to 0 Hit Points" is read off
        # current_hp here, not target.active (a real bug caught by tests/test_auto_eye.py's Adroit Focus test).
        if target is None or target.current_hp > 0:
            continue
        for actor in engine.state.actors.values():
            if has(engine, actor.entity_id, "adroit_focus") and analyzed_by(target, actor.entity_id):
                # A key containing "_round_" survives the turn reset (combat/ext/__init__.py determinism rule): stays
                # usable for the rest of the round the kill happened in, covering both "immediately" readings of
                # "Bonus Action or Reaction" without inventing an unbounded window.
                actor.turn_flags[f"adroit_focus_ready_round_{engine.state.round_number}"] = True
    return None


@hook("compile_actions")
def adroit_focus_action(info: dict[str, Any]) -> list[Any] | None:
    if ADROIT_FOCUS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.adroit_focus", display_name="Adroit Focus: Regain Martial Focus",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "gain_resource", "resource_id": FOCUS, "applies_to": "self", "flat": 1, "formula": "none"}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": ["Adroit Focus may instead be taken as a Reaction; this table offers it as a Bonus Action only."]},
                    "expected_damage": 0})]


@hook("candidate_allowed")
def adroit_focus_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not str(getattr(action, "source_definition_id", "")).endswith(".adroit_focus"):
        return None
    if actor.resources.get(FOCUS, 0) >= 1:
        return False
    return bool(actor.turn_flags.get(f"adroit_focus_ready_round_{engine.state.round_number}"))
