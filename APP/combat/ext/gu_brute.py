"""Brute sphere: Hammer (Impact Collision), Break Defenses, Focused Might (Gu Xiangze, 2026-09-28).

Hammer's printed text ("While holding Martial Focus, when a shove would move a creature into a wall, creature, or
solid object no more than one size smaller than the shoved creature, create an Impact Collision. The shoved
creature and the collided object or creature each take: 1d6 Bludgeoning damage. Add: +1d6 for every 5 feet of
forced movement that could not be completed because of the collision.") was typed as a "named" modifier on
"Shove" that the generic apply_modifiers pass matched to Brutal Shove by the word-subset fallback
(factory_compiler._resolve_targets: "shove" <= {"brutal","shove"}). Nothing in that pipeline evaluates a
modifier's free-text "precondition", so the 1d6 landed on *every* Brutal Shove hit, with no Martial Focus check
and no check that the target actually collided with anything -- free damage on every shove. reviewed_final.d/
gu.json nulls Hammer's `modifier` (and its duplicate top-level `effects`) so it stops auto-attaching; this module
supplies the real, gated behaviour via the new `collision` hook (typed_executor._push, combat/ext/__init__.py) that
fires only when a push actually stops short of its distance.

Not modelled: the RAW "no more than one size smaller than the shoved creature" size check on the collided
creature/object (the collision hook only says a step was illegal, not why or by what) -- disclosed on a GM-only
rider rather than guessed at.

Break Defenses ("Whenever you successfully shove a creature, the next attack made against it before the start of
its next turn has Advantage") and Focused Might ("Whenever you successfully shove a creature, regain Martial Focus
as a Bonus Action") both key off a successful Brutal Shove: the Strength (Athletics) contest of combat/ext/brute_shove.py
(its shove_succeeded hook, rider lane C16; before, Brutal Shove was an attack roll and a hit stood for the success). Focused Might is gated with a
"focused_might_ready" self-condition (mirroring the existing target_requires_condition filter used for Extinguish
Flames) rather than being an always-available bonus action, so it stays optional and triggered as printed, not a
free resource refresh on demand.

Ownership lookup: Brutal Shove is built by the standard authority pipeline, not this plug-in, so there is no typed
field of its own to stash "does this actor also own Hammer/Break Defenses" on. Each of the three is therefore
recorded on the fight's own compiled row -- Hammer as a ``block`` (combat/rules/feature_blocks.d/riders_c4.json's
brute_hammer_owned, shared with Crushing Collision and Sovereign Weight Incarnation), Break Defenses as a
``brute_break_defenses`` block, and Focused Might as the action this module compiles for its owner
(``granted.focused_might``) -- which the runtime hooks read through combat/ext/fight_ownership.py. Nothing is cached
outside the fight, so a second fight in the same process is judged only by what it compiled itself.
"""
from __future__ import annotations

from typing import Any

from . import hook
from . import fight_ownership as own
from .ability_source import attack_target_key
from ..gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind

BRUTE = "tianxia.sphere.brute"
BRUTAL_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
FOCUS = "resource:core.martial_focus"
READY = "condition:typed.focused_might_ready"
HAMMER_BLOCK = "brute_hammer_owned"
BREAK_DEFENSES_BLOCK = "brute_break_defenses"
FOCUSED_MIGHT_ACTION = ".granted.focused_might"


@hook("compile_block")
def brute_break_defenses_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Break Defenses' ownership marker (combat/rules/feature_blocks.d/riders_c4.json), the one the shove_riders
    hook below reads. The talent compiles no action of its own, so this row is the fight's whole record of it."""
    return [{**row, "block": BREAK_DEFENSES_BLOCK, **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}] if block == BREAK_DEFENSES_BLOCK else None


