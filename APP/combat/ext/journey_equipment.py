"""Native Draw/Stow continuation for source abilities used during journeys.

The existing compiled equipment_grip actions are the sole action/weapon schema.
Manual choices commit real readiness conditions; encounter transfer restores
those same native choices. No catalog policy marker means no new option.
"""
import json
from . import hook
from ..journey import require
from ..journey_equipment import STATE,grip_options


@hook('journey_options')
def equipment_options(session,aid):
    return [{'id':a.source_definition_id,'kind':'equipment_grip','payload':{'action':a.source_definition_id},
        'auto_select':0,'label':session.state['actors'][aid]['name']+': '+a.display_name} for a in grip_options(session,aid)] or None


@hook('journey_command')
def equipment_command(session,aid,kind,payload):
    if kind!='equipment_grip':return
    require(set(payload)=={'action'} and type(payload['action']) is str,'Choose one native Draw or Stow action.')
    action=next((a for a in grip_options(session,aid) if a.source_definition_id==payload['action']),None)
    require(action is not None,'That weapon readiness choice is no longer legal.')
    from ..gate2_runtime_models import ConditionInstance
    from .hand_occupancy import GRIP
    data={**action.parameters['equipment_grip']};data['held']=int(bool(data['held']))
    c=ConditionInstance(instance_id='journey:grip:'+data['weapon'],condition_id=GRIP,
        source_definition_id=action.source_definition_id,source_actor_id=aid,target_id=aid,
        applied_sequence=len(session.state['events']),expires_on='UNTIL_REMOVED',data=data)
    records=session.state['actors'][aid].setdefault('source_states',{}).setdefault(STATE,{}).setdefault('conditions',[])
    records[:]=[raw for raw in records if json.loads(raw)['data']['weapon']!=data['weapon']]
    records.append(c.model_dump_json())
    session.emit('EQUIPMENT_GRIP_COMMITTED',aid,source=action.source_definition_id,weapon=data['weapon'],held=data['held'])
    return True


@hook('journey_combat_bundle')
def transfer_grips(bundle,session,aid):
    data=session.state['actors'][aid].get('source_states',{}).get(STATE,{}).get('conditions',[])
    if data:bundle.setdefault('journey_setup',{})['equipment_grips']=list(data)


@hook('match_initialize')
def restore_grips(engine):
    from ..gate2_runtime_models import ConditionInstance
    from .equipment_hands import set_weapon_readiness
    from ..weapon_delivery import available_weapons
    for bundle in getattr(engine,'typed_bundle_documents',()):
        aid=bundle['actor_id'];actor=engine.state.actors.get(aid)
        if actor is None:continue
        for raw in bundle.get('journey_setup',{}).get('equipment_grips',[]):
            c=ConditionInstance.model_validate(json.loads(raw));data=c.data
            require(c.source_actor_id==aid and data.get('weapon') in available_weapons(engine,actor,include_busy=True),
                    'A saved readiness choice must name its owner’s real weapon.')
            set_weapon_readiness(engine,actor,data['weapon'],bool(data['held']),source=c.source_definition_id,source_actor_id=aid,
                hand=data.get('hand'))


@hook('journey_encounter_settled')
def retain_grips(session,aid,engine,creature):
    from .hand_occupancy import GRIP
    session.state['actors'][aid].setdefault('source_states',{}).setdefault(STATE,{})['conditions']=[
        c.model_dump_json() for c in creature.conditions.values() if c.condition_id==GRIP]
