"""Ground made by a hit or a kill, and auras that ride with a fighter (docket 2026-09-28; owner 2026-09-27: "Terrain made by
a hit or a kill (Hungry Flame, Clean Break, Heaven-Shaking Batter) and always-on auras (Yokozuna Presence) -- need engine
hooks").

Effects (for typed rows, e.g. authority/typed_mechanics/reviewed_final.d/docket.json):
  terrain_patch   {"terrain": "<terrain.json name>" | None, "difficult": "all" | "hostile" | None, "radius_ft": 0 | N,
                   "duration": {...}, "center": {"x": int, "y": int} (optional)}: ground at the target's space, or an
                  explicit effect-owned map center -- its own square(s), or a round patch of that
                  radius centered on it (not through walls) -- for the duration (whole fight when none is printed).
                  Heaven-Shaking Batter: "create a 10-foot-radius patch of difficult terrain centered on the target";
                  Hungry Flame: "create one 5-foot square of Fire Terrain in its space until the start of your next turn".
  if_target       {"condition": "kindled", "effects": [...]}: only against a target that has that condition ("When
                  Ignite hits a Kindled target").
  damage_then     {"damage": {<damage effect>}, "if_dropped": [...]}: that damage, then the effects if this damage took
                  the target from above 0 hit points to 0 ("If this damage reduces a creature to 0 HP").

Auras: a feature_blocks row {"block": "aura", "radius_ft", "difficult": "hostile", "while_stance": "<stance name>" |
"while_active": true, "ally_cover": {...}} is an area centered on its owner that moves with it, worked out from where the
owner stands whenever areas are read (combat/zones.py typed_zones, hook "zones") -- never stored, so a replayed fight has
it exactly the same. Yokozuna Presence: "While Rooted Stance is active: Hostile creatures treat spaces within 10 feet of
you as difficult terrain ... An ally gains Half Cover against a ranged attack when it is within 5 feet of you and the line
from attacker to ally crosses your space" (hook "cover"). Nine-Star Incarnation's for its minute.

Rooted Stance (Sumo) is a stance (combat/stances.py) that ends when its holder willingly moves more than half its Speed
in one turn or falls Unconscious.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

AURA_ACTIVE = "condition:typed.aura_active"   # data: feature_id, until_round -- an aura switched on by using its ability
ROOTED = "condition:typed.stance.rooted_stance"


# ------------------------------------------------------------------------------------------------ ground from a blow
def _duration(duration: dict[str, Any] | None) -> int | None:
    from .. import zones

    if not duration:
        return None  # nothing printed: it stays for the fight
    return zones._duration_rounds(duration)


@effect("terrain_patch")
def terrain_patch(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    from ..gate2_runtime_models import ZoneState

    engine, target = ctx.engine, ctx.target
    if target is None:
        return
    from ..gate2_runtime_models import Position

    center = Position.model_validate(eff["center"]) if eff.get("center") else target.position
    rules = zones.terrain_rules().get("terrains") or {}
    name = str(eff.get("terrain") or "").lower()
    terrain = rules.get(name) or {}
    radius = int(eff.get("radius_ft") or 0)
    if radius:
        cells = zones._cells(engine, center, {"shape": "sphere", "size_ft": radius})
    else:
        cells = tuple(engine.grid.footprint_cells(center, engine._footprint(target.entity_id)))
        from ..gate2_runtime_models import Position

        cells = tuple(Position(x=cell[0], y=cell[1]) if isinstance(cell, tuple) else cell for cell in cells)
    zone_id = f"zone:typed:{ctx.actor.entity_id}:{engine.state.event_sequence + 1}"
    label = str(eff.get("name") or (name.title() if name else "Difficult terrain"))
    zone = ZoneState(
        zone_id=zone_id, source_definition_id=ctx.source, owner_id=ctx.actor.entity_id, center=center,
        radius_cells=radius // engine.grid.square_size_ft, affected_cells=cells, concentration_link=False,
        duration_rounds=_duration(eff.get("duration")), created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "name": label, "terrain": [name] if terrain else [],
                         "difficult": eff.get("difficult") or ("all" if terrain.get("difficult") else None),
                         "obscured": terrain.get("obscured"), "color": terrain.get("color") or zones.terrain_rules().get("default_color"),
                         "follows_owner": False, "shape": "sphere" if radius else "square", "size_ft": radius or 5,
                         "triggers": _terrain_triggers(zone_id, terrain, ctx), "move_through": copy.deepcopy(terrain.get("move_through")),
                         "talents": [], "inside": [], "visual": {"material": terrain.get("material") or "cracked"},
                         "numbers": dict(ctx.numbers)})
    engine.state.zones[zone_id] = zone
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id, payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, ctx.source)


def _terrain_triggers(zone_id: str, terrain: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
    """A named terrain's own "entering or starting its turn there makes a save" (Fire Terrain), as combat/factory_compiler.py
    _zone_spec gives it; a rule that takes its damage from the ability that made it keeps to the ability's printed dice."""
    rule = terrain.get("enter_start")
    if not rule or rule.get("from_ability"):
        return []
    return [{"id": f"{zone_id}:terrain", "name": "terrain", "on": ["enter", "start"], "who": rule.get("who") or "hostile",
             "effects": [{"type": "save", "ability": rule.get("ability") or "DEX", "on_fail": copy.deepcopy(rule.get("on_fail") or []),
                          "on_success": copy.deepcopy(rule.get("on_success") or [])}]}]


