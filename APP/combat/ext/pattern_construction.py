"""Elapsed physical construction shared by Trap and Formations.

Uses the existing journey command/admission/replay and combat-setup contracts
from stock-materials (5ca14d86f), with no parallel inventory or fact transport.
A construction_site admission records only a bounded physical site, not an
ability outcome. Actor commands select known patterns, pay costs and advance
real elapsed seconds. Records expire on that source clock and are projected
into native zone/object state when the journey enters combat on the same map.
"""
from copy import deepcopy
from fractions import Fraction
import json
from . import hook, placed
from ..journey import require, integer
from ..gate2_runtime_models import Position

TRAP = 'tianxia.sphere.trap'
SET = 'FORMATIONS_BASE_SET_ARRAY'
PRIVATE_EVENTS = frozenset((
    'PATTERN_CONSTRUCTED', 'CONSTRUCTION_COLLAPSED', 'CONSTRUCTED_TRAP_DISARMED',
    'CONSTRUCTION_PATTERN_LEARNED', 'TRAP_KEY_ABILITY_CHOSEN',
    'FORMATION_DAMAGE_TYPE_DECLARED', 'CONSTRUCTION_SITE_RECORDED',
    'CONSTRUCTED_PATTERNS_RECONCILED', 'CONSTRUCTION_PLANNING',
))


def profile(session, aid):
    return session.state['actors'][aid]['bundle'].get('construction_contract', {})


def components(bundle, family, *, engine=None, actor=None, journey_actor=None):
    items = (bundle.get('carrying') or {}).get('items', ())
    from .. import carry
    ids = {i['item_id'] for i in items if i.get('quantity', 0) > 0
           and (engine is None or carry.holds(engine,actor,i['key']))
           and (journey_actor is None or carry.journey_holds(journey_actor, i['key']))}
    if family == 'trap':
        return 'tianxia.mortal.tool.thieves_tools' in ids
    return any(i in ids for i in ('tianxia.mortal.gear.chalk', 'tianxia.mortal.gear.ink',
                                  'tianxia.mortal.gear.paper', 'tianxia.mortal.tool.formation_kit'))


@hook('compile_bundle')
def compile_construction(bundle, info):
    ids = set(info.get('owned_ids', ()))
    trap = any(r.get('parameters', {}).get('set_trap') for r in bundle['action_catalog'])
    if not trap and SET not in ids:
        return None
    from .formations import known_patterns, owned_talents
    sheet = info['owner_sheet']
    listed = (sheet.get('spheres_and_talents') or {}).get('formation_patterns')
    out = deepcopy(bundle)
    from ..factory_compiler import RESOURCE_IDS
    out['construction_contract'] = {'trap': int(trap), 'array': int(SET in ids),
        'numbers': dict(info['numbers']), 'patterns': known_patterns({'owner_sheet': sheet, 'owned_ids': ids}) if listed else [],
        'formation_talents':owned_talents({'owned_ids':ids}), 'damage_types':{},
        'pool': RESOURCE_IDS.get(str(info['primary']).lower(), 'resource:core.qi'),
        'trap_tools': int(components(bundle, 'trap')), 'trap_key':(sheet.get('spheres_and_talents') or {}).get('trap_key_ability',''), 'mods':dict(info['mods']), 'array_markers': int(components(bundle, 'array'))}
    return out


def source_clock(session, aid):
    actor = session.state['actors'][aid]
    return Fraction(actor.get('construction_clock_num', 0), actor.get('construction_clock_den', 1))


def damage_permissions(session, aid):
    """Source declarations remain authoritative after a fresh compilation."""
    return {**profile(session, aid).get('damage_types', {}),
            **session.state['actors'][aid].get('formation_damage_permissions', {})}


def expiry(record):
    return Fraction(record['expires_num'], record['expires_den']) if 'expires_num' in record else Fraction(record['expires'])


@hook('journey_elapsed')
def elapsed(session, aid, before, seconds, moving):
    if not profile(session, aid):
        return
    clock = source_clock(session, aid) + seconds
    actor = session.state['actors'][aid]
    actor['construction_clock_num'], actor['construction_clock_den'] = clock.numerator, clock.denominator


