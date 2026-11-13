"""Source Lock / World-Nail Source Seal, using native zones, objects and checks.

A section seal gates physical passage on either side, including its creator.
An object seal gates opening, moving or breaking that object. Checks use the
attempting creature's Strength (Athletics), never a saving throw. Success permits
that attempt; it does not dispel the seal. Source-Heaven Sealing Scripture offers
an explicit optional extra-CP variant. Surface material comes from mechanical
terrain; cosmetic floor art is not material evidence. Unknown surfaces remain
unavailable. World-Nail's discretionary hazard-delay clause remains text.

Shared helper mineral_surface_points supplies source_origin with positively
recorded terrain surfaces and intact mineral object occupied cells, at their
actual altitude. It does not apply the seal-specific protected-object rules:
choosing an origin is not sealing an object. Cosmetic floor art is not evidence.
mineral_surface remains the terrain-only predicate for section seals.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note

LOCK = "tianxia.talent.source.source_lock"
NAIL = "tianxia.talent.source.world_nail_source_seal"
SCRIPTURE = "tianxia.talent.source.source_heaven_sealing_scripture"
KINDS = {LOCK, NAIL}
MINERALS = {"stone", "rock", "obsidian", "crystal", "jade", "ore", "mineral", "sand", "earth", "dirt", "soil", "gravel", "rubble", "scree", "brick", "tile", "marble", "basalt", "metal", "iron", "steel", "copper", "silver", "gold", "mithral", "adamantine"}


def source(action: Any) -> str:
    return str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or "")


def mineral_surface(engine: Any, point: Any) -> bool:
    """Positive evidence at this altitude from a physical named terrain only."""
    from .. import zones
    for zone in zones.typed_zones(engine):
        if not zone.active or point.z != zone.center.z or not zone.trigger_profile.get("terrain"):
            continue
        if not any(c.x == point.x and c.y == point.y for c in zone.affected_cells):
            continue
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower()
        if material in MINERALS:
            return True
    return False


def mineral_surface_points(engine: Any) -> tuple[Any, ...]:
    """Recorded surface anchors, deduplicated by x/y/z; never infer bare floors.

    A terrain surface lies at its zone center's altitude over its affected cells.
    Objects supply their public occupied-cell geometry, with each cell's altitude.
    No unknown face/height/contact geometry is extrapolated from an anchor.
    Visibility and printed range are the consuming action provider's responsibility.
    """
    from .. import zones
    from ..gate2_runtime_models import Position
    from ..object_geometry import target_cells
    points = set()
    for zone in zones.typed_zones(engine):
        if (zone.active and zone.trigger_profile.get("terrain")
                and str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower() in MINERALS):
            points.update((cell.x, cell.y, zone.center.z) for cell in zone.affected_cells)
    for obj in engine.state.objects.values():
        if not obj.destroyed and str((obj.component or {}).get("material") or "").lower() in MINERALS:
            points.update((cell.x, cell.y, cell.z) for cell in target_cells(engine, obj))
    return tuple(Position(x=x, y=y, z=z) for x, y, z in sorted(points))


def eligible_object(engine: Any, obj: Any, *, closed: bool = True) -> bool:
    from ..object_geometry import target_cells
    component = obj.component or {}
    return (not obj.destroyed and obj.unattended is True
            and str(component.get("material") or "").lower() in MINERALS
            and str(component.get("size") or "").lower() in {"tiny", "small", "medium"}
            and len(target_cells(engine, obj)) == 1
            and not any(component.get(k) for k in ("magical", "artifact", "domain", "formation", "secret", "worn", "carried", "created_by"))
            and (not closed or not component.get("door_open")))


@effect("source_lock")
def place(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    name = ctx.action.display_name
    minutes = int(eff.get("minutes") or 1)
    zone = zones.create(ctx, {"name": name, "shape": "cube", "size_ft": 5,
        "duration": {"kind": "minutes", "amount": minutes},
        "profile": {"source_lock": True, "dc": int(ctx.numbers["save_dc"]),
                    **({"object_id": str(eff["object_id"])} if eff.get("object_id") else {})}})
    if zone is not None:
        note(ctx.engine, ctx.source, ctx.actor,
             f"{name}: sealed for {minutes} minute{'s' if minutes != 1 else ''}. Opening, breaking or passing through requires a Strength (Athletics) check against DC {ctx.numbers['save_dc']}.")


@effect("source_lock_extension")
def extension(ctx: Any, eff: dict[str, Any]) -> None:
    """Ownership marker; compile_actions supplies the optional paid variant."""
    return None


@hook("compile_actions")
def buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .cp_pools import build_pool
    pool = build_pool(info)
    if pool is None:
        return None
    out = []
    for feature in sorted(KINDS & set(info["owned_ids"])):
        mechanic = info["mechanics"][feature]
        name = mechanic["name"]
        for extended in ([False, True] if feature == LOCK and SCRIPTURE in info["owned_ids"] else [False]):
            minutes = 10 if extended else 1
            cost = (1 if feature == LOCK else 4) + int(extended)
            label = name + (" + Source-Heaven Sealing Scripture" if extended else "")
            for object_target in (False, True):
                out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{feature}#seal.{minutes}.{'object' if object_target else 'surface'}",
                    display_name=label + (": object" if object_target else ": surface"), owner_id=info["actor_id"], economy=EconomyKind.ACTION,
                    resolution_kind="TYPED", target_kind="OBJECT" if object_target else "CELL", range_ft=5 if feature == LOCK else 30,
                    costs=((pool, cost),), parameters={"any_cell": True, "source_lock_target": "object" if object_target else "surface",
                        "expected_damage": 0, "player_only": object_target,
                        "description": f"Seal one {'unattended mineral object or closed stone or metal door' if object_target else '5-foot section of mineral surface'} for {minutes} minute{'s' if minutes != 1 else ''}. Creatures must pass a Strength (Athletics) check against your Source Save DC to open, break or pass through it. Costs {cost} cultivation point{'s' if cost != 1 else ''} and your action.",
                        "typed": {"source": feature, "sphere": "tianxia.sphere.source", "numbers": dict(info["numbers"]),
                            "effects": [{"type": "source_lock", "minutes": minutes}], "riders": list(mechanic.get("riders") or []), "duration": {"kind": "instant"}}}))
    return out or None


@hook("object_targets")
def targets(engine: Any, actor: Any, action: Any) -> list[str] | None:
    if (action.parameters or {}).get("source_lock_target") != "object":
        return None
    return [o.object_id for o in engine.state.objects.values() if eligible_object(engine, o, closed=source(action) == LOCK)]


@hook("candidate_allowed")
def allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if source(action) not in KINDS:
        return None
    mode = (action.parameters or {}).get("source_lock_target")
    if mode == "object":
        obj = engine.state.objects.get(next(iter(candidate.target_ids), ""))
        return obj is not None and eligible_object(engine, obj, closed=source(action) == LOCK)
    if mode == "surface":
        return candidate.destination is not None and mineral_surface(engine, candidate.destination)
    return False  # reviewed declaration is replaced by these exact target branches


@hook("object_action")
def seal_object(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    if (action.parameters or {}).get("source_lock_target") != "object":
        return None
    if not eligible_object(engine, obj, closed=source(action) == LOCK):
        raise ValueError("This seal needs an unattended ordinary mineral object no larger than a 5-foot cube, or a closed stone or metal door.")
    from dataclasses import replace
    from .spirit_traditions import context
    ctx = context(engine, actor, action, [], intent=intent)
    ctx = replace(ctx, intent=intent.model_copy(update={"destination": obj.position}))
    row = ctx.typed["effects"][0]
    place(ctx, {**row, "object_id": obj.object_id})
    return True


def seals(engine: Any):
    from .. import zones
    for zone in zones.typed_zones(engine):
        if zone.active and (zone.trigger_profile.get("profile") or {}).get("source_lock"):
            yield zone


def check(engine: Any, actor: Any, zone: Any, intent: Any) -> bool:
    from ..typed_executor import resolve_opposed_check
    from .spirit_traditions import context
    from .needle import numbers_of
    action = engine.action_catalog[zone.source_definition_id]
    # The check belongs to the attempting creature; the seal's stored DC belongs to its caster.
    ctx = context(engine, actor, action, [actor], numbers=numbers_of(engine, actor), intent=intent)
    dc = int(zone.trigger_profile["profile"]["dc"])
    result = resolve_opposed_check(ctx, actor, {"kind": "check", "ability": "STR", "skill": "Athletics"}, {"kind": "dc", "dc": dc})
    note(engine, zone.source_definition_id, actor,
         f"{action.display_name}: {actor.display_name}'s Strength (Athletics) check is {result.actor.total} against DC {dc}; {'the attempt succeeds' if result.success else 'the seal stops the attempt'}.")
    return result.success


@hook("movement_attempt")
@hook("forced_movement_attempt")
def passage(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    for zone in seals(engine):
        object_id = zone.trigger_profile["profile"].get("object_id")
        obj = engine.state.objects.get(object_id) if object_id else None
        if object_id and (obj is None or (obj.component or {}).get("kind") != "door"):
            continue
        # A door remains sealed after a successful opening check. Passage
        # through that doorway is a distinct attempt, at its current position.
        center = obj.position if obj is not None else zone.center
        cells = {(center.x, center.y)} if obj is not None else {(c.x, c.y) for c in zone.affected_cells}
        def inside(point: Any) -> bool:
            return point.z == center.z and bool(cells.intersection(engine._actor_cells(mover, point)))
        if not inside(nxt) and not inside(previous):
            continue
        # A successful traversal includes leaving the same section, not a second
        # check for the second half of one movement intent.
        key = f"source_lock_pass|{zone.zone_id}"
        attempt = str(getattr(intent, "intent_id", "") or "")
        if attempt and mover.turn_flags.get(key) == attempt:
            continue
        if not check(engine, mover, zone, intent):
            return {"stop": True, "source_id": zone.source_definition_id, "label": "The source seal stops passage."}
        if attempt:
            mover.turn_flags[key] = attempt
    return None


@hook("object_operation_gate")
def object_gate(engine: Any, actor: Any, obj: Any, operation: str, source_id: str, intent: Any) -> bool | None:
    if operation not in {"open", "move", "break"} or actor is None:
        return None
    for zone in seals(engine):
        if zone.trigger_profile["profile"].get("object_id") == obj.object_id and not check(engine, actor, zone, intent):
            return False
    return None


@hook("event")
def destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "OBJECT_UPDATED":
        return
    from .. import zones
    for zone in list(seals(engine)):
        object_id = zone.trigger_profile["profile"].get("object_id")
        obj = engine.state.objects.get(object_id)
        if obj is not None and obj.destroyed:
            zones.remove(engine, zone, "SEALED_TARGET_DESTROYED")
