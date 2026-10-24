"""GM-requested ordinary checks, resolved by real native table actions.

The public check request supplies its actual DC, task and existing reference.
It grants no movement, item, consent, attack or acquisition. All participants
must be explicit readers because ordinary table dice are public. Private world
facts remain on their separate admission path. No pending request means no new
candidate, roll, event, cost or actor edit. Human d20 choices retain the normal
active-intent/reaction provider, including when another actor schedules a check.
"""
from . import hook,effect
from ..journey import require,integer
from ..gate2_runtime_models import ActionDefinition

SOURCE='system:scene.checks'
ACTION='action:system.scene.requested_check'
DONE='condition:scene.check_resolved'
PURPOSES={'carry','drag','lift','hold_burden','pass_hostile_space','other'}


def numbers(bundle,ability):
    recorded=bundle.get('ordinary_ability_modifiers') or {}
    if ability in recorded:return {'ability_mods':recorded}
    for action in bundle.get('action_catalog',[]):
        value=(action.get('parameters',{}).get('typed') or {}).get('numbers') or {}
        if ability in value.get('ability_mods',{}):return value
    return None


@hook('compile_bundle')
def ordinary_statistics(bundle,info):
    """Seal actual sheet scores; never infer ordinary modifiers from saves."""
    import json
    rows=(info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('abilities') or []
    if isinstance(rows,str):rows=json.loads(rows)
    values={r['ability']:(r['score']-10)//2 for r in rows if isinstance(r,dict)
            and r.get('ability') in ('STR','DEX','CON','INT','WIS','CHA') and type(r.get('score')) is int and r['score']>=1}
    return {**bundle,'ordinary_ability_modifiers':values} if values else None


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=SOURCE or kind!='ability_check' or not hasattr(session,'engine'):return None
    return {'value_type':'document','maximum_seconds':60,'authority':'table_owner',
        'description':'Request a public ordinary check against an actual DC and task; never an ability activation or movement permission.'}


@hook('fact_admission_validate')
def validate(session,source,subject,kind,scope,value):
    if source!=SOURCE or kind!='ability_check':return None
    engine=session.engine;actor=engine.state.actors[subject]
    require(set(value)-{'breathing_hazards','source_rule','source_cl'}=={'ability','skill','dc','purpose','reference'}
        and value['ability'] in ('STR','DEX','CON','INT','WIS','CHA') and type(value['skill']) is str
        and integer(value['dc']) and value['dc']<=1000 and value['purpose'] in PURPOSES
        and type(value['reference']) is str,'Name a real ability, recorded skill (or none), DC, task and reference.')
    if 'breathing_hazards' in value:
        require(isinstance(value['breathing_hazards'],list) and value['breathing_hazards'] and
                set(value['breathing_hazards'])<={'inhalation','suffocation','breathing_interference'} and
                type(value.get('source_rule')) is str and bool(value['source_rule'].strip()) and integer(value.get('source_cl')),
                'Breathing hazards need their actual printed source, Source CL and explicit inhalation, suffocation or breathing-interference classification.')
    else:require('source_rule' not in value and 'source_cl' not in value,'Classify the recorded breathing hazard explicitly.')
    require(actor.active and actor.life_state not in ('DYING','STABLE'),'This creature cannot perform the requested voluntary check.')
    bundle=session.state['actors'][subject]['bundle']
    require(numbers(bundle,value['ability']) is not None,'This creature has no recorded ordinary ability modifier.')
    require(not value['skill'] or value['skill'] in bundle.get('skills',{}),'This skill has no recorded check total.')
    ref=value['reference']
    if value['purpose']=='pass_hostile_space':
        other=engine.state.actors.get(ref)
        require(other is not None and other.team_id!=actor.team_id and engine._distance_actor_to_actor(actor,other)<=5,
            'The hostile creature whose space is attempted must actually be adjacent.')
    elif value['purpose']!='other':
        from .. import carry
        obj=engine.state.objects.get(ref)
        item=carry.item_of(carry.carrying_of(engine,subject),key=ref)
        require(bool(obj and not obj.destroyed and engine.grid.distance_ft(actor.position,obj.position)<=5
            and engine.grid.line_of_physical_transmission(actor.position,obj.position))
            or bool(item and carry.holds(engine,actor,ref)),'Choose the actual nearby object or held supply, pack, rope or burden.')
        require(value['ability']=='STR','Carrying, dragging, lifting and holding this burden require the actual Strength check.')
    return True


@hook('fact_admission_readers_validate')
def public_check(session,source,subject,kind,readers):
    if source!=SOURCE or kind!='ability_check':return None
    require(set(readers)==set(session.state['actors']),'Ordinary table checks are public; explicitly include every participant as a reader.')
    return True


def pending(engine):
    from ..combat_world_facts import records,clock
    latest={}
    for r in records(engine):
        if r['source']==SOURCE and r['kind']=='ability_check':latest[(r['subject'],r['scope'])]=r
    done={c.data['receipt_id'] for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id==DONE}
    return [r for r in latest.values() if r['expires_at']>clock(engine) and r['receipt_id'] not in done]


@hook('match_start')
def register(engine):
    if not getattr(engine,'typed_bundle_documents',()):return
    engine.action_catalog[ACTION]=ActionDefinition(source_definition_id=ACTION,display_name='Resolve a requested ability check',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'typed':{'source':SOURCE,'effects':[{'type':'scene_requested_check'}],'numbers':{},
            'duration':{'kind':'instant'},'riders':[],'manual_inline_choice':True},
            'free_primary':True,'description':'Resolve a public GM-requested check using the creature’s recorded statistics and the actual task DC. No action or resource cost; this grants no movement or item.'})


