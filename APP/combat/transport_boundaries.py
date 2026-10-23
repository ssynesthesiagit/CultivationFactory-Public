"""Explicit, persisted surface boundaries for source-limited transport.

The owner map editor admits catalogue terrain, validates its squares and saves
it privately under combat_maps. to_battlefield seals those declarations into a
fight. Consumers opt into the kinds their printed source forbids; this helper
does not restrict walking, grant a barrier or classify scenery by its name.
Dynamic zone providers may publish transport_boundary with the same vocabulary
on their existing trigger_profile and their actual affected_cells.
"""

KINDS = frozenset({"sealed_formation", "spatial_lock"})


def cells(engine, kinds):
    from .zones import terrain_rules
    kinds = frozenset(kinds)
    if not kinds <= KINDS:
        raise ValueError("Unknown transport boundary kind")
    terrain = terrain_rules()["terrains"]
    result = {(int(x), int(y), 0) for row in (engine.battlefield_document or {}).get("map_terrain", [])
              if terrain.get(row.get("terrain"), {}).get("transport_boundary") in kinds
              for x, y in row.get("cells", [])}
    for zone in engine.state.zones.values():
        if zone.active and zone.trigger_profile.get("transport_boundary") in kinds:
            result.update((p.x, p.y, p.z) for p in zone.affected_cells)
    return result


def crosses(engine, actor, path, kinds=KINDS):
    """Whether this physical body's route intersects an explicitly marked boundary."""
    boundaries = cells(engine, kinds)
    return any(set(engine._actor_volume(actor, position)) & boundaries for position in path)
