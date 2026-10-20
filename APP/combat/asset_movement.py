"""Stepwise movement of physical Assets (not creature turns or teleportation).

Callers supply a previously validated grid path and its source. Every occupied
step commits the actual object before object_movement_step observers run.
Explicit object-targeting zone entry effects use ordinary object damage, never
creature-only saves/conditions. Destroyed/displaced works stop immediately.
No moving Asset, no new events, hooks or change to creature movement.
"""
from copy import deepcopy
from . import ext
from .gate2_runtime_models import ActionDefinition
from .object_geometry import target_cells


def move_path(engine, owner, obj, path, source, intent):
    if not path or path[0] != obj.position:
        raise ValueError('An Asset path must begin at its actual space.')
    traveled = [obj.position]
    for previous, nxt in zip(path, path[1:]):
        obj = engine.state.objects[obj.object_id]
        if obj.destroyed or obj.position != previous:
            break
        if max(abs(nxt.x-previous.x), abs(nxt.y-previous.y), abs(nxt.z-previous.z)) != 1:
            raise ValueError('Asset movement must visit every grid step.')
        engine._update_object(obj.model_copy(update={'position': nxt}), source, owner.entity_id)
        traveled.append(nxt)
        obj = engine.state.objects[obj.object_id]
        zone_entry(engine, owner, obj, previous, intent)
        ext.run_strict('object_movement_step', engine, owner, obj, previous, nxt, source, intent)
    return traveled


def zone_entry(engine, owner, obj, previous, intent):
    from . import zones, typed_executor
    old = obj.model_copy(update={'position': previous})
    for zone in zones.typed_zones(engine):
        cells = set(zone.affected_cells)
        if not cells.intersection(target_cells(engine, obj)) or cells.intersection(target_cells(engine, old)):
            continue
        for trigger in zone.trigger_profile.get('triggers') or []:
            if trigger.get('who') != 'objects' or 'enter' not in trigger.get('on', []):
                continue  # a creature-only hazard never acquires object permission
            marks = dict(obj.component.get('movement_zone_uses') or {})
            key = zone.zone_id + ':' + str(trigger.get('id') or trigger.get('name'))
            turn = str(engine.state.round_number) + ':' + str(engine.state.current_actor_id) + ':' + str(engine.state.actors[engine.state.current_actor_id].turns_started)
            if marks.get(key) == turn:
                continue
            marks[key] = turn
            obj = engine.state.objects[obj.object_id]
            if obj.destroyed:
                return
            engine._update_object(obj.model_copy(update={'component': {**obj.component, 'movement_zone_uses': marks}}),
                                  zone.source_definition_id, zone.owner_id)
            caster = engine.state.actors.get(zone.owner_id, owner)
            typed = {'source': zone.source_definition_id, 'numbers': dict(zone.trigger_profile.get('numbers') or {}),
                     'effects': deepcopy(trigger.get('effects') or []), 'duration': {'kind': 'instant'}}
            action = ActionDefinition(source_definition_id=zone.source_definition_id, display_name=zone.trigger_profile.get('name') or 'Hazard',
                                      owner_id=caster.entity_id, economy='NONE', resolution_kind='TYPED', target_kind='OBJECT',
                                      parameters={'typed': typed})
            ctx = typed_executor.Context(engine, caster, action, intent, typed, [], None)
            ctx.damage_cache['_object'] = obj
            typed_executor.run_effects(ctx, [e for e in typed['effects'] if e.get('type') == 'object_damage'])
