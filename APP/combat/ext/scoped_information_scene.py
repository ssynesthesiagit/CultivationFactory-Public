"""Assigned source consumers outside combat using native journey commands.

Actual author content stays in ink_base_actions. Adorn recipients declare consent
through the public fact-admission contract; the caster cannot declare willingness
for another actor. Geometry and sight use the actual scene map and actor positions.
"""
from copy import deepcopy
from . import hook,query
from ..journey import require
from .beauty_adorn_base import SOURCE as ADORN,CHECKS,PURPOSES,AURAS
from .ink_base_actions import PRESS
from .thread_base_line import DRAW,LISTEN
from .journey_turns import live,deadline,pay,elapsed_deadline


def owns(session,aid,source):
    bundle=session.state['actors'][aid]['bundle']
    if source in bundle.get('ink_sources',[]):return True
    return any((a.get('parameters',{}).get('typed',{}).get('option_of') or a.get('parameters',{}).get('typed',{}).get('source'))==source for a in bundle['action_catalog'])


@hook('journey_native_actions')
def native_actions(session,aid,native):
    from .ability_source import mechanic_of
    from .ink_base_actions import LIVING,LASH
    sources={PRESS,DRAW,LISTEN,LIVING,LASH}
    return [a.source_definition_id for a in native.action_catalog.values() if a.owner_id==aid
            and (mechanic_of(a) in sources or a.parameters.get('thread_response'))]


@hook('journey_native_enabled')
def native_enabled(session,aid):
    from .ink_base_actions import LIVING,LASH
    return True if any(owns(session,aid,s) for s in (PRESS,DRAW,LISTEN,LIVING,LASH)) or any(
        r['subject']==aid for actor in session.state['actors'].values() for r in actor.get('scene_thread_lines',[]) if live(session,r)) else None


def distance(session,a,b):
    from ..gate2_runtime_models import Position
    return session.grid.distance_ft(Position.model_validate(a),Position.model_validate(b))


@hook('journey_persistent_fields')
def fields():return ('scoped_presentations','scoped_memories','adorn_used_scene','scene_ink_marks','scene_thread_lines','scene_listen','scene_snares','scene_prone','scene_dropped_items')


@hook('fact_admission_schema')
def consent_schema(session,source,subject,kind):
    if source!=ADORN or kind!='adorn_consent' or not any(owns(session,aid,ADORN) for aid in session.state['actors']):return None
    return {'value_type':'flag','maximum_seconds':60,'description':'Consent to this caster’s Adorn the Moment offer in touch range.'}


def observe(session):
    if not any(r.get('kind')=='memory' and live(session,r) for a in session.state['actors'].values() for r in a.get('scoped_presentations',[])):return
    from ..journey_equipment import context
    from ..target_knowledge import can_see
    from ..senses import perceives_object
    native=context(session)
    for target_id,holder in session.state['actors'].items():
        for row in holder.get('scoped_presentations',[]):
            if not live(session,row) or row['kind']!='memory':continue
            subject=row.get('object_subject') or target_id
            target=native.state.objects.get(subject) if row.get('object_subject') else native.state.actors[target_id]
            if target is None or getattr(target,'destroyed',False):continue
            for aid,viewer in session.state['actors'].items():
                perceives=(perceives_object(native,native.state.actors[aid],target) if row.get('object_subject') else can_see(native,native.state.actors[aid],target))
                if not viewer['incapacitated'] and perceives:
                    memories=viewer.setdefault('scoped_memories',[])
                    if subject not in memories:
                        memories.append(subject);session.emit('ADORN_WITNESSED',aid,subject=subject,source=ADORN)


