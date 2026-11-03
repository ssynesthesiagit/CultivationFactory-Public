"""Opt-in mapped swimming shared by liquid routes and native Swim Speed grants.

Only mechanically authored water cells opt in. An ordinary swimmer pays the
basic extra foot per foot; a Swim Speed or liquid-surface movement capability
removes that surcharge. Native movement still owns terrain, occupancy, routes,
movement pools, OAs and hazards. Observation-only maps may omit water cells.
"""
from . import hook,query
from .. import route_environment


def swim_speed(engine,actor):
    values=query('swim_speed',engine,actor)
    if any(type(v) is not int or v<0 for v in values):
        raise ValueError('Swim Speed providers must return nonnegative integer feet.')
    return max([0,*values])


@hook('movement_segment_surcharge')
def swimming_cost(engine,actor,previous,destination,mode):
    if mode!='walk' or not route_environment.at(engine.grid,destination,('water',)):
        return None
    if swim_speed(engine,actor)>0 or True in query('liquid_surface_step',engine,actor,previous,destination):
        return 0
    return engine.grid.square_size_ft
