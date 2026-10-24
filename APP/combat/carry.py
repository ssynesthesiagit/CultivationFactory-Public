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

import threading
from contextlib import contextmanager
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


def _condition_weight(engine: Any, owner_id: str, data: dict[str, Any]) -> float:
    carrying = carrying_of(engine, owner_id)
    item = item_of(carrying, key=data.get("item_key"), weapon_action=data.get("disables_action"))
    return _pounds((item or {}).get("weight_lb"))


def owned_item_location(actor: Any, key: str) -> str | None:
    """Explicit journaled location on its original owner, or no override.

    Hand occupancy and shield permission read the same opt-in relocation record.
    ``carried`` reserves no hand; ``hand:<part>`` reserves exactly that part.
    Markerless saved equipment keeps its compiled default location.
    """
    return next((str(data['object_location']) for row in actor.conditions.values()
                 if (data := row.data or {}).get('item_key') == key
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
               and ((condition.data or {}).get("dropped_at") or (condition.data or {}).get("held_by"))
               for condition in actor.conditions.values())


def weight(engine: Any, actor: Any) -> float:
    """Pounds carried now: the compiled load, less what it has dropped or had taken, plus weapons of others it holds."""
    carrying = carrying_of(engine, actor.entity_id)
    if carrying is None:
        return 0.0
    load = _pounds(carrying.get("weight_lb"))
    for condition in actor.conditions.values():
        data = condition.data or {}
        if data.get("dropped_at") or data.get("held_by"):  # on the ground, or in someone else's hands
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
    return {"weight_lb": f"{load:g}", "capacity_lb": int(carrying.get("capacity_lb") or 0), "over": load > int(carrying.get("capacity_lb") or 0),
            "speed_ft": int(carrying.get("speed_ft") or 30)}


class _LoadAs(threading.local):
    value = None


_LOAD_AS = _LoadAs()


@contextmanager
def _load_as(overloaded: bool):
    """Price Speed as if the carrying restriction were `overloaded` (used only to read a prior Speed).

    The read runs outside every memo and candidate-pass frame. Speed memo keys carry no load
    state, so a live-load reading cached earlier in the frame would be returned as the prior one,
    and the prior reading would be cached under the key a later live read uses.
    """
    from . import read_queries
    before = _LOAD_AS.value
    _LOAD_AS.value = bool(overloaded)
    frame_token = read_queries._FRAME.set(None)
    pass_token = read_queries._PASS.set(None)
    try:
        yield
    finally:
        read_queries._PASS.reset(pass_token)
        read_queries._FRAME.reset(frame_token)
        _LOAD_AS.value = before


def speed_limit(engine: Any, actor: Any, speed: int) -> int:
    """Final carrying restriction shared by walking and native mode queries.

    An imported already-overloaded template is already 5 feet and needs no
    Encumbered delta condition. Read the actual load as well as that marker.
    This query never changes inventory or refreshes a condition.
    """
    if _LOAD_AS.value is not None:
        overloaded = _LOAD_AS.value
    else:
        load = status(engine, actor)
        overloaded = (load is not None and load['over']) or any(
            c.condition_id == ENCUMBERED for c in actor.conditions.values())
    return min(speed, 5) if overloaded else speed


def refresh(engine: Any, actor: Any, source: str) -> None:
    """Keep Speed in step with the load: at most 5 feet over capacity, the character's own under it."""
    carrying = carrying_of(engine, actor.entity_id)
    if carrying is None or not carrying.get("speed_ft"):
        return
    now = status(engine, actor)
    target = min(int(carrying["speed_ft"]), 5) if now["over"] else int(carrying["speed_ft"])
    delta = target - int(carrying.get("template_speed_ft") or carrying["speed_ft"])
    wanted = ENCUMBERED if delta < 0 else UNBURDENED if delta > 0 else None
    # Speed before this load change is what the pool was granted under: the prior
    # Encumbered record, not the live load (which already reads over-capacity here).
    # Pricing it live made the change zero and left the walking pool at its
    # pre-overload value, so an overloaded creature kept a full-length move.
    prior_over = any(c.condition_id == ENCUMBERED for c in actor.conditions.values())
    with _load_as(prior_over):
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
    if quantity_exhausted(engine, actor, item):
        return False
    if item.get("weapon_action"):
        return not any((condition.data or {}).get("disables_action") == item["weapon_action"] for condition in actor.conditions.values())
    return dropped(actor, key) is None


def item_carrier(engine: Any, owner: Any, key: str) -> str | None:
    """Current bearer of an original inventory row, or None when not carried.

    Blacksmith item use reads both ordinary item-key relocations and native
    disarm/catch records identified by disables_action. The original owner is
    a storage anchor; only the current bearer's activity determines availability.
    This pure query creates no possession or equipment state.
    """
    item = item_of(carrying_of(engine, owner.entity_id), key=key)
    if item is None or quantity_exhausted(engine, owner, item):
        return None
    bearer = owner.entity_id
    relocated = False
    for row in owner.conditions.values():
        data = row.data or {}
        located = item_of(carrying_of(engine, owner.entity_id), key=data.get('item_key'),
                          weapon_action=data.get('disables_action'))
        if located is None or located.get('key') != key:
            continue
        if data.get('dropped_at'):
            return None
        if data.get('held_by'):
            bearer = str(data['held_by'])
            relocated = True
    if not relocated and not holds(engine, owner, key):
        return None
    carrier = engine.state.actors.get(bearer)
    return bearer if carrier is not None and carrier.active else None


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
