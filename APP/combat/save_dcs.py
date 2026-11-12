"""The printed Save DCs a creature defends a check with, and nothing else.

Owner 2026-10-05 (AUTO16f1 review, finding 1): "Make a Sound Check against the triggering
creature's Save DC, Cultivation Save DC, or named sphere Save DC" is a comparison with a
number. Rolling a defending saving throw instead (what ``kind: save`` does) uses a stat the
printed line never names and adds a second die. This module is the one place that answers
"what is that creature's Save DC", so a printed DC and a rolled save can never be confused
for one another again.

Who uses it:
  * combat/typed_executor.resolve_opposed_check -- the ``kind: "dc"`` branch of a target check
    (any printed "your check against X's <name> Save DC").
  * combat/ext/contests.py -- ``select_check``, so a defender picking between several printed
    DC alternatives ranks them, and combat/ext/contests.py's own prompt names the one used.

Three bases, all read from the defender's own sealed numbers (``combat/ext/needle.numbers_of``
-- the compiled numbers that survive a table commit and reload):
  ``save_dc``      the creature's own Save DC: the Save DC its sheet records, else
                   8 + Proficiency Bonus + Key Ability modifier.
  ``cultivation`` 8 + Proficiency Bonus + Key Ability modifier. The Cultivation Save DC a
                   sphere save uses (combat/ext/d20_rewrite.py ``save_dc``).
  ``sphere``      the same 8 + Proficiency Bonus + Key Ability modifier, because a named
                   sphere's talent casts from the Key Ability too; it can differ from
                   ``save_dc`` only where a sheet records a Save DC of its own.

A creature with no compiled numbers falls back to Proficiency Bonus + 2, the same default
combat/ext/needle.py uses. This is a pure query: it reads no state, writes none, and rolls
nothing, so a saved fight reloads to the same number.
"""

from __future__ import annotations

from typing import Any

# The printed names a typed row may use for a target check. Unknown names read as "own Save DC".
BASES = ("save_dc", "cultivation", "sphere")
DEFAULT = "save_dc"


def numbers(engine: Any, actor: Any) -> dict[str, Any]:
    """The creature's own sealed combat numbers; ``{}`` when it compiled none."""
    from .ext.needle import numbers_of

    return dict(numbers_of(engine, actor) or {})


def save_dc(engine: Any, actor: Any, basis: str = DEFAULT, *, sphere_id: str | None = None) -> int:
    """The number a check is compared against for this printed basis (see the module docstring)."""
    from .ability_checks import key_modifier

    # Named-sphere providers answer only their owned scope. Ordinary Save DC
    # and Cultivation DC queries retain the historical formula.
    if basis == "sphere" and sphere_id:
        from .ext import run_strict

        for value in run_strict("named_save_dc", engine, actor, sphere_id):
            if value is not None:
                return int(value)
    sealed = numbers(engine, actor)
    pb = int(sealed.get("pb") or getattr(actor, "proficiency_bonus", 0) or 2)
    formula = 8 + pb + key_modifier(engine, actor, numbers=sealed)
    if str(basis) in ("cultivation", "sphere"):
        return formula
    recorded = sealed.get("save_dc")
    return int(recorded) if recorded else formula