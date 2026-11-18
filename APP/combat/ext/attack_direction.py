"""Typed directional knowledge from an attack, without revealing a hidden square.

reveal_attack_direction is used by Folded Weapon Line and can be attached to any
printed hit/miss consequence. A historical condition stores only a signed compass
direction, never the origin coordinates or a target-knowledge observation.
"""
from . import effect


@effect("reveal_attack_direction")
def reveal(ctx, row):
    from ..action_geometry import point
    target = ctx.target
    if target is None:
        return
    origin = point(ctx.engine, ctx.actor)
    delta = [origin.x - target.position.x, origin.y - target.position.y, origin.z - target.position.z]
    dx, dy, dz = [(value > 0) - (value < 0) for value in delta]
    horizontal = ({-1: "north", 0: "", 1: "south"}[dy]
                  + {-1: "west", 0: "", 1: "east"}[dx]) or "this space"
    direction = horizontal + (" above" if dz > 0 else " below" if dz < 0 else "")
    ctx.engine._remove_condition(target, "condition:typed.attack_direction", ctx.source)
    ctx.engine._apply_condition(target, "condition:typed.attack_direction", ctx.source,
        ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
        data={"dx": dx, "dy": dy, "dz": dz,
              "label": f"Last attack came from {direction}",
              "reading": "You know the direction of that attack, not the attacker's hidden location."})
