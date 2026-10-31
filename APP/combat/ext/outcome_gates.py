"""Effects that run their nested effects only for one outcome of the roll that got them here (rider lane 3, 2026-09-29).

Six printed shapes the core has no row for; three are "did that roll go far enough" (or "did it fall"), two are "how big is the target" and
one is "where does it stand":

  if_missed_by         {"max": 5, "effects": [...]}   in an attack's ``on_miss``: the attack missed by no more than ``max``
                                                     ("Miss by 5 or less: the target cannot take Reactions against you").
                                                     The margin is the target's AC (with cover) minus the attack total, read from
                                                     the ATTACK_ROLLED event; a natural 1 that would have hit counts as 0.
  if_failed_by         {"min": 5, "effects": [...]}   in a save's ``on_fail``: the save fell short of its DC by at least ``min``
                                                     ("If the target fails the save by 5 or more, it is also pushed 5 feet").
                                                     Read from the SAVE_ROLLED event (its DC already carries the saver's bonuses).
  if_size_at_most      {"larger": 1, "effects": [...]}   the nested effects run against the current target only when it is no more than
                                                     ``larger`` sizes larger than you ("If the target is no more than one size larger
                                                     than you, push it 5 feet"); size is the width of its footprint in cells.
  if_size_larger       {"than": 0, "effects": [...]}   the nested effects run only when the target is more than ``than`` sizes larger than you
                                                     ("When you hit a creature larger than you ..."; "If the target is larger ...").
  if_on_difficult_ground {"effects": [...]}          the nested effects run against the current target only while it stands on Difficult Terrain --
                                                     a zone or painted map ground that is difficult for it (zones.difficult_cells): "If the
                                                     target is standing on difficult terrain, mud, snow, roots, rubble ... it must also succeed
                                                     on a Dexterity saving throw or fall Prone" (Low Chop). Stairs, a narrow bridge and a slope
                                                     are not terrain the table has, and stay the GM's.
  if_dropped_by_attack {"effects": [...]}             a sibling AFTER the ``attack`` row: the nested effects run once for each
                                                     target this attack took from above 0 HP to 0 ("If this attack reduces the
                                                     target to 0 HP, hostile creatures within 30 feet ... Frightened"). The
                                                     target's HP is snapshotted at ``attack_sequence_start``; the nested effects
                                                     run with that fallen target as ``ctx.target``.

Nothing here changes state itself: the nested rows do, through the engine's evented methods, so a saved fight replays.
"""
from dataclasses import replace
from typing import Any

from . import effect, hook

SNAPSHOT = "_hp_before_attack"


def _last(engine: Any, event_type: str, actor_id: str, target_id: str | None = None) -> Any:
    for event in reversed(engine.events):
        if event.event_type != event_type:
            continue
        if event.actor_id == actor_id and (target_id is None or target_id in (event.target_ids or ())):
            return event
    return None


def _run(ctx: Any, subject: Any, rows: list[Any]) -> None:
    import copy

    from ..typed_executor import run_effects

    run_effects(replace(ctx, targets=[subject], target=subject), copy.deepcopy(rows or []))


@effect("if_missed_by")
def if_missed_by(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if subject is None:
        return
    event = _last(ctx.engine, "ATTACK_ROLLED", ctx.actor.entity_id, subject.entity_id)
    if event is None:
        return
    payload = event.payload or {}
    margin = max(0, int(payload.get("target_ac") or 0) - int(payload.get("modified_total") or 0))
    if margin <= int(row.get("max") if row.get("max") is not None else 5):
        _run(ctx, subject, row.get("effects"))


@effect("if_failed_by")
def if_failed_by(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if subject is None:
        return
    event = _last(ctx.engine, "SAVE_ROLLED", subject.entity_id)
    if event is None:
        return
    payload = event.payload or {}
    short = int(payload.get("dc") or 0) - int(payload.get("total") or 0)
    if short >= int(row.get("min") if row.get("min") is not None else 5):
        _run(ctx, subject, row.get("effects"))


@effect("if_size_at_most")
def if_size_at_most(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if subject is None or not subject.active:
        return
    engine = ctx.engine
    if row.get("max_size"):
        # "no larger than Large" is the creature's size right now, so growth counts: a Medium creature changed to
        # Huge is Huge. dynamic_size.current_category is the public helper that reads a recorded transformation
        # first and otherwise the sealed footprint width, so a legacy wide footprint counts as its real size too.
        from ..dynamic_size import CATEGORIES, current_category

        if CATEGORIES.index(current_category(engine, subject)) <= CATEGORIES.index(str(row["max_size"]).title()):
            _run(ctx, subject, row.get("effects"))
        return
    larger = int(row.get("larger") if row.get("larger") is not None else 1)
    if engine._footprint(subject).width_cells <= engine._footprint(ctx.actor).width_cells + larger:
        _run(ctx, subject, row.get("effects"))


@effect("if_size_larger")
def if_size_larger(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if subject is None or not subject.active:
        return
    engine = ctx.engine
    if engine._footprint(subject).width_cells > engine._footprint(ctx.actor).width_cells + int(row.get("than") or 0):
        _run(ctx, subject, row.get("effects"))


@effect("if_on_difficult_ground")
def if_on_difficult_ground(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if subject is None or not subject.active:
        return
    from .. import zones

    if set(ctx.engine._actor_cells(subject)) & zones.difficult_cells(ctx.engine, subject):
        _run(ctx, subject, row.get("effects"))


@hook("attack_sequence_start")
def snapshot(ctx: Any) -> None:
    ctx.damage_cache[SNAPSHOT] = {target.entity_id: int(target.current_hp) for target in ctx.targets}


@effect("if_dropped_by_attack")
def if_dropped_by_attack(ctx: Any, row: dict[str, Any]) -> None:
    before = ctx.damage_cache.get(SNAPSHOT) or {}
    for subject in list(ctx.targets):
        if before.get(subject.entity_id, 0) > 0 and int(subject.current_hp) <= 0:
            _run(ctx, subject, row.get("effects"))
