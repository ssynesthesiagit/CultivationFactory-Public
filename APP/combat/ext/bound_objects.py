"""Objects an effect makes and depends on: prisons, shells, cages, shelters (rider lane C12, 2026-09-30 -- shared helper).

Many printed effects make an object with its own numbers and tie the effect to it: "The shell is also an object with AC 12 +
your Proficiency Bonus and Hit Points equal to 10 + twice your Cultivation Level. If the shell is destroyed, the effect ends"
(Ice Coffin), Thousand-Facet Prison, Void Prison, Glass Prison, Glass Coffin Without Death, Stone-Lung Shelter. Objects
already exist on the table (RuntimeObjectState, combat/object_rules.py, "Attack an object" in combat/ext/objects.py); what
was missing was one shared way for a typed ability to say which effect the object guards. This module is that helper; any
plug-in may call ``place`` directly, typed data uses the ``bound_object`` effect.

Typed row (put it right after the condition row or zone row it guards, inside the same save branch):

  {"type": "bound_object", "name": "Ice Coffin shell", "material": "ice", "ac": "12+pb", "hp": "10+2*cl",
   "guards": ["restrained"],              condition names (typed conditions) on the held creature this activation just
                                          applied; the newest instance of each, from this user and this ability
   "guards_zone": false,                  true: the area this activation just made (the newest of this user and ability)
   "native_lifecycle": true,              opt in to native state_event cleanup; missing keeps the old Gate4 lifecycle
   "at": "holder",                        "holder" (the held creature's space), "zone" (the area's centre), "self"
   "resist": ["FORCE"], "vulnerable": ["FIRE"], "immune": [...]   besides the Poison/Psychic immunity every object has
   "on_destroyed": [typed rows]}          run as the user against the held creature when the object is destroyed
                                          (Glass Prison: "the target is freed and takes Piercing damage equal to your PB")

Formulas use the user's numbers: whole numbers, "pb", "half_pb" (rounded down), "cl", "save_dc", "key_mod", joined with "+"
and "*" ("20+3*cl", "15+half_pb").

Lifecycle (both directions are evented, so a saved fight replays them):
  destroyed first    any damage that brings the object to 0 HP (Attack an object, an area that damages objects, ...) ends
                     exactly the guarded condition instances and areas, runs ``on_destroyed``, and says so in the log;
                     the held creature's freedom is reported to combat/ext/hold_escapes.py (``destroyer``: who broke it)
  effect ends first  when none of the guarded instances/areas is left (a successful repeat save, Concentration lost,
                     expiry), the object is removed (destroyed, no damage), so nothing is left standing on the map

The object is unattended, never blocks its square (the held creature stands in it) and is a legal target of "Attack an
object" for anyone who can reach it -- the held creature included, as the printed prisons allow. Nothing here runs for a
creature or ability that has no ``bound_object`` row: the event hook returns at once when the fight has no bound object.
Stored data is strings and integers only.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, note

KEY = "bound"
SOURCE = "system:bound_object"
_TERM = re.compile(r"\d+|pb|half_pb|cl|save_dc|key_mod")


def formula(text: Any, numbers: dict[str, Any]) -> int | None:
    """"12+pb", "10+2*cl", "save_dc", "10*pb" with the user's numbers; None when the text is not such a formula."""
    if text is None:
        return None
    if isinstance(text, int) and not isinstance(text, bool):
        return text
    total = 0
    for term in str(text).replace(" ", "").lower().split("+"):
        value = 1
        for factor in term.split("*"):
            if not _TERM.fullmatch(factor or ""):
                return None
            if factor == "half_pb":  # "half your Proficiency Bonus, rounded down" (the Chains sphere's Chain Object AC)
                value *= int(numbers.get("pb") or 0) // 2
            else:
                value *= int(factor) if factor.isdigit() else int(numbers.get(factor) or 0)
        total += value
    return total


def _condition_id(name: str) -> str:
    name = str(name).strip()
    return name if name.startswith("condition:") else f"condition:typed.{name.lower()}"


def bound(obj: Any) -> dict[str, Any] | None:
    """The guarded-effect record of a bound object, or None for any other object."""
    component = getattr(obj, "component", None) or {}
    record = component.get(KEY)
    return record if isinstance(record, dict) else None


def _newest_instances(holder: Any, names: list[str], source: str, owner_id: str) -> list[str]:
    found = []
    for name in names:
        wanted = _condition_id(name)
        rows = [(int(c.applied_sequence or 0), iid) for iid, c in holder.conditions.items()
                if c.condition_id == wanted and c.source_definition_id == source and c.source_actor_id == owner_id]
        if rows:
            found.append(max(rows)[1])
    return found


