"""Destructible objects and structures on the map (owner 2026-09-29, task O: "destructible objects and structures per D&D 5.5e
... placeable on the map, attackable, with the abilities whose text damages objects/structures/barriers using them").

What an object is and how damage works on it is combat/object_rules.py (the numbers: combat/rules/objects.json). This plug-in
is everything that touches the fight:

  the map        objects placed on a tabletop map ("map_objects" in the sealed arena, combat/tabletop.py to_battlefield) become
                 RuntimeObjectState records the first time the fight looks (seed), through _update_object, so a saved fight
                 replays them; a blocking one (door, gate, pillar) fills its square, like a wall, until it is destroyed
  Attack an object   a player's Action: one weapon's attacks (Extra Attack included) against an object in reach or range,
                 against its AC. Talents that change what a weapon does to objects are "object_damage" rows (block
                 "object_damage" in combat/rules/feature_blocks.d/sysv2_objects.json): Work-Axe Eye's Proficiency Bonus,
                 Gate-Splitting Blow's extra dice and lower Damage Threshold (one variant of the action per way to pay it),
                 Great Destroyer's double damage, ...
  object_damage  an effect type for a technique's own text ("It takes 40 Force or Necrotic damage, ignoring Resistance and
                 treating Damage Threshold as 0": Crumble Matter, Reduce Structure): aimed at an object it rolls and deals
                 that damage; aimed at a creature it does nothing (that half of the text stays the GM's)
  area techniques   a technique whose own text says objects in its area take its damage ("Objects and ordinary barriers
                 inside take double damage") has an "object_damage" row for that feature: after its effects ran, each object
                 in the area takes the technique's damage roll (an object makes no saving throw: the texts have it "take" the
                 damage, not half), doubled once when the text says so; a row's "dice" gives objects their own printed amount
                 ("Objects ... in the line take 24d10 Ruin damage automatically")
  direct rows    (an attack technique aimed at an object) also take "add_pb": true (Black Trace's Crack) and "after_effects": the
                 ability's own top-level row types to run after the attack at the object, hit or miss (Unbound Trace's price)
Shared helper: ``record_creator`` records projected Banner provenance.
Shared helper: ``deal`` (sky_treading.py and sumo.py: the map object a collision hits takes its damage; still_water.py: a barrier cut on
Heaven Divided Before Sound's line).
Shared helpers ``technique_damage_row`` and ``roll_technique_attack`` are used by
force_second_pass for native object targeting, rather than duplicating the object attack roll.
Shared helper: ``rectangular_footprint`` (object_subjects.geometry: the spiritual-object movement
proxy uses the same explicit dimensions a targeting consumer sees).
"""

from __future__ import annotations

import copy
import re
from typing import Any
from ..gate2_runtime_models import Position, ZoneState
from ..read_queries import invariant_memo
from ..object_geometry import target_cells

from . import effect, hook, stable_subscribers

BLOCK = "object_damage"
SOURCE = "system:battlefield.object"
_AXE_WORDS = ("axe", "hatchet", "francisca", "tomahawk")
CREATED_BY = "created_by"   # component key: the source_definition_id of the ability that put this object on the map


# ------------------------------------------------------------------------------------------------ the map's objects
def rectangular_footprint(obj: Any, *, grid: Any = None) -> Any:
    """The sealed body footprint a map object's explicit dimensions describe, or ``None``.

    Shared by the object_target_cells targeting geometry (:func:`rectangular_cells`) and the
    spiritual-object movement proxy (``object_subjects.geometry``) so a route or destination a
    consumer validates uses the same body the targeting consumer sees. ``grid`` optionally bounds
    the rectangle to the battlefield. Never infers dimensions from kind or size: no explicit
    ``width_cells``/``length_cells`` returns ``None`` and the caller keeps its own default.
    """
    from ..footprints import ActorFootprintDefinition

    component = obj.component or {}
    if "width_cells" not in component and "length_cells" not in component:
        return None
    width, length = component.get("width_cells"), component.get("length_cells")
    rotation = component.get("rotation", 0)
    if (type(width) is not int or type(length) is not int or width < 1 or length < 1
            or type(rotation) is not int or rotation not in (0, 90)):
        raise ValueError("object_target_cells requires positive integer width_cells/length_cells and rotation 0/90")
    if rotation == 90:
        width, length = length, width
    # Bound the allocation before building the footprint. The anchor is northwest
    # at either rotation, with width east and length south, at the object's z.
    if grid is not None and not grid.in_bounds((obj.position.x + width - 1, obj.position.y + length - 1)):
        raise ValueError("object_target_cells rectangle exceeds the battlefield")
    return ActorFootprintDefinition.rectangle(width, length,
        footprint_id=f"footprint:object.{obj.object_id}",
        source_definition_id=f"system:combat.object_footprint:{obj.object_id}")


@hook("object_target_cells", stable=True)
def rectangular_cells(engine: Any, obj: Any) -> tuple[Any, ...] | None:
    """Explicit sealed dimensions only; never infer dimensions from kind/size."""

    footprint = rectangular_footprint(obj, grid=engine.grid)
    if footprint is None:
        return None
    return tuple(Position(x=x, y=y, z=obj.position.z) for x, y in footprint.occupied_cells(obj.position))


def object_id(row: dict[str, Any]) -> str:
    return f"object:map.{int(row['id'])}"


def ignite(engine: Any, object_id: str, source_id: str, actor_id: str) -> None:
    """Evented ignition of an unattended flammable object, shared by runtime engines.

    This records only ignition; it invents no ongoing damage or destruction.
    """
    obj = engine.state.objects.get(object_id)
    if obj is None:
        raise ValueError("typed object target does not exist")
    if not obj.unattended or not obj.flammable:
        raise ValueError("object ignition requires an unattended flammable object")
    if obj.ignited:
        return
    obj.ignited = True
    obj.ignition_source_definition_id = source_id
    obj.ignition_actor_id = actor_id
    obj.ignition_sequence = engine.state.event_sequence + 1
    engine._append_event(
        "OBJECT_IGNITED",
        source_id,
        actor_id=actor_id,
        payload={"object": obj.model_dump(mode="json")},
    )


