"""Parry Anything (auto-lane4 2026-09-29): "You may use Parry and Riposte when a ranged weapon attack or ranged spell attack
hits you. You may make the retaliatory attack only if the attacker is within the legal reach or range of the attack form you
use for the riposte. Parry Anything does not reduce damage from an effect that does not hit you with an attack roll."

Parry and Riposte is a generic reaction row whose printed trigger is "a creature hits you with a melee attack", so the row is
``melee_only``. Parry Anything is a named modifier of that row (reviewed_final.d/auto_lane4.json); the one effect it adds,
``lane4_parry_ranged``, does nothing when run -- the row simply carries it, and ``typed_reactions._generic_kind_ok`` lets a row
that carries it answer a ranged attack that hit as well. The reaction still needs an attack roll to have hit (the reaction fires
from the hit), so damage from a save-based or automatic effect is never parried, as printed. The riposte itself is the base
talent's melee attack "if it is within your reach" and stays with the base talent's rider; a ranged attacker beyond reach is
simply not riposted.
"""

from __future__ import annotations

from typing import Any

from . import effect

MARKER = "lane4_parry_ranged"


@effect(MARKER)
def parry_ranged(ctx: Any, eff: dict[str, Any]) -> None:
    return None