@hook('additional_actions')
def available(engine,actor):
    return [ACTION] if ACTION in engine.action_catalog and pending(engine) else None


@hook('candidate_allowed')
def requested_only(engine,actor,candidate,action):
    return bool(pending(engine)) if action is not None and action.source_definition_id==ACTION else None


@effect('scene_requested_check')
def resolve(ctx,row):
    from .needle import ask,checkpoint_id,CHOICE
    from ..combat_world_facts import Admission
    from ..ability_checks import ordinary_check_bonus
    requests=pending(ctx.engine)
    if not requests:return
    if len(requests)>1:
        selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'SCENE_CHECK_REQUEST'),ctx.actor,
            CHOICE+'scene_check',[r['receipt_id'] for r in requests],minimum=1,maximum=1,name='Requested ability check',
            labels={r['receipt_id']:ctx.engine.state.actors[r['subject']].display_name+': '+r['scope'] for r in requests},
            prompt='Choose which actual GM-requested check to resolve. The creature uses its recorded statistics against the declared DC; no action or resource cost.')
        request=next(r for r in requests if r['receipt_id']==selected[0])
    else:request=requests[0]
    value=request['value'];actor=ctx.engine.state.actors[request['subject']]
    adapter=Admission(ctx.engine)
    validate(adapter,SOURCE,actor.entity_id,'ability_check',request['scope'],value)
    bundle=adapter.state['actors'][actor.entity_id]['bundle']
    stats=numbers(bundle,value['ability'])
    bonus=ordinary_check_bonus(ctx.engine,actor,value['ability'],value['skill'],numbers=stats)
    require(bonus is not None,'The requested check statistic is unknown.')
    reason='CHECK:'+SOURCE+':'+request['receipt_id']
    context={'kind':'check','source_id':SOURCE,'actor_id':actor.entity_id,'reason':reason,'ability':value['ability'],
        'skill':value['skill'],'purpose':value['purpose'],'reference':value['reference'],'target_dc':value['dc']}
    with ctx.engine.d20_scope(context):
        roll=ctx.engine.roll_check(modifier=bonus,actor_id=actor.entity_id,reason=reason,
            ability=value['ability'],skill=value['skill'] or None,hazards=(value['purpose'],*('category:'+tag for tag in value.get('breathing_hazards',[]))))
        ctx.engine._record_roll(roll)
        success=roll.total>=value['dc']
        ctx.engine._append_event('CHECK_ROLLED',SOURCE,actor_id=actor.entity_id,target_ids=(actor.entity_id,),
            payload={'actor':roll.model_dump(mode='json'),'dc':value['dc'],'success':success,'check':value['skill'] or value['ability'],
                     'purpose':value['purpose'],'request_receipt_id':request['receipt_id']})
    ctx.engine._apply_condition(actor,DONE,SOURCE,actor.entity_id,expires_on='UNTIL_REMOVED',data={
        'receipt_id':request['receipt_id'],'roll_id':roll.roll_id,'total':int(roll.total),'success':int(success),
        'label':'Resolved requested check: '+request['scope']})


@hook('presentation_hidden_conditions')
def hidden_receipts(engine,actor):
    return [iid for iid,c in actor.conditions.items() if c.condition_id==DONE] or None


@hook('presentation_hidden_history_conditions')
def hidden_history(events):
    result=[]
    for event in events:
        payload=event.get('payload',{}) if isinstance(event,dict) else event.payload
        if payload.get('condition_id')==DONE and payload.get('instance_id'):result.append(payload['instance_id'])
    return result or None