@hook('journey_command')
def adorn(session,aid,kind,payload):
    if kind!='adorn_moment':return None
    require(owns(session,aid,ADORN) and not session.state['actors'][aid]['incapacitated'],'An active Adorn the Moment owner must adorn this target.')
    require(set(payload)=={'subject','kind','aura'} and type(payload['subject']) is str and payload['kind'] in ('check','memory','aura'), 'Choose one native creature or object and one Adorn presentation.')
    subject=payload['subject'];actor=session.state['actors'][aid]
    from ..journey_assets import JourneyAssetContext
    obj=JourneyAssetContext(session).state.objects.get(subject) if subject not in session.state['actors'] else None
    require(subject in session.state['actors'] or (obj is not None and not obj.destroyed),'Choose an actual live target.')
    target=actor if obj is not None else session.state['actors'][subject]
    point=obj.position.model_dump(mode='json') if obj is not None else target['position']
    require(distance(session,actor['position'],point)<=5,'Adorn the Moment requires touch.')
    from ..gate2_runtime_models import Position
    require(session.grid.line_of_physical_transmission(Position.model_validate(actor['position']),Position.model_validate(point)),'Touch the target through an actual clear physical path.')
    require((payload['kind']=='aura' and payload['aura'] in AURAS) or (payload['kind']!='aura' and payload['aura']==''),'Choose one printed aura, or leave aura blank for a mechanical option.')
    if obj is None and subject!=aid:
        from ..fact_consent_admission import read
        receipt=read(session,ADORN,subject,'adorn_consent',aid,aid)
        require(receipt is not None and receipt['value']==1,'The recipient must declare consent to this caster through the native source-scoped consent action.')
    scene=session.state.get('scene_id',session.state['journey_id'])
    require(obj is not None or payload['kind']!='check' or target.get('adorn_used_scene')!=scene,'This creature has already benefited from Adorn’s check option this scene.')
    pay(session,aid,'bonus_action')
    presentation={'source':ADORN,'owner':aid,'kind':payload['kind'],'aura':payload['aura'],**elapsed_deadline(session,60),'scene':scene}
    if obj is not None:
        presentation['object_subject']=subject
        for holder in session.state['actors'].values():
            holder['scoped_presentations']=[r for r in holder.get('scoped_presentations',[]) if r.get('object_subject')!=subject]
        actor['scoped_presentations'].append(presentation)
    else:
        target['scoped_presentations']=[r for r in target.get('scoped_presentations',[]) if r.get('object_subject')]+[presentation]
    session.emit('ADORN_USED',aid,subject=subject,presentation=payload['kind'],aura=payload['aura'],deadline=elapsed_deadline(session,60),economy='BONUS_ACTION',cost=0)
    observe(session)
    return True


@hook('journey_check_modes')
def modes(session,aid,task):
    actor=session.state['actors'][aid]
    if task['purpose'] in ('remember','identify') and task['subject'] in actor.get('scoped_memories',[]):return 'ADVANTAGE'
    if CHECKS.get(task['skill'])==task['ability'] and task['purpose'] in PURPOSES and task['purpose']!='other' and any(r['kind']=='check' and not r.get('object_subject') and live(session,r) for r in actor.get('scoped_presentations',[])):return 'ADVANTAGE'
    grant=actor.get('scene_listen')
    if grant and grant['benefit']=='check' and live(session,grant) and task['subject']==grant['subject'] and task['purpose']=='line' and task['skill'] in ('Insight','Perception','Sleight of Hand'):
        if any(r['id']==grant['line_id'] and live(session,r) for r in actor.get('scene_thread_lines',[])):return 'ADVANTAGE'
    return None


@hook('journey_check_resolved')
def consumed(session,aid,task,roll):
    actor=session.state['actors'][aid]
    qualifying=CHECKS.get(task['skill'])==task['ability'] and task['purpose'] in PURPOSES and task['purpose']!='other'
    if qualifying:
        grants=[r for r in actor.get('scoped_presentations',[]) if r['kind']=='check' and not r.get('object_subject') and live(session,r)]
        if grants:
            actor['adorn_used_scene']=grants[0]['scene'];actor['scoped_presentations']=[r for r in actor['scoped_presentations'] if r not in grants]
    grant=actor.get('scene_listen')
    if grant and grant['benefit']=='check' and task['purpose']=='line' and task['subject']==grant['subject'] and task['skill'] in ('Insight','Perception','Sleight of Hand'):
        actor.pop('scene_listen',None)
        from .scoped_continuation import discard
        discard(session,aid,lambda c:c.get('condition_id')=='condition:typed.thread_listen' and c.get('data',{}).get('benefit')=='check' and c['data'].get('subject')==task['subject'])


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid];now=session.clock()
    for key in ('scoped_presentations','scene_ink_marks','scene_thread_lines'):
        if key in actor:actor[key]=[r for r in actor[key] if live(session,r)]
    if actor.get('scene_listen') and not live(session,actor['scene_listen']):actor.pop('scene_listen',None)
    observe(session)