@hook('journey_persistent_fields')
def persistent():
    return ('constructed_patterns', 'construction_learning', 'construction_clock_num', 'construction_clock_den', 'formation_damage_permissions')


@hook('journey_shared_fields')
def shared():
    return ('construction_sites',)


def position(session, raw):
    require(isinstance(raw, dict) and {'x', 'y'} <= set(raw) <= {'x', 'y', 'z'} and
            all(integer(v) for v in raw.values()), 'Choose whole, nonnegative map coordinates.')
    p = Position.model_validate(raw)
    require(session.grid.volume_legal(p) and (p.z == 0 or session.grid.roof_supported(p)),
            'Construction needs a solid supported map space.')
    return p


def connected(cells):
    left = set((p.x, p.y, p.z) for p in cells)
    reached = {left.pop()}
    while left:
        add = {p for p in left if any(max(abs(a-b) for a, b in zip(p, q)) == 1 for q in reached)}
        if not add:
            return False
        reached |= add
        left -= add
    return True


def component_spaces(session, cells):
    """Legal installation spaces inside an effect footprint, for defaults and picker.

    An array's effect can cover walls or unsupported air; its physical Nodes
    still need the same solid/support validation as an explicitly placed Eye.
    Preserve footprint order and every legal space without capping choices.
    """
    out = []
    for raw in cells:
        try:
            position(session, raw)
        except ValueError:
            continue
        out.append(raw)
    return out


def available_site(session, aid, site, center):
    """Picker/executor authority: a known, supported site on this physical map."""
    if (not site or not site.get('map_id') or
            site['map_id'] != session.state['battlefield'].get('stable_id') or aid not in site['known_to']):
        return False
    cells = [Position.model_validate(c) for c in site['cells']]
    return (center in cells and all(session.grid.volume_legal(p) and
            (p.z == 0 or session.grid.roof_supported(p)) for p in cells))


@hook('journey_admission')
def site(session, aid, kind, payload, reason):
    if kind=='formation_damage_type':
        from .formations import KILLING_TYPES
        p=profile(session,aid)
        require(p.get('array') and set(payload)=={'damage_type','source_logic'} and payload['damage_type'] in KILLING_TYPES,
                'Choose a printed Killing Line damage type for an acquired Formation source.')
        require(isinstance(payload['source_logic'],str) and 1<=len(payload['source_logic'].strip())<=1000,
                'Record the actual source logic approved by the GM.')
        fact={'damage_type':payload['damage_type'],'source_logic':payload['source_logic'].strip(),
              'provenance':reason,'authority':'GM'}
        session.state['actors'][aid].setdefault('formation_damage_permissions',{})[payload['damage_type']]=fact
        p['damage_types'][payload['damage_type']]=fact
        session.emit('FORMATION_DAMAGE_TYPE_DECLARED',aid,damage_type=payload['damage_type'])
        return True
    if kind != 'construction_site':
        return None
    require(set(payload) == {'id', 'name', 'kind', 'cells', 'known_to'}, 'Record a complete bounded construction site.')
    require(isinstance(payload['id'], str) and 0 < len(payload['id']) < 121 and
            payload['id'] not in session.state.get('construction_sites', {}), 'Use a new stable site identity.')
    require(payload['kind'] in ('room', 'courtyard', 'gatehouse', 'bridge', 'bounded_site'), 'Choose the actual bounded site type.')
    require(isinstance(payload['name'], str) and 0 < len(payload['name']) < 201, 'Name the physical site.')
    require(isinstance(payload['cells'], list) and payload['cells'], 'Map every space of this bounded site.')
    cells = [position(session, p) for p in payload['cells']]
    require(len(set((p.x,p.y,p.z) for p in cells)) == len(cells) and connected(cells), 'A site must have distinct connected spaces.')
    require(isinstance(payload['known_to'], list) and all(a in session.state['actors'] for a in payload['known_to']),
            'Name the creatures who know the site.')
    map_id = session.state['battlefield'].get('stable_id')
    require(isinstance(map_id, str) and bool(map_id), 'A surveyed site needs a stable physical map identity.')
    session.state.setdefault('construction_sites', {})[payload['id']] = {
        **deepcopy(payload), 'provenance': reason, 'map_id': map_id}
    session.emit('CONSTRUCTION_SITE_RECORDED', aid, site_id=payload['id'])
    return True