def created_by(obj: Any) -> str:
    """The source_definition_id of the ability that made this object, when its maker recorded one in
    ``component[CREATED_BY]``; otherwise "". Only the maker knows: the arena's own furniture, and anything put on the
    map by nothing the table tracks, has no maker and returns "".

    This names the ability, not the moment: two casts of one technique leave two objects with the same value, so a
    consumer must not read it as "the object this cast of that ability is creating right now" and offer it as that
    cast's effect. Nothing here records which single activation of an ability made an object, so a consumer that needs
    that distinction has to add it to its own data; see combat/ext/unmaking_forms.py (_answer_damage), which deals the
    printed 5d10 to the creature making the effect and tells the Game Master how to move it to the effect instead.
    """
    return str((getattr(obj, "component", None) or {}).get(CREATED_BY) or "")


def record_creator(component: dict[str, Any] | None, source_id: str) -> dict[str, Any]:
    """The ``component`` to hand ``engine._update_object`` when an ability puts a damageable object of its own on the map,
    stamped with ``source_id`` (a string, so a saved fight keeps it) so ``created_by`` can name that one object's maker.
    Returns a new dict and keeps the caller's own keys; this says who made it, nothing about how it fights.

    Stamping names the ability that made the object. It does not, and cannot, say which one of that ability's several
    uses made it: a reader that needs that distinction has to record its own activation identity alongside this one."""
    return {**(component or {}), CREATED_BY: str(source_id or "")}


def seed(engine: Any) -> None:
    """Create the objects a map placed, once each (idempotent: a destroyed one stays in the fight's state, so it is not
    made again). Evented, so a saved fight replays them. Checked at every event rather than once: a fight loaded from its
    saved state replaces the state after the engine is built, so the first event of the next move finds them missing and
    makes them then (the fight's start makes them itself once "match_start" is a core hook: see the report)."""
    if engine.__dict__.get("_objects_seeding"):
        return
    rows = (getattr(engine, "battlefield_document", None) or {}).get("map_objects") or []
    fresh = [row for row in rows if isinstance(row, dict) and object_id(row) not in engine.state.objects]
    if not fresh:
        return
    from .. import object_rules, zones
    from ..gate2_runtime_models import Position, RuntimeObjectState

    engine.__dict__["_objects_seeding"] = True
    try:
        for row in fresh:
            if not engine.grid.in_bounds((int(row["x"]), int(row["y"]))):
                continue
            numbers = object_rules.stats(row)
            door = object_rules.simple_door_state(row)
            from .object_subjects import validate_profile
            spiritual = validate_profile(row["spiritual_profile"]) if "spiritual_profile" in row else None
            if door is not None:
                numbers["blocks"] = not bool(door["door_open"])
            engine._update_object(RuntimeObjectState(
                object_id=object_id(row), object_kind=numbers["kind"], position=Position(x=int(row["x"]), y=int(row["y"]), z=int(row.get("z", 0))),
                height_ft=row.get("height_ft"),
                unattended=numbers["unattended"], flammable=numbers["flammable"], ac=numbers["ac"], current_hp=numbers["hp"],
                maximum_hp=numbers["hp"], damage_immunities=numbers["immune"], damage_threshold=numbers["threshold"], destroyed=False,
                component={"name": numbers["name"], "material": numbers["material"], "size": numbers["size"], "blocks": numbers["blocks"],
                           "structure": numbers["structure"], "resilient": numbers["resilient"], "vulnerable": list(numbers["vulnerable"]),
                           "resist": list(numbers["resist"]), "artifact": bool(row.get("artifact")), "kind": numbers["kind"],
                           **({"weight_lb": row["weight_lb"]} if type(row.get("weight_lb")) is int and row["weight_lb"] >= 0 else {}),
                           **{key: row[key] for key in ('rotation', 'mount_axis', 'mount_line', 'nudge') if key in row},
                           **{key: row[key] for key in ('fragile', 'temporary_barrier', 'formation_anchor', 'world_scale') if type(row.get(key)) is bool},
                           # An editor row's explicit extents, as documented for
                           # ``object_target_cells``. Only positive integers are forwarded, so an
                           # arena without them keeps its historical single-cell footprint and a
                           # malformed row still raises in ``rectangular_cells`` rather than
                           # silently producing a differently shaped object.
                           **{key: row[key] for key in ('width_cells', 'length_cells')
                              if type(row.get(key)) is int and row[key] >= 1},
                           **({"spiritual_profile": spiritual} if spiritual is not None else {}),
                           **(door or {})}),
                SOURCE, None)
        zones.sync_walls(engine)
    finally:
        engine.__dict__["_objects_seeding"] = False


@hook("match_start")
def _match_start(engine: Any) -> None:
    seed(engine)


@hook("turn_start")
def _turn_start(engine: Any, actor: Any) -> None:
    seed(engine)


@hook("event")
def _event(engine: Any, event_type: str, kwargs: Any) -> None:
    seed(engine)


def blocker_at(engine: Any, position: Any) -> Any | None:
    """The standing object that fills ``position`` (its "blocks"), or None when nothing placed there blocks it (a wall
    or a trunk did). Several objects may share a square (SOL201): only a blocking one stops a creature, so a collision
    there hits that one, never a cushion lying beside it. Ties go to the lowest object id, so it is the same every time."""
    from ..object_geometry import target_cells
    found = [obj for obj in engine.state.objects.values()
             if not obj.destroyed and obj.current_hp is not None and (obj.component or {}).get("blocks")
             and position in target_cells(engine, obj)]
    return min(found, key=lambda obj: obj.object_id) if found else None


@hook("zones")
def blocking_zones(engine: Any) -> list[Any]:
    """A door, gate, pillar or barricade that is still standing fills its square like a wall (combat/zones.py sync_walls)."""
    # Map objects are invariant during pure enumeration, unlike projected actors.
    # Construct and validate each derived wall once; lists stay caller-owned.
    geometry = stable_subscribers('object_target_cells', engine)
    if geometry is None:
        # A custom geometry provider may follow projected actors. Its dependency
        # contract stays authoritative; absent an explicit opt-in, evaluate it.
        return _blocking_zones(engine)
    return list(invariant_memo(engine, ('object_blocking_zones', geometry), lambda: tuple(_blocking_zones(engine))))


