"""Native Culinary learning and paid elapsed meal/ration preparation.

Reuses the stock-materials ledger and journey activity/consent contracts. Food
inputs are explicitly classified creature-days, never inferred from a name.
Rations remain physical batches consumed by the existing culinary_rations provider.
"""
from copy import deepcopy
from . import hook
from . import material_ledger as materials, prepared_consumables as batches
from ..journey import require, integer
from ..fact_consent_admission import read

SCHOOL='tianxia.subpath.qi.culinary_cultivator'
PREFIX=SCHOOL+'.feature.'
MEAL=PREFIX+'body_tempering_meal'
RATION=PREFIX+'sealed_field_rations'
KITCHEN=PREFIX+'cultivated_camp_kitchen'
COMMISSARY=PREFIX+'thousand_person_commissary'
BANQUET=PREFIX+'banquet_of_ten_thousand_tables'
LEVELS={MEAL:3,RATION:6,KITCHEN:10,COMMISSARY:14,BANQUET:18}
HASHES={MEAL:'d9ab010d1981815800478a0d56c22b2b1449358a6463af252abe44817a6d449a',
RATION:'941d2e6ddcb32e331ce5ddd06e6c5ea3bbfd07cf7afc6a40920ee947300240a6',
KITCHEN:'0e73589047f9fb2722f0edf5f962977ff7c1d8a638633f28c08d9336d771f076',
COMMISSARY:'5f364520e1bc2615f04c37ad707c08d96c2ceeb7b3b53b70b9e24575ac03698f',
BANQUET:'f2c4bee2a6a1556a0d0dd319eedcbea3d60b731af4a0c59cbddce1dc46ecc181'}
COURSES=('iron_bone_stew','long_march_rice','bitter_herb_broth','furnace_spice_skewers','clear_fish_soup','festival_dumplings')
CP='resource:core.qi'
KEY='culinary:preparation'


@hook('subpath_acquisition')
def acquisition(source,sheet):
    if source!=SCHOOL:return None
    from ..table_advance import known
    facts=known(sheet)
    other=any(str(f).startswith('tianxia.subpath.qi.') and not str(f).startswith(SCHOOL+'.')
              for f in (sheet.get('path_and_subpath') or {}).get('path_feature_record_ids',()))
    legal='tianxia.path.qi_cultivation' in facts['paths'] and facts['cl']>=3 and not other
    return {'name':'Culinary Cultivator','legal':legal,'reasons':[] if legal else ['Culinary Cultivator requires Qi Cultivation, CL3 and an available Subpath.'],
            'features':[{'id':f,'minimum_cl':cl,'text_sha256':HASHES[f]} for f,cl in LEVELS.items()]}


@hook('compile_passives')
def seal(rows,info):
    held=[f for f in LEVELS if f in info['owned_ids']]
    if not held:return None
    return [*rows,{'block':KEY,'owned':held,'numbers':deepcopy(info['numbers'])}]


def specification(session,aid):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives',()) if r.get('block')==KEY),None)


def owns(session,aid,feature):
    return feature in (specification(session,aid) or {}).get('owned',())


