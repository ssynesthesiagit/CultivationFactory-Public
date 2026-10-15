"""Adorn's three presentations, single qualifying check and witnessed memory.

A journey scene ends only at its explicit owner-authorized boundary. Standalone
encounters use their native scene identity.
Witnesses are collected only at actual activation/committed events using sight;
remembering does not grant sight, identity, or teammate knowledge.
"""
from copy import deepcopy
from . import hook,effect
from .ability_source import mechanic_of
SOURCE='BEAUTY_BASE_ADORN_THE_MOMENT'
PRESENT='condition:typed.adorn_presentation'
MEMORY='condition:typed.adorn_memory'
USED='condition:typed.adorn_scene_used'
CHECKS={'Performance':'CHA','Persuasion':'CHA','Acrobatics':'DEX','Insight':'WIS'}
PURPOSES={x:x.replace('_',' ').capitalize() for x in ('grace','poise','first_impressions','etiquette','dance','beauty','emotional_presentation','other')}
AURAS=('soft','graceful','haunting','radiant','refined','tragic','elegant','terrible')


def scene_identity(engine,actor):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    return bundle.get('scoped_scene_id') or engine.state.match_seed


@hook('journey_combat_setup')
def scene_snapshot(bundle,session,aid):
    actor=session.state['actors'][aid]
    from .scoped_information_scene import owns
    if not actor.get('adorn_used_scene') and not any(owns(session,owner,SOURCE) for owner in session.state['actors']):return None
    return {**bundle,'scoped_scene_id':session.state.get('scene_id',session.state['journey_id']),
        'adorn_used_scene':actor.get('adorn_used_scene','')}


@hook('journey_encounter_settled')
def scene_settled(session,aid,engine,creature):
    used=next((c for c in creature.conditions.values() if c.condition_id==USED and c.data.get('scene')==scene_identity(engine,creature)),None)
    if used:session.state['actors'][aid]['adorn_used_scene']=used.data['scene']



@hook('compile_action')
def adorn_compile(action,info):
    if SOURCE not in info['owned_ids'] or mechanic_of(action)!=SOURCE or action.parameters.get('adorn_object'):return None
    t=deepcopy(action.parameters['typed']); label=t.get('option_label','')
    if label not in ('Advantage on Check','Visually Memorable'):return None
    kind='check' if label=='Advantage on Check' else 'memory'
    t.update(effects=[{'type':'choose_willing','target_only':True,'allow_hostile_target':True,'range_ft':5,
        'effects':[{'type':'adorn_presentation','kind':kind,'applies_to':'target'}]}],riders=[])
    shared=bool(action.parameters.get('shared_spotlight'))
    if shared:
        t['effects'][0]['range_ft']=30
        t['effects'].append({'type':'adorn_presentation','kind':kind,'applies_to':'self'})
    return action.model_copy(update={'target_kind':action.target_kind if shared else 'ANY_CREATURE','range_ft':30 if shared else 5,'parameters':{**action.parameters,'typed':t}})


@hook('compile_actions')
def adorn_actions(info):
    if SOURCE not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    from .source_checks import check_action
    actions=[]
    for aura in AURAS:
        actions.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.adorn.aura.{aura}",display_name='Adorn the Moment: '+aura,
            owner_id=info['actor_id'],economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',target_kind='ANY_CREATURE',range_ft=5,
            parameters={'description':f'Bonus Action, no CP: give a willing creature within touch a {aura} aura for one minute. No direct combat effect.',
                'typed':{'source':SOURCE,'numbers':dict(info['numbers']),'riders':[],
                    'effects':[{'type':'choose_willing','target_only':True,'allow_hostile_target':True,'range_ft':5,
                        'effects':[{'type':'adorn_presentation','kind':'aura','aura':aura,'applies_to':'target'}]}]}}))
    return actions