@hook('journey_options')
def options(session,aid):
    if not owns(session,aid,ADORN) or session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    from ..journey_assets import JourneyAssetContext
    subjects=[(subject,actor['name'],actor['position']) for subject,actor in session.state['actors'].items()]
    subjects.extend((obj.object_id,str(obj.component.get('name') or obj.object_kind),obj.position.model_dump(mode='json')) for obj in JourneyAssetContext(session).state.objects.values() if not obj.destroyed)
    result=[]
    for subject,name,position in subjects:
        if distance(session,session.state['actors'][aid]['position'],position)>5:continue
        for kind,aura in [('check',''),('memory',''),*[('aura',a) for a in AURAS]]:
            result.append({'id':'adorn:'+subject+':'+kind+':'+aura,'kind':'adorn_moment','payload':{'subject':subject,'kind':kind,'aura':aura},
                'label':f'Adorn {name}: '+(aura+' aura' if aura else 'one qualifying presentation check' if kind=='check' else 'visually memorable')+' for one minute. Bonus Action, no CP; a creature must consent.'})
    return result


@hook('fact_admission_schema')
def mark_consent(session,source,subject,kind):
    if source!=PRESS or kind!='ink_mark_consent' or not any(owns(session,aid,PRESS) for aid in session.state['actors']):return None
    return {'value_type':'flag','maximum_seconds':60,'description':'Accept this writer’s Ink Mark without a Dexterity save.'}


def numbers(session,aid):
    for action in session.state['actors'][aid]['bundle']['action_catalog']:
        n=action.get('parameters',{}).get('typed',{}).get('numbers')
        if n:return n
    raise ValueError('The source actor has no compiled cultivation numbers.')


def native_roll(session,aid,reason,*,bonus=0):
    from ..gate2_rolls import DeterministicRollAuthority
    actor=session.state['actors'][aid]
    roller=DeterministicRollAuthority(session.state['journey_id']+':source_actions');roller.counter=actor.get('scene_check_counter',0)
    roll=roller.d20(modifier=int(bonus),actor_id=aid,reason=reason)
    actor['scene_check_counter']=roller.counter
    session.emit('SOURCE_ACTION_ROLL',aid,roll=roll.model_dump(mode='json'))
    return roll


@hook('journey_command')
def ink_mark(session,aid,kind,payload):
    if kind!='ink_press_mark':return None
    require(owns(session,aid,PRESS) and not session.state['actors'][aid]['incapacitated'],'An active Press Mark owner must place this mark.')
    require(set(payload)=={'subject','surface','conceal'} and type(payload['conceal']) is int and payload['conceal'] in (0,1),'Choose the target or mapped surface and concealment choice.')
    from ..scene_resolution import engine_for,candidates,commit
    from .ability_source import mechanic_of
    from ..fact_consent_admission import read
    native=engine_for(session);subject=payload['subject'];surface=payload['surface']
    choices={(aid,'choice:needle.ink_conceal'):['conceal'] if payload['conceal'] else []}
    if subject in native.state.actors:
        require(surface=={},'A creature target does not also choose a surface.')
        consent=read(session,PRESS,subject,'ink_mark_consent',aid,aid) if subject!=aid else {'value':1}
        choices[(subject,'choice:needle.ink_accept')]=['accept'] if consent and consent['value']==1 else []
        actions=[a for a in native.action_catalog.values() if a.owner_id==aid and mechanic_of(a)==PRESS and not a.parameters.get('ink_surface_mark')]
        target=subject
    else:
        require(not payload['conceal'],'Concealment applies to hostile creature marking.')
        if subject:
            require(subject in native.state.objects and surface=={},'Choose an actual object or an explicit mapped surface.')
            selection='object:'+subject
        elif set(surface)=={'x','y','z'}:
            selection='ground:'+':'.join(str(surface[k]) for k in ('x','y','z'))
        else:
            require(surface.get('kind')=='item' and surface.get('actor_id',aid)==aid,'Choose your own actual held item.')
            selection='item:'+surface['item_key']
        choices[(aid,'choice:needle.ink_surface')]=[selection]
        actions=[a for a in native.action_catalog.values() if a.owner_id==aid and a.parameters.get('ink_surface_mark')]
        target=aid
    for action in actions:
        for candidate in candidates(native,aid,action):
            if candidate.target_ids==(target,):return commit(session,native,aid,action,candidate,choices)
    raise ValueError('Touch an actual admitted Press Mark target through a clear physical path.')


