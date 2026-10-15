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
from .journey_turns import live,deadline,pay


def owns(session,aid,source):
    bundle=session.state['actors'][aid]['bundle']
    if source in bundle.get('ink_sources',[]):return True
    return any((a.get('parameters',{}).get('typed',{}).get('option_of') or a.get('parameters',{}).get('typed',{}).get('source'))==source for a in bundle['action_catalog'])


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
    from ..gate2_runtime_models import Position
    now=session.clock()
    for target_id,target in session.state['actors'].items():
        for row in target.get('scoped_presentations',[]):
            if row['expires_at']<=now or row['kind']!='memory':continue
            for aid,viewer in session.state['actors'].items():
                if not viewer['incapacitated'] and session.grid.line_of_sight(Position.model_validate(viewer['position']),Position.model_validate(target['position'])):
                    memories=viewer.setdefault('scoped_memories',[])
                    if target_id not in memories:
                        memories.append(target_id);session.emit('ADORN_WITNESSED',aid,subject=target_id,source=ADORN)


@hook('journey_command')
def adorn(session,aid,kind,payload):
    if kind!='adorn_moment':return None
    require(owns(session,aid,ADORN) and not session.state['actors'][aid]['incapacitated'],'An active Adorn the Moment owner must adorn this target.')
    require(set(payload)=={'subject','kind','aura'} and payload['subject'] in session.state['actors'] and payload['kind'] in ('check','memory','aura'), 'Choose one native creature and one Adorn presentation.')
    subject=payload['subject'];target=session.state['actors'][subject];actor=session.state['actors'][aid]
    require(distance(session,actor['position'],target['position'])<=5,'Adorn the Moment requires touch.')
    require((payload['kind']=='aura' and payload['aura'] in AURAS) or (payload['kind']!='aura' and payload['aura']==''),'Choose one printed aura, or leave aura blank for a mechanical option.')
    if subject!=aid:
        from ..fact_consent_admission import read
        receipt=read(session,ADORN,subject,'adorn_consent',aid,aid)
        require(receipt is not None and receipt['value']==1,'The recipient must declare consent to this caster through the native source-scoped consent action.')
    scene=session.state.get('scene_id',session.state['journey_id'])
    require(payload['kind']!='check' or target.get('adorn_used_scene')!=scene,'This creature has already benefited from Adorn’s check option this scene.')
    pay(session,aid,'bonus_action')
    target['scoped_presentations']=[{'source':ADORN,'owner':aid,'kind':payload['kind'],'aura':payload['aura'],'expires_at':int(session.clock())+60,'scene':scene}]
    session.emit('ADORN_USED',aid,subject=subject,presentation=payload['kind'],aura=payload['aura'],expires_at=int(session.clock())+60,economy='BONUS_ACTION',cost=0)
    observe(session)
    return True


@hook('journey_check_modes')
def modes(session,aid,task):
    actor=session.state['actors'][aid]
    if task['purpose'] in ('remember','identify') and task['subject'] in actor.get('scoped_memories',[]):return 'ADVANTAGE'
    if CHECKS.get(task['skill'])==task['ability'] and task['purpose'] in PURPOSES and task['purpose']!='other' and any(r['kind']=='check' and live(session,r) for r in actor.get('scoped_presentations',[])):return 'ADVANTAGE'
    grant=actor.get('scene_listen')
    if grant and grant['benefit']=='check' and live(session,grant) and task['subject']==grant['subject'] and task['purpose']=='line' and task['skill'] in ('Insight','Perception','Sleight of Hand'):
        if any(r['id']==grant['line_id'] and live(session,r) for r in actor.get('scene_thread_lines',[])):return 'ADVANTAGE'
    return None


