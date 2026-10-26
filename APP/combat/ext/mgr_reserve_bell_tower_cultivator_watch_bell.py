"""Bell-Tower native progression. Source: Qi Subpath R19 and Shared Qi R4.

All behavior requires a sealed owned feature at its printed CL. Choices use
Needle for humans on every turn; automatic recipients use personal perception.
Information goes through observer_information; it grants only the printed
observer/subject exception, never a team-wide hidden-position grant.
"""
from . import hook, effect, placed
from .. import observer_information as information

P = 'tianxia.subpath.qi.bell_tower_cultivator.feature.'
WATCH, ALARM, PURIFY, FORM, NINE = [P+s for s in ('watch_bell','alarm_resonance','purifying_peal','bell_tower_formation','ninefold_heavenly_bell')]
LEVELS = {WATCH:3, ALARM:6, PURIFY:10, FORM:14, NINE:18}
NAMES = {WATCH:'Watch Bell',ALARM:'Alarm Resonance',PURIFY:'Purifying Peal',FORM:'Begin Bell-Tower Formation',NINE:'Ninefold Heavenly Bell'}
QI = 'resource:core.qi'
BELL = 'condition:typed.bell.'
FORM_TAG, NINE_TAG = 'bell_formation', 'heavenly_bell'
UNTIL = 'START_OF_SOURCE_NEXT_TURN'
LABELS={
    'guarding':'Guarding Tone: +2 AC against the next attack roll; ends at the bell ringer’s next turn start',
    'clarity':'Clarity Tone: Advantage on the next save against Charmed, Frightened, Illusion or supernatural disorientation before the bell ringer’s next turn',
    'marked':'Bell-Marked: Invisible and ordinary concealment alone cannot hide you from this bell ringer; direction is revealed within 120 feet on the same plane',
    'resonance':'Revealing Tone: visible or audible resonance until the bell ringer’s next turn starts',
    'ritual':'Bell-Tower Formation: completing a one-minute ritual; its field is not active yet',
    'cannot_possess':'Judgment Resonance: cannot possess until your next turn starts',
    'closed_gate':'Closed Gate: lower-CL hostile teleportation into, and possession inside, the Heavenly Bell field are blocked until the bell ringer’s next turn',
    'great_alarm':'Great Alarm: Advantage on the next attack or save before the bell ringer’s next turn',
    'perception':'Ring the Alarm: Advantage on the next Perception check before your next turn',
    'corruption_suppressed':'One point of source-scoped temporary Corruption is suppressed for the stated duration'}
MENTAL = {'charmed','frightened','illusion','possession','supernatural_disorientation'}
QUALIFY = {'daemonic','demon','fiend','hostile spirit','incorporeal','possessing entity','undead'}


def owned(engine,actor,feature):
    return any(r.get('block') == 'bell_tower' and r.get('feature_id') == feature
               for r in engine.typed_passive_rows.get(actor.entity_id, []))


def numbers(engine,actor):
    return next((r['numbers'] for r in engine.typed_passive_rows.get(actor.entity_id,[])
                 if r.get('block') == 'bell_tower'), {})


def scene_grants(engine,actor,tag):
    current=scene_id(engine,actor)
    return [c for c in held(actor,tag) if c.data.get('scene',current)==current]


def scene_id(engine,actor):
    bundle=next((b for b in engine.typed_bundle_documents if b.get('actor_id')==actor.entity_id),{})
    return bundle.get('bell_tower_scene') or engine.state.match_id


def round_grants(engine,actor,tag):
    return [c for c in scene_grants(engine,actor,tag) if c.data.get('round')==engine.state.round_number
        and c.data.get('encounter',engine.state.match_id)==engine.state.match_id]


def bind_journey_scene(session,aid,current=None):
    actor=session.state['actors'][aid];bundle=actor['bundle']
    if not any(r.get('block')=='bell_tower' for r in bundle.get('typed_passives',())):return
    state=actor.setdefault('source_states',{}).setdefault(P.removesuffix('.feature.'),{})
    current=current or session.state.get('scene_id') or state.get('scene') or session.state['journey_id']
    if type(current) is not str or not current:raise ValueError('Bell-Tower requires a native scene identity')
    state['scene']=current;bundle['bell_tower_scene']=current
    from ..canonical import canonical_sha256
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    session.emit('BELL_SCENE_BOUND',aid,source=P.removesuffix('.feature.'),scene=current)


@hook('journey_initialize')
def initialize_journey_scene(session,aid):
    bind_journey_scene(session,aid)


@hook('journey_scene_end')
def end_journey_scene(session,previous,current):
    import json
    for aid,actor in session.state['actors'].items():
        # Recipients need not own Bell-Tower. The encounter snapshot is the
        # native continuation record; expired grants must not enter a new fight.
        snapshot=actor.get('encounter_snapshot')
        if snapshot:
            for iid,raw in list(snapshot.get('conditions',{}).items()):
                row=json.loads(raw)
                if (row['condition_id']==BELL+'corruption_suppressed'
                        and row.get('data',{}).get('scene')==previous):
                    del snapshot['conditions'][iid]
                    session.emit('BELL_CORRUPTION_SUPPRESSION_ENDED',aid,source=row['source_definition_id'])
        bind_journey_scene(session,aid,current)


def conscious(engine,actor):
    return actor.active and actor.current_hp>0 and actor.life_state in (None,'CONSCIOUS') and not any(
        c.condition_id in {'condition:typed.unconscious','unconscious'} for c in actor.conditions.values())


@hook('compile_passives')
def ownership(rows,info):
    found = [f for f,cl in LEVELS.items() if f in info['owned_ids'] and int(info['numbers'].get('cl') or 1)>=cl]
    return [*rows,*[{'block':'bell_tower','feature_id':f,'numbers':dict(info['numbers'])} for f in found]]


def action(info,feature):
    from ..gate2_runtime_models import ActionDefinition
    cost = {WATCH:1,PURIFY:4,FORM:5,NINE:8}[feature]
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{feature}",
        display_name=NAMES[feature],owner_id=info['actor_id'],economy='BONUS_ACTION' if feature==WATCH else 'ACTION',
        resolution_kind='TYPED',target_kind='SELF',costs=((QI,cost),),
        parameters={'description':f"{NAMES[feature]}: spend {cost} Qi. Choose the bell origin and printed benefits.",
            'typed':{'source':feature,'manual_inline_choice':True,'numbers':dict(info['numbers']),'duration':{'kind':'instant'},
                     'riders':[],'effects':[{'type':'bell_tower','feature':feature}]}})


@hook('compile_actions')
def actions(info):
    have = {(a.parameters.get('typed') or {}).get('source') for a in info['actions']}
    return [action(info,f) for f,cl in LEVELS.items() if f!=ALARM and f not in have and f in info['owned_ids']
            and int(info['numbers'].get('cl') or 1)>=cl] or None


