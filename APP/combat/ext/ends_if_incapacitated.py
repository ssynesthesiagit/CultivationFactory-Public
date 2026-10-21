"""An ability that "ends early if you become Incapacitated" (riders lane 2, 2026-09-29): the Martial Domains of the Iron Fist,
Wrestling, Guardian and Berserker spheres, Sovereign Iron-Body Incarnation, Stand Against the Calamity ("... or willingly move").
The Needle domains have their own copy of this in needle.py.

    {"type": "ends_if_incapacitated", "applies_to": "self"}                       # anywhere in the ability's effects
    {"type": "ends_if_incapacitated", "applies_to": "self", "also_on_move": true}  # ... or when you willingly move

puts a marker (``condition:typed.ends_if_incapacitated.<ability>``) on the user for as long as the ability lasts (the ability's own
duration; Concentration included).  When the user gains the Incapacitated condition -- or any state that includes it -- everything
that ability put on anyone comes off: its conditions, its modifiers, its areas, the Concentration it held, and the marker.
``also_on_move`` also ends it the first time the user moves on its own (forced or dragged movement is not willing).

Deterministic and evented: conditions and modifiers are removed with CONDITION_REMOVED / MODIFIER_REMOVED events (the way
end_effect.py and concentration.py remove them), an area with zones.remove, Concentration with the engine's own
_end_concentration.  Nothing here reads a random roll.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "condition:typed.ends_if_incapacitated."


def _slug(source: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(source))[-80:]


@effect("ends_if_incapacitated")
def apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for holder in _default_subject(ctx, {**row, "applies_to": row.get("applies_to") or "self"}, harmful=False):
        marker = PREFIX + _slug(ctx.source)
        ctx.engine._remove_condition(holder, marker, ctx.source)  # again: the new use's own
        ctx.engine._apply_condition(holder, marker, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, row, holder, condition=True),
                                    data={"label": "Ends early if you become Incapacitated" + (" or willingly move" if row.get("also_on_move") else ""),
                                          "also_on_move": bool(row.get("also_on_move"))})


def _markers(actor: Any) -> list[Any]:
    return [condition for condition in actor.conditions.values() if condition.condition_id.startswith(PREFIX)]


def end_ability(engine: Any, holder: Any, source: str, why: str) -> None:
    """Take off everything the ability ``source`` (used by ``holder``) put on anyone, and its area and Concentration."""
    concentration = getattr(holder, "concentration", None)
    if concentration is not None and concentration.source_definition_id == source:
        engine._end_concentration(holder, why.upper().replace(" ", "_"))
    for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        for iid, row in list(other.conditions.items()):
            if row.source_definition_id == source and row.source_actor_id == holder.entity_id:
                del other.conditions[iid]
                engine._append_event("CONDITION_REMOVED", source, actor_id=holder.entity_id, target_ids=(other.entity_id,),
                                     payload={"condition_id": row.condition_id, "instance_id": iid, "reason": why.upper().replace(" ", "_")})
        for mid, row in list(other.modifiers.items()):
            if row.source_definition_id == source and row.source_actor_id == holder.entity_id:
                del other.modifiers[mid]
                engine._append_event("MODIFIER_REMOVED", source, actor_id=holder.entity_id, target_ids=(other.entity_id,),
                                     payload={"modifier_id": mid, "reason": why.upper().replace(" ", "_")})
    from .. import zones

    for zone in sorted(engine.state.zones.values(), key=lambda row: row.zone_id):
        if zone.active and zone.source_definition_id == source and zone.owner_id == holder.entity_id:
            zones.remove(engine, zone, why.upper().replace(" ", "_"))


def _incapacitated(actor: Any) -> bool:
    from .needle import incapacitated

    return incapacitated(actor)


@hook("event")
def ends_when_incapacitated_or_moves(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "CONDITION_APPLIED":
        holder = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if holder is None or not _incapacitated(holder):
            return
        for marker in _markers(holder):
            note(engine, marker.source_definition_id, holder, f"{holder.display_name} is Incapacitated: the ability ends.")
            end_ability(engine, holder, marker.source_definition_id, "incapacitated")
    elif event_type == "MOVEMENT_COMMITTED":
        holder = engine.state.actors.get(kwargs.get("actor_id") or "")
        payload = kwargs.get("payload") or {}
        if holder is None or payload.get("forced") or payload.get("dragged_by") or len(payload.get("path") or []) < 2:
            return
        for marker in _markers(holder):
            if (marker.data or {}).get("also_on_move"):
                note(engine, marker.source_definition_id, holder, f"{holder.display_name} moved willingly: the ability ends.")
                end_ability(engine, holder, marker.source_definition_id, "willingly moved")
