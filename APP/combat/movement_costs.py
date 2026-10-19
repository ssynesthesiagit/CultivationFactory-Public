"""Pure per-square surcharges shared by walking, flight and granted movement.

Mounted crawling supplies a surcharge; other movement providers may use the
same query without changing Speed or storing a second movement allowance.
"""


def surcharge(engine, actor, mode="walk"):
    from . import ext

    total = 0
    for value in ext.run_strict("movement_step_surcharge", engine, actor, mode):
        if type(value) is not int or value < 0:
            raise ValueError("Movement step surcharges require nonnegative integer feet")
        total += value
    return total
