"""Shared counted marks for Disease and Poison: count and lifetime live together.

Typed placement and consumption use default-inert mark_apply/mark_consume hooks.
Real removal removes the count; refresh may add stacks and replace the deadline,
while partial spending preserves the old deadline and save/concentration data.
Legacy saves without count data read the old owner flag only while a mark exists.
"""
from __future__ import annotations
import re
from typing import Any
from . import hook
from .rider_support import remove_instance

STACKING = ("Contagion Token", "Dose Mark", "Toxin Burden")


def _key(name: str, subject: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"_round_marks:{slug}:{subject.entity_id}"


def _mark_id(name: str, owner_id: str) -> str:
    from ..typed_executor import mark_condition_id
    return mark_condition_id(name, owner_id)


def _mark(owner: Any, subject: Any, name: str) -> Any | None:
    return next((c for c in subject.conditions.values() if c.condition_id == _mark_id(name, owner.entity_id)), None) if subject else None


def count(engine: Any, owner: Any, subject: Any, name: str) -> int:
    mark = _mark(owner, subject, name)
    if mark is None:
        return 0
    return max(1, int((mark.data or {}).get("count") or owner.turn_flags.get(_key(name, subject)) or 1))


def _set(engine: Any, owner: Any, subject: Any, name: str, number: int, source: str,
         *, expires: str | None = None, data: dict[str, Any] | None = None) -> None:
    old = _mark(owner, subject, name)
    lifetime = expires if expires is not None else old.expires_on if old else "UNTIL_REMOVED"
    kept = dict(data if data is not None else (old.data or {}) if old else {})
    if old is not None:
        remove_instance(engine, subject, old.instance_id, source)
    owner.turn_flags.pop(_key(name, subject), None)
    if number > 0:
        origin = source if expires is not None or old is None else old.source_definition_id
        engine._apply_condition(subject, _mark_id(name, owner.entity_id), origin, owner.entity_id, expires_on=lifetime,
                                data={**kept, "label": f"{number} {name}{'s' if number > 1 else ''} ({owner.display_name})", "count": number})


def add(engine: Any, owner: Any, subject: Any, name: str, number: int, source: str) -> None:
    if subject is not None and subject.active and number > 0:
        _set(engine, owner, subject, name, count(engine, owner, subject, name) + number, source)


def spend(engine: Any, owner: Any, subject: Any, name: str, source: str, number: int = 1) -> bool:
    held = count(engine, owner, subject, name)
    if held < number or number <= 0:
        return False
    _set(engine, owner, subject, name, held - number, source)
    return True


@hook("mark_apply")
def placed(ctx: Any, effect: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    name = str(effect.get("mark") or "")
    if name not in STACKING:
        return None
    _set(ctx.engine, ctx.actor, subject, name, count(ctx.engine, ctx.actor, subject, name) + 1, ctx.source, expires=expires, data=data)
    return True


@hook("mark_consume")
def spent(ctx: Any, effect: dict[str, Any], subject: Any) -> bool | None:
    name = str(effect.get("mark") or "")
    if name not in STACKING:
        return None
    return spend(ctx.engine, ctx.actor, subject, name, ctx.source, max(1, int(effect.get("count") or 1)))


def _walk(rows: Any):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(key))


@hook("candidate_allowed")
def needs_enough(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rows = [r for r in _walk(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects"))
            if r.get("type") == "spend_mark" and str(r.get("mark")) in STACKING and int(r.get("count") or 1) > 1]
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), "")) if rows else None
    if not rows or target is None:
        return None
    return None if all(count(engine, actor, target, str(r["mark"])) >= int(r["count"]) for r in rows) else False
