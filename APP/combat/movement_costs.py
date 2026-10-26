"""Pure per-square surcharges shared by walking, flight and granted movement.

Mounted crawling supplies a surcharge; other movement providers may use the
same query without changing Speed or storing a second movement allowance.
"""


def surcharge(engine, actor, mode="walk"):
    from . import ext

    total = 0
    for value in ext.run_strict("movement_step_surcharge", engine, actor, mode):
        if type(value) is not int or value < 0:
            raise ValueError("Movement step surcharges require nonnegative integer feet")
        total += value
    return total


def elevation_surcharge(engine, actor, previous, destination, mode):
    """Pure additional price for a segment that changes height; level is inert."""
    if previous.z == destination.z:
        return 0
    from . import ext
    total = 0
    for value in ext.run_strict("movement_elevation_surcharge", engine, actor, previous, destination, mode):
        if type(value) is not int or value < 0:
            raise ValueError("Elevation surcharges require nonnegative integer feet")
        total += value
    return total


def segment_surcharge(engine,actor,previous,destination,mode):
    """Pure source prices for a specific edge, shared by quotes and commits."""
    from . import ext
    total=0
    for value in ext.run_strict('movement_segment_surcharge',engine,actor,previous,destination,mode):
        if type(value) is not int or value<0:
            raise ValueError('Movement segment surcharges require nonnegative integer feet')
        total+=value
    return total


def walk_edge_surcharge(engine, actor):
    """Per-edge price callable for a ground walking search (SquareGrid.reachable's and shortest_path's edge_surcharge).

    Every walking search whose cost is spent as movement passes this (flight.reachable, granted movement, the gate2
    step loop and the portable Combustive Step), so the offered price of an edge equals the cost step_cost charges
    when that edge commits (combat/flight.py). Forced displacements charge no movement and do not pass it."""
    return lambda previous, destination: segment_surcharge(engine, actor, previous, destination, 'walk')
