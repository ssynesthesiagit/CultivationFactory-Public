"""What a Factory fighter carries during a fight (owner 2026-09-27: "we should have a tab for items and equipment.
Dropping things should also be an option"; "we should have encumberance update with the state of the time").

The compiled bundle's ``carrying`` (combat/factory_compiler.py _carrying) lists the character's items and weights, its
capacity and its Speed. In a fight the load changes: an item dropped (Drop, free), a weapon knocked away or taken by
someone else, another's weapon picked up. ``refresh`` reweighs the load from the fight's own state -- the Disarmed and
"dropped" conditions, which are in the event log -- and keeps Speed in step: over capacity it is at most 5 feet (2024),
under it the character's own. The change is a condition (Encumbered / Unburdened) carrying the Speed difference, so a
saved fight replays it; during the creature's own turn the movement it has left changes by the difference at once.
"""

from __future__ import annotations

from typing import Any

PREFIX = "condition:typed."
DROPPED = PREFIX + "dropped_item"
ENCUMBERED, UNBURDENED = PREFIX + "encumbered", PREFIX + "unburdened"


def carrying_of(engine: Any, actor_id: str) -> dict[str, Any] | None:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor_id:
            return bundle.get("carrying")
    return None


def _pounds(text: Any) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def item_of(carrying: dict[str, Any] | None, *, key: str | None = None, weapon_action: str | None = None) -> dict[str, Any] | None:
    for item in (carrying or {}).get("items") or []:
        if (key and item.get("key") == key) or (weapon_action and item.get("weapon_action") == weapon_action.split("#")[0]):
            return item
    return None


