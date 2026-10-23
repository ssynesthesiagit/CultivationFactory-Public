"""The printed ability lights of docs/specs/LIGHTING_SPEC.md §8.2, read from combat/rules/light_sources.json.

One table, so a printed light is named once and never guessed from prose. Three consumers read it:

    combat/factory_compiler.py::_zone_visual   the zone an ability leaves carries the row's printed radii; the
                                               radius the compiler used to read out of the rules text is kept only
                                               for a mechanic this table does not name (§8.1)
    combat/ext/printed_light.py                a lasting condition or modifier the ability places makes its holder
                                               shed the row's light for exactly as long as that state lasts
    tests/test_lighting_migration.py           the cross-check proving this table still matches the typed-mechanics
                                               authority, so a new printed light cannot land silently

A row is:

    {"mechanic": <typed-mechanics id>, "name": <printed name>, "bright_ft": N, "dim_ft": M,
     "follows": "self" | "zone" | "target" | "targets" | "summon", "magical": bool,
     "state": <optional>, "evidence": <the printed clause>}

``state`` is present only when the light rides a lasting state on a creature: the condition id it is filed as (a
prefix match, e.g. "condition:typed.exposed") or "modifier" for a rider that lands as a modifier. The creature
holding that state sheds the light; nothing else does. A row with no ``state`` is carried by its own producer -- a
zone's visual.light (Living Wax Form's Wick Body candlelight), a summon's light (Ghost Lantern), or a condition the
ability's producer writes itself (Cinder Touch's Revealing Ember) -- so this table must not add a second emitter.

Nothing here is saved, and nothing here changes a fight by itself: it is data the model and the compiler read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The curated table (spec §8.2). Not generated: it is reviewed data, like combat/rules/senses.json.
PATH = Path(__file__).with_name("rules") / "light_sources.json"
_CACHE: dict[str, tuple[int, dict[str, dict[str, Any]]]] = {}


def _table() -> dict[str, dict[str, Any]]:
    """mechanic id -> its row, reloaded when the file changes on disk (an editor session may rewrite it)."""
    key = str(PATH)
    stamp = PATH.stat().st_mtime_ns
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    rows = json.loads(PATH.read_text(encoding="utf-8"))["sources"]
    table = {str(row["mechanic"]): row for row in rows}
    _CACHE[key] = (stamp, table)
    return table


def rows() -> tuple[dict[str, Any], ...]:
    """Every printed light row, in the file's order."""
    return tuple(_table().values())


def row(mechanic: str) -> dict[str, Any] | None:
    """One mechanic's printed light, or None when this table does not name it."""
    return _table().get(str(mechanic or ""))


def light(mechanic: str) -> dict[str, Any] | None:
    """The light a zone made by ``mechanic`` carries: {"bright_ft", "dim_ft", "magical"}, or None."""
    found = row(mechanic)
    if found is None:
        return None
    return {"bright_ft": int(found["bright_ft"]), "dim_ft": int(found["dim_ft"]),
            "magical": bool(found.get("magical"))}


def state_rows() -> tuple[dict[str, Any], ...]:
    """The rows whose light rides a lasting condition or modifier on a creature (the ones no zone or summon carries)."""
    return tuple(found for found in _table().values() if found.get("state"))
