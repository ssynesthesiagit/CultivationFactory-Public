"""Typed zone entry/leave at native landed movement steps; no zones is inert."""
from . import hook
from .. import zones


@hook("movement_step", priority=-100)
def landed(engine, mover, previous, nxt, intent):
    if zones.on_step(engine, mover, previous, nxt):
        return {"stop":True, "source_id":"system:combat.zone_movement",
                "label":f"{mover.display_name} stops here after the area's effects."}
    return None