def object_occluder(kind):
    """Sight shape of a placed object. Owner ruling 2026-10-23: every object shows a centre plus by default so the
    art stays visible; only presets marked "occluder": "cell" in combat/rules/objects.json (low walls, doors, gates)
    keep full-cell sight. Read from the object preset, never from display text."""
    from ..object_rules import presets
    return presets().get(str(kind or ""), {}).get("occluder", "centerline")


def _blocking_zones(engine: Any) -> list[Any]:
    from .. import zones

    out = []
    for obj in sorted(engine.state.objects.values(), key=lambda row: row.object_id):
        if obj.destroyed or not (obj.component or {}).get("blocks"):
            continue
        out.append(ZoneState(
            zone_id=f"zone:{obj.object_id}", source_definition_id=SOURCE, owner_id=zones.MAP_OWNER, center=obj.position, radius_cells=0,
            affected_cells=target_cells(engine, obj), concentration_link=False, duration_rounds=None, created_round=0,
            trigger_profile={"kind": zones.KIND, "name": (obj.component or {}).get("name") or "Object", "object": obj.object_id,
                             "wall": {"blocks_movement": True, "occluder": object_occluder((obj.component or {}).get("kind")),
                                      "sight_class": "object",
                                      **({"cover": obj.component["cover"]} if "width_cells" in obj.component
                                         and "length_cells" in obj.component
                                         and obj.component.get("cover") in ("half", "three_quarters") else {}),
                                      **({"height_ft": obj.height_ft, "base_altitude_ft": obj.position.z * 5} if obj.height_ft is not None else {})},
                             "follows_owner": False, "shape": "painted", "size_ft": 5, "triggers": [],
                             "talents": [], "inside": [], "map": True, "numbers": {"save_dc": 10, "pb": 2, "cl": 1}}))
    return out


