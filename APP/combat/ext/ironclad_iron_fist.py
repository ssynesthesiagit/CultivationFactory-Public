"""Iron Fist sphere mechanisms (owner 2026-09-28, auto-ironclad worker: the Iron Fist sphere is owned by this
worker for every fielded character, not just Lingfeng Ironclad -- see the coordinator's ownership message).

Two things live here that the data-only fixes in authority/typed_mechanics/reviewed_final.d/ironclad.json cannot
express because they need state that spans two separate attack rolls within the same turn:

- Crane-Step Combination ("After you hit with an Unarmed Strike, move up to 10 feet... If your next Unarmed
  Strike before the end of the turn targets a DIFFERENT creature, add your Proficiency Bonus to its damage"):
  the bonus belongs to a *later* hit, not the triggering one.
- Hammer-and-Anvil Rhythm ("Once per turn, when you hit the same creature with two or more Unarmed Strikes
  during your turn, choose one: ... regain Martial Focus if it is absent"): needs a same-target hit counter.
  Its own printed modifier of Unarmed Strike has no attachable effects, so combat/rules/feature_blocks.d/
  ironclad.json marks it "automated" under a private block name this module recognises.
"""

from __future__ import annotations

from typing import Any

from . import hook

CRANE_STEP_ID = "TAL_IRON_FIST_CRANE_STEP_COMBINATION"
HAMMER_ANVIL_ID = "TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM"
MARTIAL_FOCUS = "resource:core.martial_focus"


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block == "ironclad_hammer_anvil":
        return [row]  # a bare marker row; _after_unarmed_hit below only checks that it exists
    return None


@hook("after_hit")
def _after_unarmed_hit(ctx: Any, target: Any, kind: str) -> None:
    if kind != "unarmed":
        return
    actor, engine = ctx.actor, ctx.engine

    # Crane-Step Combination: "after you hit with an Unarmed Strike" -- every hit arms it (it is free and
    # harmless, so factory_compiler.py's apply_modifiers merges it straight into the base Unarmed Strike rather
    # than making it a separate variant; the _ironclad_crane_step marker on its own movement effect, set in
    # reviewed_final.d/ironclad.json, is how this hook recognises "this character has Crane-Step Combination"
    # once merged, since a merge carries no per-modifier "id" the way an optional variant would). Pay the bonus
    # out on the next different-target Unarmed Strike hit this turn, then clear it.
    pending_key = "ironclad_crane_step_target"
    # apply_modifiers stamps every effect it merges in with "source_modifier": <mechanic id> (combat/
    # factory_compiler.py); Crane-Step Combination's own effects live nested under the attack's own "on_hit"
    # list, not at the top level, so this walks one level in rather than using typed_executor's generic _walk
    # (a private helper of that module) just to check one specific, known shape.
    nested = [row for effect in ctx.typed.get("effects") or [] if isinstance(effect, dict) for row in effect.get("on_hit") or []]
    has_crane_step = any(isinstance(row, dict) and row.get("source_modifier") == CRANE_STEP_ID
                         for row in (*(ctx.typed.get("effects") or []), *nested))
    if has_crane_step:
        pending = actor.turn_flags.get(pending_key)
        if pending and pending != target.entity_id and target.active:
            pb = int(ctx.numbers.get("pb") or 0)
            if pb > 0:
                engine._commit_damage(target, pb, "BLUDGEONING", f"{CRANE_STEP_ID}.buff", actor.entity_id, None, reaction_depth=0)
                ctx.rider(f"Crane-Step Combination: +{pb} Bludgeoning (different target from the strike that armed it).")
        actor.turn_flags[pending_key] = target.entity_id  # this hit re-arms it, against its own target, either way

    # Hammer-and-Anvil Rhythm: once per turn, on the second (or later) Unarmed Strike hit against the same
    # creature this turn, regain Martial Focus if it is absent (the only one of its three choices with a clear,
    # always-distinct mechanical effect -- see the reviewed_final rider for why the other two are not offered).
    from .iron_fist_riders import config
    if "rhythm" in config(engine, actor):
        return
    if actor.turn_flags.get("ironclad_hammer_anvil_used"):
        return
    from .. import typed_reactions

    if not typed_reactions._rows(engine, actor.entity_id, "ironclad_hammer_anvil"):
        return
    count_key = f"ironclad_hammer_anvil_hits:{target.entity_id}"
    count = int(actor.turn_flags.get(count_key) or 0) + 1
    actor.turn_flags[count_key] = count
    if count >= 2 and actor.resources.get(MARTIAL_FOCUS, 0) <= 0:
        actor.turn_flags["ironclad_hammer_anvil_used"] = True
        engine._gain_resource(actor, MARTIAL_FOCUS, 1, HAMMER_ANVIL_ID)
        ctx.rider("Hammer-and-Anvil Rhythm: regained Martial Focus (two Unarmed Strikes landed on the same creature this turn).")
