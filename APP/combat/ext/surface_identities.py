"""Pure native surface identities shared by Earth Foundations and Glass.

Equipment retains its compiled inventory key through held_by/dropped_at records.
This is a location adapter over carry's public identity; it creates no object,
Anchor, durability, ownership or item supply schema.
"""
from ..gate2_runtime_models import Position


def item_position(engine, owner_id, key):
    from .. import carry
    owner = engine.state.actors.get(owner_id)
    if owner is None: return None
    item = carry.item_of(carry.carrying_of(engine, owner_id), key=key)
    if item is None or carry.remaining_quantity(engine, owner, item) <= 0: return None
    for condition in owner.conditions.values():
        data = condition.data or {}
        if data.get('item_key') != key and not (item.get('weapon_action') and data.get('disables_action') == item['weapon_action']):
            continue
        if data.get('held_by'):
            holder = engine.state.actors.get(data['held_by'])
            return holder.position if holder else None
        if data.get('dropped_at'):
            return Position.model_validate(data['dropped_at'])
    return owner.position


def position(engine, record):
    kind = record['kind']
    if kind == 'fixed':
        return Position(x=record['x'], y=record['y'], z=record['z'])
    if kind == 'item': return item_position(engine, record['actor_id'], record['item_key'])
    if kind == 'object':
        obj = engine.state.objects.get(record['object_id'])
        return obj.position if obj is not None and not obj.destroyed else None
    actor = engine.state.actors.get(record['actor_id'])
    return actor.position if actor is not None else None
