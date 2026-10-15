"""Assigned source conditions across actual journey/encounter boundaries.

Consumes the consent owner's public snapshot/settled/setup hooks. The terminal
fight is immutable. Source clocks are exported before generic health validation:
full elapsed rounds use the engine's six-second round standard; next-turn clocks
stay source-turn clocks and never become guessed elapsed seconds. Opaque native
condition data and real line objects retain exact source/recipient identities.
"""
import json
from copy import deepcopy
from fractions import Fraction
from . import hook
from .beauty_adorn_base import PRESENT,MEMORY,USED
from .ink_base_actions import SUPPLY,SURFACE_MARK
from .thread_base_line import GUIDE,LISTENING,LINE_OBJECT
from .journey_turns import live,elapsed_deadline,deadline
KEY='scoped_information'

def owned_modifier(engine,modifier):
    from .ability_source import mechanic_of
    from .thread_base_line import DRAW
    action=engine.action_catalog.get(modifier.source_definition_id)
    return bool(action and mechanic_of(action)==DRAW and modifier.target_field=='speed_ft')

STATIC={PRESENT,MEMORY,USED,SUPPLY,SURFACE_MARK,GUIDE,LISTENING,
    'condition:typed.thread_holding','condition:typed.detected_thread'}


def managed(engine,c):
    if c.condition_id in STATIC or c.data.get('object_mark_name')=='Thread Line':return True
    if c.condition_id=='condition:information.reading':
        from .ability_source import mechanic_of
        from .ink_base_actions import LIVING,LASH,PRESS
        from .thread_base_line import DRAW,LISTEN
        from .beauty_adorn_base import SOURCE as ADORN
        from .jester_scene import SOURCE as JESTER
        source=engine.action_catalog.get(c.source_definition_id)
        return (mechanic_of(source) if source else c.source_definition_id) in (LIVING,LASH,PRESS,DRAW,LISTEN,ADORN,JESTER)
    from ..typed_executor import mark_condition_id
    from .jester import PROPOSITIONS,foil_mark
    return any(c.condition_id in tuple(mark_condition_id(name,aid) for name in ('Thread Line','ink_mark',*[foil_mark(p) for p in PROPOSITIONS])) for aid in engine.state.actors)


def clock_out(session,engine,c):
    from .effect_durations import parse_round,parse
    name=c.expires_on
    if name in (None,'UNTIL_REMOVED'):return {}
    rounded=parse_round(name)
    if rounded:
        # Slot phase stays in the saved native record; only complete rounds
        # remaining enter the elapsed-time scene's ordinary duration clock.
        seconds=max(0,(rounded[0]-engine.state.round_number)*6)
        if seconds==0 and rounded[1]>engine.state.current_slot_index:seconds=6
        return elapsed_deadline(session,seconds) if seconds else {'expires_num':session.clock().numerator,'expires_den':session.clock().denominator}
    parsed=parse(name)
    if parsed:
        edge,owner,turn=parsed
        return {**deadline(session,owner,edge),
            'remaining_turns':max(1,turn-engine.state.actors[owner].turns_started)}
    if name in ('START_OF_MARKER_NEXT_TURN','END_OF_MARKER_NEXT_TURN','START_OF_SOURCE_NEXT_TURN'):
        return deadline(session,c.source_actor_id,'start' if name.startswith('START') else 'end')
    raise ValueError('This source condition has an unsupported continuation clock: '+str(name))


def records(session,aid):
    return session.state['actors'][aid].get('source_states',{}).get(KEY,{}).get('conditions',[])


@hook('journey_snapshot_actor')
def snapshot(actor,session,aid,engine):
    owned={iid for iid,c in actor.conditions.items() if managed(engine,c)}
    mods={mid for mid,m in actor.modifiers.items() if owned_modifier(engine,m)}
    if not owned and not mods:return None
    out=actor.model_copy(deep=True)
    out.conditions={iid:c for iid,c in out.conditions.items() if iid not in owned}
    out.modifiers={mid:m for mid,m in out.modifiers.items() if mid not in mods}
    return out


@hook('journey_encounter_settled')
def export(session,aid,engine,creature):
    conditions=[{'kind':'condition','native':c.model_dump_json(exclude_none=True),**clock_out(session,engine,c)}
        for c in creature.conditions.values() if managed(engine,c)]
    conditions.extend({'kind':'modifier','native':m.model_dump_json(exclude_none=True),**clock_out(session,engine,m)} for m in creature.modifiers.values() if owned_modifier(engine,m))
    actor=session.state['actors'][aid]
    prior=actor.get('source_states',{}).get(KEY)
    if not conditions and not prior:return
    actor.setdefault('source_states',{})[KEY]={'conditions':conditions}
    # Scene consumers use the same actual information, without a fresh grant.
    actor['scoped_presentations']=[]
    actor['scene_snares']=[]
    for row in conditions:
        c=json.loads(row['native']);data=c.get('data',{})
        if row['kind']=='modifier':
            actor.setdefault('scene_snares',[]).append({k:v for k,v in row.items() if k not in ('native','kind')});continue
        if c['condition_id']==SUPPLY:actor['living_ink']={**data,**{k:v for k,v in row.items() if k!='native'}}
        if c['condition_id']==PRESENT:
            actor['scoped_presentations'].append({'source':c['source_definition_id'],'owner':c['source_actor_id'],**data,**{k:v for k,v in row.items() if k not in ('native','kind')}})
        if c['condition_id']==MEMORY:
            memories=actor.setdefault('scoped_memories',[])
            if data['subject'] not in memories:memories.append(data['subject'])
    if aid==next(iter(session.state['actors'])):
        from ..journey_assets import JourneyAssetContext
        context=JourneyAssetContext(session)
        for obj in engine.state.objects.values():
            if obj.object_kind==LINE_OBJECT:context._update_object(obj,'system:source.line_continuation',obj.owner_id)


