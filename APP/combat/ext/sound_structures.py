"""Sound through objects and structures (rider lane C11, 2026-09-30): Harmonic Weakness and Stone-Bell Propagation.

Source (owner text, authority/typed_mechanics/rules_text.json):
  Harmonic Weakness: "When you damage an object, construct, barrier, or structure with Sound damage, mark it with Harmonic Weakness
    until the start of your next turn. The next time it takes damage before the mark ends, add one Sound Die to that damage. Sound
    Die by Realm: Mortal: 1d6. Foundation: 1d8. Core Formation: 1d10. Nascent Soul: 2d8. Harmonic Weakness cannot stack with
    itself."
  Stone-Bell Propagation: "When using a Sound talent against a target touching the same continuous surface, structure, bridge,
    wall, floor, pillar, chain, or bell network as you, increase the range by 30 feet."

How it runs.
  Harmonic Weakness (feature block ``sound_structures`` kind ``harmonic_weakness``): a map object (combat/ext/objects.py) that one
    of the owner's Sound techniques damages (OBJECT_UPDATED with damage taken, from an action of the Sound Sphere: "Sound damage"
    read as damage a Sound talent deals) carries ``harmonic_weakness`` in its component -- one mark, never two -- until the owner's
    next turn starts. The next damage instance on it from anyone (hook ``object_packets``) rolls the Sound Die (CL 1-4 1d6, 5-10
    1d8, 11-16 1d10, 17-20 2d8: the Realms' CL bands) and adds it as damage of that instance's first type; the mark is used up. A
    fully prevented instance keeps the mark (objects.deal keeps the record from before the instance). The log says so in plain words.
  Stone-Bell Propagation's +30 feet was already typed (its modifier's add_range_ft on Sound techniques); the table has no flight or
    altitude, so every creature stands on the one battlefield floor the user stands on and the printed condition always holds.
Not automated: a construct creature (a rolled die on the next damage a creature takes from any source has no seam: the next-damage
seams are flat and for Factory targets only; no table creature is typed construct today), barriers and walls that are zones rather
than map objects, Stone-Bell's Carry Voice / warning bell from a connected point.
"""

from __future__ import annotations

import json
from typing import Any

from ..object_rules import label
from . import hook, note

BLOCK = "sound_structures"
SOUND = "tianxia.sphere.sound"
KEY = "harmonic_weakness"
# Sound Die by Realm, on the Realms' CL bands (Mortal 1-4, Foundation 5-10, Core Formation 11-16, Nascent Soul 17-20).
SOUND_DIE = ((1, 4, 1, 6), (5, 10, 1, 8), (11, 16, 1, 10), (17, 20, 2, 8))
_MECHANICS: dict[str, Any] = {}


def _mechanics() -> dict[str, Any]:
    if not _MECHANICS:
        from .. import factory_compiler

        _MECHANICS.update(json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"])
    return _MECHANICS


def mechanic_of(action_id: str) -> str:
    """"action:typed.<short>.<mechanic id>[#option][+variant]" -> the mechanic id."""
    parts = str(action_id).split(".", 2)
    return parts[2].split("+")[0].split("#")[0] if len(parts) == 3 else ""


def is_sound(action_id: str) -> bool:
    return (_mechanics().get(mechanic_of(action_id)) or {}).get("sphere_id") == SOUND


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    cl = int(numbers.get("cl") or 1)
    count, sides = next(((count, sides) for low, high, count, sides in SOUND_DIE if low <= cl <= high), (1, 6))
    return [{**row, "kind": spec.get("kind"), "count": count, "sides": sides}]


def _row(engine: Any, actor: Any) -> dict[str, Any] | None:
    from .. import typed_reactions

    return next((row for row in typed_reactions._rows(engine, actor.entity_id, BLOCK) if row.get("kind") == "harmonic_weakness"), None)


@hook("event")
def mark_on_sound_damage(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "OBJECT_UPDATED":
        return
    payload = kwargs.get("payload") or {}
    if int((payload.get("damage") or {}).get("taken") or 0) <= 0:
        return
    event = engine.events[-1]
    actor = engine.state.actors.get(str(event.actor_id or ""))
    if actor is None or not is_sound(str(event.source_definition_id or "")):
        return
    row = _row(engine, actor)
    if row is None:
        return
    obj = engine.state.objects.get(str((payload.get("object") or {}).get("object_id") or ""))
    if obj is None or obj.destroyed:
        return
    component = dict(obj.component or {})
    if component.get(KEY):  # "cannot stack with itself"
        return
    component[KEY] = {"owner": actor.entity_id, "count": int(row["count"]), "sides": int(row["sides"])}
    engine._update_object(obj.model_copy(update={"component": component}), str(event.source_definition_id), actor.entity_id)
    note(engine, str(event.source_definition_id), actor,
         f"Harmonic Weakness: the {label(obj)} rings with {actor.display_name}'s "
         f"Sound; the next damage it takes before {actor.display_name}'s next turn deals {row['count']}d{row['sides']} more.",
         targets=())


@hook("object_packets")
def sound_die(engine: Any, actor: Any, obj: Any, packets: list[tuple[int, str]], source: str) -> dict[str, Any] | None:
    mark = (obj.component or {}).get(KEY)
    if not mark or not any(int(amount) > 0 for amount, _kind in packets):
        return None
    from ..gate2_runtime_models import DiceSpec

    owner = engine.state.actors.get(str(mark.get("owner") or ""))
    roll = engine.roller.roll(DiceSpec(count=int(mark["count"]), sides=int(mark["sides"]), modifier=0),
                              actor_id=str(mark.get("owner") or getattr(actor, "entity_id", "")), reason="HARMONIC_WEAKNESS")
    engine._record_roll(roll)
    kind = next(str(kind) for amount, kind in packets if int(amount) > 0)
    component = {key: value for key, value in (obj.component or {}).items() if key != KEY}
    note(engine, source, actor, f"Harmonic Weakness ({owner.display_name if owner else 'Sound'}): the {label(obj)} takes "
         f"{mark['count']}d{mark['sides']} = {roll.total} more {kind.lower()} damage from this hit, and the ringing ends.")
    return {"object": obj.model_copy(update={"component": component}), "packets": [(int(roll.total), kind)]}


@hook("turn_start")
def expire(engine: Any, actor: Any) -> None:
    for obj in list(engine.state.objects.values()):
        mark = (obj.component or {}).get(KEY)
        if mark and mark.get("owner") == actor.entity_id:
            component = {key: value for key, value in (obj.component or {}).items() if key != KEY}
            engine._update_object(obj.model_copy(update={"component": component}), "sound:harmonic_weakness_expired", actor.entity_id)
