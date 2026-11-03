"""Riverway consumers of the native persisted elapsed-time journey contract.

The actor submitting transit is the consenting passenger and chooses their own
arrival. Creators declare actual cells and recipients before paying. The same
mapped geometry and absolute barriers are used in combat. All retained state is
integer/string data in the journey registry; cold commands revalidate ownership,
costs, capacity, Concentration, route, position and elapsed-time expiry.
"""
from . import hook
from .riverway import PASSAGE, FERRY, MOON, KNOWS, FIELD, QI, field_contains
from ..gate2_runtime_models import Position
from .. import route_environment as environment
from ..journey import require
from fractions import Fraction

SOURCES = (PASSAGE, MOON, FIELD)
NAMES = {PASSAGE:'Flowing Passage', MOON:'Moonlit Ferry', FIELD:'Imperial River Field'}


def owned(session, aid, source):
    row=next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives',())
                 if r.get('block')=='riverway' and r.get('feature_id')==source),None)
    if row is None:return None
    from .journey_world import actor_state
    from .activation_requirements import min_cl_ready,effective_numbers
    creature=actor_state(session,aid)
    if min_cl_ready(creature,row) is False:return None
    return {**row,'numbers':effective_numbers(creature,row.get('numbers',{}))}


def effects(session):
    return [(aid, source, effect) for aid,actor in session.state['actors'].items()
            for source,effect in actor['travel_effects'].items() if source in SOURCES
            and owned(session,aid,source) and expiry(effect)>session.clock()]


def expiry(effect):
    return Fraction(effect.get('expiry_num',effect['expires_at']),effect.get('expiry_den',1))


def position(session,aid):
    return Position.model_validate(session.state['actors'][aid]['position'])


def contains(effect,cell):
    if effect['source']==FIELD:
        center=Position.model_validate(effect['cells'][0])
        return field_contains(center,cell)
    return cell.model_dump(mode='json') in effect['cells']


def points(session, raw):
    require(isinstance(raw,list) and raw,'Declare the route spaces before activation.')
    result=[]
    for row in raw:
        require(isinstance(row,dict) and not set(row)-{'x','y','z'}
                and all(type(row.get(k,0)) is int for k in ('x','y','z')),'Route spaces need integer map coordinates.')
        p=Position.model_validate(row)
        require(session.grid.in_bounds((p.x,p.y)) and session.grid.volume_legal(p,footprint=None),'The route must use open mapped spaces.')
        require(p not in result,'Each declared route space must be distinct.')
        result.append(p)
    return result


def field_of(session,aid):
    return next((e for owner,s,e in effects(session) if owner==aid and s==FIELD),None)


