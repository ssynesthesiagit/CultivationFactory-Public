"""Ordinary movement withheld by immobilization at the start of a turn.

Only the withheld initial allowance is restored. Movement already spent, Dash,
and separate granted movement are never refunded by removing a condition.
"""

WITHHELD = 'movement_withheld_ft'


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


def condition_removed(engine, event):
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
