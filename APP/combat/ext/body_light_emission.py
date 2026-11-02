"""Body light location, separate from the shared scene/suppression owner.

Only the seen creature's enrolled Body source can reveal its square. Emitted
light never grants sight through an obstruction or reveals an Invisible body.
The former scene-owner hook remains here with its existing pure query contract.
"""
from . import hook, query
from .body_modes_scene_resources import bundle_of, profiles


@hook('pinpoint_target')
def visible_light_source(engine, viewer, seen):
    if any(c.condition_id in ('condition:typed.invisible', 'condition:core.invisible')
           for c in seen.conditions.values()):
        return
    enrolled = {p.get('source') for p in profiles(bundle_of(engine, seen)) if p.get('source')}
    if not any(isinstance(reply, dict) and reply.get('source') in enrolled
               and (reply.get('dim_ft', 0) > 0 or reply.get('bright_ft', 0) > 0)
               for reply in query('light_emission', engine, seen)):
        return
    from .. import senses, zones
    from ..typed_executor import condition_rules
    if any(r.get('blinded') for r in condition_rules(viewer)):
        return
    if senses.physical_sight(engine, viewer, seen) and not zones.hidden_from(engine, viewer, seen):
        return True
