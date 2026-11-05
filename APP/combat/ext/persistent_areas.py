"""Post-creation persistence for abilities whose printed augment allows conversion (Hunt 57)."""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .ability_source import mechanic_of
from .. import concentration, zones

DARKNESS = "DARK_BASE_DARKNESS"
PERSISTENT_AREA = "condition:combat.ext.persistent_area"


@hook("compile_actions")
def conversion_action(info: dict[str, Any]) -> list[Any] | None:
    """A separate affordable post-cast control; the loadout toggle stays free."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    for action in info["actions"]:
        if mechanic_of(action) != DARKNESS:
            continue
        loadout = (action.parameters or {}).get("augment_loadout") or {}
        row = next((r for r in loadout.get("augments") or [] if r.get("name") == "Persistent Darkness"), None)
        if row is None:
            continue
        return [ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.darkness.convert_persistent",
            display_name="Make existing Darkness Persistent", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            costs=tuple((str(resource), int(amount)) for resource, amount in row.get("costs") or []),
            parameters={"persistent_darkness_conversion": True, "expected_damage": 0,
                        "typed": {"effects": [{"type": "convert_persistent_darkness"}],
                                  "duration": {"kind": "instant"}, "numbers": dict(info["numbers"]), "riders": []},
                        "description": "No action: pay 2 cultivation points from your Path resource pool to make your most recent Darkness created this turn persist without Concentration until its original one-minute duration ends."})]
    return None


def convertible_copy(engine: Any, actor: Any) -> Any:
    """Latest owned Darkness created this turn, whether current or held."""
    copies = [state for _iid, state in concentration.held(actor)]
    if actor.concentration is not None:
        copies.append(actor.concentration)
    for state in sorted(copies, key=lambda state: state.started_sequence, reverse=True):
        action = engine.action_catalog.get(state.source_definition_id)
        zone = engine.state.zones.get(state.zone_id)
        if (action is not None and action.owner_id == actor.entity_id and mechanic_of(action) == DARKNESS
                and zone is not None and zone.active and zone.owner_id == actor.entity_id
                and zone.concentration_link and zone.created_round == engine.state.round_number):
            return state, zone
    return None


@hook("candidate_allowed")
def conversion_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("persistent_darkness_conversion"):
        return None
    return engine.state.current_actor_id == actor.entity_id and convertible_copy(engine, actor) is not None


@effect("convert_persistent_darkness")
def convert_existing_area(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor, source = ctx.engine, ctx.actor, ctx.source
    found = convertible_copy(engine, actor)
    if found is None:
        return
    state, zone = found

    # Keep the cast's round as an integer deadline. The old zone schema stores
    # no separate deadline for Concentration-only zones, so the marker carries
    # it through ordinary condition events and table recovery.
    engine._apply_condition(actor, PERSISTENT_AREA, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"zone_id": zone.zone_id, "expires_round": zone.created_round + 10,
                                  "label": "Persistent Darkness"})
    concentration.end_copy(engine, actor, state.started_sequence, "PERSISTENT_AREA", retain_zone=True)


@hook("turn_start")
def expire_persistent_darkness(engine: Any, actor: Any) -> None:
    """Expire converted areas at the same round boundary as their original one-minute duration."""
    for instance_id, condition in list(actor.conditions.items()):
        if condition.condition_id != PERSISTENT_AREA:
            continue
        data = condition.data or {}
        if engine.state.round_number < int(data.get("expires_round") or 0):
            continue
        zone = engine.state.zones.get(str(data.get("zone_id") or ""))
        if zone is not None:
            zones.remove(engine, zone, "DURATION_EXPIRED")
        actor.conditions.pop(instance_id, None)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id,
                             target_ids=(actor.entity_id,), payload={"condition_id": PERSISTENT_AREA, "instance_id": instance_id,
                                                                     "reason": "DURATION_EXPIRED"})


@hook("status_description")
def persistent_darkness_status(engine: Any, holder: Any, row: Any, data: dict[str, Any]) -> dict[str, str] | None:
    """Present the persistent marker's true duration instead of the original concentration flag."""
    description = {
        "display_name": "Persistent Darkness",
        "rules": "This Darkness area remains without Concentration. Converting it costs 2 cultivation points from your Path resource pool once, with no Action. It ends no later than one minute after the original cast.",
        "duration": "up to 10 rounds from when it was created",
    }
    condition_id = row.get("condition_id") if isinstance(row, dict) else getattr(row, "condition_id", None)
    if condition_id == PERSISTENT_AREA:
        # Historical condition events can omit the marker's stored zone data.
        return description
    zone_id = str((data or {}).get("zone_id") or getattr(row, "zone_id", "") or "")
    if isinstance(row, dict):
        zone_id = str((data or {}).get("zone_id") or row.get("zone_id") or "")
    if not zone_id:
        return None
    owner_id = getattr(row, "owner_id", None)
    if isinstance(row, dict):
        # Zone rows carry owner_id; condition pills carry their applier as
        # source_actor_id. Both identify the actor holding the deadline marker.
        owner_id = row.get("owner_id") or row.get("source_actor_id")
    owner = engine.state.actors.get(owner_id)
    if owner is None or not any(condition.condition_id == PERSISTENT_AREA and
                                (condition.data or {}).get("zone_id") == zone_id for condition in owner.conditions.values()):
        return None
    return description


@hook("button_description")
def persistent_darkness_button(row: dict[str, Any]) -> str | None:
    """The setting never converts or charges for an existing area."""
    parameters = row.get("parameters") or {}
    if (parameters.get("augment_name") == "Persistent Darkness" and
            parameters.get("augment_family_name") == "Darkness" and
            any(effect.get("type") == "toggle_augment" for effect in ((parameters.get("typed") or {}).get("effects") or []))):
        return ("Free setting: choose Persistent Darkness for future casts. Casting it costs 2 cultivation points from your Path resource pool; "
                "the area lasts up to one minute without Concentration. Existing Darkness is unchanged. "
                "To convert an area created this turn, choose Make existing Darkness Persistent separately.")
    return None
