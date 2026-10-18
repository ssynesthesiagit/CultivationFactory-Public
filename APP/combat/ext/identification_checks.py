"""Identification checks: one documented seam that says a check identifies a magic thing, and
adds every check_bonus subscriber's flat bonus to it.

A printed "Intelligence check to identify a spell, sphere technique, talisman effect, or Active
Qi Pattern" is an ordinary ability check on the table (combat/ext/talismans.py Read the Script
reads what a talisman's writing does; combat/ext/figment.py Study an illusion recognizes a false
image). Those two checks roll their own die, so without this seam no subscriber of the existing
``check_bonus`` hook can ever reach them, and an ability that prints a bonus for exactly these
checks would print a number a player never receives.

Producers mark the check they are about to roll with :func:`identifying` (or take its bonus with
:func:`identification_bonus`). Subscribers ask :func:`is_identification`. The marker lives on an
ephemeral copy of the check context exactly like the documented ``ctx.escape_hazards`` and
``ctx.resists_gravity`` scope fields: nothing is saved, no existing check changes, and an unmarked
check stays inert for everyone.
"""
from __future__ import annotations

from typing import Any

#: The one ``check_purpose`` value that names an identification check.
IDENTIFICATION = "identification"


def identifying(ctx: Any, *, ability: str = "INT", skill: str | None = None,
                kind: str | None = None) -> Any:
    """An ephemeral copy of ``ctx`` naming the check it is about to roll an identification check.

    ``kind`` records what the writing is (a talisman effect, an illusion, ...), so a subscriber
    can narrow itself without reading the action name. Absent values are simply absent; the caller's
    own context is never modified.
    """
    from copy import copy

    marked = copy(ctx)
    typed = dict(getattr(ctx, "typed", None) or {})
    typed["check_purpose"] = IDENTIFICATION
    typed["ability"] = str(ability).upper()
    if skill:
        typed["skill"] = skill
    if kind:
        typed["identification_kind"] = kind
    marked.typed = typed
    return marked


def is_identification(ctx: Any) -> bool:
    """True only for a context a producer marked with :func:`identifying`.

    A skill name alone is never enough: Arcana, Investigation and Calligrapher's Supplies are used
    for many unrelated checks, so a check that no producer marked grants nothing.
    """
    return str((getattr(ctx, "typed", None) or {}).get("check_purpose") or "") == IDENTIFICATION


def identification_bonus(ctx: Any, actor: Any, *, ability: str = "INT", skill: str | None = None,
                         kind: str | None = None) -> int:
    """Every ``check_bonus`` subscriber's flat bonus for this one marked identification check.

    This is the same public hook and the same aggregation the shared check resolvers use, applied to
    a check that rolls its own die. Nothing is rolled here and no state is kept; the caller adds the
    returned integer to its own modifier before drawing.
    """
    from . import run

    return sum(int(value) for value in run("check_bonus", identifying(ctx, ability=ability,
                                                                    skill=skill, kind=kind), actor)
               if isinstance(value, int))