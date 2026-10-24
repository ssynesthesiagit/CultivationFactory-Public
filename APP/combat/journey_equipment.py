"""Read-only journey adapter for the existing native equipment queries.

Uses acquired bundles, actual encounter conditions, item records and committed
Draw/Stow choices. Materialized ActorState/ConditionInstance views never enter
scene storage or create receipts. There is one readiness policy: native
weapon_delivery/hand_occupancy. No names, appearance or inventory flags add
hands, weapons, proficiency or ownership.
"""
import json
from types import SimpleNamespace
from .gate2_runtime_models import ActorState,ActionDefinition,ConditionInstance,ModifierInstance,Position
STATE='system:equipment_grips'


def readiness(row):
    """Saved Draw/Stow choices in the engine's own readiness shape: weapon id -> 1/0 or its hand.

    The native equipment model spells readiness as ActorState.equipment_readiness,
    so journeys persist exactly that mapping and nothing else.
    """
    stored=row.get('source_states',{}).get(STATE,{}).get('readiness') or {}
    return {weapon:value for weapon,value in stored.items() if type(weapon) is str and type(value) in (int,str)}


class JourneyReadView(SimpleNamespace):
    """Query protocol over actual journey data; never a resolving combat engine."""
    @staticmethod
    def _has_condition(actor,condition_id):
        return any(c.condition_id==condition_id for c in actor.conditions.values())


def projection(session,aid):
    actors={};catalog={};bundles=[]
    for who,row in session.state['actors'].items():
        bundle=row['bundle'];bundles.append(bundle);template=bundle['actor_template']
        snapshot=row.get('encounter_snapshot') or {}
        conditions={key:ConditionInstance.model_validate(json.loads(raw)) for key,raw in snapshot.get('conditions',{}).items()}
        from .ext.body_modes_scene_resources import AUTHORITY,SUPPRESSION
        managed=row.get('source_states',{}).get(AUTHORITY,{})
        modifiers={}
        for n,effect in enumerate(managed.get('effects',[])):
            if effect.get('remaining_num',1)<=0:continue
            model=json.loads(effect['model'])
            if effect['kind']=='condition':
                c=ConditionInstance.model_validate({'instance_id':'query:body:'+str(n),'target_id':who,
                    'applied_sequence':0,**model})
                conditions[c.instance_id]=c
            elif effect['kind']=='modifier':
                m=ModifierInstance.model_validate({'modifier_id':'query:body:'+str(n),'target_id':who,**model})
                modifiers[m.modifier_id]=m
        for scope,record in managed.get('sources',{}).items():
            if record.get('kind')!='cultivation_suppression' or record['expires_at']<=session.clock():continue
            c=ConditionInstance(instance_id='query:body-source:'+scope,condition_id=SUPPRESSION,
                source_definition_id=AUTHORITY,source_actor_id=who,target_id=who,applied_sequence=0,
                data=dict(record['value']))
            conditions[c.instance_id]=c
        items=row.get('recorded_inventory',bundle.get('acquisition_inventory',{}))
        if items:
            from .acquisition_inventory import CONDITION
            c=ConditionInstance(instance_id='query:journey.inventory',condition_id=CONDITION,source_definition_id='inventory:acquisition',
                source_actor_id=who,target_id=who,applied_sequence=0,expires_on='UNTIL_REMOVED',data={'inventory':json.dumps(items,sort_keys=True)})
            conditions[c.instance_id]=c
        data={key:value for key,value in template.items() if key in ActorState.model_fields}
        data.update(position=Position.model_validate(row['position']),current_hp=int(snapshot.get('current_hp',template['maximum_hp'])),
            temporary_hp=int(snapshot.get('temporary_hp',0)),active=bool(snapshot.get('active',1)),
            life_state=snapshot.get('life_state') or None,movement_remaining_ft=int(template['speed_ft']),
            resources=dict(row['resources']),resource_maximums={r['resource_id']:r['maximum'] for r in template['resources']},
            conditions=conditions,modifiers=modifiers,equipment_readiness=readiness(row))
        actors[who]=ActorState.model_validate(data)
        for raw in bundle['action_catalog']:
            action=ActionDefinition.model_validate(raw);catalog[action.source_definition_id]=action
    engine=JourneyReadView(action_catalog=catalog,typed_bundle_documents=tuple(bundles),grid=session.grid,
        typed_passive_rows={who:row['bundle'].get('typed_passives',[]) for who,row in session.state['actors'].items()},
        state=SimpleNamespace(actors=actors,state_version=session.state['revision'],event_sequence=len(session.state['events']),current_actor_id=None,zones={}))
    return engine,actors[aid]


def ready_weapons(session,aid):
    from .weapon_delivery import ready_weapons as native_ready
    engine,actor=projection(session,aid)
    return native_ready(engine,actor)


def grip_options(session,aid):
    from .ext.hand_occupancy import weapon_grips,free_hands,resting_hands
    from .weapon_delivery import available_weapons
    engine,actor=projection(session,aid)
    grips=weapon_grips(engine,actor);available=available_weapons(engine,actor)
    return [a for a in engine.action_catalog.values() if a.owner_id==aid
        and (g:=a.parameters.get('equipment_grip')) and g['weapon'] in available
        and (bool(g['held'])!=(g['weapon'] in grips))
        and (not g['held'] or len(free_hands(engine,actor))>=resting_hands(available[g['weapon']]))]
