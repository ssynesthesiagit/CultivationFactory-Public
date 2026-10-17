"""Thread the Object's instantaneous object manipulations (owner rules_text.json).

Uses existing compile_actions/object_targets/object_action hooks and OBJECT_UPDATED
replay. Explicit map weight_lb is required: size/material never establish weight.
Explicit simple doors can open/close, but cannot be moved. Other attached
structures, other simple manipulations and Projected Puppetry
permission remain GM work. Body Refiners conservatively use touch (5 feet).
The original declaration-only button remains for those unrepresented clauses.
"""
from __future__ import annotations

from .map_positions import map_position

from typing import Any

from . import hook, note

SOURCE = "PUPPETRY_BASE_THREAD_THE_OBJECT"
ERRAND = "tianxia.talent.puppetry.little_servant_s_errand"


@hook('compile_block')
def errand_row(block: str, spec: Any, row: Any, numbers: Any) -> Any:
    return [{**row,'block':block,'keeps_compiling':True}] if block == 'thread_errand' else None


@hook("compile_actions")
def movement_button(info: dict[str, Any]) -> list[Any] | None:
    original = next((a for a in info["actions"]
                     if ((a.parameters or {}).get("typed") or {}).get("source") == SOURCE), None)
    if original is None:
        return None
    params = dict(original.parameters or {})
    params.update(thread_object_move=True, expected_damage=0)
    params.pop("player_only", None)
    if any(r.get('block') == 'thread_errand' and r.get('feature_id') == ERRAND for r in info.get('passives',[])):
        params['thread_object_max_weight']=10*int(info.get('pb') or info['numbers'].get('pb') or 1)
    params["typed"] = {**params["typed"], "effects": [], "riders": [], "duration": {"kind": "instant"}}
    paths = (info["owner_sheet"].get("path_and_subpath") or {}).get("path_record_ids") or []
    body = "tianxia.path.body_refining" in paths or info.get("primary") == "stamina"
    movement = original.model_copy(update={
        "source_definition_id": original.source_definition_id + ".move_object",
        "display_name": "Thread the Object: move object", "target_kind": "OBJECT",
        "range_ft": 5 if body else 30, "parameters": params})
    door_params = {**params, "thread_object_move": False, "thread_object_door": True}
    door = movement.model_copy(update={
        "source_definition_id": original.source_definition_id + ".simple_door",
        "display_name": "Thread the Object: open/close simple door", "parameters": door_params})
    simple = movement.model_copy(update={
        'source_definition_id': original.source_definition_id + '.simple_manipulation',
        'display_name': 'Thread the Object: simple manipulation',
        'parameters': {**params, 'thread_object_move': False, 'thread_object_simple': True}})
    return [movement, door, simple]


def _owns(actor: Any, action: Any, flag: str = "thread_object_move") -> bool:
    return (action.owner_id == actor.entity_id and action.source_definition_id in actor.action_ids
            and bool((action.parameters or {}).get(flag)))


def _door_eligible(engine: Any, obj: Any, maximum: int = 10) -> bool:
    from ..object_rules import simple_door_state

    component = obj.component or {}
    state = simple_door_state(component)
    weight = component.get("weight_lb")
    if (obj.destroyed or not obj.unattended or type(weight) is not int or not 0 <= weight <= maximum
            or state is None or state["door_locked"] or state["door_jammed"] or component.get("artifact")):
        return False
    # Closing must never entomb a creature, including a large footprint, or
    # another owner's object. An open door stays attached to its map square.
    from .door_state import closing_blocked
    return not state["door_open"] or not closing_blocked(engine, obj)


def _eligible(obj: Any, maximum: int = 10) -> bool:
    component = obj.component or {}
    weight = component.get("weight_lb")
    return (not obj.destroyed and obj.unattended and type(weight) is int and 0 <= weight <= maximum
            and not component.get("blocks") and not component.get("structure"))


