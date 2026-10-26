"""Controlled ordinary hits for table regressions after reviewed AC recalculation.

Wheel, Undo Harm and Gilded Guard test damage consequences, not hit probability.
Use the documented roll hook, scoped to their attacker's actual attack rolls.
"""
from combat import ext


def accurate_attacks(monkeypatch, actor_id):
    ext.effects()

    def hit(engine, roll, intent):
        if roll.actor_id == actor_id and str(roll.reason).startswith("ATTACK:"):
            return {"source_id": "test:ordinary-hit", "operation": "replace", "natural_result": 19}
        return None

    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), hit])
