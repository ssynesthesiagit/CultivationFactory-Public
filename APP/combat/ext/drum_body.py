"""Heaven-Thunder Drum Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Body Beats are gained by the Subpath record's triggers (combat/ext/subpath_pools.py; maximum PB, PB + 2 with Heaven-Drum
Circulation). This module adds:
  Heaven-Drum Circulation  once per round after spending Stamina on a Body Refining Path or Subpath feature (an Action or
                           Bonus Action of the owner), 1 Body Beat -- still the one normal Beat a round.
  Counter-Resonance        ``resonance_burst`` (only when its reduction brought the packet to 0): each hostile creature within
                           10 feet of the protected creature makes a Constitution save: 2d8 Thunder and pushed 10 feet away
                           from the protected creature, or half and no push.
  Internal Echo            ``echoing`` on a failed save: until the end of the owner's next turn, the first time the target
                           starts a typed Action or Bonus Action, or spends CP on one, the Echo detonates before that action's
                           effects -- 3d8 Thunder, no Reactions until the start of its next turn, Disadvantage on the Concentration
                           save that damage causes -- and ends.
Every hook returns early for a creature without the owner's row or the Echoing condition.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.heaven_thunder_drum_body.feature."
ECHOING = "condition:typed.echoing"
BEAT = "resource:named.body_beat"
FLIGHT_SUPPRESSED = "condition:typed.cadence_flight_suppressed"


@effect("cadence_suppress_flight")
def cadence_suppress_flight(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_subjects
    for target in effect_subjects(ctx, row, harmful=True):
        ctx.engine._apply_condition(target, FLIGHT_SUPPRESSED, ctx.source, ctx.actor.entity_id,
                                    expires_on="START_OF_TARGET_NEXT_TURN",
                                    data={"label": "Temporary flight suppressed until your next turn"})


@hook("flight_grant_allowed")
def cadence_blocks_temporary_flight(engine: Any, actor: Any, grant: Any) -> bool | None:
    if not any(c.condition_id == FLIGHT_SUPPRESSED for c in actor.conditions.values()):
        return None
    # Native wings remain on actor.fly_speed_ft. Recorded finite flight is the
    # temporary granted capability; permanent grants and unrelated data survive.
    if grant.expires_on and (grant.data or {}).get("fly_speed_ft") and not grant.data.get("flight_anatomy"):
        return False
    return None


@hook("flight_provider_allowed")
def cadence_blocks_cultivated_flight(engine: Any, actor: Any, grant: Any) -> bool | None:
    if not any(c.condition_id == FLIGHT_SUPPRESSED for c in actor.conditions.values()):
        return None
    if grant.get("fly_speed_ft", 0) > 0 and not grant.get("flight_anatomy"):
        return False
    return None


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(str(row.get("feature_id") or "") == PREFIX + feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("sense_grant_allowed")
def circulation_surface_sense(engine: Any, actor: Any, grant: Any, seen: Any) -> bool | None:
    if grant.get("feature_id") != PREFIX + "heaven_drum_circulation" or grant.get("sense") != "tremorsense":
        return None
    from .surface_contact import connected_contact, solid_contact
    if not _owns(engine, actor, "heaven_drum_circulation") or not solid_contact(engine, actor):
        return False
    return connected_contact(engine, actor, seen) if seen is not None else True


@hook("action_completed")
def circulation(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if BEAT not in actor.resources or not _owns(engine, actor, "heaven_drum_circulation"):
        return
    action = engine.action_catalog.get(source_definition_id)
    source = str((((action.parameters or {}).get("typed") or {}).get("source") if action is not None else "") or "")
    if not (source.startswith("tianxia.subpath.body.") or source.startswith("tianxia.path.body_refining")):
        return
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED" and event.actor_id == actor.entity_id:
            return
        if event.event_type == "RESOURCE_SPENT" and event.actor_id == actor.entity_id and (event.payload or {}).get("resource_id") == "resource:core.stamina":
            from .subpath_pools import gain

            gain(engine, actor, BEAT, PREFIX + "heaven_drum_circulation")
            return


@effect("resonance_burst")
def resonance_burst(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine = ctx.engine
    protected = engine.state.actors.get(str(ctx.typed.get("protects") or "")) or ctx.actor
    foes = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
            if other.active and other.team_id != ctx.actor.team_id and engine._distance_actor_to_actor(protected, other) <= 10]
    if not foes:
        return
    sub = te.Context(engine, ctx.actor, ctx.action, ctx.intent, {**ctx.typed, "_area_centre": (protected.position.x, protected.position.y)},
                     foes, foes[0] if len(foes) == 1 else None, {})
    te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Counter-Resonance: Constitution saving throw",
                          "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["thunder"]},
                                      {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away_center"}],
                          "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["thunder"]}]}])
    note(engine, ctx.source, ctx.actor, f"Counter-Resonance: the blow on {protected.display_name} rings back at those within 10 feet.", foes)


@effect("echoing")
def echoing(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is None or not target.active:
        return
    for held in [c for c in target.conditions.values() if c.condition_id == ECHOING and c.source_actor_id == ctx.actor.entity_id]:
        target.conditions.pop(held.instance_id)
        ctx.engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": ECHOING, "instance_id": held.instance_id, "reason": "REFRESHED"})
    ctx.engine._apply_condition(target, ECHOING, PREFIX + "internal_echo", ctx.actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                                data={"label": "Echoing: its next Action or Bonus Action detonates 3d8 Thunder", "pb": int(ctx.numbers.get("pb") or 2),
                                      "save_dc": int(ctx.numbers.get("save_dc") or 10), "cl": int(ctx.numbers.get("cl") or 1)})


@hook("technique_start")
def echo_detonates(engine: Any, actor: Any, action: Any) -> bool | None:
    held = next((c for c in actor.conditions.values() if c.condition_id == ECHOING), None)
    if held is None or str(getattr(action.economy, "value", action.economy)) not in ("ACTION", "BONUS_ACTION"):
        return None
    source = engine.state.actors.get(held.source_actor_id)
    actor.conditions.pop(held.instance_id)
    engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": ECHOING, "instance_id": held.instance_id, "reason": "DETONATED"})
    if source is None:
        return None
    from .. import typed_executor as te
    from .states import context

    data = held.data or {}
    ctx = context(engine, source, held.source_definition_id, [actor], {"pb": int(data.get("pb") or 2), "cl": int(data.get("cl") or 1),
                                                                       "save_dc": int(data.get("save_dc") or 10)})
    note(engine, held.source_definition_id, source, f"Internal Echo: the Echo in {actor.display_name} detonates.", (actor,))
    te.run_effects(ctx, [{"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw", "expires_on": "END_OF_CURRENT_TURN"},
                         {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["thunder"]},
                         {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"}])
    return True if not actor.active else None  # a creature the detonation drops does not finish its action