# ------------------------------------------------------------------------------------------------ the rows and actions
@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    # keeps_compiling: these talents are also actions (Unmake Barrier, Falling Star) or modifiers (Iron Meridian Body) that
    # compile as they always did; listing them here must not make the compiler treat them as done and skip them.
    return [{**row, **{key: value for key, value in spec.items() if key not in {"block", "resource", "why"}},
             "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1), "keeps_compiling": True}]


def _rows(engine: Any, actor_id: str, on: str) -> list[dict[str, Any]]:
    from ..typed_reactions import _rows as rows

    return [row for row in rows(engine, actor_id, BLOCK) if row.get("on") == on]


def _group(row: Any, typed: dict[str, Any], attack: dict[str, Any]) -> str:
    if attack.get("attack_kind") == "unarmed":
        return "unarmed"
    text = f"{row.display_name} {typed.get('source') or ''}".lower()
    return "axe" if typed.get("sphere") == "tianxia.sphere.axes" or any(word in text for word in _AXE_WORDS) else "weapon"


@hook("compile_actions")
def object_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    best: dict[str, tuple[int, str, Any, dict[str, Any], dict[str, Any]]] = {}
    for row in info.get("actions") or []:
        typed = (row.parameters or {}).get("typed") or {}
        economy = getattr(row.economy, "value", row.economy)
        attack = next((item for item in typed.get("effects") or [] if isinstance(item, dict) and item.get("type") == "attack"), None)
        if (economy == "ACTION" and row.target_kind == "HOSTILE_ENTITY" and typed.get("weapon") and attack is not None
                and not typed.get("variant_of") and not str(typed.get("source") or "").startswith("improvised")
                and "#" not in row.source_definition_id and not (row.parameters or {}).get("requires_condition")):
            value = (int(row.parameters.get("expected_damage") or 0), row.source_definition_id, row, typed, attack)
            group = _group(row, typed, attack)
            if group not in best or value[:2] > best[group][:2]:
                best[group] = value
    unarmed_talent = any(row.get("block") == BLOCK and row.get("on") == "attack" and row.get("weapon") == "unarmed" for row in info.get("passives") or [])
    if not best or (unarmed_talent and "unarmed" not in best):  # nothing to swing, or a talent for fists: an Unarmed Strike (2024: 1 + Strength modifier, no die)
        from ..factory_compiler import unarmed_strike_weapon

        strength = int((info.get("mods") or {}).get("STR") or 0)
        weapon = unarmed_strike_weapon(strength)
        typed = {"weapon": weapon, "numbers": {**(info.get("numbers") or {}), "attack_bonus": int(info.get("pb") or 2) + strength}}
        best["unarmed"] = (0, "", None, typed, {"count": 1})
    out = []
    ways = [row for row in info.get("passives") or [] if row.get("block") == BLOCK and row.get("on") == "attack" and row.get("ways")]
    for group, (_value, _id, row, typed, attack) in sorted(best.items()):
        name = (row.display_name[:-len(" attack")] if row is not None and row.display_name.endswith(" attack")
                else (row.display_name if row is not None else "Unarmed Strike"))
        base = {"typed": {"effects": [{"type": "object_attack", "count": int((attack or {}).get("count") or 1)}],
                          "object_weapon": dict(typed["weapon"]), "object_weapon_group": group, "object_melee": not typed.get("range_ft"), "mundane": typed.get("mundane"),
                          "numbers": dict(typed.get("numbers") or {}), "duration": {"kind": "instant"}, "riders": [],
                          "source": "object_attack", **({"sphere": typed["sphere"]} if typed.get("sphere") else {})},
                "expected_damage": 0, "player_only": True, "object_attack": True,
                "description": f"Use your Action to make {name} attacks against a reachable object or structure, applying its defenses and damage rules."}
        reach = int((row.range_ft if row is not None else None) or 5)
        label = "Attack an object" if len(best) == 1 else f"Attack an object: {name}"
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.object_attack.{group}", display_name=label, owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="OBJECT", range_ft=reach, parameters=base))
        for rider in ways:
            if rider.get("weapon") not in (None, group):
                continue
            slug = re.sub(r"\W+", "_", str(rider["feature_id"]).lower())
            paid = []
            for way, amount in rider["ways"]:
                way = info.get("primary") or "qi" if way == "cp" else way  # "1 CP" is the character's own primary pool
                if way in RESOURCE_IDS and way not in {taken for taken, _cost in paid}:
                    paid.append((way, amount))
            for way, amount in paid:
                parameters = {**base, "typed": {**base["typed"], "object_rider": rider["feature_id"]}}
                out.append(ActionDefinition(
                    source_definition_id=f"action:typed.{info['short']}.object_attack.{group}+{slug}.{way}", display_name=f"{label} + {rider.get('label')} ({amount} {way.replace('_', ' ')})",
                    owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="OBJECT", range_ft=reach,
                    costs=((RESOURCE_IDS[way], int(amount)),), parameters=parameters))
    # An area technique the engine offers only where the area catches a creature (a door between you and the foe stops that)
    # gets a player-only sibling aimed at any square whose area reaches an object it damages: "Heaven-Crushing Palm (at an object)".
    techniques = [row for row in info.get("passives") or [] if row.get("block") == BLOCK and row.get("on") == "technique"]
    for row in info.get("actions") or []:
        typed = (row.parameters or {}).get("typed") or {}
        area = typed.get("area") or {}
        source = str(typed.get("source") or "")
        if (row.target_kind != "CELL" or (row.parameters or {}).get("any_cell") or not area.get("size_ft") or (area.get("shape") or "sphere") == "wall"
                or typed.get("weapon") is not None or not any(source == mine["feature_id"] or source.startswith(mine["feature_id"] + "#") for mine in techniques)):
            continue
        out.append(row.model_copy(update={"source_definition_id": row.source_definition_id + "#object", "display_name": f"{row.display_name} (at an object)",
                                          "parameters": {**(row.parameters or {}), "any_cell": True, "player_only": True, "object_area": True, "expected_damage": 0}}))
    # Explicit source-backed object delivery preserves this option's own attack
    # and effects. No opt-in means no extra action or change to legacy delivery.
    for row in info.get('actions') or []:
        typed = (row.parameters or {}).get('typed') or {}
        attack = next((e for e in typed.get('effects') or [] if e.get('type') == 'attack'), {})
        if attack.get('object_target') == 'unattended' and row.target_kind != 'OBJECT':
            out.append(row.model_copy(update={
                'source_definition_id': row.source_definition_id + '#object',
                'display_name': row.display_name + ' (at an object)', 'target_kind': 'OBJECT'}))
    return out or None


def _object_effects(action: Any) -> list[dict[str, Any]]:
    return [item for item in ((action.parameters or {}).get("typed") or {}).get("effects") or []
            if isinstance(item, dict) and item.get("type") in ("object_attack", "object_damage")]


def _source(action: Any) -> str:
    return str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or "")


def _direct_row(engine: Any, actor: Any, action: Any) -> dict[str, Any] | None:
    """The character's row saying this attack technique may be aimed at an object (Unmake Barrier, Heaven-Emptying Lance)."""
    source = _source(action)
    typed = (action.parameters or {}).get('typed') or {}
    attack = next((e for e in typed.get('effects') or [] if e.get('type') == 'attack'), {})
    if (action.owner_id == actor.entity_id and action.source_definition_id in actor.action_ids
            and attack.get('object_target') == 'unattended'):
        return {'typed_activation': True, 'object_target': 'unattended', 'needs': ['unattended'],
                'on_hit_effects': list(attack.get('object_on_hit_effects') or [])}
    return next((row for row in _rows(engine, actor.entity_id, "direct") if source and (source == row["feature_id"] or source.startswith(row["feature_id"] + "#"))), None)


@hook("object_targets")
def object_targets(engine: Any, actor: Any, action: Any) -> list[str]:
    from ..object_rules import has_tag
    if not _object_effects(action) and _direct_row(engine, actor, action) is None:
        return []
    direct = _direct_row(engine, actor, action) or {}
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and obj.ac is not None and obj.current_hp is not None
            and (direct.get('object_target') != 'unattended' or has_tag(obj, 'unattended'))]


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """An action that only ever damages an object (Crumble Matter) is not offered against a creature; an area technique's
    "(at an object)" sibling is offered at the squares whose area reaches an object it damages."""
    if (getattr(action, "parameters", None) or {}).get("object_area"):
        aim = getattr(candidate, "destination", None)
        typed = action.parameters.get("typed") or {}
        row = _technique_row(engine, actor, typed)
        return bool(aim is not None and row is not None and _struck(engine, actor.position, aim, typed.get("area") or {}, row))
    effects = [eff for eff in ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
               if eff.get("type") != "menu"]
    if effects and all(isinstance(item, dict) and item.get("type") in ("object_attack", "object_damage") for item in effects):
        if not (getattr(candidate, "metadata", None) or {}).get("object_target"):
            return False
        obj = engine.state.objects.get(next(iter(getattr(candidate, "target_ids", None) or ()), None))
        # An object the ability cannot touch (Crumble Matter and an artifact) is not offered, rather than offered and refused.
        return None if obj is None or all(_why_not(obj, item) is None for item in effects if item.get("type") == "object_damage") else False
    return None


