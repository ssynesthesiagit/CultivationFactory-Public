"""Physical inventory identity shared by Blacksmith work and native tool checks.

An identity is (original inventory owner, item key), never a creature's label.
Queries follow journaled drop/transfer locations and never equip or create items.
Tool-check effects opt in with tool_item_key; without that explicit provenance a
check does not claim to use an inventory tool. No ability ids occur here.
"""
from . import carry
from .attack_provenance import describe
from .weapon_delivery import physical_weapon_id


def carried_item(engine, owner_id, key):
    owner = engine.state.actors.get(owner_id)
    item = carry.item_of(carry.carrying_of(engine, owner_id), key=key)
    if owner is None or item is None:
        return None
    carrier_id = carry.item_carrier(engine, owner, key)
    if carrier_id is None:
        return None
    kind = ('weapon' if item.get('weapon_action') else 'shield' if item.get('shield')
            else 'armor' if item.get('worn') and carrier_id == owner_id else 'object')
    return {'owner': owner_id, 'key': key, 'carrier': carrier_id, 'kind': kind,
            'name': str(item.get('name') or 'Carried item'), 'item': dict(item)}


def inventory(engine):
    return [found for owner in engine.state.actors.values()
            for item in (carry.carrying_of(engine, owner.entity_id) or {}).get('items', [])
            if (found := carried_item(engine, owner.entity_id, item['key'])) is not None]


def attack_item(engine, actor, spec):
    """Bind the shared resolving weapon descriptor to its original inventory row.

    Explicit unarmed packets never borrow identity from a held weapon. Derived
    and borrowed attacks use the same ancestry contract as other weapon riders.
    """
    packet = describe(engine, actor, spec)
    if packet['delivery'] != 'weapon':
        return None
    source = packet['weapon_source_id']
    # Native borrowed actions keep an actor-local catalogue/grip identity.
    # Their possession binding names the original inventory weapon instead.
    # Apply that binding only here, after shared packet ancestry has resolved;
    # changing global weapon identity would invalidate the borrower's grip keys.
    weapon = engine.action_catalog.get(source)
    required = (weapon.parameters if weapon else packet['parameters']).get('requires_held_weapon')
    if required:
        source = physical_weapon_id(required)
    return next((found for found in inventory(engine)
                 if found['carrier'] == actor.entity_id and found['kind'] == 'weapon'
                 and (found['item'].get('weapon_action') or '').split('#')[0] == source), None)


def tool_use(engine, actor, effect):
    """Native consumer's opt-in exact tool identity, only while actually carried."""
    key = effect.get('tool_item_key')
    if not isinstance(key, str) or not key:
        return None
    owner = effect.get('tool_owner_id') or actor.entity_id
    found = carried_item(engine, owner, key)
    if found is None or found['carrier'] != actor.entity_id or found['kind'] != 'object':
        return None
    return {'owner': owner, 'key': key}
