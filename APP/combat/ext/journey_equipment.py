"""Opted-in journey equipment using existing native inventory and grip records.

No new ownership, possession or anatomy schema is introduced. Native compiled
carrying supplies exact instances; encounter_snapshot.conditions holds the same
GRIP/dropped/transfer records that combat already restores. No enabling source,
unknown inventory or old unmanageable catalog leaves options/state unchanged.
"""
import json
from . import hook,run_strict
from .hand_occupancy import HANDS,GRIP,default_weapon_grips,resting_hands
from ..gate2_runtime_models import ActionDefinition,ConditionInstance

SOURCE='system:equipment.readiness'


def enabled(session,aid):
    return True in run_strict('journey_equipment_enabled',session.state['actors'][aid]['bundle'])


def actions(session,aid):
    return [ActionDefinition.model_validate(a) for a in session.state['actors'][aid]['bundle'].get('action_catalog',[])]


def conditions(session,aid):
    return [json.loads(c) if isinstance(c,str) else c for c in session.state['actors'][aid].get('encounter_snapshot',{}).get('conditions',{}).values()]


def parts(session,aid):
    known=list(HANDS)
    for extra in run_strict('journey_hand_parts',session,aid):
        if not isinstance(extra,(list,tuple)) or any(type(p) is not str or not p for p in extra):
            raise ValueError('Journey hand parts must be explicit named parts')
        known.extend(p for p in extra if p not in known)
    return known


def weapons(session,aid):
    from ..weapon_delivery import physical_weapon_id
    owned=session.state['actors'][aid]['bundle'].get('carrying') or {}
    actual={item.get('weapon_action') for item in owned.get('items',[]) if item.get('weapon_action')}
    return {a.source_definition_id:a for a in actions(session,aid) if a.owner_id==aid and a.source_definition_id in actual
            and physical_weapon_id(a.source_definition_id,a.parameters)==a.source_definition_id}


def grips(session,aid):
    default=default_weapon_grips(actions(session,aid),session.state['actors'][aid]['bundle'].get('carrying'),len(parts(session,aid)),owner_id=aid)
    rows=conditions(session,aid)
    choices={r.get('data',{}).get('weapon'):r.get('data',{}).get('held') for r in rows if r['condition_id']==GRIP}
    custody={r.get('data',{}).get('disables_action') for r in rows if (r.get('data',{}).get('dropped_at')
        or r.get('data',{}).get('held_by') or r['condition_id']=='condition:typed.disarmed')}
    return {key:resting_hands(action) for key,action in weapons(session,aid).items()
            if key not in custody and choices.get(key,int(key in default))}


def free_hands(session,aid):
    from factory_authoring.starting_kits import item_definition
    occupied=set()
    hand_parts=parts(session,aid)
    own_rows=conditions(session,aid)
    lost={r.get('data',{}).get('item_key') for r in own_rows if r.get('data',{}).get('dropped_at') or r.get('data',{}).get('held_by')}
    shields=sum(item_definition(str(i.get('item_id') or '')).get('armor_category')=='shield' and i.get('key') not in lost
        for i in session.state['actors'][aid]['bundle'].get('carrying',{}).get('items',[]))
    occupied.update(hand_parts[:shields])
    held=grips(session,aid)
    explicit={r.get('data',{}).get('weapon'):r.get('data',{}).get('hand') for r in own_rows if r['condition_id']==GRIP}
    named=[explicit[key] for key in held if explicit.get(key) in hand_parts]
    if len(set(named))!=len(named) or set(named)&occupied:return []
    occupied.update(named)
    for key,count in held.items():
        hand=explicit.get(key)
        if hand in hand_parts:count-=1
        for part in hand_parts:
            if count>0 and part not in occupied:occupied.add(part);count-=1
    for other in session.state['actors']:
        for row in conditions(session,other):
            data=row.get('data',{})
            if data.get('held_by')==aid and data.get('hand') in hand_parts:
                occupied.add(data['hand'])
            if data.get('grapple_source')=='physical' and row.get('source_actor_id')==aid:
                part=data.get('grappling_part')
                if part in hand_parts:occupied.add(part)
                elif not part and any(p not in occupied for p in hand_parts):occupied.add(next(p for p in hand_parts if p not in occupied))
    return [p for p in hand_parts if p not in occupied]


def operation_allowed(session,aid,item,operation):
    replies=run_strict('journey_possession_operation_allowed',session,aid,item,operation,SOURCE)
    if any(type(r) is not bool for r in replies):raise ValueError('Journey possession replies must be boolean')
    return False not in replies


@hook('journey_options')
def options(session,aid):
    if not enabled(session,aid) or session.state['actors'][aid]['incapacitated']:return None
    held=grips(session,aid);free=free_hands(session,aid);rows=conditions(session,aid)
    disabled={r.get('data',{}).get('disables_action') for r in rows if r.get('data',{}).get('dropped_at') or r.get('data',{}).get('held_by') or r['condition_id']=='condition:typed.disarmed'}
    items={i.get('weapon_action'):i for i in session.state['actors'][aid]['bundle'].get('carrying',{}).get('items',[])}
    out=[]
    for key,action in weapons(session,aid).items():
        if key in disabled:continue
        ready=key not in held
        if ready and len(free)<resting_hands(action):continue
        operation='draw' if ready else 'stow'
        if not operation_allowed(session,aid,items[key],operation):continue
        out.append({'id':SOURCE+':'+operation+':'+key,'kind':'equipment_readiness','payload':{'weapon':key,'held':int(ready)},
                    'label':operation.title()+' '+action.display_name.removesuffix(' attack')+'; ordinary equipment handling, no Stamina cost.'})
    return out or None


@hook('journey_command')
def change(session,aid,kind,payload):
    if kind!='equipment_readiness':return None
    from ..journey import require
    require(any(o['payload']==payload for o in options(session,aid) or []),'That physical equipment operation is not available.')
    from .body_modes_scene_resources import journey_health
    snapshot=journey_health(session,aid);key=payload['weapon'];action=weapons(session,aid)[key]
    rows=snapshot.setdefault('conditions',{})
    for iid,serialized in list(rows.items()):
        row=json.loads(serialized) if isinstance(serialized,str) else serialized
        if row['condition_id']==GRIP and row.get('data',{}).get('weapon')==key:del rows[iid]
    data={'weapon':key,'held':payload['held'],'label':action.display_name.removesuffix(' attack')+(' drawn' if payload['held'] else ' stowed')}
    if payload['held']:data['hand']=free_hands(session,aid)[0]
    iid='condition:journey.equipment:'+str(len(session.state['events']))
    row=ConditionInstance(instance_id=iid,condition_id=GRIP,source_definition_id=SOURCE,source_actor_id=aid,target_id=aid,
        applied_sequence=len(session.state['events']),expires_on='UNTIL_REMOVED',data=data)
    rows[iid]=row.model_dump_json()
    session.emit('EQUIPMENT_READINESS_CHANGED',aid,source=SOURCE,weapon=key,held=payload['held'])
    run_strict('journey_state_changed',session,aid)
    return True