# ------------------------------------------------------------------------------------------------ damage
def deal(engine: Any, actor: Any, obj: Any, packets: list[tuple[int, str]], source: str, *, area_scope_resolved: bool = False, **modifiers: Any) -> dict[str, Any]:
    """One instance of damage on one object, worked out (combat/object_rules.py work_out), taken off its hit points and
    recorded in one OBJECT_UPDATED event (combat/history_feed.py tells it in plain words). A destroyed object opens its
    square. Returns work_out's answer plus {"destroyed": bool}.
    ``area_scope_resolved`` is transient admission context: callers may set it
    only after filtering every packet with the shared per-payload area policy
    (including authoritative overrides) for this recipient. Admission hooks
    retain other guards, such as once-per-activation shared pools. It is not a
    damage modifier and is never persisted."""
    from .. import object_rules, zones
    from ..gate2_runtime_models import RuntimeObjectState

    from . import run as run_hooks
    from .sound_objects import consume_exposure

    from . import run_strict, CheckpointError
    admitted = run_strict("object_damage_admission", engine, actor, obj, packets, source,
                          area_scope_resolved=area_scope_resolved)
    if any(type(answer) is not bool for answer in admitted):
        raise CheckpointError("object_damage_admission must return bool or None")
    if any(answer is False for answer in admitted):
        return {"total": 0, "packets": [], "notes": [], "destroyed": bool(obj.destroyed)}
    if False in run_strict("object_operation_gate", engine, actor, obj, "break", source, getattr(engine, "_active_intent", None)):
        return {**object_rules.work_out([], obj), "destroyed": False}
    before_exposure = obj
    obj, bypass = consume_exposure(engine, obj, packets)
    for answer in run_hooks("object_packets", engine, actor, obj, packets, source):  # e.g. Harmonic Weakness's Sound Die
        obj, packets = answer["object"], [*packets, *answer.get("packets", [])]
    # A Resistance that is not the object's own material (Stand Against the Calamity's aura over the built world).
    # Collected as the ordinary defense rows so object_rules.work_out applies it with the same halving, rounding,
    # note and suppression as any other resistance; this is the object half of the creature damage_defenses hook.
    defense_rows = [row for group in run_hooks("object_damage_defenses", engine, actor, obj, packets, source)
                    for row in (group or [])]
    granted = {str(kind).upper() for row in defense_rows if row.get("kind", "resistance") == "resistance"
               for kind in (row.get("damage_types") or ())}
    vulnerable = {str(kind).upper() for row in defense_rows if row.get("kind") == "vulnerability"
                  for kind in (row.get("damage_types") or ())}
    if vulnerable:
        modifiers = {**modifiers, "extra_vulnerable_types": tuple(sorted(vulnerable))}
    if granted and not modifiers.get("ignore_resistance"):
        modifiers = {**modifiers, "extra_resist_types": tuple(sorted(granted))}
    result = object_rules.work_out(packets, obj, ignore_resistance_types=bypass, **modifiers)
    taken = int(result["total"])
    if taken == 0:
        obj = before_exposure  # immunity/threshold/reduction prevented it taking any damage
    left = max(0, int(obj.current_hp) - taken)
    # General destruction protection preserves HP without turning it into immunity.
    from . import run_strict
    for floor in run_strict('object_hp_floor', engine, actor, obj, taken, source):
        if floor is None:continue
        if type(floor) is not int or not 0 <= floor <= int(obj.maximum_hp or 0):
            raise ValueError('object_hp_floor must return a bounded integer')
        left = max(left, min(int(obj.current_hp), floor))
    if left > max(0, int(obj.current_hp) - taken):
        taken = int(obj.current_hp) - left
        result = {**result, 'total':taken, 'notes':[*result['notes'], 'Destruction protection preserves the object']}
    destroyed = taken > 0 and left == 0
    opens = destroyed and bool((obj.component or {}).get("blocks"))
    after = RuntimeObjectState.model_validate(obj.model_copy(update={"current_hp": left, "destroyed": destroyed or bool(obj.destroyed)}).model_dump(mode="json"))
    engine.state.objects[after.object_id] = after
    engine._append_event("OBJECT_UPDATED", source, actor_id=actor.entity_id, target_ids=(after.object_id,), payload={
        "object": after.model_dump(mode="json"),
        "damage": {"taken": taken, "kinds": ", ".join(sorted({kind.lower() for amount, kind in result["packets"] if amount})), "notes": list(result["notes"]),
                   "opened": opens}})
    if opens:
        zones.sync_walls(engine)
    return {**result, "destroyed": destroyed}


def _mine(row: dict[str, Any], obj: Any, actor: Any, typed: dict[str, Any]) -> bool:
    """Whether a talent's row applies to this weapon (axe, unarmed, any melee) and this object (its tags: "wooden", ...)."""
    from .. import object_rules

    wants = row.get("weapon")
    if wants == "melee":
        if not typed.get("object_melee"):
            return False
    elif wants is not None and wants != typed.get("object_weapon_group"):
        return False
    if row.get("needs_focus") and not int((actor.resources or {}).get("resource:core.martial_focus", 0)):
        return False
    if row.get("needs_condition") and not any(c.condition_id == row["needs_condition"] for c in actor.conditions.values()):
        return False  # only while a timed state is on (rider lane C14: Mountain-Felling Axe Body's form)
    if any(object_rules.has_tag(obj, tag) or (obj.component or {}).get(tag)
           for tag in row.get("forbids") or []):
        return False
    return all(object_rules.has_tag(obj, tag) for tag in row.get("needs") or [])


@effect("object_attack")
def object_attack(ctx: Any, eff: dict[str, Any]) -> None:
    """Never run through run_effects (the object candidate goes to object_action); a creature aimed at gets nothing."""
    ctx.rider("An object attack needs an object to aim at.")


def _why_not(obj: Any, eff: dict[str, Any]) -> str | None:
    """Why an object_damage effect cannot touch this object ("needs" / "forbids" are the ability's own words, as tags)."""
    from .. import object_rules

    for tag in eff.get("needs") or []:
        if not object_rules.has_tag(obj, tag):
            return f"needs a {tag} object; {object_rules.label(obj)} is not."
    for tag in eff.get("forbids") or []:
        if object_rules.has_tag(obj, tag) or (obj.component or {}).get(tag):
            return f"cannot damage {object_rules.label(obj)} ({tag})."
    return None