@hook('compile_action')
def replace_catalog_action(old,info):
    typed=old.parameters.get('typed') or {}
    f=typed.get('source')
    if f not in {WATCH,PURIFY,FORM,NINE}:
        return None
    # Preserve the existing catalog action identity and source acquisition.
    return old.model_copy(update={'display_name':NAMES[f], 'target_kind':'SELF','range_ft':None,
        'parameters':{**old.parameters,'typed':{'source':f,'manual_inline_choice':True,'numbers':dict(info['numbers']),
            'duration':{'kind':'instant'},'riders':[],'effects':[{'type':'bell_tower','feature':f}]}}})


def choose(ctx,key,options,labels=None,maximum=1,minimum=1,optional=False,subject=None,automatic_options=None):
    from .rider_choices import pick
    labels=labels or {o:o.replace('_',' ').title() for o in options}
    return pick(ctx.engine,ctx.actor,'bell_'+key,ctx.action.display_name,options,
        subject=subject or ctx.actor,labels=labels,maximum=maximum,minimum=minimum,optional=optional,preferred=options[:maximum],
        intent=ctx.intent,automatic_options=automatic_options,
        prompt=f'{ctx.action.display_name}: choose {minimum if minimum==maximum else "up to "+str(maximum)} for {key.replace("_"," ")}.')


def allies(ctx,origin,feet):
    from ..relations import relation,ALLY
    return [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine,ctx.actor,a)==ALLY
            and ctx.engine.grid.distance_ft(origin,a.position)<=feet]


def select(ctx,key,roster,maximum=None,hearing=False):
    from ..speech import can_hear_from
    from ..target_knowledge import located
    roster=[a for a in roster if not hearing or can_hear_from(ctx.engine,ctx.actor,a,ctx.source)]
    if not roster: return []
    ids=[a.entity_id for a in roster]
    picked=choose(ctx,key,ids,{a.entity_id:a.display_name for a in roster},maximum=maximum or len(ids),minimum=0,
                  automatic_options=[a.entity_id for a in roster if a is ctx.actor or located(ctx.engine,ctx.actor,a)])
    return [a for a in roster if a.entity_id in picked]


def run(ctx,target,rows):
    from ..typed_executor import run_effects
    from .spirit_traditions import context
    run_effects(context(ctx.engine,ctx.actor,ctx.action,[target],ctx.numbers,ctx.intent),rows)


def put(ctx,target,name,data=None,expires=UNTIL):
    ctx.engine._apply_condition(target,BELL+name,ctx.source,ctx.actor.entity_id,expires_on=expires,
        data={'label':LABELS.get(name,name.replace('_',' ').title()),**(data or {})})


def held(actor,name,owner=None):
    return [c for c in actor.conditions.values() if c.condition_id==BELL+name and (owner is None or c.source_actor_id==owner.entity_id)]


def remove(engine,actor,condition,reason='CONSUMED'):
    from ..effect_endings import remove_instance
    remove_instance(engine,actor,'condition',condition.instance_id,condition.source_definition_id,
        actor_id=condition.source_actor_id,payload={'reason':reason,'instance_id':condition.instance_id,
            'condition_id':condition.condition_id},expected=condition)


def expiry(actor):
    from .effect_durations import holder_next_turn
    return holder_next_turn(actor)


def effect_option(engine,viewer,source):
    from ..canonical import canonical_sha256
    return 'bell-effect:'+canonical_sha256({'viewer':viewer.entity_id,'scene':scene_id(engine,viewer),
        'source':source['id'],'revision':source['revision']})[:24]


def origin(ctx,anchor=False):
    from ..gate2_runtime_models import Position
    from .qi_path import armament_condition,armament_point
    options={'self':ctx.actor.position}
    armed=armament_condition(ctx.actor)
    if armed and (armed.data.get('mode') or '').lower() in {'assault','guard'}:
        options['armament']=Position(x=armament_point(ctx.actor)[0],y=armament_point(ctx.actor)[1])
    if anchor:
        for z in placed.of(ctx.engine,FORM_TAG,owner_id=ctx.actor.entity_id):
            if anchor_live(ctx.engine,z): options['anchor:'+z.zone_id]=z.center
    if len(options)==1:return ctx.actor.position
    picked=choose(ctx,'origin',list(options),{k:('Your bell' if k=='self' else 'Bell Domain Armament' if k=='armament' else 'Active Bell Anchor') for k in options})
    return options[picked[0]] if picked else ctx.actor.position


@effect('bell_tower')
def activate(ctx,row):
    f=row['feature']
    if not owned(ctx.engine,ctx.actor,f): raise ValueError('This creature has not acquired this Bell-Tower feature')
    if f==WATCH: watch(ctx)
    elif f==PURIFY: purify(ctx)
    elif f==FORM: formation(ctx)
    elif f==NINE: nine(ctx)


def watch(ctx):
    tone=choose(ctx,'warning_tone',['guarding','clarity','revealing'],{
        'guarding':'Guarding Tone: one hearing ally within 60 feet gains +2 AC against its next attack until your next turn starts',
        'clarity':'Clarity Tone: one hearing ally within 60 feet gains Advantage on its next qualifying save before your next turn',
        'revealing':'Revealing Tone: mark one creature or test one active supernatural effect within 60 feet'})[0]
    if tone in {'guarding','clarity'}:
        picked=select(ctx,tone,allies(ctx,ctx.actor.position,60),maximum=1,hearing=True)
        for target in picked:
            if tone=='guarding':
                put(ctx,target,'guarding')
            else: put(ctx,target,'clarity')
        return
    engine=ctx.engine
    from ..target_knowledge import located,knowledge
    creatures=[a for a in engine.state.actors.values() if a.active and engine.grid.distance_ft(ctx.actor.position,a.position)<=60 and knowledge(engine,ctx.actor,a) is not None]
    effects=[s for s in information.sources(engine) if set(s['tags']) & {'illusion','possession','spirit_manifestation','concealment','invisible'}
             and engine.grid.distance_ft(ctx.actor.position,s['position'])<=60
             and not any(c.data.get('source_instance')==s['id'] and c.data.get('revision')==s['revision'] for c in scene_grants(engine,ctx.actor,'failed_revelation'))]
    effect_options={effect_option(engine,ctx.actor,s):s for s in effects}
    options=[a.entity_id for a in creatures]+list(effect_options)
    if not options: return
    labels={a.entity_id:a.display_name for a in creatures}
    labels.update({key:'An active supernatural effect' for key in effect_options})
    # The source menu exposes no concealed effect nature or exact position.
    automatic=[a.entity_id for a in creatures if located(engine,ctx.actor,a)]
    picked=choose(ctx,'reveal_target',options,labels,automatic_options=automatic)
    if not picked: return
    target=engine.state.actors.get(picked[0])
    if target:
        from .spirit_traditions import save,context
        failed=save(context(engine,ctx.actor,ctx.action,[target],ctx.numbers,ctx.intent),target,'cha')
        put(ctx,target,'marked',expires=UNTIL if failed else 'END_OF_CURRENT_TURN')
    else:
        source=effect_options[picked[0]]
        if source['dc'] is None:raise ValueError('Record this effect’s actual source save DC before using Revealing Tone on it')
        from .ability_source import cultivation_check
        if cultivation_check(engine,ctx.actor,ctx.numbers,source['dc'],ctx.source,'Revealing Tone Cultivation Check'):
            # Resonance is intentionally visible/audible to ordinary observers.
            holder=engine.state.actors.get(source['holder_id'])
            if holder: put(ctx,holder,'resonance',{'source_instance':source['id']})
            information.publish(engine,ctx.actor,ctx.source,ctx.actor,'resonance',
                {'text':'An active supernatural effect is producing visible or audible resonance.'},UNTIL)
        else:
            information.publish(engine,ctx.actor,ctx.source,ctx.actor,'concealment_exists',{},'UNTIL_REMOVED')
            put(ctx,ctx.actor,'failed_revelation',{'source_instance':source['id'],'revision':source['revision'],'scene':scene_id(engine,ctx.actor)},'UNTIL_REMOVED')


