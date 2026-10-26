"""One shared test of a creature's own Hit Point state, for passives printed "while you are ...".

Two printed readings exist and they differ at exactly half: ``below_half`` ("while you are below half your maximum Hit
Points") is strict, ``bloodied`` ("while you are Bloodied", "at or below half") is the engine's Bloodied test
(combat/ext/blood_bloodied.py). A gated row names one of them in ``requires_self`` (``while`` on a motion row):

* typed effect rows, through the ``effect_allowed`` gate (the gated on-hit damage of a passive; skipped before any
  once-per-turn use is consumed);
* ``defense`` rows (Advantage on a save: combat/pressure.save_advantage) and ``motion`` rows (combat/motion._holds), which
  call ``holds`` directly.

Nothing here knows an ability: the data names the state, this reads the actor's current and maximum HP. A creature that
conceals its HP from others is still tested on the real numbers (the printed rule says the owner knows).
"""

from __future__ import annotations

from typing import Any

from . import hook
from .blood_bloodied import is_bloodied

STATES = frozenset({"below_half", "bloodied"})


def holds(creature: Any, state: str | None) -> bool:
    """True when ``state`` is empty or the creature is in it; an unknown name never holds."""
    if not state:
        return True
    if state not in STATES:
        return False
    if state == "bloodied":
        return is_bloodied(creature)
    return bool(creature is not None and creature.active and creature.maximum_hp > 0
                and creature.current_hp * 2 < creature.maximum_hp)


@hook("effect_allowed")
def effect_allowed(ctx: Any, eff: dict) -> bool | None:
    state = eff.get("requires_self")
    return False if state and not holds(ctx.actor, state) else None
