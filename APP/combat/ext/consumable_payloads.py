"""Ordinary physical consumable delivery for items and Activation Trap.

Public API: available, reserve, release, activate. Identity and stock come from
carry.carrying_of / holds / remaining_quantity, the same compiled starting-kit
inventory used by ammunition and dropped equipment. No item is granted here.
A source plug-in can provide ordinary_consumable_spec(engine, owner, item),
returning a typed definition with effects, optional numbers, area and name.
Unknown items remain unknown until an actual typed source defines their ordinary nature; known treasures cannot enter this channel. Item names and identifier namespaces do not classify an external Alchemy/Tinker batch.
All reservations are integer counters in the established round-persistent flags.
"""
from copy import deepcopy
from . import hook, effect, run_strict, placed
from .. import carry

PREFIX = '_round_payload_reserved:'
ORDINARY = 'tianxia.mortal.gear.'
PRIVATE_EVENTS = frozenset(('ITEM_STOCK_RESERVED', 'ITEM_STOCK_RECOVERED', 'ORDINARY_ITEM_DEFINITION_RECORDED'))


def definition(engine, owner, item):
    if item.get('treasure'):
        return None
    replies = [r for r in run_strict('ordinary_consumable_spec', engine, owner, item) if r is not None]
    if len(replies) > 1:
        raise ValueError('An ordinary item must have exactly one delivery definition')
    if replies and type(replies[0].get('fragile')) is int and replies[0]['fragile'] in (0,1):
        return deepcopy(replies[0])
    return None


def available(engine, owner):
    """Actual carried, unreserved batches, never labels or alleged ownership."""
    return [(item, spec, carry.remaining_quantity(engine, owner, item))
            for item in (carry.carrying_of(engine, owner.entity_id) or {}).get('items', ())
            if carry.holds(engine, owner, item['key']) and (spec := definition(engine, owner, item))]


@hook('carried_item_remaining')
def remaining(engine, owner, item):
    reserved = int(owner.turn_flags.get(PREFIX + item['key'], 0))
    return max(0, int(item.get('quantity', 1)) - reserved) if reserved else None


def reserve(engine, owner, key, amount):
    """Move actual stock out of carried availability into one physical device."""
    from ..journey import require, integer
    match = next((row for row in available(engine, owner) if row[0]['key'] == key), None)
    require(match is not None and integer(amount, 1) and amount <= match[2], 'Choose enough of your own carried consumable.')
    item, spec, _ = match
    flag = PREFIX + key
    owner.turn_flags[flag] = int(owner.turn_flags.get(flag, 0)) + amount
    placed.note(engine, 'item:reserve', owner, f"{owner.display_name} loads {amount} {spec['name']} into a device.")
    return {'key': key, 'item_id': item['item_id'], 'remaining': amount, 'spec': spec, 'owner': owner.entity_id}


def release(engine, owner, payload):
    """Return unused stock once to its recorded owner; callers empty the device."""
    from ..journey import require
    require(payload['owner'] == owner.entity_id, 'Recover the recorded owner’s item stock.')
    amount = int(payload['remaining'])
    flag = PREFIX + payload['key']
    require(0 <= amount <= int(owner.turn_flags.get(flag, 0)), 'This payload has no reserved stock to return.')
    owner.turn_flags[flag] -= amount
    placed.note(engine, 'item:recover', owner, f"{owner.display_name} recovers {amount} unused {payload['spec']['name']}.")