@hook('journey_check_resolved')
def consumed(session,aid,task,roll):
    actor=session.state['actors'][aid]
    qualifying=CHECKS.get(task['skill'])==task['ability'] and task['purpose'] in PURPOSES and task['purpose']!='other'
    if qualifying:
        grants=[r for r in actor.get('scoped_presentations',[]) if r['kind']=='check' and live(session,r)]
        if grants:
            actor['adorn_used_scene']=grants[0]['scene'];actor['scoped_presentations']=[]
    grant=actor.get('scene_listen')
    if grant and grant['benefit']=='check' and task['purpose']=='line' and task['subject']==grant['subject'] and task['skill'] in ('Insight','Perception','Sleight of Hand'):actor.pop('scene_listen',None)


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
    return [{'id':'adorn:'+subject+':'+kind,'kind':'adorn_moment','payload':{'subject':subject,'kind':kind,'aura':''},
        'label':f'Adorn {actor["name"]}: '+('one qualifying presentation check' if kind=='check' else 'visually memorable')+' for one minute. Bonus Action, no CP; consent required.'}
        for subject,actor in session.state['actors'].items() if distance(session,session.state['actors'][aid]['position'],actor['position'])<=5 for kind in ('check','memory')]


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
    actor=session.state['actors'][aid];subject=payload['subject'];now=int(session.clock())
    surface=payload['surface']
    if subject:
        require(subject in session.state['actors'] and surface=={},'Choose an actual creature, or an explicit surface.')
        target=session.state['actors'][subject]
        require(distance(session,actor['position'],target['position'])<=5,'Press Mark requires touch.')
        from ..fact_consent_admission import read
        consent=read(session,PRESS,subject,'ink_mark_consent',aid,aid) if subject!=aid else {'value':1}
        if consent is None or consent['value']!=1:
            dc=int(numbers(session,aid)['save_dc']);save=target['bundle']['actor_template'].get('saving_throws',{}).get('DEX',0)
            roll=native_roll(session,subject,'SAVE:Press Mark:DEX',bonus=save)
            if roll.total>=dc:
                session.emit('INK_MARK_RESISTED',aid,subject=subject,dc=dc);return True
    else:
        require(isinstance(surface,dict) and set(surface)=={'x','y','z'} and all(type(v) is int and v>=0 for v in surface.values())
                and session.grid.in_bounds((surface['x'],surface['y'])) and distance(session,actor['position'],surface)<=5,'Choose a mapped five-foot surface within touch.')
    if payload['conceal']:
        pools=[r for r in ('resource:core.qi','resource:core.stamina','resource:core.resonance') if actor['resources'].get(r,0)>=1]
        require(pools,'Concealing a hostile Ink Mark costs one Cultivation Point.')
        actor['resources'][pools[0]]-=1;session.emit('SOURCE_RESOURCE_SPENT',aid,source=PRESS,resource=pools[0],amount=1)
    pay(session,aid,'action')
    row={'id':f"{aid}:mark:{len(session.state['events'])}",'source':PRESS,'subject':subject,'surface':deepcopy(surface),
        'expires_at':now+3600,'concealed':payload['conceal'],'owner':aid}
    marks=actor.setdefault('scene_ink_marks',[])
    marks[:]=[r for r in marks if not (r['subject']==subject and r['surface']==surface)]
    marks.append(row);n=numbers(session,aid);cap=max(1,int(n['pb'])+int(n['key_mod']))
    del marks[:-cap]
    session.emit('INK_MARK_PLACED',aid,mark=deepcopy(row),economy='ACTION')
    return True


