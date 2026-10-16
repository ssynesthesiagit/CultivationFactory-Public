"""Source-scoped information shared by Bell-Tower and future observers.

``publish(engine, viewer, source, owner, kind, details, expires)`` commits a
private reading as an ordinary condition. ``readings(engine, viewer)`` returns
only that viewer's active readings. Directions never grant sight, identity or
an exact position. All values are JSON primitives; normal condition persistence,
expiry and mechanical replay apply. No grants means no state or query changes.

``sources(engine)`` derives ongoing sources from native conditions and zones.
Authored ``information_profile`` metadata supplies classifications that cannot
be inferred mechanically. It never guesses a tag from damage, names or prose.
Subjective declarations use the normal owner-bound choice transport in the
source plug-in; publication alone cannot establish mechanical authority.
"""
from copy import deepcopy

READING = 'condition:information.reading'
SOURCE = 'condition:information.source'
KINDS = frozenset({'direction', 'resonance', 'concealment_exists', 'field_event', 'declaration'})


def primitives(value):
    if value is None or type(value) in (str, int, bool):
        return True
    if isinstance(value, (list, tuple)):
        return all(primitives(v) for v in value)
    return isinstance(value, dict) and all(type(k) is str and primitives(v) for k, v in value.items())


def direction(origin, target):
    dx, dy, dz = target.x-origin.x, target.y-origin.y, target.z-origin.z
    planar = ('north' if dy < 0 else 'south' if dy > 0 else '') + ('east' if dx > 0 else 'west' if dx < 0 else '')
    return ' '.join(part for part in (planar, 'above' if dz > 0 else 'below' if dz < 0 else '') if part) or 'here'


def publish(engine, viewer, source, owner, kind, details, expires):
    if kind not in KINDS or not source or not expires or not primitives(details):
        raise ValueError('Information requires a typed kind, source, expiry and primitive details')
    if engine.state.actors.get(viewer.entity_id) is not viewer or engine.state.actors.get(owner.entity_id) is not owner:
        raise ValueError('Information must bind live native actors')
    from .alternative_payments import owned
    action=engine.action_catalog.get(source)
    if not ((action is not None and action.owner_id==owner.entity_id) or owned(engine,owner,source)):
        raise ValueError('Information authority must belong to its actual source owner')
    engine._apply_condition(viewer, READING, source, owner.entity_id, expires_on=expires,
        data={'kind':kind, 'viewer_id':viewer.entity_id, 'authority_actor_id':owner.entity_id,
              'source_id':source, 'details':deepcopy(details), 'label':'Private supernatural information'})


def readings(engine, viewer):
    """A viewer's information only; caller must project this list to that seat."""
    if engine.state.actors.get(viewer.entity_id) is not viewer:
        return []
    stored = [deepcopy(c.data) for c in viewer.conditions.values()
            if c.condition_id == READING and c.data.get('viewer_id') == viewer.entity_id]
    from . import ext
    for rows in ext.run_strict('observer_information_rows', engine, viewer):
        if not isinstance(rows,list) or not primitives(rows):
            raise ValueError('Observer information must contain primitive rows')
        stored.extend(deepcopy(rows))
    return stored


def source_numbers(engine, source, owner_id):
    from .ext.source_eligibility import catalog_action
    action = catalog_action(engine,source)
    if action is not None:
        numbers = (action.parameters.get('typed') or {}).get('numbers') or {}
        if numbers:
            return numbers
    bundle = next((b for b in getattr(engine, 'typed_bundle_documents', ()) if b.get('actor_id') == owner_id), {})
    # A missing source is unknown, not an invented CL1/DC10 effect. Live source
    # profiles supplied by information_sources carry both derived numbers.
    return {'cl':int(bundle['cl'])} if bundle.get('cl') else {}


def source_profile(engine, source, data):
    """Merge explicit source classification with authenticated printed authority.

    This uses the shared category reader rather than treating every Charmed
    condition as an ordinary, removable power. Unknown sources stay unknown.
    """
    from .ext.source_eligibility import stored_power,protected_power
    profile=deepcopy(data.get('information_profile') or {})
    power=stored_power(engine,source)
    if power:
        typed,text=power
        if protected_power(typed,text,permanent_transformations=True,
                extra_categories=('Curse','Foundation Injury','Secret Law')):
            profile['authority']='protected'
        else:
            profile.setdefault('authority','ordinary')
    else:
        profile.setdefault('authority','unknown')
    return profile


def save_ability(engine, source, holder_id, applied_sequence):
    """Recover a relevant save from its actual committed native roll receipt."""
    for event in reversed(engine.events):
        if event.sequence>=applied_sequence:
            continue
        if event.event_type=='SAVE_ROLLED' and event.actor_id==holder_id and event.source_definition_id==source:
            ability=str(event.payload.get('reason') or '').rsplit(':',1)[-1].upper()
            return ability if ability in {'STR','DEX','CON','INT','WIS','CHA'} else None
    return None