@hook('journey_view')
def view(state, viewer):
    if ('construction_sites' not in state and not any(any(k in a for k in (
            'constructed_patterns','construction_learning','formation_damage_permissions','construction_draft'))
            for a in state['actors'].values()) and not any(
            event.get('kind') in PRIVATE_EVENTS for event in state.get('events', ()))):
        return None
    out = deepcopy(state)
    out.pop('replay_base',None); out.pop('command_journal',None)
    if 'construction_sites' in out:
        out['construction_sites'] = {k:v for k,v in out['construction_sites'].items()
            if viewer in v['known_to'] and v.get('map_id') == out['battlefield'].get('stable_id')}
    for aid,actor in out['actors'].items():
        if aid!=viewer:
            for key in ('constructed_patterns','construction_learning','formation_damage_permissions','construction_draft'):
                actor.pop(key,None)
            actor.get('bundle',{}).get('construction_contract',{}).pop('damage_types',None)
    out['events'] = [event for event in out.get('events', ())
                     if event.get('kind') not in PRIVATE_EVENTS or event.get('actor_id') == viewer]
    return out


@hook('journey_options')
def menu(session, aid):
    actor = session.state['actors'][aid]
    if session.state['phase'] != 'travel' or actor['incapacitated']:
        return None
    p = profile(session, aid)
    options = []
    known = actor.get('construction_learning', {}).get('pattern')
    if p.get('array') and not p['patterns'] and not known:
        from .formations import PATTERNS
        options.extend({'id': 'learn_pattern:' + key, 'kind': 'learn_construction_pattern', 'payload': {'pattern': key},
                        'auto_select': 0, 'label': 'Formation Training: learn ' + row['name'] + ' as your first Basic Pattern.'}
                       for key,row in PATTERNS.items() if not row.get('talent'))
    if p.get('trap') and not p.get('trap_key') and not actor.get('construction_learning',{}).get('trap_key'):
        options.extend({'id':'trap_key:'+key,'kind':'choose_trap_key','payload':{'ability':key},'auto_select':0,
            'label':'Trap Training: choose '+label+' as your permanent Trap key ability.'}
            for key,label in (('DEX','Dexterity'),('INT','Intelligence')))
    for r in actor.get('constructed_patterns',()):
        if r['family']!='trap' or r.get('map_id')!=session.state['battlefield'].get('stable_id',''):
            continue
        if session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(r['center']))>5:
            continue
        if expiry(r)>source_clock(session,aid):
            options.append({'id':'disarm:'+r['id'],'kind':'disarm_constructed','payload':{'device':r['id']},
                'auto_select':0,'label':f"Disarm your trap at ({r['center']['x']}, {r['center']['y']}); one Action, no check for its creator."})
        elif r.get('payload',{}).get('remaining',0):
            options.append({'id':'recover:'+r['id'],'kind':'recover_constructed_payload','payload':{'device':r['id']},
                'auto_select':0,'label':'Recover unused consumables from your inactive trap; no cost.'})
    return options


