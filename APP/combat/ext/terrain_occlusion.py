"""Bind data-driven terrain geometry at genesis, without changing old fights."""
from . import hook
from ..terrain_occlusion import CROSS_POLICY


@hook('match_start')
def record_terrain_occlusion(engine):
    # Default maps with no thin geometry keep identical stock history bytes.
    if not engine.grid.centerline_cells:
        return
    for event in engine.events:
        if event.event_type == 'MATCH_CREATED':
            event.payload['terrain_occlusion_policy'] = CROSS_POLICY
            return