@hook('journey_command')
def draw_line(session,aid,kind,payload):
    if kind!='thread_draw_line':return None
    require(owns(session,aid,DRAW) and not session.state['actors'][aid]['incapacitated'],'An active Draw the Line owner must create this line.')
    require(set(payload)=={'subject','medium','stock','effect','anchor','item'} and payload['subject'] in session.state['actors'] and payload['medium'] in ('mundane','qi') and payload['effect'] in ('Pull','Snare','Guide','Trip','Disarm'), 'Choose a real target, medium, stock, source anchor and printed basic effect.')
    actor=session.state['actors'][aid];subject=payload['subject'];target=session.state['actors'][subject]
    # Controlled Anchor identity uses the upstream public Asset contract.
    anchor=actor['position']
    if payload['anchor']!=aid:
        obj=session.state.get('runtime_objects',{}).get(payload['anchor'])
        require(obj is not None and not obj['destroyed'] and obj.get('owner_id')==aid and obj.get('component',{}).get('anchor'),'Choose yourself or a live controlled native Anchor.')
        anchor=obj['position']
    if payload['effect']=='Disarm':
        from ..journey_equipment import held
        items=held(session,subject)
        require((not items and payload['item']=='') or any(r['key']==payload['item'] for r in items),'Choose one of the target’s actual held objects.')
    else:require(payload['item']=='','Only Disarm chooses an item.')
    reach=30 if payload['medium']=='qi' else 20
    require(distance(session,anchor,target['position'])<=reach,'The connected target is outside this medium’s range.')
    if payload['medium']=='mundane':
        from . import material_ledger as ledger
        item=ledger.holdings(session,aid).get(payload['stock'])
        require(item and item['quantity']>0 and item['kind']=='thread_tool' and ledger.sources(session)[item['source_id']]['material'] in ('thread','silk','wire','cord','needles'),'Use your own actual thread stock.')
    else:
        pools=[r for r in ('resource:core.qi','resource:core.stamina','resource:core.resonance') if actor['resources'].get(r,0)>=1]
        require(pools,'Qi Thread requires one Cultivation Point.');actor['resources'][pools[0]]-=1
        session.emit('SOURCE_RESOURCE_SPENT',aid,source=DRAW,resource=pools[0],amount=1)
    pay(session,aid,'action')
    n=numbers(session,aid);roll=native_roll(session,aid,'ATTACK:Draw the Line',bonus=n['attack_bonus'])
    ac=target['bundle']['actor_template']['armor_class']
    if isinstance(ac,dict):ac=ac.get('base',ac.get('base_value',10))
    if roll.natural_result==1 or (roll.natural_result!=20 and roll.total<int(ac)):
        session.emit('THREAD_MISSED',aid,subject=subject);return True
    line={'id':f'{aid}:line:{len(session.state["events"])}','source':DRAW,'subject':subject,'owner':aid,'anchor':payload['anchor'],
        'medium':payload['medium'],'stock':payload['stock'],'effect':payload['effect'],**deadline(session,aid,'end'),'motion':'still','handling':'unknown'}
    actor.setdefault('scene_thread_lines',[]).append(line)
    session.emit('THREAD_LINE_CREATED',aid,line=deepcopy(line),economy='ACTION')
    sizes=('Tiny','Small','Medium','Large','Huge','Gargantuan')
    own=actor['bundle']['actor_template'].get('size_category','Medium');theirs=target['bundle']['actor_template'].get('size_category','Medium')
    if payload['effect']=='Snare':
        target.setdefault('scene_snares',[]).append({'owner':aid,**deadline(session,aid,'start')})
    elif payload['effect']=='Trip' and sizes.index(theirs)<=sizes.index(own)+1:
        if native_roll(session,subject,'SAVE:Thread Trip:DEX',bonus=target['bundle']['actor_template'].get('saving_throws',{}).get('DEX',0)).total<int(n['save_dc']):
            target['scene_prone']=1;session.emit('SCENE_PRONE',subject,source=DRAW)
    elif payload['effect']=='Disarm':
        if native_roll(session,subject,'SAVE:Thread Disarm:STR',bonus=target['bundle']['actor_template'].get('saving_throws',{}).get('STR',0)).total<int(n['save_dc']):
            if payload['item']:
                from ..journey_equipment import drop
                drop(session,aid,subject,payload['item'],DRAW)
    # Pull uses native size, save, placement and occupied-space checks.
    if payload['effect']=='Pull':
        sizes=('Tiny','Small','Medium','Large','Huge','Gargantuan');own=actor['bundle']['actor_template'].get('size_category','Medium');theirs=target['bundle']['actor_template'].get('size_category','Medium')
        allowed=sizes.index(theirs)<=sizes.index(own)
        if not allowed:allowed=native_roll(session,subject,'SAVE:Thread Pull:STR',bonus=target['bundle']['actor_template'].get('saving_throws',{}).get('STR',0)).total<int(n['save_dc'])
        if allowed:
            from ..gate2_runtime_models import Position
            old=Position.model_validate(target['position']);p=Position.model_validate(anchor)
            nxt=Position(x=old.x+(1 if p.x>old.x else -1 if p.x<old.x else 0),y=old.y+(1 if p.y>old.y else -1 if p.y<old.y else 0),z=old.z)
            if nxt!=old and session.grid.step_legal(old,nxt) and not any(aid2!=subject and a['position']==nxt.model_dump(mode='json') for aid2,a in session.state['actors'].items()):
                target['position']=nxt.model_dump(mode='json');session.emit('THREAD_TARGET_PULLED',aid,subject=subject,position=deepcopy(target['position']))
    return True