def activate(ctx, payload, origin, target, *, origin_record=None):
    """Resolve the item's own effects/numbers at the set origin or trigger target.

    Consumer owns the device's load decrement. This function neither reserves
    stock again nor spends an extra action, focus or item on delivery.
    """
    from ..typed_executor import Context, run_effects
    from ..action_geometry import activate as at_origin
    spec = payload['spec']
    numbers = {**ctx.numbers, **spec.get('numbers', {})}
    typed = {**ctx.typed, 'numbers': numbers, 'source': 'item:' + payload['item_id']}
    targets=[target]
    if spec.get('area'):
        from ..typed_executor import area_cells
        cells=area_cells(ctx.engine,origin,origin,spec['area'])
        targets=[a for a in ctx.engine.state.actors.values() if a.active and ctx.engine._footprint_intersects(a,cells)]
        typed['area']=spec['area']
    intent = ctx.intent.model_copy(update={'destination': origin}) if ctx.intent else None
    sub = Context(ctx.engine, ctx.actor, ctx.action, intent, typed, targets, targets[0] if len(targets)==1 else None, {})
    with at_origin(ctx.engine, ctx.actor, ctx.action.source_definition_id,
                   origin_record or {'id': 'item:' + payload['item_id'], 'label': spec['name'], 'position': origin.model_dump(mode='json')}):
        def redirected(value):
            if isinstance(value,list):
                return [redirected(v) for v in value]
            if isinstance(value,dict):
                return {k:('target' if k=='applies_to' and v=='self' else redirected(v)) for k,v in value.items()}
            return value
        run_effects(sub, redirected(spec['effects']))


@hook('ordinary_consumable_spec')
def mundane(engine, owner, item):
    """2024 ordinary Acid; no spell or treasure payload is admitted by name.

    Source: SRD 5.2.1 / D&D Free Rules, Equipment, Acid. The save is the
    thrower's Dexterity plus PB, rather than Trap key ability or an attack.
    Additional item families supply their own source-backed provider.
    """
    if item['item_id'] != ORDINARY + 'acid':
        return None
    for bundle in engine.typed_bundle_documents:
        if bundle['actor_id'] == owner.entity_id:
            return (bundle.get('ordinary_item_specs') or {}).get(item['item_id'])
    return None


@hook('compile_bundle')
def compile_specs(bundle, info):
    """Seal item mechanics from acquired equipment and actual ability scores."""
    from .ordinary_consumables import compiled_specs
    specs=compiled_specs(bundle,info)
    if any(i['item_id']==ORDINARY+'acid' for i in bundle.get('carrying',{}).get('items',())):
        specs[ORDINARY+'acid']={
            'name':'Acid','fragile':1,'numbers':{'save_dc':8+int(info['mods'].get('DEX',0))+int(info['numbers']['pb'])},
            'effects':[{'type':'save','ability':'dex','on_fail':[
                {'type':'damage','dice':{'count':2,'sides':6},'damage_types':['acid'],'applies_to':'target'}]}]}
    if not specs:
        return None
    out=deepcopy(bundle)
    out['ordinary_item_specs']=specs
    return out


def journey_specs(actor):
    """Validated persisted recipes plus canonical compiled definitions.

    Used by journey reservations and the construction picker as well as the
    encounter projection; canonical definitions always retain precedence.
    """
    return {**{key: validate_definition(receipt['spec'])
               for key, receipt in actor.get('declared_item_specs', {}).items()},
            **(actor['bundle'].get('ordinary_item_specs') or {})}


def journey_available(actor):
    """Source-defined batches still possessed after encounter continuation."""
    specs = journey_specs(actor)
    flags = actor.get('payload_stock', {})
    return [(item, specs[item['item_id']], amount)
            for item in actor['bundle'].get('carrying', {}).get('items', ())
            if item['item_id'] in specs and carry.journey_holds(actor, item['key'])
            and (amount := int(item['quantity']) - int(flags.get(PREFIX + item['key'], 0))) > 0]


def reserve_journey(session, aid, key, amount):
    """Same acquired stock identity/counters while no encounter is running."""
    from ..journey import require, integer
    actor=session.state['actors'][aid]
    match=next((row for row in journey_available(actor) if row[0]['key']==key),None)
    flags=actor.setdefault('payload_stock',{})
    require(match is not None and integer(amount,1) and amount <= match[2],
            'Choose enough actually acquired ordinary consumable stock.')
    item, spec, _ = match
    flags[PREFIX+key]=int(flags.get(PREFIX+key,0))+amount
    session.emit('ITEM_STOCK_RESERVED',aid,item_key=key,quantity=amount)
    return {'key':key,'item_id':item['item_id'],'owner':aid,'remaining':amount,'spec':deepcopy(spec)}