@hook('journey_command')
def command(session, aid, kind, data):
    if kind not in ('learn_construction_pattern', 'choose_trap_key', 'prepare_array', 'construct_trap', 'disarm_constructed', 'recover_constructed_payload'):
        return None
    p = profile(session, aid)
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'An incapacitated creature cannot construct a device.')
    if kind == 'choose_trap_key':
        require(set(data)=={'ability'} and data['ability'] in ('DEX','INT') and p.get('trap')
                and not p.get('trap_key') and not actor.get('construction_learning',{}).get('trap_key'),
                'Trap Training lets its learner choose Dexterity or Intelligence once.')
        actor.setdefault('construction_learning',{})['trap_key']=data['ability']
        session.emit('TRAP_KEY_ABILITY_CHOSEN',aid,ability=data['ability'])
        return True
    if kind in ('disarm_constructed','recover_constructed_payload'):
        require(set(data)=={'device'}, 'Choose one actual constructed device.')
        r=next((r for r in actor.get('constructed_patterns',()) if r['id']==data['device']),None)
        require(r is not None and r['family']=='trap' and r.get('map_id')==session.state['battlefield'].get('stable_id','')
                and session.grid.distance_ft(Position.model_validate(actor['position']), Position.model_validate(r['center']))<=5,
                'Choose your own recorded trap within reach on this map.')
        if kind=='disarm_constructed':
            require(expiry(r)>source_clock(session,aid), 'This trap is already inactive.')
            session.tick(6)
            r.update(expires_num=source_clock(session,aid).numerator,expires_den=source_clock(session,aid).denominator)
            session.emit('CONSTRUCTED_TRAP_DISARMED',aid,device_id=r['id'])
        else:
            require(expiry(r)<=source_clock(session,aid) and r.get('payload',{}).get('remaining',0)>0,
                    'Recover actual unused payload only from an inactive trap.')
            from .consumable_payloads import release_journey
            release_journey(session,aid,r['payload'])
            r['payload']['remaining']=0
        return True
    if kind == 'learn_construction_pattern':
        from .formations import PATTERNS
        require(set(data) == {'pattern'} and p.get('array') and not p['patterns'] and
                not actor.get('construction_learning', {}).get('pattern') and
                data['pattern'] in PATTERNS and not PATTERNS[data['pattern']].get('talent'),
                'Formation Training grants one first Basic Pattern, chosen by its learner.')
        actor.setdefault('construction_learning',{})['pattern']=data['pattern']
        p['patterns'] = [data['pattern']]
        session.emit('CONSTRUCTION_PATTERN_LEARNED', aid, pattern=data['pattern'])
        return True
    records = actor.setdefault('constructed_patterns', [])
    if kind == 'prepare_array':
        from .formations import load_of, KILLING_TYPES, construction_radius
        require({'pattern', 'center', 'site', 'damage_type'} <= set(data) <= {'pattern','center','site','damage_type','layers','nodes','replace'} and p.get('array') and components(actor['bundle'], 'array', journey_actor=actor),
                'Prepared Array requires Set Array and carried formation markers.')
        known = p['patterns'] or [actor.get('construction_learning', {}).get('pattern')]
        layers=data.get('layers') or [data['pattern']]
        require(isinstance(layers,list) and layers and layers[0]==data['pattern'] and len(layers)==len(set(layers))
                and all(k in known for k in layers), 'Choose only Pattern Layers you actually learned.')
        require(len(layers)==1 or (len(layers)==2 and 'layered_pattern' in p['formation_talents'] and int(p['numbers']['cl'])>=5),
                'A second layer requires the acquired Layered Pattern talent at CL 5 or higher.')
        if 'killing_line' in layers:
            require(data['damage_type'] in damage_permissions(session, aid), 'Killing Line needs a GM-declared damage type and source logic.')
        require(data['damage_type'] in KILLING_TYPES, 'Choose a legal source-backed Killing Line damage type.')
        center = position(session, data['center'])
        here = Position.model_validate(actor['position'])
        require(session.grid.distance_ft(here, center) <= 5 and session.grid.line_of_sight(here, center), 'Prepared Array has Touch range.')
        radius=construction_radius({'formation_talents':p['formation_talents']},mode='prepared')
        if data['site']:
            site = session.state.get('construction_sites', {}).get(data['site'])
            require(available_site(session, aid, site, center), 'Choose a known bounded physical site on this map.')
            cells = site['cells']
        else:
            cells = [Position(x=x,y=y,z=center.z).model_dump(mode='json') for x in range(session.grid.width)
                     for y in range(session.grid.height) if session.grid.distance_ft(center, Position(x=x,y=y,z=center.z)) <= radius]
        legal_nodes = component_spaces(session, cells)
        require(len(legal_nodes) >= 3, 'A Prepared Array needs three supported, unobstructed Node spaces.')
        nodes = legal_nodes[:3]
        if data.get('nodes') is not None:
            nodes=data['nodes']
            require(isinstance(nodes,list) and len(nodes)==3, 'Choose three distinct installed Node spaces inside the site.')
            positions=[position(session,n) for n in nodes]
            require(len({(n.x,n.y,n.z) for n in positions})==3 and all(
                n in [Position.model_validate(c) for c in legal_nodes] for n in positions),
                'Choose three distinct installed Node spaces inside the site.')
        pool = p['pool']
        cost=3+2*(len(layers)-1)
        require(actor['resources'].get(pool, 0) >= cost, 'Pay 3 CP, plus 2 CP for a permitted second layer.')
        actor['resources'][pool] -= cost
        session.tick(60 if 'rapid_array' in p['formation_talents'] else 600)
        live = [r for r in records if r['family'] == 'array' and expiry(r) > source_clock(session, aid)]
        if len(live) >= load_of(p['numbers']):
            old=next((r for r in live if r['id']==data.get('replace')),None)
            require(old is not None, 'Choose which of your active arrays collapses when the new array exceeds Formation Load.')
            old.update(expires_num=source_clock(session,aid).numerator, expires_den=source_clock(session,aid).denominator)
            session.emit('CONSTRUCTION_COLLAPSED', aid, device_id=old['id'], reason='Formation Load')
        record = {'family': 'array', 'pattern': data['pattern'], 'damage_type': data['damage_type'],
                  'layers':layers,'numbers':{**p['numbers'],'formation_talents':p['formation_talents'],'formation_pool':p['pool']},
                  'center': data['center'], 'cells': deepcopy(cells), 'nodes': deepcopy(nodes),
                  'expires': session.state['seconds'] + 28800}
    else:
        from .trap import AIMS
        require({'form', 'cells', 'aim'} <= set(data) <= {'form','cells','aim','payload_key','payload_count','origin','replace'} and p.get('trap') and components(actor['bundle'], 'trap', journey_actor=actor), 'Set Trap requires actual thieves’ tools.')
        require(data['form'] in ('dart', 'tripwire', 'activation') and data['aim'] in AIMS and data['aim'] != 'auto', 'Choose a known physical pattern and a fixed direction.')
        cl = int(p['numbers'].get('cl') or 1)
        cells = [position(session, raw) for raw in data['cells']]
        require(1 <= len(cells) <= 1+(cl>=5)+(cl>=10)+(cl>=15) and len({(c.x,c.y,c.z) for c in cells}) == len(cells) and connected(cells), 'Choose a legal contiguous footprint within the CL cap.')
        here = Position.model_validate(actor['position'])
        require(all(session.grid.distance_ft(here,c) <= 5 and session.grid.line_of_sight(here,c) for c in cells), 'All trap spaces must be within natural reach and visible.')
        require(all(not any(a['position'] == c.model_dump(mode='json') for a in session.state['actors'].values()) for c in cells), 'A trap needs unoccupied spaces.')
        require(not any(r['family']=='trap' and r.get('map_id')==session.state['battlefield'].get('stable_id','')
                and expiry(r)>source_clock(session, aid) and any(c == Position.model_validate(raw)
                for c in cells for raw in r['cells']) for r in records), 'Your traps cannot overlap.')
        key=p.get('trap_key') or actor.get('construction_learning',{}).get('trap_key')
        require(key in ('DEX','INT'), 'Choose your Trap key ability through Trap Training first.')
        payload=None
        if data['form']=='activation':
            from .consumable_payloads import reserve_journey
            require({'payload_key','payload_count','origin'} <= set(data) and data['origin'] in data['cells'],
                    'Activation Trap requires actual consumable stock and a chosen occupied-space origin.')
            payload=reserve_journey(session,aid,data['payload_key'],data['payload_count'])
        else:
            require({'form','cells','aim'} <= set(data) <= {'form','cells','aim','replace'}, 'Only Activation Trap loads consumables.')
        session.tick(60)
        live = [r for r in records if r['family']=='trap' and expiry(r)>source_clock(session, aid)]
        if len(live)>=int(p['numbers'].get('pb') or 2):
            old=next((r for r in live if r['id']==data.get('replace')),None)
            require(old is not None, 'Choose which of your active traps disassembles when the new trap exceeds your limit.')
            old.update(expires_num=source_clock(session,aid).numerator,expires_den=source_clock(session,aid).denominator)
            session.emit('CONSTRUCTION_COLLAPSED',aid,device_id=old['id'],reason='Active trap limit')
        record = {'family':'trap', 'form':data['form'], 'aim':data['aim'], 'center':data['cells'][0],
                  'cells':deepcopy(data['cells']), 'expires':session.state['seconds']+3600,
                  'numbers':{**p['numbers'],'key_mod':int(p['mods'][key]),'save_dc':8+int(p['numbers']['pb'])+int(p['mods'][key]),
                             'attack_bonus':int(p['numbers']['pb'])+int(p['mods'][key])},
                  **({'payload':payload,'payload_origin':deepcopy(data['origin'])} if payload else {})}
    end = source_clock(session,aid) + (28800 if record['family']=='array' else 3600)
    record.update(expires_num=end.numerator, expires_den=end.denominator, map_id=session.state['battlefield'].get('stable_id',''))
    record['id'] = f"constructed:{aid}:{len(records)+1}"
    records.append(record)
    actor.pop('construction_draft', None)
    session.emit('PATTERN_CONSTRUCTED', aid, device=deepcopy(record))
    return True