@effect("if_target")
def if_target(ctx: Any, eff: dict[str, Any]) -> None:
    target = ctx.target
    wanted = f"condition:typed.{str(eff.get('condition') or '').lower()}"
    if target is None or not any(condition.condition_id == wanted for condition in target.conditions.values()):
        return
    from .. import typed_executor

    typed_executor.run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("damage_then")
def damage_then(ctx: Any, eff: dict[str, Any]) -> None:
    target = ctx.target
    if target is None or not target.active:
        return
    from .. import typed_executor

    before = int(target.current_hp)
    typed_executor.run_effects(ctx, [copy.deepcopy(eff.get("damage") or {})])
    if before > 0 and int(target.current_hp) <= 0:
        typed_executor.run_effects(ctx, copy.deepcopy(eff.get("if_dropped") or []))


# ------------------------------------------------------------------------------------------------ auras
@hook("compile_block")
def aura_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "aura":
        return None
    return [{**row, "block": "aura", "radius_ft": int(spec.get("radius_ft") or 10), "difficult": spec.get("difficult"),
             "while_stance": spec.get("while_stance"), "while_active": bool(spec.get("while_active")),
             "ally_cover": copy.deepcopy(spec.get("ally_cover")), "name": spec.get("name") or row.get("name")}]


def _aura_rows(engine: Any) -> list[tuple[str, dict[str, Any]]]:
    cached = engine.__dict__.get("_aura_rows")
    if cached is None:
        cached = [(actor_id, row) for actor_id, rows in sorted((getattr(engine, "typed_passive_rows", {}) or {}).items())
                  for row in rows if row.get("block") == "aura"]
        engine.__dict__["_aura_rows"] = cached
    return cached


def _on(engine: Any, owner: Any, row: dict[str, Any]) -> bool:
    if not owner.active:
        return False
    if row.get("while_stance"):
        from .. import stances

        slug = "condition:typed.stance." + stances._slug(row["while_stance"])
        if not any(condition.condition_id == slug for condition in owner.conditions.values()):
            return False
    if row.get("while_active"):
        return any(condition.condition_id == AURA_ACTIVE and (condition.data or {}).get("feature_id") == row.get("feature_id")
                   for condition in owner.conditions.values())
    return True