def release_journey(session, aid, payload):
    from ..journey import require
    flags=session.state['actors'][aid].setdefault('payload_stock',{})
    flag=PREFIX+payload['key']
    require(payload['owner']==aid and 0 <= payload['remaining'] <= flags.get(flag,0),
            'Return only actual unused stock to its recorded owner.')
    flags[flag]-=payload['remaining']
    session.emit('ITEM_STOCK_RECOVERED',aid,item_key=payload['key'],quantity=payload['remaining'])


@hook('journey_persistent_fields')
def persistent_stock():
    return ('payload_stock','declared_item_specs')


@hook('journey_combat_bundle')
def stock_into_encounter(bundle, session, aid):
    actor=session.state['actors'][aid]
    flags=actor.get('payload_stock')
    definitions=actor.get('declared_item_specs')
    if flags is None and not definitions:
        return None
    out=deepcopy(bundle)
    if flags is not None:
        out['payload_stock']=dict(flags)
    if definitions:
        out['ordinary_item_specs']=journey_specs(actor)
    return out


@hook('match_initialize')
def initialize_stock(engine):
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is not None:
            actor.turn_flags.update(bundle.get('payload_stock') or {})


@hook('journey_encounter_settled')
def stock_from_encounter(session, aid, engine, creature):
    flags={k:int(v) for k,v in engine.state.actors[aid].turn_flags.items() if k.startswith(PREFIX)}
    if flags:
        session.state['actors'][aid]['payload_stock']=flags


def validate_definition(spec):
    """Bounded ordinary item grammar; no resources, ownership or code grants.

    External recipes remain unknown until the table owner supplies their actual
    source text and typed mechanics. This validates a definition, never declares
    a hit, save outcome, successful construction or completed activation.
    """
    from ..journey import require, integer
    from ..fact_consent_admission import plain
    require(isinstance(spec,dict) and {'name','effects','fragile'} <= set(spec) <= {'name','effects','numbers','area','fragile'},
            'Supply an ordinary item name, effects and optional numbers/area/fragility.')
    require(type(spec['fragile']) is int and spec['fragile'] in (0,1), 'Record whether the actual payload is fragile.')
    require(plain(spec) and isinstance(spec['name'],str) and 0<len(spec['name'])<=200,
            'Ordinary definitions use bounded integer/string data.')
    require(isinstance(spec['effects'],list) and 1<=len(spec['effects'])<=32, 'Supply the item’s actual typed effects.')
    def effects(rows,depth=0):
        require(depth<=8 and isinstance(rows,list) and len(rows)<=32, 'Ordinary effects must remain bounded.')
        for row in rows:
            require(isinstance(row,dict) and row.get('type') in ('save','damage','healing','temp_hp','condition','remove_condition','physical_payload_fact'),
                    'An ordinary recipe may resolve physical effects, saves, damage and conditions, never grant an ability or resource.')
            if row['type']=='save':
                require(set(row)<= {'type','ability','on_fail','on_success','applies_to'}, 'Use only ordinary saving throw fields.')
                require(row.get('ability') in ('str','dex','con','int','wis','cha'), 'Use a named saving throw ability.')
                effects(row.get('on_fail',[]),depth+1); effects(row.get('on_success',[]),depth+1)
            if row['type'] in ('damage','healing','temp_hp'):
                dice=row.get('dice',{})
                require(not dice or (set(dice)=={'count','sides'} and integer(dice['count'],1) and dice['count']<=20
                        and integer(dice['sides'],2) and dice['sides']<=100), 'Use the printed ordinary damage dice.')
                require(set(row)<= {'type','dice','flat','damage_types','applies_to'} and type(row.get('flat',0)) is int,
                        'Use only printed ordinary damage fields.')
            if row['type']=='remove_condition':
                require(set(row)<= {'type','condition','applies_to'} and row.get('condition') in ('poisoned','blinded','deafened'),
                        'Remove only the printed ordinary physical condition.')
            if row['type']=='condition':
                require(row.get('condition') in ('prone','blinded','deafened','poisoned','restrained'),
                        'Use a named ordinary physical condition.')
                require(set(row)<= {'type','condition','applies_to','duration'}, 'Ordinary conditions cannot install arbitrary rules or grants.')
                duration=row.get('duration','instant')
                require(duration=='instant' or (isinstance(duration,dict) and set(duration)=={'kind','amount'}
                        and duration['kind'] in ('rounds','minutes','hours') and integer(duration['amount'],1)
                        and duration['amount']<=100), 'Use a supported printed duration.')
            if row['type']=='physical_payload_fact':
                require(set(row)=={'type','text'} and isinstance(row['text'],str) and 0<len(row['text'])<=500,
                        'Describe the actual harmless physical activation without inventing a penalty.')
    effects(spec['effects'])
    numbers=spec.get('numbers',{})
    require(isinstance(numbers,dict) and set(numbers)<= {'save_dc'} and all(integer(v,1) and v<=100 for v in numbers.values()),
            'Record only the item’s printed fixed save DC.')
    def saves(rows):
        return any(r['type']=='save' or saves(r.get('on_fail',[])) or saves(r.get('on_success',[])) for r in rows)
    require(not saves(spec['effects']) or 'save_dc' in numbers, 'A save recipe must supply its actual printed save DC.')
    area=spec.get('area',{})
    require(not area or (isinstance(area,dict) and set(area)=={'shape','size_ft'} and
            area['shape'] in ('sphere','cube') and integer(area['size_ft'],5) and area['size_ft']<=120 and area['size_ft']%5==0),
            'Record an ordinary item’s printed whole-foot sphere or square area.')
    return deepcopy(spec)