@hook('journey_command')
def draw_line(session,aid,kind,payload):
    if kind!='thread_draw_line':return None
    require(owns(session,aid,DRAW) and not session.state['actors'][aid]['incapacitated'],'An active Draw the Line owner must create this line.')
    require(set(payload) in ({'subject','medium','stock','effect','anchor','item'}, {'subject','medium','stock','effect','anchor','item','visibility'}) and payload.get('visibility','visible') in ('visible','hidden') and payload['medium'] in ('mundane','qi') and payload['effect'] in ('Pull','Snare','Guide','Trip','Disarm'),'Choose a real target, medium, stock, controlled anchor, visibility and printed basic effect.')
    from ..scene_resolution import engine_for,candidates,commit
    from .thread_base_line import stock
    from .ability_source import mechanic_of
    native=engine_for(session);actor=native.state.actors[aid]
    subject=payload['subject']
    require(subject in native.state.actors or subject in native.state.objects,'Choose an actual creature, item, object or mapped surface object.')
    if payload['medium']=='mundane':
        require(any(r['id']==payload['stock'] for r in stock(native,actor)),'Use your own actual thread stock.')
    else:require(payload['stock']=='','Qi Thread does not choose mundane stock.')
    if payload['effect']=='Disarm' and subject in native.state.actors:
        from ..journey_equipment import held
        items=held(session,subject)
        require((not items and payload['item']=='') or any(r['key']==payload['item'] for r in items),'Choose an actual held object.')
    else:require(payload['item']=='','Only Disarm against a creature chooses a held item.')
    actions=[a for a in native.action_catalog.values() if a.owner_id==aid and mechanic_of(a)==DRAW
        and a.parameters['typed'].get('option_label')==payload['effect']
        and bool(a.parameters.get('thread_twin',{}).get('qi'))==(payload['medium']=='qi')
        and not a.parameters.get('draw_attack_replacement') and not a.parameters.get('thread_weapon_source')
        and not a.parameters.get('thread_twin',{}).get('two')]
    chosen=None
    for action in actions:
        for candidate in candidates(native,aid,action):
            origin=candidate.metadata.get('effect_origin',{}).get('id',aid)
            if candidate.target_ids==(subject,) and origin==payload['anchor']:
                chosen=(action,candidate);break
        if chosen:break
    require(chosen is not None,'The target must be known and reachable along a legal physical Thread path, within range and source permissions.')
    # Explicit source geometry, including routed Qi Thread, admits before any
    # scene payment or roll. The native resolver owns attack, saves and effects.
    choices={(aid,'choice:needle.thread_visibility'):[payload.get('visibility','visible')]}
    if payload['medium']=='mundane':choices[(aid,'choice:needle.thread_stock')]=[payload['stock']]
    if payload['item']:choices[(aid,'choice:needle.thread_disarm')]=[payload['item']]
    return commit(session,native,aid,*chosen,choices)


