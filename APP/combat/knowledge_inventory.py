"""Question scopes on actual native carried, dropped and transferred items.

Consumers: the five information readers and shared world-fact scope admission.
The inventory producer remains combat.carry and its real native item keys and
location/quantity receipts. No item, ownership or parallel object ID is created.
Source facts use the existing actor subject + item:<native key> scope. Observer
references are opaque so examining another's item does not disclose its owner.
"""
from hashlib import sha256
from .carry import carrying_of,quantity_exhausted
from .gate2_runtime_models import Position
from .encounter_sources import facts


def reference(owner,key):return 'examined-item:'+sha256((owner+'\0'+key).encode()).hexdigest()[:24]


def locate(engine,owner,item):
    if type(item.get('quantity')) is int and item['quantity']<=0 or quantity_exhausted(engine,owner,item):return None
    rows=[c.data for c in owner.conditions.values() if c.data.get('item_key')==item['key']
        or item.get('weapon_action') and c.data.get('disables_action')==item['weapon_action']]
    marker=next((data for data in reversed(rows) if data.get('held_by') or data.get('dropped_at')),None)
    if marker and marker.get('held_by'):
        holder=engine.state.actors.get(marker['held_by'])
        return (holder.position,holder.entity_id) if holder is not None else None
    if marker and marker.get('dropped_at'):
        return Position.model_validate(marker['dropped_at']),None
    return owner.position,owner.entity_id


def options(engine,reader,action):
    from .ext.knowledge_readings import source_of,KINDS,QI,TRACE,VESSEL,VENOM,METAL
    from . import senses
    from .targeting import line_of_effect
    source=source_of(action)
    if source not in KINDS or action.owner_id!=reader.entity_id or action.source_definition_id not in reader.action_ids:return {}
    found={}
    for owner in engine.state.actors.values():
        for item in (carrying_of(engine,owner.entity_id) or {}).get('items',[]):
            key=item['key'];scope='item:'+key
            data=facts(engine,owner.entity_id,scope)
            location=locate(engine,owner,item)
            if location is None:continue
            position,holder_id=location
            if not engine.grid.in_bounds((position.x,position.y)):continue
            distance=engine._effect_distance_to_cell(reader,position)
            if distance>(action.range_ft or 0) or not line_of_effect(engine,reader,destination=position):continue
            # Unknown item exposure never reveals a hidden inventory. Visible or
            # physically presented items still need native range/medium/contact.
            visible=data.get('item.visible',{}).get('value') is True and senses.perceives(engine,reader,senses.cell_probe(position),sight_only=source==METAL)
            if visible and holder_id and holder_id!=reader.entity_id:
                visible=senses.perceives(engine,reader,engine.state.actors[holder_id],locate_concealed=True,sight_only=source==METAL)
            touch=data.get('item.touchable',{}).get('value') is True and distance<=5
            if not visible and not (touch and source in {QI,TRACE,VESSEL,VENOM}):continue
            kind=data.get('subject.kind',{}).get('value') or ('weapon' if item.get('weapon_action') else 'armor' if item.get('kind')=='armor' else 'object')
            if source==TRACE:
                if kind not in KINDS[TRACE] and data.get('trace.present',{}).get('value') is not True:continue
            elif source==METAL:
                if not visible or data.get('metal.bearing',{}).get('value') is not True:continue
            elif source==VESSEL:pass  # an actual native item is an object Vessel
            elif kind not in KINDS[source]:continue
            public=data.get('item.public_name',{}).get('value')
            name=public or item['name'] if owner.entity_id==reader.entity_id else public or ('the examined '+kind.replace('_',' '))
            ref=reference(owner.entity_id,key)
            found[ref]={'owner_id':owner.entity_id,'item_key':key,'scope':scope,'kind':kind,'name':name,'reference':ref}
    return found