def cleansing(ctx,target,until_scene=True):
    engine=ctx.engine
    candidates=[s for s in information.sources(engine) if s['holder_id']==target.entity_id
                and set(s['tags']) & {'charmed','frightened','deafened','illusion','possession','temporary_corruption'}
                and s['cl'] is not None and not s['profile'].get('permanent') and s['profile'].get('authority','ordinary')=='ordinary'
                and not (s['profile'].get('full_control') and 'possession' in s['tags'])]
    if not candidates: return
    ids=[s['id'] for s in candidates]
    picked=choose(ctx,'purify_'+target.entity_id,ids,{s['id']:', '.join(s['tags']).replace('_',' ') for s in candidates},subject=target)
    if not picked:return
    s=next(s for s in candidates if s['id']==picked[0])
    if 'temporary_corruption' in s['tags']:
        if s['cl']<=int(ctx.numbers['cl']):
            put(ctx,target,'corruption_suppressed',{'source_instance':s['id'],'points':1,
                **({'scene':scene_id(engine,ctx.actor)} if until_scene else {})},'UNTIL_REMOVED' if until_scene else UNTIL)
        return
    if s['cl']<=int(ctx.numbers['cl']): remove(engine,target,s['condition'],'PURIFIED')
    elif s['save_ability'] and s['dc'] is not None:
        roll=engine._roll_save(target,s['save_ability'].upper(),s['dc'],s['source'],extra_mode='ADVANTAGE')
        if roll.total>=s['dc']: remove(engine,target,s['condition'],'REPEATED_SAVE')


def judgment(ctx,targets,dice):
    from .creature_kinds import matches
    from ..relations import relation,ENEMY
    from .spirit_traditions import save,context
    dtype=choose(ctx,'damage_type',['radiant','thunder'])[0]
    for target in targets:
        if relation(ctx.engine,ctx.actor,target)!=ENEMY or not matches(target,QUALIFY): continue
        sub=context(ctx.engine,ctx.actor,ctx.action,[target],ctx.numbers,ctx.intent)
        damage={'type':'damage','applies_to':'target','dice':{'count':dice,'sides':8},'damage_types':[dtype]}
        fail=[damage,{'type':'reaction_denied','applies_to':'target','duration':{'kind':'until_start_of_next_turn'}}]
        save(sub,target,'cha',on_fail=fail,on_success=[{'type':'half_damage'}])
        put(ctx,target,'cannot_possess',expires=expiry(target))


def purify(ctx):
    center=origin(ctx)
    for target in select(ctx,'allies_to_purify',allies(ctx,center,20)): cleansing(ctx,target)
    targets=[a for a in ctx.engine.state.actors.values() if a.active and ctx.engine.grid.distance_ft(center,a.position)<=20]
    judgment(ctx,targets,5)


def anchor_live(engine,zone):
    from ..typed_executor import in_area
    obj=engine.state.objects.get(placed.data(zone).get('anchor_id'))
    if not obj or obj.destroyed or obj.suppressed or not obj.current_hp:return False
    point=obj.position
    if (obj.component or {}).get('bell_armament'):
        from .qi_path import armament_condition,armament_point
        owner=engine.state.actors[zone.owner_id]
        if armament_condition(owner) is None:return False
        x,y=armament_point(owner)
        point=point.model_copy(update={'x':x,'y':y})
    return in_area(engine,zone.center,zone.center,point,{'shape':'cylinder','size_ft':30,'height_ft':30})


def field_inside(engine,actor,zone):
    from ..zones import actor_inside_zone
    return engine._on_battlefield(actor) and zone.active and (placed.data(zone).get('tag')!=FORM_TAG or anchor_live(engine,zone)) and actor_inside_zone(engine,actor,zone)


def field_holds(engine,zone,position):
    """Whether a point (an effect's own position, not a creature) is inside the field's printed area."""
    from ..typed_executor import in_area
    profile=zone.trigger_profile
    shape={'shape':profile.get('shape') or 'cylinder','size_ft':int(profile.get('size_ft') or 30)}
    if profile.get('height_ft'):shape['height_ft']=int(profile['height_ft'])
    return in_area(engine,zone.center,zone.center,position,shape)


def fields(engine,actor,tag=None):
    return [z for z in placed.of(engine,tag) if placed.data(z).get('tag') in {FORM_TAG,NINE_TAG}
            and actor.entity_id in placed.data(z).get('chosen',[]) and field_inside(engine,actor,z)]


