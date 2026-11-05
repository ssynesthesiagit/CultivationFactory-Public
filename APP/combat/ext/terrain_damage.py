"""Shared helper: the creating ability's own damage, for a named terrain's entering/starting-turn save.

``APP/combat/rules/terrain.json`` gives Molten Terrain a save "against the creating
ability's own damage" (``from_ability``): a patch Magma Glob leaves is dealt the damage
the talent that made it lists, half on a success. Two abilities need that reading of one
ability's effect tree, so it is shared here rather than written twice:

* ``combat/factory_compiler._zone_spec`` -- the area an ability itself casts.
* ``combat/ext/magma_crust.magma_patch`` -- the one-square patch an on-hit option leaves.

Public API: ``own_damage_rows(effects) -> list[dict]``, a pure read that deep-copies the rows.

A row that carries ``source_modifier`` is another ability's rider grafted onto this
strike (Magma Glob gains Eruption Strike, "Trigger: You hit a creature ... Cost 2 CP").
Those are the rider's own rules with their own trigger, cost and use limit; the terrain
they leave behind is the talent's ground, and repeating a paid rider there would fire it
with no attack, no cost and no use limit. Its whole subtree is skipped, so nothing the
rider adds -- its damage, its save, or a nested row -- reaches the terrain save.
"""
from __future__ import annotations

from typing import Any, Iterable
from copy import deepcopy

# The branches an effect nests rows under. A named terrain's save looks at the ability's
# whole tree, so the ability's own hit row counts (that is where a strike's damage lives).
_BRANCHES = ("on_hit", "on_miss", "on_fail", "on_success", "effects")


def own_damage_rows(effects: Iterable[Any]) -> list[dict[str, Any]]:
    """Deep copies of the creating ability's own damage rows, with no attached rider's rows.

    Pure and read-only: the rows are copied so the caller may store them on a zone.
    """
    rows: list[dict[str, Any]] = []
    for effect in effects or ():
        if not isinstance(effect, dict):
            continue
        if effect.get("source_modifier"):
            continue  # another ability's rider, with its own trigger, cost and use limit
        if effect.get("type") in ("damage", "extra_damage") and (effect.get("dice") or effect.get("dice_by_cl")):
            rows.append(deepcopy(effect))
        for branch in _BRANCHES:
            nested = effect.get(branch)
            if isinstance(nested, list):
                rows.extend(own_damage_rows(nested))
    return rows
