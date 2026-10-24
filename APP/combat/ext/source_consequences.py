"""Native table-owner application of externally adjudicated source consequences.

The shared fact admission transaction supplies source text, authority, target and
one explicit result. It does not infer injuries from damage. A declaration only requests a result. A real committed table action applies it
once through the normal reaction, damage and reload pipeline. Source consumers may replace exactly that result through source_consequence.
Other consequences require separate explicit applications and remain unaffected.
No declaration, no source result, no new action or anatomy. Private source text
continues to use the world-fact reader policy.
"""
from . import hook,effect,run_strict
from ..journey import require,integer
from ..gate2_runtime_models import DiceSpec

AUTHORITY='system:source_consequences'
OPERATIONS=('disarm','break','rust','warp','corrode','dull','destroy_limb','deform_limb')
AUTHORITIES=('ordinary','artifact','divine','secret','foundation','method','immortal','conceptual')


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source==AUTHORITY and kind=='apply_result' and hasattr(session,'engine'):
        return {'value_type':'document','maximum_seconds':60,'authority':'table_owner',
                'description':'Apply one explicit external Source Rule consequence to a present creature or its physical implement.'}


@hook('fact_admission_validate')
def validate(session,source,subject,kind,scope,value):
    if source!=AUTHORITY or kind!='apply_result':return
    require(hasattr(session,'engine'),'Apply external consequences through a native table scene.')
    required={'source_rule','source_cl','explicit_source_cl','authority','source_actor_id','operation','target_kind','target_key','reconstructable'}
    require(required<=set(value)<=required|{'result_nature'},
            'Record the exact source rule, Source CL and authority, source actor, explicit operation and target structure.')
    require(value.get('result_nature','physical') in ('physical','conceptual_erasure'),
            'Classify the actual result separately from the Source Rule’s authority.')
    require(type(value['source_rule']) is str and bool(value['source_rule'].strip()) and integer(value['source_cl'])
            and value['authority'] in AUTHORITIES and value['operation'] in OPERATIONS
            and value['explicit_source_cl'] in (0,1) and type(value['explicit_source_cl']) is int
            and type(value['reconstructable']) is int and value['reconstructable'] in (0,1), 'Use the typed source-result fields.')
    require(value['source_actor_id']=='' or value['source_actor_id'] in session.state['actors'], 'Choose a present source actor or an external source.')
    require(value['target_kind'] in ('body','weapon','limb','natural_structure','appendage')
            and type(value['target_key']) is str and bool(value['target_key'].strip()), 'Identify the actual physical target. Flavor creates no anatomy.')
    anatomy=value['operation'] in ('destroy_limb','deform_limb')
    require(not anatomy or value['target_kind'] in ('limb','natural_structure','appendage'), 'An anatomical operation requires a specific physical structure.')
    require(value['operation']!='disarm' or value['target_kind']=='weapon','Disarm requires a physical weapon.')
    if anatomy and value['target_key'].startswith('hand:'):
        from .hand_occupancy import hand_parts
        require(value['target_key'] in hand_parts(session.engine,session.engine.state.actors[subject]),
                'Choose an actual functional native hand slot; source text creates no extra hand.')
    if value['target_kind']=='weapon':
        actions=session.state['actors'][subject]['bundle'].get('action_catalog',())
        require(any(a['source_definition_id']==value['target_key'] and (a.get('parameters',{}).get('typed') or {}).get('weapon') for a in actions),
                'Choose an actual weapon from this creature’s inventory.')
    return True


@hook('body_part_functional')
def recorded_structure_loss(engine,actor,part):
    if any(c.condition_id=='condition:source.anatomy_loss' and c.source_definition_id==AUTHORITY
           and c.data.get('target_key')==part and c.data.get('functional')==0
           for c in actor.conditions.values()):return False


