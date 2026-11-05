"""The Flower sphere's Fragrance as an area on the table (docket 2026-09-28; owner 2026-09-28: "Dreamscape base typed as
passive; no 'Fragrance' base exists -- fix both so their area talents work"). The base abilities themselves come from
authority/typed_mechanics/base_ability_sources.json; their talents shape the area like Darkness's (combat/zones.py). The
Fragrance core rules add:

  "you may maintain only one Fragrance at a time"      making a new one ends the others it has
  "a Fragrance may be moved up to 10 feet as a Bonus Action"   "Move Fragrance" (a square within 10 feet of it)
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FRAGRANCE = "FLOWERS_BASE_FRAGRANCE"


def _fragrances(engine: Any, actor: Any) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.owner_id == actor.entity_id and zone.zone_id.startswith("zone:typed:")
            and (zone.trigger_profile.get("name") or "") == "Fragrance" and not zone.trigger_profile.get("wall")]


@hook("technique_used")
def one_fragrance(ctx: Any) -> None:
    typed = ctx.typed or {}
    if str(typed.get("option_of") or typed.get("source") or "") != FRAGRANCE:
        return
    from .. import zones

    rows = sorted(_fragrances(ctx.engine, ctx.actor), key=lambda zone: int(zone.zone_id.rsplit(":", 1)[-1]))
    for zone in rows[:-1]:  # the one just made is the newest
        zones.remove(ctx.engine, zone, "REPLACED")


@hook("compile_actions")
def move_fragrance(info: dict[str, Any]) -> list[Any] | None:
    if FRAGRANCE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.move_fragrance", display_name="Move Fragrance", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=120,
        parameters={"typed": {"effects": [{"type": "move_fragrance", "max_ft": 10,
                                           "evidence": "A Fragrance may be moved up to 10 feet as a Bonus Action."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": FRAGRANCE},
                    "expected_damage": 0, "player_only": True, "any_cell": True, "move_fragrance": True})]


@hook('button_description')
def move_fragrance_description(row: dict[str, Any]) -> str | None:
    if not (row.get('parameters') or {}).get('move_fragrance'):
        return None
    return ("Move Fragrance\nAction Type: Bonus Action\nCost: None\n"
            "Move one of your existing Fragrance areas up to 10 feet. Its remaining duration continues.")


@hook("candidate_allowed")
def fragrance_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("move_fragrance"):
        return None
    aim = getattr(candidate, "destination", None)
    rows = _fragrances(engine, actor)
    if aim is None or not rows or all(engine.grid.distance_ft(zone.center, aim) > 10 or zone.center == aim for zone in rows):
        return False
    return None


@effect("move_fragrance")
def move_fragrance_effect(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones

    engine, aim = ctx.engine, getattr(ctx.intent, "destination", None)
    rows = _fragrances(engine, ctx.actor)
    if aim is None or not rows:
        ctx.rider("No Fragrance of yours to move.")
        return
    zone = min(rows, key=lambda row: (engine.grid.distance_ft(row.center, aim), row.zone_id))
    if engine.grid.distance_ft(zone.center, aim) > int(eff.get("max_ft") or 10):
        ctx.rider("A Fragrance moves at most 10 feet.")
        return
    zone.center = aim
    zone.affected_cells = zones._cells(engine, aim, {"size_ft": zone.trigger_profile.get("size_ft"), "shape": zone.trigger_profile.get("shape"),
                                                      "spreads": zone.trigger_profile.get("spreads")})
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, ctx.source)
