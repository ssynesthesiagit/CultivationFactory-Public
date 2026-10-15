"""Native walkable surfaces projected from persistent runtime objects.

``runtime_roof_surfaces(engine) -> list[roof document] | None`` is a pure,
strict extension query. Each document uses the same cells/height/openings/check
schema as an authored roof. Absent providers preserve every existing grid field.
A provider's last surface disappearing restores authored roofs, never deletes
an authored roof. No surface is saved twice; cold reload derives it from objects.
Consumers are ordinary roof walking, climbing, support, falling, sight and rays.
"""
from . import ext
from .roof_geometry import RoofGeometry


def sync(engine):
    rows=[row for group in ext.run_strict('runtime_roof_surfaces',engine) for row in group]
    if not rows and not getattr(engine,'_runtime_surface_bound',False):
        return
    authored=list((getattr(engine,'battlefield_document',{}) or {}).get('roof_surfaces',()))
    ids=[str(row['id']) for row in [*authored,*rows]]
    if len(ids)!=len(set(ids)):
        raise ValueError('Runtime surface identities must be distinct from each other and authored roofs.')
    geometry=RoofGeometry([*authored,*rows])
    engine.grid.roof_geometry=geometry
    engine.grid.roof_surfaces=geometry.surfaces
    engine._runtime_surface_bound=True
