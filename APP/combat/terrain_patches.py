"""Generic named terrain creation and duration transitions.

Shared by combat/ext/docket_terrain.terrain_patch, zones.expire_owned_zones,
and combat/ext/magma_crust.shape (one-square cooling with its own duration).
create_patch stores only JSON rules/numbers and emits the ordinary zone event.
A transition reuses the surviving cells, owner, source and geometry, but builds
the destination terrain's own hazards and difficulty rather than copying them.
"""
from __future__ import annotations

import copy
from typing import Any

from .gate2_runtime_models import ZoneState


def create_patch(engine: Any, *, owner_id: str, source: str, center: Any,
                 radius_ft: int, cells: Any, effect: dict[str, Any],
                 numbers: dict[str, Any], effects=(), ctx=None) -> ZoneState:
    from . import zones
    from .ext.terrain_damage import own_damage_rows, terrain_triggers

    name = str(effect.get("terrain") or "").lower()
    terrain = (zones.terrain_rules().get("terrains") or {}).get(name) or {}
    zone_id = f"zone:typed:{owner_id}:{engine.state.event_sequence + 1}"
    label = str(effect.get("name") or (name.title() if name else "Difficult terrain"))
    ability_damage = (own_damage_rows(effects, ctx=ctx)
                      if (terrain.get("enter_start") or {}).get("from_ability") or effect.get("becomes") else [])
    profile = {
        "kind": zones.KIND, "name": label, "terrain": [name] if terrain else [],
        "difficult": effect.get("difficult") or terrain.get("difficult"),
        "obscured": terrain.get("obscured"),
        "color": terrain.get("color") or zones.terrain_rules().get("default_color"),
        "follows_owner": False, "shape": "sphere" if radius_ft else "square",
        "size_ft": radius_ft or 5,
        "triggers": terrain_triggers(zone_id, label, terrain, ability_damage),
        "move_through": copy.deepcopy(terrain.get("move_through")),
        "talents": [], "inside": [],
        "visual": {"material": terrain.get("material") or "cracked"},
        "numbers": dict(numbers),
    }
    if effect.get("becomes"):
        profile["becomes"] = copy.deepcopy(effect["becomes"])
        # A destination with from_ability needs the original ability tree, too.
        profile["terrain_effects"] = copy.deepcopy(ability_damage)
    duration = effect.get("duration") or {}
    zone = ZoneState(
        zone_id=zone_id, source_definition_id=source, owner_id=owner_id,
        center=center, radius_cells=radius_ft // engine.grid.square_size_ft,
        affected_cells=tuple(cells), concentration_link=False,
        duration_rounds=zones._duration_rounds(duration) if duration else None,
        created_round=engine.state.round_number, trigger_profile=profile,
    )
    engine.state.zones[zone_id] = zone
    engine._append_event("ZONE_CREATED", source, actor_id=owner_id,
                         payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, source)
    return zone