def object_units(owner_id: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    """Individual physical objects for storage and exact-object transfers.

    Compiled rows retain their quantity and total weight. A multi-unit row's
    stable identities are owner|key|unit:N; singleton identities stay owner|key.
    This is a projection, never a mutation of the sealed inventory bundle.
    """
    count = item.get('quantity', 1)
    count = max(0, count) if type(count) is int else 1
    identity = f"{owner_id}|{item['key']}"
    if count <= 1:
        return [{**item, 'object': identity}] if count else []
    pounds = _pounds(item.get('weight_lb')) / count
    return [{**item, 'quantity': 1, 'weight_lb': f'{pounds:g}',
             'worn': bool(item.get('worn')) and number == 1,
             'name': f"{item.get('name') or 'Object'} (copy {number})",
             'object': f'{identity}|unit:{number}'} for number in range(1, count + 1)]


def object_item(engine: Any, owner_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a location record to its exact unit, including its share of load."""
    item = item_of(carrying_of(engine, owner_id), key=data.get('item_key'),
                   weapon_action=data.get('disables_action'))
    identity = str(data.get('object_id') or '')
    if item is not None and '|unit:' in identity:
        return next((unit for unit in object_units(owner_id, item) if unit['object'] == identity), None)
    return item


def inventory_objects(engine: Any, actor: Any, item: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep untouched stacks aggregate; project split stacks into stable units.

    Possession and Drop share this view. Unit locations on the original owner
    are the journaled opt-in; actors without them retain their compiled model.
    """
    identity = f"{actor.entity_id}|{item['key']}"
    split = any(str((row.data or {}).get('object_id') or '').startswith(identity + '|unit:')
                for row in actor.conditions.values())
    return object_units(actor.entity_id, item) if split else [{**item, 'object': identity}]


def split_object_location(engine: Any, owner: Any, item: dict[str, Any], source: str) -> None:
    """Fan out a whole-stack location before moving a single unit out of it.

    Storage and transfer providers use relocate_object, so receiving a stack
    before splitting it cannot restore its siblings to the original owner.
    Each removal/application is journaled; all persisted identity fields are text.
    """
    identity = f"{owner.entity_id}|{item['key']}"
    for iid, row in list(owner.conditions.items()):
        data = row.data or {}
        if (data.get('object_id', f"{owner.entity_id}|{data.get('item_key', '')}") != identity
                or not (data.get('held_by') or data.get('dropped_at') or data.get('stashed_by'))):
            continue
        engine._remove_condition_instance(owner, iid, source, expected=row)
        for unit in object_units(owner.entity_id, item):
            engine._apply_condition(owner, row.condition_id, source, owner.entity_id, expires_on='UNTIL_REMOVED',
                data={**data, 'object_id': unit['object'], 'item_name': unit['name'],
                      'weight_lb': unit['weight_lb']})


def drop_split_stack(engine: Any, actor: Any, item: dict[str, Any], source: str) -> bool:
    """Drop the carried units of a split row, leaving stored/taken units alone.

    The ordinary row-level Drop action still drops all available units, and
    Pick up can recover each ground record in turn. False leaves the historical
    unsplit path unchanged. This adapter is shared by the native item executor
    and any future inventory provider using unit locations.
    """
    objects = inventory_objects(engine, actor, item)
    if not any('|unit:' in obj['object'] for obj in objects):
        return False
    from .ext.scoundrel_riders import possessions
    available = {row['object'] for row in possessions(engine, actor)}
    for obj in objects:
        if obj['object'] in available:
            relocate_object(engine, obj['object'],
                {'item_name': obj['name'], 'dropped_at': actor.position.model_dump(mode='json'),
                 **({'disables_action': item['weapon_action']} if item.get('weapon_action') else {})},
                source, actor.entity_id, DROPPED)
    return True


def _condition_weight(engine: Any, owner_id: str, data: dict[str, Any]) -> float:
    item = object_item(engine, owner_id, data)
    return _pounds((item or {}).get("weight_lb"))


def owned_item_location(actor: Any, key: str) -> str | None:
    """Explicit journaled location on its original owner, or no override.

    Hand occupancy and shield permission read the same opt-in relocation record.
    ``carried`` reserves no hand; ``hand:<part>`` reserves exactly that part.
    Markerless saved equipment keeps its compiled default location.
    """
    return next((str(data['object_location']) for row in actor.conditions.values()
                 if (data := row.data or {}).get('item_key') == key
                 and ('|unit:' not in str(data.get('object_id') or '')
                      or str(data['object_id']).endswith('|unit:1'))
                 and data.get('held_by') == actor.entity_id and data.get('object_location')), None)


def clear_owned_item_location(engine: Any, actor: Any, key: str, source: str) -> dict[str, Any]:
    """Retire opt-in owned placement before ordinary Drop or Pick up.

    One physical object's location must transition rather than accumulate. Removal
    is journaled before the caller writes a ground record (Drop) or restores the
    compiled inventory (Pick up). Return only stable identity fields for the next
    record. Markerless equipment/transfer records retain their original behavior.
    """
    identity = {}
    for iid, row in list(actor.conditions.items()):
        data = row.data or {}
        if data.get('item_key') != key or data.get('held_by') != actor.entity_id or not data.get('object_location'):
            continue
        identity.update({field: data[field] for field in ('owner', 'object_id') if field in data})
        del actor.conditions[iid]
        engine._append_event('CONDITION_REMOVED', source, actor_id=actor.entity_id,
                             target_ids=(actor.entity_id,),
                             payload={'condition_id': row.condition_id, 'instance_id': iid})
    return identity


def lost_to_another_hand(actor: Any, key: str) -> bool:
    """Whether this item is out of the actor's hands: lying where it was dropped,
    or now in another creature's grasp (needle bind, open hand, a thief taking it).

    Used by ``combat/ext/shield_possession.py`` to stop granting shield AC.
    ``weight`` separately accounts for all dropped and taken inventory rows.
    """
    location = owned_item_location(actor, key)
    if location is not None:
        return not location.startswith("hand:")
    return any((condition.data or {}).get("item_key") == key
               and ('|unit:' not in str((condition.data or {}).get('object_id') or '')
                    or str(condition.data['object_id']).endswith('|unit:1'))
               and ((condition.data or {}).get("dropped_at") or (condition.data or {}).get("held_by")
                    or (condition.data or {}).get('stashed_by'))
               for condition in actor.conditions.values())


def weight(engine: Any, actor: Any) -> float:
    """Pounds carried now: the compiled load, less what it has dropped or had taken, plus weapons of others it holds."""
    carrying = carrying_of(engine, actor.entity_id)
    if carrying is None:
        return 0.0
    load = _pounds(carrying.get("weight_lb"))
    for condition in actor.conditions.values():
        data = condition.data or {}
        if data.get("stashed"):  # tucked away weightless (Shadow Stash and the like): neither on the ground nor in a hand
            load -= _condition_weight(engine, actor.entity_id, data)
        elif data.get("dropped_at") or data.get("held_by"):  # on the ground, or in someone else's hands
            # Explicit same-owner relocation keeps this object's weight on its
            # owner. Markerless historical transfer records retain their load.
            if not (data.get("object_location") and data.get("held_by") == actor.entity_id):
                load -= _condition_weight(engine, actor.entity_id, data)
    for other in engine.state.actors.values():
        if other.entity_id == actor.entity_id:
            continue
        for condition in other.conditions.values():
            if (condition.data or {}).get("held_by") == actor.entity_id:
                load += _condition_weight(engine, other.entity_id, condition.data)
    return max(0.0, load)


def status(engine: Any, actor: Any) -> dict[str, Any] | None:
    carrying = carrying_of(engine, actor.entity_id)
    if carrying is None:
        return None
    load = weight(engine, actor)
    from . import ext
    speed = ext.transform('carrying_speed', int(carrying.get('speed_ft') or 30), engine, actor)
    return {"weight_lb": f"{load:g}", "capacity_lb": int(carrying.get("capacity_lb") or 0), "over": load > int(carrying.get("capacity_lb") or 0),
            "speed_ft": speed}


def refresh(engine: Any, actor: Any, source: str) -> None:
    """Keep Speed in step with the load: at most 5 feet over capacity, the character's own under it."""
    carrying = carrying_of(engine, actor.entity_id)
    if carrying is None or not carrying.get("speed_ft"):
        return
    now = status(engine, actor)
    target = min(now["speed_ft"], 5) if now["over"] else now["speed_ft"]
    delta = target - int(carrying.get("template_speed_ft") or carrying["speed_ft"])
    wanted = ENCUMBERED if delta < 0 else UNBURDENED if delta > 0 else None
    speed_before = engine._effective_speed(actor)
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id in (ENCUMBERED, UNBURDENED):
            if condition.condition_id == wanted and int((condition.data or {}).get("speed_delta", 0)) == delta:
                return
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    if wanted:
        engine._apply_condition(actor, wanted, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"speed_delta": delta, "weight_lb": now["weight_lb"], "capacity_lb": now["capacity_lb"]})
    _adjust_this_turn(engine, actor, engine._effective_speed(actor) - speed_before, source)


def _adjust_this_turn(engine: Any, actor: Any, change: int, source: str) -> None:
    """Dropping or picking up gear during its own turn changes the movement it has left by the difference in Speed at once
    (docket 2026-09-28: "adjust the movement left this turn by the difference"), never below none."""
    from .movement_budget import speed_changed
    speed_changed(engine, actor, change, source, reason='load')


def dropped(actor: Any, key: str) -> str | None:
    """The condition instance of an item it has dropped, if it has."""
    return next((iid for iid, condition in actor.conditions.items()
                 if condition.condition_id == DROPPED and (condition.data or {}).get("item_key") == key), None)


def holds(engine: Any, actor: Any, key: str) -> bool:
    """Whether it still carries the item (a weapon not knocked away or taken; anything else not dropped)."""
    item = item_of(carrying_of(engine, actor.entity_id), key=key)
    if item is None:
        return False
    objects = inventory_objects(engine, actor, item)
    if any('|unit:' in obj['object'] for obj in objects):
        unavailable = {str((row.data or {}).get('object_id') or '')
                       for row in actor.conditions.values()
                       if (row.data or {}).get('item_key') == key
                       and ((row.data or {}).get('stashed_by') or (row.data or {}).get('dropped_at')
                            or ((row.data or {}).get('held_by')
                                and row.data['held_by'] != actor.entity_id))}
        return (not quantity_exhausted(engine, actor, item)
                and any(obj['object'] not in unavailable for obj in objects))
    if any((row.data or {}).get('item_key') == key and (row.data or {}).get('stashed_by')
           for row in actor.conditions.values()):
        return False
    if quantity_exhausted(engine, actor, item):
        return False
    if item.get("weapon_action"):
        return not any((condition.data or {}).get("disables_action") == item["weapon_action"] for condition in actor.conditions.values())
    return dropped(actor, key) is None


def relocate_object(engine: Any, identity: str, data: dict[str, Any], source: str, actor_id: str,
                    condition_id: str) -> None:
    """Storage/transfer contract: one exact inventory object, one journaled location.

    Shadow Stash and future storage providers share this transition. Records
    stay on the inventory owner, so received copies never debit the receiver's
    kit. Storage omits held_by/hand; retrieval restores carried placement.
    """
    owner_id, key, *unit = identity.split('|', 2)
    owner = engine.state.actors[owner_id]
    item = item_of(carrying_of(engine, owner_id), key=key)
    if unit and item is not None:
        if identity not in {obj['object'] for obj in object_units(owner_id, item)}:
            raise ValueError('Unknown inventory unit')
        split_object_location(engine, owner, item, source)
    for iid, row in list(owner.conditions.items()):
        old = row.data or {}
        if old.get('object_id', f"{owner_id}|{old.get('item_key', '')}") == identity and (
                old.get('held_by') or old.get('dropped_at') or old.get('stashed_by')):
            engine._remove_condition_instance(owner, iid, source, expected=row)
    engine._apply_condition(owner, condition_id, source, actor_id, expires_on='UNTIL_REMOVED',
                            data={**data, 'owner': owner_id, 'object_id': identity, 'item_key': key})


def remaining_quantity(engine: Any, actor: Any, item: dict[str, Any]) -> int:
    """Remaining inventory units, shared by possession, weapon eligibility and consumable costs.

    Subscribers may reduce the recorded quantity; with no subscriber it is unchanged.
    This query does not mutate the compiled inventory or infer ownership from action labels.
    """
    from . import ext

    recorded = item.get("quantity", 1)
    quantity = max(0, recorded) if type(recorded) is int else 1
    for value in ext.query("carried_item_remaining", engine, actor, item):
        if type(value) is int:
            quantity = min(quantity, max(0, value))
    return quantity


def quantity_exhausted(engine: Any, actor: Any, item: dict[str, Any]) -> bool:
    """Consumption gate shared by holds and weapon_delivery; untouched legacy empty/unknown rows stay inert."""
    recorded = item.get("quantity", 1)
    return type(recorded) is int and recorded > 0 and remaining_quantity(engine, actor, item) <= 0


def can_pick_up(engine: Any, actor: Any, key: str) -> bool:
    iid = dropped(actor, key)
    if iid is None:
        return False
    spot = actor.conditions[iid].data.get("dropped_at") or {}
    from .gate2_runtime_models import Position

    return engine.grid.distance_ft(actor.position, Position(x=int(spot.get("x", 0)), y=int(spot.get("y", 0)))) <= 5