@effect("object_damage")
def object_damage(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import object_rules, typed_executor

    obj = ctx.damage_cache.get("_object")
    if obj is None:
        return  # aimed at a creature: the object clause of the text has nothing to act on
    obj = ctx.engine.state.objects[obj.object_id]
    if obj.destroyed:
        return
    why = _why_not(obj, eff)
    if why:
        ctx.rider(f"{ctx.action.display_name} {why}")
        return
    natural = 0
    if eff.get("attack_roll"):
        # "Make a Sound Cultivation Attack against the object's AC" (riders lane 5, 2026-09-29: Shatter Vessel, Bell That Breaks the
        # Formation): the ability's own attack roll against the object, then its damage on a hit (a natural 20 rolls the dice twice).
        hit, natural = attack_object_roll(ctx, obj, 0)
        if not hit:
            return
    amount, kind = typed_executor._damage_roll(ctx, eff)
    if natural == 20:
        from ..gate2_runtime_models import DiceSpec

        dice = ctx.dice(typed_executor._effect_dice(ctx, eff))
        if isinstance(dice, DiceSpec):
            amount += typed_executor._roll(ctx, DiceSpec(count=dice.count, sides=dice.sides, modifier=0), "DAMAGE")
    if eff.get("add_pb_for") and any(object_rules.has_tag(obj, tag) for tag in eff["add_pb_for"]):
        amount += int(ctx.numbers.get("pb") or 0)
    result = deal(ctx.engine, ctx.actor, obj, [(int(amount), str(kind).upper())], ctx.source, ignore_threshold=bool(eff.get("ignore_threshold")),
                  ignore_resistance=bool(eff.get("ignore_resistance")), multiplier=int(eff.get("multiplier") or 1))
    burst = eff.get("on_destroy")
    if burst and result.get("destroyed"):
        _burst(ctx, obj, burst)


def _burst(ctx: Any, obj: Any, burst: dict[str, Any]) -> None:
    """What happens around an object the ability just destroyed ("If this damage destroys the object ... creatures within 5 feet
    make Dexterity saving throws or take 1d8 Thunder damage from the burst", Shatter Vessel): the burst's own effects, run once for
    every creature within its radius of any occupied object cell (friend or foe: the text says "creatures")."""
    from .. import typed_executor
    from ..object_geometry import target_cells

    reach = int(burst.get("radius_ft") or 5)
    cells = target_cells(ctx.engine, obj)
    for creature in sorted(ctx.engine.state.actors.values(), key=lambda row: row.entity_id):
        if not creature.active or min(ctx.engine._distance_actor_to_cell(creature, cell) for cell in cells) > reach:
            continue
        inner = typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, ctx.damage_cache)
        typed_executor.run_effects(inner, copy.deepcopy(burst.get("effects") or []))


@hook("object_action")
def object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    from .. import typed_executor

    typed = dict((action.parameters or {}).get("typed") or {})
    typed["numbers"] = dict(typed.get("numbers") or {})
    ctx = typed_executor.Context(engine, actor, action, intent, typed, [], None)
    ctx.damage_cache["_object"] = obj
    if (action.parameters or {}).get("object_attack"):
        _attack(ctx, obj)
        return True
    effects = [item for item in typed.get("effects") or [] if isinstance(item, dict) and item.get("type") == "object_damage"]
    if not effects:
        direct = _direct_row(engine, actor, action)
        if direct is None:
            return None
        # Opt-in for a technique's object delivery: preserve its activation
        # gates, preparations and completion without changing legacy rows.
        if direct.get("typed_activation"):
            from . import run_strict

            # Acceptance consumes shared activation limits even if a start veto
            # or counter later cancels delivery, just as creature techniques do.
            run_strict("technique_accepted", engine, actor, action)
            if any(value is True for value in run_strict("technique_start", engine, actor, action)):
                return True
            if not typed_executor.activation_reactions(ctx):
                return True  # canceled; Action, costs and preparations stay spent
            wanted = set(direct.get("before_effects") or ())
            typed_executor.run_effects(ctx, [copy.deepcopy(eff) for eff in typed.get("effects") or []
                                            if eff.get("type") in wanted])
        _direct(ctx, obj, direct)
        _direct_after(ctx, direct)
        if direct.get("typed_activation"):
            run_strict("technique_used", ctx)
        return True
    menus = [item for item in typed.get('effects') or [] if item.get('type') == 'menu']
    typed_executor.run_effects(ctx, [*menus, *effects])
    riders = [" ".join(str(text).split()) for text in typed.get("riders") or [] if str(text).strip()]
    if riders:
        ctx.rider(" / ".join(riders)[:1200])
    return True


def attack_roll_bonus(ctx: Any) -> int:
    """The attacker's shared flat modifier for one roll against an inanimate defense.

    The printed technique's own ``attack_bonus`` plus every ``attack_bonus`` subscriber
    (a Riding sign, Jinxed Name, Turning Wheel, Exhaustion, a forged penalty). The general
    seam for any roll made against an object, a wall section or another inanimate defense:
    a route that rolled from ``ctx.numbers`` alone silently dropped every rider whose
    printed text modifies the attack roll, and left consumable riders (Jinxed Name's
    once-per-round penalty) unspent for a later attack. Mirrors the native fold in
    ``combat/typed_executor``'s attack path; no subscriber means the printed bonus exactly.
    """
    from . import run

    bonus = int(ctx.numbers.get("attack_bonus") or 0)
    return bonus + sum(int(value) for value in run("attack_bonus", ctx, ctx.actor) if isinstance(value, int))


def prepare_damage_dice(ctx: Any, dice: Any, effect: dict[str, Any] | None = None,
                        kinds: list[str] | None = None) -> Any:
    """Fold the shared damage-roll modifiers into one packet's dice before it is rolled.

    The general seam for a route that builds and rolls its own damage instead of letting
    ``combat/typed_executor`` dispatch it: every ``damage_roll_bonus`` subscriber (Turning
    Wheel's attack face, a printed "add your Proficiency Bonus to one damage roll") reaches
    this packet too, at the same fold point the native path uses -- after dice selection,
    before defenses. The caller still owns its own shaping (a confirmed-hit extra die, native
    critical doubling), so this returns the same dice untouched when nothing is folded and
    never re-queries a subscriber the caller has already applied.
    """
    from ..typed_executor import _damage_dice

    return _damage_dice(ctx, dice, effect, kinds or [])


def attack_object_roll(ctx: Any, obj: Any, index: int = 0) -> tuple[bool, int]:
    """One attack roll against the object's AC (a natural 20 hits, a natural 1 misses; cover does not apply to an object).
    Shared by this module and death_decay.py (Rotting Grasp).
    Recorded as ATTACK_ROLLED, which the fight feed reads as "... vs Wooden door (AC 15): ... Hit/Miss."""
    engine, actor = ctx.engine, ctx.actor
    bonus = attack_roll_bonus(ctx)
    roll = engine.roller.d20(
        modifier=bonus,
        actor_id=actor.entity_id,
        reason=f'ATTACK:{ctx.source}:object:{index + 1}',
        mode=engine.direct_attack_mode(actor),
    )
    engine._record_roll(roll)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or roll.total >= int(obj.ac))
    engine._append_event("ATTACK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                         payload={**roll.model_dump(mode="json"), "modified_total": int(roll.total), "target_ac": int(obj.ac), "cover_bonus": 0,
                                  "provisional_hit": hit, "object_id": obj.object_id})
    return hit, natural