def formation(ctx):
    from .qi_path import armament_condition,armament_point
    from ..gate2_runtime_models import Position
    configuration=choose(ctx,'configuration',['exorcist','purification','revealing'])[0]
    real=[o for o in ctx.engine.state.objects.values() if not o.destroyed and ctx.engine.grid.distance_ft(ctx.actor.position,o.position)<=60]
    kinds=['projected']+(['real'] if real else [])+(['armament'] if armament_condition(ctx.actor) is not None else [])
    kind=choose(ctx,'anchor_kind',kinds,{'projected':'Create a projected Bell Anchor','real':'Empower an existing real bell','armament':'Use your bound Bell Domain Armament'})[0]
    existing=''
    if kind=='real':
        oid=choose(ctx,'real_bell',[o.object_id for o in real],{o.object_id:str((o.component or {}).get('name') or 'Existing object') for o in real})[0]
        obj=ctx.engine.state.objects[oid]
        from ..fact_consent_admission import admit_choice
        declared=admit_choice(ctx,ctx.actor,ctx.source,'bell_real_focus',obj.object_id,['confirm'],
            labels={'confirm':'Confirm this actual item is a bell, chime, gong, bowl or similar bell focus'},
            prompt='Bell Anchor: confirm the chosen existing item is a legal bell focus. This empowers that one item and creates no duplicate.',
            expires_on='UNTIL_REMOVED')
        if not declared:raise ValueError('An existing Bell Anchor requires a confirmed bell focus')
        point=obj.position;existing=obj.object_id
    elif kind=='armament':
        x,y=armament_point(ctx.actor);point=Position(x=x,y=y)
        if ctx.engine.grid.distance_ft(ctx.actor.position,point)>60:raise ValueError('The Bell Domain Armament is beyond 60 feet')
    else:
        from ..object_placement import destinations
        from .needle import cell_options,position_of
        cells={p:ctx.engine.grid.distance_ft(ctx.actor.position,p) for p in destinations(ctx.engine,ctx.actor,60)}
        opts,labels=cell_options(ctx.engine,ctx.actor,cells,cap=len(cells))
        if not opts:raise ValueError('No legal Bell Anchor location within 60 feet')
        point=position_of(choose(ctx,'anchor_location',opts,labels)[0])
    selected=select(ctx,'protected_allies',allies(ctx,point,99999))
    put(ctx,ctx.actor,'ritual',{'point':point.model_dump(mode='json'),'configuration':configuration,
        'anchor_kind':kind,'existing_object_id':existing,
        'chosen':[a.entity_id for a in selected],'complete_round':ctx.engine.state.round_number+10,
        'numbers':dict(ctx.numbers)},'UNTIL_REMOVED')


def complete_ritual(engine,owner,c):
    from ..gate2_runtime_models import Position,RuntimeObjectState
    point=Position.model_validate(c.data['point']); nums=c.data['numbers']
    for old in placed.of(engine,FORM_TAG,owner_id=owner.entity_id):placed.drop(engine,old,'REPLACED')
    oid=c.data.get('existing_object_id') or f'object:bell_anchor:{owner.entity_id}:{engine.state.event_sequence+1}'
    original=engine.state.objects.get(oid)
    if c.data.get('existing_object_id') and (original is None or original.destroyed):
        remove(engine,owner,c,'BELL_DESTROYED');return
    obj=RuntimeObjectState(object_id=oid,object_kind='bell_anchor',position=point,unattended=True,flammable=False,
        owner_id=owner.entity_id,ac=15,current_hp=4*int(nums['cl']),maximum_hp=4*int(nums['cl']),
        damage_immunities=('POISON','PSYCHIC'),component={'name':'Bell Anchor','size':'medium','source_cl':int(nums['cl']),
        'resist':['BLUDGEONING','PIERCING','SLASHING'],'created_by':c.source_definition_id,
        'bell_armament':int(c.data.get('anchor_kind')=='armament'),
        'save_modifier':int(nums.get('pb') or 2)+int(nums.get('key_mod') or 0),
        'condition_immunities':['charmed','frightened','poisoned','prone'],'speed_ft':0,
        'initiative':'creator','default_action':'Dodge','tether_ft':60})
    if original:
        obj=original.model_copy(update={'object_kind':'bell_anchor','ac':15,'current_hp':4*int(nums['cl']),
            'maximum_hp':4*int(nums['cl']),'damage_immunities':('POISON','PSYCHIC'),
            'component':{**(original.component or {}),**obj.component}})
    if original:
        engine._update_object(obj,c.source_definition_id,owner.entity_id)
    else:
        from ..asset_anchor_runtime import create
        obj=create(engine,owner,c.source_definition_id,{
            'name':'Bell Anchor','kind':'bell_anchor','ac':15,'hp':4*int(nums['cl']),
            'source_cl':int(nums['cl']),'height_ft':5,'group':FORM_TAG,
            'immune':['POISON','PSYCHIC'],'resist':['BLUDGEONING','PIERCING','SLASHING']},
            point,component=dict(obj.component))
        oid=obj.object_id
    placed.place(engine,owner,source=c.source_definition_id,tag=FORM_TAG,cells=(point,),name='Bell-Tower Formation',
        placed={'anchor_id':oid,'chosen':c.data['chosen'],'configuration':c.data['configuration']},
        numbers=nums,duration_rounds=4800,radial_volume=True,shape='cylinder',size_ft=30,extra={'height_ft':30})
    remove(engine,owner,c,'RITUAL_COMPLETED')


def nine(ctx):
    if scene_grants(ctx.engine,ctx.actor,'nine_used'):raise ValueError('Ninefold Heavenly Bell was already used in this scene')
    center=origin(ctx,anchor=True)
    chosen=select(ctx,'protected_allies',allies(ctx,center,99999))
    put(ctx,ctx.actor,'nine_used',{'scene':scene_id(ctx.engine,ctx.actor)},expires='UNTIL_REMOVED')
    z=placed.place(ctx.engine,ctx.actor,source=ctx.source,tag=NINE_TAG,cells=(center,),name='Ninefold Heavenly Bell',
        placed={'chosen':[a.entity_id for a in chosen]},numbers=ctx.numbers,duration_rounds=10,
        concentration=True,radial_volume=True,shape='sphere',size_ft=60)
    from ..gate2_runtime_models import ConcentrationState
    ctx.engine._start_concentration(ctx.actor,ctx.source)
    ctx.actor.concentration.zone_id=z.zone_id


TONES=['iron_vigil','swift_assembly','returning_clarity','closed_gate','heavenly_judgment','great_alarm']


