"""Returning Tide Body: the once-per-scene Jujutsu follow-up.

The printed rule (authority/typed_mechanics/reviewed_final.d/a2_insights7.json,
printed text ea47369e...): "Once per scene: Immediately after you successfully
redirect or throw a hostile creature through a Jujutsu feature, regain 1
Stamina, move up to 5 feet without provoking Opportunity Attacks, and gain
Advantage on the next Grapple roll you make before the end of your next turn."

The trigger is a Jujutsu feature's resolution moving or throwing the hostile
creature, which jujutsu.py now reports through the general, default-inert
``jujutsu_redirect_or_throw`` seam (documented in combat/ext/__init__.py):
Redirect Force's printed creature-moving option (the redirect), and Throw's
failed-save resolution (the throw).  The strict reading of "redirect or throw
a hostile creature" is the creature itself being moved or thrown: the
move-yourself and move-around options redirect nobody, the attack-redirection
options of Harmonious Body and Empty Body redirect an attack rather than a
creature, and a successful Throw save is a failed throw.

The three printed benefits are automatic once the trigger lands, so the
observer spends the scene's allowance on the trigger and applies all of them:
the Stamina regain is the engine's own resource gain, the step is the shared
``rider_step`` effect (5 feet, no opportunity attacks from any creature), and
the Grapple Advantage is a condition on the owner that the table's save
resolution reads: the table runs Grapple and Shove as the target's Strength
or Dexterity save, so the owner's Advantage is that save's Disadvantage (the
same model Redirect Force's own "Advantage on your next Grapple or Shove"
uses), consumed by the first such save and expiring at the end of the owner's
next turn.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import hook, note
from .effect_durations import token
from .passive_rows import row_of
from ..relations import ENEMY, relation

FEATURE = "insight.returning-tide-body"
BLOCK = "returning_tide"
KIND = "returning_tide"
USED = "_round_returning_tide_used"
TIDE_EDGE = "condition:typed.returning_tide_grapple"
STAMINA = "resource:core.stamina"

OUTCOME = ("Once per scene, immediately after you successfully redirect or throw a hostile "
           "creature through a Jujutsu feature: regain 1 Stamina, move up to 5 feet without "
           "provoking Opportunity Attacks, and your next Grapple before the end of "
           "your next turn has Advantage")


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Compile the Insight's passive row from its feature block."""
    if block != BLOCK:
        return None
    return [{**row, "kind": KIND, "pb": int(numbers["pb"]), "cl": int(numbers["cl"]), "player_outcome": OUTCOME}]


@hook("jujutsu_redirect_or_throw")
def returning_tide(engine: Any, owner: Any, creature: Any, feature_id: str, ctx: Any) -> None:
    """The printed follow-up, once per scene, after a Jujutsu redirect or throw."""
    if owner is None or not getattr(owner, "active", False) or creature is None:
        return
    if relation(engine, owner, creature) != ENEMY:
        return  # the trigger is a hostile creature
    row = row_of(engine, owner.entity_id, BLOCK, KIND)
    if row is None or owner.turn_flags.get(USED):
        return
    owner.turn_flags[USED] = 1
    engine._gain_resource(owner, STAMINA, 1, f"passive:{FEATURE}")
    from ..typed_executor import run_effects

    # The step runs through the shared rider_step effect on a Context whose
    # actor is the Insight's owner (the seam's ctx carries the Jujutsu
    # resolution, whose actor may be the creature that attacked).
    run_effects(replace(ctx, actor=owner, target=creature, targets=[creature]),
                [{"type": "rider_step", "distance_ft": 5, "no_oa": True,
                  "label": "Returning Tide Body", "trigger": _names(feature_id)}])
    engine._apply_condition(owner, TIDE_EDGE, FEATURE, owner.entity_id,
                            expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": (f"Returning Tide Body: {owner.display_name}'s next Grapple "
                                            f"before the end of its next turn has Advantage")})
    note(engine, FEATURE, owner, f"Returning Tide Body: {owner.display_name} regains 1 Stamina, "
         f"moves up to 5 feet without provoking Opportunity Attacks, and its next Grapple "
         f"before the end of its next turn has Advantage.", (creature,))


def _names(feature_id: str) -> str:
    """The plain feature name for the step's question."""
    return {"tianxia.subpath.body.jujutsu.feature.redirect_force": "Redirect Force",
            "tianxia.subpath.body.jujutsu.feature.throw": "Throw"}.get(feature_id, "a Jujutsu feature")


@hook("save")
def returning_tide_edge(ctx: Any, subject: Any, ability: Any, named: Any) -> dict[str, Any] | None:
    """The owner's next Grapple: the target's save against it has Disadvantage."""
    actor = ctx.actor
    if (subject is None or actor is subject or "grappled" not in set(named or ())
            or not _grapple(ctx)):
        return None
    held = next((c for c in actor.conditions.values()
                 if c.condition_id == TIDE_EDGE and c.source_actor_id == actor.entity_id), None)
    if held is None:
        return None
    ctx.engine._remove_condition_instance(actor, held.instance_id, FEATURE, expected=held)
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


def _grapple(ctx: Any) -> bool:
    """The table runs Grapple and Shove as the target's save against a maneuver."""
    for row in ctx.typed.get("effects") or []:
        if (isinstance(row, dict) and row.get("type") == "save" and row.get("max_size_larger") is not None
                and any(isinstance(effect, dict) and effect.get("type") == "condition"
                        and effect.get("condition") == "grappled"
                        for effect in row.get("on_fail") or [])):
            return True
    return False