def state(session,aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(KEY,{})


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source in LEVELS and kind=='willing' and any(owns(session,a,source) for a in session.state['actors']):
        return {'value_type':'flag','maximum_seconds':86400,'description':'Consent to attend and consume this Culinary preparation.'}


def food(session,aid,key,count,*,meal=False):
    row=materials.holdings(session,aid).get(key)
    require(row is not None and row['kind']=='raw_material' and row['unit']==('creature_day' if meal else 'ration_ingredient_portion')
            and materials.sources(session).get(row['source_id'],{}).get('material')=='ordinary_food'
            and row['quantity']>=count, 'Use actual food: one creature-day per Meal target, or source-accounted ingredient portions for field rations.')


@hook('journey_command')
def learn(session,aid,kind,payload):
    if kind!='culinary_courses':return None
    require(owns(session,aid,MEAL) and set(payload)=={'courses'} and isinstance(payload['courses'],list), 'Choose learned Meal Courses.')
    count=6 if owns(session,aid,COMMISSARY) else 4 if owns(session,aid,RATION) else 3
    chosen=payload['courses'];old=state(session,aid).get('courses',[])
    require(len(chosen)==count and len(set(chosen))==count and set(chosen)<=set(COURSES) and set(old)<=set(chosen),
            'Learn three Courses at CL3, one more at CL6 and all six at CL14.')
    state(session,aid)['courses']=list(chosen)
    session.emit('CULINARY_COURSES_LEARNED',aid,courses=list(chosen))
    return True


def validate(session,aid,source,p):
    require(owns(session,aid,source), 'This cook has not acquired this Culinary feature.')
    require(not session.state['actors'][aid]['incapacitated'], 'An incapacitated cook cannot prepare food.')
    if source==RATION:
        from .culinary_rations import KINDS
        require(set(p)=={'food','rations'} and isinstance(p['rations'],list) and 1<=len(p['rations'])<=specification(session,aid)['numbers']['pb']
                and all(k in KINDS for k in p['rations']), 'Choose up to Proficiency Bonus rations and an actual food holding.')
        food(session,aid,p['food'],len(p['rations']))
    else:
        require(set(p)=={'food','servings','rations'} and isinstance(p['servings'],dict) and p['servings'], 'Assign actual recipients and one learned Course each.')
        n=specification(session,aid)['numbers']
        require(len(p['servings'])<=1+2*n['pb'] and len([t for t in p['servings'] if t!=aid])<=2*n['pb'], 'A meal serves yourself and up to twice Proficiency Bonus others.')
        for target,course in p['servings'].items():
            require(target in session.state['actors'] and course in state(session,aid).get('courses',[]), 'Choose actual recipients and learned Courses.')
            consent=read(session,MEAL,target,'willing',aid,aid)
            require(consent and consent['value']==1,'Each eater must consent to attend and consume this cook’s meal.')
        food(session,aid,p['food'],len(p['servings']),meal=True)
        from .culinary_rations import KINDS
        expected=n['pb'] if owns(session,aid,RATION) else 0
        require(isinstance(p['rations'],list) and len(p['rations'])==expected and all(k in KINDS for k in p['rations']), 'At CL6 choose the type of every free prepared field ration.')


@hook('activity_spec')
def activity(session,aid,source,p):
    if source not in (MEAL,RATION):return None
    validate(session,aid,source,p)
    require(session.state['actors'][aid]['resources'].get(CP,0)>=(1 if source==MEAL else 2),'Pay the printed Qi cost before preparing.')
    return {'seconds':3600 if source==MEAL else 600,'label':'Body-Tempering Meal (one hour, 1 Qi)' if source==MEAL else 'Sealed Field Rations (10 minutes, 2 Qi)'}


@hook('activity_started')
def start(session,aid,row):
    if row['source'] not in (MEAL,RATION):return
    p=row['parameters'];source=row['source']
    session.spend_resource(aid,CP,1 if source==MEAL else 2,source)
    materials.consume(session,aid,p['food'],len(p['servings']) if source==MEAL else len(p['rations']))
    row['culinary_paid']=1


@hook('activity_validate')
def continuing(session,aid,row):
    if row['source'] not in (MEAL,RATION):return
    require(owns(session,aid,row['source']) and row.get('culinary_paid')==1,'Preparation must retain its acquired source and committed payment.')
    if row['source']==MEAL:
        for target in row['parameters']['servings']:
            receipt=read(session,MEAL,target,'willing',aid,aid)
            require(receipt and receipt['value']==1,'Meal recipients must remain willing throughout preparation.')


@hook('activity_finished')
def finish(session,aid,row):
    if row['source'] not in (MEAL,RATION):return
    numbers=specification(session,aid)['numbers'];p=row['parameters']
    from collections import Counter
    for kind,count in Counter(p['rations']).items():
        batches.prepare(session,aid,row,kind='sealed_'+kind,count=count,lifetime=86400,numbers=numbers)
    if row['source']==MEAL:
        for target,course in p['servings'].items():
            state(session,target)['serving']={'course':course,'maker':aid,'numbers':deepcopy(numbers),
                'prepared_at':int(session.clock()),'prepared_scene':session.state.get('scene_id',session.state['journey_id']),
                'recipient_rest':session.state['actors'][target]['long_rests']}
            session.emit('MEAL_PORTION_SERVED',target,maker=aid,course=course,source=MEAL)


@hook('journey_command')
def eat(session,aid,kind,payload):
    if kind not in ('culinary_eat','culinary_decline_meal'):return None
    if kind=='culinary_decline_meal':
        require(not payload and state(session,aid).get('serving') is not None,'Choose your actual served portion.')
        del state(session,aid)['serving'];session.emit('MEAL_PORTION_DECLINED',aid,source=MEAL)
        return True
    require(not payload,'Consume your own served Meal Portion; no replacement receipt can be supplied.')
    data=state(session,aid);serving=data.get('serving')
    require(serving is not None and session.state['actors'][aid]['long_rests']==serving['recipient_rest']
            and serving['prepared_scene']==session.state.get('scene_id',session.state['journey_id']),
            'Attend this meal and consume its actual served portion before leaving its scene or resting.')
    require(not session.state['actors'][aid]['incapacitated'],'An incapacitated creature cannot choose to eat a meal.')
    require(serving['maker']==aid or session.near_visible(aid,serving['maker']),
            'Receive the actual serving from your adjacent cook before consuming it.')
    consent=read(session,MEAL,aid,'willing',serving['maker'],serving['maker'])
    require(consent and consent['value']==1,'Consuming this served meal requires the eater’s current consent.')
    data['meal']={k:deepcopy(serving[k]) for k in ('course','maker','numbers')}
    data['meal']['ends_after_rest']=session.state['actors'][aid]['long_rests']+1
    del data['serving']
    session.emit('MEAL_PORTION_CONSUMED',aid,maker=serving['maker'],course=serving['course'],source=MEAL)
    return True


@hook('journey_rest')
def rest(session,aid):
    data=session.state['actors'][aid].get('source_states',{}).get(KEY,{})
    meal=data.get('meal')
    if meal and session.state['actors'][aid]['long_rests']>=meal['ends_after_rest']:
        del data['meal'];session.emit('MEAL_COURSE_ENDED',aid,source=MEAL)


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel':return None
    serving=session.state['actors'][aid].get('source_states',{}).get(KEY,{}).get('serving')
    if serving:
        return [{'id':'culinary:eat','kind':'culinary_eat','payload':{},'auto_select':0,
                 'label':'Consume your served '+serving['course'].replace('_',' ').title()+': one Meal Portion; until the end of your next Long Rest.'},
                {'id':'culinary:decline','kind':'culinary_decline_meal','payload':{},'auto_select':0,
                 'label':'Decline your served Meal Portion; gain no Course.'}]
    if not owns(session,aid,MEAL):return None
    from itertools import combinations
    count=6 if owns(session,aid,COMMISSARY) else 4 if owns(session,aid,RATION) else 3
    old=set(state(session,aid).get('courses',[]))
    return [{'id':'culinary:learn:'+','.join(c),'kind':'culinary_courses','auto_select':0,'payload':{'courses':list(c)},
             'label':'Learn Meal Courses: '+', '.join(x.replace('_',' ').title() for x in c)+'. No Qi or action cost.'}
            for c in combinations(COURSES,count) if old<=set(c)]


@hook('journey_combat_bundle')
def export(bundle,session,aid):
    from .culinary_rations import actions_for_stock, POOL
    from ..gate2_runtime_models import ResourceDefinition
    stock=[]
    for key,row in session.state['actors'][aid].get('material_holdings',{}).items():
        if not batches.available(session,aid,key) or not row['preparation'].startswith('sealed_'):continue
        stock.append({'kind':row['preparation'].removeprefix('sealed_'),'count':row['quantity'],
                      'maker_cl':row['numbers']['cl'],'maker_pb':row['numbers']['pb'],'maker_key_mod':row['numbers']['key_mod'],
                      'age_seconds':int(session.clock())-row['acquired_at'],
                      'remaining_rounds':(row['expires_at']-int(session.clock())+5)//6,'batch':key})
    meal=session.state['actors'][aid].get('source_states',{}).get(KEY,{}).get('meal')
    if not stock and not meal and not owns(session,aid,MEAL):return None
    # The same resource/action consumer handles physical equipment and native
    # batches. Do not overwrite carried equipment pools with journey stock.
    require(not any(r['resource_id'].startswith(POOL) for r in bundle['actor_template']['resources']),
            'Resolve legacy manually recorded rations before binding native prepared batches.')
    out=deepcopy(bundle)
    out['culinary_native']=1
    if meal:out['culinary_meal']=deepcopy(meal)
    from hashlib import sha256
    info={'numbers':{},
          'short':sha256(aid.encode()).hexdigest()[:12],'actor_id':aid}
    actions=actions_for_stock(info,stock)
    for i,item in enumerate(stock):
        out['actor_template']['resources'].append(ResourceDefinition(resource_id=POOL+str(i),initial=item['count'],maximum=item['count']).model_dump(mode='json'))
    out['action_catalog'].extend(a.model_dump(mode='json') for a in actions)
    out['actor_template']['action_ids'].extend(a.source_definition_id for a in actions)
    out['culinary_batches']=[{'id':item['batch'],'pool':POOL+str(i)} for i,item in enumerate(stock)]
    return out


@hook('journey_encounter_settled')
def import_remaining(session,aid,engine,creature):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==aid),{})
    for row in bundle.get('culinary_batches',()):
        holding=materials.holdings(session,aid).get(row['id'])
        require(holding is not None,'The continued ration must retain its physical batch.')
        remaining=creature.resources.get(row['pool'],0)
        require(integer(remaining) and remaining<=holding['quantity'],'Encounter rations cannot create new portions.')
        holding['quantity']=remaining

COURSE_CONDITION='condition:typed.culinary_meal_course'


@hook('match_initialize')
def serve_prepared(engine):
    for bundle in engine.typed_bundle_documents:
        meal=bundle.get('culinary_meal');target=engine.state.actors.get(bundle['actor_id'])
        if not meal or target is None:continue
        data={'label':meal['course'].replace('_',' ').title()+': until your next Long Rest or replacement',
              'course':meal['course'],'pb':meal['numbers']['pb'],'maker':meal['maker'],'furnace_used':int(meal.get('furnace_used',0))}
        if meal['course']=='long_march_rice':data['speed_delta']=5
        engine._apply_condition(target,COURSE_CONDITION,MEAL,meal['maker'],expires_on='UNTIL_REMOVED',data=data)
        if meal['course']=='iron_bone_stew':
            from .maximum_hp_riders import apply_stew
            apply_stew(engine,target,meal['maker'],2*meal['numbers']['pb'],
                current_delta=meal['continued_hp']-target.current_hp if 'continued_hp' in meal else None)
        elif meal['course']=='furnace_spice_skewers':
            engine._grant_temp_hp(target,2*meal['numbers']['pb'],MEAL,meal['maker'])


@hook('journey_snapshot_actor')
def normalize_meal_snapshot(creature,session,aid,engine):
    """Remove only this provider's projection before ordinary health validation.

    Base-equivalent HP plus the continuing meal reproduces the actual HP at
    re-entry, without paying another preparation or healing on each reload.
    """
    from .maximum_hp_riders import STEW
    own=[(k,c) for k,c in creature.conditions.items() if c.condition_id in (COURSE_CONDITION,STEW)]
    if not own:return None
    out=creature.model_copy(deep=True)
    for key,c in own:
        adjustment=out.maximum_hp_adjustments.pop(key,None)
        if adjustment:
            out.current_hp=max(1 if out.current_hp>0 else 0,out.current_hp-adjustment.amount)
        del out.conditions[key]
    if any(c.condition_id==STEW for _,c in own):
        base=out.maximum_hp_base if out.maximum_hp_base is not None else out.maximum_hp
        out.current_hp=min(out.current_hp,max(1,base+sum(r.amount for r in out.maximum_hp_adjustments.values())))
        out.maximum_hp=max(1,base+sum(r.amount for r in out.maximum_hp_adjustments.values()))
        if not out.maximum_hp_adjustments:out.maximum_hp_base=None
    return out


@hook('journey_encounter_settled')
def import_meal_cadence(session,aid,engine,creature):
    held=next((c for c in creature.conditions.values() if c.condition_id==COURSE_CONDITION),None)
    meal=session.state['actors'][aid].get('source_states',{}).get(KEY,{}).get('meal')
    if meal and held:
        meal['furnace_used']=int(held.data.get('furnace_used',0))
        if meal['course']=='iron_bone_stew':meal['continued_hp']=creature.current_hp


@hook('save_mode')
def meal_saves(engine,target,ability,dc,source_id,roll_context):
    courses={c.data['course'] for c in target.conditions.values() if c.condition_id==COURSE_CONDITION}
    named=set(roll_context.get('named') or ())
    if 'bitter_herb_broth' in courses and named & {'poison','poisoned','disease','contaminated_food','contaminated_water','parasites','ordinary_environmental_sickness'}:
        return 'ADVANTAGE'
    if 'long_march_rice' in courses and 'exhaustion' in named and named & {'travel','forced_march','hunger','thirst','ordinary_exposure','carrying_loads'}:
        return 'ADVANTAGE'
    return None


@hook('d20_bonus')
def furnace_after_roll(engine,roll,intent):
    if not str(roll.reason).startswith('CHECK:') or roll.natural_result is None:return None
    context=engine.d20_context(roll) or {}
    if context.get('ability') not in ('STR','CON'):return None
    target=engine.state.actors.get(roll.actor_id)
    held=next((c for c in target.conditions.values() if c.condition_id==COURSE_CONDITION and c.data['course']=='furnace_spice_skewers'),None) if target else None
    if held is None or held.data.get('furnace_used'):return None
    from .rider_choices import pick
    chosen=pick(engine,target,'furnace_course','Furnace-Spice Skewers',['use'],subject=target,optional=True,intent=intent,
        labels={'use':f'Add {held.data["pb"]} to this Strength or Constitution check after rolling; once before your Course ends'})
    if not chosen:return None
    held.data['furnace_used']=1
    return {'source_id':MEAL,'bonus':held.data['pb']}


@hook('journey_auto_blocked')
def pending_serving(session,aid):
    if session.state['actors'][aid].get('source_states',{}).get(KEY,{}).get('serving'):return True
    return None


@hook('journey_encounter_clock')
def elapsed_encounter(session,engine):
    # Real prepared food ages through a bound fight as well as outside it.
    if any(specification(session,aid) is not None or any(
            row.get('kind')=='prepared_consumable' for row in session.state['actors'][aid].get('material_holdings',{}).values())
            for aid in session.state['actors']):return True
    return None