@hook('journey_combat_bundle')
def combat_setup(bundle, session, aid):
    records = [deepcopy(r) for r in session.state['actors'][aid].get('constructed_patterns', ())
               if expiry(r) > source_clock(session, aid) and r.get('map_id') == session.state['battlefield'].get('stable_id','')]
    learning=session.state['actors'][aid].get('construction_learning',{})
    permissions=session.state['actors'][aid].get('formation_damage_permissions')
    if not records and not learning and not permissions:
        return None
    out = deepcopy(bundle)
    if permissions:
        out['construction_contract']['damage_types']=deepcopy(permissions)
    if learning.get('trap_key'):
        for action in out['action_catalog']:
            if action.get('parameters',{}).get('set_trap'):
                action['parameters']['trap_key_ability']=learning['trap_key']
    if learning.get('pattern'):
        out['construction_contract']['patterns']=[learning['pattern']]
    out['constructed_patterns'] = [{**r, 'remaining_seconds': -(-(expiry(r)-source_clock(session,aid)).numerator // (expiry(r)-source_clock(session,aid)).denominator)} for r in records]
    return out


@hook('match_initialize')
def initialize(engine):
    from . import formations as F
    from ..gate2_runtime_models import RuntimeObjectState
    for bundle in engine.typed_bundle_documents:
        owner = engine.state.actors.get(bundle['actor_id'])
        if owner is None:
            continue
        for r in bundle.get('constructed_patterns', ()):
            if r['id'] in engine.state.zones:
                continue
            if r.get('native_zone'):
                from ..gate2_runtime_models import ZoneState
                objects=[RuntimeObjectState.model_validate(json.loads(raw) if isinstance(raw,str) else raw)
                         for raw in r.get('native_objects', ())]
                # Genesis restores the complete component set before publishing
                # either kind of event; collapse checks must not see half a site.
                for obj in objects:
                    engine.state.objects[obj.object_id]=obj
                raw = json.loads(r['native_zone']) if isinstance(r['native_zone'],str) else deepcopy(r['native_zone'])
                raw.update(created_round=engine.state.round_number, duration_rounds=(r['remaining_seconds']+5)//6,
                           per_turn_triggered={})
                zone = ZoneState.model_validate(raw)
                engine.state.zones[zone.zone_id] = zone
                engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=owner.entity_id,
                                     payload={'zone':zone.model_dump(mode='json')})
                for obj in objects:
                    engine._update_object(obj, zone.source_definition_id, owner.entity_id)
                from .. import zones
                zones.sync_inside(engine, zone.source_definition_id)
                continue
            nums = r.get('numbers') or bundle['construction_contract']['numbers']
            cells = [Position.model_validate(c) for c in r['cells']]
            if r['family'] == 'array':
                action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and
                    a.parameters.get('formation') == 'set' and a.parameters.get('pattern') == r['pattern']), None)
                if action is None:
                    continue
                spec = F.passive_spec(r['pattern'], r['damage_type'], nums)
                zone = placed.place(engine, owner, source=action.source_definition_id, tag='prepared_array', cells=cells,
                    zone_id=r['id'], name='Prepared ' + F.PATTERNS[r['pattern']]['name'] + ' Array', numbers=nums,
                    duration_rounds=(r['remaining_seconds']+5)//6, triggers=spec['triggers'], inside=spec['inside'], difficult=spec['difficult'])
                zone.center = Position.model_validate(r['center'])
                for layer in r.get('layers',[r['pattern']])[1:]:
                    F.add_layer(zone,layer,r['damage_type'],nums)
                parts = []
                for role, at in [('eye',r['center']), *[('node',n) for n in r['nodes']]]:
                    oid = f"object:formation:{r['id']}:{role}:{len(parts)}"
                    obj = F.formation_component(oid, zone.zone_id, owner.entity_id, role,
                        Position.model_validate(at), ac=15,
                        hp=((5 if role=='eye' else 3)+int('reinforced_nodes' in F.talents_of(nums)))*int(nums['cl']))
                    engine._update_object(obj, action.source_definition_id, owner.entity_id); parts.append(oid)
                F.save_zone(engine,zone,action.source_definition_id,{'mode':'prepared','layers':r.get('layers',[r['pattern']]),
                    'damage_type':r['damage_type'],'eye':parts[0],'nodes':parts[1:],'numbers':nums,'cl':int(nums['cl'])})
            else:
                from .trap import FORMS, AIMS
                action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and a.parameters.get('set_trap')),None)
                if action is None:
                    continue
                zid=r['id']
                placed.place(engine,owner,source=action.source_definition_id,tag='trap',cells=cells,zone_id=zid,
                    name='Prepared '+FORMS[r['form']][0],numbers=nums,duration_rounds=(r['remaining_seconds']+5)//6,
                    triggers=[{'id':'trap:'+zid,'on':['enter'],'who':'any','effects':[{'type':'placed_trap_fire','zone_id':zid}]}],
                    placed={'form':r['form'],'pattern':r['form'],'dir':list(AIMS[r['aim']][1]),'damage_type':'PIERCING',
                            'physical_device':1,'physical_3d':1,'cl':int(nums['cl']),'pb':int(nums['pb']),'aware':[owner.entity_id],'warned':[],'walk_through':1,
                            **({'payload':r['payload'],'payload_origin':r['payload_origin']} if r.get('payload') else {})})

