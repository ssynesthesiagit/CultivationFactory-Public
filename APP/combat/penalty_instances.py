"""Exact ending of one penalty and its explicitly linked native components.

Used by foundations3's optional relief. Producers such as Dreams record
`data.consequences` as exact dependent instance IDs, not broad condition names.
Only components with the same native source/owner/target may follow the parent;
ordinary unlinked conditions/modifiers use their existing one-instance ending.
This helper neither classifies penalties nor grants permission to end them.
"""


def modifier_penalty(modifier):
    """True/False for known native harm/benefit, None for GM-classified semantics.

    Field names here are engine mechanics, not source names or damage guesses.
    Unknown compound modifiers need the source consumer's explicit GM facts.
    This pure contract is shared by admission and exact-instance relief.
    """
    field, value = modifier['target_field'], modifier['value']
    if modifier['operation'] != 'ADD':
        return None
    if field in {'speed_ft', 'armor_class', 'armor_class_vs_melee', 'armor_class_vs_ranged',
                 'attack_bonus', 'attack_roll', 'saving_throw_bonus', 'eye_sense_range',
                 'next_qualifying_attack_damage'} and type(value) is int:
        return value < 0
    if field in {'attack_mode', 'attack_mode_vs', 'check_mode', 'save_mode'}:
        return value == 'DISADVANTAGE'
    if field == 'incoming_attack_mode':
        return value == 'ADVANTAGE'
    if field in {'damage_resistance', 'damage_immunity', 'condition_immunity', 'damage_resistance_next'}:
        return False
    if field in {'speed_halved', 'healing_reduction', 'resistance_suppressed'}:
        return True
    return None


def end_instance(engine, subject, instance_id, source, *, seen=None):
    seen = set() if seen is None else seen
    if instance_id in seen:
        return False
    seen.add(instance_id)
    parent = subject.conditions.get(instance_id) or subject.modifiers.get(instance_id)
    if parent is None:
        return False
    children = list(getattr(parent, 'data', {}).get('consequences') or ())
    remove = engine._remove_condition_instance if instance_id in subject.conditions else engine._remove_modifier_instance
    if not remove(subject, instance_id, source):
        return False
    for key in children:
        child = subject.conditions.get(key) or subject.modifiers.get(key)
        if child is not None and (child.source_definition_id, child.source_actor_id, child.target_id) == (
                parent.source_definition_id, parent.source_actor_id, parent.target_id):
            end_instance(engine, subject, key, source, seen=seen)
    return True
