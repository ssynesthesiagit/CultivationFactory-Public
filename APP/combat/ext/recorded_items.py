"""Native collection/continuation adapter for the shared acquisition_inventory.

Consumes the Artifact owner's public contract, preserved from f70e06cd9. The
actual OwnerItemStore gives each item its stable ID, source rule and profile.
No runtime_profile means no compilation, condition, event or journey changes.
The same ledger is consumed by source-bound Assets and item-source features.
"""
from copy import deepcopy
from fractions import Fraction
from . import hook
from .. import acquisition_inventory as inventory
SOURCE='system:recorded_items'

def rebound(previous,item):
    result=deepcopy(previous or item)
    for key in ('weapon_actions','inventory_key','native_record'):
        if key in item:result[key]=deepcopy(item[key])
    return result

def saved(actor):
    return actor.setdefault('source_states',{}).setdefault(SOURCE,{})


@hook('compile_bundle',priority=40)
def collect_actual_items(bundle,info):
    items=inventory.collect(info.get('owner_items',[]),info['actor_id'])
    if not items:return None
    result=deepcopy(bundle);carrying=result.get('carrying') or {};carried=carrying.setdefault('items',[])
    attuned=set((carrying.get('attunement') or {}).get('attuned',[]))
    extra=Fraction(0)
    for uid,item in items.items():
        record=next(r['record'] for r in info['owner_items'] if r['item_uid']==uid)
        item['native_record']=deepcopy(record)
        native=next((r for r in carried if r['key']==item['inventory_key']),None)
        item['weapon_actions']=[entry['owner_action'] for entry in result.get('weapons', [])
            if entry['row'].get('inventory_key') == item['inventory_key']]
        if native and native.get('weapon_action') and native['weapon_action'] not in item['weapon_actions']:
            item['weapon_actions'].append(native['weapon_action'])
        item['attuned']=int(item['inventory_key'] in attuned)
        if native is None:
            weight=inventory.weight_lb(item['profile'])*item['quantity'];extra+=weight
            carried.append({'key':item['inventory_key'],'item_id':uid,'name':item['name'],'quantity':item['quantity'],
                'weight_lb':str(weight),'kind':'item','worn':False,'treasure':True})
    carrying['weight_lb']=str(Fraction(carrying.get('weight_lb','0'))+extra)
    carrying['over']=Fraction(carrying['weight_lb'])>int(carrying.get('capacity_lb',0))
    result['carrying']=carrying;result['acquisition_inventory']=items
    result['inventory_other_attunement_slots']=max(0,int((carrying.get('attunement') or {}).get('used',0))-
        sum(i['profile']['attunement_slots'] for i in items.values() if i['attuned']))
    return result


@hook('match_initialize',priority=-30)
def initialize_actual_items(engine):
    for bundle in getattr(engine,'typed_bundle_documents',[]):
        actor=engine.state.actors.get(bundle['actor_id']);items=bundle.get('acquisition_inventory')
        if actor is not None and items and not inventory.read(actor):inventory.write(engine,actor,deepcopy(items),SOURCE)


@hook('journey_initialize')
def initialize_journey_items(session,aid):
    actor=session.state['actors'][aid];items=actor['bundle'].get('acquisition_inventory')
    if items:
        previous=saved(actor).get('inventory',{})
        items={uid:rebound(previous.get(uid),item) for uid,item in items.items()}
        actor['recorded_inventory']=items
        saved(actor)['inventory']=deepcopy(items)
        actor['bundle']['acquisition_inventory']=deepcopy(items)


@hook('journey_acquired')
def preserve_acquired_items(session,aid,source,receipt):
    actor=session.state['actors'][aid];old=actor.get('recorded_inventory',{});compiled=actor['bundle'].get('acquisition_inventory',{})
    if not old and not compiled:return
    items={uid:rebound(old.get(uid),item) for uid,item in compiled.items()}
    actor['recorded_inventory']=items;actor['bundle']['acquisition_inventory']=deepcopy(items)
    saved(actor)['inventory']=deepcopy(items)


@hook('journey_combat_bundle',priority=-30)
def carry_actual_items(bundle,session,aid):
    items=session.state['actors'][aid].get('recorded_inventory')
    return {**bundle,'acquisition_inventory':deepcopy(items)} if items else None


@hook('journey_snapshot_actor')
def separate_inventory(actor,session,aid,engine):
    keys={key for key,c in actor.conditions.items() if c.condition_id==inventory.CONDITION}
    if not keys:return None
    copy=actor.model_copy(deep=True);copy.conditions={key:c for key,c in copy.conditions.items() if key not in keys}
    return copy


@hook('journey_encounter_settled')
def return_actual_items(session,aid,engine,actor):
    items=inventory.read(actor)
    if items:
        session.state['actors'][aid]['recorded_inventory']=items
        saved(session.state['actors'][aid])['inventory']=deepcopy(items)
        session.state['actors'][aid]['bundle']['acquisition_inventory']=deepcopy(items)


@hook('presentation_hidden_conditions')
def private_item_records(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==inventory.CONDITION]


@hook('carried_item_remaining')
def actual_remaining(engine,actor,item):
    actual=next((i for i in inventory.read(actor).values() if i.get('inventory_key')==item.get('key')),None)
    if actual is not None:return 0 if actual['profile']['flags'].get('consumed') else int(actual.get('quantity',1))
