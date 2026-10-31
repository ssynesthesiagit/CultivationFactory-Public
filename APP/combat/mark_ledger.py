"""Read/remove owned creature and object marks without a second storage schema.

Glass capacity uses this ledger; Ice and other object consumers can share it.
Creature marks remain native conditions, objects remain object_marks entries.
Returned recipient/condition references are ephemeral and never serialized.
"""


def owned(engine, name, owner_id):
    from .typed_executor import mark_condition_id
    from .ext.object_marks import KEY, key
    condition_id = mark_condition_id(name, owner_id)
    out = [{'id': condition.instance_id, 'kind': 'creature', 'recipient': actor,
        'condition': condition, 'sequence': condition.applied_sequence}
        for actor in engine.state.actors.values() for condition in actor.conditions.values()
        if condition.condition_id == condition_id and condition.source_actor_id == owner_id]
    for obj in engine.state.objects.values():
        mark = (obj.component or {}).get(KEY, {}).get(key(name, owner_id))
        if mark is not None and mark.get('owner_id') == owner_id and mark.get('name') == name:
            out.append({'id': 'object-mark:' + obj.object_id, 'kind': 'object', 'recipient': obj,
                'mark': mark, 'sequence': int(mark.get('applied_sequence', 0))})
    return sorted(out, key=lambda entry: (entry['sequence'], entry['id']))


def remove(engine, entry, name, owner_id, source):
    """End the exact owned entry selected from the current native ledger."""
    current = next((value for value in owned(engine, name, owner_id) if value['id'] == entry['id']), None)
    if current is None:
        raise ValueError('That owned mark is no longer active.')
    if current['kind'] == 'creature':
        engine._remove_condition_instance(current['recipient'], current['condition'].instance_id, source)
    else:
        from .ext.object_marks import remove as remove_object
        remove_object(engine, current['recipient'], name, owner_id, source)


def visible_name(engine, viewer, entry):
    """Choice label from the viewer's current senses, without hidden identity."""
    from . import senses
    target = entry['recipient']
    if entry['kind'] == 'creature':
        return target.display_name if senses.perceives(engine, viewer, target) else 'an unseen creature'
    from .object_rules import label
    return label(target) if senses.perceives_object(engine, viewer, target) else 'an unseen object'