@hook('journey_command')
def listen(session,aid,kind,payload):
    if kind!='thread_listen':return None
    require(owns(session,aid,LISTEN) and not session.state['actors'][aid]['incapacitated'],'An active Listen Through Tension owner must listen.')
    require(set(payload)=={'line','benefit'} and payload['benefit'] in ('motion','handling','check','space'),'Choose one active line and one printed benefit.')
    line=next((r for r in session.state['actors'][aid].get('scene_thread_lines',[]) if r['id']==payload['line'] and live(session,r)),None)
    require(line is not None,'Choose a live Thread Line you maintain.')
    from ..scene_resolution import engine_for,candidates,commit
    from .ability_source import mechanic_of
    native=engine_for(session)
    action=next(a for a in native.action_catalog.values() if a.owner_id==aid and mechanic_of(a)==LISTEN and any(r.get('type')=='thread_listen' for r in a.parameters['typed']['effects']))
    offered=candidates(native,aid,action)
    require(bool(offered),'Choose a live physically connected Thread Line.')
    return commit(session,native,aid,action,offered[0],{
        (aid,'choice:needle.thread_listen_line'):[line['subject']],
        (aid,'choice:needle.thread_listen_benefit'):[payload['benefit']]})


@hook('journey_command')
def handling(session,aid,kind,payload):
    if kind!='thread_line_response':return None
    require(set(payload)=={'line','handling'} and payload['handling'] in ('holding','ignoring'),'Declare your own actual interaction with one connected line.')
    from ..scene_resolution import engine_for,candidates,commit
    native=engine_for(session)
    identity=native._source_instance_mapping.get(payload['line'],payload['line'])
    action=next(a for a in native.action_catalog.values() if a.owner_id==aid and a.parameters.get('thread_response')==payload['handling'])
    offered=candidates(native,aid,action)
    require(bool(offered),'Choose a real line physically connected to you; holding requires a free hand.')
    return commit(session,native,aid,action,offered[0],{(aid,'choice:needle.thread_response'):[identity]})


@hook('journey_view')
def private_view(state,viewer_id):
    if not any(any(key in a for key in ('scoped_memories','scene_listen','scene_ink_marks','action_source_facts')) for a in state['actors'].values()):return None
    out=deepcopy(state);out.pop('replay_base',None);out.pop('command_journal',None)
    from ..journey import JourneySession
    session=JourneySession(state);viewer=state['actors'].get(viewer_id,{})
    grant=viewer.get('scene_listen')
    out['information']=[]
    if grant and live(session,grant):
        line=next((r for r in viewer.get('scene_thread_lines',[]) if r['id']==grant['line_id'] and live(session,r)),None)
        if line and grant['benefit'] in ('motion','handling','space'):
            benefit=grant['benefit'];details={benefit:line.get(benefit,'unknown')}
            if benefit=='space':
                target=state['actors'].get(line['subject']) or state.get('runtime_objects',{}).get(line['subject'])
                if target:details={'position':deepcopy(target['position'])}
            from .thread_base_line import listen_label
            out['information'].append({'ability':'Listen Through Tension','label':listen_label(benefit),'details':details})
    for aid,actor in out['actors'].items():
        # Storage mirrors are not extra information benefits. Only the chosen
        # Listen consumer above discloses motion, handling or an exact space.
        for row in actor.get('scene_thread_lines',[]):
            for key in ('motion','handling','position'):row.pop(key,None)
        if aid!=viewer_id:
            for key in ('scoped_memories','scene_listen','scene_ink_marks','action_source_facts'):actor.pop(key,None)
    from .thread_base_line import LINE_OBJECT
    from ..journey_equipment import context
    from ..gate2_runtime_models import RuntimeObjectState
    from ..senses import perceives_object
    native=context(session);observer=native.state.actors.get(viewer_id)
    def public_object(raw):
        if raw.get('object_kind')!=LINE_OBJECT:return raw
        obj=RuntimeObjectState.model_validate(raw)
        if observer is None or not perceives_object(native,observer,obj):return None
        return {**raw,'component':{'name':'Thread Line','blocks':False,'structure':False}}
    if 'runtime_objects' in out:
        out['runtime_objects']={oid:clean for oid,raw in out['runtime_objects'].items() if (clean:=public_object(raw)) is not None}
    events=[]
    for event in out['events']:
        if event['kind']=='SOURCE_NATIVE_RESOLVED':continue
        if event['actor_id']!=viewer_id and event['kind'] in ('ADORN_WITNESSED','THREAD_LISTENED','THREAD_HANDLING_DECLARED','INK_MARK_PLACED','ACTION_SOURCE_FACT'):continue
        if event['kind']=='OBJECT_UPDATED':
            clean=public_object(event['object'])
            if clean is None:continue
            event={**event,'object':clean}
        events.append(event)
    out['events']=events
    return out


