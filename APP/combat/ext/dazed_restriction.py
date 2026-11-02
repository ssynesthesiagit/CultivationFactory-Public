"""The one printed rule behind every Daze in Tianxia: a Dazed creature cannot take Reactions and may take either an Action or a
Bonus Action on its turn, not both.

Tianxia defines Daze as a shared custom condition ("Dazed is a Tianxia custom restriction ..." in Drunken Style's The Floor
Betrays You; the same wording in Pressure Points' Shut the Heaven Gate and Brute's Crushing Collision). Each Sphere that can
Daze used to carry its own copy of the two hooks that enforce the Action-or-Bonus half, so a Brute Daze enforced no restriction
at all and a fourth Sphere would have added a fourth copy.

This module is that shared helper. Who uses it: ``pressure_points.pp_dazed`` (Shut the Heaven Gate), ``drunken_style.drunken_dazed``
and ``drunken_style.floor_betrayed_success`` (The Floor Betrays You), and Brute's Crushing Collision place their own condition id
through ``apply``; ``IDS`` lists every printed Daze in the game so the restriction reaches all of them, and the two hooks below
are registered once here for the whole list. ``apply`` replaces only the applying owner's own Daze, so two casters can hold
independent Dazes on one creature and each keeps its own deadline. No hook is registered for any other purpose, and a creature
that is not Dazed is untouched.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .condition_ownership import remove_instance

# Every condition id a printed Daze uses in the game today.
DRUNKEN_DAZED = "condition:typed.drunken_dazed"
PRESSURE_POINT_DAZED = "condition:typed.pp_dazed"
BRUTE_DAZED = "condition:typed.brute_dazed"
IDS = (DRUNKEN_DAZED, PRESSURE_POINT_DAZED, BRUTE_DAZED)

LABEL = "Dazed: no Reactions, and an Action or a Bonus Action on its turn, not both"


def holds(actor: Any) -> bool:
    """Whether ``actor`` currently bears any printed Daze."""
    return any(row.condition_id in IDS for row in (getattr(actor, "conditions", None) or {}).values())


def apply(engine: Any, subject: Any, condition_id: str, source: str, owner_id: str, *,
          expires_on: str | None = None, label: str = LABEL) -> None:
    """Place ``condition_id`` on ``subject`` and deny its Reactions, replacing only this owner's own Daze.

    A re-Daze from the same owner replaces its earlier one, so the Action-or-Bonus restriction never stacks. A Daze from a
    *different* caster is left alone: its own (possibly longer) deadline still runs, and the creature stays restricted
    until the last of them expires (``holds`` is true while any printed Daze remains). This is what Pressure Points'
    Shut the Heaven Gate did before the shared helper -- one caster's Daze never deleted another's.

    Each replacement removes the selected instance only. The engine's ``_remove_condition`` deletes *every* instance
    carrying the condition id and only uses its ``source_id`` argument to attribute the removal event, so calling it
    here made a refresh silently end another caster's still-running Daze and lose its longer deadline. This module uses
    the shared exact-instance helper instead (``condition_ownership.remove_instance``), which is what the next-attack,
    next-damage and Overstrain riders use for the same reason.
    """
    if subject is None or not subject.active:
        return
    for iid, held in list(subject.conditions.items()):
        if held.condition_id in IDS and held.source_actor_id == owner_id:
            remove_instance(engine, subject, iid, held.source_definition_id)
    engine._apply_condition(subject, condition_id, source, owner_id, expires_on=expires_on or "UNTIL_REMOVED",
                            data={"label": label})
    subject.reaction_available = False


@hook("candidate_allowed")
def dazed_one_action(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"A Dazed creature ... may take either an Action or a Bonus Action on its turn, not both" (the Tianxia custom Daze)."""
    if action is None or not holds(actor):
        return None
    economy = str(getattr(getattr(action, "economy", None), "value", getattr(action, "economy", "")) or "")
    if economy.endswith("BONUS_ACTION") and not actor.action_available:
        return False
    if economy.endswith("ACTION") and not economy.endswith("BONUS_ACTION") and not actor.bonus_action_available:
        return False
    if economy.endswith("REACTION"):
        return False
    return None


@hook("reaction_allowed")
def dazed_no_reaction(engine: Any, reactor: Any, other: Any) -> bool | None:
    """"A Dazed creature cannot take Reactions" (the Tianxia custom Daze)."""
    return False if holds(reactor) else None