def apply_result(engine,subject,result,receipt_id,intent):
    replies=[r for r in run_strict('source_consequence',engine,subject,result) if r is not None]
    require(len(replies)<=1,'Only one source may replace this exact consequence.')
    if replies:
        replacement=replies[0]
        require(isinstance(replacement,dict) and set(replacement)<={'prevented','dice','damage_type','source','exclude_temp_hp_source','excluded_reduction_sources','label'},
                'A source replacement must prevent this result or supply its printed replacement damage.')
        if 'dice' in replacement:
            roll=engine.roller.roll(DiceSpec(**replacement['dice']),actor_id=subject.entity_id,reason='DAMAGE:'+replacement['source'])
            engine._record_roll(roll)
            # Only the excluded source's currently surviving temporary buffer is
            # withheld. Independent defenses still meet the native damage packet.
            excluded=replacement.get('exclude_temp_hp_source')
            latest=next((e for e in reversed(engine.events) if e.event_type=='TEMP_HP_GRANTED'
                and subject.entity_id in e.target_ids and int(e.payload.get('after',0))>int(e.payload.get('before',0))),None)
            flags=('bypass_temporary_hp',) if excluded and latest and latest.source_definition_id==excluded else ()
            flags+=tuple('exclude_reduction_source:'+source for source in replacement.get('excluded_reduction_sources',()))
            engine._commit_damage(subject,int(roll.total),replacement['damage_type'],replacement['source'],
                                  result['source_actor_id'],intent,reaction_depth=0,source_flags=flags)
        outcome='REPLACED'
    else:
        operation=result['operation'];key=result['target_key']
        action=engine.action_catalog.get(key)
        target_label=action.display_name.removesuffix(' attack') if action is not None else anatomical_label(result['target_kind'],key)
        condition='condition:source.anatomy_loss' if operation in ('destroy_limb','deform_limb') else 'condition:source.implement_damage'
        data={'operation':operation,'target_key':key,'target_kind':result['target_kind'],'source_cl':result['source_cl'],
              'receipt_id':receipt_id,'information_profile':{'authority':result['authority'],'source_cl':result['source_cl']},'functional':0,'label':'Recorded '+operation.replace('_',' ')+': '+target_label+'; persists until legally restored'}
        data['result_nature']=result_nature(result)
        if result['target_kind']=='weapon':data['disables_action']=key
        if operation=='disarm':condition='condition:typed.disarmed';data.update({'disables_action':key,'weapon':key,'dropped_at':subject.position.model_dump(mode='json')})
        engine._apply_condition(subject,condition,AUTHORITY,result['source_actor_id'] or subject.entity_id,
                                expires_on='UNTIL_REMOVED',data=data,unavoidable=True)
        outcome='APPLIED'
    engine._append_event('PASSIVE_TRIGGERED',AUTHORITY,actor_id=subject.entity_id,target_ids=(subject.entity_id,),
        payload={'receipt_id':receipt_id,'operation':result['operation'],'target_key':result['target_key'],'outcome':outcome,'log':(replies[0].get('label') if replies else None) or ('Recorded '+result['operation'].replace('_',' ')+' resolved for '+subject.display_name+'.')})


def anatomical_label(kind,key):
    """Turn canonical anatomy keys into readable condition-pill names."""
    if kind == 'limb' and key.startswith('hand:'):
        side=key.partition(':')[2]
        if side in ('left','right'): return side+' hand'
    if kind in ('natural_structure','appendage'):
        return key.replace('_',' ').replace(':',' ')
    return key.replace('_',' ').replace(':',' ')


def result_nature(result):
    """Explicit result classification, retaining the old conceptual declaration.

    New declarations distinguish physical loss from conceptual erasure even
    when their authority is the same. Historical conceptual-authority records
    used that field for erasure; no old record is silently broadened.
    """
    return result.get('result_nature','conceptual_erasure' if result['authority']=='conceptual' else 'physical')


ACTION='action:system.source_consequence'
DONE='condition:source.result_resolved'


def pending(engine,viewer):
    from ..combat_world_facts import records,clock,Admission
    from ..fact_consent_admission import read
    completed={c.data['receipt_id'] for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id==DONE}
    adapter=Admission(engine)
    out=[]
    for r in records(engine):
        if r['source']!=AUTHORITY or r['kind']!='apply_result' or r['expires_at']<=clock(engine) or r['receipt_id'] in completed:continue
        current=read(adapter,AUTHORITY,r['subject'],'apply_result',r['scope'],viewer)
        if current is not None and current['receipt_id']==r['receipt_id']:out.append(r)
    return out


@hook('match_start')
def register(engine):
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[ACTION]=ActionDefinition(source_definition_id=ACTION,display_name='Apply a recorded source consequence',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={'free_primary':True,
        'description':'Apply one actual external Source Rule result recorded by the table owner. Native protection and replacement rules still apply. No action or resource cost.',
        'typed':{'source':AUTHORITY,'effects':[{'type':'source_consequence'}],'numbers':{},'duration':{'kind':'instant'},'manual_inline_choice':True}})


@hook('additional_actions')
def options(engine,actor):
    return [ACTION] if pending(engine,actor.entity_id) else None


@hook('candidate_allowed')
def eligible(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==ACTION:return bool(pending(engine,actor.entity_id))


@effect('source_consequence')
def resolve(ctx,row):
    from .needle import ask,checkpoint_id
    from ..combat_world_facts import Admission
    requests=pending(ctx.engine,ctx.actor.entity_id)
    require(requests,'This source result is absent, expired or already resolved.')
    if len(requests)>1:
        picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'source_result'),ctx.actor,
            'choice:needle.source_consequence',[r['receipt_id'] for r in requests],minimum=1,maximum=1,
            labels={r['receipt_id']:'Recorded result for '+ctx.engine.state.actors[r['subject']].display_name for r in requests},
            name='Recorded source consequence',prompt='Choose one actual recorded source result to apply. No action or resource cost.')
        record=next(r for r in requests if r['receipt_id']==picked[0])
    else:record=requests[0]
    subject=ctx.engine.state.actors[record['subject']]
    validate(Admission(ctx.engine),AUTHORITY,record['subject'],'apply_result',record['scope'],record['value'])
    # Reserve before native replacement damage can open nested reactions.
    ctx.engine._apply_condition(subject,DONE,AUTHORITY,subject.entity_id,expires_on='UNTIL_REMOVED',
        data={'receipt_id':record['receipt_id'],'label':'Recorded source result resolved'})
    apply_result(ctx.engine,subject,record['value'],record['receipt_id'],ctx.intent)
