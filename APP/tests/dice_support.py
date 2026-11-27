"""Hold the table's d20 still for the roll a test wants to decide.

A fight rolls through the engine's own seeded authority; forcing one natural result (optionally only for one actor or
one reason) keeps the fight real while making the decided roll deterministic. Nothing here reads repository history.

Users: tests/test_riders_c15.py, tests/test_auto4_methods.py.
"""


def force_d20(engine, natural, *, actor_id=None, reason=None):
    """Every d20 rolled from now on (by ``actor_id``, for a reason starting with ``reason``) shows ``natural``."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        wanted = natural if (actor_id in (None, kwargs.get("actor_id"))
                             and (reason is None or str(kwargs.get("reason") or "").startswith(reason))) else None
        while True:
            roll = original(**kwargs)
            if wanted is None or int(roll.natural_result) == wanted:
                return roll

    engine.roller.d20 = d20
