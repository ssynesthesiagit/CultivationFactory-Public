"""A benefit "a creature can receive once per Long Rest" (riders lane 4, 2026-09-29: Meridian Stitch's CP restoration, Life-Line
Stitch): the ability's typed effects carry a ``mark`` row flagged ``"once_per_creature": true`` that lasts until removed
(the fight); a creature that already bears that mark, from anyone, is not a legal target of the ability again.

The engine has no rests between fights, so the Long Rest is the fight -- the same reading combat/ext/qi_instability.py takes
for Regulated Breathing's "once per short rest".  The mark is an ordinary condition (block_mark), so a saved fight replays it.
Hooks: candidate_allowed (an action) and reaction_subject_allowed (a reaction row), which never turn a benefit on.
``once_per_caster`` scopes the same record to the acting cultivator instead of
granting target-wide immunity; used by Empty-Lung Edict.
"""

from __future__ import annotations

from typing import Any

from . import hook


def _walk(rows: Any):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for value in row.values():
                if isinstance(value, list):
                    yield from _walk(value)


def limited_marks(effects: Any) -> list[str]:
    return [str(row["mark"]) for row in _walk(effects) if row.get("type") == "mark" and row.get("once_per_creature") and row.get("mark")]


def caster_marks(effects: Any) -> list[str]:
    return [str(row["mark"]) for row in _walk(effects) if row.get("type") == "mark" and row.get("once_per_caster") and row.get("mark")]


def _used(holder: Any, effects: Any, owner: Any) -> bool:
    from ..typed_executor import mark_condition_id

    ids = {mark_condition_id(name, owner.entity_id) for name in caster_marks(effects)}
    return _received(holder, limited_marks(effects)) or any(c.condition_id in ids for c in holder.conditions.values())


def _received(holder: Any, names: list[str]) -> bool:
    from ..typed_executor import mark_condition_id

    prefixes = tuple(mark_condition_id(name, "") for name in names)  # every owner's
    return any(condition.condition_id.startswith(prefixes) for condition in holder.conditions.values())


@hook("candidate_allowed")
def action_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects")
    if not limited_marks(effects) and not caster_marks(effects):
        return None
    for target_id in candidate.target_ids or ():
        holder = engine.state.actors.get(target_id)
        if holder is not None and _used(holder, effects, actor):
            return False
    return None


@hook("reaction_subject_allowed")
def reaction_allowed(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    return False if other is not None and _used(other, row.get("effects"), reactor) else None