def tones(engine,owner,zone):
    ctx=placed.context(engine,owner,zone.source_definition_id,zone.trigger_profile['numbers'])
    selected=choose(ctx,'two_different_heavenly_tones',TONES,{
        'iron_vigil':'Iron Vigil: up to two allies gain +2 AC until your next turn starts',
        'swift_assembly':'Swift Assembly: up to two allies move 10 feet without provoking',
        'returning_clarity':'Returning Clarity: one ally ends a lower/equal-CL effect, repeats a higher save with Advantage, or suppresses one temporary Corruption',
        'closed_gate':'Closed Gate: lower-CL hostile effects cannot teleport into or possess inside the field',
        'heavenly_judgment':'Heavenly Judgment: up to your Proficiency Bonus in qualifying enemies save against 4d8 Radiant or Thunder damage',
        'great_alarm':'Great Alarm: up to two allies gain Advantage on their next attack or save and twice your Proficiency Bonus in Temporary HP'},maximum=2,minimum=2)
    roster=[a for a in engine.state.actors.values() if a.entity_id in placed.data(zone)['chosen'] and field_inside(engine,a,zone)]
    for tone in selected:
        if tone=='closed_gate':
            put(ctx,owner,'closed_gate',{'zone_id':zone.zone_id});continue
        if tone=='heavenly_judgment':
            from .creature_kinds import matches
            from ..relations import relation,ENEMY
            foes=[a for a in engine.state.actors.values() if field_inside(engine,a,zone) and relation(engine,owner,a)==ENEMY and matches(a,QUALIFY)]
            chosen=select(ctx,tone,foes,maximum=int(ctx.numbers.get('pb') or 2))
            judgment(ctx,chosen,4);continue
        chosen=select(ctx,tone,roster,maximum=1 if tone=='returning_clarity' else 2)
        for target in chosen:
            if tone=='iron_vigil':run(ctx,target,[{'type':'ac_bonus','applies_to':'target','amount':2,'duration':{'kind':'until_start_of_your_next_turn'}}])
            elif tone=='swift_assembly':step(ctx,target,10)
            elif tone=='returning_clarity':cleansing(ctx,target,until_scene=False)
            elif tone=='great_alarm':
                put(ctx,target,'great_alarm')
                run(ctx,target,[{'type':'temp_hp','applies_to':'target','flat':2*int(ctx.numbers.get('pb') or 2)}])


def step(ctx,target,feet):
    from .granted_movement import choices,move
    from .needle import cell_id,position_of
    paths=choices(ctx.engine,target,feet)
    opts=[cell_id(p.destination) for p in paths]
    if not opts:return
    # Mover owns its voluntary response, including when the caster is AI.
    from .rider_choices import pick
    picked=pick(ctx.engine,target,'bell_step','Bell movement',opts,subject=target,optional=True,
        labels={cell_id(p.destination):f'Move {target.display_name} to ({p.destination.x}, {p.destination.y}) without provoking' for p in paths},intent=ctx.intent)
    if picked:
        path=next(p for p in paths if p.destination==position_of(picked[0]))
        move(ctx.engine,target,path,ctx.intent,feet,list(ctx.engine.state.actors),name='Bell movement')


@hook('turn_start_choice')
def start_tones(engine,owner):
    for z in placed.of(engine,NINE_TAG,owner_id=owner.entity_id):tones(engine,owner,z)


@hook('turn_start')
def finish_rituals(engine,actor):
    for c in list(held(actor,'ritual')):
        if not conscious(engine,actor):remove(engine,actor,c,'INTERRUPTED')
        elif engine.state.round_number>=c.data['complete_round']:complete_ritual(engine,actor,c)


@hook('candidate_allowed')
def admission(engine,actor,candidate,action):
    f=((action.parameters.get('typed') or {}).get('source')) if action else None
    if held(actor,'ritual') and action is not None and str(action.economy.value)=='ACTION':return False
    if f in LEVELS:
        return owned(engine,actor,f) and (f!=NINE or not scene_grants(engine,actor,'nine_used'))
    return None


@hook('save')
def bell_save(ctx,subject,ability,named):
    tags={str(t).removeprefix('condition:typed.').removeprefix('category:') for t in (named or [])}
    clarity=held(subject,'clarity') if tags & {'charmed','frightened','illusion','supernatural_disorientation'} else []
    alarm=held(subject,'great_alarm')
    if clarity or alarm:
        return {'bonus':0,'modes':['ADVANTAGE']}
    for z in fields(ctx.engine,subject):
        allowed=MENTAL if placed.data(z)['tag']==NINE_TAG else {'illusion','frightened','possession'}
        if tags & allowed:return {'bonus':0,'modes':['ADVANTAGE']}


@hook('masked_conditions')
def marked_visibility(engine,viewer,target):
    if owned(engine,viewer,WATCH) and held(target,'marked',viewer):return {target.entity_id:{iid for iid,c in target.conditions.items() if c.condition_id in {'condition:typed.invisible','condition:typed.hidden'}}}
    return None


@hook('zone_obscuration_ignored')
def marked_concealment(engine,zone,viewer,target):
    from ..senses import is_creature
    from .darkness_scope import scope
    if not (is_creature(viewer) and is_creature(target) and owned(engine,viewer,WATCH)
            and held(target,'marked',viewer)):return None
    tier=scope(engine,zone)
    visual=zone.trigger_profile.get('visual') or {}
    if tier=='superior':return None
    # The printed darkness exception includes normal magical darkness. Ordinary
    # concealment and explicitly classified visual Illusions also cannot be
    # the sole concealment. This hook never bypasses native physical sight.
    if visual.get('darkness') or tier=='ordinary':return True
    profile=information.source_profile(engine,zone.source_definition_id,zone.trigger_profile)
    if 'visual_illusion' in profile.get('tags',()) and profile.get('authority')=='ordinary':return True
    return None


@hook('condition_application_attempt')
def no_surprise(engine,subject,condition_id,source,owner_id):
    if condition_id=='condition:typed.surprised' and ((owned(engine,subject,ALARM) and conscious(engine,subject)) or fields(engine,subject)):
        return False
    source_actor=engine.state.actors.get(owner_id)
    if 'possession' in condition_id and source_actor and held(source_actor,'cannot_possess'):return False
    return None


@hook('initiative_modes')
def alarm_initiative(engine,actor):
    bundle=next((b for b in engine.typed_bundle_documents if b.get('actor_id')==actor.entity_id),{})
    snapshot=(bundle.get('journey_setup') or {}).get('encounter_snapshot') or {}
    if snapshot.get('current_hp',1)<=0 or snapshot.get('life_state') in {'DYING','STABLE','DEAD'}:return None
    import json
    if any(json.loads(row).get('condition_id') in {'unconscious','condition:typed.unconscious'}
            for row in snapshot.get('conditions',{}).values()):return None
    # Incapacitated alone does not establish unconsciousness. The native flag
    # still disables actions/reactions after setup; it does not remove this
    # explicitly consciousness-gated Initiative benefit.
    if owned(engine,actor,ALARM) and conscious(engine,actor):
        return {'advantage':True,'ignore_surprise_disadvantage':True}
    return None


def reaction_context(engine,owner,feature):
    from .spirit_traditions import context,feature_action
    return context(engine,owner,feature_action(engine,owner,feature),[],numbers(engine,owner),getattr(engine,'_active_intent',None))


@hook('choice_reactors')
def bell_choice_owners(engine):
    # Alarm is a passive with no action row. It still offers the responding
    # creature its benefit on an AI mover's turn through the native probe.
    if not any(owned(engine,a,ALARM) for a in engine.state.actors.values()):return None
    from ..tabletop_service import MANUAL_MODES
    return tuple(sorted(aid for aid,mode in (getattr(engine,'typed_control_modes',None) or {}).items()
        if mode in MANUAL_MODES and aid in engine.state.actors))


