"""Printed ability lights that ride a lasting state on a creature (docs/specs/LIGHTING_SPEC.md §8.2).

The model is combat/lighting.py; the curated table is combat/rules/light_sources.json, read through
combat/light_sources.py. A row with a ``state`` names the condition id (a prefix, e.g.
"condition:typed.exposed") or "modifier" that the ability files on the creature it affects. While that state is on
an active creature, that creature sheds the row's printed radii -- for exactly as long as the state lasts, because
the state IS the clock and nothing here stores or removes anything.

Rows whose light a zone, a summon or their own producer already carries have no ``state`` and are not emitted here:
the compiler gives a zone its printed radii (combat/factory_compiler.py::_zone_visual), combat/lighting.py reads a
summon's own light, and each of those producers writes what it prints. That keeps one emitter per printed light.

The hook is pure and default-inert: a fight with no such state returns None and the field is exactly what the map and
the four stores already say. No saved field, no engine state, no prompt.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import hook


def _held(actor: Any) -> list[tuple[str, str]]:
    """Every lasting typed state on the creature as (kind, source id): its conditions and its modifiers.

    ``kind`` is the condition id, or "modifier" for a rider that lands as a modifier. Engine clock rows
    ("condition:typed.concentration_deadline", a concentration deadline, a save marker) are not effect states, and a
    row only matches when its printed mechanic is also named by that state's source, so they never light anything.
    """
    held: list[tuple[str, str]] = [(str(condition.condition_id), str(condition.source_definition_id))
                                   for condition in actor.conditions.values()]
    held.extend(("modifier", str(modifier.source_definition_id)) for modifier in actor.modifiers.values())
    return held


def _carries(state: str, mechanic: str, held: Iterable[tuple[str, str]]) -> bool:
    """Whether one of the creature's states is the one this row names, filed by this mechanic."""
    if state == "modifier":
        return any(kind == "modifier" and mechanic in source for kind, source in held)
    return any(kind.startswith(state) and mechanic in source for kind, source in held)


@hook("light_sources")
def printed_light_sources(engine: Any) -> Any:
    """The light of every printed ability whose lasting state the creature currently holds."""
    from .. import light_sources
    from ..lighting import LightSource

    rows = light_sources.state_rows()
    if not rows:
        return None
    out: list[LightSource] = []
    for actor in list(engine.state.actors.values()):
        if not actor.active:
            continue
        held = _held(actor)
        if not held:
            continue
        cells = frozenset(engine._actor_cells(actor))
        if not cells:
            continue
        for row in rows:
            if not _carries(str(row["state"]), str(row["mechanic"]), held):
                continue
            out.append(LightSource(f"printed:{row['mechanic']}:{actor.entity_id}", str(row["name"]), cells,
                                   int(row["bright_ft"]), int(row["dim_ft"]), None, bool(row.get("magical")),
                                   following=actor.entity_id))
    return out or None