def _destinations(engine: Any, obj: Any) -> list[Any]:
    """Reachable free squares within ten feet, using ordinary corner/wall checks.

    Staying in place is a valid 'up to' choice; no actor movement is consumed.
    Other objects' occupied squares are preserved, including nonblocking ones.
    """
    from ..gate2_runtime_models import Position

    occupied = set().union(*(engine.grid.footprint_cells(a.position, engine._footprint(a))
                             for a in engine.state.actors.values() if a.active))
    occupied.update((o.position.x, o.position.y) for o in engine.state.objects.values()
                    if not o.destroyed and o.object_id != obj.object_id)
    start = (obj.position.x, obj.position.y)
    reached = {start: 0}
    pending = [obj.position]
    while pending:
        current = pending.pop(0)
        distance = reached[(current.x, current.y)]
        if distance >= 10:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = map_position(engine, current.x + dx, current.y + dy)
                if cell is None:
                    continue
                key = (cell.x, cell.y)
                if (dx or dy) and key not in reached and engine.grid.step_legal(current, cell, occupied_cells=occupied):
                    reached[key] = distance + 5
                    pending.append(cell)
    return [Position(x=x, y=y) for x, y in sorted(reached)]


@hook("object_targets")
def targets(engine: Any, actor: Any, action: Any) -> list[str]:
    maximum=int((action.parameters or {}).get('thread_object_max_weight') or 10)
    if _owns(actor, action, 'thread_object_simple'):
        from ..simple_objects import available
        return [o.object_id for o in engine.state.objects.values() if available(o)
                and type((o.component or {}).get('weight_lb')) is int and 0 <= o.component['weight_lb'] <= maximum]
    if _owns(actor, action, "thread_object_door"):
        return [o.object_id for o in engine.state.objects.values() if _door_eligible(engine, o,maximum)]
    if not _owns(actor, action):
        return []
    return [o.object_id for o in engine.state.objects.values() if _eligible(o,maximum)]


@hook("object_action")
def move(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    if _owns(actor, action, 'thread_object_simple'):
        return _simple(engine, actor, action, obj, intent)
    if _owns(actor, action, "thread_object_door"):
        return _door(engine, actor, action, obj, intent)
    if not _owns(actor, action):
        return None
    maximum=int((action.parameters or {}).get('thread_object_max_weight') or 10)
    if not _eligible(obj,maximum):
        raise ValueError(f"Thread the Object needs a loose unattended object of known weight at most {maximum} pounds")
    from .. import object_rules
    from . import needle

    cells = _destinations(engine, obj)
    by_id = {needle.cell_id(cell): cell for cell in cells}
    name = object_rules.label(obj)
    selected = needle.ask(engine, intent,
        needle.checkpoint_id(engine, "THREAD_OBJECT", action.source_definition_id, obj.object_id), actor,
        "choice:needle.thread_object", list(by_id),
        labels={key: f"({cell.x}, {cell.y})" for key, cell in by_id.items()},
        prompt=f"Thread the Object: {action.display_name} — move {name} up to 10 feet to which space?",
        name="Thread the Object", target_id=obj.object_id,
        preferred=[needle.cell_id(obj.position)])
    if selected:
        destination = by_id[selected[0]]
        if destination != obj.position:
            from . import run_strict
            if False in run_strict("object_operation_gate", engine, actor, obj, "move", action.source_definition_id, intent):
                return True
            engine._update_object(obj.model_copy(update={"position": destination}), action.source_definition_id, actor.entity_id)
        note(engine, action.source_definition_id, actor,
             f"Thread the Object moves {name} to ({destination.x}, {destination.y}).", targets=(obj.object_id,))
    return True


def _door(engine: Any, actor: Any, action: Any, obj: Any, intent: Any) -> bool:
    from .. import object_rules
    from .door_state import change_door
    from . import needle

    maximum=int((action.parameters or {}).get('thread_object_max_weight') or 10)
    if not _door_eligible(engine, obj,maximum):
        raise ValueError(f"Thread the Object needs an unattended simple door of known weight at most {maximum} pounds, unlocked and unjammed, with space to close")
    name = object_rules.label(obj)
    opening = not obj.component["door_open"]
    operation = "OPEN" if opening else "CLOSE"
    selected = needle.ask(engine, intent,
        needle.checkpoint_id(engine, "THREAD_DOOR", action.source_definition_id, obj.object_id), actor,
        "choice:needle.thread_door", [operation, "LEAVE"],
        labels={operation: f"{operation.title()} {name}", "LEAVE": f"Leave {name} as it is"},
        prompt=f"Thread the Object: {action.display_name} — {operation.lower()} {name} or leave it as it is?",
        name="Thread the Object", target_id=obj.object_id, preferred=["LEAVE"])
    if selected and selected[0] == operation:
        from . import run_strict
        if opening and False in run_strict("object_operation_gate", engine, actor, obj, "open", action.source_definition_id, intent):
            return True
        change_door(engine, actor, obj, opening, action.source_definition_id)
        note(engine, action.source_definition_id, actor,
             f"Thread the Object {operation.lower()}s {name}.", targets=(obj.object_id,))
    return True


@hook("compile_action")
def executable(action, info):
    parameters = action.parameters or {}
    if ((parameters.get("typed") or {}).get("source") == SOURCE
            and any(parameters.get(k) for k in ("thread_object_move", "thread_object_door", "thread_object_simple"))
            and SOURCE in info["owned_ids"]):
        return action.model_copy(update={"parameters": {**parameters, "inert": False}})
    return None


def _simple(engine, actor, action, obj, intent):
    from ..simple_objects import available, perform
    from . import needle
    from .effect_durations import token
    rows = available(obj)
    maximum = int(action.parameters.get('thread_object_max_weight') or 10)
    if type((obj.component or {}).get('weight_lb')) is not int or not 0 <= obj.component['weight_lb'] <= maximum:
        raise ValueError('Thread the Object requires a known weight of at most ten pounds.')
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'thread_simple', action.source_definition_id, obj.object_id),
        actor, 'choice:needle.thread_simple', [r['id'] for r in rows], labels={r['id']: r['name'] for r in rows},
        preferred=[r['id'] for r in rows[:1]], name='Thread the Object', target_id=obj.object_id,
        prompt=f'Thread the Object: choose one simple manipulation of {obj.component.get("name", "this object")}. An Action, no Cultivation Point cost. This cannot attack, activate magic, use tools, pick locks, disarm traps or perform complex craft.')
    if chosen:
        operation = next(r for r in rows if r['id'] == chosen[0])
        if perform(engine, actor, obj, chosen[0], action.source_definition_id) and operation['kind'] == 'pick_up':
            engine._apply_condition(actor, 'condition:typed.thread_object_held', action.source_definition_id, actor.entity_id,
                expires_on=token('end', actor.entity_id, actor.turns_started + 1),
                data={'label': 'Thread the Object: holding ' + str(obj.component.get('name') or 'object'), 'object_id': obj.object_id, 'retain_removal_data': 1})
    return True