@hook('journey_admission')
def admit_definition(session,aid,kind,payload,reason):
    if kind!='ordinary_consumable_definition':
        return None
    from ..journey import require
    from ..fact_consent_admission import digest
    from hashlib import sha256
    require(set(payload)=={'item_id','nature','source_text','source_sha256','spec'}, 'Record the exact ordinary item source and typed definition.')
    require(payload['nature']=='ordinary_consumable', 'Magical, charged and technique-bearing items require their own Script source.')
    actor=session.state['actors'][aid]
    item=next((i for i in actor['bundle'].get('carrying',{}).get('items',()) if i['item_id']==payload['item_id']),None)
    require(item is not None and not item.get('treasure'),
            'This path defines an ordinary item you actually acquired; it cannot grant stock or permit magic items.')
    require(item['item_id'] not in (actor['bundle'].get('ordinary_item_specs') or {}), 'A committed canonical item definition cannot be overridden.')
    text=payload['source_text']
    require(isinstance(text,str) and 0<len(text)<=16000 and sha256(text.encode()).hexdigest()==payload['source_sha256'],
            'Record the real source text and its matching SHA-256.')
    spec=validate_definition(payload['spec'])
    receipt={'item_id':item['item_id'],'nature':payload['nature'],'source_text':text,'source_sha256':payload['source_sha256'],
             'spec':spec,'authority':'GM','provenance':reason}
    receipt['receipt_id']=digest(receipt)
    actor.setdefault('declared_item_specs',{})[item['item_id']]=receipt
    actor['bundle'].setdefault('ordinary_item_specs',{})[item['item_id']]=spec
    session.emit('ORDINARY_ITEM_DEFINITION_RECORDED',aid,item_id=item['item_id'],receipt_id=receipt['receipt_id'])
    return True


@effect('physical_payload_fact')
def physical_fact(ctx,row):
    placed.note(ctx.engine,ctx.source,ctx.actor,row['text'],ctx.targets)


@hook('journey_view')
def definition_privacy(state, viewer):
    if not any(a.get('declared_item_specs') or a.get('payload_stock') for a in state['actors'].values()) and not any(
            event.get('kind') in PRIVATE_EVENTS for event in state.get('events', ())):
        return None
    out=deepcopy(state)
    out.pop('replay_base',None); out.pop('command_journal',None)
    for aid,actor in out['actors'].items():
        if aid==viewer:
            continue
        actor.pop('payload_stock',None)
        actor['bundle'].pop('payload_stock',None)
        private=actor.pop('declared_item_specs',{})
        for key in private:
            actor['bundle'].get('ordinary_item_specs',{}).pop(key,None)
    out['events'] = [event for event in out.get('events', ())
                     if event.get('actor_id') == viewer or event.get('kind') not in
                     PRIVATE_EVENTS]
    return out