LEARNED = 'condition:typed.formation_learned_pattern'


def learned_patterns(engine, actor):
    """Public source-specific learning facts shared by Set and native Training."""
    bundle = next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    contract = bundle.get('construction_contract')
    if contract is None:
        return None  # historical sealed bundles retain their original menus
    learned = [c.data['pattern'] for c in actor.conditions.values() if c.condition_id==LEARNED]
    return list(dict.fromkeys([*contract.get('patterns',()),*learned]))


@hook('compile_actions')
def learn_buttons(info):
    if SET not in info.get('owned_ids', ()):
        return None
    from .formations import PATTERNS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    listed = (info['owner_sheet'].get('spheres_and_talents') or {}).get('formation_patterns')
    if listed:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.formation.learn.{key}",
        display_name='Formation Training: learn ' + row['name'], owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED',target_kind='SELF',parameters={'formation_learn':key,'setting_only':True,
            'description':'Choose your first Basic Pattern from Formation Training. No action or resource cost; this learning choice is permanent.',
            'typed':{'effects':[{'type':'formation_learn_pattern','pattern':key}], 'numbers':info['numbers'],
                     'duration':{'kind':'instant'},'riders':[]}})
            for key,row in PATTERNS.items() if not row.get('talent')]


@hook('candidate_allowed')
def learning_allowed(engine, actor, candidate, action):
    if action is not None and action.parameters.get('formation_learn'):
        return learned_patterns(engine,actor)==[]
    return None