@hook("collision")
def hammer(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    if ctx.typed.get("source") != BRUTAL_SHOVE or not own.owns_block(ctx.engine, ctx.actor, HAMMER_BLOCK):
        return
    # Brutal Shove's own base typing rolls two separate forced_movement effects on one hit (a flat 5 ft push, plus
    # a conditional "+5 ft per 5 points the check was exceeded by") -- both share this Context and its damage_cache,
    # so this guard keeps one collision (and one damage roll) per shove even though _push can be entered twice.
    gate = f"hammer_collision:{attack_target_key(ctx, target)}"
    if ctx.damage_cache.get(gate):
        return
    ctx.damage_cache[gate] = True
    if ctx.actor.resources.get(FOCUS, 0) < 1:
        ctx.rider("Hammer: this shove would have caused an Impact Collision, but you are not holding Martial Focus.")
        return
    dice = 1 + max(0, int(remaining_ft) // 5)
    roll = ctx.engine.roller.roll(DiceSpec(count=dice, sides=6, modifier=0), actor_id=ctx.actor.entity_id, reason="HAMMER_IMPACT_COLLISION")
    ctx.engine._record_roll(roll)
    blocker = next((actor for actor in ctx.engine.state.actors.values() if actor.active and actor.entity_id != target.entity_id
                    and actor.position == blocked_at), None)
    ctx.engine._commit_damage(target, roll.total, "BLUDGEONING", ctx.source, ctx.actor.entity_id, ctx.intent, reaction_depth=0)
    if blocker is not None:
        ctx.engine._commit_damage(blocker, roll.total, "BLUDGEONING", ctx.source, ctx.actor.entity_id, ctx.intent, reaction_depth=0)
    else:
        ctx.rider("Hammer: an unattended object at the point of collision takes the same damage where appropriate (GM call).")
    ctx.rider("Hammer: this table does not check the printed 'no more than one size smaller than the shoved "
              "creature' limit on the collision -- apply it by hand if the collided creature is too large.")


@hook("after_hit")
def shove_riders_legacy(ctx: Any, target: Any, kind: str) -> None:
    """A saved fight whose sealed Brutal Shove is still the attack roll (compiled before rider lane C16): a hit stood for the success.
    New bundles have no attack in Brutal Shove, so this never fires for them."""
    if ctx.typed.get("source") == BRUTAL_SHOVE and any(isinstance(e, dict) and e.get("type") == "attack" for e in ctx.typed.get("effects") or []):
        shove_riders(ctx, target, None)


@hook("shove_succeeded")
def shove_riders(ctx: Any, target: Any, result: Any) -> None:
    """A successful Brutal Shove contest (combat/ext/brute_shove.py's shove_succeeded hook; rider lane C16). Dominoes' free shove
    is its own ability and keeps out, as before (tests/test_c4_dominoes_review.py)."""
    if ctx.typed.get("source") != BRUTAL_SHOVE:
        return
    if own.owns_block(ctx.engine, ctx.actor, BREAK_DEFENSES_BLOCK):
        # "the next attack made against it ... has Advantage" -- the same incoming_attack_mode/NEXT_ATTACK/CONSUMED
        # modifier gate2_engine.py already uses elsewhere for an identical "next attack has Advantage" rider.
        ctx.engine._add_modifier(target, ctx.source, "incoming_attack_mode", "ADVANTAGE", 1, "NEXT_ATTACK", expires_on="CONSUMED")
    if own.owns_granted_action(ctx.engine, ctx.actor, FOCUSED_MIGHT_ACTION):
        ctx.engine._apply_condition(ctx.actor, READY, ctx.source, ctx.actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN")


@hook("compile_actions")
def focused_might_button(info: dict[str, Any]) -> list[ActionDefinition] | None:
    if BRUTE not in info["spheres"] or "TAL_BRUTE_FOCUSED_MIGHT" not in info["owned_ids"]:
        return None
    typed = {"effects": [{"type": "gain_resource", "applies_to": "self", "resource_id": FOCUS, "flat": 1}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "range_ft": None,
             "riders": ["Focused Might: available after you successfully shove a creature this turn or last."],
             "source": "TAL_BRUTE_FOCUSED_MIGHT"}
    typed["effects"].insert(0, {"type": "remove_condition", "condition": "focused_might_ready", "applies_to": "self"})
    return [ActionDefinition(
        # New packets use an explicit owner-ready query. A generic target-condition
        # filter could otherwise borrow an ally's marker while restoring the user's Focus.
        source_definition_id=f"action:typed.{info['short']}.granted.focused_might", display_name="Focused Might: Regain Martial Focus",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=5,
        parameters={"typed": typed, "expected_damage": 0, "focused_might_self_ready": True})]


@hook("candidate_allowed")
def focused_might_owner_ready(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("focused_might_self_ready"):
        return None
    return any(c.condition_id == READY for c in actor.conditions.values()) and actor.resources.get(FOCUS, 0) < 1
