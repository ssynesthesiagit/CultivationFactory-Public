"""A Shield's +2 AC follows whether the fighter still has the shield in the fight (MMX34, 2026-10-02).

A shield is not worn body armour, so it is never dropped by taking the armour off: it has its own Drop and Pick up
actions, and another creature can take it out of a fighter's hands (needle bind, open hand).  The Shield's +2 is
folded into the compiled Armor Class -- one number the sheet and the fight both read -- so a shield that leaves the
fighter's hands mid-fight has to be taken back somewhere it can change: the ``ac`` hook, which the engine sums into
``_ac_modifier``.

This plug-in is that one subtraction, and it owns all of it.  ``combat/armour.py`` answers the single question every
reader now shares:

* ``compiled_shield_bonus`` -- the +2 already inside the compiled AC, read from the ``shield_ac`` passive row;
* ``shield_bonus_earning``  -- that +2 only while the shield is still in hand and unbroken;
* ``shield_bonus_lost``     -- the difference, which is what this plug-in subtracts.

Because the earning number is the ceiling, the other places that deny a Shield Bonus subtract from the same
ceiling rather than a second copy of it: ``shield_riders``' Sacrificial Shield (the shield is broken) and
``guard_broken`` (a talent denies it against one attack).  A fighter whose shield is dropped *and* broken therefore
loses the +2 once, not twice.

Inert without both a shield row and an inventory marker. The existing
shield_riders hook still owns broken-shield penalties for unmarked saved fighters.
"""

from __future__ import annotations

from typing import Any

from . import hook


@hook("ac")
def shield_in_hand(engine: Any, target: Any) -> int | None:
    """Take back the +2 AC a shield gives when the fighter no longer has it (dropped, taken, or broken)."""
    from .. import armour

    if armour.shield_item_key(engine, target) is None:
        return None  # legacy broken shields remain owned by shield_riders
    from .shield_wielding import orbiting, wielding_a_shield

    if orbiting(engine, target) and wielding_a_shield(engine, target):
        return None  # an explicitly orbiting, usable Shield retains its compiled bonus
    return -armour.shield_bonus_lost(engine, target) or None