@effect('adorn_presentation',harmful=False)
def adorn(ctx,row):
    from ..typed_executor import effect_subjects
    from .effect_durations import round_token
    from .condition_ownership import remove_instance
    for target in effect_subjects(ctx,row,harmful=False):
        if row['kind']=='check' and any(c.condition_id==USED and c.data.get('scene',scene_identity(ctx.engine,target))==scene_identity(ctx.engine,target) for c in target.conditions.values()):continue
        for iid,c in list(target.conditions.items()):
            if c.condition_id==PRESENT and not c.data.get('object_subject'):remove_instance(ctx.engine,target,iid,ctx.source)
        ctx.engine._apply_condition(target,PRESENT,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,10),
            data={'kind':row['kind'],'aura':row.get('aura',''),'label':'Adorn the Moment: '+row.get('aura',row['kind'])})
    witnesses(ctx.engine)


def witnesses(engine):
    from ..target_knowledge import can_see
    from ..senses import perceives_object
    for holder in engine.state.actors.values():
        presentations=[c for c in holder.conditions.values() if c.condition_id==PRESENT and c.data.get('kind')=='memory']
        for c in presentations:
            subject=c.data.get('object_subject') or holder.entity_id
            target=engine.state.objects.get(subject) if c.data.get('object_subject') else holder
            if target is None or getattr(target,'destroyed',False):continue
            for viewer in engine.state.actors.values():
                if not viewer.active or not (perceives_object(engine,viewer,target) if c.data.get('object_subject') else can_see(engine,viewer,target)):continue
                if any(m.condition_id==MEMORY and m.data.get('subject')==subject for m in viewer.conditions.values()):continue
                engine._apply_condition(viewer,MEMORY,c.source_definition_id,c.source_actor_id,expires_on='UNTIL_REMOVED',
                    data={'subject':subject,'label':'Remembers a visually memorable subject'})


@hook('event')
def observed(engine,kind,kwargs):
    if kind in ('MOVEMENT_COMMITTED','ACTION_RESOLVED','TURN_STARTED','CONDITION_REMOVED'):witnesses(engine)
    if kind!='CHECK_ROLLED':return
    from .source_checks import current
    from .condition_ownership import remove_instance
    actor=engine.state.actors.get(kwargs.get('actor_id')); frame=current(engine,actor) if actor else None
    if not frame or frame['skill'] not in CHECKS or frame['purpose'] not in PURPOSES or frame['purpose']=='other':return
    for iid,c in list(actor.conditions.items()):
        if c.condition_id==PRESENT and c.data.get('kind')=='check' and (not c.data.get('object_subject') or c.data['object_subject']==frame['subject']):
            remove_instance(engine,actor,iid,c.source_definition_id)
            if c.data.get('object_subject'):continue
            engine._apply_condition(actor,USED,c.source_definition_id,c.source_actor_id,expires_on='UNTIL_REMOVED',
                data={'scene':scene_identity(engine,actor),'label':'Adorn presentation benefit used this scene'})


@hook('source_check_mode')
def adorn_check(engine,actor,ability,skill,against):
    from .source_checks import current
    frame=current(engine,actor)
    if not frame:return None
    if frame['purpose'] in ('remember','identify') and any(c.condition_id==MEMORY and c.data.get('subject')==frame['subject'] for c in actor.conditions.values()):return 'ADVANTAGE'
    if CHECKS.get(skill)==ability and frame['purpose'] in PURPOSES and frame['purpose']!='other' and any(c.condition_id==PRESENT and c.data.get('kind')=='check' and (not c.data.get('object_subject') or c.data['object_subject']==frame['subject']) for c in actor.conditions.values()):return 'ADVANTAGE'
    return None


@hook('source_check_subjects')
def recall_subjects(ctx,row):
    if mechanic_of(ctx.action)==SOURCE:
        return [ctx.actor.entity_id,*[c.data['object_subject'] for c in ctx.actor.conditions.values() if c.condition_id==PRESENT and c.data.get('object_subject')]]
    if mechanic_of(ctx.action)!=SOURCE+'.memory':return None
    return [c.data['subject'] for c in ctx.actor.conditions.values() if c.condition_id==MEMORY]


