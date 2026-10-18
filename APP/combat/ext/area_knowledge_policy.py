"""Bind the general owner area targeting rule for newly created fights only."""
from . import hook
from ..area_knowledge import STAMP, ORIGIN_AUTHORITY, bind_origin_permissions


@hook('match_start')
def record_area_knowledge_policy(engine):
    for event in engine.events:
        if event.event_type == 'MATCH_CREATED':
            event.payload[STAMP] = 1
            event.payload[ORIGIN_AUTHORITY] = bind_origin_permissions(engine.source_root)
            return