@hook('state_event')
def release_held(engine, event):
    if event.event_type != 'CONDITION_REMOVED':
        return
    condition = event.payload.get('removed_condition') or {}
    # Exact condition payloads include the removed snapshot. Older events that
    # carry only an instance id are handled by turn_end below.
    if condition.get('condition_id') == 'condition:typed.thread_object_held':
        _release(engine, condition.get('target_id') or next(iter(event.target_ids),None), (condition.get('data') or {}).get('object_id'))


def _release(engine, aid, object_id):
    obj = engine.state.objects.get(object_id)
    if obj is not None and (obj.component or {}).get('suspended_by') == aid:
        component = dict(obj.component); component.pop('suspended_by', None)
        engine._update_object(obj.model_copy(update={'component': component, 'unattended': True}), SOURCE, aid)


@hook('turn_end')
def release_expired(engine, actor):
    held = {c.data.get('object_id') for c in actor.conditions.values() if c.condition_id == 'condition:typed.thread_object_held'}
    for obj in list(engine.state.objects.values()):
        if (obj.component or {}).get('suspended_by') == actor.entity_id and obj.object_id not in held:
            _release(engine, actor.entity_id, obj.object_id)


@hook('compile_actions')
def projected_buttons(info):
    paths = (info['owner_sheet'].get('path_and_subpath') or {}).get('path_record_ids') or []
    if 'tianxia.path.body_refining' not in paths:
        return None
    # The permission is a runtime sealed scene fact, not a compiler claim. The
    # variants stay unavailable until the specific subject is admitted.
    out = []
    for action in movement_button(info) or []:
        out.append(action.model_copy(update={'source_definition_id': action.source_definition_id + '.projected',
            'range_ft': 30, 'display_name': action.display_name + ' (Projected Puppetry)',
            'parameters': {**action.parameters, 'thread_object_projected': True}}))
    return out or None


@hook('candidate_allowed')
def projection_gate(engine, actor, candidate, action):
    if not (getattr(action, 'parameters', None) or {}).get('thread_object_projected'):
        return None
    from .physical_source_facts import projected
    return bool(candidate.target_ids and all(projected(engine, actor.entity_id, SOURCE, oid) for oid in candidate.target_ids))
