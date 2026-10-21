"""Actual teleport-begin limits, separate from pure menu/range previews.

The executing adapter supplies the resolved printed maximum and stable hop key.
Providers may spend a source-owned response and return a nonnegative distance
reduction. One parsed hop resolves once, including zero-distance prevention.
No provider leaves reach, payment, destination ownership and movement unchanged.
"""
from . import ext


def begin(ctx, subject, maximum, key):
    if type(maximum) is not int or maximum < 0 or not isinstance(key, str) or not key:
        raise ValueError('A teleport requires its actual nonnegative maximum and hop identity.')
    if key in ctx.hop_limits:
        return ctx.hop_limits[key]
    reduced = 0
    if maximum:
        for value in ext.run_strict('teleport_begin', ctx, subject, maximum, key):
            if type(value) is not int or value < 0:
                raise ValueError('teleport_begin returns nonnegative integer distance reductions.')
            reduced += value
    ctx.hop_limits[key] = max(0, maximum - reduced)
    if reduced:
        ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=subject.entity_id,
            payload={'checkpoint': 'TELEPORT_DISTANCE_REDUCED', 'hop_identity': key,
                'maximum_before_ft': maximum, 'maximum_after_ft': ctx.hop_limits[key]})
    return ctx.hop_limits[key]


def shortened_destination(ctx, destination, maximum):
    """Automatic bound intent: preserve its goal using every remaining legal cell.

    Humans choose through the ordinary map picker; no option list is truncated.
    Only a previously legal destination outside the reduced reach is replaced.
    """
    from .ext.teleport_steps import destinations, teleport_requirement
    if ctx.engine.grid.distance_ft(ctx.actor.position, destination) <= maximum:
        return destination
    cells = destinations(ctx.engine, ctx.actor, maximum,
        where=teleport_requirement(ctx.typed), action=ctx.action)
    return min(cells, key=lambda cell: (ctx.engine.grid.distance_ft(cell, destination),
        cell.z, cell.y, cell.x), default=None)
