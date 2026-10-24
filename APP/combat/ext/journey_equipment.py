"""Native Draw/Stow continuation for source abilities used during journeys.

The existing compiled equipment_grip actions are the sole action/weapon schema.
Manual choices commit the engine's own ActorState.equipment_readiness mapping;
encounter transfer restores those same native choices. No catalog policy marker
means no new option.
"""
from . import hook
from ..journey import require
from ..journey_equipment import STATE,grip_options,readiness


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
    data={**action.parameters['equipment_grip']};held=int(bool(data['held']))
    records=session.state['actors'][aid].setdefault('source_states',{}).setdefault(STATE,{}).setdefault('readiness',{})
    records[data['weapon']]=held
    session.emit('EQUIPMENT_GRIP_COMMITTED',aid,source=action.source_definition_id,weapon=data['weapon'],held=held)
    return True


@hook('journey_combat_bundle')
def transfer_grips(bundle,session,aid):
    data=readiness(session.state['actors'][aid])
    if data:bundle.setdefault('journey_setup',{})['equipment_grips']=data


@hook('match_initialize')
def restore_grips(engine):
    from .equipment_hands import set_weapon_readiness
    from ..weapon_delivery import available_weapons
    for bundle in getattr(engine,'typed_bundle_documents',()):
        aid=bundle['actor_id'];actor=engine.state.actors.get(aid)
        if actor is None:continue
        for weapon,value in (bundle.get('journey_setup',{}).get('equipment_grips') or {}).items():
            require(weapon in available_weapons(engine,actor,include_busy=True),
                    'A saved readiness choice must name its owner’s real weapon.')
            set_weapon_readiness(engine,actor,weapon,bool(value),source='system:equipment_grips',source_actor_id=aid,
                hand=value if isinstance(value,str) else None)


@hook('journey_encounter_settled')
def retain_grips(session,aid,engine,creature):
    session.state['actors'][aid].setdefault('source_states',{}).setdefault(STATE,{})['readiness']=dict(creature.equipment_readiness)
