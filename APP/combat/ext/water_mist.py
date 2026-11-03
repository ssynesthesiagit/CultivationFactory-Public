"""Mist Veil's dense mist (Water; rider lane C11, 2026-09-30).

Source (owner text, authority/typed_mechanics/rules_text.json TAL_WATER_MIST_VEIL): "When you create a Mist Basin, you may make the area
a 15-foot-radius sphere instead of a 10-foot square. The area is Lightly Obscured. By spending 1 additional CP when you create it, you
may make the area Heavily Obscured until the start of your next turn; after that, it becomes Lightly Obscured for the remaining duration.
A creature does not become Hidden automatically. It must still use Hide or another feature."

How it runs. The 15-foot sphere was already typed (Mist Veil's modifier on Mist Basin). Its reviewed modifier (reviewed_final.d/
riders_c11.json) now offers two choices: "Lightly Obscured" and "Heavily Obscured" (+1 CP). The second carries the effect
``mist_veil_dense``: the Mist Basin just made turns Heavily Obscured, and at the start of its maker's next turn (``turn_start``) it goes
back to Lightly Obscured for the rest of its duration. Each change is the zone re-recorded (ZONE_CREATED, as zones.close_openings
does), so a saved fight replays it. Hiding is still the Hide action (nobody becomes Hidden by standing in it).
Default-inert: only areas made through that choice carry the flag.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

FLAG = "dense_until_turn"


def _record(engine: Any, zone: Any) -> None:
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


@effect("mist_veil_dense")
def dense(ctx: Any, row: dict[str, Any]) -> None:
    zones = [zone for zone in ctx.engine.state.zones.values()
             if zone.active and zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source]
    if not zones:
        ctx.rider("Mist Veil: no Mist Basin was made to thicken.")
        return
    # Creation events preserve activation order; unpadded zone IDs do not.
    ids = {zone.zone_id: zone for zone in zones}
    created = next((event for event in reversed(ctx.engine.events)
                    if event.event_type == "ZONE_CREATED" and event.source_definition_id == ctx.source
                    and event.actor_id == ctx.actor.entity_id
                    and (ctx.intent is None or event.trigger_or_intent_id == ctx.intent.intent_id)
                    and (event.payload.get("zone") or {}).get("zone_id") in ids), None)
    if created is None:
        return
    zone = ids[created.payload["zone"]["zone_id"]]
    zone.trigger_profile = {**zone.trigger_profile, "obscured": "heavy", FLAG: int(ctx.actor.turns_started) + 1}
    _record(ctx.engine, zone)
    note(ctx.engine, ctx.source, ctx.actor, f"Mist Veil: the mist is Heavily Obscured until the start of {ctx.actor.display_name}'s next turn, "
         "then Lightly Obscured.")


@hook("turn_start")
def thin_out(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    for zone in list(engine.state.zones.values()):
        until = zone.trigger_profile.get(FLAG)
        if zone.owner_id != actor.entity_id or until is None or not custom_turn_due(
                actor, until, zone.per_turn_triggered, "water_mist", nominal=nominal):
            continue
        profile = {key: value for key, value in zone.trigger_profile.items() if key != FLAG}
        zone.trigger_profile = {**profile, "obscured": "light"}
        _record(engine, zone)
        note(engine, zone.source_definition_id, actor, "Mist Veil: the dense mist thins; it is Lightly Obscured for the rest of its duration.")


@hook("nominal_slot_boundary")
def nominal_mist(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        thin_out(engine, actor, nominal=True)
