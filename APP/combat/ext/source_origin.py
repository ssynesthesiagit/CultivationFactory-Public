"""Pulse Through the Seam: Source Pulse's optional visible mineral origin.

Uses the shared action_geometry effect_origins contract for range, line of sight,
line of effect and cover, without moving its caster. Shared helper
source_locks.mineral_surface_points reads recorded terrain and object geometry,
not decorative floors. Each origin binds x/y and five-foot altitude z.
The anchor must be visible and within the printed 30 feet of the caster.
AI target knowledge remains anchored to what its caster can perceive.
"""
from . import effect, hook

SEAM = 'tianxia.talent.source.pulse_through_the_seam'
PULSE = 'SOURCE_BASE_SOURCE_PULSE'


@effect('source_seam_origin')
def marker(ctx, row):
    """Ownership marker; the bound remote origin governs this activation."""
    return None


@hook('compile_block')
def compile_origin(block, spec, row, numbers):
    return [{**row, 'block': block, 'kind': 'pulse_seam'}] if block == 'source_origin' else None


@hook('effect_origins')
def origins(engine, actor, action):
    from .passive_rows import row_of
    if row_of(engine, actor.entity_id, 'source_origin', 'pulse_seam') is None:
        return None
    if ((action.parameters or {}).get('typed') or {}).get('source') != PULSE:
        return None
    from .. import senses
    from .source_locks import mineral_surface_points
    return [{'id': f'source_seam:{point.x},{point.y},{point.z}',
             'label': f'Pulse Through the Seam: mineral surface at {point.x},{point.y}'
                      + (f', {point.z * 5} feet up' if point.z else ''),
             'position': {'x': point.x, 'y': point.y, 'z': point.z}}
            for point in mineral_surface_points(engine)
            if point != actor.position
            and engine.grid.distance_ft(actor.position, point) <= 30
            and senses.perceives_cell(engine, actor, point)] or None


@hook('candidate_allowed')
def perceived_target(engine,actor,candidate,action):
    origin=(candidate.metadata or {}).get('effect_origin') or {}
    if not str(origin.get('id') or '').startswith('source_seam:'):
        return None
    from .. import senses
    from ..action_geometry import activate
    from ..target_knowledge import located
    from ..shot_geometry import scope
    from .needle import ai_controlled
    # The attack origin is not a sensor. Reset to physical caster geometry even
    # when this query is called inside a candidate's remote activation scope.
    with activate(engine,actor,action.source_definition_id,None), scope(engine,actor,action):
        perception = senses.perceives if ai_controlled(engine,actor) else located
        return all((target:=engine.state.actors.get(tid)) is None or perception(engine,actor,target)
                   for tid in candidate.target_ids)
