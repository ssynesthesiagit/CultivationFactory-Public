"""Source-authorized narrow physical paths, shared by native route offers/commit.

physical_passages(engine, actor) -> None or list of records:
{id, source, label, path: Position JSON list, region_ids: [str],
 object_ids: [str], extra_step_ft: nonnegative int, compact: bool}.
Providers own actual passage/physiology/item admission. This module preserves
native movement, OAs, hazards, budgets and replay; it never teleports a token.
Only named preexisting barriers may be crossed. Other objects, creatures,
new walls and roofs still block. No provider means no routes or geometry change.
"""
from . import ext
from .gate2_runtime_models import Position


def records(engine, actor):
    from .read_queries import memo
    def collect():
        out=[]
        for group in ext.run_strict('physical_passages',engine,actor):
            if not isinstance(group,list):raise ValueError('Physical passages must be a list.')
            for row in group:
                if (not isinstance(row,dict) or set(row)!={'id','source','label','path','region_ids','object_ids','extra_step_ft','compact'}
                        or any(type(row[k]) is not str or not row[k] for k in ('id','source','label'))
                        or type(row['extra_step_ft']) is not int or row['extra_step_ft']<0
                        or type(row['compact']) is not bool):
                    raise ValueError('Physical passages require source-owned paths and integer prices.')
                path=tuple(Position.model_validate(p) for p in row['path'])
                if len(path)<2 or len(set(path))!=len(path) or any(not engine.grid.in_bounds((p.x,p.y)) for p in path):
                    raise ValueError('A physical passage needs a distinct in-bounds path.')
                if any(max(abs(a.x-b.x),abs(a.y-b.y),abs(a.z-b.z))!=1 for a,b in zip(path,path[1:])):
                    raise ValueError('Physical passages must visit every adjacent step.')
                if any(not isinstance(row[k],list) or any(type(s) is not str for s in row[k]) for k in ('region_ids','object_ids')):
                    raise ValueError('Name the actual barrier identities a passage crosses.')
                out.append({**row,'positions':path})
        return out
    return memo(engine,('physical_passages',actor.entity_id),collect)


def _edge(row,previous,destination):
    path=row['positions']
    return any((a==previous and b==destination) or (b==previous and a==destination) for a,b in zip(path,path[1:]))