from . import effect
@effect('formation_learn_pattern')
def learn_pattern(ctx, row):
    if learned_patterns(ctx.engine,ctx.actor) != []:
        return
    from .formations import PATTERNS
    from .needle import ask,checkpoint_id,CHOICE
    keys=[row['pattern'],*[k for k,v in PATTERNS.items() if not v.get('talent') and k!=row['pattern']]]
    choice=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'formation_first_pattern',ctx.actor.entity_id),
        ctx.actor,CHOICE+'formation_first_pattern',keys,labels={k:PATTERNS[k]['name'] for k in keys},
        preferred=[row['pattern']],name='Formation Training: first Basic Pattern',
        prompt='Formation Training: choose the first Basic Pattern you learn. This is your permanent learning choice; no action or resource cost.')
    if not choice:
        return
    ctx.engine._apply_condition(ctx.actor,LEARNED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'pattern':choice[0],'label':'Learned Formation Pattern: '+choice[0].replace('_',' ')})


@hook('journey_encounter_settled')
def resumed(session, aid, engine, creature):
    """Read committed terminal devices; do not repair or recreate spent stock."""
    actor=session.state['actors'][aid]
    if not profile(session,aid):
        return
    for condition in engine.state.actors[aid].conditions.values():
        if condition.condition_id=='condition:typed.trap_key_ability':
            actor.setdefault('construction_learning',{})['trap_key']=condition.data['ability']
        if condition.condition_id==LEARNED:
            actor.setdefault('construction_learning',{})['pattern']=condition.data['pattern']
    clock=source_clock(session,aid)
    records=actor.setdefault('constructed_patterns',[])
    known={r['id'] for r in records}
    for zone in engine.state.zones.values():
        data=placed.data(zone)
        if zone.owner_id!=aid or zone.zone_id in known or data.get('tag')!='trap' or not data.get('physical_device'):
            continue
        if data.get('form') not in ('dart','tripwire','activation'):
            continue
        remaining=max(0,(int(zone.duration_rounds or 0)-max(0,engine.state.round_number-zone.created_round))*6)
        end=clock+remaining if zone.active else clock
        records.append({'id':zone.zone_id,'family':'trap','form':data['form'],
            'center':zone.center.model_dump(mode='json'),'cells':[c.model_dump(mode='json') for c in zone.affected_cells],
            'map_id':session.state['battlefield'].get('stable_id',''), 'expires':int(end),
            'expires_num':end.numerator,'expires_den':end.denominator})
    for r in records:
        if r.get('map_id') != session.state['battlefield'].get('stable_id',''):
            continue
        zone=engine.state.zones.get(r['id'])
        if zone is None:
            continue
        if placed.data(zone).get('payload'):
            r['payload']=deepcopy(placed.data(zone)['payload'])
        if not zone.active:
            r.update(expires_num=clock.numerator,expires_den=clock.denominator)
        else:
            r['native_zone']=json.dumps(zone.model_dump(mode='json'),sort_keys=True,separators=(',',':'))
            r['native_objects']=[json.dumps(o.model_dump(mode='json'),sort_keys=True,separators=(',',':')) for o in engine.state.objects.values()
                if (o.component or {}).get('formation')==zone.zone_id or (o.component or {}).get('trap_zone')==zone.zone_id]
    session.emit('CONSTRUCTION_ENCOUNTER_RECORDED',aid,rounds=max(0,engine.state.round_number-1))