def use_reaction(ctx,feature,cost):
    from ..typed_reactions import publish_reaction_used,spend_reaction
    if cost:ctx.engine._spend_resource(ctx.actor,QI,cost,feature)
    spend_reaction(ctx.engine,ctx.actor,{'feature_id':feature})
    ctx.engine._append_event('REACTION_RESOLVED',feature,actor_id=ctx.actor.entity_id,payload={'checkpoint':'BELL_INTRUSION'})
    publish_reaction_used(ctx.engine,ctx.actor,{'feature_id':feature,'name':'Ring the Alarm' if feature==ALARM else 'Answer the Intrusion'})


def alarm_response(engine,owner,mover):
    from ..typed_reactions import can_react
    if not can_react(engine,owner):return
    from ..target_knowledge import located
    from ..relations import relation,ALLY,ENEMY
    if not (owned(engine,owner,ALARM) and conscious(engine,owner) and owner.reaction_available
            and owner.resources.get(QI,0)>=2 and relation(engine,owner,mover)==ENEMY and located(engine,owner,mover)):
        return
    if round_grants(engine,owner,'alarm_used'):return
    perceivable=[a for a in engine.state.actors.values() if relation(engine,owner,a)==ALLY and (a is owner or located(engine,owner,a))]
    if not any(engine._distance_actor_to_actor(mover,a)<=30 for a in perceivable):return
    ctx=reaction_context(engine,owner,ALARM)
    if not choose(ctx,'ring_alarm',['ring'],{'ring':f'Ring the Alarm for {mover.display_name}: spend your Reaction and 2 Qi'},optional=True):return
    targets=select(ctx,'alarm_recipient',allies(ctx,owner.position,60),maximum=1,hearing=True)
    if not targets:return
    target=targets[0]
    choices=['move','temp_hp','draw','stow','stand','armament','perception']
    from .rider_choices import pick
    use_reaction(ctx,ALARM,2)
    put(ctx,owner,'alarm_used',{'round':engine.state.round_number,'scene':scene_id(engine,owner),'encounter':engine.state.match_id},'UNTIL_REMOVED')
    result=pick(engine,target,'bell_alarm_benefit','Ring the Alarm',choices,subject=target,
        optional=True,intent=ctx.intent,labels={'move':f'{target.display_name} may move 5 feet without provoking',
        'temp_hp':f'{target.display_name} gains {int(ctx.numbers.get("pb") or 2)} Temporary Hit Points',
        'draw':'Draw one weapon, shield or implement','stow':'Stow one weapon, shield or implement',
        'stand':'Stand from Prone','armament':'Move the chosen creature’s Domain Armament 10 feet',
        'perception':'Advantage on the next Perception check before its next turn'})
    if not result:return
    benefit=result[0]
    if benefit=='move':step(ctx,target,5)
    elif benefit=='temp_hp':run(ctx,target,[{'type':'temp_hp','applies_to':'target','flat':int(ctx.numbers.get('pb') or 2)}])
    elif benefit=='stand':
        from ..posture import stand_up
        stand_up(engine,target,source_id=ALARM,cost=0,ignore_speed=True)
    elif benefit=='perception':put(ctx,target,'perception',{'rule':{'check_mode':{'Perception':'ADVANTAGE'}}},expires=expiry(target))
    elif benefit=='armament':
        from .devil_heart_second_furnace import move_armament_choice
        from .spirit_traditions import context
        sub=context(engine,target,ctx.action,[],numbers(engine,target),ctx.intent)
        move_armament_choice(sub,target,10,feature_id=ALARM,name='Ring the Alarm')
    else:
        # Use the same item/hand path as ordinary native draw/stow actions.
        interact_alarm(ctx,target,benefit)


def interact_alarm(ctx,target,kind):
    """Choose one actual carried weapon, Shield or confirmed implement."""
    from .rider_choices import pick
    from .equipment_hands import require_free_hands
    from .shield_training import equipment_mode,equip_allowed
    from .. import carry
    from .hand_occupancy import free_hands
    from factory_authoring.starting_kits import item_definition
    from ..typed_executor import run_effects
    from .spirit_traditions import context
    candidates=[]
    for a in ctx.engine.action_catalog.values():
        if a.owner_id!=target.entity_id:continue
        grip=a.parameters.get('equipment_grip')
        if grip and grip.get('held')==(1 if kind=='draw' else 0) and require_free_hands(ctx.engine,target,None,a) is True:
            candidates.append(a)
        if equipment_mode(a)==('don' if kind=='draw' else 'doff') and equip_allowed(ctx.engine,target,None,a) is True:
            candidates.append(a)
    carrying=carry.carrying_of(ctx.engine,target.entity_id) or {}
    implements=[i for i in carrying.get('items',[]) if not i.get('weapon_action')
                and (item_definition(str(i.get('item_id') or '')) or {}).get('armor_category')!='shield' and carry.holds(ctx.engine,target,i['key'])
                and ((kind=='stow' and (carry.owned_item_location(target,i['key']) or '').startswith('hand:'))
                     or (kind=='draw' and free_hands(ctx.engine,target)
                         and not (carry.owned_item_location(target,i['key']) or '').startswith('hand:')))]
    labels={a.source_definition_id:a.display_name for a in candidates}
    labels.update({'item:'+i['key']:f"{kind.title()} {i.get('name') or 'carried item'} as an implement" for i in implements})
    if not labels:return
    chosen=pick(ctx.engine,target,'bell_'+kind,'Ring the Alarm',list(labels),subject=target,
        labels=labels,intent=ctx.intent,optional=True)
    if not chosen:return
    if chosen[0].startswith('item:'):
        item=next(i for i in implements if 'item:'+i['key']==chosen[0])
        from ..fact_consent_admission import admit_choice
        confirmed=admit_choice(ctx,target,ctx.source,'bell_implement_fact',item['key'],['confirm'],
            labels={'confirm':'Confirm this actual carried item is an implement'},
            prompt='Ring the Alarm: confirm this real item is a weapon, shield or cultivation implement. An unrelated carried item does not qualify.',
            expires_on='UNTIL_REMOVED')
        if not confirmed:return
        carry.clear_owned_item_location(ctx.engine,target,item['key'],ctx.source)
        location='carried' if kind=='stow' else 'hand:'+free_hands(ctx.engine,target)[0]
        put(ctx,target,'implement',{'item_key':item['key'],'held_by':target.entity_id,
            'object_location':location,'label':str(item.get('name') or 'Implement')},'UNTIL_REMOVED')
        return
    a=next(a for a in candidates if a.source_definition_id==chosen[0])
    granted=a.model_copy(update={'source_definition_id':ctx.source})
    run_effects(context(ctx.engine,target,granted,[target],numbers(ctx.engine,target),ctx.intent),
        (a.parameters.get('typed') or {})['effects'])