@hook("zones")
def aura_zones(engine: Any) -> list[Any]:
    rows = _aura_rows(engine)
    if not rows:
        return []
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState

    cache = engine.__dict__.setdefault("_aura_zone_cache", {})
    out = []
    for actor_id, row in rows:
        owner = engine.state.actors.get(actor_id)
        if owner is None or not _on(engine, owner, row):
            continue
        key = (actor_id, row.get("feature_id"), owner.position.x, owner.position.y)
        zone = cache.get(key)
        if zone is None:
            reach = int(row["radius_ft"])
            cells = tuple(Position(x=x, y=y) for y in range(engine.grid.height) for x in range(engine.grid.width)
                          if engine._distance_actor_to_cell(owner, Position(x=x, y=y)) <= reach)
            zone = ZoneState(
                zone_id=f"zone:aura:{actor_id}:{row.get('feature_id')}", source_definition_id=f"passive:{row.get('feature_id')}", owner_id=actor_id,
                center=owner.position, radius_cells=reach // engine.grid.square_size_ft, affected_cells=cells, concentration_link=False,
                duration_rounds=None, created_round=0,
                trigger_profile={"kind": zones.KIND, "name": str(row.get("name") or "Aura"), "terrain": [], "difficult": row.get("difficult"),
                                 "obscured": None, "color": zones.terrain_rules().get("default_color"), "follows_owner": True, "shape": "emanation",
                                 "size_ft": reach, "triggers": [], "move_through": None, "talents": [], "inside": [], "aura": True,
                                 "visual": {"material": "aura"}, "numbers": {}})
            cache[key] = zone
        out.append(zone)
    return out


@hook("cover")
def aura_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Yokozuna Presence: "An ally gains Half Cover against a ranged attack when it is within 5 feet of you and the line
    from attacker to ally crosses your space" (checked for the ranged attacks the engine gives cover against)."""
    best = None
    for actor_id, row in _aura_rows(engine):
        cover = row.get("ally_cover") or {}
        guard = engine.state.actors.get(actor_id)
        if not cover or guard is None or guard.entity_id == target.entity_id or guard.team_id != target.team_id or not _on(engine, guard, row):
            continue
        if engine._distance_actor_to_actor(guard, target) > int(cover.get("within_ft") or 5):
            continue
        space = {(cell.x, cell.y) if hasattr(cell, "x") else tuple(cell) for cell in engine._actor_cells(guard)}
        if space & set(engine.grid.ray_cells(attacker.position, target.position)[1:-1]):
            best = max(best or 0, int(cover.get("bonus") or 2))
    return best


@hook("technique_used")
def aura_switched_on(ctx: Any) -> None:
    """An aura that lasts for its ability's duration (Nine-Star Incarnation's minute)."""
    typed = ctx.typed or {}
    record = str(typed.get("option_of") or typed.get("source") or "")
    rows = [row for actor_id, row in _aura_rows(ctx.engine) if actor_id == ctx.actor.entity_id and row.get("while_active") and row.get("feature_id") == record]
    if not rows:
        return
    from .effect_durations import until_round

    until = until_round(ctx.engine, dict(typed.get("duration") or {}))
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == AURA_ACTIVE and (condition.data or {}).get("feature_id") == record:
            ctx.actor.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    ctx.engine._apply_condition(ctx.actor, AURA_ACTIVE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"feature_id": record, "label": f"{rows[0].get('name')} (aura)", **({"until_round": until} if until else {})})


@hook("nominal_slot_boundary")
def nominal_aura_expires(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        aura_expires(engine, actor)


@hook("turn_start")
def aura_expires(engine: Any, actor: Any) -> None:
    for iid, condition in list(actor.conditions.items()):
        until = (condition.data or {}).get("until_round")
        if condition.condition_id == AURA_ACTIVE and until is not None and engine.state.round_number >= int(until):
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", "aura", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "ended"})


# ------------------------------------------------------------------------------------------------ Rooted Stance ends
@hook("event")
def rooted_stance_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"It lasts until you ... willingly move more than half your Speed during one turn, become Unconscious" (Rooted
    Stance's Normalized Procedure: forced movement does not count)."""
    if event_type not in ("MOVEMENT_COMMITTED", "CONDITION_APPLIED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "") if event_type == "MOVEMENT_COMMITTED" else \
        engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is None or not any(condition.condition_id == ROOTED for condition in actor.conditions.values()):
        return
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED":
        if payload.get("condition_id") == "condition:typed.unconscious":
            engine._remove_condition(actor, ROOTED, "passive:rooted_stance")
        return
    if payload.get("forced") or payload.get("dragged_by"):
        return
    moved = max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
    total = int(actor.turn_flags.get("rooted_moved_ft") or 0) + moved
    actor.turn_flags["rooted_moved_ft"] = total
    if total > engine._effective_speed(actor) // 2:
        engine._remove_condition(actor, ROOTED, "passive:rooted_stance")
