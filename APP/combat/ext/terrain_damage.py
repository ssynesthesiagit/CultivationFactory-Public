"""Shared helper: the creating ability's own damage, for a named terrain's entering/starting-turn save.

``APP/combat/rules/terrain.json`` gives Molten Terrain a save "against the creating
ability's own damage" (``from_ability``): a patch Magma Glob leaves is dealt the damage
the talent that made it lists, half on a success. Terrain producers share that reading
of the creating ability's effect tree rather than writing it twice:

* ``combat/factory_compiler._zone_spec`` -- the area an ability itself casts.
* ``combat/ext/docket_terrain.terrain_patch`` (via combat/terrain_patches) -- ground an effect leaves.
* ``combat/zones.expire_owned_zones`` (via combat/terrain_patches) -- its destination terrain.

``terrain_triggers`` is the shared enter/start-save builder for all these callers.
An optional runtime Context snapshots attack dice through typed_executor.resolve_attack_damage,
including the same attack_damage hook used by the creating attack; compilation stays pure.

Public API: ``own_damage_rows(effects, ctx=None) -> list[dict]`` deep-copies the rows;
without ctx it is a pure read. ``terrain_triggers`` returns the named terrain's save.

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


def own_damage_rows(effects: Iterable[Any], *, ctx=None) -> list[dict[str, Any]]:
    """Deep copies of the creating ability's own damage rows, with no attached rider's rows.

    Without ctx this is a pure read. Runtime attack rows use the existing dice
    resolver once; copied rows may then be stored on a zone without live objects.
    """
    rows: list[dict[str, Any]] = []
    for effect in effects or ():
        if not isinstance(effect, dict):
            continue
        if effect.get("source_modifier"):
            continue  # another ability's rider, with its own trigger, cost and use limit
        if effect.get("type") in ("damage", "extra_damage") and (effect.get("dice") or effect.get("dice_by_cl")):
            rows.append(deepcopy(effect))
        primary = None
        resolved = None
        if ctx is not None and effect.get("type") == "attack":
            from dataclasses import replace
            from ..typed_executor import resolve_attack_damage

            dice, kinds, _kind, primary, _weapon = resolve_attack_damage(replace(ctx), effect)
            if primary is not None and not primary.get("source_modifier") and dice is not None:
                resolved = deepcopy(primary)
                resolved.pop("dice_by_cl", None)
                resolved.update(dice={"count": dice.count, "sides": dice.sides, "bonus": dice.modifier},
                                flat=0, formula="none", damage_types=kinds)
        for branch in _BRANCHES:
            nested = effect.get(branch)
            if isinstance(nested, list):
                for child in nested:
                    if child is primary and resolved is not None:
                        rows.append(resolved)
                    else:
                        rows.extend(own_damage_rows([child], ctx=ctx))
    return rows


def terrain_triggers(source: str, name: str, terrain: dict[str, Any],
                     effects: Iterable[Any], *, ctx=None) -> list[dict[str, Any]]:
    """Build a named terrain's enter/start save for compilation, patches and transitions.

    An explicit roster keeps the terrain's printed recipients, including its owner.
    from_ability replaces an inferred ability trigger, but never repeats paid riders.
    """
    rule = terrain.get("enter_start")
    if not rule:
        return []
    if rule.get("from_ability"):
        damage = own_damage_rows(effects, ctx=ctx)
        if not damage:
            return []
        on_fail = [{**row, "applies_to": "target"} for row in damage]
        on_success = [{"type": "half_damage"}] if rule.get("half") else []
    else:
        on_fail = deepcopy(rule.get("on_fail") or [])
        on_success = deepcopy(rule.get("on_success") or [])
    return [{"id": f"{source}:terrain", "name": name, "on": ["enter", "start"],
             "who": rule.get("who") or "hostile",
             **({"roster": str(rule["who"]).strip().lower()} if rule.get("who") else {}),
             "effects": [{"type": "save", "ability": rule.get("ability") or "DEX",
                          "on_fail": on_fail, "on_success": on_success}]}]
