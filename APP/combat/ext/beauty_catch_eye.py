"""Catch the Eye's creature domain, perception requirement and optional mark.

Uses compile_action/target_eligibility and choose_effects contracts, plus the
default-inert condition_source_perceived seam for Captivated's live cleanup.
The original save, Captivated rules, expiry and caster-scoped resistance remain
the typed producers. Only the owned base action (including its variants) opts
in; no other Beauty ability or creature receives different behavior.
"""
from __future__ import annotations

import copy
from typing import Any

from . import hook

EYE = "BEAUTY_BASE_CATCH_THE_EYE"


@hook("compile_action")
def catch_eye(action: Any, info: dict[str, Any]) -> Any | None:
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("source") != EYE or EYE not in (info.get("owned_ids") or ()):
        return None
    typed = copy.deepcopy(typed)
    for row in typed.get("effects") or []:
        if row.get("type") != "save":
            continue
        success = []
        for effect in row.get("on_success") or []:
            if effect.get("type") == "mark" and effect.get("mark") == "Beauty Mark":
                success.append({"type": "choose_effects", "name": "Catch the Eye",
                    "result": "succeeded on the Wisdom saving throw against Catch the Eye",
                    "options": [
                        {"label": "Place Beauty Mark", "display_label": "Place your Beauty Mark until the end of your next turn (0 CP; no extra action).", "effects": [effect]},
                        {"label": "No Beauty Mark", "display_label": "Do not place a Beauty Mark.", "effects": []}]})
            else:
                success.append(effect)
        row["on_success"] = success
    typed["manual_inline_choice"] = True
    return action.model_copy(update={"target_kind": "ANY_CREATURE", "parameters": {
        **action.parameters, "typed": typed,
        "description": "Action, 0 CP. Choose one creature within 60 feet that can perceive you. "
        "It makes a Wisdom saving throw. On failure, it is Captivated by you until the end of your next turn "
        "and gains your Beauty Mark for 1 minute. On success, you may place your Beauty Mark until the end "
        "of your next turn; it also has Advantage on saves against your Catch the Eye for 10 minutes."}})


@hook("target_eligibility")
def perceiving_target(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    if action is None or ((action.parameters or {}).get("typed") or {}).get("source") != EYE:
        return None
    if not can_perceive_presence(engine, target, actor, action.source_definition_id):
        return False
    return None


def can_perceive_presence(engine: Any, observer: Any, source: Any, source_id: str) -> bool:
    """Catch the Eye admission and Captivated upkeep share visual/voiced delivery.

    Sight/special senses and hearing/sound-path rules are native facts. Voice is
    one of the printed delivery methods, available only while the caster can
    speak and the observer can hear them; no scene or intent fact is invented.
    """
    from ..senses import perceives
    from ..speech import can_hear_from, silenced

    return (observer is source or perceives(engine, observer, source)
            or (not silenced(source) and can_hear_from(engine, source, observer, source_id)))


@hook("condition_source_perceived")
def captivated_presence(engine: Any, observer: Any, source: Any, condition: Any) -> bool | None:
    from .resist_ability import source_ability

    action = engine.action_catalog.get(condition.source_definition_id)
    if (condition.condition_id != "condition:typed.captivated"
            or action is None or action.owner_id != source.entity_id
            or source_ability(engine, condition.source_definition_id) != EYE):
        return None
    return can_perceive_presence(engine, observer, source, condition.source_definition_id)
