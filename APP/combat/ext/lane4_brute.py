"""Brute: Takedown (Manhandle) and Follow-Through (auto-lane4 2026-09-29). Both were GM-only lines.

Takedown ("After the shove succeeds, if the target remains within reach, attempt to Grapple it.") is a Manhandle talent, so
it rides Brutal Shove (reviewed_final.d/auto_lane4.json: an optional ``hit`` modifier on "Brutal Shove", which the compiler
turns into a "Brutal Shove + Takedown" variant like the other Manhandle talents). The modifier's one effect,
``lane4_takedown_grapple``, is the ordinary 2024 Grapple attempt the unarmed strike already has (the target, no more than
one size larger, makes a Strength or Dexterity save against 8 + Strength modifier + Proficiency Bonus; on a failure it is
Grappled until it escapes), made only when the target is still within reach once the shove's own effects have moved it. The
sealed Brutal Shove typing pushes and knocks Prone on every hit, so the Grapple mostly fires when the push is cut short
(a wall, another creature) -- that is the printed "remains within reach", not a limit added here.

Follow-Through ("After you damage a creature with a melee weapon attack, shove that creature as a Bonus Action.") is a
Bonus Action shove: a copy of the character's own Brutal Shove (same typing, so Hammer, Break Defenses, Focused Might and
the Manhandle variants all apply to it) that can only be aimed at a creature the character has just damaged with a melee
weapon attack this turn. The ``after_hit`` hook puts a mark on the creature that lasts to the end of the character's turn,
the action is offered only against a marked creature, and using it takes the mark off.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from . import fight_ownership as own
from ..gate2_runtime_models import ActionDefinition, EconomyKind

BRUTE = "tianxia.sphere.brute"
BRUTAL_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
FOLLOW_THROUGH = "TAL_BRUTE_FOLLOW_THROUGH"
FOLLOW_THROUGH_ACTION = ".granted.follow_through_shove"
MARK = "condition:typed.lane4_follow_through"


def _mark_id(actor_id: str) -> str:
    return f"{MARK}.{actor_id}"  # per owner: another Brute's mark on the same creature is not this one's


@effect("lane4_takedown_grapple")
def takedown_grapple(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    subject = ctx.target
    if subject is None or not subject.active or subject.entity_id == ctx.actor.entity_id:
        return
    # "if the target remains within reach" is the creature's own natural reach -- the body, never a weapon. A shove made
    # through a tether is declared with the tether's reach, and a reach weapon is not natural reach either, so neither
    # may become natural reach for this talent; a printed body form that really lengthens the body does count, because
    # reach_bonus.natural_reach_ft reads the same "Unarmed reach +N feet" rows the attack menus do.
    from . import reach_bonus

    reach = reach_bonus.natural_reach_ft(ctx.engine, ctx.actor)
    if ctx.engine._distance_actor_to_actor(ctx.actor, subject) > reach:
        ctx.rider("Takedown: the target is no longer within reach, so there is no Grapple attempt.")
        return
    dc = 8 + int(ctx.numbers.get("pb") or 2) + int(ctx.actor.saving_throws.get("STR", 0) or 0)
    typed = {**ctx.typed, "numbers": {**ctx.numbers, "save_dc": dc}}
    inner = typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, [subject], subject)
    typed_executor.block_save(inner, {"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1,
                                      "on_fail": [{"type": "condition", "condition": "grappled", "applies_to": "target", "until_escape": True}]})


@hook("compile_actions")
def follow_through_shove(info: dict[str, Any]) -> list[ActionDefinition] | None:
    if FOLLOW_THROUGH not in info["owned_ids"] or BRUTE not in info["spheres"]:
        return None
    base = next((action for action in info.get("actions") or ()
                 if str(action.source_definition_id).endswith("." + BRUTAL_SHOVE)), None)
    if base is None:
        return None
    parameters = copy.deepcopy(base.parameters)
    typed = parameters.get("typed") or {}
    typed["effects"] = [{"type": "lane4_follow_through_used"}, *typed.get("effects", [])]
    typed["riders"] = [*(typed.get("riders") or []), "Follow-Through: a Bonus Action shove against a creature you just damaged with a melee weapon attack."]
    parameters["typed"] = typed
    parameters["target_requires_condition"] = _mark_id(info["actor_id"])
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.granted.follow_through_shove", display_name="Follow-Through: Brutal Shove",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind=base.target_kind,
        range_ft=base.range_ft, reach_ft=base.reach_ft, attack_bonus=base.attack_bonus, attack_count=1, damage=base.damage,
        damage_type=base.damage_type, save=base.save, radius_ft=base.radius_ft, parameters=parameters)]


@effect("lane4_follow_through_used")
def follow_through_used(ctx: Any, eff: dict[str, Any]) -> None:
    if not str(ctx.source).endswith("granted.follow_through_shove"):
        return  # the plain Brutal Shove carries no mark to spend
    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        ctx.engine._remove_condition(subject, _mark_id(ctx.actor.entity_id), ctx.source)


@hook("after_hit")
def follow_through_mark(ctx: Any, target: Any, kind: str) -> None:
    # The Follow-Through shove this fight compiled for the actor is its own record that the talent is owned
    # (combat/ext/fight_ownership.py), so a fight that never compiled one cannot mark anything.
    if kind != "weapon" or not own.owns_granted_action(ctx.engine, ctx.actor, FOLLOW_THROUGH_ACTION) or target is None or not target.active \
            or target.entity_id == ctx.actor.entity_id:
        return
    if int(ctx.typed.get("range_ft") or 0) > 5:
        return  # a melee weapon attack
    if any(condition.condition_id == _mark_id(ctx.actor.entity_id) for condition in target.conditions.values()):
        return
    # "After you damage a creature": the hit must have dealt damage.
    dealt = next((event for event in reversed(ctx.engine.events[-25:])
                  if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ctx.actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    if dealt is None or int((dealt.payload or {}).get("hp_damage") or 0) + int((dealt.payload or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    ctx.engine._apply_condition(target, _mark_id(ctx.actor.entity_id), FOLLOW_THROUGH, ctx.actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started)}",
                                data={"label": "Follow-Through: may be shoved as a Bonus Action"})