@hook('compile_actions')
def adorn_objects(info):
    if SOURCE not in info['owned_ids']:return None
    out=[]
    for action in info['actions']:
        if mechanic_of(action)!=SOURCE:continue
        label=action.parameters.get('typed',{}).get('option_label')
        if label not in ('Advantage on Check','Visually Memorable'):continue
        kind='check' if label=='Advantage on Check' else 'memory'
        out.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'.object',
            'display_name':action.display_name+' (object)','target_kind':'OBJECT','range_ft':5,
            'parameters':{**action.parameters,'adorn_object':kind,'description':'Bonus Action, no CP: adorn a touched object for one minute.'}}))
    # Aura objects retain all eight printed presentations.
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    for aura in AURAS:
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.adorn.object.{aura}",
            display_name='Adorn the Moment: '+aura+' (object)',owner_id=info['actor_id'],
            economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',target_kind='OBJECT',range_ft=5,
            parameters={'adorn_object':'aura','adorn_aura':aura,'description':f'Bonus Action, no CP: a touched object has a {aura} aura for one minute; no direct combat effect.',
                'typed':{'source':SOURCE,'effects':[],'numbers':dict(info['numbers']),'riders':[]}}))
    return out


@hook('object_targets')
def object_targets(engine,actor,action):
    if not action.parameters.get('adorn_object') or action.owner_id!=actor.entity_id:return None
    return [o.object_id for o in engine.state.objects.values() if not o.destroyed]


@hook('object_action')
def object_adorn(engine,actor,action,obj,candidate,intent):
    kind=action.parameters.get('adorn_object')
    if not kind or action.owner_id!=actor.entity_id:return None
    from .effect_durations import round_token
    from .condition_ownership import remove_instance
    for owner in engine.state.actors.values():
        for iid,c in list(owner.conditions.items()):
            if c.condition_id==PRESENT and c.data.get('object_subject')==obj.object_id:remove_instance(engine,owner,iid,action.source_definition_id)
    engine._apply_condition(actor,PRESENT,action.source_definition_id,actor.entity_id,expires_on=round_token(engine,10),
        data={'kind':kind,'object_subject':obj.object_id,'aura':action.parameters.get('adorn_aura',''),
            'label':'Adorn the Moment on an object'})
    witnesses(engine)
    return True


@hook('compile_actions')
def granted_check_actions(info):
    from .source_checks import check_action
    skills={'Acrobatics':'DEX','Animal Handling':'WIS','Arcana':'INT','Athletics':'STR','Deception':'CHA','History':'INT','Insight':'WIS','Intimidation':'CHA','Investigation':'INT','Medicine':'WIS','Nature':'INT','Perception':'WIS','Performance':'CHA','Persuasion':'CHA','Religion':'INT','Sleight of Hand':'DEX','Stealth':'DEX','Survival':'WIS'}
    return [check_action(info,SOURCE,'Adorn: make a presentation check',CHECKS,PURPOSES),
        check_action(info,SOURCE+'.memory','Recall a memorable subject',skills,
            {'remember':'Remember the subject','identify':'Identify the subject','other':'Another purpose'})]


@hook('candidate_allowed')
def granted_checks_only(engine,actor,candidate,action):
    if action is None:return None
    source=mechanic_of(action)
    if not any(r.get('type')=='source_check' for r in action.parameters.get('typed',{}).get('effects',[])):return None
    if source==SOURCE:return None if any(c.condition_id==PRESENT and c.data.get('kind')=='check' for c in actor.conditions.values()) else False
    if source==SOURCE+'.memory':return None if any(c.condition_id==MEMORY for c in actor.conditions.values()) else False
    return None


@hook('match_initialize')
def new_scene_allowance(engine):
    from .condition_ownership import remove_instance
    for actor in engine.state.actors.values():
        for iid,c in list(actor.conditions.items()):
            if c.condition_id==USED and c.data.get('scene') and c.data['scene']!=scene_identity(engine,actor):
                remove_instance(engine,actor,iid,c.source_definition_id)

    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is not None and bundle.get('adorn_used_scene')==scene_identity(engine,actor) and not any(c.condition_id==USED for c in actor.conditions.values()):
            engine._apply_condition(actor,USED,SOURCE,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'scene':scene_identity(engine,actor),'label':'Adorn presentation benefit used this scene'})