@hook('journey_turn_boundary')
def source_turn_ended(session,aid,edge):
    for subject,actor in session.state['actors'].items():
        for key in ('scene_thread_lines','scene_snares'):
            if key in actor:actor[key]=[row for row in actor[key] if live(session,row)]
        grant=actor.get('scene_listen')
        if grant and (not live(session,grant) or not any(r['id']==grant['line_id'] for r in actor.get('scene_thread_lines',[]))):actor.pop('scene_listen',None)


@hook('journey_state_changed')
def physical_lines_changed(session,aid):
    """Sync actual movement and line geometry through the native consumers."""
    old_lines=[(owner,r) for owner,a in session.state['actors'].items() for r in a.get('scene_thread_lines',[]) if live(session,r)]
    if not old_lines:return
    from ..scene_resolution import engine_for
    from .thread_base_line import line_motion,settle_line_geometry
    from .scoped_continuation import export
    from ..gate2_runtime_models import Position
    native=engine_for(session)
    for subject in {r['subject'] for _,r in old_lines}:
        target=native.state.actors.get(subject)
        previous=next((r.get('position') for _,r in old_lines if r['subject']==subject),None)
        if target is not None and previous and previous!=target.position.model_dump(mode='json'):
            line_motion(native,target,Position.model_validate(previous),target.position,None,False)
    settle_line_geometry(native)
    for subject,creature in native.state.actors.items():export(session,subject,native,creature)


@hook('journey_pace_ratio')
def snared_pace(session,aid):
    actor=session.state['actors'][aid]
    if not any(live(session,r) for r in actor.get('scene_snares',[])):return None
    speed=int(actor['bundle']['actor_template']['speed_ft'])
    return (max(0,speed-10),speed) if speed else (0,1)


@hook('journey_step_surcharge')
def crawling(session,aid,old,nxt):
    return 1 if session.state['actors'][aid].get('scene_prone') else None


@hook('journey_command')
def stand(session,aid,kind,payload):
    if kind!='scene_stand':return None
    require(not payload and session.state['actors'][aid].get('scene_prone')==1,'Only a prone creature can stand.')
    from .journey_turns import pay_movement
    pay_movement(session,aid,int(session.state['actors'][aid]['bundle']['actor_template']['speed_ft'])//2)
    session.state['actors'][aid].pop('scene_prone')
    from .scoped_continuation import discard
    discard(session,aid,lambda c:c.get('condition_id')=='condition:typed.prone')
    session.emit('SCENE_STOOD',aid,movement_cost_ft=int(session.state['actors'][aid]['bundle']['actor_template']['speed_ft'])//2)
    return True


@hook('journey_options')
def stand_option(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or actor['incapacitated'] or not actor.get('scene_prone'):return None
    turn=actor.get('source_turn')
    cost=int(actor['bundle']['actor_template']['speed_ft'])//2
    if turn and (not turn['active'] or turn['movement_remaining_ft']<cost):return None
    return [{'id':'scene_stand','kind':'scene_stand','payload':{},
        'label':f'Stand from Prone: spend {cost} feet of movement; no Action or CP.'}]


@hook('journey_combat_setup')
def dropped_items_snapshot(bundle,session,aid):
    drops=[r for r in session.state['actors'][aid].get('scene_dropped_items',[]) if not r.get('native_continuation')]
    return {**bundle,'scene_equipment_drops':deepcopy(drops)} if drops else None


@hook('match_initialize')
def dropped_items_restore(engine):
    from .. import carry
    for bundle in engine.typed_bundle_documents:
        drops=bundle.get('scene_equipment_drops')
        if not drops:continue
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for row in drops:
            if carry.item_of(carry.carrying_of(engine,actor.entity_id),key=row['item_key']) is None:raise ValueError('A scene drop no longer matches the acquired inventory.')
            engine._apply_condition(actor,carry.DROPPED,row['source'],row['writer'],expires_on='UNTIL_REMOVED',
                data={'item_key':row['item_key'],'disables_action':row['weapon_action'],'dropped_at':row['position'],'label':'Object dropped in its holder’s space'})