def _attack(ctx: Any, obj: Any) -> None:
    from ..gate2_runtime_models import DiceSpec
    from . import run_strict

    engine, actor, typed = ctx.engine, ctx.actor, ctx.typed
    weapon = typed.get("object_weapon") or {}
    rows = [row for row in _rows(engine, actor.entity_id, "attack") if not row.get("ways") or row["feature_id"] == typed.get("object_rider")]
    for index in range(int((typed.get("effects") or [{}])[0].get("count") or 1)):
        obj = engine.state.objects[obj.object_id]
        if obj.destroyed:
            return
        hit, natural = attack_object_roll(ctx, obj, index)
        if not hit:
            continue  # the ATTACK_ROLLED line already reads "... vs Wooden door (AC 15): ... Miss."
        # A cost paid for one attack (Gate-Splitting Blow) is that first attack's; the others swing as usual.
        mine = [row for row in rows if _mine(row, obj, actor, typed) and (not row.get("ways") or index == 0)]
        dice = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
        attack_kind = str(typed.get("object_weapon_group") or "weapon")
        bonus = sum(int(value) for value in run_strict("object_hit_roll_bonus", ctx, obj, attack_kind, dice)
                    if isinstance(value, int))
        if bonus:
            dice = dice.model_copy(update={"modifier": int(dice.modifier) + bonus})
        kind = str(weapon.get("damage_type") or "BLUDGEONING").upper()
        critical = natural == 20
        main = engine.roller.roll(dice, actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object:{index + 1}", critical=critical,
                                  fixed_damage=weapon.get("fixed_damage"))
        engine._record_roll(main)
        packets = [(int(main.total) + sum(int(row.get("add_pb") and row.get("pb") or 0) for row in mine), kind)]
        for row in mine:
            extra = None
            if row.get("add_weapon_die") and weapon.get("damage"):
                extra = DiceSpec(count=int(row["add_weapon_die"]), sides=int(weapon["damage"]["sides"]), modifier=0)
            elif row.get("add_dice"):
                extra = DiceSpec(count=int(row["add_dice"]["count"]), sides=int(row["add_dice"]["sides"]), modifier=0)
            if extra is not None:
                roll_extra = engine.roller.roll(extra, actor_id=actor.entity_id, reason=f"DAMAGE:{row['feature_id']}:object:{index + 1}", critical=critical)
                engine._record_roll(roll_extra)
                packets.append((int(roll_extra.total), str(row.get("damage_type") or kind).upper()))
        reduce = sum(int(row.get("reduce_threshold") or 0) + (int(row["pb"]) if row.get("reduce_threshold_pb") else 0) for row in mine)
        deal(engine, actor, obj, packets, ctx.source, ignore_threshold=any(row.get("ignore_threshold") for row in mine), reduce_threshold=reduce,
             ignore_resistance=any(row.get("ignore_resistance") for row in mine), multiplier=max([1, *(int(row.get("multiplier") or 1) for row in mine)]))
        run_strict("object_hit", ctx, obj, attack_kind)


def _direct(ctx: Any, obj: Any, row: dict[str, Any]) -> None:
    """An attack technique aimed at an object (Unmake Barrier, Heaven-Emptying Lance): its own attack roll against the
    object's AC, then the damage of its "on hit" (a critical hit rolls the dice twice, 2024 PHB); the creature-only
    parts (a saving throw, a condition) have nothing to act on. The row's own words: ignore_threshold, double_for."""
    from .. import object_rules, typed_executor
    from ..gate2_runtime_models import DiceSpec

    attack = next((item for item in ctx.typed.get("effects") or [] if isinstance(item, dict) and item.get("type") == "attack"), None)
    damage = _first_damage((attack or {}).get("on_hit"))
    if damage is None:
        return
    hit, natural = attack_object_roll(ctx, obj, 0)
    if not hit:
        return
    if row.get("typed_activation"):
        from . import run_strict

        kinds = typed_executor.damage_choices(damage)
        for replacement in run_strict("attack_damage_types", ctx, attack, kinds):
            if replacement:
                kinds = list(replacement)
        damage = {**damage, "damage_types": kinds}
    amount, kind = typed_executor._damage_roll(ctx, damage)
    if natural == 20:
        dice = ctx.dice(typed_executor._effect_dice(ctx, damage))
        if isinstance(dice, DiceSpec):
            amount += typed_executor._roll(ctx, DiceSpec(count=dice.count, sides=dice.sides, modifier=0), "DAMAGE")
    double = row.get("double") or any(object_rules.has_tag(obj, tag) for tag in row.get("double_for") or [])
    if row.get("add_pb_for") and any(object_rules.has_tag(obj, tag) for tag in row["add_pb_for"]):
        amount += int(ctx.numbers.get("pb") or 0)  # Resonant Note: "add your Proficiency Bonus to the damage" (riders lane 5, 2026-09-29)
    if row.get("add_pb"):
        amount += int(ctx.numbers.get("pb") or 0)  # Black Trace's Crack: "If the target is an object ... additional Ruin damage equal to your PB"
    deal(ctx.engine, ctx.actor, obj, [(int(amount), str(kind).upper())], ctx.source, ignore_threshold=bool(row.get("ignore_threshold")),
         ignore_resistance=bool(row.get("ignore_resistance")), multiplier=2 if double else 1)
    typed_executor.run_effects(ctx, [{**eff, 'recipient_object_id': obj.object_id} for eff in (attack or {}).get("on_hit") or []
                                    if eff.get("type") in {'sound_object_resonance', *(row.get('on_hit_effects') or [])}])


def _direct_after(ctx: Any, row: dict[str, Any]) -> None:
    """A direct row's "after_effects": the ability's own top-level rows of those types, run once the attack at the object resolved,
    hit or miss (Unbound Trace: "After the attack resolves, whether it hits or misses, choose one" price, rider lane C5)."""
    from .. import typed_executor

    wanted = set(row.get("after_effects") or ())
    if wanted:
        typed_executor.run_effects(ctx, [copy.deepcopy(eff) for eff in ctx.typed.get("effects") or [] if isinstance(eff, dict) and eff.get("type") in wanted])


