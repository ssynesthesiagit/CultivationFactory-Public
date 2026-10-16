"""Public recorded-item contract, shared by item activations and treasure consumers.

normalize_profile(profile) validates an owner's explicit Source Rule declaration.
collect(owner_items, actor_id) derives stable, source-scoped acquisitions from the
existing OwnerItemStore, never from names, narration or test receipts. The optional
runtime_profile opts in; absent profiles leave existing equipment unchanged.
read(actor)/write(engine, actor, inventory, source) carry a JSON inventory in one
persistent condition. Callers operate on copies and commit through write, so cold
reload and event replay retain actual identity, location and charge expenditure.
Hidden facts are not emitted in logs or public choice labels.
"""
import copy
import json

CONDITION = 'condition:typed.acquisition_inventory'
KINDS = {'weapon', 'shield', 'armor', 'implement', 'magic_item', 'tool_set', 'tiny_bundle', 'sealed_container', 'mundane', 'creature', 'secret_law', 'foundation', 'method'}
FLAGS = {'magical', 'cultivated', 'damaged', 'cursed', 'suppressed', 'illusion', 'projection', 'sentient', 'willing', 'forbid_expanded', 'active_spirit', 'active_field', 'nested_space', 'unstable', 'consumed', 'channels_user', 'prerequisites_met', 'instant_don', 'broken'}
BARRIERS = {'legendary', 'secret', 'sacrifice', 'wish', 'resurrection', 'story_recharge', 'permanent', 'strategic', 'destroy_on_use', 'expensive_material', 'weapon_attack'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def normalize_profile(value):
    require(isinstance(value, dict), 'An item profile must be a structured owner declaration.')
    allowed = {'source_rule', 'authority', 'source_cl', 'kind', 'weight_lb', 'cube_ft', 'flags', 'max_charges', 'charges', 'recharge', 'properties', 'object_profile', 'facts', 'concealed', 'conceal_dc', 'attunement_slots', 'expires_scene', 'quantity', 'unit_value', 'shield_bonus', 'resonance_policy'}
    require(set(value) <= allowed, 'Unknown item profile field.')
    p = copy.deepcopy(value)
    require('weight_lb' in p and 'cube_ft' in p,'Record actual item weight and its bounding cube; they cannot be inferred from a label.')
    require(type(p.get('source_cl')) is int and p['source_cl']>=1,'Record the printed Source CL, or the native owner’s sourced grade/creator adjudication; it cannot be inferred from a name.')
    for key in ('source_rule', 'authority'):
        require(type(p.get(key)) is str and 0 < len(p[key]) <= 500, 'Record the item Source Rule and declaring authority.')
    require(p.get('kind') in KINDS, 'Choose the item kind explicitly.')
    for key, default in (('source_cl', 1), ('cube_ft', 1), ('max_charges', 0), ('charges', 0), ('conceal_dc', 10 + int(p.get('source_cl',1))//2), ('attunement_slots', 0), ('quantity',1), ('unit_value',0)):
        p.setdefault(key, default)
        require(type(p[key]) is int and p[key] >= 0, 'Item measurements, charges and authority must be nonnegative whole numbers.')
    from fractions import Fraction
    try:weight=Fraction(p['weight_lb']) if type(p['weight_lb']) in (int,str) else None
    except (ValueError,ZeroDivisionError):weight=None
    require(weight is not None and weight>=0,'Record a nonnegative whole or exact decimal/fraction item weight.')
    require(p['quantity']>=1,'An acquired stack must contain at least one actual object.')
    require(p['charges'] <= p['max_charges'], 'Charges cannot exceed the printed maximum.')
    p.setdefault('flags', {})
    require(isinstance(p['flags'], dict) and set(p['flags']) <= FLAGS and all(type(v) is int and v in (0, 1) for v in p['flags'].values()), 'Declare typed item flags as 0 or 1.')
    if p['flags'].get('sentient') and p['flags'].get('willing'):
        require(type(p.get('expires_scene')) is str and bool(p['expires_scene'].strip()), 'Sentient consent needs an explicit scene expiry.')
    if p['kind']=='tiny_bundle':
        require(p['quantity']==10 and not p['flags'].get('magical') and not p['flags'].get('cultivated'),'A Treasury bundle must be exactly ten identical Tiny mundane objects.')
    p.setdefault('recharge', 'long_rest')
    require(p['recharge'] in {'none', 'short_rest', 'long_rest', 'day', 'month', 'year', 'age', 'cycle', 'story'}, 'Record the printed recharge cycle.')
    for key in ('facts', 'concealed'):
        p.setdefault(key, {})
        require(isinstance(p[key], dict) and all(type(k) is str and type(v) in (str, int) for k,v in p[key].items()), 'Item facts must be named strings or integers.')
    if 'shield_bonus' in p:
        require(type(p['shield_bonus']) is int and p['shield_bonus']>=0,'Record the printed shield bonus including enhancement.')
    if 'object_profile' in p:
        o=p['object_profile']
        require(isinstance(o,dict) and set(o)<={'ac','hp','current_hp','damage_threshold','damage_immunities','material','size'}, 'Record only printed item durability fields.')
        require(all(type(o.get(k)) is int and o[k]>=0 for k in ('ac','hp')), 'Record the real item AC and durability.')
        o.setdefault('current_hp',o['hp'])
        require(type(o['current_hp']) is int and 0<=o['current_hp']<=o['hp'],'Current durability must be within the printed maximum.')
        require(bool(p['flags'].get('damaged')) == (o['current_hp']<o['hp']), 'Declare damaged state consistently with actual item durability.')
        require(not p['flags'].get('broken') or o['current_hp']==0,'A broken item cannot retain durability.')
        require(type(o.get('material')) is str and o['material'] and o.get('size') in {'Tiny','Small','Medium','Large','Huge','Gargantuan'}, 'Record the item material and size.')
    policy=p.get('resonance_policy')
    if policy is not None:
        require(isinstance(policy,dict) and set(policy)<={'denied','reason','absolute','backlash'} and type(policy.get('reason')) is str and bool(policy['reason'].strip()),'A refusal needs its actual printed Source Rule reason.')
        require(isinstance(policy.get('denied'),list) and set(policy['denied'])<={'read','surge','attune','bind','treasury'},'Choose source-scoped resonance procedures.')
        require(type(policy.get('absolute',0)) is int and policy.get('absolute',0) in (0,1),'Declare whether the printed protection is absolute.')
        require(isinstance(policy.get('backlash',[]),list),'Backlash must contain native effects.')
    p.setdefault('properties', [])
    require(isinstance(p['properties'], list), 'Record a list of item properties.')
    names = set()
    for r in p['properties']:
        require(isinstance(r, dict) and set(r) <= {'name', 'text', 'economy', 'duration_seconds', 'charge_cost', 'flags', 'effects', 'prerequisites_met', 'material_paid', 'repeat_same_turn', 'known', 'trigger', 'target_kind', 'range_ft', 'materials', 'min_cl', 'resource_costs', 'requires_physical_grip', 'requires_target_condition'}, 'Unknown item property field.')
        require(type(r.get('name')) is str and r['name'] and r['name'] not in names, 'Item properties need distinct printed names.')
        names.add(r['name'])
        require(not r.get('known') or type(r.get('text')) is str and 0<len(r['text'])<=4000, 'Known item properties need their plain printed effect text.')
        require(r.get('economy') in {'ACTION', 'BONUS_ACTION', 'REACTION', 'NONE'}, 'Record the property action cost.')
        if r.get('trigger')=='on_hit':
            require(r['economy']=='NONE' and r.get('charge_cost')==0 and not r.get('materials') and not r.get('resource_costs'),'An automatic on-hit property cannot waive another action, charge or cost.')
        require(type(r.get('requires_physical_grip',0)) is int and r.get('requires_physical_grip',0) in (0,1),'Physical-grip requirements use an explicit 0/1 flag.')
        require(type(r.get('requires_target_condition','')) is str,'Target condition requirements use a native condition ID.')
        if r.get('economy')=='REACTION':
            from .reaction_triggers import classify_trigger
            require(type(r.get('trigger')) is str and classify_trigger(r['trigger']).runnable, 'Record an executable printed reaction trigger.')
        require(r.get('target_kind','SELF') in {'SELF','ANY_CREATURE','HOSTILE_ENTITY','ALLY_OR_SELF','CELL','OBJECT'}, 'Choose a native property target kind.')
        require('range_ft' not in r or type(r['range_ft']) is int and r['range_ft']>=0, 'Record a whole-foot property range.')
        for key in ('duration_seconds', 'charge_cost'):
            require(type(r.get(key)) is int and r[key] >= 0, 'Record property duration and charge cost as whole numbers.')
        require(isinstance(r.get('flags', []), list) and set(r.get('flags', [])) <= BARRIERS, 'Unknown item property restriction.')
        r.setdefault('min_cl',0)
        require(type(r['min_cl']) is int and r['min_cl']>=0,'Record the printed minimum CL.')
        r.setdefault('resource_costs',[])
        require(isinstance(r['resource_costs'],list) and all(isinstance(c,dict) and set(c)=={'resource_id','amount'} and type(c['resource_id']) is str and c['resource_id'].startswith('resource:') and type(c['amount']) is int and c['amount']>=0 for c in r['resource_costs']),'Property resource costs identify actual native pools and whole amounts.')
        r.setdefault('materials',[])
        require(isinstance(r['materials'],list) and len(r['materials'])<=8,'Record up to eight real material requirements.')
        for m in r['materials']:
            require(isinstance(m,dict) and set(m)<={'source_rule','quantity','consume','minimum_value'} and type(m.get('source_rule')) is str and bool(m['source_rule']), 'Materials identify their actual Source Rule.')
            require(type(m.get('quantity')) is int and m['quantity']>0 and type(m.get('consume')) is int and m['consume'] in (0,1), 'Materials need a positive quantity and explicit consumption.')
            require(type(m.get('minimum_value',0)) is int and m.get('minimum_value',0)>=0,'Material value must be a nonnegative whole number.')
        require('expensive_material' not in r.get('flags',[]) or bool(r['materials']),'Record the actual expensive material; a paid flag cannot waive it.')
        require(isinstance(r.get('effects'), list), 'Record native typed item effects.')
        # Keep declarations JSON-only and prohibit recursive inventory mutations.
        from .typed_executor import BLOCKS
        from .ext import effects
        known=set(BLOCKS)|set(effects())
        require(all(isinstance(e,dict) and e.get('type') in known and safe_item_tree(e) for e in r['effects']), 'Choose registered native item effects.')
        for key in ('prerequisites_met', 'material_paid', 'repeat_same_turn', 'known'):
            require(key not in r or type(r[key]) is int and r[key] in (0,1), 'Property permissions must be explicit flags.')
    if policy and policy.get('backlash'):
        from .typed_executor import BLOCKS
        from .ext import effects
        require(all(isinstance(e,dict) and e.get('type') in set(BLOCKS)|set(effects()) and not str(e['type']).startswith(('inventory_','artifact_')) for e in policy['backlash']),'Backlash uses registered native effects without recursive item manipulation.')
    require(type(p.get('expires_scene', '')) is str, 'Item declaration expiry must name a scene.')
    # Reject floats, opaque objects, booleans and invalid nested keys before persistence.
    def plain(x):
        return x is None or type(x) in (str,int) or isinstance(x,list) and all(plain(v) for v in x) or isinstance(x,dict) and all(type(k) is str and plain(v) for k,v in x.items())
    require(plain(p), 'Item declarations support only JSON strings and integers.')
    return p


def collect(owner_items, actor_id):
    result = {}
    for row in owner_items:
        profile = (row.get('record') or {}).get('runtime_profile')
        if profile is None:
            continue
        uid = row.get('item_uid')
        require(type(uid) is str and uid and uid not in result, 'Acquired items need unique stable identities.')
        result[uid] = {'id': uid, 'name': row['name'], 'owner': actor_id, 'holder': actor_id,
                       'location': 'carried', 'profile': normalize_profile(profile),
                       'charges': profile.get('charges', 0), 'spent': 0, 'surge': 0,
                       'version': 0, 'attuned': 0, 'bound': 0, 'quantity':profile.get('quantity',1),
                       'inventory_key':f'given.{owner_items.index(row)}',
                       'acquisition': {'route': 'owner_gift', 'authority': profile['authority'],
                                       'source_rule': profile['source_rule'], 'recorded_at': row['given_at']}}
    return result


def read(actor):
    held = next((c for c in actor.conditions.values() if c.condition_id == CONDITION), None)
    return json.loads(held.data['inventory']) if held else {}


def write(engine, actor, inventory, source):
    from .ext.condition_ownership import remove_instance
    previous=read(actor)
    for uid,item in inventory.items():
        old=previous.get(uid)
        if old and item.get('placement_declared') and (old.get('location')!=item['location'] or old.get('placement_revision',0)!=item.get('placement_revision',0)):
            for c in list(actor.conditions.values()):
                d=c.data or {}
                if d.get('item_key')==item.get('inventory_key') or d.get('disables_action') in item.get('weapon_actions',[]):
                    if d.get('dropped_at') or d.get('object_location'):
                        require(not d.get('held_by') or d['held_by']==actor.entity_id, 'Another creature controls this item.')
                        remove_instance(engine,actor,c.instance_id,source)
    for c in list(actor.conditions.values()):
        if c.condition_id == CONDITION:
            remove_instance(engine, actor, c.instance_id, source)
    engine._apply_condition(actor, CONDITION, source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'inventory': json.dumps(inventory, sort_keys=True), 'label': 'Recorded item inventory'})
    from .ext.equipment_hands import set_weapon_readiness
    for uid,item in inventory.items():
        old=previous.get(uid)
        if old and item.get('placement_declared') and (old.get('location')!=item['location'] or old.get('placement_revision',0)!=item.get('placement_revision',0)):
            for weapon in item.get('weapon_actions',[]):
                if '.weapon.' in weapon and '#' not in weapon and weapon in engine.action_catalog:
                    set_weapon_readiness(engine,actor,weapon,item['location']=='hand',source=source,source_actor_id=actor.entity_id,hand=item.get('hand'))
    from . import carry
    carry.refresh(engine,actor,source)
    from .ext import run_strict
    run_strict('inventory_committed',engine,actor,inventory,source)


def usable(item, actor_id):
    p = item['profile']; f = p['flags']
    return (item['owner'] == actor_id and item['holder'] == actor_id and item['location'] in {'carried','hand','worn','floating'}
            and not any(f.get(k) for k in ('consumed','suppressed','broken'))
            and item.get('quantity',1)>0 and f.get('prerequisites_met', 0) and (not p['attunement_slots'] or item['attuned']))


def location(actor, key):
    """Explicit placement for an opted-in native inventory key; None is inert."""
    items=read(actor)
    tracked=next((i for i in items.values() if i.get('inventory_key')==key),None)
    if tracked is None:
        return None
    for c in actor.conditions.values():
        d=c.data or {}
        if d.get('item_key')==key or tracked and d.get('disables_action') in tracked.get('weapon_actions',[]):
            if d.get('held_by') and d['held_by']!=actor.entity_id:
                return 'held_elsewhere'
            if d.get('dropped_at'):
                return 'space'
    return next(((i['hand'] if i['hand'].startswith('hand:') else 'hand:'+i['hand']) if i['location']=='hand' and i.get('hand') else i['location'] for i in items.values()
                 if i.get('inventory_key') == key and i.get('placement_declared')), None)


def removed_weight(actor, carrying):
    """Whole-pound authored weight outside carried space, without double counts."""
    removed=0
    for item in read(actor).values():
        original=next((i for i in (carrying or {}).get('items',()) if i.get('key')==item.get('inventory_key')),None)
        if original is None:continue
        weight=float(original.get('weight_lb') or 0)
        if item.get('placement_declared') and item['location'] in {'treasury','space','floating','consumed'}:removed+=weight
        elif item.get('quantity',1)<item['profile'].get('quantity',1):removed+=weight*(1-item['quantity']/item['profile']['quantity'])
    return removed


def controlled(actor,item):
    """Lawful personal control, checked against actual native drop/take state."""
    place=location(actor,item.get('inventory_key'))
    return item['owner']==actor.entity_id and item['holder']==actor.entity_id and place not in {'space','held_elsewhere'}


def attunement_used(bundle,items):
    """Actual campaign slots including native equipment outside the opt-in ledger."""
    return int(bundle.get('inventory_other_attunement_slots',0))+sum(i['profile']['attunement_slots'] for i in items.values() if i['attuned'])


def touching(engine,actor,item):
    """Actual owned touch access, including an unattended recorded item nearby.

    A native transfer to another hand wins over the ledger. Ground coordinates
    come from the committed Drop event/condition or explicit object placement.
    """
    if item['owner']!=actor.entity_id:return False
    position=item.get('position') if item['location']=='space' else None
    for condition in actor.conditions.values():
        data=condition.data or {}
        if data.get('item_key')==item.get('inventory_key') or data.get('disables_action') in item.get('weapon_actions',[]):
            if data.get('held_by') and data['held_by']!=actor.entity_id:return False
            if data.get('dropped_at'):position=data['dropped_at']
    from .gate2_runtime_models import Position
    if position:return engine.grid.distance_ft(actor.position,Position.model_validate(position))<=5 and engine.grid.line_of_physical_transmission(actor.position,Position.model_validate(position))
    if item['location']=='floating':
        point=Position(x=item['point'][0],y=item['point'][1],z=item['point'][2] if len(item['point'])>2 else 0)
        return engine.grid.distance_ft(actor.position,point)<=5 and engine.grid.line_of_physical_transmission(actor.position,point)
    return item['holder']==actor.entity_id and item['location'] in {'carried','hand','worn'}


def resonance_refused(item,procedure,user_cl):
    """Only explicit printed protection/higher item authority can refuse resonance."""
    p=item['profile'];policy=p.get('resonance_policy') or {}
    return procedure in policy.get('denied',[]) and (policy.get('absolute') or p['source_cl']>user_cl)


def weight_lb(profile):
    """Exact source-declared or native-derived physical weight, without floats."""
    from fractions import Fraction
    return Fraction(profile['weight_lb'])


def safe_item_tree(value):
    """Do not hide recursive item/ability mutations in a conditional child tree."""
    if isinstance(value,dict):
        if str(value.get('type','')).startswith(('inventory_','artifact_')):return False
        return all(safe_item_tree(v) for v in value.values())
    if isinstance(value,list):return all(safe_item_tree(v) for v in value)
    return True
