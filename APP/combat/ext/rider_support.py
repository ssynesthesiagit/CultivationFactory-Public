"""Shared spatial/resource helpers used by Force, Shadow, Disease, Radiance, Destruction and Wax.

These queries contain no sphere eligibility or ability behavior. Refund callers
provide their own source so resource events keep the correct provenance.
"""
from typing import Any
from . import note


def cp_pool(actor: Any) -> str | None:
    for pool in ("resource:core.qi", "resource:core.cp", "resource:core.stamina", "resource:core.resonance"):
        if pool in actor.resources:
            return pool
    return next((key for key in actor.resources if key.startswith("resource:core.")), None)


def refund(engine: Any, actor: Any, why: str, source: str) -> None:
    pool = cp_pool(actor)
    if pool is not None and actor.resources.get(pool, 0) < actor.resource_maximums.get(pool, 0):
        engine._gain_resource(actor, pool, 1, source)
        note(engine, source, actor, f"{why} (1 CP back).")


def occupant(engine: Any, cell: Any) -> Any | None:
    def squares(actor: Any) -> set[tuple[int, int]]:
        return {(c.x, c.y) if hasattr(c, "x") else (int(c[0]), int(c[1]))
                for c in engine.grid.footprint_cells(actor.position, engine._footprint(actor.entity_id))}
    return next((actor for actor in engine.state.actors.values()
                 if actor.active and (cell.x, cell.y) in squares(actor)), None)


def remove_instance(engine: Any, holder: Any, iid: str, source: str) -> None:
    """Remove exactly the selected condition; preserve other casters/copies."""
    condition = holder.conditions.pop(iid, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id,
                             target_ids=(holder.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid})


def area_recipients(ctx: Any) -> list[str]:
    """The creature ids that share ONE damage roll, or ``[]`` when this roll reaches a single creature.

    Shared by the riders that fold a printed bonus into one named creature's damage: an area rolls once
    for every creature in it, so a bonus that names one of them is not part of the shared roll and is
    added at delivery instead (``deal_bonus``). Users: combat/ext/roll_modifiers.py and
    combat/ext/death_riders.py. The executor records the subjects under ``_area_targets`` (see
    ``typed_executor._save_each`` and ``_damage_roll``), the same signal the damage-type choice uses to
    keep an area's roll shared.
    """
    subjects = [subject for subject in (ctx.damage_cache.get("_area_targets") or []) if subject is not None]
    return [subject.entity_id for subject in subjects] if len(subjects) > 1 else []


def teleport(ctx: Any, mover: Any, destination: Any) -> bool:
    """Shadow travel and companion riders use ordinary typed teleport resolution.

    Preserve the originating action/typed metadata while checking the mover's
    seal, footprint, teleport gates and destination entry effects.
    """
    from dataclasses import replace
    from ..typed_executor import block_movement

    start = mover.position
    block_movement(replace(ctx, actor=mover, destination=destination),
                   {"type": "teleport", "applies_to": "self"})
    return mover.position != start