@hook('journey_step')
def native_pattern_contact(session,aid,old,nxt,regions):
    """Route actual device contact to native table resolution, never skip a save."""
    here=(nxt.x,nxt.y,nxt.z)
    for owner,actor in session.state['actors'].items():
        for record in actor.get('constructed_patterns',()):
            if record.get('map_id')!=session.state['battlefield'].get('stable_id','') or expiry(record)<=source_clock(session,owner):
                continue
            if here in {(c['x'],c['y'],c.get('z',0)) for c in record['cells']}:
                return {'native_scene_required':'This route enters an active trap or array. Open a table scene to resolve its actual movement, triggers and choices.'}
    return None


@hook('journey_options')
def native_scene_option(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:
        return None
    if not any(r.get('map_id')==session.state['battlefield'].get('stable_id','') and expiry(r)>source_clock(session,owner)
               for owner,a in session.state['actors'].items() for r in a.get('constructed_patterns',())):
        return None
    # The existing journey admits a travel party. This explicit menu choice
    # declares its scene teams; callers may instead supply another complete
    # roster to journey_start_scene. It never declares any recipient willing.
    return [{'id':'resolve_native_table_scene','kind':'open_scene','payload':{
                'teams':{a:'team:journey_party' for a in session.state['actors']}},'auto_select':0,
             'label':'Open a six-second table scene for this travel party. Resolve normal actions, movement, active traps and array Pulses, then resume travel.'}]
