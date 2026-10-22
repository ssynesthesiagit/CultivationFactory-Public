"""Soul contracts: source-owned native rituals, signatures, Claims and foreclosure.

Subjective declarations use fact_consent_admission; costs, elapsed ritual time,
resource pledges and foreclosure use committed native state. A contract is one
ledger with per-party breach/rights, not a generic mark on unrelated creatures.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import json
from . import hook, effect
from ..fact_consent_admission import read, digest, canonical
from ..journey import require, integer

PARENT='tianxia.subpath.qi.soul_collateral_contract_cultivator'
PREFIX=PARENT+'.feature.'
FEATURES=('sign_in_living_qi','foreclose_minor_collateral','major_soul_covenant','soul_foreclosure','sovereign_soul_contract')
LEVELS=(3,6,10,14,18)
QI='resource:core.qi'
LEDGER='condition:typed.soul_contract_ledger'
STATE='soul_contracts'
CHOICE='choice:needle.soul_contract.'
MINOR={'qi','blood','item','movement','voice','service'}
MAJOR={'cultivation_points','system','armament','movement_mode','memory','lifespan','office','asset','item'}
SOVEREIGN={'resource','system','soul','lifespan','bloodline','item','office','service'}


def owned(bundle, feature):
    return any(a.get('parameters',{}).get('soul_contract_feature')==feature for a in bundle.get('action_catalog',()))


def numbers(bundle):
    return next((a['parameters']['typed']['numbers'] for a in bundle.get('action_catalog',())
                 if a.get('parameters',{}).get('soul_contract_feature')), {})


def contracts(session):
    return session.state.setdefault(STATE,{})


@hook('fact_admission_schema')
def declaration_schema(session,source,subject,kind):
    if source != PARENT or not any(owned(a['bundle'],FEATURES[0]) for a in session.state['actors'].values()):
        return None
    types={'offer':'document','signature':'document','breach':'document','release':'flag','accept_assignment':'flag','binding_basis':'document'}
    if kind in types:
        return {'value_type':types[kind],'maximum_seconds':2592000,
                'description':'Exact soul-contract offer, knowing signature, breach, release or assignment acceptance.'}


def live(session, c):
    return not c.get('ended') and (c['expires_at']==0 or session.clock()<c['expires_at'])


def sync_bundles(session):
    # This source-owned extension travels with the real paid character bundle.
    # CombatService re-seals bundles at combat entry; no core ability dispatch.
    for aid, actor in session.state['actors'].items():
        actor['bundle'][STATE]={'clock':int(session.clock()),'scene_id':session.state.get('scene_id',session.state['journey_id']),
                               'binding_lockouts':list(session.state.get('soul_contract_binding_lockouts',[])),'contracts':deepcopy(session.state.get(STATE,{})),
                               'admissions':deepcopy(session.state.get('fact_consent_admission',[])),
                               'acquired_sheet':actor.get('soul_contract_acquired_sheet',''),'training':deepcopy(actor.get('soul_contract_training',{})),
                               'secrets':deepcopy(actor.get('soul_contract_secrets',{})),'channels':deepcopy(actor.get('soul_contract_channels',{})),
                               'recovery':deepcopy(actor.get('soul_contract_recovery',{})),
                               'properties':deepcopy(actor.get('soul_contract_properties',{})),
                               'source_effects':deepcopy(actor.get('soul_contract_effects',[]))}
        actor.setdefault('source_states',{})[PARENT]=deepcopy(actor['bundle'][STATE])


def validate_offer(session, actor_id, offer):
    required={'grade','parties','consideration','terms','duration_seconds','completion','collateral','breach_trigger',
              'foreclosure_right','release_conditions','acceptance','authorized_assignees','remote','hidden_text_cl'}
    mandatory=required | ({'anchor'} if offer.get('grade')=='sovereign' else set())
    require(mandatory<=set(offer)<=mandatory|{'severe_breach_trigger'},'A contract must name every component, its exact collateral and authorized assignees.')
    require(type(offer.get('severe_breach_trigger','')) is str,'Define a severe breach explicitly, or omit it.')
    grade=offer['grade']; require(grade in ('minor','major','sovereign'),'Choose Minor, Major or Sovereign grade.')
    actor=session.state['actors'][actor_id]; b=actor['bundle']; n=numbers(b)
    feature={'minor':FEATURES[0],'major':FEATURES[2],'sovereign':FEATURES[4]}[grade]
    require(owned(b,feature),'This creature has not acquired this contract grade.')
    parties=offer['parties']
    require(isinstance(parties,list) and actor_id in parties and len(parties)==len(set(parties))
            and set(parties)<=set(session.state['actors']), 'Name distinct present parties including the creditor.')
    require(all(type(offer[k]) is str and offer[k].strip() for k in
                ('consideration','terms','completion','breach_trigger','foreclosure_right','release_conditions')),
            'Define consideration, terms, completion, breach, foreclosure and release explicitly.')
    require(offer['acceptance'] in ('voluntary','coerced','conquered','inherited','imposed'),'Choose the actual acceptance state.')
    require(type(offer['remote']) is int and offer['remote'] in (0,1) and integer(offer['hidden_text_cl']), 'Use sourced remote and hidden-text authority.')
    duration=offer['duration_seconds']; require(integer(duration) and (0<duration<=28800 if grade=='minor' else
        0<duration<=2592000 if grade=='major' else duration==0),'Use this grade’s printed duration.')
    require(set(offer['authorized_assignees'])<=set(session.state['actors']),'Name present authorized assignees.')
    limit=10 if grade=='minor' else 5 if grade=='major' else 0
    from ..gate2_runtime_models import Position
    if grade!='sovereign':
        require(all(session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(session.state['actors'][p]['position']))<=limit
                    for p in parties),'Every party must be within the ritual’s range.')
    pledges=offer['collateral']; require(isinstance(pledges,dict) and set(pledges)==set(parties),'Pledge collateral separately for every party.')
    for party,rows in pledges.items():
        require(isinstance(rows,list) and 1<=len(rows) and (grade=='sovereign' or len(rows)<=(1 if grade=='minor' else 2)), 'Too many collateral pledges for this grade.')
        for row in rows:
            require(isinstance(row,dict) and set(row) >= {'kind','name','amount','resource','procedure'} and set(row) <= {'kind','name','amount','resource','procedure','destination','recipient','territory'}
                    and row['kind'] in (MINOR if grade=='minor' else MAJOR if grade=='major' else SOVEREIGN)
                    and type(row['name']) is str and row['name'].strip() and integer(row['amount'])
                    and type(row['procedure']) is str and row['procedure'].strip(), 'Name exact legal collateral and its transfer procedure.')
            kind=row['kind']; pb=int(n['pb']); target=session.state['actors'][party]
            if kind in ('qi','resource','cultivation_points'):
                require(row['resource'] in target['resources'],'The party does not own the pledged resource.')
                maximum=pb if grade=='minor' else 2*pb if grade=='major' else next(r['maximum'] for r in target['bundle']['actor_template']['resources'] if r['resource_id']==row['resource'])
                require(1<=row['amount']<=maximum,'The pledge exceeds this grade’s resource limit.')
                if grade=='sovereign':require(row['amount']==maximum,'A Sovereign resource pledge names the entire cultivation resource.')
                if grade=='minor':require(row['amount']<=target['resources'][row['resource']], 'Current-point collateral must exist when pledged.')
            if kind=='system':
                require(row['resource'] in cultivation_systems(target['bundle']),'Pledge an actually acquired named cultivation system, Sphere or technique family.')
            if row.get('territory'):
                from ..gate2_runtime_models import Position
                require(isinstance(row['territory'],list) and all(session.grid.volume_legal(Position.model_validate(pos)) for pos in row['territory']),
                    'The named territory must consist of legal mapped spaces on this plane.')
            if kind=='service':
                require(row['procedure'] in ('ordinary_movement','drop_item','open_door','deliver_object','perform_service'),
                    'Choose the actual native ordinary action procedure pledged by the Contract.')
                if row['procedure']=='deliver_object':require(row.get('recipient') in session.state['actors'],'Name the actual recipient of the pledged delivery.')
            if kind=='voice':require(row['resource'] in target.get('soul_contract_secrets',{}),'Name a privately recorded secret this party actually knows.')
            if kind=='blood':
                require(1<=row['amount']<=2*pb,'Minor blood collateral is limited to twice Proficiency Bonus.')
            if kind in ('memory','lifespan','office','soul','bloodline'):
                prop=target.get('soul_contract_properties',{}).get(row['resource'])
                require(prop is not None and prop['kind']==kind and prop['quantity']>=row['amount']>0,
                        'Pledge an actually recorded property owned by this party, within its remaining quantity.')
                require(not prop['exceptional'] or prop['pledge_permitted'] or int(n['cl'])>=prop['source_cl'],
                        'This exceptional property’s Source Rule does not permit a lower-authority pledge.')
            if kind=='lifespan':
                require(1<=row['amount']<=(1 if grade=='major' else 10),'This grade cannot pledge that many years.')
            if row.get('destination') is not None:
                from ..gate2_runtime_models import Position
                destination=Position.model_validate(row['destination'])
                require(session.grid.volume_legal(destination),'Name a legal destination on this plane.')
            if kind in ('item','asset'):
                # No decorative name or subjective declaration invents an item.
                items=(target['bundle'].get('carrying') or {}).get('items',[])
                require(any(i.get('key')==row['resource'] for i in items),'Pledge a real held/carried inventory item.')
    return deepcopy(offer)


@hook('journey_command')
def ritual_command(session,actor_id,kind,payload):
    if kind not in ('soul_contract_create','soul_contract_breach','soul_contract_release'):
        return None
    actor=session.state['actors'][actor_id]
    require(not actor['incapacitated'],'An incapacitated creature cannot perform a contract procedure.')
    if kind=='soul_contract_create':
        require(set(payload)=={'offer_scope'},'Choose a declared exact offer.')
        record=read(session,PARENT,actor_id,'offer',payload['offer_scope'],actor_id)
        require(record is not None,'Declare a current contract offer first.')
        offer=validate_offer(session,actor_id,record['value']); scope=digest(offer)
        signatures={};unwilling=[]
        for party in offer['parties']:
            signed=read(session,PARENT,party,'signature',scope,actor_id)
            if signed is None or signed['value'].get('resisting')==1:
                require(offer['grade']!='minor','A Minor Contract cannot bind an unwilling resisting party.')
                basis=read(session,PARENT,party,'binding_basis',scope,actor_id)
                require(basis is not None and set(basis['value'])=={'basis','source_rule','anti_contract'} and
                    basis['value']['basis'] in ('completely_subdued','formally_surrendered','accepted_release','inherited','recognized_authority') and
                    type(basis['value']['source_rule']) is str and basis['value']['source_rule'].strip() and
                    type(basis['value']['anti_contract']) is int and basis['value']['anti_contract'] in (0,1),
                    'An unwilling party requires its controller’s explicit surrendered, release, inherited Source Rule or recognized authority input.')
                unwilling.append((party,basis))
                signatures[party]=basis['receipt_id']
                continue
            require(signed is not None and set(signed['value'])=={'knowing','resisting','method'} and
                    signed['value']['knowing']==1 and signed['value']['resisting']==0 and
                    type(signed['value']['method']) is str and signed['value']['method'].strip(),
                    'Every party must knowingly sign this exact offer; resistance is never inferred from friendship.')
            signatures[party]=signed['receipt_id']
        grade=offer['grade']; cost={'minor':2,'major':6,'sovereign':10}[grade]
        require(actor['resources'].get(QI,0)>=cost,'Insufficient Qi for this ritual.')
        if grade=='sovereign':
            anchor=offer['anchor']
            require(isinstance(anchor,dict) and set(anchor)=={'holder','item_key'} and anchor['holder'] in offer['parties'],
                    'Name the present holder and stable identity of the required Sovereign Anchor.')
            inventory=session.state['actors'][anchor['holder']]['bundle'].get('carrying',{}).get('items',[])
            require(any(i['key']==anchor['item_key'] for i in inventory),'The Sovereign Anchor must be a real acquired item.')
            require(not any(live(session,old) and old.get('anchor')==anchor for old in contracts(session).values()),
                    'That real item is already an active Contract Anchor.')
        lockouts=session.state.setdefault('soul_contract_binding_lockouts',[])
        require(not any(p in lockouts for p,basis in unwilling),'This party resisted binding and cannot be targeted again during this scene.')
        actor['resources'][QI]-=cost
        if actor['resources'][QI]==0:actor['exhaustion']+=1
        ritual={'minor':60,'major':600,'sovereign':3600}[grade]
        session.tick(ritual)
        # Acceptance must remain live through the completed ritual.
        require(all(read(session,PARENT,p,'signature',scope,actor_id) is not None for p in offer['parties'] if p not in {q for q,basis in unwilling}),
                'A signature expired before the ritual finished.')
        for party,basis in unwilling:
            from ..gate2_rolls import DeterministicRollAuthority
            roller=DeterministicRollAuthority(session.state['journey_id']+':soul_binding',counter=session.state.get('soul_contract_roll_counter',0))
            target=session.state['actors'][party]['bundle']
            n=numbers(actor['bundle'])
            automatic=int(target['cl'])<=int(n['cl'])-6 and basis['value']['basis']=='completely_subdued' and not basis['value']['anti_contract']
            if automatic:
                success=True
                session.emit('SOUL_CONTRACT_AUTOMATIC_SAVE_FAILURE',party,source=PARENT,basis_receipt=basis['receipt_id'])
            else:
                roll=roller.d20(modifier=target['actor_template']['saving_throws'].get('CHA',0),actor_id=party,reason='SOUL_CONTRACT_BINDING_SAVE')
                session.emit('SOUL_CONTRACT_BINDING_ROLLED',party,roll=canonical(roll.model_dump(mode='json')),save_dc=int(n['save_dc']))
                success=roll.total<int(n['save_dc'])
            if success and int(target['cl'])>=int(n['cl'])+3:
                check=roller.d20(modifier=int(n['pb'])+int(n['key_mod']),actor_id=actor_id,reason='SOUL_CONTRACT_SUPERIOR_AUTHORITY_CHECK')
                dc=int(next((a.get('parameters',{}).get('typed',{}).get('numbers',{}).get('save_dc') for a in target['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('numbers',{}).get('save_dc')),10))
                session.emit('SOUL_CONTRACT_BINDING_CHECK',actor_id,roll=canonical(check.model_dump(mode='json')),save_dc=dc)
                success=success and check.total>=dc
            session.state['soul_contract_roll_counter']=roller.counter
            if not success:
                lockouts.append(party)
                session.emit('SOUL_CONTRACT_BINDING_RESISTED',party,source=PARENT,scene_lockout=1)
                sync_bundles(session)
                return True
        cid=digest({'journey':session.state['journey_id'],'offer':scope,'sequence':len(contracts(session))})
        n=numbers(actor['bundle'])
        c={**offer,'id':cid,'owner':actor_id,'source_cl':int(n['cl']),'pb':int(n['pb']),'save_dc':int(n['save_dc']),
           'created_at':int(session.clock()),'expires_at':int(session.clock())+offer['duration_seconds'] if offer['duration_seconds'] else 0,
           'claims':{p:0 for p in offer['parties']},'rights':{p:actor_id for p in offer['parties']},
           'breached':[],'breach_receipts':[],'signatures':signatures,'ended':0,'assignments':[],'released_parties':[]}
        contracts(session)[cid]=c
        session.emit('SOUL_CONTRACT_CREATED',actor_id,contract_id=cid,grade=grade,qi_spent=cost,ritual_seconds=ritual)
    else:
        require(set(payload)=={'contract_id'},'Choose one contract.')
        c=contracts(session).get(payload['contract_id'])
        require(c is not None and live(session,c) and actor_id in c['parties'],'Choose your own active contract.')
        if kind=='soul_contract_breach':
            receipt=read(session,PARENT,actor_id,'breach',c['id'],c['owner'])
            require(receipt is not None and set(receipt['value'])=={'knowing','severity','term'} and
                    receipt['value']['knowing']==1 and receipt['value']['term']==(c.get('severe_breach_trigger','') if receipt['value']['severity']=='severe' and c['grade']=='major' else c['breach_trigger']),
                    'A knowing breach must identify this contract’s exact defined breach trigger.')
            require(receipt['receipt_id'] not in c['breach_receipts'],'This breach has already produced Claims.')
            severity=receipt['value']['severity'];require(severity in ('meaningful','severe'),'Choose the printed breach severity.')
            if severity=='severe' and c['grade']=='major':require(bool(c.get('severe_breach_trigger','').strip()),'This Contract did not explicitly define a severe breach.')

            count=1 if c['grade']=='minor' else c['pb'] if c['grade']=='sovereign' else 3 if severity=='severe' else 2
            c['claims'][actor_id]+=min(count,max(0,c['pb']-sum(c['claims'].values())))
            if actor_id not in c['breached']:c['breached'].append(actor_id)
            c['breach_receipts'].append(receipt['receipt_id'])
            if c['grade']=='sovereign':c.setdefault('pending_penalties',[]).append(actor_id)
            session.emit('SOUL_CONTRACT_BREACHED',actor_id,contract_id=c['id'],claims=count,receipt_id=receipt['receipt_id'])
        else:
            require(all((r:=read(session,PARENT,p,'release',c['id'],actor_id)) and r['value']==1 for p in c['parties']),
                    'Mutual release requires every party’s explicit current acceptance.')
            c['ended']=1;c['claims']={p:0 for p in c['parties']}
            release_travel_collateral(session,c)
            session.emit('SOUL_CONTRACT_RELEASED',actor_id,contract_id=c['id'])
    sync_bundles(session)
    return True


@hook('journey_elapsed')
def expire_journey(session,actor_id,before,elapsed,moving):
    if actor_id!=next(iter(session.state['actors'])) or not session.state.get(STATE):return
    for c in session.state[STATE].values():
        if not c['ended'] and c['expires_at'] and session.clock()>=c['expires_at']:
            c['ended']=1;c['claims']={p:0 for p in c['parties']}
            release_travel_collateral(session,c)
            session.emit('SOUL_CONTRACT_EXPIRED',c['owner'],contract_id=c['id'])
    sync_bundles(session)


@hook('compile_actions')
def compile_contracts(info):
    from ..gate2_runtime_models import ActionDefinition
    ids=set(info['owned_ids']); cl=int(info['numbers']['cl'])
    owned_ids={f for f,l in zip(FEATURES,LEVELS) if PREFIX+f in ids and cl>=l}
    if not owned_ids:return None
    def make(feature,key,label,economy='ACTION',cost=0):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.soul_contract.{key}",
            display_name=label,owner_id=info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind='SELF',
            costs=((QI,cost),) if cost else (),parameters={'soul_contract_feature':feature,'soul_contract_operation':key,
            'expected_damage':0,'description':contract_action_text(key),
            'typed':{'source':PREFIX+feature,'numbers':dict(info['numbers']),'riders':[],
                     'manual_inline_choice':True,'effects':[{'type':'soul_contract_procedure','operation':key}]}})
    actions=[]
    for f in owned_ids:
        if f==FEATURES[0]:actions.append(make(f,'sight','Contract Sight: Analyze Soul Contract'))
        elif f==FEATURES[1]:
            for key,label in [('qi','Qi'),('blood_necrotic','Blood — Necrotic'),('blood_psychic','Blood — Psychic'),('item','Item'),('movement','Movement'),('voice','Voice'),('service','Service')]:
                actions.append(make(f,'minor_'+key,'Foreclose Minor Collateral: '+label,'BONUS_ACTION'))
            actions.append(make(f,'transfer','Claim Transfer',cost=2))
        elif f==FEATURES[2]:actions.append(make(f,'anchor','Challenge Contract Anchor'))
        elif f==FEATURES[3]:
            actions.extend([make(f,'call','Call the Contracted Party',cost=5),make(f,'cultivation','Foreclose Cultivation'),make(f,'payment','Seize the Payment')])
        else:
            actions.extend([make(f,'court','Contract Court',cost=8),make(f,'final','Final Foreclosure'),make(f,'penalty','Sovereign Breach: Enforce the Pledged Penalty',economy='NONE')])
    return actions


def ledgers(engine):
    return [(a,c) for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id==LEDGER]


def active_rows(engine):
    result=[]
    for holder,c in ledgers(engine):
        doc=json.loads(c.data['contract'])
        if not doc['ended']:result.append((holder,c,doc))
    return result


@hook('match_initialize')
def import_contracts(engine):
    for b in engine.typed_bundle_documents:
        data=b.get(STATE)
        if not data:continue
        owner=engine.state.actors.get(b['actor_id'])
        if owner is None:continue
        for c in data['contracts'].values():
            if c['owner']!=owner.entity_id or c['ended']:continue
            remain=c['expires_at']-data['clock'] if c['expires_at'] else 0
            if c['expires_at'] and remain<=0:continue
            engine._apply_condition(owner,LEDGER,PREFIX+FEATURES[0],owner.entity_id,expires_on='UNTIL_REMOVED',
                data={'contract':canonical(c),'remaining_seconds':remain,'start_round':engine.state.round_number,
                      'label':'Soul Contract: '+c['grade'].title()+'; explicit pledges and Claims'})

    for holder,condition,c in active_rows(engine):
        if c['grade']=='minor':continue
        from .bound_objects import place
        from .retained_updates import record_instance_update
        for party in c['parties']:
            if c['grade']=='sovereign' and party!=c['anchor']['holder']:continue
            target=engine.state.actors.get(party)
            if target is None:continue
            source=PREFIX+(FEATURES[4] if c['grade']=='sovereign' else FEATURES[2])
            engine._apply_condition(target,'condition:typed.soul_contract_party',source,holder.entity_id,
                expires_on='UNTIL_REMOVED',data={'contract_id':c['id'],'label':'Contract Anchor on '+target.display_name})
            member=next(x for x in reversed(list(target.conditions.values())) if x.condition_id=='condition:typed.soul_contract_party' and x.data['contract_id']==c['id'])
            from ..typed_executor import Context
            action=next(a for a in engine.action_catalog.values() if a.owner_id==holder.entity_id and a.parameters.get('soul_contract_feature'))
            context=Context(engine,holder,action,None,{'source':source,'numbers':{'cl':c['source_cl'],'pb':c['pb'],'save_dc':c['save_dc']}},[],None,{},effect_source=source)
            sovereign=c['grade']=='sovereign'
            obj=place(context,{'name':('Sovereign ' if sovereign else 'Major ')+'Soul Contract Anchor',
                'kind':'soul_contract_anchor','ac':c['save_dc']+2 if sovereign else c['save_dc'],
                'hp':(12 if sovereign else 5)*c['source_cl'],'resist':[] if sovereign else ['BLUDGEONING','PIERCING','SLASHING'],
                'native_lifecycle':True},holder=target,instance_ids=[member.instance_id],position=target.position)
            if obj is not None:
                updated=obj.model_copy(update={'component':{**obj.component,'soul_contract':c['id'],'party':party,
                    'source_cl':c['source_cl'],'sovereign':int(sovereign)}})
                saved=c.get('anchor_state',{}).get(party)
                if saved:
                    prior=json.loads(saved)
                    updated=updated.model_copy(update={'current_hp':prior['current_hp'],'destroyed':prior['destroyed'],
                        'component':{**updated.component,**({'soul_escrow':prior['component']['soul_escrow']} if prior['component'].get('soul_escrow') else {})}})
                engine._update_object(updated,source,holder.entity_id)
                c.setdefault('anchor_ids',{})[party]=obj.object_id
                if sovereign:
                    engine._apply_condition(target,'condition:typed.soul_contract_anchor_item',source,holder.entity_id,
                        expires_on='UNTIL_REMOVED',data={'contract_id':c['id'],'item_key':c['anchor']['item_key'],
                        'held_by':party,'object_location':'anchor','object_id':obj.object_id,
                        'label':'Real item serves as Sovereign Contract Anchor'})
        write(engine,holder,condition,c)


def claim_balance(c,party,actor_id):
    assigned=sum(a['claims'] for a in c.get('assignments',[]) if a['party']==party)
    return (c['claims'][party]-assigned if actor_id==c['rights'][party] else
            sum(a['claims'] for a in c.get('assignments',[]) if a['party']==party and a['assignee']==actor_id))


def in_court(engine,actor,c,target=None):
    from .placed import of,data
    from ..zones import actor_inside_zone
    target=target or actor
    return any(data(z).get('contract_id')==c['id'] and actor_inside_zone(engine,target,z)
               for z in of(engine,'soul_contract_court',owner_id=c['owner']))


def claim_cost(engine,actor,c,amount):
    return max(1,amount-int(in_court(engine,actor,c)))


def spend_claims(engine,actor,c,party,amount):
    require(claim_balance(c,party,actor.entity_id)>=amount,'Insufficient Claims owned by this creditor for this party.')
    if actor.entity_id!=c['rights'][party]:
        remaining=amount
        for a in c.get('assignments',[]):
            if a['party']==party and a['assignee']==actor.entity_id:
                spent=min(remaining,a['claims']);a['claims']-=spent;remaining-=spent
    c['claims'][party]-=amount


def write(engine,holder,condition,doc):
    condition.data['contract']=canonical(doc)
    from .retained_updates import record_instance_update
    record_instance_update(engine,holder,'condition',condition.instance_id,condition)


def available(engine,actor,op):
    # No invented expenditure rule for the source's unresolved final clause.
    if op=='final':return []
    out=[]
    for holder,condition,c in active_rows(engine):
        if op in ('sight','anchor','court'):
            if op=='sight':
                from ..senses import of
                normal_range=int((of(engine,actor).get('qi_sensing') or {}).get('range_ft') or 0)
                if normal_range<=0 or not any(engine._distance_actor_to_actor(actor,engine.state.actors[p])<=normal_range for p in c['parties']):continue
            if op=='anchor' and not any(oid in engine.state.objects and not engine.state.objects[oid].destroyed and engine.grid.distance_ft(actor.position,engine.state.objects[oid].position)<=5 and (actor.entity_id==party or actor.team_id==engine.state.actors[party].team_id) for party,oid in c.get('anchor_ids',{}).items()):continue
            if op=='court' and (c['grade']!='sovereign' or c['owner']!=actor.entity_id or c.get('court_used')):continue
            out.append((holder,condition,c,None));continue
        if c['owner']!=actor.entity_id and actor.entity_id not in c['rights'].values() and not any(a['assignee']==actor.entity_id and a['claims'] for a in c.get('assignments',[])):continue
        for party in c['breached']:
            target=engine.state.actors.get(party)
            if target is None or party in c.get('released_parties',[]) or (op!='penalty' and claim_balance(c,party,actor.entity_id)<=0):continue
            price=claim_cost(engine,actor,c,3 if op=='cultivation' else 1)
            if op!='penalty' and claim_balance(c,party,actor.entity_id)<price:continue
            if op=='penalty' and (c['grade']!='sovereign' or c['owner']!=actor.entity_id or party not in c.get('pending_penalties',[])):continue
            if op=='final' and (not in_court(engine,actor,c,target) or c.get('final_used') or claim_balance(c,party,actor.entity_id)<4):continue
            if op.startswith('minor_') and c['grade']!='minor':continue
            if op in ('call','cultivation','payment') and c['grade']=='minor':continue
            if op in ('court','final') and c['grade']!='sovereign':continue
            if op.startswith('minor_'):
                kind=op[6:].split('_')[0]
                if not any(p['kind']==kind for p in c['collateral'][party]):continue
            # Same-plane is implicit in this encounter. Remote permission is
            # explicit; it never bypasses legal movement geometry.
            if not c['remote'] and not in_court(engine,actor,c,target) and engine._distance_actor_to_actor(actor,target)>60:continue
            out.append((holder,condition,c,party))
    return out


@hook('candidate_allowed')
def candidates(engine,actor,candidate,action):
    op=(action.parameters if action is not None else {}).get('soul_contract_operation')
    if not op:return None
    return bool(available(engine,actor,op))


def pick(ctx,key,options,labels,chooser=None,prompt=''):
    from .needle import ask,checkpoint_id
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'soul_contract',key),chooser or ctx.actor,
        CHOICE+key,options,labels=labels,preferred=[],minimum=1,maximum=1,allow_decline=False,
        prompt=prompt,name=ctx.action.display_name,feature_id=ctx.source)


def condition(ctx,target,kind,rule,until,label,**data):
    from ..typed_executor import stated_expiry
    ctx.engine._apply_condition(target,'condition:typed.soul_contract_'+kind,ctx.source,ctx.actor.entity_id,
        expires_on=stated_expiry(ctx,{'expires_on':until},target,condition=True),data={'rule':rule,'label':label,**data})


def resource(engine,target,rid,delta,source):
    before=target.resources.get(rid,0)
    if delta < 0:
        amount=min(before,-delta)
        target.resources[rid]=before-amount
        engine._append_event('RESOURCE_EXPIRED',source,actor_id=target.entity_id,
            payload={'resource_id':rid,'before':before,'after':before-amount})
        if rid==QI and before>0 and before-amount==0:
            from .forged_exhaustion import add
            add(engine,target,1,source)
    else:
        engine._gain_resource(target,rid,delta,source)
    return target.resources.get(rid,0)-before


@effect('soul_contract_procedure')
def procedure(ctx,row):
    op=row['operation'];rows=available(ctx.engine,ctx.actor,op)
    assigned=ctx.action.parameters.get('soul_contract_assigned_contract')
    if assigned:rows=[r for r in rows if r[2]['id']==assigned]
    if not rows:return
    keys={c['id']+':'+str(p):(h,cond,c,p) for h,cond,c,p in rows}
    labels={k:f"{c['grade'].title()} Contract — {ctx.engine.state.actors[p].display_name if p else ', '.join(ctx.engine.state.actors[x].display_name for x in c['parties'])}; {c['claims'].get(p,0)} Claims"
            for k,(h,cond,c,p) in keys.items()}
    choice=pick(ctx,'contract',list(keys),labels,prompt=ctx.action.display_name+': choose one active contract and party. Only its exact collateral may be foreclosed.')
    h,cond,c,p=keys[choice[0]]
    if op=='sight':
        visible={'parties':[ctx.engine.state.actors[a].display_name for a in c['parties']], 'grade':c['grade'],
            'breached':int(bool(c['breached'])),'collateral_categories':sorted({r['kind'] for rs in c['collateral'].values() for r in rs}),
            'source_cl':c['source_cl'],'acceptance':c['acceptance']}
        from ..observer_information import publish
        text='Soul Contract: '+visible['grade']+'; parties '+', '.join(visible['parties'])+'; '+('breached' if visible['breached'] else 'not breached')+'; collateral '+', '.join(visible['collateral_categories'])+'; Source CL '+str(visible['source_cl'])+'; acceptance '+visible['acceptance']+'.'
        publish(ctx.engine,ctx.actor,ctx.source,ctx.actor,'declaration',{'text':text,'contract_analysis':visible},'UNTIL_REMOVED')
        return
    if op=='anchor':
        reachable=[(party,oid) for party,oid in c.get('anchor_ids',{}).items() if oid in ctx.engine.state.objects
            and not ctx.engine.state.objects[oid].destroyed and ctx.engine.grid.distance_ft(ctx.actor.position,ctx.engine.state.objects[oid].position)<=5
            and (ctx.actor.entity_id==party or ctx.actor.team_id==ctx.engine.state.actors[party].team_id)]
        if not reachable:return
        oid=pick(ctx,'anchor',[oid for party,oid in reachable],{oid:'Challenge the Anchor on '+ctx.engine.state.actors[party].display_name for party,oid in reachable},prompt='Choose one adjacent Contract Anchor for a compatible Cultivation Check against its save DC. This costs your Action.')[0]
        party=next(party for party,key in reachable if key==oid)
        from ..typed_executor import resolve_opposed_check
        from .needle import numbers_of
        check_ctx=replace(ctx,typed={**ctx.typed,'numbers':numbers_of(ctx.engine,ctx.actor)})
        result=resolve_opposed_check(check_ctx,h,{'kind':'cultivation'},{'kind':'dc','dc':c['save_dc']})
        if result.success:
            release_party(ctx.engine,c,party)
            write(ctx.engine,h,cond,c)
        return
    if op=='court':
        from .placed import place
        anchors=[ctx.engine.state.objects[oid] for oid in c.get('anchor_ids',{}).values() if oid in ctx.engine.state.objects and not ctx.engine.state.objects[oid].destroyed]
        if not anchors:return
        ctx.engine._start_concentration(ctx.actor,ctx.source)
        place(ctx.engine,ctx.actor,source=ctx.source,tag='soul_contract_court',cells=[anchors[0].position],
            name='Contract Court — '+ctx.actor.display_name,placed={'contract_id':c['id'],'anchor':anchors[0].object_id},
            numbers=dict(ctx.numbers),duration_rounds=10,concentration=True,shape='sphere',size_ft=40,radial_volume=True,
            color='#b69a67',material='spirit')
        condition(ctx,ctx.actor,'court',{},'UNTIL_REMOVED','Contract Court: 40-foot field; one minute; Concentration; foreclosure costs one fewer Claim, minimum 1',
            contract_id=c['id'],first_round=ctx.engine.state.round_number,rounds=10)
        c['court_used']=1
        write(ctx.engine,h,cond,c);return
    target=ctx.engine.state.actors[p]
    if op=='transfer':
        from .willing_targets import asks_consent
        opts=[a for a in c['authorized_assignees'] if a in ctx.engine.state.actors]
        if not opts:return
        aid=pick(ctx,'assignee',opts,{a:ctx.engine.state.actors[a].display_name for a in opts},prompt='Claim Transfer: Action and 2 Qi. Transfer one Claim and its foreclosure right to a named willing authorized assignee.')[0]
        assignee=ctx.engine.state.actors[aid]
        if not asks_consent(ctx.engine,ctx.intent,assignee,ctx.action.display_name,'Accept one Claim and its foreclosure right?',prefer_accept=False,asker=ctx.actor):return
        if ctx.actor.entity_id!=c['rights'][p]:
            remaining=1
            for assignment in c.get('assignments',[]):
                if assignment['party']==p and assignment['assignee']==ctx.actor.entity_id and assignment['claims'] and remaining:
                    assignment['claims']-=1;remaining=0
        c.setdefault('assignments',[]).append({'party':p,'assignee':aid,'claims':1})
        write(ctx.engine,h,cond,c);return
    pledges=c['collateral'][p]
    if op.startswith('minor_'):
        kind=op[6:].split('_')[0];pledges=[r for r in pledges if r['kind']==kind]
    if op=='cultivation':pledges=[r for r in pledges if r['kind'] in ('system','armament','movement_mode','cultivation_points')]
    if not pledges:return
    idx=pick(ctx,'collateral',[str(i) for i in range(len(pledges))],
        {str(i):r['name']+' — '+r['procedure'] for i,r in enumerate(pledges)},
        prompt=ctx.action.display_name+': choose collateral actually pledged by this party; 1 Claim, unless this action states otherwise.')[0]
    pledge=pledges[int(idx)]
    payment_cost=1
    if op=='payment':
        balance=claim_balance(c,p,ctx.actor.entity_id)
        options=[str(n) for n in range(1,balance+1+int(in_court(ctx.engine,ctx.actor,c)))]
        payment_cost=int(pick(ctx,'payment_claims',options,{n:n+' Claims' for n in options},prompt='Seize the Payment: choose one or more Claims to spend for the exact pledged transfer procedure. Inside Contract Court, the cost is reduced by one, minimum one.')[0])
    if op=='penalty':
        sovereign_penalty(ctx,target,c,pledge)
        c['pending_penalties'].remove(p)
        write(ctx.engine,h,cond,c);return
    if op=='final':
        require(False,'Final Foreclosure Claim expenditure awaits clarification of its conflicting printed cost clauses.')
    if op=='minor_qi':
        removed=-resource(ctx.engine,target,pledge['resource'],-min(c['pb'],pledge['amount']),ctx.source)
        resource(ctx.engine,ctx.actor,QI,(removed+1)//2,ctx.source)
    elif op.startswith('minor_blood'):
        from ..typed_executor import run_effects
        first_event=len(ctx.engine.events)
        run_effects(replace(ctx,target=target,targets=[target]),[{'type':'damage','applies_to':'target','dice':{'count':3,'sides':8},'damage_types':['psychic' if op.endswith('psychic') else 'necrotic']}])
        dealt=sum(int(e.payload.get('hp_damage') or 0)+int(e.payload.get('temporary_hp_absorbed') or 0) for e in ctx.engine.events[first_event:] if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==ctx.source and target.entity_id in e.target_ids)
        beneficiary=pick(ctx,'beneficiary',list(ctx.engine.state.actors),{a:ctx.engine.state.actors[a].display_name for a in ctx.engine.state.actors},prompt='Blood Foreclosure: choose yourself or a named beneficiary to gain Temporary Hit Points equal to half the damage dealt.')[0]
        run_effects(replace(ctx,target=ctx.engine.state.actors[beneficiary],targets=[ctx.engine.state.actors[beneficiary]]),[{'type':'temp_hp','applies_to':'target','flat':dealt//2}])
    elif op=='minor_movement':
        selected=pick(ctx,'movement',['stop','pull'],{'stop':'Speed 0 until the start of the breacher’s next turn','pull':'Pull up to 15 feet toward the named boundary, creditor, prison or delivery point'},prompt='Movement Foreclosure: choose one pledged movement penalty for 1 Claim.')[0]
        if selected=='stop':condition(ctx,target,'movement',{'speed_zero':True},'START_OF_TARGET_NEXT_TURN','Movement Foreclosure: Speed 0 until your next turn starts')
        else:
            from ..typed_executor import run_effects
            distance=int(pick(ctx,'pull_distance',['0','5','10','15'],{str(n):str(n)+' feet toward the named destination' for n in (0,5,10,15)},prompt='Choose how far to pull the breacher, up to 15 feet.')[0])
            destination=pledge.get('destination') or ctx.actor.position.model_dump(mode='json')
            local=replace(ctx,target=target,targets=[target],typed={**ctx.typed,'_area_centre':[destination['x'],destination['y']]})
            run_effects(local,[{'type':'forced_movement','applies_to':'target','distance_ft':distance,'direction':'toward_center'}])
    elif op=='minor_voice':
        condition(ctx,target,'voice',{'silenced':True},'START_OF_SOURCE_NEXT_TURN','Voice Foreclosure: cannot speak, use audible techniques or communicate '+pledge['name'],secret_scope=pledge['resource'])
    elif op=='minor_service':
        if target.reaction_available:
            from .willing_targets import asks_consent
            willing=asks_consent(ctx.engine,ctx.intent,target,'Service Foreclosure',f'Perform the pledged action {pledge["name"]} using your Reaction?',prefer_accept=False,asker=ctx.actor)
            roll=None if willing else ctx.engine._roll_save(target,'CHA',c['save_dc'],ctx.source)
            target.reaction_available=False
            ctx.engine._append_event('REACTION_RESOLVED',ctx.source,actor_id=p,payload={'reason':'Service Foreclosure','gate3_reaction_available_after':False})
            if willing or roll.total<c['save_dc']:
                # Execution of ordinary object/service commands requires their
                # native procedure; never describe narration as a committed act.
                perform_pledged_service(ctx,target,c,pledge)
    elif op=='call':
        from .effect_durations import token
        roll=ctx.engine._roll_save(target,'CHA',c['save_dc'],ctx.source)
        if roll.total>=c['save_dc']:
            condition(ctx,target,'call_resisted',{'speed_zero':True,'no_teleport':True},token('end',target.entity_id,target.turns_started+1),
                'Call the Contracted Party: Speed 0 and no willing teleport until your next turn ends')
        else:call_party(ctx,target,c,pledge)
    elif op=='payment':
        if pledge['kind'] in ('qi','resource','cultivation_points'):
            removed=-resource(ctx.engine,target,pledge['resource'],-pledge['amount'],ctx.source)
            resource(ctx.engine,ctx.actor,pledge['resource'],removed,ctx.source)
        elif pledge['kind'] in ('memory','lifespan','office','soul','bloodline'):
            require(seize_property(ctx,target,c,pledge),'The exact pledged property is not available for this procedure.')
        elif pledge['kind'] in ('item','asset'):move_pledged_item(ctx,target,pledge)
        else:require(False,'The named payment must have an explicit transfer procedure.')
    elif op=='minor_item':
        condition(ctx,target,'item_locked',{},'START_OF_SOURCE_NEXT_TURN',
            'Item Foreclosure: '+pledge['name']+' cannot be activated, dismissed, called, transferred or willingly moved until the creditor’s next turn starts',
            item_key=pledge['resource'],item_owner=target.entity_id,source_cl=int(ctx.numbers['cl']))
        move_pledged_item(ctx,target,pledge,require_superior=True)
    elif op=='cultivation':
        require(pledge['kind'] in ('system','armament','movement_mode','cultivation_points'),'Choose cultivation collateral.')
        roll=ctx.engine._roll_save(target,'CHA',c['save_dc'],ctx.source)
        gap=c['source_cl']-next((int(b['cl']) for b in ctx.engine.typed_bundle_documents if b['actor_id']==p),c['source_cl'])
        extended=False
        if roll.total<c['save_dc'] and gap<=-3:
            from ..typed_executor import resolve_opposed_check
            from .needle import numbers_of
            result=resolve_opposed_check(ctx,target,{'kind':'cultivation'},{'kind':'dc','dc':int(numbers_of(ctx.engine,target)['save_dc'])})
            extended=result.success
        until='START_OF_TARGET_NEXT_TURN' if roll.total>=c['save_dc'] or (gap<=-3 and not extended) else 'UNTIL_REMOVED'
        suppress_collateral(ctx,target,c,pledge,until,rounds=600 if gap<6 and until=='UNTIL_REMOVED' else 0)
    else:
        require(False,'This foreclosure requires its native item, route, Anchor or transfer procedure.')
    spend_claims(ctx.engine,ctx.actor,c,p,claim_cost(ctx.engine,ctx.actor,c,3 if op=='cultivation' else payment_cost if op=='payment' else 1))
    write(ctx.engine,h,cond,c)


@hook('turn_start')
def contract_clock(engine,actor):
    for holder,cond,c in active_rows(engine):
        seconds=int(cond.data['remaining_seconds'])
        if seconds and (engine.state.round_number-int(cond.data['start_round']))*6>=seconds:
            for party in list(c['parties']):release_party(engine,c,party)
            c['ended']=1;c['claims']={p:0 for p in c['parties']};write(engine,holder,cond,c)


@hook('candidate_allowed')
def foreclosed_system(engine,actor,candidate,action):
    if action is None:return None
    source=(action.parameters.get('typed') or {}).get('source','')
    suppressed=suppressed_system_ids(actor)
    if not suppressed:return None
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    systems=cultivation_systems(bundle)
    from ..typed_executor import CP_POOLS
    if all_cultivation_suppressed(engine,actor) and (source in {s for group in systems.values() for s in group} or any(rid in CP_POOLS for rid,amount in action.costs)):return False
    for c in actor.conditions.values():
        if c.condition_id=='condition:typed.soul_contract_suppressed' and (source in systems.get(c.data.get('system'),[]) or source.startswith(c.data.get('system') or '\0') or any(rid==c.data.get('system') for rid,amount in action.costs)):
            return False
    return None


@hook('status_description')
def private_ledger(engine,holder,row,data):
    if row.get('condition_id')!=LEDGER:return None
    return {'display_name':'Active Soul Contract','applied_by':'Contract creditor','conceal_source':True,
        'source_ability':'Soul Contract','rules':'A valid contract records exact pledged collateral. Contract Sight can analyze its grade, parties, breach, collateral categories and authority. Superior protected terms remain private.',
        'duration':'Until fulfillment, release or its recorded expiry'}


@hook('compile_bundle')
def contract_admission(bundle,info):
    paths=info['owner_sheet'].get('path_and_subpath') or {}
    ids=set(paths.get('path_feature_record_ids') or [])
    ids.update(r['feature_id'] for r in paths.get('earned_feature_occurrences',[]) if r.get('feature_id'))
    if any(s.startswith(PREFIX) for s in ids):
        require(not any(s.startswith('tianxia.subpath.qi.oath_ledger_cultivator.feature.') for s in ids),
                'Soul-Collateral replaces Oath-Ledger; the two progressions cannot coexist.')
        # Replace parsed approximations with this family's single native provider.
        removed={a['source_definition_id'] for a in bundle['action_catalog'] if
                 a.get('parameters',{}).get('typed',{}).get('source','').startswith(PREFIX)
                 and not a.get('parameters',{}).get('soul_contract_operation')}
        bundle['action_catalog']=[a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]
        bundle['actor_template']['action_ids']=[sid for sid in bundle['actor_template']['action_ids'] if sid not in removed]
        return bundle
    return None


def release_party(engine,c,party):
    """Release exactly this party; transferred/consumed collateral is not restored."""
    parties=c['parties'] if c['grade']=='sovereign' else [party]
    for person in parties:
        if person not in c.setdefault('released_parties',[]):c['released_parties'].append(person)
        c['claims'][person]=0
    c['assignments']=[a for a in c.get('assignments',[]) if a['party'] not in parties]
    if set(c['released_parties'])==set(c['parties']):c['ended']=1
    # Commit the ledger before synchronous ending subscribers inspect it.
    for holder,ledger in ledgers(engine):
        if json.loads(ledger.data['contract'])['id']==c['id']:write(engine,holder,ledger,c)
    from .condition_ownership import remove_instance
    for holder in engine.state.actors.values():
        for cond in list(holder.conditions.values()):
            if cond.data.get('contract_id')==c['id'] and holder.entity_id in parties and cond.condition_id in (
                    'condition:typed.soul_contract_party','condition:typed.soul_contract_suppressed','condition:typed.soul_contract_points_suppressed','condition:typed.soul_contract_territory'):
                remove_instance(engine,holder,cond.instance_id,PREFIX+FEATURES[2])
    if c['grade']=='sovereign' or set(c['released_parties'])==set(c['parties']):
        c['ended']=1;c['claims']={p:0 for p in c['parties']}


@hook('state_event')
def anchor_released(engine,event):
    if event.event_type!='CONDITION_REMOVED' or event.payload.get('condition_id')!='condition:typed.soul_contract_party':return
    party=next(iter(event.target_ids),None)
    if not party:return
    for holder,cond,c in active_rows(engine):
        oid=c.get('anchor_ids',{}).get(party)
        if oid in engine.state.objects and engine.state.objects[oid].destroyed:
            release_party(engine,c,party);write(engine,holder,cond,c)


@hook('object_damage_defenses')
def sovereign_anchor_defenses(engine,actor,obj,packets,source):
    data=obj.component or {}
    if not data.get('sovereign') or not data.get('soul_contract'):return None
    from .passive_rows import known_level
    action=engine.action_catalog.get(source)
    typed=(action.parameters or {}).get('typed',{}) if action is not None else {}
    source_cl=typed.get('source_cl',(typed.get('numbers') or {}).get('cl'))
    if source_cl is None and action is not None and action.resolution_kind!='TYPED':source_cl=known_level(engine,actor)
    if source_cl is not None and source_cl<int(data['source_cl']):
        return [{'kind':'resistance','damage_types':[kind for amount,kind in packets]}]
    return None


def legal_route(engine,target,centre,radius=10):
    """Nearest legal destination via full-volume physical steps; no teleportation."""
    from collections import deque
    from ..gate2_runtime_models import Position
    occupied=engine._occupied_volumes_except(target.entity_id)
    footprint=engine._footprint(target)
    start=target.position
    queue=deque([start]);previous={start:None}
    while queue:
        cell=queue.popleft()
        if engine.grid.distance_ft(cell,centre)<=radius:
            path=[]
            while cell is not None:path.append(cell);cell=previous[cell]
            return tuple(reversed(path))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                if not(dx or dy) or cell.x+dx<0 or cell.y+dy<0:continue
                nxt=Position(x=cell.x+dx,y=cell.y+dy,z=cell.z)
                if nxt in previous or not engine.grid.volume_step_legal(cell,nxt,footprint=footprint,occupied_cells=occupied):continue
                previous[nxt]=cell;queue.append(nxt)
    return ()


def call_party(ctx,target,c,pledge,*,radius=10,feet=None):
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve
    centre=Position.model_validate(pledge['destination']) if pledge.get('destination') else ctx.actor.position
    path=legal_route(ctx.engine,target,centre,radius)
    if not path:
        ctx.engine._append_event('SOUL_CONTRACT_ROUTE_BLOCKED',ctx.source,actor_id=ctx.actor.entity_id,
            target_ids=(target.entity_id,),payload={'contract_id':c['id'],'reason':'No legal route to the named destination'})
        return False
    if feet is not None:path=path[:feet//ctx.engine.grid.square_size_ft+1]
    if len(path)>1:
        resolve(ctx.engine,target,path,ctx.source,kind='forced',intent=ctx.intent,
            source_actor_id=ctx.actor.entity_id,ctx=ctx,feet=(len(path)-1)*ctx.engine.grid.square_size_ft)
    return ctx.engine.grid.distance_ft(target.position,centre)<=radius


@hook('turn_start')
def expire_contract_effects(engine,actor):
    from .condition_ownership import remove_instance
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if not c.condition_id.startswith('condition:typed.soul_contract_'):continue
            rounds=int(c.data.get('rounds') or 0)
            expired=rounds and engine.state.round_number-int(c.data['first_round'])>=rounds
            if c.condition_id=='condition:typed.soul_contract_court':
                held=target.concentration is not None and target.concentration.source_definition_id==c.source_definition_id
                expired=expired or not held
            if expired:remove_instance(engine,target,c.instance_id,c.source_definition_id)


@hook('reaction_rows')
def suppressed_reactions(engine,actor_id,block,rows):
    actor=engine.state.actors.get(actor_id)
    if actor is None:return None
    suppressed=[c.data.get('system') for c in actor.conditions.values() if c.condition_id=='condition:typed.soul_contract_suppressed']
    if not suppressed:return None
    return [r for r in rows if not any(str(r.get('feature_id') or '').startswith(s) for s in suppressed if s)]


DECLARATION='system:soul_contract.declare'


@hook('match_start')
def install_party_declarations(engine):
    if not ledgers(engine):return
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[DECLARATION]=ActionDefinition(source_definition_id=DECLARATION,
        display_name='Soul Contract: Declare breach or release',owner_id='*',economy='NONE',
        resolution_kind='TYPED',target_kind='SELF',parameters={'expected_damage':0,'player_only':True,
        'description':'Record your own knowing breach, fulfillment or acceptance of release. No action or Qi cost. This never declares another creature’s consent or state.',
        'typed':{'source':DECLARATION,'numbers':{},'manual_inline_choice':True,'effects':[{'type':'soul_contract_party_declaration'}],'riders':[]}})


@hook('additional_actions')
def party_declaration_actions(engine,actor):
    return [DECLARATION] if DECLARATION in engine.action_catalog and any(actor.entity_id in c['parties']
            and actor.entity_id not in c.get('released_parties',[]) for _,_,c in active_rows(engine)) else []


@effect('soul_contract_party_declaration',harmful=False)
def declare_party_state(ctx,row):
    from .willing_targets import asks_consent
    choices={c['id']:(h,cond,c) for h,cond,c in active_rows(ctx.engine) if ctx.actor.entity_id in c['parties']}
    if not choices:return
    chosen=pick(ctx,'declaration_contract',list(choices),{cid:c['terms'] for cid,(_,_,c) in choices.items()},
                prompt='Choose your own Soul Contract. Only your controller may declare your knowing breach or release.')[0]
    holder,cond,c=choices[chosen]
    op=pick(ctx,'declaration_kind',['breach','release','fulfill'],{'breach':'Declare a knowing breach of the exact trigger',
        'release':'Accept mutual release of this contract','fulfill':'Declare fulfillment of its completion condition'},
        prompt='Record your own contract state, without spending an action or resources.')[0]
    from ..fact_consent_admission import admit_choice
    declaration=admit_choice(ctx,ctx.actor,PARENT,'contract_'+op,c['id'],['confirm'],
        labels={'confirm':'I confirm this declaration for my creature'},
        prompt=('Confirm your own knowing breach: '+c['breach_trigger'] if op=='breach' else
            'Confirm fulfillment: '+c['completion'] if op=='fulfill' else 'Accept mutual release of these exact contract terms?'),
        expires_on='UNTIL_REMOVED',readers=[c['owner']])
    if declaration is None:return
    if op=='breach':
        severity=pick(ctx,'severity',['meaningful']+(['severe'] if c.get('severe_breach_trigger','').strip() else []),{'meaningful':'Meaningful breach: two Major Claims (one Minor Claim)',
            'severe':'Severe breach as explicitly defined by these terms: three Major Claims'},prompt='Choose the breach severity defined by this contract.')[0]
        added=1 if c['grade']=='minor' else c['pb'] if c['grade']=='sovereign' else 3 if severity=='severe' else 2
        if c['grade']=='sovereign':c.setdefault('pending_penalties',[]).append(ctx.actor.entity_id)
        c['claims'][ctx.actor.entity_id]+=min(added,max(0,c['pb']-sum(c['claims'].values())))
        if ctx.actor.entity_id not in c['breached']:c['breached'].append(ctx.actor.entity_id)
        ctx.engine._append_event('SOUL_CONTRACT_BREACHED',ctx.source,actor_id=ctx.actor.entity_id,
            payload={'contract_id':c['id'],'knowing':1,'severity':severity,'claims_added':added})
    else:
        voters=c.setdefault('release_acceptances' if op=='release' else 'fulfillment_declarations',[])
        if ctx.actor.entity_id not in voters:voters.append(ctx.actor.entity_id)
        # A party cannot unilaterally erase an adverse obligation by asserting
        # fulfillment. The creditor confirms the completion condition as well.
        if set(voters)==set(c['parties']):
            for party in list(c['parties']):release_party(ctx.engine,c,party)
            c['ended']=1;c['claims']={p:0 for p in c['parties']}
    write(ctx.engine,holder,cond,c)


@hook('candidate_allowed')
def locked_collateral_action(engine,actor,candidate,action):
    if action is None:return None
    locked={c.data['item_key'] for c in actor.conditions.values() if c.condition_id=='condition:typed.soul_contract_item_locked'}
    if not locked:return None
    from ..carry import carrying_of
    for item in (carrying_of(engine,actor.entity_id) or {}).get('items',[]):
        if item['key'] in locked and (action.source_definition_id==item.get('weapon_action') or
            action.parameters.get('item_key')==item['key']):return False
    return None


@hook('resource_gain_allowed')
def suppressed_resource_gain(engine,actor,rid,amount,source):
    from ..typed_executor import CP_POOLS
    if amount and rid in CP_POOLS and all_cultivation_suppressed(engine,actor):return False
    if amount and any(c.condition_id=='condition:typed.soul_contract_suppressed' and c.data.get('system')==rid for c in actor.conditions.values()):return False
    return None


PROPERTY='condition:typed.soul_contract_property'


@hook('fact_admission_schema')
def property_schema(session,source,subject,kind):
    if source==PARENT and kind=='property' and any(owned(a['bundle'],FEATURES[0]) for a in session.state['actors'].values()):
        return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
            'description':'Native owner declaration of one existing memory, lifespan, office, soul right or bloodline, with its Source Rule.'}
    return None


@hook('journey_command')
def collect_contract_property(session,actor_id,kind,payload):
    if kind!='soul_contract_record_property':return None
    require(set(payload)=={'scope'},'Choose the source-scoped property declaration.')
    declaration=read(session,PARENT,actor_id,'property',payload['scope'],actor_id)
    require(declaration is not None,'Supply the owner’s current property declaration first.')
    value=declaration['value']
    require(set(value)=={'kind','name','quantity','source_rule','source_cl','recognized','exceptional','pledge_permitted','private_value'}
        and value['kind'] in ('memory','lifespan','office','soul','bloodline') and
        all(type(value[k]) is str and value[k].strip() for k in ('name','source_rule')) and
        integer(value['quantity'],1) and integer(value['source_cl'],1) and
        all(type(value[k]) is int and value[k] in (0,1) for k in ('recognized','exceptional','pledge_permitted')) and
        type(value['private_value']) is str,'Record the exact existing property, quantity, Source Rule, authority, recognition and permission.')
    require(value['recognized']==1,'Unrecognized setting offices or property cannot be acquired by declaring a title.')
    actor=session.state['actors'][actor_id]
    props=actor.setdefault('soul_contract_properties',{})
    pid=digest({'owner':actor_id,'kind':value['kind'],'name':value['name'],'source_rule':value['source_rule']})
    require(pid not in props,'That property was already recorded; a new declaration cannot replenish consumed collateral.')
    props[pid]={**deepcopy(value),'id':pid,'owner':actor_id,'holder':actor_id,'declaration':declaration['receipt_id']}
    session.emit('SOUL_PROPERTY_RECORDED',actor_id,property_id=pid,property_kind=value['kind'],source_rule=value['source_rule'])
    sync_bundles(session)
    return True


@hook('match_initialize')
def import_contract_properties(engine):
    for bundle in engine.typed_bundle_documents:
        holder=engine.state.actors.get(bundle['actor_id'])
        if holder is None:continue
        for prop in (bundle.get(STATE) or {}).get('properties',{}).values():
            engine._apply_condition(holder,PROPERTY,PREFIX+FEATURES[0],holder.entity_id,expires_on='UNTIL_REMOVED',
                data={'property':canonical(prop),'property_id':prop['id'],'label':'Recorded pledged property'})


def property_records(engine,holder):
    return [(c,json.loads(c.data['property'])) for c in holder.conditions.values() if c.condition_id==PROPERTY]


def seize_property(ctx,target,c,pledge):
    from .condition_ownership import remove_instance
    records=[(cond,prop) for cond,prop in property_records(ctx.engine,target) if prop['id']==pledge['resource'] and prop['quantity']>0]
    if not records:return False
    cond,prop=records[0]
    require(prop['kind']==pledge['kind'],'The property’s native kind does not match the pledge.')
    amount=min(prop['quantity'],pledge['amount'] or 1)
    operation=pledge['procedure']
    require(operation in ('transfer','copy','seal','escrow','consume'),'The Contract must define its exact property transfer procedure.')
    if prop['kind']=='memory':require(operation in ('copy','seal'),'A memory is sealed or copied only as this Contract states.')
    if operation!='copy':prop['quantity']-=amount
    remove_instance(ctx.engine,target,cond.instance_id,ctx.source)
    ctx.engine._apply_condition(target,PROPERTY,ctx.source,target.entity_id,expires_on='UNTIL_REMOVED',
        data={'property':canonical(prop),'property_id':prop['id'],'label':'Pledged property after lawful foreclosure'})
    collected={**prop,'quantity':amount,'holder':ctx.actor.entity_id,'foreclosure_contract':c['id']}
    if operation in ('seal','escrow'):
        anchors=[ctx.engine.state.objects[oid] for oid in c.get('anchor_ids',{}).values() if oid in ctx.engine.state.objects and not ctx.engine.state.objects[oid].destroyed]
        if not anchors:return False
        anchor=anchors[0]
        component=deepcopy(anchor.component);component.setdefault('soul_escrow',[]).append(canonical(collected))
        ctx.engine._update_object(anchor.model_copy(update={'component':component}),ctx.source,ctx.actor.entity_id)
    elif operation!='consume':
        ctx.engine._apply_condition(ctx.actor,PROPERTY,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'property':canonical(collected),'property_id':prop['id'],'label':'Lawfully collected contract property'})
    if prop['kind'] in ('lifespan','soul','bloodline'):
        condition(ctx,target,'long_term_harm',{},'UNTIL_REMOVED','Lawful foreclosure: '+pledge['name']+'; reconstruction requires its own recovery procedure',
            source_cl=c['source_cl'],contract_id=c['id'],property_id=prop['id'],quantity=amount,
            tier=4 if prop['kind']=='soul' else 3)
    ctx.engine._append_event('SOUL_PROPERTY_FORECLOSED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(target.entity_id,),
        payload={'contract_id':c['id'],'property_id':prop['id'],'quantity':amount,'operation':operation,'source_cl':c['source_cl']})
    return True


@hook('presentation_hidden_conditions')
def hide_contract_private_records(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in (LEDGER,PROPERTY,SECRET_CONDITION_ID)]


@hook('journey_options')
def ritual_options(session,actor_id):
    actor=session.state['actors'][actor_id]
    if actor['incapacitated']:return []
    out=[]
    if owned(actor['bundle'],FEATURES[0]):
        seen=set()
        for record in reversed(session.state.get('fact_consent_admission',[])):
            if record['source']!=PARENT or record['subject']!=actor_id or record['kind']!='offer' or record['scope'] in seen:continue
            seen.add(record['scope'])
            current=read(session,PARENT,actor_id,'offer',record['scope'],actor_id)
            if current is None:continue
            try:offer=validate_offer(session,actor_id,current['value'])
            except (ValueError,TypeError,KeyError):continue
            grade=offer['grade'];cost={'minor':2,'major':6,'sovereign':10}[grade]
            if actor['resources'].get(QI,0)<cost:continue
            out.append({'id':'soul_contract_create:'+record['scope'],'kind':'soul_contract_create','payload':{'offer_scope':record['scope']},
                'label':f"{actor['name']}: create the proposed {grade.title()} Soul Contract; {cost} Qi, "
                    +{'minor':'one-minute ritual, up to eight hours','major':'ten-minute ritual, up to thirty days','sovereign':'one-hour ritual, until lawfully ended'}[grade]})
    for cid,c in session.state.get(STATE,{}).items():
        if not live(session,c) or actor_id not in c['parties']:continue
        receipt=read(session,PARENT,actor_id,'breach',cid,c['owner'])
        if receipt is not None and receipt['receipt_id'] not in c['breach_receipts']:
            out.append({'id':'soul_contract_breach:'+cid,'kind':'soul_contract_breach','payload':{'contract_id':cid},
                'label':actor['name']+': record your declared knowing breach of this Soul Contract; no action or Qi cost'})
        if all((r:=read(session,PARENT,p,'release',cid,actor_id)) and r['value']==1 for p in c['parties']):
            out.append({'id':'soul_contract_release:'+cid,'kind':'soul_contract_release','payload':{'contract_id':cid},
                'label':actor['name']+': complete the accepted mutual release; unspent Claims end and collected collateral stays collected'})
    return out


@hook('journey_properties')
def contract_directions(session,actor_id):
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][actor_id];directions=[]
    for c in session.state.get(STATE,{}).values():
        if c['owner']!=actor_id or not live(session,c):continue
        origin=Position.model_validate(actor['position'])
        for party in c['breached']:
            if party in c.get('released_parties',[]):continue
            target=Position.model_validate(session.state['actors'][party]['position'])
            if session.grid.distance_ft(origin,target)>5280:continue
            dx,dy=target.x-origin.x,target.y-origin.y
            bearing=('north' if dy<0 else 'south' if dy>0 else '')+('east' if dx>0 else 'west' if dx<0 else '') or 'here'
            directions.append({'creature':session.state['actors'][party]['name'],'direction':bearing,
                               'contract_id':c['id'],'exact_location_granted':0})
    return {'soul_contract_directions':directions} if directions else None


@hook('journey_initialize')
def restore_contract_journey(session,actor_id):
    actor=session.state['actors'][actor_id]
    saved=(actor.get('source_states') or {}).get(PARENT)
    if saved is None:return
    now=int(session.clock());old_clock=saved['clock']
    session.state.setdefault('scene_id',saved.get('scene_id',session.state['journey_id']))
    locks=session.state.setdefault('soul_contract_binding_lockouts',[])
    locks.extend(p for p in saved.get('binding_lockouts',[]) if p not in locks)
    actor['soul_contract_acquired_sheet']=saved.get('acquired_sheet','')
    actor['soul_contract_training']=deepcopy(saved.get('training',{}))
    if actor['soul_contract_acquired_sheet'] and not owned(actor['bundle'],FEATURES[0]):
        from ..factory_compiler import compile_character
        actor['bundle']=compile_character(json.loads(actor['soul_contract_acquired_sheet']),actor_id=actor_id)
    actor['soul_contract_secrets']=deepcopy(saved.get('secrets',{}))
    actor['soul_contract_channels']=deepcopy(saved.get('channels',{}))
    actor['soul_contract_recovery']=deepcopy(saved.get('recovery',{}))
    actor['soul_contract_properties']=deepcopy(saved.get('properties',{}))
    actor['soul_contract_effects']=deepcopy(saved.get('source_effects',[]))
    for effect in actor['soul_contract_effects']:
        if effect['expires_at']:effect['expires_at']=now+max(0,effect['expires_at']-old_clock)
    for cid,old in saved.get('contracts',{}).items():
        c=deepcopy(old)
        if c['expires_at']:
            remaining=c['expires_at']-old_clock
            if remaining<=0:c['ended']=1;c['claims']={p:0 for p in c['parties']}
            c['expires_at']=now+max(0,remaining)
        existing=session.state.setdefault(STATE,{}).get(cid)
        if existing is None or c['owner']==actor_id:session.state[STATE][cid]=c
    prior=session.state.setdefault('fact_consent_admission',[])
    receipts={r['receipt_id'] for r in prior}
    # Historical declarations retain their original clock and commitment for
    # audit only. They cannot become fresh signatures in the new journey.
    for r in saved.get('admissions',[]):
        if r['receipt_id'] not in receipts:
            audit=deepcopy(r);session.state.setdefault('prior_fact_admissions',[]).append(audit)


@hook('journey_initialized')
def finish_contract_continuation(session):
    if session.state.get(STATE) or any(PARENT in a.get('source_states',{}) for a in session.state['actors'].values()):sync_bundles(session)


@hook('journey_encounter_settled')
def settle_contract_journey(session,actor_id,engine,creature):
    actor=session.state['actors'][actor_id]
    for holder,condition,c in ledgers(engine):
        if holder.entity_id!=actor_id:continue
        doc=json.loads(condition.data['contract'])
        doc['anchor_state']={party:canonical(engine.state.objects[oid].model_dump(mode='json')) for party,oid in doc.get('anchor_ids',{}).items() if oid in engine.state.objects}
        elapsed=max(0,engine.state.round_number-int(condition.data['start_round']))*6
        remaining=max(0,int(condition.data['remaining_seconds'])-elapsed)
        if doc['expires_at']:
            doc['expires_at']=int(session.clock())+remaining
            if remaining==0:doc['ended']=1;doc['claims']={p:0 for p in doc['parties']}
        session.state.setdefault(STATE,{})[doc['id']]=doc
    actor['soul_contract_properties']={p['id']:p for cond,p in property_records(engine,creature)}
    actor['soul_contract_secrets']={c.data['secret_scope']:json.loads(c.data['secret']) for c in creature.conditions.values() if c.condition_id==SECRET_CONDITION_ID}
    actor['soul_contract_channels']={c.data['channel_scope']:json.loads(c.data['channel']) for c in creature.conditions.values() if c.condition_id==CHANNEL}
    effects=[]
    for condition in creature.conditions.values():
        if not condition.condition_id.startswith('condition:typed.soul_contract_') or condition.condition_id in (LEDGER,PROPERTY,'condition:typed.soul_contract_party','condition:typed.soul_contract_anchor_item','condition:typed.soul_contract_court',SECRET_CONDITION_ID,CHANNEL):continue
        remaining=0
        if condition.data.get('rounds'):
            remaining=max(0,(int(condition.data['rounds'])-engine.state.round_number+int(condition.data['first_round']))*6)
            if remaining==0:continue
        elif condition.expires_on not in (None,'UNTIL_REMOVED'):
            remaining=6
        effects.append({'condition':condition.condition_id,'source':condition.source_definition_id,
            'source_actor':condition.source_actor_id,'data':canonical(condition.data),
            'expires_at':int(session.clock())+remaining if remaining else 0})
    actor['soul_contract_effects']=effects
    sync_bundles(session)


@hook('state_event')
def move_attached_anchors(engine,event):
    if event.event_type not in ('MOVEMENT_COMMITTED','TELEPORT_COMMITTED'):return
    party=event.actor_id
    target=engine.state.actors.get(party)
    if target is None:return
    for holder,condition,c in active_rows(engine):
        if c['grade']!='major':continue
        oid=c.get('anchor_ids',{}).get(party);obj=engine.state.objects.get(oid)
        if obj is not None and not obj.destroyed and obj.position!=target.position:
            engine._update_object(obj.model_copy(update={'position':target.position}),PREFIX+FEATURES[2],holder.entity_id)


@hook('journey_snapshot_actor')
def contract_snapshot_actor(creature,session,actor_id,engine):
    owned=[iid for iid,c in creature.conditions.items() if c.condition_id.startswith('condition:typed.soul_contract_')]
    if not owned:return None
    result=creature.model_copy(deep=True)
    for iid in owned:result.conditions.pop(iid,None)
    return result


@hook('match_initialize')
def import_contract_effects(engine):
    for bundle in engine.typed_bundle_documents:
        data=bundle.get(STATE)
        holder=engine.state.actors.get(bundle['actor_id'])
        if not data or holder is None:continue
        for record in data.get('source_effects',[]):
            details=json.loads(record['data'])
            cid=details.get('contract_id')
            if cid and (data['contracts'].get(cid) or {}).get('ended') and record['condition']!='condition:typed.soul_contract_long_term_harm':continue
            remain=record['expires_at']-data['clock'] if record['expires_at'] else 0
            if record['expires_at'] and remain<=0:continue
            if remain:details.update(first_round=engine.state.round_number,rounds=(remain+5)//6)
            if record['condition']=='condition:typed.soul_contract_points_suppressed':
                rid=details['system']
                engine._set_resource_maximum(holder,rid,max(0,holder.resource_maximums[rid]-int(details['maximum_reduction'])),record['source'])
            engine._apply_condition(holder,record['condition'],record['source'],record['source_actor'],
                expires_on='UNTIL_REMOVED',data=details)


@hook('journey_elapsed')
def expire_contract_travel_effects(session,actor_id,before,elapsed,moving):
    actor=session.state['actors'][actor_id]
    if not actor.get('soul_contract_effects'):return
    retained=[]
    for e in actor['soul_contract_effects']:
        if e['expires_at'] and e['expires_at']<=session.clock():
            if e['condition']=='condition:typed.soul_contract_points_suppressed':
                data=json.loads(e['data']);rid=data['system']
                maximum=next(r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id']==rid)
                actor['resources'][rid]=min(maximum,actor['resources'][rid]+int(data['current_withheld']))
        else:retained.append(e)
    actor['soul_contract_effects']=retained
    sync_bundles(session)


def move_pledged_item(ctx,target,pledge,*,require_superior=False):
    from .scoundrel_riders import possessions,relocate_possession
    from ..object_placement import destinations
    item=next((i for i in possessions(ctx.engine,target) if i['key']==pledge['resource']),None)
    if item is None:return False
    bundle=next((b for b in ctx.engine.typed_bundle_documents if b['actor_id']==target.entity_id),{})
    profiles=bundle.get('acquisition_inventory',{})
    profile=next((i['profile'] for i in profiles.values() if i.get('inventory_key')==item['key']),None)
    # Mundane catalogue equipment has no cultivated controlling authority.
    # A treasure requires its actually acquired Source Rule profile.
    if item.get('treasure') and profile is None:return False
    if profile is not None and int(profile.get('facts',{}).get('artifact',0)):return False
    authority=int(profile['source_cl']) if profile is not None else 0
    if require_superior and int(ctx.numbers['cl'])<=authority:return False
    beneficiaries=list(ctx.engine.state.actors)
    aid=pick(ctx,'item_beneficiary',beneficiaries,{a:ctx.engine.state.actors[a].display_name for a in beneficiaries},
        prompt='Choose yourself or a named beneficiary. The exact real pledged item travels by a legal route to a space within 5 feet; it is never duplicated.')[0]
    beneficiary=ctx.engine.state.actors[aid]
    routes={}
    for destination in destinations(ctx.engine,beneficiary,5):
        path=legal_route(ctx.engine,target,destination,radius=0)
        if path:routes[f'{destination.x},{destination.y},{destination.z}']=path
    if not routes:
        ctx.engine._append_event('SOUL_CONTRACT_ROUTE_BLOCKED',ctx.source,actor_id=ctx.actor.entity_id,
            target_ids=(target.entity_id,),payload={'reason':'No legal route for the pledged item'})
        return False
    selected=pick(ctx,'item_destination',list(routes),{key:f'Place {item["name"]} at {path[-1].x}, {path[-1].y}' for key,path in routes.items()},
        prompt='Choose a legal destination within 5 feet of the named beneficiary. The item travels along a physical route.')[0]
    return relocate_possession(ctx,target,item,routes[selected])


@hook('movement_attempt')
def locked_item_willing_movement(engine,mover,previous,nxt,intent):
    from .scoundrel_riders import possessions,object_id
    held={i['object'] for i in possessions(engine,mover)}
    for holder in engine.state.actors.values():
        for c in holder.conditions.values():
            if c.condition_id=='condition:typed.soul_contract_item_locked' and object_id(c.data['item_owner'],c.data['item_key']) in held:
                return {'stop':True,'source_id':c.source_definition_id,
                    'label':'The foreclosed item cannot be willingly moved before the creditor’s next turn. Its freeze ends at the creditor’s next turn.'}
    return None


@hook('possession_operation_allowed')
def foreclosed_item_operation(engine,actor,holder,item,operation,source):
    from .scoundrel_riders import object_id
    identity=item.get('object') or object_id(holder.entity_id,item['key'])
    for creature in engine.state.actors.values():
        for c in creature.conditions.values():
            if c.condition_id!='condition:typed.soul_contract_item_locked':continue
            if object_id(c.data['item_owner'],c.data['item_key'])!=identity:continue
            if operation=='move' and source==c.source_definition_id:return None
            return False
    return None


def perform_pledged_service(ctx,target,c,pledge):
    """Execute the exact ordinary act through its native mechanical adapter."""
    procedure=pledge['procedure']
    if procedure=='drop_item':
        from .scoundrel_riders import held_possessions,drop_held_object
        item=next((i for i in held_possessions(ctx.engine,target) if i['key']==pledge['resource']),None)
        return item is not None and drop_held_object(ctx.engine,target,item,source=ctx.source,by=ctx.actor)
    if procedure=='ordinary_movement':
        from ..granted_movement import routes,resolve_path
        options=routes(ctx.engine,target,ctx.engine._effective_speed(target))
        if pledge.get('destination'):
            from ..gate2_runtime_models import Position
            want=Position.model_validate(pledge['destination']);options={p:route for p,route in options.items() if p==want}
        if not options:return False
        names={f'{p.x},{p.y},{p.z}':(p,route) for p,route in options.items()}
        chosen=pick(ctx,'service_movement',list(names),{key:f'Move {target.display_name} to {p.x}, {p.y}' for key,(p,route) in names.items()},
            prompt='Perform the exact pledged ordinary movement using the breacher’s Reaction. Ordinary movement and Opportunity Attacks still apply.')[0]
        p,route=names[chosen]
        path,cost,mode=route
        resolve_path(ctx.engine,target,path,ctx.source,feet=ctx.engine._effective_speed(target),intent=ctx.intent,mode=mode)
        return target.position==p
    if procedure=='open_door':
        from .door_state import change_door
        from ..object_rules import simple_door_state
        obj=ctx.engine.state.objects.get(pledge['resource'])
        state=simple_door_state(obj.component or {}) if obj is not None else None
        if state is None or state['door_locked'] or state['door_jammed'] or ctx.engine.grid.distance_ft(target.position,obj.position)>5:return False
        change_door(ctx.engine,target,obj,True,ctx.source)
        return True
    if procedure=='deliver_object':
        from .scoundrel_riders import possessions,transfer_object
        receiver=ctx.engine.state.actors.get(pledge.get('recipient'))
        item=next((i for i in possessions(ctx.engine,target) if i['key']==pledge['resource']),None)
        if receiver is None or item is None or ctx.engine._distance_actor_to_actor(receiver,target)>5:return False
        transfer_object(replace(ctx,actor=receiver,target=target,targets=[target]),
            {'item':item['key'],'object':item['object'],'as':'take','ability':'Service Foreclosure: deliver the pledged object'})
        return any(i['object']==item['object'] for i in possessions(ctx.engine,receiver))
    if procedure=='perform_service':
        # Explicit nonphysical ordinary acts (a named spoken statement, payment
        # acknowledgement, appearance, etc.) are native campaign acts. This
        # receipt does not claim any object, anatomy or resource changed.
        receipt={'actor':target.entity_id,'contract':c['id'],'action':pledge['name'],
                 'source_cl':c['source_cl'],'sequence':ctx.engine.state.event_sequence+1}
        condition(ctx,target,'service_performed',{},'UNTIL_REMOVED',
            target.display_name+' performed the pledged ordinary act: '+pledge['name'],receipt=canonical(receipt))
        ctx.engine._append_event('CONTRACT_SERVICE_PERFORMED',ctx.source,actor_id=target.entity_id,
            payload={'receipt':canonical(receipt)})
        return True
    return False


@hook('observer_information_rows')
def contract_information(engine,viewer):
    from ..observer_information import direction
    rows=[]
    for holder,condition,c in active_rows(engine):
        if viewer.entity_id==c['owner']:
            for party in c['breached']:
                target=engine.state.actors.get(party)
                if target is not None and party not in c.get('released_parties',[]) and engine._distance_actor_to_actor(viewer,target)<=5280:
                    rows.append({'kind':'direction','viewer_id':viewer.entity_id,'authority_actor_id':c['owner'],
                        'source_id':condition.source_definition_id,'details':{'direction':direction(viewer.position,target.position)}})
        if in_court(engine,viewer,c):
            parts=', '.join(engine.state.actors[p].display_name for p in c['parties'] if p in engine.state.actors)
            collateral=', '.join(p['name'] for pledges in c['collateral'].values() for p in pledges)
            assignees=', '.join(engine.state.actors[p].display_name for p in c['authorized_assignees'] if p in engine.state.actors) or 'none'
            text='Contract Court: parties '+parts+'; terms '+c['terms']+'; '+str(sum(c['claims'].values()))+' Claims; pledged collateral '+collateral+'; '+('breached' if c['breached'] else 'not breached')+'; authorized assignees '+assignees+'.'
            rows.append({'kind':'declaration','viewer_id':viewer.entity_id,'authority_actor_id':c['owner'],
                'source_id':condition.source_definition_id,'details':{'text':text}})
    return rows


@hook('state_event')
def court_anchor_ended(engine,event):
    if event.event_type!='OBJECT_UPDATED':return
    from .placed import of,data,drop
    for court in list(of(engine,'soul_contract_court')):
        anchor=engine.state.objects.get(data(court).get('anchor'))
        if anchor is None or anchor.destroyed:drop(engine,court,'ANCHOR_DESTROYED')


@hook('journey_scene_end')
def contract_scene_end(session,previous,current):
    if not session.state.get(STATE) and not session.state.get('soul_contract_binding_lockouts'):return
    session.state['soul_contract_binding_lockouts']=[]
    for c in session.state.get(STATE,{}).values():
        c['court_used']=0
    sync_bundles(session)


def suppress_collateral(ctx,target,c,pledge,until='UNTIL_REMOVED',*,rounds=0):
    """Withhold only the pledged structure. Current/max point pledges are finite.

    Existing native effects retain their identity and original expiry while
    dormant. The matching ending checkpoint restores only surviving instances.
    Suppression never creates, destroys or transfers cultivation property.
    """
    point_pledge=pledge['kind']=='cultivation_points'
    kind='points_suppressed' if point_pledge else 'suppressed'
    cid='condition:typed.soul_contract_'+kind
    if any(x.condition_id==cid and x.data.get('contract_id')==c['id'] and
           x.data.get('system')==pledge['resource'] for x in target.conditions.values()):
        return
    data={'system':pledge['resource'],'contract_id':c['id'],'rounds':rounds,
          'first_round':ctx.engine.state.round_number,'pledge_kind':pledge['kind']}
    if point_pledge:
        rid=pledge['resource']
        reduction=min(target.resource_maximums[rid],pledge['amount'])
        withheld=min(target.resources[rid],reduction)
        resource(ctx.engine,target,rid,-withheld,ctx.source)
        ctx.engine._set_resource_maximum(target,rid,target.resource_maximums[rid]-reduction,ctx.source)
        data.update(maximum_reduction=reduction,current_withheld=withheld)
    else:
        from .end_effect import suppress,SUPPRESSED_FLAG
        held=[]
        bundle=next((b for b in ctx.engine.typed_bundle_documents if b['actor_id']==target.entity_id),{})
        sources=set(cultivation_systems(bundle).get(pledge['resource'],[]))
        for collection,rows in (('condition',target.conditions),('modifier',target.modifiers)):
            for key,item in list(rows.items()):
                if (item.source_definition_id in sources or item.source_definition_id.startswith(pledge['resource'])) and (collection!='condition' or not item.condition_id.startswith('condition:typed.soul_contract_')):
                    suppress(target,collection,key,item,engine=ctx.engine,boundary='scene')
                    held.append(key)
        data['dormant_instances']=canonical(held)
    condition(ctx,target,kind,{},until,'Foreclosed cultivation: '+pledge['name'],**data)
    if all_cultivation_suppressed(ctx.engine,target):
        from .. import concentration
        concentration.end_all_copies(ctx.engine,target,'COMPLETE_CULTIVATION_SUPPRESSION')


@hook('event')
def restore_foreclosed_collateral(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED':return
    ended=kwargs.get('ended_effect') or {}
    if ended.get('condition_id') not in ('condition:typed.soul_contract_suppressed','condition:typed.soul_contract_points_suppressed'):return
    data=ended['data'];target=engine.state.actors[next(iter(kwargs['target_ids']))]
    source=ended['source_definition_id']
    if ended['condition_id'].endswith('points_suppressed'):
        rid=data['system']
        engine._set_resource_maximum(target,rid,target.resource_maximums[rid]+int(data['maximum_reduction']),source)
        resource(engine,target,rid,int(data['current_withheld']),source)
    else:
        from .end_effect import restore_suppressed,SUPPRESSED_FLAG
        keys=set(json.loads(data.get('dormant_instances','[]')))
        for row in list(target.turn_flags.get(SUPPRESSED_FLAG,[])):
            if row['key'] in keys:restore_suppressed(engine,target,row)


def sovereign_penalty(ctx,target,c,pledge):
    """Activate exactly one printed penalty against actually pledged property."""
    options=['call']
    if pledge['kind']=='system':options+=['suppress']
    if pledge.get('territory'):options+=['territory']
    if pledge['kind'] in ('item','office','resource'):options+=['transfer']
    if pledge['kind'] in ('system','soul','lifespan','bloodline'):options+=['harm3','harm4']
    if pledge['kind']=='soul':options+=['escrow']
    labels={'call':'Call the breacher before this Sovereign Anchor by a legal route',
        'suppress':'Suppress the exact pledged cultivation system until this Contract ends or equal authority restores it',
        'territory':'Seal movement within the exact named territory pledged in this Contract',
        'transfer':'Transfer the exact pledged item, resource, office or authority by its recorded procedure',
        'harm3':'Inflict Tier III cultivation harm matching this pledged structure',
        'harm4':'Inflict Tier IV cultivation harm matching this pledged structure',
        'escrow':'Place the exact pledged soul fragment or reincarnation right in the Sovereign Anchor’s escrow'}
    selected=pick(ctx,'sovereign_penalty',options,labels,prompt='Sovereign breach: choose one printed penalty for '+target.display_name+' using only the selected pledged collateral. No additional action, Qi or Claim cost.')[0]
    if selected=='suppress':suppress_collateral(ctx,target,c,pledge)
    elif selected=='territory':
        condition(ctx,target,'territory',{},'UNTIL_REMOVED','Sovereign penalty: cannot willingly leave the named territory '+pledge['name'],
            contract_id=c['id'],territory=canonical(pledge['territory']))
    elif selected=='transfer':collect_payment(ctx,target,c,pledge)
    elif selected in ('harm3','harm4'):
        condition(ctx,target,'long_term_harm',{},'UNTIL_REMOVED','Sovereign cultivation harm to '+pledge['name']+'; Tier '+selected[-1]+'; reconstruction required',
            source_cl=c['source_cl'],contract_id=c['id'],property_id=pledge['resource'],quantity=pledge['amount'],tier=int(selected[-1]))
        if pledge['kind']=='system':suppress_collateral(ctx,target,c,pledge)
    elif selected=='escrow':
        require(pledge['procedure']=='escrow','The exact pledged soul collateral must name escrow as its procedure.')
        require(seize_property(ctx,target,c,pledge),'The pledged soul collateral is not available.')
    else:
        anchors=[ctx.engine.state.objects[oid] for oid in c.get('anchor_ids',{}).values() if oid in ctx.engine.state.objects and not ctx.engine.state.objects[oid].destroyed]
        require(bool(anchors),'This Sovereign Contract has no surviving Anchor.')
        call_party(ctx,target,c,{**pledge,'destination':anchors[0].position.model_dump(mode='json')})
    ctx.engine._append_event('SOVEREIGN_PENALTY_ENFORCED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(target.entity_id,),
        payload={'contract_id':c['id'],'penalty':selected,'collateral':pledge['resource']})


def collect_payment(ctx,target,c,pledge):
    if pledge['kind'] in ('qi','resource','cultivation_points'):
        removed=-resource(ctx.engine,target,pledge['resource'],-pledge['amount'],ctx.source)
        resource(ctx.engine,ctx.actor,pledge['resource'],removed,ctx.source)
        return True
    if pledge['kind'] in ('memory','lifespan','office','soul','bloodline'):
        return seize_property(ctx,target,c,pledge)
    if pledge['kind'] in ('item','asset'):return move_pledged_item(ctx,target,pledge)
    if pledge['kind']=='service':return perform_pledged_service(ctx,target,c,pledge)
    require(False,'This pledged price has no matching native transfer procedure.')


@hook('movement_attempt')
def contracted_territory(engine,mover,previous,nxt,intent):
    for condition in mover.conditions.values():
        if condition.condition_id!='condition:typed.soul_contract_territory':continue
        from ..gate2_runtime_models import Position
        allowed={Position.model_validate(p) for p in json.loads(condition.data['territory'])}
        if previous in allowed and nxt not in allowed:
            return {'stop':True,'source_id':condition.source_definition_id,'label':condition.data['label']}
    return None


def cultivation_systems(bundle):
    """Derive active named systems from owned, compiled Source Rule records.

    The typed authority supplies ownership categories; display names, damage
    types, an idle actor and free-form declarations are never ownership proof.
    """
    from ..factory_compiler import TYPED_AUTHORITY
    records=cultivation_authority(str(TYPED_AUTHORITY),TYPED_AUTHORITY.stat().st_mtime_ns)
    sources={a.get('parameters',{}).get('typed',{}).get('source','') for a in bundle.get('action_catalog',[])}
    sources.update(p.get('feature_id','') for p in bundle.get('typed_passives',[]))
    from ..typed_executor import CP_POOLS
    out={}
    for action in bundle.get('action_catalog',[]):
        typed=action.get('parameters',{}).get('typed',{})
        source=typed.get('source')
        if source and source not in records and any(rid in CP_POOLS for rid,amount in action.get('costs',[])):
            out[source]=[source]
    for sid in sources:
        rule=records.get(sid)
        if rule is None:continue
        for field in ('path_id','subpath_id','method_id','foundation_id','sphere_id'):
            owner=rule.get(field)
            if owner:out.setdefault(owner,[]).append(sid)
        if '.feature.' in sid:out.setdefault(sid.split('.feature.')[0],[]).append(sid)
    return {k:sorted(set(v)) for k,v in out.items()}


def suppressed_system_ids(actor):
    return {c.data['system'] for c in actor.conditions.values() if c.condition_id=='condition:typed.soul_contract_suppressed'}


def all_cultivation_suppressed(engine,actor):
    if not suppressed_system_ids(actor):return False
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    systems=cultivation_systems(bundle)
    # A Path pledge covers its compiled features, including its resource-paid
    # expressions. Compare actual source sets, not number of descriptive names.
    active=set(s for group in systems.values() for s in group)
    pledged=set(s for key in suppressed_system_ids(actor) for s in systems.get(key,[]))
    return bool(active) and active<=pledged


@hook('journey_step')
def contracted_travel_boundary(session,actor_id,previous,nxt,regions):
    actor=session.state['actors'][actor_id]
    for record in actor.get('soul_contract_effects',[]):
        if record['condition']!='condition:typed.soul_contract_territory':continue
        from ..gate2_runtime_models import Position
        data=json.loads(record['data']);allowed={Position.model_validate(p) for p in json.loads(data['territory'])}
        require(not(previous in allowed and nxt not in allowed),'The active Sovereign Contract prevents voluntary departure from '+data['label'])
    return None


from functools import lru_cache

@lru_cache(maxsize=2)
def cultivation_authority(path,mtime):
    from pathlib import Path
    return json.loads(Path(path).read_text())['mechanics']


def contract_participant(session,actor_id):
    return bool(session.state['actors'][actor_id].get('soul_contract_training')) or owned(session.state['actors'][actor_id]['bundle'],FEATURES[0]) or any(actor_id in c['parties'] and live(session,c) for c in session.state.get(STATE,{}).values())


def journey_qi_maximum(actor):
    base=next((r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id']==QI),0)
    withheld=sum(int(json.loads(e['data'])['maximum_reduction']) for e in actor.get('soul_contract_effects',[])
        if e['condition']=='condition:typed.soul_contract_points_suppressed' and json.loads(e['data'])['system']==QI)
    return max(0,base-withheld)


def journey_qi_gain(session,actor_id,amount):
    actor=session.state['actors'][actor_id]
    if any(e['condition'] in ('condition:typed.soul_contract_no_recovery','condition:typed.soul_contract_suppressed')
           and json.loads(e['data']).get('system')==QI for e in actor.get('soul_contract_effects',[])):return 0
    before=actor['resources'].get(QI,0)
    actor['resources'][QI]=min(journey_qi_maximum(actor),before+amount)
    delta=actor['resources'][QI]-before
    session.emit('SOUL_CONTRACT_QI_RECOVERED',actor_id,source=PARENT,amount=delta)
    sync_bundles(session)
    return delta


@hook('journey_rest')
def contract_long_rest(session,actor_id):
    if not contract_participant(session,actor_id):return
    actor=session.state['actors'][actor_id]
    journey_qi_gain(session,actor_id,journey_qi_maximum(actor)//2)
    actor.setdefault('soul_contract_recovery',{}).update(short_used=0,session_used=0)
    sync_bundles(session)


@hook('journey_command')
def contract_qi_recovery(session,actor_id,kind,payload):
    if kind not in ('soul_contract_short_rest','soul_contract_cultivation_session'):return None
    require(contract_participant(session,actor_id),'This source has no Qi recovery procedure for that creature.')
    actor=session.state['actors'][actor_id]
    require(not actor['incapacitated'],'An incapacitated creature cannot perform this recovery procedure.')
    uses=actor.setdefault('soul_contract_recovery',{})
    key='short_used' if kind=='soul_contract_short_rest' else 'session_used'
    require(not uses.get(key),'This recovery was already used before your next Long Rest.')
    if kind=='soul_contract_short_rest':
        require(not payload,'A Short Rest lasts one hour.')
        session.tick(3600);gain=int(actor['bundle']['cl'])
    else:
        require(set(payload)=={'environment_scope'},'Choose your own current calm ambient-Qi environment declaration.')
        declaration=read(session,PARENT,actor_id,'cultivation_environment',payload['environment_scope'],actor_id)
        require(declaration is not None and declaration['value']==1,'Confirm the actual calm environment and available ambient Qi.')
        session.tick(7200)
        require(read(session,PARENT,actor_id,'cultivation_environment',payload['environment_scope'],actor_id) is not None,'The environment declaration expired during cultivation.')
        gain=journey_qi_maximum(actor)
    uses[key]=1
    journey_qi_gain(session,actor_id,gain)
    session.emit('SOUL_CONTRACT_QI_REST',actor_id,procedure=kind,seconds=3600 if key=='short_used' else 7200)
    sync_bundles(session)
    return True


@hook('fact_admission_schema')
def cultivation_environment_schema(session,source,subject,kind):
    if source==PARENT and kind=='cultivation_environment' and contract_participant(session,subject):
        return {'value_type':'flag','maximum_seconds':28800,'description':'Owner confirmation that the actual current environment is calm and supplies ambient Qi for a cultivation session.'}
    return None


@hook('journey_options')
def contract_recovery_options(session,actor_id):
    if not contract_participant(session,actor_id):return []
    actor=session.state['actors'][actor_id]
    if actor['incapacitated']:return []
    uses=actor.get('soul_contract_recovery',{});out=[]
    if not uses.get('short_used'):
        out.append({'id':'soul_contract_short_rest','kind':'soul_contract_short_rest','payload':{},
            'label':actor['name']+': Short Rest for one hour; recover Qi equal to Cultivation Level, once per Long Rest'})
    for record in reversed(session.state.get('fact_consent_admission',[])):
        if record['subject']==actor_id and record['source']==PARENT and record['kind']=='cultivation_environment' and not uses.get('session_used'):
            latest=read(session,PARENT,actor_id,record['kind'],record['scope'],actor_id)
            if latest and latest['value']==1:
                out.append({'id':'soul_contract_cultivation_session:'+record['scope'],'kind':'soul_contract_cultivation_session',
                    'payload':{'environment_scope':record['scope']},'label':actor['name']+': Cultivate for two calm hours with ambient Qi; recover all Qi, once per Long Rest'})
                break
    return out


RIGHT_ACTION='action:soul_contract.assigned.'


@hook('match_start')
def install_assigned_right_actions(engine):
    """A transferred right grants its native foreclosure, never a progression."""
    from ..gate2_runtime_models import ActionDefinition
    for holder,cond,c in active_rows(engine):
        if c['grade']!='minor':continue
        originals=[a for a in list(engine.action_catalog.values()) if a.owner_id==c['owner'] and
                   a.parameters.get('soul_contract_operation','').startswith('minor_')]
        for aid in c['authorized_assignees']:
            if aid not in engine.state.actors:continue
            for action in originals:
                key=RIGHT_ACTION+c['id']+'.'+aid+'.'+action.parameters['soul_contract_operation']
                params=deepcopy(action.parameters)
                params['soul_contract_assigned_contract']=c['id']
                params['description']='Use the one transferred foreclosure right: '+params['description']
                engine.action_catalog[key]=action.model_copy(update={'source_definition_id':key,'owner_id':aid,'parameters':params})


@hook('additional_actions')
def assigned_right_actions(engine,actor):
    rights={c['id'] for holder,cond,c in active_rows(engine) if any(a['assignee']==actor.entity_id and a['claims'] for a in c.get('assignments',[]))}
    return [key for key,a in engine.action_catalog.items() if key.startswith(RIGHT_ACTION) and a.owner_id==actor.entity_id and
            a.parameters['soul_contract_assigned_contract'] in rights]


ANCHOR_CHALLENGE='action:soul_contract.anchor_challenge'


@hook('match_start')
def install_anchor_challenge(engine):
    if not any(c.get('anchor_ids') for holder,condition,c in active_rows(engine)):return
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[ANCHOR_CHALLENGE]=ActionDefinition(source_definition_id=ANCHOR_CHALLENGE,
        display_name='Challenge an adjacent Soul Contract Anchor',owner_id='*',economy='ACTION',resolution_kind='TYPED',target_kind='SELF',
        parameters={'expected_damage':0,'soul_contract_operation':'anchor','description':'Action: a party or adjacent ally makes a compatible Cultivation Check to release that party from this Anchor. Already collected collateral stays collected.',
            'typed':{'source':ANCHOR_CHALLENGE,'numbers':{},'manual_inline_choice':True,'effects':[{'type':'soul_contract_procedure','operation':'anchor'}],'riders':[]}})


@hook('additional_actions')
def anchor_challenge_actions(engine,actor):
    own=any(engine.action_catalog[a].parameters.get('soul_contract_operation')=='anchor' for a in actor.action_ids if a in engine.action_catalog)
    return [ANCHOR_CHALLENGE] if not own and ANCHOR_CHALLENGE in engine.action_catalog and available(engine,actor,'anchor') else []


def contract_action_text(op):
    descriptions={
        'sight':'Action: analyze an active Soul Contract within your normal Qi Sensing range. Learn its parties, grade, breach status, collateral categories, Source Cultivation Level and acceptance state. Superior protected text stays private. No Qi or Claim cost.',
        'minor_qi':'Bonus Action and 1 Claim: remove current pledged Cultivation Points up to your Proficiency Bonus from one breaching party within 60 feet, or remotely on this plane if the Contract permits. Regain Qi equal to half removed, rounded up.',
        'minor_blood_necrotic':'Bonus Action and 1 Claim: deal 3d8 Necrotic damage to one breaching party with pledged blood collateral within 60 feet, or remotely if the Contract permits. You or one named beneficiary gains Temporary Hit Points equal to half the damage dealt.',
        'minor_blood_psychic':'Bonus Action and 1 Claim: deal 3d8 Psychic damage to one breaching party with pledged blood collateral within 60 feet, or remotely if the Contract permits. You or one named beneficiary gains Temporary Hit Points equal to half the damage dealt.',
        'minor_item':'Bonus Action and 1 Claim: freeze the exact pledged nonartifact item of a breaching party within 60 feet, or remotely if permitted, until your next turn starts. It cannot be activated, dismissed, called, transferred or willingly moved. If your Source Cultivation Level exceeds its authority, move the real item by a legal route within 5 feet of you or a named beneficiary.',
        'minor_movement':'Bonus Action and 1 Claim: one breaching party within 60 feet, or remotely if permitted, has Speed 0 until its next turn starts, or is pulled up to 15 feet toward the pledged boundary, creditor, prison or delivery point.',
        'minor_voice':'Bonus Action and 1 Claim: a breaching party within 60 feet, or remotely if permitted, cannot speak, use audible techniques or communicate the named pledged secret until your next turn starts.',
        'minor_service':'Bonus Action and 1 Claim: a breaching party within 60 feet, or remotely if permitted, must use an available Reaction for its explicitly pledged ordinary, non-self-destructive action. A resisting party makes a Charisma save; success still removes its Reaction.',
        'transfer':'Action and 2 Qi: transfer one unspent Claim and its foreclosure right to a willing authorized assignee named in the same Contract. No new obligation is created.',
        'anchor':'Action: make a compatible Cultivation Check against an adjacent Major Contract Anchor. Success releases that party; already collected collateral is not restored. No Qi or Claim cost.',
        'call':'Action, 5 Qi and 1 Claim: call a breaching party on this plane by a legal route to the nearest legal space within 10 feet of the named destination. A successful Charisma save instead makes its Speed 0 and prevents willing teleportation through the end of its next turn. Barriers may block or delay travel.',
        'cultivation':'Action and 3 Claims: foreclose one pledged cultivation collateral within 60 feet or remotely through an authorized Anchor. A failed Charisma save suppresses it for one hour; success lasts until its next turn starts. Printed Source Cultivation Level differences change duration and higher authority requires a Cultivation Check.',
        'payment':'Action and at least 1 Claim: collect one exact pledged payment by the transfer procedure in its breached Major or Sovereign Contract. Real items use legal routes and are never copied; memories are sealed or copied exactly as agreed. Unpledged property cannot be seized.',
        'court':'Action and 8 Qi, once per scene: concentrate for up to one minute on a 40-foot-radius field centered on the Sovereign Anchor. Contract terms, Claims, collateral, breaches and assignees become visible inside. Foreclosures cost one fewer Claim, minimum 1; Call and Foreclose Cultivation reach parties anywhere inside.',
        'penalty':'After Sovereign breach, choose one printed penalty using only that party’s pledged collateral. Suppress cultivation, seal movement to the named territory, transfer a pledged price, inflict matching Tier III or IV harm, call the party to the Anchor, or escrow pledged soul collateral. No additional action or resource cost.',
        'final':'Once during Contract Court: a party in Sovereign breach with at least four Claims makes a Charisma save against one exact pledged result.'}
    return descriptions[op]


def release_travel_collateral(session,c):
    """Ending a contract returns suppression, never collected or destroyed prices."""
    for actor_id,actor in session.state['actors'].items():
        retained=[]
        for effect in actor.get('soul_contract_effects',[]):
            data=json.loads(effect['data'])
            if data.get('contract_id')!=c['id'] or effect['condition']=='condition:typed.soul_contract_long_term_harm':
                retained.append(effect);continue
            if effect['condition']=='condition:typed.soul_contract_points_suppressed':
                rid=data['system']
                maximum=next(r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id']==rid)
                actor['resources'][rid]=min(maximum,actor['resources'][rid]+int(data['current_withheld']))
                session.emit('SOUL_CONTRACT_POINTS_RETURNED',actor_id,contract_id=c['id'],amount=int(data['current_withheld']))
        actor['soul_contract_effects']=retained


def final_foreclosure_outcome(ctx,target,c,successful_save):
    """Printed results, separated from the unresolved Claim expenditure rule.

    This is not an admission/cost bypass: only a cost-settled native procedure
    may call it. It never invents collateral or expands a pledged transfer.
    """
    pledges=c['collateral'][target.entity_id]
    if successful_save:
        systems=[p for p in pledges if p['kind']=='system']
        if systems:
            from .effect_durations import token
            selected=pick(ctx,'final_resisted_system',[str(i) for i in range(len(systems))],
                {str(i):p['name'] for i,p in enumerate(systems)},prompt='Successful Charisma save: choose one pledged system to suppress until the end of '+target.display_name+'’s next turn.')[0]
            suppress_collateral(ctx,target,c,systems[int(selected)],token('end',target.entity_id,target.turns_started+1))
        from ..typed_executor import CP_POOLS
        pools=[rid for rid in target.resources if rid in CP_POOLS]
        if pools:
            selected=pick(ctx,'final_resisted_pool',pools,{rid:rid.removeprefix('resource:core.').capitalize() for rid in pools},
                prompt='Successful Charisma save: '+target.display_name+' loses current Cultivation Points equal to twice the creditor’s Proficiency Bonus. Choose its actual resource.')[0]
            resource(ctx.engine,target,selected,-2*c['pb'],ctx.source)
        return
    options=[]
    for i,p in enumerate(pledges):
        if p['kind']=='resource':options.append('qi:'+str(i))
        if p['kind']=='soul':options.append('escrow:'+str(i))
        if p['kind'] in ('item','office','lifespan','memory','bloodline','service'):options.append('price:'+str(i))
        if p['kind']=='service' and p.get('destination'):options.append('performance:'+str(i))
    if any(p['kind']=='system' for p in pledges):options.append('cultivation')
    require(bool(options),'No printed Final Foreclosure result matches this party’s actual pledges.')
    labels={}
    for key in options:
        if key=='cultivation':labels[key]='Close all explicitly pledged cultivation systems';continue
        op,i=key.split(':');pledge=pledges[int(i)]
        labels[key]={'qi':'Collect all current points from the pledged resource and prevent recovery for one hour',
            'escrow':'Place the exact pledged soul collateral in the Sovereign Anchor',
            'price':'Collect the exact named price by its pledged procedure',
            'performance':'Move to the named lawful service site and prevent voluntary departure for one hour'}[op]+': '+pledge['name']
    result=pick(ctx,'final_result',options,labels,prompt='Failed Charisma save: choose one printed Final Foreclosure result for '+target.display_name+' using only its exact pledged collateral.')[0]
    if result=='cultivation':
        for pledge in pledges:
            if pledge['kind']=='system':suppress_collateral(ctx,target,c,pledge)
        return
    op,index=result.split(':');pledge=pledges[int(index)]
    if op=='qi':
        resource(ctx.engine,target,pledge['resource'],-target.resources[pledge['resource']],ctx.source)
        condition(ctx,target,'no_recovery',{},'UNTIL_REMOVED',
            'Final Foreclosure: cannot recover the pledged '+pledge['name']+' for one hour',
            system=pledge['resource'],rounds=600,first_round=ctx.engine.state.round_number,contract_id=c['id'])
    elif op=='escrow':
        require(pledge['procedure']=='escrow','This exact soul collateral must name the Anchor escrow procedure.')
        require(seize_property(ctx,target,c,pledge),'The pledged soul collateral no longer exists.')
    elif op=='price':require(collect_payment(ctx,target,c,pledge),'The exact pledged price cannot currently transfer by its lawful procedure.')
    else:
        if call_party(ctx,target,c,pledge,radius=0):
            territory=pledge.get('territory') or [pledge['destination']]
            condition(ctx,target,'territory',{},'UNTIL_REMOVED',
                'Final Foreclosure: perform the pledged service at '+pledge['name']+'; no voluntary departure for one hour',
                territory=canonical(territory),rounds=600,first_round=ctx.engine.state.round_number,contract_id=c['id'])


@hook('resource_gain_allowed')
def final_recovery_lock(engine,actor,rid,amount,source):
    if amount and any(c.condition_id=='condition:typed.soul_contract_no_recovery' and c.data.get('system')==rid for c in actor.conditions.values()):return False
    return None


SECRET_CONDITION_ID='condition:typed.soul_contract_secret'
CHANNEL='condition:typed.soul_contract_channel'
SHARE_SECRET_ACTION_ID='action:soul_contract.share_secret'


@hook('fact_admission_schema')
def secret_schema(session,source,subject,kind):
    if source!=PARENT or not any(owned(a['bundle'],FEATURES[0]) for a in session.state['actors'].values()):return None
    if kind=='secret':return {'value_type':'text','maximum_seconds':2592000,'description':'The creature records one actual secret it knows; its content remains private.'}
    if kind=='communication_channel':return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
        'description':'The native world owner records a real acquired communication method and its Source Rule.'}
    return None


def secret_blocked(records,scope):
    return any(row.get('secret_scope')==scope for row in records)


@hook('journey_command')
def secret_collection(session,actor_id,kind,payload):
    if kind not in ('soul_contract_record_secret','soul_contract_record_channel','soul_contract_share_secret'):return None
    actor=session.state['actors'][actor_id]
    if kind=='soul_contract_record_secret':
        require(set(payload)=={'scope','name'},'Name your exact privately recorded secret and its scope.')
        record=read(session,PARENT,actor_id,'secret',payload['scope'],actor_id)
        require(record is not None and type(payload['name']) is str and bool(payload['name'].strip()),'Record a current secret you actually know first.')
        secrets=actor.setdefault('soul_contract_secrets',{})
        identity=digest({'source':PARENT,'owner':actor_id,'scope':payload['scope']})
        require(identity not in secrets,'That secret already has a native identity; a new declaration cannot replace its content.')
        secrets[identity]={'scope':identity,'source_scope':payload['scope'],'name':payload['name'],'value':record['value'],
            'owner':actor_id,'receipt':record['receipt_id']}
        session.emit('CONTRACT_SECRET_RECORDED',actor_id,scope=identity,receipt=record['receipt_id'])
    elif kind=='soul_contract_record_channel':
        require(set(payload)=={'scope'},'Choose the world-owner communication method record.')
        record=read(session,PARENT,actor_id,'communication_channel',payload['scope'],actor_id)
        require(record is not None,'The world owner must record this real communication capability first.')
        value=record['value']
        require(set(value)=={'name','mode','source_rule','range_ft','source_cl'} and value['mode'] in ('writing','gesture','telepathy','other')
            and all(type(value[k]) is str and value[k].strip() for k in ('name','source_rule')) and integer(value['range_ft'],1)
            and integer(value['source_cl'],1),'Name the real method, mode, Source Rule, range and authority.')
        actor.setdefault('soul_contract_channels',{})[payload['scope']]={**value,'receipt':record['receipt_id']}
        session.emit('CONTRACT_COMMUNICATION_METHOD_RECORDED',actor_id,scope=payload['scope'],receipt=record['receipt_id'])
    else:
        require(not actor['incapacitated'],'An incapacitated creature cannot communicate a secret through this procedure.')
        require(set(payload)=={'scope','recipient','channel'},'Choose your exact known secret, recipient and real communication method.')
        secret=actor.get('soul_contract_secrets',{}).get(payload['scope'])
        require(secret is not None and payload['recipient'] in session.state['actors'],'Choose an actual known secret and present recipient.')
        active=[json.loads(e['data']) for e in actor.get('soul_contract_effects',[]) if e['condition']=='condition:typed.soul_contract_voice']
        require(not secret_blocked(active,payload['scope']),'Voice Foreclosure prevents communicating that named secret by any method.')
        channel=payload['channel'];target=session.state['actors'][payload['recipient']]
        require(channel=='speech' or channel in actor.get('soul_contract_channels',{}),'This creature has not acquired that communication method.')
        if channel=='speech':require(not active,'Voice Foreclosure prevents speaking.')
        else:
            from ..gate2_runtime_models import Position
            method=actor['soul_contract_channels'][channel]
            require(session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(target['position']))<=method['range_ft'],'The recipient is outside this method’s actual range.')
        target.setdefault('soul_contract_secrets',{})[payload['scope']]={**deepcopy(secret),'learned_from':actor_id}
        session.emit('CONTRACT_SECRET_COMMUNICATED',actor_id,recipient=payload['recipient'],scope=payload['scope'],channel=channel)
    sync_bundles(session)
    return True


@hook('match_initialize')
def import_contract_secrets(engine):
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        data=bundle.get(STATE) or {}
        if actor is None:continue
        for secret in data.get('secrets',{}).values():
            engine._apply_condition(actor,SECRET_CONDITION_ID,PREFIX+FEATURES[0],actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'secret':canonical(secret),'secret_scope':secret['scope'],'label':'Private known secret'})
        for scope,channel in data.get('channels',{}).items():
            engine._apply_condition(actor,CHANNEL,PREFIX+FEATURES[0],actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'channel':canonical(channel),'channel_scope':scope,'label':'Recorded communication method: '+channel['name']})


@hook('match_start')
def install_secret_communication(engine):
    if not any(c.condition_id==SECRET_CONDITION_ID for actor in engine.state.actors.values() for c in actor.conditions.values()):return
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[SHARE_SECRET_ACTION_ID]=ActionDefinition(source_definition_id=SHARE_SECRET_ACTION_ID,display_name='Communicate a known secret',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={'expected_damage':0,
        'description':'Choose one secret you actually know, a recipient and speech or an actually acquired communication method. Foreclosed named secrets cannot be communicated by any method. No Action or Qi cost.',
        'typed':{'source':SHARE_SECRET_ACTION_ID,'numbers':{},'manual_inline_choice':True,'effects':[{'type':'soul_contract_share_secret'}],'riders':[]}})


@hook('additional_actions')
def offer_secret_communication(engine,actor):
    locks=[c.data for c in actor.conditions.values() if c.condition_id=='condition:typed.soul_contract_voice']
    return [SHARE_SECRET_ACTION_ID] if SHARE_SECRET_ACTION_ID in engine.action_catalog and any(c.condition_id==SECRET_CONDITION_ID and not secret_blocked(locks,c.data['secret_scope']) for c in actor.conditions.values()) else []


@effect('soul_contract_share_secret',harmful=False)
def communicate_known_secret(ctx,row):
    from ..speech import silenced,can_hear_from
    secrets={c.data['secret_scope']:json.loads(c.data['secret']) for c in ctx.actor.conditions.values() if c.condition_id==SECRET_CONDITION_ID}
    locks=[c.data for c in ctx.actor.conditions.values() if c.condition_id=='condition:typed.soul_contract_voice']
    secrets={key:value for key,value in secrets.items() if not secret_blocked(locks,key)}
    if not secrets:return
    scope=pick(ctx,'known_secret',list(secrets),{key:value['name'] for key,value in secrets.items()},prompt=ctx.actor.display_name+': choose an actual known secret to communicate. Its content is private to you and the chosen recipient.')[0]
    channels={c.data['channel_scope']:json.loads(c.data['channel']) for c in ctx.actor.conditions.values() if c.condition_id==CHANNEL}
    if not silenced(ctx.actor):channels={'speech':{'name':'Speak the secret','mode':'speech','range_ft':0},**channels}
    if not channels:return
    method=pick(ctx,'communication_method',list(channels),{key:value['name'] for key,value in channels.items()},prompt='Choose speech or an actually acquired communication method for '+secrets[scope]['name']+'.')[0]
    channel=channels[method]
    recipients={aid:a for aid,a in ctx.engine.state.actors.items() if aid!=ctx.actor.entity_id and
        (can_hear_from(ctx.engine,ctx.actor,a,ctx.source) if method=='speech' else ctx.engine._distance_actor_to_actor(ctx.actor,a)<=channel['range_ft'])}
    if not recipients:return
    aid=pick(ctx,'secret_recipient',list(recipients),{aid:a.display_name for aid,a in recipients.items()},prompt='Choose the actual recipient of '+secrets[scope]['name']+'.')[0]
    target=recipients[aid]
    if not any(c.condition_id==SECRET_CONDITION_ID and c.data['secret_scope']==scope for c in target.conditions.values()):
        ctx.engine._apply_condition(target,SECRET_CONDITION_ID,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'secret':canonical({**secrets[scope],'learned_from':ctx.actor.entity_id}),'secret_scope':scope,'label':'Privately learned secret'})
    ctx.engine._append_event('CONTRACT_SECRET_COMMUNICATED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(aid,),
        payload={'scope':scope,'channel':method})


OATH='tianxia.subpath.qi.oath_ledger_cultivator'
OATH_FEATURES=tuple(OATH+'.feature.'+s for s in ('record_the_promise','invoke_the_clause','battlefield_covenant','oathkeeper_s_record','heaven_as_witness'))


@hook('fact_admission_schema')
def source_access_schema(session,source,subject,kind):
    if source!=PARENT or subject not in session.state['actors']:return None
    if kind=='source_access':
        return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
            'description':'The native world owner grants actual forbidden-variant access through its legal Source Rule; it does not grant earned features.'}
    if kind=='conversion_environment':
        return {'value_type':'flag','maximum_seconds':28800,
            'description':'The creature confirms an actual calm environment and ambient Qi for a Cultivation Session spent training its accessed Variant.'}
    return None


def acquired_sheet(actor,fallback):
    text=actor.get('soul_contract_acquired_sheet') or actor.get('source_states',{}).get(PARENT,{}).get('acquired_sheet')
    if not text:return deepcopy(fallback)
    result=deepcopy(fallback);saved=json.loads(text)
    old_paths=deepcopy(saved['path_and_subpath']);current=deepcopy(fallback.get('path_and_subpath') or {})
    level=next((int(row[key]) for row in current.get('paths',[]) if row.get('path_id')=='tianxia.path.qi_cultivation' for key in ('attainment','owning_path_level','effective_cl') if integer(row.get(key),1)),0)
    acquired_level=int(old_paths.get('subpath_acquisition',{}).get('path_level',level))
    ids=set(current.get('path_feature_record_ids') or [])|set(current.get('source_granted_subpath_feature_record_ids') or [])
    extra=[PREFIX+f for old,f in zip(OATH_FEATURES,FEATURES) if old in ids]
    extra += [PREFIX+f for f,threshold in zip(FEATURES,LEVELS) if acquired_level<threshold<=level]
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
        own=list(dict.fromkeys([sid for sid in old_paths.get(key,[]) if sid.startswith(PREFIX)]+extra))
        current[key]=list(dict.fromkeys([sid for sid in current.get(key,[]) if not sid.startswith(OATH+'.feature.') and not sid.startswith(PREFIX)]+own))
    for key in ('subpath_record_id','subpath_record_ids','bindings','subpath_acquisition','subpath','subpaths'):
        if key in old_paths:current[key]=deepcopy(old_paths[key])
    current['earned_feature_occurrences']=[r for r in current.get('earned_feature_occurrences',[]) if not r.get('feature_id','').startswith(OATH+'.feature.')]
    result['path_and_subpath']=current
    return result


@hook('journey_source_sheet')
def source_sheet_overlay(sheet,session,actor_id):
    actor=session.state['actors'][actor_id]
    return acquired_sheet(actor,sheet) if (actor.get('soul_contract_acquired_sheet') or actor.get('source_states',{}).get(PARENT,{}).get('acquired_sheet')) else None


@hook('journey_acquisition')
def acquire_contract_source(session,actor_id,source,payload,owner_sheet):
    if source!=PARENT:return None
    procedure=payload.get('procedure','complete')
    require(procedure in ('train','complete') and set(payload)==({'access_scope','procedure','environment_scope'} if procedure=='train' else {'access_scope'} if 'procedure' not in payload else {'access_scope','procedure'}),'Choose the source access and its complete or training procedure.')
    actor=session.state['actors'][actor_id]
    require(not actor['incapacitated'],'An incapacitated creature cannot complete this acquisition procedure.')
    access=read(session,PARENT,actor_id,'source_access',payload['access_scope'],actor_id)
    require(access is not None,'The native world owner must first grant actual access to this forbidden Variant.')
    value=access['value']
    require(set(value)=={'variant','route','source_rule'} and value['variant']==PARENT and
        value['route'] in ('direct','conversion') and type(value['source_rule']) is str and value['source_rule'].strip(),
        'Name this exact Variant, Direct or Conversion Entry, and the legal Source Rule granting access.')
    sheet=acquired_sheet(actor,owner_sheet);paths=sheet.get('path_and_subpath') or {}
    path_ids=set(paths.get('path_record_ids') or [])|set((sheet.get('identity') or {}).get('path_ids') or [])
    if paths.get('path_record_id'):path_ids.add(paths['path_record_id'])
    require('tianxia.path.qi_cultivation' in path_ids,'This creature has not acquired the Qi Cultivation Path.')
    cl=int(sheet['identity']['cultivation_level']);pb=int(sheet['identity']['proficiency_bonus'])
    path_level=next((int(row[key]) for row in paths.get('paths',[]) if row.get('path_id')=='tianxia.path.qi_cultivation' for key in ('attainment','owning_path_level','effective_cl') if integer(row.get(key),1)),None)
    require(path_level is not None and 3<=path_level<=cl,'This acquisition requires committed Qi Path attainment of at least 3; overall CL alone cannot grant its progression.')
    ids=set(paths.get('path_feature_record_ids') or [])|set(paths.get('source_granted_subpath_feature_record_ids') or [])
    ids.update(r['feature_id'] for r in paths.get('earned_feature_occurrences',[]) if r.get('feature_id'))
    selections=set(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):selections.add(paths['subpath_record_id'])
    require(PARENT not in selections and not any(s.startswith(PREFIX) for s in ids),'This creature already acquired the Variant; acquisition cannot reset its limits.')
    parent_ids=set(OATH_FEATURES)&ids
    if procedure=='train':
        require(value['route']=='conversion' and parent_ids and selections<={OATH},'Only an attained Oath-Ledger parent can train Conversion Entry.')
        train_contract_conversion(session,actor_id,access,payload['environment_scope'])
        return {'sheet':None,'acquisition_id':access['receipt_id']}
    if value['route']=='direct':
        require(not selections and not parent_ids and not any(s.startswith('tianxia.subpath.qi.') for s in ids),
                'Direct Entry is the first Subpath choice and cannot retain another Qi Subpath progression.')
    else:
        require(parent_ids and selections<= {OATH},'Conversion Entry replaces the attained Oath-Ledger parent progression.')
        count=len(parent_ids)
        sessions=int(actor.get('soul_contract_training',{}).get(PARENT,0))
        require(sessions>=count,'Conversion requires one actual Cultivation Session per attained parent feature.')
        actor['soul_contract_training'][PARENT]=sessions-count
        from ..gate2_rolls import DeterministicRollAuthority
        roller=DeterministicRollAuthority(session.state['journey_id']+':source_conversion',counter=session.state.get('soul_contract_roll_counter',0))
        modifier=pb+next((int(a['modifier']) for a in sheet['ability_scores_and_statistics']['abilities'] if a['ability']==sheet['identity']['key_ability']),0)
        roll=roller.d20(modifier=modifier,actor_id=actor_id,reason='SOUL_CONTRACT_CONVERSION_CHECK')
        session.state['soul_contract_roll_counter']=roller.counter
        dc=10+pb+count
        session.emit('SOUL_CONTRACT_CONVERSION_ROLLED',actor_id,roll=canonical(roll.model_dump(mode='json')),dc=dc,
            access_receipt=access['receipt_id'],sessions_spent=count)
        if roll.total<dc:
            sync_bundles(session)
            return {'sheet':None,'acquisition_id':access['receipt_id']}
    earned=[PREFIX+f for f,l in zip(FEATURES,LEVELS) if path_level>=l] if value['route']=='direct' else [PREFIX+f for old,f in zip(OATH_FEATURES,FEATURES) if old in parent_ids]
    paths=deepcopy(paths)
    for field in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
        current=paths.get(field,[])
        paths[field]=[sid for sid in current if not sid.startswith(OATH+'.feature.')]
    paths['path_feature_record_ids']=list(dict.fromkeys([*paths['path_feature_record_ids'],*earned]))
    paths['source_granted_subpath_feature_record_ids']=list(dict.fromkeys([*paths['source_granted_subpath_feature_record_ids'],*earned]))
    paths['earned_feature_occurrences']=[r for r in paths.get('earned_feature_occurrences',[]) if not r.get('feature_id','').startswith(OATH+'.feature.')]
    paths['subpath_record_id']=PARENT;paths['subpath_record_ids']=[PARENT]
    new_subpath={'subpath_id':PARENT,'display_name':'Soul-Collateral Contract Cultivator','owning_path_id':'tianxia.path.qi_cultivation','source_packet_ids':[access['receipt_id']]}
    paths['subpath']=new_subpath
    paths['subpaths']=[r for r in paths.get('subpaths',[]) if r.get('owning_path_id')!='tianxia.path.qi_cultivation']+[new_subpath]
    paths['bindings']=[b for b in paths.get('bindings',[]) if b.get('path_id')!='tianxia.path.qi_cultivation']+[
        {'path_id':'tianxia.path.qi_cultivation','subpath_id':PARENT,'source_packet_ids':[access['receipt_id']]}]
    paths['subpath_acquisition']={'source_rule':value['source_rule'],'access_receipt':access['receipt_id'],'route':value['route'],
        'replaced_features':sorted(parent_ids),'earned_features':earned,'clock':int(session.clock()),'path_level':path_level}
    sheet['path_and_subpath']=paths
    actor['soul_contract_acquired_sheet']=canonical(sheet)
    if value['route']=='conversion':
        for recipient in session.state['actors'].values():
            snapshot=recipient.get('encounter_snapshot')
            if snapshot:
                snapshot['conditions']={key:raw for key,raw in snapshot['conditions'].items()
                    if not (json.loads(raw).get('source_actor_id')==actor_id and json.loads(raw).get('source_definition_id','').startswith(OATH+'.feature.'))}
        actor.setdefault('source_states',{}).pop(OATH,None)
    session.emit('SOUL_CONTRACT_SOURCE_ACQUIRED',actor_id,access_receipt=access['receipt_id'],route=value['route'],
        source_rule=value['source_rule'],earned_features=earned,replaced_features=sorted(parent_ids))
    return {'sheet':sheet,'acquisition_id':access['receipt_id']}


@hook('journey_acquired')
def publish_acquired_contract(session,actor_id,source,acquisition_id):
    if source==PARENT:sync_bundles(session)


def train_contract_conversion(session,actor_id,access,environment_scope):
    """Paid preparation called only after native installed-sheet prerequisites."""
    environment=read(session,PARENT,actor_id,'conversion_environment',environment_scope,actor_id)
    require(environment is not None and environment['value']==1,'Confirm an actual calm ambient-Qi environment for this Cultivation Session.')
    actor=session.state['actors'][actor_id]
    session.tick(7200)
    require(read(session,PARENT,actor_id,'conversion_environment',environment_scope,actor_id) is not None,
        'The actual cultivation environment expired before this two-hour session ended.')
    training=actor.setdefault('soul_contract_training',{})
    training[PARENT]=training.get(PARENT,0)+1
    recovery=actor.setdefault('soul_contract_recovery',{})
    if not recovery.get('session_used'):
        recovery['session_used']=1
        journey_qi_gain(session,actor_id,journey_qi_maximum(actor))
    session.emit('SOUL_CONTRACT_CONVERSION_SESSION',actor_id,access_receipt=access['receipt_id'],seconds=7200)
    sync_bundles(session)