def _newest_zone(engine: Any, source: str, owner_id: str) -> Any | None:
    zones = [zone for zone in engine.state.zones.values()
             if zone.active and zone.source_definition_id == source and zone.owner_id == owner_id]
    return max(zones, key=lambda zone: (int(zone.created_round or 0), zone.zone_id)) if zones else None


def place(ctx: Any, spec: dict[str, Any], *, holder: Any = None, instance_ids: list[str] = (), zone_ids: list[str] = (),
          position: Any = None) -> Any | None:
    """Make one bound object for ``spec`` (the typed row's shape) guarding the given condition instances on ``holder`` and
    the given areas. Returns the object, or None when the printed numbers are missing or nothing is guarded."""
    from .. import object_rules
    from ..gate2_runtime_models import RuntimeObjectState

    numbers = dict(ctx.numbers)
    ac, hp = formula(spec.get("ac"), numbers), formula(spec.get("hp"), numbers)
    if ac is None or hp is None or hp <= 0 or not (instance_ids or zone_ids) or position is None:
        return None
    from .durability import creation_bonus
    hp += creation_bonus(ctx, str(spec.get("creation_kind") or spec.get("kind") or "object"))

    from . import run_strict
    for bonus in run_strict("bound_object_bonuses", ctx, spec):
        if bonus is None:
            continue
        if not isinstance(bonus, dict) or set(bonus) - {"ac", "hp"} or any(
                type(value) is not int or value < 0 for value in bonus.values()):
            raise ValueError("bound_object_bonuses requires nonnegative integer ac/hp bonuses")
        ac += bonus.get("ac", 0)
        hp += bonus.get("hp", 0)
    engine = ctx.engine
    name = str(spec.get("name") or "Prison")
    immune = sorted({str(kind).upper() for kind in [*object_rules.rules().get("immune", []), *(spec.get("immune") or [])]})
    keep = {key: int(numbers[key]) for key in ("pb", "cl", "save_dc", "key_mod") if isinstance(numbers.get(key), int)}
    record = {"holder": getattr(holder, "entity_id", "") or "", "owner": ctx.actor.entity_id, "source": ctx.source,
              "conditions": sorted(instance_ids), "zones": sorted(zone_ids), "numbers": keep,
              "on_destroyed": list(spec.get("on_destroyed") or [])}
    if spec.get("native_lifecycle"):
        record["native_lifecycle"] = 1
    object_id = f"object:bound.{engine.state.event_sequence + 1}"
    obj = RuntimeObjectState(object_id=object_id, object_kind="BOUND_" + re.sub(r"\W+", "_", str(spec.get("kind") or "prison")).upper(),
                             position=position, unattended=True, flammable=bool(spec.get("flammable")), ac=ac, current_hp=hp,
                             maximum_hp=hp, damage_immunities=tuple(immune), damage_threshold=None, destroyed=False,
                             component={"name": name, "material": str(spec.get("material") or "magical"), "size": "medium",
                                        "blocks": False, "structure": False, "resilient": False, "artifact": False,
                                        "kind": "bound", "resist": sorted({str(k).upper() for k in spec.get("resist") or []}),
                                        "vulnerable": sorted({str(k).upper() for k in spec.get("vulnerable") or []}), KEY: record})
    engine._update_object(obj, ctx.source, ctx.actor.entity_id)
    note(engine, ctx.source, ctx.actor, f"{name}: an object with AC {ac} and {hp} hit points. Any creature that can reach it "
         f"(the one held inside too) can attack it; destroying it ends the effect.", targets=[holder] if holder is not None else ())
    return obj


@effect("bound_object")
def bound_object(ctx: Any, row: dict[str, Any]) -> None:
    names = [str(name) for name in row.get("guards") or []]
    at = str(row.get("at") or ("zone" if row.get("guards_zone") and not names else "holder"))
    zone = _newest_zone(ctx.engine, ctx.source, ctx.actor.entity_id) if row.get("guards_zone") else None
    zone_ids = [zone.zone_id] if zone is not None else []
    holders = [subject for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)) if subject is not None] if names else []
    if not names:
        place(ctx, row, zone_ids=zone_ids, position=zone.center if (zone is not None and at == "zone") else ctx.actor.position)
        return
    for holder in holders:
        instance_ids = _newest_instances(holder, names, ctx.source, ctx.actor.entity_id)
        if not instance_ids:
            continue  # it saved, or an immunity kept the condition off: no object
        position = {"holder": holder.position, "self": ctx.actor.position}.get(at, zone.center if zone is not None else holder.position)
        place(ctx, row, holder=holder, instance_ids=instance_ids, zone_ids=zone_ids, position=position)


def _guarded_left(engine: Any, record: dict[str, Any]) -> bool:
    holder = engine.state.actors.get(record.get("holder") or "")
    conditions = [iid for iid in record.get("conditions") or [] if holder is not None and iid in holder.conditions]
    zones = [zid for zid in record.get("zones") or [] if zid in engine.state.zones and engine.state.zones[zid].active]
    return bool(conditions or zones)


