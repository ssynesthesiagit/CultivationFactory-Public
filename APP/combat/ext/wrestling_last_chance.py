"""Last Chance Grapple (lane 1 automation, 2026-09-29): "When one creature succeeds on its saving throw against your Unarmed
Strike Grapple option, expend Martial Focus. Use a Bonus Action before the end of your turn to attempt to Grapple the same
creature again." It was an inert Bonus Action: nothing remembered whose save had just held, and the retry had no Grapple to
roll.

Effect type "last_chance_grapple" (the ability's one effect; the ability's cost row spends the Martial Focus): rolls the
character's own Unarmed Strike Grapple option again -- the same Strength-or-Dexterity save against 8 + PB + Strength, the
same size limit, the same Grappled on a failure -- against the creature that just made its save, with no extra Attacks
(the option's other Attacks belong to the Attack action, not to this Bonus Action).

Hook use: after_save -- a successful save against an Unarmed Strike Grapple option notes the creature on the attacker's turn
flags (cleared at the start of its next turn, which is "before the end of your turn"); candidate_allowed -- Last Chance
Grapple is offered only against a creature so noted, and each note is used up by one retry.
Determinism: turn flags and the engine's own save roll; nothing else is kept.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

NOTED = "last_chance_grapple_targets"  # no "_round_" in the key: it is cleared when the attacker's next turn starts
MECHANIC_ID = "TAL_WRESTLING_LAST_CHANCE_GRAPPLE"


def _is_last_chance(action: Any) -> bool:
    return action is not None and ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") == MECHANIC_ID


@hook("after_save")
def note_a_held_grapple(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if failed or (ctx.typed or {}).get("unarmed_option") != "grapple":
        return
    noted = list(ctx.actor.turn_flags.get(NOTED) or [])
    if subject.entity_id not in noted:
        ctx.actor.turn_flags[NOTED] = [*noted, subject.entity_id]


@hook("candidate_allowed")
def only_against_the_creature_that_held(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not _is_last_chance(action):
        return None
    noted = actor.turn_flags.get(NOTED) or []
    return False if not (candidate.target_ids and candidate.target_ids[0] in noted) else None


@effect("last_chance_grapple")
def last_chance_grapple(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    grapple = ctx.engine.action_catalog.get(f"{ctx.source.rsplit('.', 1)[0]}.unarmed.grapple")
    if grapple is None:
        ctx.rider("Last Chance Grapple needs a free hand for the Unarmed Strike Grapple option.")
        return
    typed = copy.deepcopy((grapple.parameters or {}).get("typed") or {})
    typed["effects"] = typed.get("effects", [])[:1]  # the Grapple attempt alone: no further Attacks of the Attack action
    typed.pop("unarmed_option", None)  # the retry is not the Unarmed Strike option, so a held retry does not open another
    ctx.actor.turn_flags[NOTED] = [t for t in ctx.actor.turn_flags.get(NOTED) or [] if t not in {s.entity_id for s in ctx.targets}]
    typed_executor.run_effects(typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, list(ctx.targets), ctx.target,
                                                      ctx.damage_cache), typed["effects"])