def intrusion(engine,owner,mover,zone):
    from ..typed_reactions import can_react
    if not can_react(engine,owner):return
    if not owner.reaction_available or round_grants(engine,owner,'intrusion_used'):return
    from ..relations import relation,ENEMY
    if relation(engine,owner,mover)!=ENEMY:return
    ctx=reaction_context(engine,owner,FORM)
    result=choose(ctx,'answer_intrusion',['ally','armament'],{'ally':'Use your Reaction: move one ally inside 10 feet without provoking',
        'armament':'Use your Reaction: move your Bell Domain Armament 20 feet'},optional=True)
    if not result:return
    use_reaction(ctx,FORM,0)
    put(ctx,owner,'intrusion_used',{'round':engine.state.round_number,'scene':scene_id(engine,owner),'encounter':engine.state.match_id},'UNTIL_REMOVED')
    if result[0]=='ally':
        roster=[a for a in allies(ctx,zone.center,30) if field_inside(engine,a,zone)]
        for target in select(ctx,'intrusion_ally',roster,maximum=1):step(ctx,target,10)
    else:
        from .devil_heart_second_furnace import move_armament_choice
        move_armament_choice(ctx,owner,20,feature_id=FORM,name='Answer the Intrusion')


def tower_event(engine,subject,event_type,previous=None):
    from ..relations import relation,ALLY,ENEMY
    from ..target_knowledge import located
    for zone in placed.of(engine,FORM_TAG):
        if not anchor_live(engine,zone) or not field_inside(engine,subject,zone):continue
        if event_type in {'enters','teleports_in'} and previous is not None:
            prior=subject.model_copy(update={'position':previous})
            if field_inside(engine,prior,zone):continue
        owner=engine.state.actors[zone.owner_id]
        allegiance=relation(engine,owner,subject) if located(engine,owner,subject) else None
        details={'event_type':event_type,'direction':information.direction(zone.center,subject.position),
                 'allegiance':'friendly' if allegiance==ALLY else 'hostile' if allegiance==ENEMY else 'unidentified'}
        information.publish(engine,owner,zone.source_definition_id,owner,'field_event',details,'UNTIL_REMOVED')
        if event_type in {'enters','teleports_in'}:intrusion(engine,owner,subject,zone)


@hook('movement_step_settled')
@hook('forced_movement_step')
def bell_movement(engine,mover,previous,destination,intent):
    tower_event(engine,mover,'enters',previous)
    for owner in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):alarm_response(engine,owner,mover)


@hook('teleport_settled')
def bell_teleport(ctx,subject,previous,destination,unwilling):
    tower_event(ctx.engine,subject,'teleports_in',previous)
    for owner in sorted(ctx.engine.state.actors.values(),key=lambda a:a.entity_id):alarm_response(ctx.engine,owner,subject)


@hook('state_event')
def bell_events(engine,event):
    if event.event_type=='CONDITION_APPLIED':
        cid=event.payload.get('condition_id','')
        for tid in event.target_ids:
            subject=engine.state.actors.get(tid)
            if subject and cid=='condition:typed.invisible':tower_event(engine,subject,'becomes_invisible')
            elif subject and 'possession' in cid:tower_event(engine,subject,'begins_possession')
    if event.event_type in {'OBJECT_UPDATED','ROUND_STARTED'}:
        for z in list(placed.of(engine,FORM_TAG)):
            obj=engine.state.objects.get(placed.data(z).get('anchor_id'))
            if not obj or obj.destroyed or obj.current_hp==0 or (not obj.suppressed and not anchor_live(engine,z)):placed.drop(engine,z,'ANCHOR_REMOVED')
    if event.event_type=='ATTACK_ROLLED':
        attacker=engine.state.actors.get(event.actor_id)
        if attacker:
            for c in held(attacker,'great_alarm'):remove(engine,attacker,c)
        for tid in event.target_ids:
            target=engine.state.actors.get(tid)
            if not target:continue
            for c in held(target,'guarding'):remove(engine,target,c)


@hook('technique_start')
def audible_intrusion(engine,actor,action):
    from ..speech import needs_voice
    typed=action.parameters.get('typed') or {}
    if needs_voice(action) or typed.get('audible') or typed.get('bell_audible') or typed.get('source') in LEVELS:
        tower_event(engine,actor,'audible_technique')


@hook('attack_roll_modes')
def great_alarm_attack(engine,attacker,target):
    return ['ADVANTAGE'] if held(attacker,'great_alarm') else None


@hook('ability_check_mode')
def bell_perception(engine,actor,ability,skill,against):
    if str(skill).lower()=='perception':
        if held(actor,'perception'):return 'ADVANTAGE'
        if str(against or '').lower()=='hearing' and fields(engine,actor,FORM_TAG):return 'ADVANTAGE'
    return None


@hook('condition_attempt')
def closed_gate_possession(ctx,subject,row):
    if row.get('condition') not in {'possession','possessed','possessing'}:return None
    if held(ctx.actor,'cannot_possess'):return False
    from ..relations import relation,ENEMY
    for zone in fields(ctx.engine,subject,NINE_TAG):
        owner=ctx.engine.state.actors[zone.owner_id]
        if held(owner,'closed_gate') and relation(ctx.engine,owner,ctx.actor)==ENEMY and int(ctx.numbers.get('cl') or 1)<int(zone.trigger_profile['numbers']['cl']):return False
    return None


@hook('teleport_gate')
def closed_gate_transport(ctx,start,destination):
    from ..relations import relation,ENEMY
    for zone in placed.of(ctx.engine,NINE_TAG):
        owner=ctx.engine.state.actors[zone.owner_id]
        projected=ctx.actor.model_copy(update={'position':destination})
        if (held(owner,'closed_gate') and relation(ctx.engine,owner,ctx.actor)==ENEMY
                and field_inside(ctx.engine,projected,zone) and not field_inside(ctx.engine,ctx.actor,zone)
                and int(ctx.numbers.get('cl') or 1)<int(zone.trigger_profile['numbers']['cl'])):return False
    return None


@hook('object_damage_defenses')
def anchor_resistance(engine,actor,obj,packets,source):
    if obj.object_kind=='bell_anchor' and obj.component and obj.component.get('created_by') in engine.action_catalog:
        return [{'kind':'resistance','damage_types':['BLUDGEONING','PIERCING','SLASHING']}]
    return None


@hook('observer_information_rows')
def private_directions(engine,viewer):
    """What this viewer's own bell pays it: Bell-Marked directions, and a Protected Watch's traces."""
    rows=[]
    for target in engine.state.actors.values():
        if (owned(engine,viewer,WATCH) and held(target,'marked',viewer) and engine._on_battlefield(viewer) and engine._on_battlefield(target)
                and engine._distance_actor_to_actor(viewer,target)<=120):
            rows.append({'kind':'direction','source_id':WATCH,'viewer_id':viewer.entity_id,
                'details':{'direction':information.direction(viewer.position,target.position)}})
    rows.extend(protected_watch_traces(engine,viewer))
    return rows or None