def expires(session,aid,source,reason):
    actor=session.state['actors'][aid]
    if source not in actor['travel_effects']:return
    del actor['travel_effects'][source]
    if actor.get('riverway_concentration')==source:actor.pop('riverway_concentration')
    session.emit('TRAVEL_EFFECT_ENDED',aid,source=source,text=NAMES[source]+' ends: '+reason+'.')
    if source==FIELD:
        gates=actor['travel_effects'].get(MOON)
        if gates and gates.get('waived'):
            gates.update(waived=0,concentration=1)
            actor['riverway_concentration']=MOON


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel':return None
    actor=session.state['actors'][aid]
    if actor['incapacitated']:return None
    rows=[]
    draft=actor.get('riverway_declaration')
    if draft:return declaration_options(session,aid,draft)
    for source in SOURCES:
        if not owned(session,aid,source):continue
        if source==FIELD and actor['travel_uses'].get(FIELD)==session.state.get('scene_id',session.state['journey_id']):continue
        rows.append({'id':source,'kind':'riverway_create','payload':{'source':source},
            'label':NAMES[source]+': declare legal spaces and chosen passengers before paying '+str({PASSAGE:1,MOON:5,FIELD:8}[source])+' Qi; lasts 1 minute.'})
    for owner,source,e in effects(session):
        if source!=MOON:continue
        for index,cell in enumerate(e['cells']):
            gate=Position.model_validate(cell)
            entered=actor.get('riverway_last_step',{})
            if (position(session,aid)!=gate or entered.get('position')!=actor['position']
                or entered.get('clock_num')!=session.clock().numerator or entered.get('clock_den')!=session.clock().denominator
                or entered.get('event_sequence',-1)<=e.get('created_sequence',0)
                or e['used'].get(aid)==str(int(session.clock()//6))):continue
            other=Position.model_validate(e['cells'][1-index])
            from .journey_world import actor_state,legal_volume
            from ..typed_executor import condition_rules
            if any(r.get('no_teleport') for r in condition_rules(actor_state(session,aid))):continue
            for z in range(max(0,other.z-1),other.z+2):
                for y in range(max(0,other.y-1),min(session.grid.height,other.y+2)):
                    for x in range(max(0,other.x-1),min(session.grid.width,other.x+2)):
                        p=Position(x=x,y=y,z=z)
                        if p==other or not legal_volume(session,aid,p):continue
                        if not environment.permits(session.grid,gate,other,teleport=True) or not environment.permits(session.grid,gate,p,teleport=True):continue
                        warning = ' An unsupported arrival may make you fall.' if not session.support_at(aid,p) else ''
                        rows.append({'id':f'riverway_transit:{owner}:{index}:{x},{y},{z}','kind':'riverway_transit',
                            'payload':{'owner_id':owner,'gate':index,'arrival':p.model_dump(mode='json')},
                            'label':f'Moonlit Ferry: willingly arrive at {x},{y}, {z*5} feet high beside the partner gate; no extra movement or Qi.{warning}'})
    return rows


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind=='riverway_create' and set(payload)=={'source'}:
        require(payload['source'] in SOURCES and owned(session,aid,payload['source']), 'Choose an acquired Riverway ability.')
        require(not session.state['actors'][aid]['incapacitated'],'An incapacitated creature cannot declare travel.')
        session.state['actors'][aid]['riverway_declaration']={'source':payload['source'],'cells':[],'chosen':[],'starters':[]}
        session.emit('TRAVEL_DECLARATION_STARTED',aid,source=payload['source'])
        return True
    if kind.startswith('riverway_declare_'):
        actor=session.state['actors'][aid];draft=actor.get('riverway_declaration')
        require(draft is not None,'Start a Riverway declaration first.')
        offered=declaration_options(session,aid,draft)
        require(any(o['kind']==kind and o['payload']==payload for o in offered),'Choose a current declaration option.')
        if kind=='riverway_declare_cancel':actor.pop('riverway_declaration')
        elif kind=='riverway_declare_cell':draft['cells'].append(payload['cell'])
        elif kind in ('riverway_declare_ally','riverway_declare_starter'):
            key='chosen' if kind=='riverway_declare_ally' else 'starters'
            if payload['target'] in draft[key]:draft[key].remove(payload['target'])
            else:draft[key].append(payload['target'])
            draft['starters']=[a for a in draft['starters'] if a in draft['chosen']]
        elif kind=='riverway_declare_finish':
            command(session,aid,'riverway_create',dict(draft))
            actor.pop('riverway_declaration')
        session.emit('TRAVEL_DECLARATION_UPDATED',aid,source=draft['source'],operation=kind)
        return True
    if kind=='riverway_create':
        require(set(payload)<= {'source','cells','chosen','starters'} and {'source','cells'}<=set(payload),'Declare the source, spaces and recipients.')
        source=payload['source']
        row=owned(session,aid,source)
        require(source in SOURCES and row is not None,'This creature has not acquired that Riverway ability.')
        actor=session.state['actors'][aid]
        require(not actor['incapacitated'],'An incapacitated creature cannot activate Riverway travel.')
        cells=points(session,payload['cells'])
        origin=position(session,aid)
        chosen=payload.get('chosen',[])
        from .journey_world import relation
        require(isinstance(chosen,list) and len(chosen)==len(set(chosen))
                and all(a in session.state['actors'] and relation(session,aid,a)=='ALLY' for a in chosen),'Choose distinct allies in this journey.')
        # Journey rosters are explicitly declared companions, not inferred
        # willingness. Only each passenger's own transit command grants consent.
        greater=bool(owned(session,aid,KNOWS))
        starters=payload.get('starters',[])
        require(isinstance(starters,list) and set(starters)<=set(chosen)
                and len(starters)<=int(row['numbers'].get('pb',2)),'Choose at most proficiency bonus starters from your chosen allies.')
        maximum={PASSAGE:30,MOON:60,FIELD:90}[source]
        require(session.grid.distance_ft(origin,cells[0])<=maximum and session.grid.line_of_sight(origin,cells[0]),'The route origin must be visible and in range.')
        if source==PASSAGE:
            require(len(cells)<= (12 if greater else 6),'The Passage exceeds its printed length.')
            gap=0
            for index,p in enumerate(cells):
                supported=(p.z==0 or session.grid.roof_supported(p) or environment.at(session.grid,p,('water',))
                           or any(session.grid.terrain_at((p.x+dx,p.y+dy,p.z+dz),'BLOCKED') for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))))
                gap=0 if supported else gap+1
                require(supported or greater and gap<=2,'Unsupported Passage gaps cannot exceed 10 feet.')
                if index:
                    a=cells[index-1]
                    require(session.grid.distance_cells(a,p)==1 and (greater or a.z==p.z)
                            and session.grid.volume_step_legal(a,p)
                            and session.grid.line_of_physical_transmission(a,p)
                            and environment.permits(session.grid,a,p,barriers=('sealed_formation',)),'The Passage must be contiguous and cannot cross a barrier.')
        elif source==MOON:
            require(len(cells)==2 and session.grid.distance_ft(cells[0],cells[1])<=120,'Moonlit Ferry needs two gates within 120 feet of each other.')
            require(all(session.grid.distance_ft(origin,p)<=60 and session.grid.line_of_sight(origin,p) for p in cells),'Both gates must be visible and within 60 feet.')
            from .journey_world import occupied_cells
            require(not any((p.x,p.y,p.z) in occupied_cells(session) for p in cells),'Gate spaces must be unoccupied.')
        else:
            require(len(cells)==1,'Declare one cylinder center.')
            require(actor['travel_uses'].get(FIELD)!=session.state.get('scene_id',session.state['journey_id']),'Imperial River Field is once per scene.')
        cost={PASSAGE:1,MOON:5,FIELD:8}[source]
        require(actor['resources'].get(QI,0)>=cost,'Not enough Qi.')
        field=field_of(session,aid)
        waived=int(source==MOON and field is not None and all(contains(field,p) for p in cells))
        if source in (MOON,FIELD) and not waived:
            from .. import concentration
            capacity=concentration.limit_for_cl(int(actor['bundle'].get('cl',1)),concentration.rules_for_bundle(actor['bundle']))
            held=sorted([(e.get('created_sequence',0),s) for s,e in actor['travel_effects'].items()
                         if s in SOURCES and e.get('concentration') and s!=source])
            if capacity is not None:
                while len(held)>=capacity:
                    _,old=held.pop(0);expires(session,aid,old,'Concentration replaced')
            actor['riverway_concentration']=source
        actor['resources'][QI]-=cost
        deadline=session.clock()+60
        actor['travel_effects'][source]={'source':source,'cells':[p.model_dump(mode='json') for p in cells],
            'chosen':chosen,'starters':starters,'greater':int(greater),'expires_at':int(session.state['seconds'])+60,
            'expiry_num':deadline.numerator,'expiry_den':deadline.denominator,
            'waived':waived,'concentration':int(source in (MOON,FIELD) and not waived),'used':{},
            'created_sequence':len(session.state['events']),'created_at':int(session.state['seconds'])}
        if source==FIELD:
            actor['travel_uses'][FIELD]=session.state.get('scene_id',session.state['journey_id'])
            for _,s,e in effects(session):
                if s==MOON and e is actor['travel_effects'].get(MOON) and all(contains(actor['travel_effects'][FIELD],Position.model_validate(p)) for p in e['cells']):
                    e.update(waived=1,concentration=0)
        session.emit('TRAVEL_ACTION',aid,source=source,qi_cost=cost,economy='BONUS_ACTION' if source==PASSAGE else 'ACTION',
            origin=origin.model_dump(mode='json'),destination=cells[-1].model_dump(mode='json'),passengers=chosen,
            text=NAMES[source]+f': paid {cost} Qi; declared route lasts 60 seconds.')
        return True
    if kind=='riverway_transit':
        require(set(payload)=={'owner_id','gate','arrival'},'Declare the gate owner, entry gate and arrival space.')
        owner=payload['owner_id']; index=payload['gate']
        require(owner in session.state['actors'] and type(index) is int and index in (0,1),'Choose a real gate pair.')
        effect=next((e for a,s,e in effects(session) if a==owner and s==MOON),None)
        require(effect is not None,'That Ferry has expired.')
        actor=session.state['actors'][aid]
        require(not actor['incapacitated'] and not actor.get('carried_by'),'This passenger cannot enter a gate.')
        gate=Position.model_validate(effect['cells'][index]); other=Position.model_validate(effect['cells'][1-index])
        require(position(session,aid)==gate,'First enter the chosen gate with ordinary movement.')
        entered=actor.get('riverway_last_step',{})
        require(entered.get('position')==actor['position'] and entered.get('clock_num')==session.clock().numerator
                and entered.get('clock_den')==session.clock().denominator
                and entered.get('event_sequence',-1)>effect.get('created_sequence',0),'Moonlit Ferry requires an actual immediate gate entry.')
        from .journey_world import actor_state,legal_volume
        from ..typed_executor import condition_rules
        require(not any(r.get('no_teleport') for r in condition_rules(actor_state(session,aid))),'This passenger cannot teleport.')
        arrival=points(session,[payload['arrival']])[0]
        require(arrival!=other and session.grid.distance_ft(other,arrival)<=5,'Arrive adjacent to the partner gate.')
        require(legal_volume(session,aid,arrival),'The arrival space cannot hold this creature or is occupied.')
        require(environment.permits(session.grid,gate,other,teleport=True)
                and environment.permits(session.grid,gate,arrival,teleport=True),'A spatial seal, Formation, planar boundary or artifact blocks this Ferry.')
        window=str(int(session.clock()//6))
        require(effect['used'].get(aid)!=window,'A creature may use the Ferry once per turn (six-second travel interval).')
        effect['used'][aid]=window
        fall_engine = session.movement_projection() if not session.support_at(aid,arrival) else None
        actor['position']=arrival.model_dump(mode='json')
        session.emit('TRAVEL_TELEPORT',aid,source=MOON,owner_id=owner,origin=gate.model_dump(mode='json'),
            destination=actor['position'],willing=1,elapsed_seconds=0,text=actor['name']+' willingly uses Moonlit Ferry; no extra movement cost.')
        from . import run_strict
        run_strict('journey_position_committed',session,aid,gate,arrival,session.state['events'][-1])
        if fall_engine is not None:
            from .journey_world import settle_arrival
            settle_arrival(session,aid,MOON,engine=fall_engine)
        return True
    return None


def declaration_options(session,aid,draft):
    """Every legal source space and recipient, before any activation cost.

    The final native command revalidates the whole declaration transactionally;
    a moved passenger or changed source cannot turn this draft into authority.
    """
    from .journey_world import relation
    source=draft['source'];origin=position(session,aid);greater=bool(owned(session,aid,KNOWS))
    row=owned(session,aid,source)
    if row is None:return [{'id':'cancel','kind':'riverway_declare_cancel','payload':{},'label':'Cancel unavailable Riverway declaration; no Qi spent.'}]
    rows=[{'id':'cancel','kind':'riverway_declare_cancel','payload':{},'auto_select':0,'label':'Cancel '+NAMES[source]+'; no Qi spent.'}]
    cells=[Position.model_validate(p) for p in draft['cells']]
    maximum=(12 if greater else 6) if source==PASSAGE else 2 if source==MOON else 1
    if len(cells)<maximum:
        reach={PASSAGE:30,MOON:60,FIELD:90}[source]//5
        center=cells[-1] if source==PASSAGE and cells else origin
        radius=1 if source==PASSAGE and cells else reach
        for z in range(max(0,center.z-radius),center.z+radius+1):
            for y in range(max(0,center.y-radius),min(session.grid.height,center.y+radius+1)):
                for x in range(max(0,center.x-radius),min(session.grid.width,center.x+radius+1)):
                    p=Position(x=x,y=y,z=z)
                    if p in cells or session.grid.distance_ft(origin,p)>reach*5 and not (source==PASSAGE and cells):continue
                    if not session.grid.volume_legal(p) or not (source==PASSAGE and cells) and not session.grid.line_of_sight(origin,p):continue
                    if source==MOON:
                        from .journey_world import occupied_cells
                        if (p.x,p.y,p.z) in occupied_cells(session) or cells and session.grid.distance_ft(cells[0],p)>120:continue
                    if source==PASSAGE:
                        supported=lambda q:(q.z==0 or session.grid.roof_supported(q) or environment.at(session.grid,q,('water',))
                            or any(session.grid.terrain_at((q.x+dx,q.y+dy,q.z+dz),'BLOCKED') for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))))
                        trailing=0
                        for q in reversed([*cells,p]):
                            if supported(q):break
                            trailing+=1
                        if trailing>(2 if greater else 0):continue
                        if cells and (session.grid.distance_cells(cells[-1],p)!=1 or not greater and cells[-1].z!=p.z
                            or not session.grid.volume_step_legal(cells[-1],p) or not session.grid.line_of_physical_transmission(cells[-1],p)
                            or not environment.permits(session.grid,cells[-1],p,barriers=('sealed_formation',))):continue
                    rows.append({'id':f'cell:{x},{y},{z}','kind':'riverway_declare_cell','payload':{'cell':p.model_dump(mode='json')},
                        'auto_select':int(session.grid.line_of_sight(origin,p)),
                        'label':f'{NAMES[source]}: add space {x},{y}, {z*5} feet high to the declared route.'})
    if source in (PASSAGE,FIELD):
        for target in session.state['actors']:
            if relation(session,aid,target)!='ALLY':continue
            selected=target in draft['chosen']
            rows.append({'id':'ally:'+target,'kind':'riverway_declare_ally','payload':{'target':target},'auto_select':int(not selected),
                'label':('Remove ' if selected else 'Choose ')+session.state['actors'][target]['name']+' for '+NAMES[source]+' movement benefits.'})
            if source==PASSAGE and greater and selected and (target in draft['starters'] or len(draft['starters'])<int(row['numbers']['pb'])):
                rows.append({'id':'starter:'+target,'kind':'riverway_declare_starter','payload':{'target':target},'auto_select':0,
                    'label':('Remove ' if target in draft['starters'] else 'Choose ')+session.state['actors'][target]['name']+' for the free 5-foot movement at the start of their turn.'})
    if cells and (source==PASSAGE or len(cells)==maximum):
        rows.append({'id':'finish','kind':'riverway_declare_finish','payload':{},
            'label':f'Create {NAMES[source]} with these spaces and recipients: pay '+str({PASSAGE:1,MOON:5,FIELD:8}[source])+' Qi; lasts 1 minute.'})
    return rows


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    for source,e in list(session.state['actors'][aid]['travel_effects'].items()):
        if source in SOURCES and session.clock()>=expiry(e):
            expires(session,aid,source,'one minute elapsed')


@hook('journey_state_changed')
def changed(session,aid):
    actor=session.state['actors'][aid]
    if actor['incapacitated'] or session.state['phase']=='finished':
        for source in (MOON,FIELD):
            if source in actor['travel_effects']:
                expires(session,aid,source,'travel ended or creator incapacitated')


@hook('journey_damage_committed')
def concentration_damage(session,aid,event):
    """A real damaging exposure checks the latest independently held route."""
    held=[(e.get('created_sequence',0),source) for owner,source,e in effects(session)
          if owner==aid and e.get('concentration')]
    damage=event.get('reduced_to',0)
    if not held or damage<=0:return
    from .journey_world import saving_throw
    if not saving_throw(session,aid,'CON',min(30,max(10,damage//2)),'system:combat.concentration'):
        expires(session,aid,max(held)[1],'failed Concentration saving throw after damage')


@hook('journey_properties')
def properties(session,aid):
    result={}
    actor=session.state['actors'][aid]
    if owned(session,aid,KNOWS):
        result.update(swim_speed_ft=actor['bundle']['actor_template']['speed_ft'],air_breathing=1,water_breathing=1,
            navigation_advantage=['rivers','canals','floods','deltas','swamps','coastlines','water routes'],
            connected_water=environment.water_knowledge(session.grid,position(session,aid)))
    active=[e for _,s,e in effects(session) if aid in e['chosen'] and contains(e,position(session,aid)) and s in (PASSAGE,FIELD)]
    if active:
        result['speed_bonus_ft']=max(10 if e['source']==FIELD else 5 for e in active)
        speed=int(actor['bundle']['actor_template']['speed_ft'])
        if speed>0:result.update(pace_num=speed+result['speed_bonus_ft'],pace_den=speed)
        deadline=min(expiry(e) for e in active)
        result.update(expiry_num=deadline.numerator,expiry_den=deadline.denominator)
    return result or None


@hook('journey_step')
def step(session,aid,old,nxt,regions):
    """Terrain answers for one travel step; never a blanket support override.

    Greater Flowing Passage widens the path, adds wall and ceiling travel and
    lets allies cross unsupported open-air gaps up to 10 feet without falling.
    It answers cross_unsupported only for the gap spaces it covers. The
    native journey arrival settlement handles a creature that stops there.
    """
    supports=set();ignore=set();cross=False
    if owned(session,aid,KNOWS):supports.update(('water','river'))
    for owner,source,e in effects(session):
        if aid not in e['chosen']:continue
        if source==PASSAGE and contains(e,old) and contains(e,nxt):
            supports.update(('water','river'))
            if e.get('greater'):
                supports.update(('vertical_surface','cliff'))
        if source==FIELD and contains(e,nxt):ignore.update(r['kind'] for r in regions)
    from .riverway_passage import supported_cell
    if not supported_cell(session,nxt):
        cross=any(aid in e['chosen'] and source==PASSAGE and e.get('greater')
                  and contains(e,old) and contains(e,nxt) for owner,source,e in effects(session))
    reply={'supported_kinds':sorted(supports),'ignore_slowing':sorted(ignore)}
    if cross:reply['cross_unsupported']=True
    return reply if supports or ignore or cross else None


@hook('journey_check_mode')
def navigation(session,aid,ability,skill,context):
    if not owned(session,aid,KNOWS) or context.get('purpose')!='navigation':return None
    if (context.get('route_kind') in ('river','canal','flood','delta','swamp','coastline','water_route')
        or any(r['id']==context.get('region_id') and r['kind']=='water' for r in session.grid.route_regions)):
        return 'ADVANTAGE'


@hook('journey_combat_setup')
def combat_setup(session,aid):
    from copy import deepcopy
    actor=session.state['actors'][aid]
    state={source:deepcopy(e) for owner,source,e in effects(session) if owner==aid}
    if not state and not owned(session,aid,FIELD):return None
    for source,e in state.items():
        remaining=expiry(e)-session.clock()
        e['remaining_num']=remaining.numerator;e['remaining_den']=remaining.denominator
    return {'riverway_state':{'effects':state,'scene_used':int(actor['travel_uses'].get(FIELD)==session.state.get('scene_id',session.state['journey_id']))}}


@hook('match_initialize')
def encounter_setup(engine):
    from . import placed
    from .riverway import owned as combat_owned,bind_concentration,FIELD_TAG,GATES
    for bundle in getattr(engine,'typed_bundle_documents',()):
        state=(bundle.get('journey_setup') or {}).get('riverway_state')
        actor=engine.state.actors.get(bundle['actor_id'])
        if not state or actor is None or actor.turn_flags.get('typed_round_riverway_imported'):continue
        actor.turn_flags['typed_round_riverway_imported']=1
        if state['scene_used']:actor.turn_flags['typed_round_riverway_scene']=1
        # Field first: its sustained gate pair never takes an extra slot.
        for source in (FIELD,PASSAGE,MOON):
            e=state['effects'].get(source)
            if not e or not combat_owned(engine,actor,source):continue
            action=next((a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id
                and (a.parameters.get('typed') or {}).get('source')==source and not (a.parameters.get('typed') or {}).get('riverway_command')),None)
            if action is None:continue
            remaining=Fraction(e['remaining_num'],e['remaining_den'])
            rounds=max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator))
            cells=[Position.model_validate(p) for p in e['cells']]
            if source==FIELD:
                center=cells[0]
                from .riverway import field_contains
                cells=[Position(x=x,y=y,z=z) for z in range(center.z,center.z+8)
                    for y in range(max(0,center.y-8),min(engine.grid.height,center.y+9))
                    for x in range(max(0,center.x-8),min(engine.grid.width,center.x+9))
                    if field_contains(center,Position(x=x,y=y,z=z))]
            concentrating=source in (FIELD,MOON) and not e.get('waived')
            if concentrating:engine._start_concentration(actor,action.source_definition_id)
            tag={PASSAGE:'riverway_passage',MOON:GATES,FIELD:FIELD_TAG}[source]
            zone=placed.place(engine,actor,source=action.source_definition_id,tag=tag,cells=cells,
                name=NAMES[source],placed={'chosen':e['chosen'],'starters':e['starters'],'greater':e['greater'],
                    'waived':e['waived'],'used':{},'command_used':'','distance_used':'',
                    'journey_deadline_num':e['expiry_num'],'journey_deadline_den':e['expiry_den']},
                numbers=(action.parameters.get('typed') or {}).get('numbers',{}),duration_rounds=rounds,
                concentration=concentrating,difficult='hostile' if source==FIELD else None,
                shape='cylinder' if source==FIELD else 'cube', size_ft=40 if source==FIELD else 5,
                extra={'footprint_height_ft':40} if source==FIELD else None)
            if concentrating:bind_concentration(placed.context(engine,actor,action.source_definition_id,zone.trigger_profile['numbers']),zone)


@hook('journey_combat_elapsed')
def combat_elapsed(session,engine):
    if any(owned(session,aid,PASSAGE) for aid in session.state['actors']):
        return max(0,engine.state.round_number-1)*6


@hook('journey_snapshot_actor')
def combat_return(creature,session,aid,engine):
    from . import placed
    from .riverway import FIELD_TAG,GATES
    from .. import concentration
    actor=session.state['actors'][aid]
    if not any(owned(session,aid,s) for s in SOURCES):return
    if creature.turn_flags.get('typed_round_riverway_scene'):
        actor['travel_uses'][FIELD]=session.state.get('scene_id',session.state['journey_id'])
    action_sources=set()
    for source,tag in ((PASSAGE,'riverway_passage'),(MOON,GATES),(FIELD,FIELD_TAG)):
        actor['travel_effects'].pop(source,None)
        for zone in placed.of(engine,tag,owner_id=aid):
            e=placed.data(zone)
            remaining=Fraction(max(0,int(zone.duration_rounds or 10)-(engine.state.round_number-zone.created_round))*6)
            if 'journey_deadline_num' in e:
                remaining=min(remaining,Fraction(e['journey_deadline_num'],e['journey_deadline_den'])-session.clock())
            if not remaining:continue
            if remaining<0:continue
            deadline=session.clock()+remaining
            actor['travel_effects'][source]={'source':source,'cells':[p.model_dump(mode='json') for p in ([zone.center] if source==FIELD else zone.affected_cells)],
                'chosen':e.get('chosen',[]),'starters':e.get('starters',[]),'greater':e.get('greater',0),
                'waived':e.get('waived',0),'concentration':int(zone.concentration_link),'used':{},
                'expires_at':deadline.numerator//deadline.denominator,'expiry_num':deadline.numerator,'expiry_den':deadline.denominator,
                'created_at':session.state['seconds'],'created_sequence':len(session.state['events'])}
            action_sources.add(zone.source_definition_id)
    # Only exported source-owned timers/Concentration are detached from this
    # copied snapshot. The immutable terminal fight and unrelated effects stay.
    if creature.concentration and creature.concentration.source_definition_id in action_sources:
        creature.concentration=None
    for iid,c in list(creature.conditions.items()):
        if c.source_definition_id in action_sources and (c.condition_id=='condition:typed.concentration_deadline'
                or c.condition_id.startswith('condition:typed.concentration_held')):
            creature.conditions.pop(iid)
    return creature


def window(session):
    return str(int(session.clock()//6))


def carry_scope(session,owner,target,destination,kind='carry'):
    from ..fact_consent_admission import digest
    e=field_of(session,owner)
    return 'carry:'+digest({'owner':owner,'target':target,'window':window(session),
        'origin':position(session,target).model_dump(mode='json'),'destination':destination,'kind':kind,
        'field_sequence':e.get('created_sequence',0) if e else -1})


@hook('fact_admission_schema')
def consent_schema(session,source,subject,kind):
    if source==FIELD and kind in ('riverway_carry_consent','riverway_distance_consent') and any(s==FIELD and contains(e,position(session,subject)) for _,s,e in effects(session)):
        return {'value_type':'flag','maximum_seconds':6,'description':'The passenger agrees to one source-bound Carry this turn; no Qi or ordinary movement cost.'}


@hook('journey_damage_committed')
def damaged(session,aid,event):
    from .journey_world import relation,actor_state
    if not event['reduced_to']:return
    for owner,actor in session.state['actors'].items():
        if owner==aid or not owned(session,owner,FERRY) or actor['incapacitated'] or relation(session,owner,aid)!='ALLY':continue
        if session.grid.distance_ft(position(session,owner),position(session,aid))>30 or not session.grid.line_of_sight(position(session,owner),position(session,aid)):continue
        actor.setdefault('riverway_rescues',[]).append({'target':aid,'event_sequence':len(session.state['events']),
            'window':window(session),'clock_num':session.clock().numerator,'clock_den':session.clock().denominator})


@hook('journey_options')
def derived_options(session,aid):
    if session.state['phase']!='travel':return None
    from .journey_world import paths,relation
    from .needle import cell_id
    actor=session.state['actors'][aid];rows=[]
    if not actor['incapacitated'] and owned(session,aid,FERRY) and actor.get('riverway_reaction_used')!=window(session):
        for trigger in actor.get('riverway_rescues',()):
            if trigger['window']!=window(session) or Fraction(trigger['clock_num'],trigger['clock_den'])!=session.clock():continue
            for point in paths(session,trigger['target'],10,barriers=('spatial_lock','sealed_formation')):
                rows.append({'id':f'rescue:{trigger["event_sequence"]}:{cell_id(point)}','kind':'riverway_rescue',
                    'payload':{'event_sequence':trigger['event_sequence'],'destination':point.model_dump(mode='json')},
                    'label':f'Ferry the Wounded: move {session.state["actors"][trigger["target"]]["name"]} to {point.x},{point.y} after damage, without provoking; Reaction and {1 if field_of(session,aid) else 2} Qi.'})
    for owner,source,e in effects(session):
        if source!=FIELD:continue
        proposal=session.state['actors'][owner].get('riverway_carry_proposal')
        if (contains(e,position(session,aid)) and relation(session,owner,aid)=='ALLY' and proposal
                and proposal['target']==aid and proposal['window']==window(session) and proposal['origin']==actor['position']):
            destination=proposal['destination'];scope=carry_scope(session,owner,aid,destination)
            safe=session.grid.line_of_sight(position(session,aid),Position.model_validate(destination))
            from ..fact_consent_admission import read
            answered=read(session,FIELD,aid,'riverway_carry_consent',scope,aid)
            for accepted,verb in ((1,'Accept'),(0,'Decline')):
                rows.append({'id':f'consent:{accepted}:{scope}','kind':'declare_fact','auto_select':int(answered is None and bool(safe)==bool(accepted)),
                    'payload':{'source':FIELD,'subject':aid,'kind':'riverway_carry_consent','scope':scope,'value':accepted,
                        'expires_at':(int(session.clock()//6)+1)*6,'readers':[owner]},
                    'label':f'{verb} Command the Current: {session.state["actors"][owner]["name"]} offers to carry you to {destination["x"]},{destination["y"]}, {destination.get("z",0)*5} feet high, without provoking or spending your movement.'})
        if owner==aid and e.get('command_used')!=window(session):
            for target in session.state['actors']:
                if not contains(e,position(session,target)):continue
                if relation(session,aid,target)=='ALLY':
                    rows.append({'id':'buoy:'+target,'kind':'riverway_command','payload':{'mode':'Buoy','target':target},
                        'label':f'Command the Current — Buoy: {session.state["actors"][target]["name"]} gains twice your proficiency bonus Temporary HP; once this turn, no extra cost.'})
                    from ..fact_consent_admission import read
                    for point in paths(session,target,15):
                        destination=point.model_dump(mode='json')
                        consent=read(session,FIELD,target,'riverway_carry_consent',carry_scope(session,aid,target,destination),aid)
                        ready=bool(consent and consent['value']==1)
                        rows.append({'id':'carry:'+target+':'+cell_id(point),'kind':'riverway_command' if ready else 'riverway_carry_propose',
                            'payload':{'mode':'Carry','target':target,'destination':destination},
                            'label':f'Command the Current — {"Carry" if ready else "offer to carry"} {session.state["actors"][target]["name"]} to {point.x},{point.y}, {point.z*5} feet high, without provoking; once this turn, no extra cost.'})
                    import json
                    for iid,encoded in session.state['actors'][target].get('encounter_snapshot',{}).get('conditions',{}).items():
                        c=json.loads(encoded)
                        if c['condition_id'].rsplit('.',1)[-1] not in ('grappled','restrained','prone'):continue
                        spec=c['data'].get('repeat_save') or c['data'].get('origin_save')
                        for ability in ([spec['ability']] if spec else ['STR','DEX']):
                            rows.append({'id':f'wash:{target}:{iid}:{ability}','kind':'riverway_command',
                                'payload':{'mode':'Wash Away','target':target,'condition_instance':iid,'ability':ability},
                                'label':f'Command the Current — Wash Away: {session.state["actors"][target]["name"]} repeats this restraint save with Advantage; no extra cost.'})
                elif relation(session,aid,target)=='ENEMY':
                    for direction in ('push','pull'):
                        rows.append({'id':'sweep:'+target+':'+direction,'kind':'riverway_command',
                            'payload':{'mode':'Sweep','target':target,'direction':direction},
                            'label':f'Command the Current — Sweep {session.state["actors"][target]["name"]}: Strength save; {direction} 15 feet on failure, 5 on success; once this turn, no extra cost.'})
        if owner==aid and not actor['incapacitated']:
            for target in session.state['actors']:
                for p in distance_points(session,owner,target):
                    rows.append({'id':'distance:'+target+':'+cell_id(p),'kind':'riverway_distance_propose',
                        'payload':{'target':target,'destination':p.model_dump(mode='json')},
                        'label':f'River Without Distance: offer to teleport {session.state["actors"][target]["name"]} to {p.x},{p.y}, {p.z*5} feet high inside the field; once this turn, no extra cost.'})
        proposal=session.state['actors'][owner].get('riverway_distance_proposal')
        if proposal and proposal['target']==aid and proposal['window']==window(session) and proposal['origin']==actor['position']:
            destination=proposal['destination'];scope=carry_scope(session,owner,aid,destination,kind='distance')
            from ..fact_consent_admission import read
            answered=read(session,FIELD,aid,'riverway_distance_consent',scope,aid)
            safe=session.grid.line_of_sight(position(session,aid),Position.model_validate(destination))
            for accepted,verb in ((1,'Accept'),(0,'Decline')):
                rows.append({'id':f'distance-consent:{accepted}:{scope}','kind':'declare_fact',
                    'auto_select':int(answered is None and bool(safe)==bool(accepted)),
                    'payload':{'source':FIELD,'subject':aid,'kind':'riverway_distance_consent','scope':scope,'value':accepted,
                        'expires_at':(int(session.clock()//6)+1)*6,'readers':[owner]},
                    'label':f'{verb} River Without Distance: {session.state["actors"][owner]["name"]} offers to teleport you to {destination["x"]},{destination["y"]}, {destination.get("z",0)*5} feet high; no extra cost.'})
    for owner,source,e in effects(session):
        if actor['incapacitated'] or e.get('start_grants',{}).get(aid)!=window(session):continue
        for point,path in paths(session,aid,5).items():
            if point==position(session,aid):continue
            if source==PASSAGE and not contains(e,point):continue
            try:cost=session.step_profile(aid,position(session,aid),point)
            except ValueError:continue
            if cost>1:continue
            rows.append({'id':f'start:{owner}:{source}:{cell_id(point)}','kind':'riverway_start_step',
                'payload':{'owner_id':owner,'source':source,'destination':point.model_dump(mode='json')},
                'label':f'{NAMES[source]}: move 5 feet to {point.x},{point.y} at the start of this turn without provoking or spending ordinary movement.'})
    return rows or None


@hook('journey_command')
def derived_commands(session,aid,kind,payload):
    from .journey_world import paths,relocate,temporary_hp,relation,snapshot,saving_throw,repeat_save
    actor=session.state['actors'][aid]
    if kind=='riverway_carry_propose':
        e=field_of(session,aid)
        require(e is not None and e.get('command_used')!=window(session) and not actor['incapacitated'],'Command the Current is unavailable.')
        require(set(payload)=={'mode','target','destination'} and payload['mode']=='Carry'
                and payload['target'] in session.state['actors'],'Declare the proposed passenger and destination.')
        target=payload['target'];point=Position.model_validate(payload['destination'])
        require(relation(session,aid,target)=='ALLY' and contains(e,position(session,target)) and point in paths(session,target,15),'Choose a legal Carry route for an ally inside the field.')
        actor['riverway_carry_proposal']={'target':target,'destination':point.model_dump(mode='json'),
            'origin':dict(session.state['actors'][target]['position']),'window':window(session)}
        session.emit('MOVEMENT_PROPOSED',aid,source=FIELD,target=target,origin=dict(session.state['actors'][target]['position']),destination=point.model_dump(mode='json'))
        return True
    if kind=='riverway_start_step':
        require(set(payload)=={'owner_id','source','destination'} and not actor['incapacitated'],'Choose an owned start-turn movement grant.')
        e=next((e for owner,source,e in effects(session) if owner==payload['owner_id'] and source==payload['source']),None)
        require(e is not None and e.get('start_grants',{}).get(aid)==window(session),'No current start-turn movement is available.')
        from ..typed_executor import condition_rules
        from .journey_world import actor_state
        require(not any(r.get('speed_zero') for r in condition_rules(actor_state(session,aid))),'This creature cannot move voluntarily while its Speed is zero.')
        point=Position.model_validate(payload['destination']);routes=paths(session,aid,5)
        require(point in routes and session.step_profile(aid,position(session,aid),point)<=1
                and (payload['source']!=PASSAGE or contains(e,point)),'Move 5 feet into or along the supporting route.')
        del e['start_grants'][aid]
        relocate(session,aid,routes[point],payload['source'],payload['owner_id'])
        return True
    if kind=='riverway_rescue':
        require(set(payload)=={'event_sequence','destination'} and owned(session,aid,FERRY)
                and not actor['incapacitated'] and actor.get('riverway_reaction_used')!=window(session),'Ferry the Wounded is unavailable.')
        trigger=next((r for r in actor.get('riverway_rescues',()) if r['event_sequence']==payload['event_sequence']
            and r['window']==window(session) and Fraction(r['clock_num'],r['clock_den'])==session.clock()),None)
        require(trigger is not None,'Choose a real, immediate committed damage trigger.')
        target=trigger['target'];destination=Position.model_validate(payload['destination'])
        routes=paths(session,target,10,barriers=('spatial_lock','sealed_formation'));require(destination in routes,'That rescue route is blocked or too far.')
        cost=1 if field_of(session,aid) else 2
        require(actor['resources'].get(QI,0)>=cost,'Not enough Qi for Ferry the Wounded.')
        actor['resources'][QI]-=cost;actor['riverway_reaction_used']=window(session)
        session.emit('REACTION_RESOLVED',aid,source=FERRY,target=target,qi_cost=cost,trigger_sequence=trigger['event_sequence'])
        relocate(session,target,routes[destination],FERRY,aid)
        if any(owner==aid and source==PASSAGE and contains(e,position(session,target)) for owner,source,e in effects(session)):
            temporary_hp(session,target,int(owned(session,aid,FERRY)['numbers'].get('pb',2)),FERRY,aid)
        return True
    if kind=='riverway_command':
        e=field_of(session,aid)
        require(e is not None and not actor['incapacitated'] and e.get('command_used')!=window(session),'Command the Current is unavailable or already used this turn.')
        require(payload.get('mode') in ('Carry','Sweep','Buoy','Wash Away') and payload.get('target') in session.state['actors'],'Choose one mode and a creature in this journey.')
        target=payload['target'];mode=payload['mode']
        require(contains(e,position(session,target)) and relation(session,aid,target)==('ENEMY' if mode=='Sweep' else 'ALLY'),'Choose an eligible creature inside your field.')
        numbers=owned(session,aid,FIELD)['numbers']
        if mode=='Buoy':
            require(set(payload)=={'mode','target'},'Buoy needs only its ally.')
            temporary_hp(session,target,2*int(numbers.get('pb',2)),FIELD,aid)
        elif mode=='Carry':
            require(set(payload)=={'mode','target','destination'},'Carry needs an ally and declared destination.')
            from ..fact_consent_admission import read
            consent=read(session,FIELD,target,'riverway_carry_consent',carry_scope(session,aid,target,payload['destination']),aid)
            require(consent is not None and consent['value']==1,'This ally must first consent through their own source-bound declaration.')
            routes=paths(session,target,15);destination=Position.model_validate(payload['destination'])
            require(destination in routes,'The Carry route is blocked or too far.')
            relocate(session,target,routes[destination],FIELD,aid)
        elif mode=='Sweep':
            require(set(payload)=={'mode','target','direction'} and payload['direction'] in ('push','pull'),'Sweep needs the hostile creature and push or pull.')
            success=saving_throw(session,target,'STR',int(numbers['save_dc']),FIELD,initiator=aid)
            feet=5 if success else 15;routes=paths(session,target,feet);path=[position(session,target)]
            for _ in range(feet//5):
                old=path[-1];origin=position(session,aid)
                dx=(origin.x>old.x)-(origin.x<old.x);dy=(origin.y>old.y)-(origin.y<old.y)
                if payload['direction']=='push':dx,dy=-dx,-dy
                if not (dx or dy) or not session.grid.in_bounds((old.x+dx,old.y+dy)):break
                nxt=Position(x=old.x+dx,y=old.y+dy,z=old.z)
                from .journey_world import legal_step
                if nxt not in routes or not legal_step(session,target,old,nxt):break
                path.append(nxt)
            relocate(session,target,path,FIELD,aid)
        else:
            require(set(payload)<= {'mode','target','condition_instance','ability'} and 'condition_instance' in payload,'Wash Away needs one actual restraint instance.')
            saved=snapshot(session,target);encoded=saved['conditions'].get(payload['condition_instance'])
            require(encoded is not None,'That restraint is not present.')
            import json
            condition=json.loads(encoded)
            require(condition['condition_id'].rsplit('.',1)[-1] in ('grappled','restrained','prone'),'Wash Away affects only Grappled, Restrained or Prone.')
            data=condition['data'];spec=data.get('repeat_save') or data.get('origin_save')
            if not spec:
                require(payload.get('ability') in ('STR','DEX') and type(data.get('escape_dc')) is int,'Choose Strength or Dexterity against the actual recorded source DC.')
                spec={'ability':payload['ability'],'dc':data['escape_dc']}
            repeat_save(session,target,payload['condition_instance'],spec,'Wash Away',extra_mode='ADVANTAGE',initiator=aid)
        e['command_used']=window(session)
        session.emit('COMMAND_THE_CURRENT',aid,source=FIELD,mode=mode,target=target)
        return True
    if kind in ('riverway_distance_propose','riverway_distance'):
        require(set(payload)=={'target','destination'} and payload['target'] in session.state['actors'],'Declare the moving creature and destination.')
        target=payload['target'];e=field_of(session,aid)
        require(e is not None and not actor['incapacitated'],'Only the field creator may offer River Without Distance.')
        destination=Position.model_validate(payload['destination'])
        require(destination in distance_points(session,aid,target),'Choose an immediate, legal River Without Distance destination.')
        if kind=='riverway_distance_propose':
            actor['riverway_distance_proposal']={'target':target,'destination':destination.model_dump(mode='json'),
                'origin':dict(session.state['actors'][target]['position']),'window':window(session)}
            session.emit('MOVEMENT_PROPOSED',aid,source=FIELD,target=target,mode='River Without Distance',
                origin=dict(session.state['actors'][target]['position']),destination=destination.model_dump(mode='json'))
            return True
        from ..fact_consent_admission import read
        consent=read(session,FIELD,target,'riverway_distance_consent',carry_scope(session,aid,target,payload['destination'],kind='distance'),aid)
        require(consent is not None and consent['value']==1,'The moving creature must consent to this declared teleport.')
        old=position(session,target);creature=session.state['actors'][target]
        fall_engine=session.movement_projection() if not session.support_at(target,destination) else None
        e['distance_used']=window(session);creature['position']=destination.model_dump(mode='json')
        session.emit('TRAVEL_TELEPORT',target,source=FIELD,source_actor_id=aid,willing=1,
            origin=old.model_dump(mode='json'),destination=creature['position'],elapsed_seconds=0)
        from . import run_strict
        run_strict('journey_position_committed',session,target,old,destination,session.state['events'][-1])
        if fall_engine is not None:
            from .journey_world import settle_arrival
            settle_arrival(session,target,FIELD,engine=fall_engine)
        return True
    return None


@hook('journey_position_committed')
def position_committed(session,aid,old,nxt,event):
    if not any(source in (MOON,FIELD) for _,source,_ in effects(session)):return
    session.state['actors'][aid]['riverway_last_step']={'position':nxt.model_dump(mode='json'),
        'event_sequence':len(session.state['events']),'clock_num':session.clock().numerator,'clock_den':session.clock().denominator}


@hook('fact_admitted')
def carry_answered(session,record):
    if record['source']!=FIELD or record['kind'] not in ('riverway_carry_consent','riverway_distance_consent'):return
    target=record['subject'];distance=record['kind']=='riverway_distance_consent'
    key='riverway_distance_proposal' if distance else 'riverway_carry_proposal'
    for owner,actor in session.state['actors'].items():
        proposal=actor.get(key)
        if not proposal or proposal['target']!=target or proposal['window']!=window(session):continue
        if record['scope']!=carry_scope(session,owner,target,proposal['destination'],kind='distance' if distance else 'carry'):continue
        field=field_of(session,owner)
        available=field and field.get('distance_used' if distance else 'command_used')!=window(session)
        if record['value']==1 and available:
            derived_commands(session,owner,'riverway_distance' if distance else 'riverway_command',
                {'target':target,'destination':proposal['destination'],**({} if distance else {'mode':'Carry'})})
        actor.pop(key,None)


@hook('journey_option_rank')
def consent_rank(session,aid,row):
    payload=row.get('payload',{})
    if row.get('kind')=='declare_fact' and payload.get('source')==FIELD and payload.get('kind') in ('riverway_carry_consent','riverway_distance_consent'):return 0


@hook('journey_auto_blocked')
def player_passenger_pending(session,aid):
    field=field_of(session,aid)
    if not field:return None
    for key,used in (('riverway_carry_proposal','command_used'),('riverway_distance_proposal','distance_used')):
        proposal=session.state['actors'][aid].get(key)
        if not proposal or proposal['window']!=window(session) or field.get(used)==window(session):continue
        target=session.state['actors'][proposal['target']]
        if target['position']==proposal['origin'] and target['control_mode']=='MANUAL':return True


def distance_points(session,owner,target):
    from .journey_world import actor_state,legal_volume
    from ..typed_executor import condition_rules
    e=field_of(session,owner)
    if not e or e.get('distance_used')==window(session):return []
    actor=session.state['actors'][target];last=actor.get('riverway_last_step',{})
    if (last.get('position')!=actor['position'] or last.get('clock_num')!=session.clock().numerator
            or last.get('clock_den')!=session.clock().denominator or last.get('event_sequence',-1)<=e.get('created_sequence',0)
            or not contains(e,position(session,target))):return []
    if any(r.get('no_teleport') for r in condition_rules(actor_state(session,target))):return []
    origin=position(session,target);result=[]
    for z in range(e['cells'][0].get('z',0),e['cells'][0].get('z',0)+8):
        for y in range(max(0,origin.y-4),min(session.grid.height,origin.y+5)):
            for x in range(max(0,origin.x-4),min(session.grid.width,origin.x+5)):
                p=Position(x=x,y=y,z=z)
                if p==origin or not contains(e,p) or session.grid.distance_ft(origin,p)>20:continue
                if not legal_volume(session,target,p) or not environment.permits(session.grid,origin,p,teleport=True):continue
                if any(a!=target and position(session,a)==p for a in session.state['actors']):continue
                result.append(p)
    return result


@hook('journey_elapsed')
def source_turn_started(session,aid,before,seconds,moving):
    if int(before//6)==int(session.clock()//6):return
    from .journey_world import relation
    for owner,source,e in effects(session):
        if owner!=aid or source not in (PASSAGE,FIELD):continue
        selected=e['starters'] if source==PASSAGE else e['chosen']
        for target in selected:
            p=position(session,target)
            near=contains(e,p) if source==FIELD else any(session.grid.distance_ft(p,Position.model_validate(c))<=5 for c in e['cells'])
            if near and relation(session,owner,target)=='ALLY':
                e.setdefault('start_grants',{})[target]=window(session)
                session.emit('TURN_MOVEMENT_AVAILABLE',target,source=source,owner_id=owner,feet=5,window=window(session))
