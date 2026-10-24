"""Public, opt-in Asset/Anchor runtime used by construction and repair providers.

``create(engine, owner, source, profile, position, *, component, lifetime=None)``
validates a source-scoped physical profile and commits one ordinary object event.
``members(engine, owner_id=None, group=None, live=True)`` queries persisted works.
``legal_placement(engine, cells, height_ft, ignore=())`` checks full volumes,
creatures, objects, terrain and support; it never supplies inferred permission.
``retire(engine, obj, source)`` ends exactly that object, never repairs damage.
``repair_allowed(obj, source_cl, *, material=False)`` preserves ownership/function
and explicit artifact/specialist/creator restrictions. No caller means no state,
no hooks and no change to existing saves. All provenance is in OBJECT_UPDATED.
Profiles and declarations belong to the calling source, never ability IDs here.
"""
from .gate2_runtime_models import RuntimeObjectState, Position
from .object_geometry import target_cells

KEY = 'asset_anchor_runtime'


def members(engine, owner_id=None, group=None, *, live=True):
    return [o for o in engine.state.objects.values() if (o.component or {}).get(KEY)
            and (owner_id is None or o.owner_id == owner_id)
            and (group is None or o.component[KEY]['group'] == group)
            and (not live or not o.destroyed)]


def stable(engine, position, *, ignore=()):
    if position.z == 0:
        return engine.grid.volume_legal(position)
    if engine.grid.roof_supported(position, None):
        return True
    if engine.grid.terrain_at((position.x, position.y, position.z - 1), 'BLOCKED'):
        return True
    return any(not obj.destroyed and obj.object_id not in ignore and
               (obj.component or {}).get('structure') and obj.height_ft is not None and
               obj.position.z + (obj.height_ft + 4)//5 == position.z and
               any((c.x,c.y)==(position.x,position.y) for c in target_cells(engine,obj))
               for obj in engine.state.objects.values())


