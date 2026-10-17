"""Typed, harmless object affordances shared by table authors and Puppetry.

A named lever/button changes its own integer state; a bell signals; a Tiny
object can be toppled; a loose object can be lifted or tugged. These records
cannot encode attacks, magic activation, checks, locks, traps or craft effects.
Missing affordances confer no operation. Object identity/weight remain native.
"""
from copy import deepcopy

KINDS = ('toggle', 'signal', 'pick_up', 'knock_over', 'tug')


def normalize(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('Simple object operations must be a list.')
    out = []
    for row in value:
        if (not isinstance(row, dict) or set(row) != {'id', 'name', 'kind', 'state'}
                or not isinstance(row['id'], str) or not row['id'] or len(row['id']) > 80
                or not isinstance(row['name'], str) or not row['name'].strip() or len(row['name']) > 120
                or row['kind'] not in KINDS or type(row['state']) is not int or row['state'] < 0
                or (row['kind'] in ('toggle', 'knock_over') and row['state'] not in (0, 1))):
            raise ValueError('Record a named simple toggle, signal, lift, topple or tug with whole-number state.')
        out.append(deepcopy(row))
    if len({r['id'] for r in out}) != len(out):
        raise ValueError('Simple object operation identities must be distinct.')
    return out


def available(obj):
    if obj.destroyed or not obj.unattended:
        return []
    return [r for r in normalize((obj.component or {}).get('simple_operations'))
            if r['kind'] != 'knock_over' or (obj.component or {}).get('size') == 'tiny']


def perform(engine, actor, obj, operation, source):
    from .ext import run_strict
    row = next((r for r in available(obj) if r['id'] == operation), None)
    if row is None:
        raise ValueError('That simple manipulation is not available for this object.')
    if False in run_strict('object_operation_gate', engine, actor, obj, row['kind'], source, getattr(engine, '_active_intent', None)):
        return False
    component = deepcopy(obj.component or {})
    for entry in component['simple_operations']:
        if entry['id'] == operation:
            entry['state'] = 1 - entry['state'] if row['kind'] == 'toggle' else 0 if row['kind'] == 'knock_over' else entry['state'] + 1
    if row['kind'] == 'pick_up':
        component['suspended_by'] = actor.entity_id
    engine._update_object(obj.model_copy(update={'component': component,
        **({'unattended': False} if row['kind'] == 'pick_up' else {})}), source, actor.entity_id)
    run_strict('simple_object_manipulated', engine, actor, engine.state.objects[obj.object_id], row['kind'], source)
    return True