@hook('journey_command')
def listen(session,aid,kind,payload):
    if kind!='thread_listen':return None
    require(owns(session,aid,LISTEN) and not session.state['actors'][aid]['incapacitated'],'An active Listen Through Tension owner must listen.')
    require(set(payload)=={'line','benefit'} and payload['benefit'] in ('motion','handling','check','space'),'Choose one active line and one printed benefit.')
    actor=session.state['actors'][aid]
    line=next((r for r in actor.get('scene_thread_lines',[]) if r['id']==payload['line'] and live(session,r)),None)
    require(line is not None,'Choose a live Thread Line you maintain.')
    pay(session,aid,'bonus_action')
    actor['scene_listen']={'line_id':line['id'],'subject':line['subject'],'benefit':payload['benefit'],**deadline(session,aid,'end')}
    session.emit('THREAD_LISTENED',aid,line_id=line['id'],benefit=payload['benefit'],economy='BONUS_ACTION',cost=0)
    return True


@hook('journey_command')
def handling(session,aid,kind,payload):
    if kind!='thread_line_response':return None
    require(set(payload)=={'line','handling'} and payload['handling'] in ('holding','cutting','ignoring'),'Declare your own actual interaction with one connected line.')
    lines=[r for a in session.state['actors'].values() for r in a.get('scene_thread_lines',[]) if r['id']==payload['line'] and r['subject']==aid and live(session,r)]
    require(len(lines)==1,'Choose one actual live Thread Line physically connected to you.')
    lines[0]['handling']=payload['handling'];session.emit('THREAD_HANDLING_DECLARED',aid,line_id=payload['line'],handling=payload['handling'])
    return True


@hook('journey_view')
def private_view(state,viewer_id):
    if not any(any(key in a for key in ('scoped_memories','scene_listen','scene_ink_marks','action_source_facts')) for a in state['actors'].values()):return None
    out=deepcopy(state);out.pop('replay_base',None);out.pop('command_journal',None)
    for aid,actor in out['actors'].items():
        if aid!=viewer_id:
            for key in ('scoped_memories','scene_listen','scene_ink_marks','action_source_facts'):actor.pop(key,None)
            if 'scene_thread_lines' in actor:
                for row in actor['scene_thread_lines']:
                    row.pop('handling',None);row.pop('motion',None)
    out['events']=[e for e in out['events'] if e['actor_id']==viewer_id or e['kind'] not in ('ADORN_WITNESSED','THREAD_LISTENED','THREAD_HANDLING_DECLARED','INK_MARK_PLACED','ACTION_SOURCE_FACT')]
    return out


@hook('journey_turn_boundary')
def source_turn_ended(session,aid,edge):
    for subject,actor in session.state['actors'].items():
        for key in ('scene_thread_lines','scene_snares'):
            if key in actor:actor[key]=[row for row in actor[key] if live(session,row)]
        grant=actor.get('scene_listen')
        if grant and (not live(session,grant) or not any(r['id']==grant['line_id'] for r in actor.get('scene_thread_lines',[]))):actor.pop('scene_listen',None)


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
    session.emit('SCENE_STOOD',aid,movement_cost_ft=int(session.state['actors'][aid]['bundle']['actor_template']['speed_ft'])//2)
    return True


@hook('journey_combat_setup')
def dropped_items_snapshot(bundle,session,aid):
    drops=session.state['actors'][aid].get('scene_dropped_items')
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
