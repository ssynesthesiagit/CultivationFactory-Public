"""Bind authored terrain modes and horizontal sight surfaces at construction."""
from . import hook
from ..terrain_occlusion import CROSS_POLICY, bind_roofs


@hook('match_start')
def record_terrain_occlusion(engine):
    bind_roofs(engine.grid, getattr(engine, 'battlefield_document', None) or {})
    # Default maps with no thin geometry keep identical stock history bytes.
    if not engine.grid.centerline_cells:
        return
    for event in engine.events:
        if event.event_type == 'MATCH_CREATED':
            event.payload['terrain_occlusion_policy'] = CROSS_POLICY
            return
