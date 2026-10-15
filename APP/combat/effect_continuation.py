"""State-only continuation of actual committed condition/modifier instances.

Yin–Yang Current/Unity/slow consumers use this transport with the public journey
continuation hooks. Callers own their source eligibility and remaining clock;
they must supply an actual exported native instance, never a declaration of a
mechanical result. Source/application provenance survives; projection-local
instance IDs are rekeyed and linked to the previous ID in the event so a later
new application cannot collide with an old match's sequence number. Restoring is not application:
no application attempt, immunity check, payment or on-gain trigger is repeated.
Without an explicit caller this module changes nothing.
"""

from contextlib import contextmanager


@contextmanager
def restoration(engine):
    """Restore actual saved models before evaluating lost support.

    Combat and outside-combat journey initialization use this scope. It defers
    falling only during restoration, never a cast/action. The next native
    transaction/boundary settles unsupported actors with its reaction provider.
    """
    previous = getattr(engine, '_restoring_native_effects', False)
    engine._restoring_native_effects = True
    try:
        yield
    finally:
        engine._restoring_native_effects = previous


def restore_condition(engine, target, condition, *, expires_on):
    from hashlib import sha256
    from .gate2_runtime_models import ConditionInstance
    from .gate3_reducer import GATE3_CONDITION_KEY
    previous = ConditionInstance.model_validate(condition)
    if previous.target_id != target.entity_id:
        raise ValueError('Condition continuation requires its original target')
    identity = 'condition:continued:' + engine.state.match_id + ':' + sha256(previous.instance_id.encode()).hexdigest()
    if identity in target.conditions:
        raise ValueError('This condition has already been continued into this match')
    restored = previous.model_copy(deep=True, update={'expires_on': expires_on,
        'instance_id': identity, 'applied_sequence': engine.state.event_sequence + 1,
        'expires_actor_id': None, 'expires_turn_count': None})
    target.conditions[restored.instance_id] = restored
    engine._append_event('CONDITION_RESTORED', restored.source_definition_id,
        actor_id=restored.source_actor_id, target_ids=(target.entity_id,),
        payload={'condition_id': restored.condition_id, 'instance_id': restored.instance_id,
                 'previous_instance_id': previous.instance_id,
                 GATE3_CONDITION_KEY: restored.model_dump(mode='json')})
    return restored


def restore_modifier(engine, target, modifier, *, expires_on):
    from hashlib import sha256
    from .gate2_runtime_models import ModifierInstance
    from .gate3_reducer import GATE3_MODIFIER_KEY
    previous = ModifierInstance.model_validate(modifier)
    if previous.target_id != target.entity_id:
        raise ValueError('Modifier continuation requires its original target')
    identity = ('modifier:continued:' + engine.state.match_id + ':' + sha256(previous.modifier_id.encode()).hexdigest()
                + ':' + str(engine.state.event_sequence + 1))
    if identity in target.modifiers:
        raise ValueError('This modifier has already been continued into this match')
    restored = previous.model_copy(deep=True, update={'expires_on': expires_on,
        'modifier_id': identity,
        'expires_actor_id': None, 'expires_turn_count': None})
    target.modifiers[restored.modifier_id] = restored
    engine._append_event('MODIFIER_RESTORED', restored.source_definition_id,
        actor_id=restored.source_actor_id, target_ids=(target.entity_id,),
        payload={'modifier_id': restored.modifier_id, 'previous_modifier_id': previous.modifier_id,
                 GATE3_MODIFIER_KEY: restored.model_dump(mode='json')})
    return restored
