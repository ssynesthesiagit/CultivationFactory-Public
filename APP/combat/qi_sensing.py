"""Material-aware Qi rays, used by the Distributed Existence information producer.

Scene-owner barrier metadata lives on terrain regions, map objects or zone
profiles: material, thickness_mils (integer thousandths of an inch), and
blocks_qi_perception/sealed. No metadata invents a source or reveals identity.
Absent explicit thickness, one occupied five-foot voxel is five feet thick.
Multiple independent barriers of the same material accumulate along the ray.
"""
from .gate2_runtime_models import Position


def ray_clear(engine, start, end, *, sealed_region_ids=(), sealed_object_ids=()):
    from .object_geometry import target_cells
    from .ext.objects import object_id
    from .terrain_materials import material_tag
    ray=set(engine.grid.effect_ray_cells(start,end)[1:-1])
    if not ray:return True
    totals={'stone':0,'metal':0,'wood':0}
    def admit(record,count,*,solid=False):
        if record.get('sealed') or record.get('sealed_formation') or record.get('blocks_qi_perception'):return False
        material=material_tag(record.get('material'))
        group=('stone' if material in ('stone','rock','granite','masonry') else
            'metal' if material in ('metal','iron','steel','copper','bronze','silver','gold','tin') else
            'wood' if material in ('wood','earth','packed earth') else None)
        if material=='lead':return False
        if not group:return bool(material) or not solid
        thickness=record.get('thickness_mils')
        if thickness is None:thickness=count*60000
        if type(thickness) is not int or thickness<0:raise ValueError('Qi barrier thickness must be nonnegative integer thousandths of an inch.')
        totals[group]+=thickness
        return totals[group]<{'stone':12000,'metal':1000,'wood':36000}[group]
    covered=set()
    document=engine.battlefield_document or {}
    for region in document.get('terrain_regions',()):
        bottom=int(region.get('base_altitude_ft',0));height=region.get('height_ft')
        cells={(c['x'],c['y']) for c in region.get('cells',())}
        hits={c for c in ray if c[:2] in cells and c[2]*5>=bottom and (height is None or c[2]*5<bottom+height)}
        solid=region.get('terrain_type')=='BLOCKED'
        if hits and (solid or region.get('blocks_qi_perception') or region.get('sealed_formation') or region.get('sealed')):
            covered.update(hits)
            if region.get('region_id') in sealed_region_ids or not admit(region,len(hits),solid=solid):return False
    authored={object_id(r):r for r in document.get('map_objects',())}
    for obj in engine.state.objects.values():
        if obj.destroyed:continue
        record={**authored.get(obj.object_id,{}),**obj.component}
        # Explicit map thickness survives component material normalization.
        if not (record.get('blocks') or record.get('blocks_qi_perception') or record.get('sealed_formation') or record.get('sealed')):continue
        volume={(p.x,p.y,z) for p in target_cells(engine,obj) for z in range(p.z,p.z+(int(obj.height_ft or 5)+4)//5)}
        hits=ray&volume
        if hits:
            covered.update(hits)
            if obj.object_id in sealed_object_ids or not admit(record,len(hits),solid=bool(record.get('blocks'))):return False
    for zone in engine.state.zones.values():
        if not zone.active:continue
        spec=zone.trigger_profile or {};wall=spec.get('wall') or {}
        record={**spec,**wall}
        bottom=int(wall.get('base_altitude_ft',0));height=wall.get('height_ft')
        cells={(p.x,p.y) for p in zone.affected_cells}
        hits={p for p in ray if p[:2] in cells and p[2]*5>=bottom and (height is None or p[2]*5<bottom+height)}
        if hits and (wall or record.get('blocks_qi_perception') or record.get('sealed_formation') or record.get('sealed')):
            covered.update(hits)
            if not admit(record,len(hits),solid=bool(wall.get('blocks_movement'))):return False
    # Unknown solid geometry cannot justify sensing through a material whose
    # identity/thickness has not been authored. Sight alone is not the policy.
    return not any(engine.grid.terrain_at(Position(x=x,y=y,z=z),'BLOCKED') for x,y,z in ray-covered)
