"""Soft Capture: the creature the response catches chooses Strength or Dexterity for its save.

Rules text (…85Spheres.md:31712, record TAL_FLOWING_RIVER_SOFT_CAPTURE): "When your Flowing Response succeeds
against a creature within reach, the triggering creature makes a Strength or Dexterity saving throw, choosing
which, against your Cultivation Save DC." The who/reach/free-hand requirement, the Grappled consequence and the
"you may move 5 feet" step are native in combat/ext/flowing_river.py.

The choice itself is data: the rider save in authority/typed_mechanics/reviewed_final.d/review_sw-fire.json carries
target_choice=True, so combat/ext/save_choices.py asks the caught creature through the ordinary save_choice seam
(and combat/typed_executor.py's better-ability selector stands only when nobody answers).

This module only enrolls the caught creatures for the service's ask-me probe (choice_reactors).

Enrollment (choice_reactors): the caught creature is the one that attacks, or otherwise triggers Flowing
Response against, the Soft Capture owner, so it is an opponent of that owner (relation ENEMY). Only those opponents
are enrolled. A creature on the owner's side (an ally, or the owner itself) can never be caught by that owner, so
it is not enrolled and cannot be pulled into the service's ask-me reactor set (_ask_reactors) or hold the fight
with a prompt of its own. In a fight with two Soft Capture owners who are enemies, each can catch the other, and
both are enrolled. A fight with no Soft Capture owner enrolls nobody and stays inert. No stored state, no new
field, no expiry token.
"""
from __future__ import annotations

from typing import Any

from . import hook

TALENT = "TAL_FLOWING_RIVER_SOFT_CAPTURE"


def owns(engine: Any, actor_id: str) -> bool:
    """Whether this character owns Soft Capture (a "when: success" rider riding Flowing Response's row)."""
    rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(actor_id, []),
            *(getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])]
    return any(not row.get("held_back") and any(
        isinstance(effect, dict) and effect.get("type") == "on_success" and effect.get("talent") == TALENT
        for effect in row.get("effects") or []) for row in rows)


@hook("choice_reactors")
def potential_savers(engine: Any) -> tuple[str, ...]:
    """The opponents of each Soft Capture owner: the only creatures Flowing Response can catch."""
    from ..relations import ENEMY, relation
    actors = engine.state.actors
    owners = [actors[actor_id] for actor_id in actors if owns(engine, actor_id)]
    return tuple(actor_id for actor_id, actor in actors.items()
                 if any(relation(engine, owner, actor) == ENEMY for owner in owners))