def _end_guarded(engine: Any, obj: Any, record: dict[str, Any]) -> None:
    """The object was destroyed: end exactly what it guarded, then its printed consequence."""
    from .. import typed_executor, zones
    from .condition_ownership import remove_instance

    from .hold_escapes import escaped

    holder = engine.state.actors.get(record.get("holder") or "")
    owner = engine.state.actors.get(record.get("owner") or "")
    name = str((obj.component or {}).get("name") or "The object")
    freed = [holder.conditions[iid] for iid in record.get("conditions") or [] if holder is not None and iid in holder.conditions]
    for iid in record.get("conditions") or []:
        if holder is not None and iid in holder.conditions:
            remove_instance(engine, holder, iid, SOURCE)
    for zone_id in record.get("zones") or []:
        zone = engine.state.zones.get(zone_id)
        if zone is not None and zone.active:
            zones.remove(engine, zone, "OBJECT_DESTROYED")
    note(engine, record.get("source") or SOURCE, owner or record.get("owner"),
         f"{name} is destroyed, so its effect ends" + (f" and {holder.display_name} is free." if holder is not None else "."),
         targets=[holder] if holder is not None else ())
    if holder is not None and freed:
        by = destroyer(engine, obj)  # the held creature breaking its own prison, or someone breaking it from outside
        escaped(engine, holder, freed, "physical" if by in (None, holder.entity_id) else "outside_assistance", by=by or holder,
                source=record.get("source") or SOURCE, way="object", object_id=obj.object_id)
    rows = record.get("on_destroyed") or []
    action = engine.action_catalog.get(record.get("source") or "")
    if rows and owner is not None and action is not None and holder is not None and holder.active:
        typed = {"numbers": dict(record.get("numbers") or {}), "source": record.get("source"), "effects": rows, "riders": []}
        ctx = typed_executor.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [holder], holder)
        typed_executor.run_effects(ctx, rows)


def destroyer(engine: Any, obj: Any) -> str | None:
    """Who brought a destroyed object to 0 hit points: the actor of its newest OBJECT_UPDATED that shows it destroyed."""
    for event in reversed(engine.events):
        if event.event_type == "OBJECT_UPDATED" and obj.object_id in (event.target_ids or ()):
            if ((event.payload or {}).get("object") or {}).get("destroyed") and event.source_definition_id != SOURCE:
                return event.actor_id
    return None


def _sweep(engine: Any, *, native_only: bool = False) -> None:
    objects = [obj for obj in engine.state.objects.values() if bound(obj) is not None
               and bool(bound(obj).get("native_lifecycle") == 1) == native_only]
    if not objects:
        return
    for obj in objects:
        record = bound(obj)
        if obj.destroyed:
            if not record.get("ended"):
                # Destroyed by damage (objects.deal): end the effect once, and remember that it was done.
                done = obj.model_copy(update={"component": {**obj.component, KEY: {**record, "ended": 1}}})
                engine._update_object(done, SOURCE, record.get("owner"))
                _end_guarded(engine, obj, record)
            continue
        if not _guarded_left(engine, record):
            # The effect ended first (a successful save, Concentration lost, expiry): the object goes with it.
            gone = obj.model_copy(update={"destroyed": True, "current_hp": 0,
                                          "component": {**obj.component, KEY: {**record, "ended": 1}}})
            engine._update_object(gone, SOURCE, record.get("owner"))
            note(engine, record.get("source") or SOURCE, record.get("owner"),
                 f"{(obj.component or {}).get('name') or 'The object'} is gone: the effect it held has ended.")


@hook("event")
def _event(engine: Any, event_type: str, kwargs: Any) -> None:
    if event_type in ("OBJECT_UPDATED", "CONDITION_REMOVED", "ZONE_REMOVED", "CONCENTRATION_ENDED", "TURN_STARTED",
                      "TURN_ENDED", "ENTITY_DEFEATED"):
        if engine.__dict__.get("_bound_sweeping"):
            return
        engine.__dict__["_bound_sweeping"] = True
        try:
            _sweep(engine)
        finally:
            engine.__dict__["_bound_sweeping"] = False


@hook("state_event")
def native_lifecycle(engine: Any, event: Any) -> None:
    """Newly sealed objects also expire at native lifecycle checkpoints."""
    if event.event_type not in ("OBJECT_UPDATED", "CONDITION_REMOVED", "ZONE_REMOVED",
                               "CONCENTRATION_ENDED", "TURN_STARTED", "TURN_ENDED", "ENTITY_DEFEATED"):
        return
    if engine.__dict__.get("_bound_sweeping"):
        return
    engine.__dict__["_bound_sweeping"] = True
    try:
        _sweep(engine, native_only=True)
    finally:
        engine.__dict__["_bound_sweeping"] = False
