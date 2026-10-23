"""Observer-specific zone sight restrictions; Ashen Blindfold's reviewed effect.

Only a new zone_view_restriction effect stores the opt-in condition. Queries
operate on retained zone/source data and the actual observer. Blindsight and
Truesight retain their printed reach; Tremorsense/pinpointing is unchanged.
"""
from typing import Any
from . import effect, hook

CONDITION = 'condition:typed.zone_view_restriction'


@effect('zone_view_restriction')
def restrict(ctx: Any, row: dict) -> None:
    from ..typed_executor import effect_expiry
    from .condition_ownership import refresh_owned
    target = ctx.target
    if target is None:
        return
    refresh_owned(ctx.engine, target, CONDITION, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, target, condition=True),
        data={'zone_source': row['zone_source'], 'preserve_senses': list(row.get('preserve_senses') or []),
              'label': f"{row.get('name', ctx.action.display_name)}: cannot see through {ctx.actor.display_name}'s {row.get('zone_name', 'area')} until your next turn starts"})


@hook('zone_view_blocked')
def blocks(engine: Any, zone: Any, viewer: Any, seen: Any, *, sight_only: bool = False) -> bool | None:
    if viewer is seen:
        return None
    matching = [c for c in viewer.conditions.values() if c.condition_id == CONDITION and not c.data.get('suppressed')
        and c.source_actor_id == zone.owner_id and c.data.get('zone_source') in zone.source_definition_id]
    if not matching:
        return None
    from .. import senses
    from ..space import ray
    from ..spatial_areas import zone_contains
    from ..gate2_runtime_models import Position
    if not any(zone_contains(engine, senses.cell_probe(Position(x=x, y=y, z=z)), zone)
               for x, y, z in ray(viewer.position, seen.position)):
        return None
    available = senses.perception_senses(engine, viewer, sight_only=sight_only)
    for c in matching:
        if not any(engine._distance_actor_to_actor(viewer, seen) <= senses.reach(engine, viewer, sense, seen)
                   and senses.reach(engine, viewer, sense, seen) > 0
                   for sense in c.data.get('preserve_senses') or [] if sense in available):
            return True
    return None