@hook('journey_combat_setup')
def setup(bundle,session,aid):
    rows=[deepcopy(r) for r in records(session,aid) if live(session,r)]
    actor=session.state['actors'][aid]
    mirrors={SUPPLY:'living_ink',PRESENT:'scoped_presentations'}
    rows=[r for r in rows if json.loads(r['native']).get('condition_id') not in {cid for cid,key in mirrors.items() if key in actor}]
    def make(cid,source,owner,data,clock,identity):
        from ..gate2_runtime_models import ConditionInstance
        native=ConditionInstance(instance_id=identity,condition_id=cid,source_definition_id=source,source_actor_id=owner,target_id=aid,applied_sequence=0,expires_on='UNTIL_REMOVED',data=data)
        return {'kind':'condition','native':native.model_dump_json(exclude_none=True),**clock}
    ink=actor.get('living_ink')
    if ink and live(session,ink):
        from .ink_base_actions import LIVING
        rows.append(make(SUPPLY,LIVING,aid,{k:v for k,v in ink.items() if k in ('origin','saleable','label')},{k:v for k,v in ink.items() if k.startswith('expires_')},aid+':scene-ink'))
    for index,presentation in enumerate(actor.get('scoped_presentations',[])):
        if live(session,presentation):rows.append(make(PRESENT,presentation['source'],presentation['owner'],{k:v for k,v in presentation.items() if k in ('kind','aura','object_subject','label')},{k:v for k,v in presentation.items() if k.startswith('expires_')},aid+':scene-adorn:'+str(index)))
    if not rows:return None
    for row in rows:
        if 'expires_num' in row:
            remaining=Fraction(row['expires_num'],row['expires_den'])-session.clock()
            row['remaining_num']=remaining.numerator;row['remaining_den']=remaining.denominator
    return {**bundle,'scoped_continuation':rows,
        'scoped_line_objects':[deepcopy(o) for o in session.state.get('runtime_objects',{}).values() if o['object_kind']==LINE_OBJECT]}


@hook('match_initialize')
def restore(engine):
    from .effect_durations import round_token
    from ..gate2_runtime_models import RuntimeObjectState
    mapping={}
    pending=[(bundle,row) for bundle in engine.typed_bundle_documents for row in bundle.get('scoped_continuation',[])]
    pending.sort(key=lambda item:json.loads(item[1]['native']).get('condition_id') in (LISTENING,'condition:typed.thread_holding'))
    for bundle,row in pending:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        c=json.loads(row['native']);modifier=row.get('kind')=='modifier'
        old=c.get('instance_id','');data=deepcopy(c.get('data',{}))
        expiry=c.get('expires_on')
        if 'remaining_num' in row:
            remaining=Fraction(row['remaining_num'],row['remaining_den'])
            if remaining<=0:continue
            expiry=round_token(engine,max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator)))
        elif 'expires_on' in row:
            expiry=row['expires_on'];data['marker_turn']=engine.state.actors[c['source_actor_id']].turns_started
        if modifier:
            if expiry in ('START_OF_MARKER_NEXT_TURN','END_OF_MARKER_NEXT_TURN'):
                from .effect_durations import token
                expiry=token('start' if expiry.startswith('START') else 'end',c['source_actor_id'],engine.state.actors[c['source_actor_id']].turns_started+1)
            engine._add_modifier(actor,c['source_definition_id'],c['target_field'],c['operation'],c['value'],c['applies_to'],expires_on=expiry,source_actor_id=c['source_actor_id'])
            continue
        if data.get('line_id') in mapping:data['line_id']=mapping[data['line_id']]
        before=set(actor.conditions)
        engine._apply_condition(actor,c['condition_id'],c['source_definition_id'],c['source_actor_id'],expires_on=expiry,data=data)
        new=next((v for iid,v in actor.conditions.items() if iid not in before and v.condition_id==c['condition_id']),None)
        if new:mapping[old]=new.instance_id
    objects={r['object_id']:r for b in engine.typed_bundle_documents for r in b.get('scoped_line_objects',[])}
    for raw in objects.values():
        row=deepcopy(raw);old=row['component']['line_instance']
        if old not in mapping:continue
        row['component']['line_instance']=mapping[old]
        engine._update_object(RuntimeObjectState.model_validate(row),'system:source.line_continuation',row['owner_id'])


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    state=session.state['actors'][aid].get('source_states',{}).get(KEY)
    if state:state['conditions']=[r for r in state['conditions'] if live(session,r)]


@hook('journey_turn_boundary')
def turn_boundary(session,aid,edge):
    for actor_id in session.state['actors']:elapsed(session,actor_id,None,0,())


@hook('journey_view')
def private_continuation(state,viewer_id):
    if not any(KEY in a.get('source_states',{}) for a in state['actors'].values()):return None
    out=deepcopy(state);out.pop('replay_base',None);out.pop('command_journal',None)
    for aid,actor in out['actors'].items():
        if aid!=viewer_id and 'source_states' in actor:actor['source_states'].pop(KEY,None)
    return out
