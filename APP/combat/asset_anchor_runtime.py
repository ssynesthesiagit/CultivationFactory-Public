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


def remaining_lifetime_token(engine, seconds):
    """A fixed elapsed lifetime at the first native slot at/after its deadline.

    Construction and timed Asset continuation use actual integer/Fraction
    seconds, not source-turn counters. Returns a recognized expiry string;
    never mutates the engine. Absent a caller, legacy clocks remain unchanged.
    """
    from fractions import Fraction
    if type(seconds) is not int and not isinstance(seconds,Fraction):
        raise ValueError('A remaining lifetime requires exact integer or rational seconds.')
    remaining=Fraction(seconds)
    if remaining<=0:raise ValueError('An ended lifetime cannot be imported.')
    slots=max(1,len(engine.state.initiative_order))
    ticks=remaining*slots/6
    count=(ticks.numerator+ticks.denominator-1)//ticks.denominator
    deadline=(engine.state.round_number-1)*slots+engine.state.current_slot_index+count
    return f'START_OF_SLOT_AT:{deadline//slots+1}:{deadline%slots}'



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


def legal_placement(engine, cells, height_ft, *, ignore=(), require_support=True, observer=None):
    if ignore:
        shadow=without_objects(engine,ignore)
        return legal_placement(shadow,cells,height_ft,require_support=require_support,observer=observer)
    if type(height_ft) is not int or height_ft < 1 or not cells:
        return False
    volume = {(c.x,c.y,z) for c in cells for z in range(c.z,c.z+(height_ft+4)//5)}
    if len({(c.x,c.y,c.z) for c in cells}) != len(cells):
        return False
    if any(not engine.grid.volume_legal(Position(x=x,y=y,z=z)) for x,y,z in volume):
        return False
    actors=engine.state.actors.values()
    if observer is not None:
        from .target_knowledge import actors_for,knowledge
        actors=[a for a in actors_for(engine,observer) if (known:=knowledge(engine,observer,a)) is not None and known.mode=='DIRECT']
    if any(volume & set(engine._actor_volume(a)) for a in actors if a.active):
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
    if not isinstance(source,str) or not source or not owner.entity_id or engine.state.actors.get(owner.entity_id) is not owner:
        raise ValueError('Asset creation requires its native owner and source.')
    sequence = max([engine.state.event_sequence,*[int(o.component[KEY]['sequence']) for o in members(engine,owner.entity_id,live=False)]])+1
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
    if not legal_placement(engine,cells,obj.height_ft):
        raise ValueError('The work needs unoccupied spaces connected to stable support.')
    if profile.get('forbid_airtight') and not component.get('air_passage') and seals_airspace(engine,cells,obj.height_ft):
        raise ValueError('A structure cannot seal a creature inside an airtight space.')
    engine._update_object(obj,source,owner.entity_id)
    refresh(engine)
    return obj


def retire(engine,obj,source):
    if not obj.destroyed or (KEY in obj.component and not obj.component[KEY].get('ended')):
        component=obj.component
        if KEY in component:component={**component,KEY:{**component[KEY],'ended':True}}
        engine._update_object(obj.model_copy(update={'destroyed':True,'current_hp':0,'component':component}),source,obj.owner_id)
        refresh(engine)


def repair_allowed(obj, source_cl, *, material=False, preview=False):
    c=obj.component or {}
    if obj.current_hp is None or obj.maximum_hp is None:return False
    if preview and c.get('asset_declaration',{}).get('visibility')=='gm':
        return not (obj.destroyed and (not material or c.get('artifact')))
    if c.get('specialist_reconstruction'):
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
    from .object_rules import simple_door_state
    roofs=engine.grid.roof_surfaces
    ceilings=[r.height_ft for r in roofs]
    ceilings += [int(o.position.z*5+(o.height_ft or 5)) for o in engine.state.objects.values() if not o.destroyed]
    ceilings += [c.z*5+height_ft for c in cells]
    top=max(ceilings,default=10)+2
    # Feet, rather than five-foot body voxels: a three-foot Low Wall cannot
    # close the air gap below a five-foot ceiling. Native roofs block vertical
    # transitions at their actual plane, not the open air on either side.
    existing={(c.x,c.y,z) for obj in engine.state.objects.values() if not obj.destroyed
        and not ((obj.component or {}).get('air_passage') or (obj.component or {}).get('mechanism',{}).get('open') or (simple_door_state(obj.component or {}) or {}).get('door_open'))
        for c in target_cells(engine,obj) for z in range(c.z*5,c.z*5+(obj.height_ft or 5))}
    addition={(c.x,c.y,z) for c in cells for z in range(c.z*5,c.z*5+height_ft)}
    spans=engine.grid.terrain_spans.get('BLOCKED',{})
    def reaches_air(start,blocked):
        seen={start};queue=deque([start])
        while queue:
            x,y,z=queue.popleft()
            if z>=top or x in (0,engine.grid.width-1) or y in (0,engine.grid.height-1):return True
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                key=(x+dx,y+dy,z+dz)
                if key in seen or key in blocked or key[2]<0:continue
                if not engine.grid.in_bounds(key[:2]):continue
                if any(low<=key[2] and (high is None or key[2]<high) for low,high in spans.get(key[:2],())):continue
                if dz and any(min(z,key[2])<r.height_ft<=max(z,key[2]) and r.solid_at(x,y) for r in roofs):continue
                seen.add(key);queue.append(key)
        return False
    for actor in engine.state.actors.values():
        if not actor.active:continue
        start=(actor.position.x,actor.position.y,actor.position.z*5)
        if reaches_air(start,existing) and not reaches_air(start,existing|addition):return True
    return False


def without_objects(engine,ignored):
    """Read-only geometry context after removing exactly these runtime objects."""
    from copy import copy,deepcopy
    shadow=copy(engine)
    if hasattr(engine,'session'):
        from .journey_assets import grid_for
        shadow.grid=grid_for(engine.session,ignore=ignored)
        shadow.state=copy(engine.state)
        shadow.state.objects={k:o for k,o in engine.state.objects.items() if k not in ignored}
    else:
        shadow.grid=deepcopy(engine.grid)
        shadow.state=engine.state.model_copy(update={'objects':{k:o for k,o in engine.state.objects.items() if k not in ignored}})
        from . import zones
        zones.sync_walls(shadow)
    return shadow


PROFILE_FIELDS=('source_cl','repair_allowed','specialist_reconstruction','absolute_repair_protection','repair_save_dc','formation_anchor','repair_contested','artifact_destruction_sources','cultivation_asset')


def declared_profile(value,object_id):
    """Validate an explicit native scene-owner object declaration.

    Map authoring is the GM input boundary. No profile is inferred from names,
    damage, inactivity or narration. Private declarations remain server-side in
    the sealed battlefield/object snapshots; public table maps omit their facts.
    """
    requested={k:value[k] for k in PROFILE_FIELDS if k in value}
    if not requested:return {}
    declaration=value.get('asset_declaration')
    fields={'actor','authority','source_rule','visibility','expiry'}
    if not isinstance(declaration,dict) or set(declaration) not in (fields,fields|{'object_id'}):
        raise ValueError('An Asset profile needs actor, GM authority, source rule, visibility and expiry declarations.')
    # Normalized maps are read through this same validator on every cold load.
    # Accept only our exact object binding; never transfer another declaration.
    if 'object_id' in declaration and (type(declaration['object_id']) is not int or declaration['object_id']!=int(object_id)):
        raise ValueError('An Asset declaration must remain bound to its actual map object.')
    if declaration['authority']!='GM' or declaration['visibility'] not in ('public','gm') or declaration['expiry']!='source_rule':
        raise ValueError('Use GM authority, public or gm visibility, and source_rule expiry for an object profile.')
    if any(not isinstance(declaration[k],str) or not declaration[k].strip() or len(declaration[k])>500 for k in ('actor','source_rule')):
        raise ValueError('Name the actual scene owner and governing source rule.')
    for k,v in requested.items():
        if k=='artifact_destruction_sources':
            if not isinstance(v,list) or len(v)>100 or len(v)!=len(set(v)) or not all(isinstance(x,str) and 0<len(x)<=240 for x in v):raise ValueError('Artifact destruction sources must be distinct bounded source IDs.')
        elif k in ('source_cl','repair_save_dc'):
            if type(v) is not int or not 0<=v<=1000:raise ValueError(k+' must be a nonnegative integer no greater than 1000.')
        elif type(v) is not bool:raise ValueError(k+' must be a boolean.')
    return {**requested,'asset_declaration':{**declaration,'object_id':int(object_id)}}


def public_map_object(row):
    """Return the public map view; private authority facts never become labels."""
    if (row.get('asset_declaration') or {}).get('visibility')!='gm':return row
    return {k:v for k,v in row.items() if k not in (*PROFILE_FIELDS,'asset_declaration')}


def source_profile(engine,obj):
    """Read Source CL/creator from committed object or linked Anchor state."""
    c=obj.component or {};cl=c.get('source_cl');owner=obj.owner_id
    if cl is None and obj.object_kind.lower()=='spirit_asset':cl=(c.get('spirit_asset') or {}).get('source_cl')
    if cl is None:
        zone=engine.state.zones.get(c.get('formation')) if hasattr(engine.state,'zones') else None
        if zone is not None:
            cl=(zone.trigger_profile.get('numbers') or {}).get('cl');owner=owner or zone.owner_id
    bound=c.get('bound') or {}
    source=c.get('created_by') or bound.get('source')
    owner=owner or bound.get('owner')
    if cl is None and source:
        action=(getattr(engine,'action_catalog',{}) or {}).get(source)
        if action is not None:cl=((action.parameters or {}).get('typed') or {}).get('numbers',{}).get('cl')
    return {'source_cl':int(cl or 0),'owner':owner,'source':source or ''}



def is_asset(obj):
    """Explicit native Asset profiles, including the shared spirit-asset producer.

    No name, team, narration or damage type classifies an object as an Asset.
    """
    return obj.object_kind.lower() in ('cultivation_asset','spirit_asset') or (obj.component or {}).get('cultivation_asset') is True
