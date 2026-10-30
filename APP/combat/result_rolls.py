"""Post-result numerical roll adjustments for native and typed attacks/saves.

Used by the native resolver and completion-response plug-ins. Providers own
their decisions/payment; this helper owns the effective roll and its receipt.
"""
def apply_bonus(engine, roll, source_id, hook_name, *args):
    from . import ext

    bonuses = ext.run_strict(hook_name, engine, *args)
    if any(type(value) is not int for value in bonuses):
        raise ValueError(f"{hook_name} requires an integer")
    bonus = sum(bonuses)
    if not bonus:
        return roll
    adjusted = roll.model_copy(update={"total": roll.total + bonus,
                                       "modifier": roll.modifier + bonus})
    engine._append_event("PASSIVE_TRIGGERED", source_id, actor_id=roll.actor_id,
                         payload={"roll_id": roll.roll_id, "hook": hook_name,
                                  "previous_total": roll.total, "total": adjusted.total,
                                  "bonus": bonus})
    return adjusted
