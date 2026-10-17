"""Ordinary movement reconciliation for Speed changes and immobilization.

Only the withheld initial allowance is restored. Movement already spent, Dash,
and separate granted movement are never refunded by removing a condition.
"""

WITHHELD = 'movement_withheld_ft'


def condition_speed(engine, actor):
    """Composed Speed, or None when immobilization owns the pool contract."""
    from .typed_executor import condition_rules
    if any(c.condition_id == 'condition:core.grappled' for c in actor.conditions.values()) or any(
            row.get('speed_zero') for row in condition_rules(actor)):
        return None
    return max(0, engine._effective_speed(actor))


def speed_changed(engine, actor, change, source, *, reason='speed', current_turn_only=True):
    """Journal a signed Speed delta in the unspent pool, clamped at zero.

    Consumers supply the effective difference, after stacking/halving. Preserve
    spent movement and extra grants, clamp at zero, and refresh movement-owner
    baselines so a subsequent technique does not apply the same delta again.
    Explicit changes default to the current actor only; removal can update a
    holder's retained pool between turns with current_turn_only=False.
    """
    current = engine.state.current_actor_id == actor.entity_id
    if not change or (current_turn_only and not current) or not actor.turns_started:
        return
    before = int(actor.movement_remaining_ft)
    actor.movement_remaining_ft = max(0, before + int(change))
    if current:
        turn_allowance(engine, actor, max(0, engine._effective_speed(actor)))
    delta = actor.movement_remaining_ft - before
    if delta:
        engine._append_event('MOVEMENT_GRANTED', source, actor_id=actor.entity_id,
            payload={'distance_ft': delta, 'remaining_ft': actor.movement_remaining_ft,
                     'reason': reason, 'allowance_replaced': True,
                     'log': f'{actor.display_name} has {actor.movement_remaining_ft} feet of movement left after the Speed change.'})


def turn_allowance(engine, actor, speed):
    """Let a movement owner replace the initial allowance, not grant extra feet."""
    from . import ext
    values = ext.run_strict('turn_movement_allowance', engine, actor, speed)
    if any(type(value) is not int or value < 0 for value in values) or len(values) > 1:
        raise ValueError('one turn_movement_allowance provider may return nonnegative integer feet')
    return values[0] if values else speed


def limit(engine, actor, available):
    """Apply independent movement-owner ceilings without increasing a pool."""
    from . import ext
    values = ext.run_strict('ordinary_movement_limit', engine, actor)
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError('ordinary_movement_limit requires nonnegative integer feet')
    return min([available, *values])


def start_turn(engine, actor):
    """Snapshot unheld Speed after turn-start expirations, before turn actions."""
    if not actor.active or actor.life_state not in (None, 'CONSCIOUS') or engine._effective_speed(actor) > 0:
        return
    from .typed_executor import condition_rules
    conditions = {}
    for key, condition in actor.conditions.items():
        single = actor.model_copy(update={'conditions': {key: condition}})
        if condition.condition_id == 'condition:core.grappled' or any(
                row.get('speed_zero') for row in condition_rules(single)):
            continue
        conditions[key] = condition
    if len(conditions) == len(actor.conditions):
        return
    unheld = actor.model_copy(update={'conditions': conditions})
    # Snapshot the same owned allowance as a mobile turn, including genesis.
    # This shallow view retains the actor's turn_flags so its movement owner
    # also records the baseline used for later Speed reconciliation.
    feet = max(0, turn_allowance(engine, unheld, engine._effective_speed(unheld)))
    if feet:
        actor.turn_flags[WITHHELD] = feet


def condition_removed(engine, event, ended_effect=None):
    # An effect can expire at a different creature's boundary. Reconcile the
    # holder's retained readout too, before its next turn refreshes the pool.
    if ended_effect is not None:
        from .gate2_runtime_models import ConditionInstance
        removed = ConditionInstance.model_validate(ended_effect)
        holder = engine.state.actors.get(removed.target_id)
        if holder is not None and not holder.turn_flags.get(WITHHELD, 0):
            previous = holder.model_copy(update={'conditions': {
                **holder.conditions, removed.instance_id: removed}})
            before = condition_speed(engine, previous)
            after = condition_speed(engine, holder)
            if before is not None and after is not None and (after < before or removed.data.get('speed_penalty_all_modes') is True and after != before):
                speed_changed(engine, holder, after - before, event.source_definition_id,
                              current_turn_only=False)
    actor = engine.state.actors.get(engine.state.current_actor_id)
    if actor is None or actor.entity_id not in event.target_ids:
        return
    withheld = actor.turn_flags.get(WITHHELD, 0)
    speed = engine._effective_speed(actor)
    if not withheld or speed <= 0 or not actor.active or actor.life_state not in (None, 'CONSCIOUS'):
        return
    actor.turn_flags.pop(WITHHELD)
    restored = min(withheld, speed)
    restored = max(0, limit(engine, actor, actor.movement_remaining_ft + restored)
                   - actor.movement_remaining_ft)
    actor.movement_remaining_ft += restored
    engine._append_event('MOVEMENT_ALLOWANCE_RESTORED', event.source_definition_id,
        actor_id=actor.entity_id, payload={'restored_ft': restored,
            'remaining_ft': actor.movement_remaining_ft,
            'log': (f'{actor.display_name} can move again: {restored} feet of unspent movement restored.'
                    if restored else f'{actor.display_name} has no unspent movement to restore.')})