def protected_watch_traces(engine,viewer):
    """Protected Watch: a chosen ally inside the Formation sees traces around lower-CL visual Illusions.

    The Illusion is the actual native source (combat/observer_information.sources), classified by
    its own authored profile: a figment becomes visual only through an explicit sight channel, and
    the printed CL it is compared against is the source's, never the field's. Spirits and
    possessing entities reach the same ally through this plug-in's outline masking. The trace
    names the effect's position because that is what is seen; it never names the effect, its
    controller or its save DC.
    """
    if not owned(engine,viewer,FORM):return []
    rows=[]
    for zone in fields(engine,viewer,FORM_TAG):
        field_cl=int(zone.trigger_profile['numbers'].get('cl') or 0)
        for source in information.sources(engine):
            if 'visual_illusion' not in source['tags'] or source['cl'] is None or source['cl']>=field_cl:continue
            position=source['position']
            if not field_holds(engine,zone,position):continue
            rows.append({'kind':'resonance','source_id':FORM,'viewer_id':viewer.entity_id,
                'details':{'text':'A visual Illusion leaves a flickering trace here.',
                           'position':{'x':position.x,'y':position.y,'z':position.z}}})
    return rows


@hook('presentation_hidden_conditions')
def private_revelation_locks(engine,actor):
    return [c.instance_id for c in held(actor,'failed_revelation')]


@hook('save_mode')
def native_bell_save(engine,actor,ability,dc,source,metadata):
    tags={str(t).removeprefix('condition:typed.').removeprefix('category:') for t in (metadata.get('named') or [])}
    if held(actor,'great_alarm') or (held(actor,'clarity') and tags & (MENTAL-{'possession'})):
        return 'ADVANTAGE'
    for zone in fields(engine,actor):
        allowed=MENTAL if placed.data(zone)['tag']==NINE_TAG else {'illusion','frightened','possession'}
        if tags & allowed:return 'ADVANTAGE'
    return None


@hook('after_save_resolved')
def spend_bell_save(ctx,subject,ability,named,failed):
    tags={str(t).removeprefix('condition:typed.').removeprefix('category:') for t in (named or [])}
    grants=held(subject,'great_alarm')
    if tags & (MENTAL-{'possession'}):grants+=held(subject,'clarity')
    for c in grants:remove(ctx.engine,subject,c)


@hook('masked_conditions')
def outlines(engine,viewer,target):
    from .creature_kinds import matches
    if not hasattr(target,'creature_types') or not matches(target,{'spirit','hostile spirit','possessing entity'}):return None
    for z in fields(engine,viewer):
        target_cl=information.source_numbers(engine,'',target.entity_id).get('cl')
        if (field_inside(engine,target,z) and (placed.data(z)['tag']==NINE_TAG
                or (target_cl is not None and target_cl<int(z.trigger_profile['numbers']['cl'])) )):
            return {target.entity_id:{iid for iid,c in target.conditions.items() if c.condition_id in {'condition:typed.invisible','condition:typed.hidden'}}}
    return None


@hook('sound_path_allowed')
def bell_through_silence(engine,speaker,listener,source):
    """Ninefold Heavenly Bell: a chosen ally inside the field hears your bell through ordinary Silence.

    The grant is the printed field's, and it names one sound: a Bell-Tower feature's own bell. A
    deafness or obstruction no Silence field accounts for still stops it, and no other speaker,
    listener or technique gains anything (speech.can_hear_from combines providers).
    """
    if not owned(engine,speaker,NINE) or not bell_sound(engine,source):return None
    return True if any(z.owner_id==speaker.entity_id for z in fields(engine,listener,NINE_TAG)) else None


def bell_sound(engine,source):
    """Whether a sound is this Bell-Tower's bell rather than some other technique in the field."""
    from .source_eligibility import catalog_action
    action=catalog_action(engine,source)
    typed=(action.parameters.get('typed') or {}) if action is not None else {}
    return (typed.get('source') or source) in LEVELS


@hook('ability_check_hazard_mode')
def protected_hearing(engine,actor,ability,skill,against,hazards):
    if str(skill).lower()=='perception' and 'hearing' in hazards and fields(engine,actor,FORM_TAG):return 'ADVANTAGE'
    return None


@hook('state_event')
def consumed_native_roll_grants(engine,event):
    actor=engine.state.actors.get(event.actor_id)
    if not actor:return
    if event.event_type=='CHECK_ROLLED' and str(event.payload.get('skill') or '').lower()=='perception':
        for c in held(actor,'perception'):remove(engine,actor,c)
    if event.event_type=='SAVE_ROLLED':
        metadata=engine.d20_context() or {}
        tags={str(t).removeprefix('condition:typed.').removeprefix('category:') for t in (metadata.get('named') or [])}
        for c in held(actor,'great_alarm')+(held(actor,'clarity') if tags & (MENTAL-{'possession'}) else []):remove(engine,actor,c)


@hook('hand_occupants')
def bell_held_implement(engine,actor):
    from ..carry import holds
    out={}
    for c in held(actor,'implement'):
        data=c.data
        if str(data.get('object_location') or '').startswith('hand:') and holds(engine,actor,data['item_key']):
            out[data['object_location'].removeprefix('hand:')]='implement:'+data['item_key']
    return out or None


# Guarding's AC belongs to the whole one attack, including rewrites and defense
# recalculations. Native attack-only defenses suspend parent modifiers during a
# nested strike. Only the committed roll consumes the persisted next-attack grant.
from contextlib import contextmanager
from contextvars import ContextVar
_GUARD_FRAMES=ContextVar('bell_guard_attack_frames',default=())


@hook('attack_resolution_scope')
def guarding_attack_scope(engine,attacker,target,spec,intent):
    grants=[c for c in held(target,'guarding') if (owner:=engine.state.actors.get(c.source_actor_id)) is not None
            and owned(engine,owner,WATCH)]
    if not grants and not any(e is engine for e in _GUARD_FRAMES.get()):return None
    @contextmanager
    def scope():
        from .attack_defenses import grant,resolving_defenses
        original=list(spec.get('attack_only_ac') or [])
        token=_GUARD_FRAMES.set((*_GUARD_FRAMES.get(),engine))
        if grants:grant(spec,target,grants[0].source_definition_id,2)
        try:
            with resolving_defenses(engine,spec):
                try:yield
                finally:
                    if original:spec['attack_only_ac']=original
                    else:spec.pop('attack_only_ac',None)
        finally:_GUARD_FRAMES.reset(token)
    return scope()