def sources(engine):
    """Actual active sources, with no assertion that any observer perceives them.

    Consumers must enforce range, plane, visibility and limited-knowledge output.
    Source identity is the condition/zone instance, so changed effects invalidate
    a previous failed-attempt lock without broadening it to unrelated effects.
    """
    result = []
    conventional = {'charmed','frightened','deafened','invisible'}
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id == READING:
                continue
            tail = condition.condition_id.removeprefix('condition:typed.')
            profile = source_profile(engine,condition.source_definition_id,condition.data)
            tags = set(profile.get('tags') or [])
            if tail in conventional:
                tags.add(tail)
            if not tags:
                continue
            nums = source_numbers(engine, condition.source_definition_id, condition.source_actor_id)
            result.append({'id':condition.instance_id, 'source':condition.source_definition_id,
                'owner_id':condition.source_actor_id, 'holder_id':actor.entity_id,
                'position':actor.position, 'tags':sorted(tags),
                'cl':profile.get('source_cl') or nums.get('cl'),
                'dc':profile.get('save_dc') or nums.get('save_dc'),
                'save_ability':profile.get('save_ability') or save_ability(engine,condition.source_definition_id,actor.entity_id,condition.applied_sequence), 'condition':condition,
                'revision':condition.applied_sequence, 'profile':profile})
    for zone in engine.state.zones.values():
        profile = zone.trigger_profile.get('information_profile') or {}
        if zone.active and profile.get('tags'):
            nums = zone.trigger_profile.get('numbers') or source_numbers(engine,zone.source_definition_id,zone.owner_id)
            result.append({'id':zone.zone_id, 'source':zone.source_definition_id, 'owner_id':zone.owner_id,
                'holder_id':None, 'position':zone.center, 'tags':profile['tags'],
                'cl':profile.get('source_cl') or nums.get('cl'),
                'dc':profile.get('save_dc') or nums.get('save_dc'),
                'save_ability':profile.get('save_ability'), 'zone':zone,
                'revision':zone.created_round, 'profile':profile})
    result.extend(world_sources(engine))
    return result


def normalize_world_sources(rows, width, height):
    """Map-owner authored fixed environmental effects, never actor declarations.

    Empty/absent input is inert. Profiles require explicit geometry, affected
    materials/authority, Source CL/DC and the source's contest bonus. Values are
    sealed with the native map, not inferred from names or visual decoration.
    """
    if rows is None:return []
    if not isinstance(rows,list) or len(rows)>64:raise ValueError('Use at most 64 environmental source profiles.')
    out=[];ids=set()
    required={'id','name','shape','x','y','z','size_ft','height_ft','source_cl','save_dc','check_bonus','removes','targets','duration_rounds','cadence_rounds','source_rule'}
    for row in rows:
        if not isinstance(row,dict) or set(row)!=required:raise ValueError('Supply the complete environmental source profile.')
        if (not isinstance(row['id'],str) or not row['id'] or len(row['id'])>80 or row['id'] in ids
                or not isinstance(row['name'],str) or not row['name'].strip() or len(row['name'])>120):
            raise ValueError('Environmental source identities and names must be distinct bounded text.')
        if not isinstance(row['source_rule'],str) or not row['source_rule'].strip() or len(row['source_rule'])>2000:
            raise ValueError('Supply the environmental source’s controlling rule.')
        if row['shape'] not in ('sphere','cube','cylinder'):raise ValueError('Choose a sphere, cube or cylinder.')
        for key,low,high in [('x',0,width-1),('y',0,height-1),('z',0,100),('size_ft',5,600),('height_ft',5,600),
                             ('source_cl',0,40),('save_dc',1,60),('check_bonus',-20,60),('duration_rounds',0,14400),('cadence_rounds',1,14400)]:
            if type(row[key]) is not int or not low<=row[key]<=high:raise ValueError('Environmental source statistics must be bounded whole numbers: '+key)
        if (not isinstance(row['removes'],list) or not row['removes']
                or any(type(v) is not str for v in row['removes']) or len(set(row['removes']))!=len(row['removes'])
                or not set(row['removes'])<={'smoke','dust','airborne_particles'}):raise ValueError('Name exactly the particles this source removes.')
        if row['targets'] not in ('mundane','cultivated','both'):raise ValueError('Name whether the source removes mundane or cultivated particles, or both.')
        ids.add(row['id']);out.append(deepcopy(row))
    return out


def world_sources(engine):
    """Pure fixed sources from the native sealed map; no actor gains authority."""
    from .gate2_runtime_models import Position
    doc=getattr(engine,'battlefield_document',{}) or {}
    rows=doc.get('world_sources') or []
    elapsed=max(0,int(getattr(engine.state,'round_number',1))-1)
    return [{'id':'world:'+r['id'],'source':'world:'+r['id'],'owner_id':'map','holder_id':None,
        'position':Position(x=r['x'],y=r['y'],z=r['z']), 'tags':['particle_removal'],
        'cl':r['source_cl'],'dc':r['save_dc'],'revision':0,'profile':deepcopy(r)}
        for r in rows if not r['duration_rounds'] or elapsed<r['duration_rounds']]