# ------------------------------------------------------------------------------------------------ area techniques
def _first_damage(effects: Any) -> dict[str, Any] | None:
    for item in effects or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "damage":
            return item
        for key in ("on_fail", "on_success", "on_hit", "effects"):
            found = _first_damage(item.get(key)) if isinstance(item.get(key), list) else None
            if found is not None:
                return found
    return None


def area_reaches(engine: Any, vertex: Any, aim: Any, obj: Any, area: dict[str, Any]) -> bool:
    """Shared by piercing_areas and this module: whether an area reaches an object: inside its shape, with no other blocking square in the way. The general rule
    ("the wall's own squares are not in it", typed_executor._clear_line) keeps an area out of a wall's square; an object that
    fills its square is the very thing the area strikes, so only the squares before it count."""
    from .. import typed_executor

    from ..object_geometry import target_cells
    cells = target_cells(engine, obj)
    own_cells = {(cell.x, cell.y) for cell in cells}
    blocked = getattr(engine.grid, "blocked", None) or set()
    origin = vertex if (area.get("shape") or "sphere") in ("line", "cone") else aim
    return any(typed_executor.in_area(engine, vertex, aim, cell, {**area, "spreads": True})
               and not any(p in blocked and p not in own_cells for p in engine.grid.ray_cells(origin, cell)[1:-1])
               for cell in cells)


def _technique_row(engine: Any, actor: Any, typed: dict[str, Any]) -> dict[str, Any] | None:
    """The character's row saying this area technique damages objects (the feature block "object_damage", on "technique")."""
    source = str(typed.get("source") or "")
    return next((row for row in _rows(engine, actor.entity_id, "technique") if source and (source == row["feature_id"] or source.startswith(row["feature_id"] + "#"))), None)


def _struck(engine: Any, vertex: Any, aim: Any, area: dict[str, Any], row: dict[str, Any]) -> list[Any]:
    from .. import object_rules

    return [obj for obj in sorted(engine.state.objects.values(), key=lambda item: item.object_id)
            if not obj.destroyed and obj.ac is not None and obj.current_hp is not None and area_reaches(engine, vertex, aim, obj, area)
            and all(object_rules.has_tag(obj, tag) for tag in row.get("needs") or [])
            and (not row.get("needs_any") or any(object_rules.has_tag(obj, tag) for tag in row["needs_any"]))
            and not any(object_rules.has_tag(obj, tag) for tag in row.get("forbids") or [])]


@hook("technique_used")
def technique_used(ctx: Any) -> None:
    """Objects in a technique's area take its damage when its own text says so (an "object_damage" row for that feature)."""
    from .. import object_rules, typed_executor

    if ctx.damage_cache.get('_ordered_objects'):
        return  # an owning ordered-area effect already resolved these objects
    typed, engine, actor = ctx.typed or {}, ctx.engine, ctx.actor
    area = typed.get("area") or {}
    if typed.get("weapon") is not None or not area.get("size_ft") or (area.get("shape") or "sphere") == "wall" or not engine.state.objects:
        return
    row = _technique_row(engine, actor, typed)
    if row is None:
        return
    packets = [value for key, value in ctx.damage_cache.items() if isinstance(key, int) and isinstance(value, tuple) and len(value) == 2
               and isinstance(value[0], int) and isinstance(value[1], str)]
    if row.get("dice"):  # its own number for objects ("Objects ... in the line take 24d10 Ruin damage automatically", rider lane C5)
        from ..gate2_runtime_models import DiceSpec

        first = _first_damage(typed.get("effects")) or {}
        rolled = engine.roller.roll(DiceSpec(count=int(row["dice"]["count"]), sides=int(row["dice"]["sides"]), modifier=0),
                                    actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object", critical=False)
        engine._record_roll(rolled)
        packets = [(int(rolled.total), str((first.get("damage_types") or ["force"])[0]).upper())]
    if not packets and row.get("packet_types"):
        first = _first_damage(typed.get("effects")) or {}
        declared = {str(kind).upper() for kind in first.get("damage_types") or []}
        allowed = {str(kind).upper() for kind in row["packet_types"]}
        if declared and declared.isdisjoint(allowed):
            return  # no qualifying object packet: do not draw an unused damage roll
    if not packets:  # nobody in the area rolled it (an empty yard, or every creature saved): the objects still take the damage
        first = _first_damage(typed.get("effects"))
        if first is None:
            return
        amount, kind = typed_executor._damage_roll(ctx, first)
        packets = [(int(amount), str(kind))]
    if row.get("packet_types"):
        allowed_types = {str(kind).upper() for kind in row["packet_types"]}
        packets = [(amount, kind) for amount, kind in packets if str(kind).upper() in allowed_types]
        if not packets:
            return
    aim = ctx.damage_cache.get("_checkpoint_aim") or actor.position
    first = _first_damage(typed.get("effects")) or {}
    sides = int((typed_executor._effect_dice(ctx, first) or {}).get("sides") or 0) if first else 0
    # Every object the blast reaches is found before any of them takes damage: a wall in front shields what is behind it,
    # and a door the blast breaks does not open the way for the same blast.
    struck = _struck(engine, actor.position, aim, area, row)
    for obj in struck:
        each = [(int(amount), str(kind).upper()) for amount, kind in packets]
        if row.get("extra_die") and sides >= 2 and (not row.get("extra_die_for") or any(object_rules.has_tag(obj, tag) for tag in row["extra_die_for"])):
            from ..gate2_runtime_models import DiceSpec

            extra = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object", critical=False)
            engine._record_roll(extra)
            each.append((int(extra.total), each[0][1]))
        double = row.get("double") and (not row.get("double_for") or any(object_rules.has_tag(obj, tag) for tag in row["double_for"]))
        deal(engine, actor, obj, each, ctx.source, ignore_threshold=bool(row.get("ignore_threshold")), ignore_resistance=bool(row.get("ignore_resistance")),
             multiplier=2 if double else 1)


def technique_damage_row(effects):
    """First ordinary damage row in a technique's selected effect tree."""
    return _first_damage(effects)


def roll_technique_attack(ctx, obj, index=0):
    """Use the shared object AC/d20/event path; return (hit, natural result)."""
    return attack_object_roll(ctx, obj, index)