def _clear(engine,actor,row,previous,destination,observed):
    from .creature_passage import endpoint_volumes
    from .object_geometry import target_cells
    from .footprints import ActorFootprintDefinition
    if not _edge(row,previous,destination):return False
    endpoint=destination in (row['positions'][0],row['positions'][-1])
    volume=set(engine._actor_volume(actor,destination)) if endpoint or not row['compact'] else {(destination.x,destination.y,destination.z)}
    if volume & endpoint_volumes(engine,actor,observed=observed):return False
    if endpoint and not engine.grid.volume_legal(destination,footprint=engine._footprint(actor)):
        return False
    fp=engine._footprint(actor) if not row['compact'] else ActorFootprintDefinition.rectangle(1,1,footprint_id='passage',source_definition_id=row['source'])
    if engine.grid.roof_step_blocked(previous,destination,fp):return False
    for region in (engine.battlefield_document or {}).get('terrain_regions',()):
        if region.get('terrain_type')!='BLOCKED':continue
        cells={(p['x'],p['y']) for p in region['cells']}
        bottom=int(region.get('base_altitude_ft',0));height=region.get('height_ft')
        if not any(p[:2] in cells and p[2]*5>=bottom and (height is None or p[2]*5<bottom+height) for p in volume):continue
        if region.get('region_id') not in row['region_ids'] or any(region.get(k) for k in ('sealed','sealed_formation','airtight','liquid_tight','artifact_restraint')) or str(region.get('material','')).lower()=='force':
            return False
    for obj in engine.state.objects.values():
        if obj.destroyed or not obj.component.get('blocks'):continue
        cells={(p.x,p.y,z) for p in target_cells(engine,obj) for z in range(p.z,p.z+(int(obj.height_ft or 5)+4)//5)}
        if cells & volume and (obj.object_id not in row['object_ids'] or any(obj.component.get(k) for k in ('sealed','sealed_formation','airtight','liquid_tight','artifact','artifact_restraint')) or str(obj.component.get('material','')).lower()=='force'):
            return False
    for zone in engine.state.zones.values():
        if not zone.active:continue
        wall=(zone.trigger_profile or {}).get('wall') or {}
        if not wall.get('blocks_movement'):continue
        bottom=int(wall.get('base_altitude_ft',0));height=wall.get('height_ft')
        cells={(p.x,p.y) for p in zone.affected_cells}
        if any(p[:2] in cells and p[2]*5>=bottom and (height is None or p[2]*5<bottom+height) for p in volume):
            return False  # A later independent wall has no declared opening.
    return True


def permitted(engine,actor,previous,destination,mode,*,observed=False):
    if mode not in ('walk','fly') or (mode=='walk' and previous.z!=destination.z):return False
    return any(_clear(engine,actor,row,previous,destination,observed) for row in records(engine,actor))


def supported(engine,actor,position):
    """A compact body inside an actual solid corridor rests on its channel.

    This grants no support in open air, at a free endpoint, after the supporting
    barrier disappears, or without the source's still-current entitlement.
    """
    from .object_geometry import target_cells
    for row in records(engine,actor):
        path=row['positions']
        if not row['compact'] or position not in path[1:-1]:continue
        index=path.index(position)
        if not _clear(engine,actor,row,path[index-1],position,False):continue
        for region in (engine.battlefield_document or {}).get('terrain_regions',()):
            bottom=int(region.get('base_altitude_ft',0));height=region.get('height_ft')
            if (region.get('region_id') in row['region_ids'] and region.get('terrain_type')=='BLOCKED'
                    and any(p['x']==position.x and p['y']==position.y for p in region['cells'])
                    and position.z*5>=bottom and (height is None or position.z*5<bottom+height)):
                return True
        for oid in row['object_ids']:
            obj=engine.state.objects.get(oid)
            if obj is not None and not obj.destroyed and obj.component.get('blocks'):
                if any(p.x==position.x and p.y==position.y and p.z<=position.z<p.z+(int(obj.height_ft or 5)+4)//5 for p in target_cells(engine,obj)):
                    return True
    return False


def surcharge(engine,actor,previous,destination,mode):
    if mode not in ('walk','fly'):return 0
    costs=[row['extra_step_ft'] for row in records(engine,actor) if _edge(row,previous,destination)]
    return min(costs) if costs else 0


def path_surcharge(engine,actor,path,mode='walk'):
    """Extra price absent from legacy ground-grid path quotes."""
    if not records(engine,actor):return 0
    return sum(surcharge(engine,actor,a,b,mode) for a,b in zip(path,path[1:]))


def routes(engine,actor,grant_ft=None):
    from . import flight
    from .voluntary_movement import path_allowed
    out=[]
    mode='fly' if flight.profile(engine,actor).speed_ft else 'walk'
    budget=flight.remaining(engine,actor,mode) if grant_ft is None else grant_ft
    for row in records(engine,actor):
        path=row['positions']
        if actor.position not in path:continue
        index=path.index(actor.position)
        for selected in (path[index:],tuple(reversed(path[:index+1]))):
            if len(selected)<2 or not path_allowed(engine,actor,selected):continue
            if not engine.grid.volume_legal(selected[-1],footprint=engine._footprint(actor)):continue
            if not all(flight.step_allowed(engine,actor,a,b,mode=mode,observed=True) for a,b in zip(selected,selected[1:])):continue
            cost=sum(flight.step_cost(engine,actor,a,b,mode) for a,b in zip(selected,selected[1:]))
            if cost<=budget:out.append((selected[-1],(selected,cost,mode)))
    return out
