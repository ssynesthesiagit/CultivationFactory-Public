"""Shared single-strike execution for br_variants and needle's Parry and Riposte.

These triggers borrow a weapon's attack, not its Attack action. The active
intent carries any per-strike choices, while normal attack and hit rules retain
the weapon's own numbers and effects. No catalog row or economy is changed.
"""
from copy import deepcopy


def make_attack_now(engine, actor, action, target):
    """Resolve one granted strike using the compiled attack profile."""
    from ..typed_executor import Context, run_effects

    typed = deepcopy((action.parameters or {}).get("typed") or {})
    attack = next((row for row in typed.get("effects") or [] if row.get("type") == "attack"), None)
    if attack is None:
        return
    attack.pop("count_by_cl", None)
    attack.update(count=1, granted_attack_root=True)
    # Off-hand readiness belongs to the Attack action, not this strike.
    for key in ("attack_action", "opens", "uses", "marks_used"):
        typed.pop(key, None)
    typed.update(effects=[attack], granted_attack=True)
    run_effects(Context(engine, actor, action, engine._active_intent, typed, [target], target), [attack])
