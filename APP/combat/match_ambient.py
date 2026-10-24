"""The table owner's ambient light, recorded as a fight event (LIGHTS2 root fix).

A mid-fight change to the light is a GM declaration committed through the same settings-binding path as the world-fact
declaration (combat/fact_consent_admission.py): it is validated against the live engine, executed in one engine
transaction, and appended to the fight's event log as AMBIENT_SET. The replay reducer applies that event into
state.ambient_override, so live play, save/reload, replay and verify all evaluate recorded decisions under the same light.

The sealed Arena_Battlefield.json is never written. Nothing else is written either: the event log is the only record.
A field the GM has not set keeps the arena's authored value (combat/lighting.py `ambient`).
"""
from __future__ import annotations

from typing import Any

from .canonical import canonical_sha256
from .journey import require

AMBIENT_KIND = "MATCH_AMBIENT_V1"
AMBIENT_EVENT = "AMBIENT_SET"
AMBIENT_DECISION = "match-ambient:v1"
AMBIENT_SOURCE = "system:table.ambient"
TIME_LEVELS = {"day": 2, "dawn": 1, "dusk": 1, "night": 0, "underground": 0}
LEVELS = {"bright": 2, "dim": 1, "dark": 0}
FIELDS = ("time_of_day", "level", "indoor_level")


def normalize_ambient(value: Any) -> dict[str, Any]:
    """The settings the GM chose, normalized. Only the keys the GM gave are kept; a level the GM did not set is
    not derived here, so the light model can fall back to the arena's authored value for it."""
    if not isinstance(value, dict):
        raise ValueError("Ambient light settings must be an object.")
    result: dict[str, Any] = {}
    if "time_of_day" in value and value["time_of_day"] is not None:
        time = str(value["time_of_day"]).strip().lower()
        if time not in TIME_LEVELS:
            raise ValueError("Choose day, dawn, dusk, night or underground.")
        result["time_of_day"] = time
    for key in ("level", "indoor_level"):
        level = value.get(key)
        if level is None:
            continue
        if isinstance(level, str):
            level = LEVELS.get(level.strip().lower())
        if type(level) is not int or level not in (0, 1, 2):
            raise ValueError("Light level must be bright, dim or dark.")
        result[key] = level
    if not result:
        raise ValueError("Set a time of day, a level or an indoor level.")
    return result


def merge_ambient(current: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """The one merge rule, shared by the live commit and the replay reducer."""
    return {**current, **{key: delta[key] for key in FIELDS if key in delta}}


def validate_ambient_binding(engine: Any, intent: Any, binding: dict[str, Any]) -> dict[str, Any]:
    require(set(binding) == {"kind", "payload"} and binding["kind"] == AMBIENT_KIND
            and isinstance(binding["payload"], dict), "Invalid ambient light input policy.")
    ambient = normalize_ambient(binding["payload"])
    require(engine.state.terminal_result is None and engine.state.pending_resolution is None
            and intent.state_version == engine.state.state_version and intent.decision_id == AMBIENT_DECISION
            and intent.candidate_id == canonical_sha256(binding)
            and not any((intent.target_ids, intent.option_ids, intent.reaction_decisions, intent.object_ids,
                         intent.destination, intent.placement_destination, intent.movement_path, intent.movement_mode,
                         intent.relation_change, intent.condition_instance_id, intent.penalty_id,
                         intent.source_effect_dc)),
            "Refresh the fight; the light is set by the table owner and cannot carry a fighter action.")
    return ambient


def execute_ambient_binding(engine: Any, intent: Any, binding: dict[str, Any]) -> None:
    ambient = validate_ambient_binding(engine, intent, binding)
    with engine._transaction(AMBIENT_SOURCE, intent.intent_id, intent.actor_id):
        engine.state.ambient_override = merge_ambient(dict(engine.state.ambient_override), ambient)
        engine._append_event(AMBIENT_EVENT, AMBIENT_SOURCE, payload={"ambient": ambient},
                             trigger_or_intent_id=intent.intent_id)