def legal_placement(engine, cells, height_ft, *, ignore=(), require_support=True, occupies_space=True):
    if ignore:
        # Rebuild only derived geometry on a query-local copy, so an object
        # never collides with its own old wall or roof while being relocated.
        from copy import copy,deepcopy
        shadow=copy(engine)
        if hasattr(engine,'session'):
            from .journey_assets import grid_for
            shadow.grid=grid_for(engine.session,ignore=ignore)
            shadow.state=copy(engine.state)
            shadow.state.objects={k:o for k,o in engine.state.objects.items() if k not in ignore}
        else:
            shadow.grid=deepcopy(engine.grid)
            shadow.state=engine.state.model_copy(update={'objects':{k:o for k,o in engine.state.objects.items() if k not in ignore}})
            from . import zones
            zones.sync_walls(shadow)
        return legal_placement(shadow,cells,height_ft,require_support=require_support,occupies_space=occupies_space)
    if type(height_ft) is not int or height_ft < 1 or not cells:
        return False
    volume = {(c.x,c.y,z) for c in cells for z in range(c.z,c.z+(height_ft+4)//5)}
    if len({(c.x,c.y,c.z) for c in cells}) != len(cells):
        return False
    if any(not engine.grid.volume_legal(Position(x=x,y=y,z=z)) for x,y,z in volume):
        return False
    if occupies_space and any(volume & set(engine._actor_volume(a)) for a in engine.state.actors.values() if a.active):
        return False
    for obj in engine.state.objects.values():
        if obj.destroyed or obj.object_id in ignore:
            continue
        occupied = {(c.x,c.y,z) for c in target_cells(engine,obj)
                    for z in range(c.z,c.z+max(1,((obj.height_ft or 5)+4)//5))}
        if volume & occupied:
            return False
    return not require_support or any(stable(engine,c,ignore=ignore) for c in cells)


def create(engine, owner, source, profile, position, *, component, lifetime=None):
    required = ('name','kind','ac','hp','source_cl','height_ft','group')
    if any(k not in profile for k in required):
        raise ValueError('Asset profile requires name, kind, AC, HP, Source CL, height and group.')
    if any(type(profile[k]) is not int or profile[k] < 1 for k in ('ac','hp','source_cl','height_ft')):
        raise ValueError('Asset statistics must be positive integers.')
    if not isinstance(source,str) or not source or not owner.entity_id:
        raise ValueError('Asset creation requires its native owner and source.')
    sequence = engine.state.event_sequence+1
    obj = RuntimeObjectState(object_id=f'object:asset:{owner.entity_id}:{sequence}',
        object_kind=profile['kind'],owner_id=owner.entity_id,position=position,
        unattended=True,flammable=False,ac=profile['ac'],current_hp=profile['hp'],maximum_hp=profile['hp'],
        damage_threshold=int(profile.get('threshold',0)),damage_immunities=tuple(profile.get('immune',('POISON','PSYCHIC'))),
        height_ft=profile['height_ft'],destroyed=False,
        component={**component,'name':profile['name'],'source_cl':profile['source_cl'],
            'created_by':source,'resist':list(profile.get('resist',())),
            KEY:{'owner':owner.entity_id,'source':source,'group':profile['group'],
                 'sequence':sequence,'lifetime':lifetime or ''}})
    cells=target_cells(engine,obj)
    if not legal_placement(engine,cells,obj.height_ft, require_support=profile.get('requires_support', True),
                           occupies_space=profile.get('occupies_space', True)):
        raise ValueError('The work needs unoccupied spaces connected to stable support.')
    if component.get('blocks') and seals_airspace(engine,cells,obj.height_ft):
        raise ValueError('A structure cannot seal a creature inside an airtight space.')
    engine._update_object(obj,source,owner.entity_id)
    refresh(engine)
    return obj


def retire(engine,obj,source):
    if not obj.destroyed:
        engine._update_object(obj.model_copy(update={'destroyed':True,'current_hp':0}),source,obj.owner_id)
        refresh(engine)


def repair_allowed(obj, source_cl, *, material=False):
    c=obj.component or {}
    if obj.current_hp is None or obj.maximum_hp is None or c.get('specialist_reconstruction'):
        return False
    if c.get('artifact') and obj.destroyed:
        return False
    if obj.destroyed and not material:
        return False
    if c.get('repair_allowed') is False or c.get('absolute_repair_protection'):
        return False
    return True


def refresh(engine):
    """Synchronize a native combat grid or an explicit journey geometry adapter."""
    if hasattr(engine,'asset_runtime_refresh'):
        engine.asset_runtime_refresh()
    else:
        from . import zones
        zones.sync_walls(engine)


def seals_airspace(engine,cells,height_ft):
    """Whether this solid addition closes the last native air route of a creature.

    Uses committed terrain/roof/object volumes. An existing sealed space is not
    attributed to the new work. Open sky remains an outlet; support never implies
    a ceiling. Called at actual creation, not while enumerating hidden choices.
    """
    from collections import deque
    ceilings=[*(getattr(engine.grid.roof_geometry,'heights',()) or ()),height_ft]
    ceilings += [int(o.position.z*5+(o.height_ft or 5)) for o in engine.state.objects.values() if not o.destroyed]
    top=max(ceilings,default=10)//5+2
    existing={(c.x,c.y,z) for obj in engine.state.objects.values() if not obj.destroyed
        and not ((obj.component or {}).get('air_passage') or (obj.component or {}).get('mechanism',{}).get('open'))
        for c in target_cells(engine,obj) for z in range(c.z,c.z+max(1,((obj.height_ft or 5)+4)//5))}
    addition={(c.x,c.y,z) for c in cells for z in range(c.z,c.z+(height_ft+4)//5)}
    def reaches_air(start,blocked):
        seen={start};queue=deque([start])
        while queue:
            x,y,z=queue.popleft()
            if z>=top or x in (0,engine.grid.width-1) or y in (0,engine.grid.height-1):return True
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                key=(x+dx,y+dy,z+dz)
                if key in seen or key in blocked or key[2]<0:continue
                if not engine.grid.volume_legal(Position(x=key[0],y=key[1],z=key[2])):continue
                seen.add(key);queue.append(key)
        return False
    for actor in engine.state.actors.values():
        if not actor.active:continue
        start=(actor.position.x,actor.position.y,actor.position.z)
        if reaches_air(start,existing) and not reaches_air(start,existing|addition):return True
    return False
