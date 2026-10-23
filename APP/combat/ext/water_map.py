"""Shared helper module: combat/ext/water_return.py uses extinguish, flame_label, obvious_sources and ordinary_flames.

Recorded map water and ordinary flames for Water Return.

Shared public helper: consumed by water_return.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Automatic flame choices use the caster's perception. Player choices retain
the full legal area menu; obvious Water Sources always require perception.
Ignited furniture represents ordinary burning material, not a persistent Fire
technique. Unrecorded scenery is left to the GM instead of being invented.
"""
from typing import Any


def ordinary_flames(engine: Any, owner: Any, cells: Any, *, ordinary_only: bool = False) -> dict[str, Any]:
    """Perceived ignition or ordinary Burning in/adjacent to water cells.

    The ordinary Burning condition is the same contract Cleansing Basin uses.
    Native sustained Fire effects are not inferred to be ordinary flames.
    Base Return passes ordinary_only=True: native Tianxia Burn carries a
    ``burn`` damage payload (typed_executor.condition), so it is not ordinary
    Burning. Default False preserves the existing Streams caller's contract.
    """
    from ..senses import perceives_object, perceives
    from . import ai_controlled
    automatic = ai_controlled(engine, owner)
    found = {key: obj for key, obj in sorted(engine.state.objects.items())
            if obj.ignited and not obj.destroyed and (not automatic or perceives_object(engine, owner, obj))
            and any(engine.grid.distance_ft(obj.position, cell) <= 5 for cell in cells)}
    found.update({actor.entity_id: actor for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
                  if actor.active and (not automatic or actor is owner or perceives(engine, owner, actor))
                  and any(c.condition_id == 'condition:typed.burning'
                          and (not ordinary_only or 'burn' not in (c.data or {}))
                          for c in actor.conditions.values())
                  and any(engine._distance_actor_to_cell(actor, cell) <= 5 for cell in cells)})
    return found


def flame_label(subject: Any) -> str:
    """Plain flame-target label shared by the Return choice and its event."""
    return subject.display_name if hasattr(subject, 'entity_id') else (
        f'{(subject.component or {}).get("name") or subject.object_kind} '
        f'at square ({subject.position.x}, {subject.position.y})')


def extinguish(engine: Any, obj: Any, source: str, owner: Any, *, ordinary_only: bool = False) -> None:
    """Extinguish recorded ordinary ignition and emit its complete persistent state."""
    if hasattr(obj, 'entity_id'):
        from .condition_ownership import remove_instance
        for iid, condition in list(obj.conditions.items()):
            if condition.condition_id == 'condition:typed.burning' \
                    and (not ordinary_only or 'burn' not in (condition.data or {})):
                remove_instance(engine, obj, iid, source)
        engine._append_event('PASSIVE_TRIGGERED', source, actor_id=owner.entity_id, target_ids=(obj.entity_id,),
                             payload={'text': f'Return the Flow extinguishes the ordinary flames on {obj.display_name}.'})
        return
    obj.ignited = False
    obj.ignition_source_definition_id = None
    obj.ignition_actor_id = None
    obj.ignition_sequence = None
    engine._update_object(obj, source, actor_id=owner.entity_id)
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=owner.entity_id,
                         payload={'text': f'Return the Flow extinguishes the ordinary flame on {flame_label(obj)}.'})


def obvious_sources(engine: Any, owner: Any) -> dict[str, Any]:
    """Perceived recorded water cells within 60 feet, nearest first, stable on ties."""
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell
    from .water_passage import WATER
    from ..zones import MAP_OWNER
    # A created Mist/Pressure Basin need not be a physical Water Source. Query
    # authored map water only, rather than treating every magical Basin as one.
    cells = {p for zone in engine.state.zones.values()
             if zone.active and zone.owner_id == MAP_OWNER
             and WATER.search(' '.join(zone.trigger_profile.get('terrain') or []))
             for p in zone.affected_cells}
    for row in (getattr(engine, 'battlefield_document', None) or {}).get('map_terrain') or []:
        if WATER.search(str(row.get('terrain') or '')):
            for cell in row.get('cells') or []:
                cells.add(Position(**cell) if isinstance(cell, dict)
                          else Position(x=int(cell[0]), y=int(cell[1]), z=int(cell[2]) if len(cell) > 2 else 0))
    points = list(cells)
    points = [p for p in points if engine.grid.distance_ft(owner.position, p) <= 60
              and perceives_cell(engine, owner, p)]
    points.sort(key=lambda p: (engine.grid.distance_ft(owner.position, p), p.x, p.y, p.z))
    return {f'water:{p.x},{p.y},{p.z}': p for p in points}
