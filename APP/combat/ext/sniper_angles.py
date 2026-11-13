"""Sniper shot angles (rider lane C11, 2026-09-30): Bouncing Shot with Through the Wrong Door / World-Needle Ricochet, and
Phasic Shot, ignoring a target's Half and Three-Quarters Cover.

Source (owner text, authority/typed_mechanics/rules_text.json TAL_SNIPER_*):
  Bouncing Shot: "When making a Snipe Shot, you may expend Martial Focus to bounce your attack off a visible ... hard surface."
  Through the Wrong Door: "When you use Bouncing Shot, the attack may ignore Half Cover or Three-Quarters Cover if the bounce
    creates a believable attack angle. If you expend Martial Focus, you may also ignore the Disadvantage from attacking a target
    you cannot see, provided you know its exact location ..."
  World-Needle Ricochet: "When you use Bouncing Shot ... At the end of the shot's route, you may ignore Half Cover and
    Three-Quarters Cover."
  Phasic Shot: "When making a Snipe Shot through an Aimed Line, expend Martial Focus and spend 2 CP. For this attack, you ignore
    cover, including Total Cover, between you and the target."

Integration: newly compiled Bouncing Shot uses bouncing_shot's native route and
cover-reduction hooks. The older angle gate and attack-bonus compensation below
remain only for saved catalogs without that route effect. Through the Wrong
Door still owns its unseen-target rider; Phasic Shot keeps its existing rider.

Legacy saved-catalog behavior.
  * Bouncing Shot's typed modifier costs Martial Focus (reviewed_final.d/riders_c11.json), so a Snipe Shot has a "+ Bouncing
    Shot" variant. Its own gain -- a shot around a corner to a target out of sight, with range counted along the bounce -- cannot
    run: the engine offers a ranged target only in line of sight (gate2 candidate rules, a saved-fight lock file). The variant is
    therefore offered only to a shooter who owns Through the Wrong Door or World-Needle Ricochet (feature block
    ``sniper_angles``, combat/rules/feature_blocks.d/riders_c11.json), whose gain runs at the table.
  * Ignoring cover: the engine adds a target's cover to its AC, and no hook takes cover away, so ``attack_bonus`` adds exactly
    that cover (+2 Half, +5 Three-Quarters: the same current cover query as hit resolution, including directional shield faces)
    to the shot's attack roll -- the same hit or miss as ignoring it -- and logs it in plain words. Total Cover cannot be targeted
    at all (the Phasic Shot "including Total Cover" line stays a rider: blocked by the same line-of-sight rule).
  * Through the Wrong Door's "If you expend Martial Focus": Bouncing Shot has already expended it (one Martial Focus is held at a
    time), so the reading is that the bounced shot also drops the Disadvantage for an unseen target (hook ``unseen_ignored``) --
    but not against a Hidden target, whose exact location the shooter does not know.
  * "if the bounce creates a believable attack angle": the table assumes a bounce surface exists (a GM may veto it).
Default-inert for everyone without the feature row (Bouncing) or a Phasic Shot variant.

Shared: ``current_cover`` is the public entry point for "how much cover does this target have against this
shooter right now" and is consumed by sniper_rangefinding.py (Rangefinding Breath reads the cover for the
shooter while Martial Focus is held). It is the one cover query both read.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

BLOCK = "sniper_angles"
BOUNCING = "TAL_SNIPER_BOUNCING_SHOT"
PHASIC = "TAL_SNIPER_PHASIC_SHOT"
WRONG_DOOR = "through_the_wrong_door"
RICOCHET = "world_needle_ricochet"
_COVER_NAMES = {2: "Half Cover", 5: "Three-Quarters Cover"}


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind")}]


def _kinds(engine: Any, actor: Any) -> set[str]:
    from .. import typed_reactions

    return {str(row.get("kind")) for row in typed_reactions._rows(engine, actor.entity_id, BLOCK)}


def _paid_by(action: Any) -> str:
    return str(((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("modifier")) or {}).get("id") or "")


def _single_target(ctx: Any) -> Any:
    return ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)


def current_cover(engine: Any, attacker: Any, target: Any) -> int:
    """The ranged cover the engine adds to this target's AC right now (gate2 _attack_defense's own query)."""
    from ..directional_cover import cover_bonus

    base = engine._cover_bonus_actor_to_actor(attacker, target)
    if engine._has_condition(target, "condition:an_eui.break_guard.no_half_cover"):
        base = 0
    return int(cover_bonus(engine, attacker, target, ranged=True, base=base))


@hook("candidate_allowed")
def bounce_needs_an_angle_talent(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from .bouncing_shot import applies
    if applies(action):
        return None  # the native provider requires a real, paid wall route
    if _paid_by(action) != BOUNCING:
        return None
    return bool(_kinds(engine, actor) & {WRONG_DOOR, RICOCHET})


@hook("attack_bonus")
def ignore_cover(ctx: Any, actor: Any) -> int | None:
    paid = _paid_by(ctx.action)
    if paid == BOUNCING:
        from .bouncing_shot import applies
        if applies(ctx.action):
            return None  # native cover reduction must not also add attack bonus
        if not _kinds(ctx.engine, actor) & {WRONG_DOOR, RICOCHET}:
            return None
        why = "the bounced shot comes in from a new angle"
    elif paid == PHASIC:
        why = "the shot passes through what stands between"
    else:
        return None
    target = _single_target(ctx)
    if target is None:
        return None
    cover = current_cover(ctx.engine, actor, target)
    if cover not in _COVER_NAMES:
        return None
    note(ctx.engine, ctx.source, actor,
         f"{ctx.action.display_name}: {why}, so {target.display_name}'s {_COVER_NAMES[cover]} does not count "
         f"(+{cover} to this attack roll, cancelling the +{cover} it adds to Armor Class).", targets=(target,))
    return cover


@hook("unseen_ignored")
def wrong_door_sees_the_angle(ctx: Any, target: Any) -> bool | None:
    if _paid_by(ctx.action) != BOUNCING or WRONG_DOOR not in _kinds(ctx.engine, ctx.actor):
        return None
    from .. import stealth

    if stealth.hidden(target) is not None:
        return None  # a Hidden target's exact location is not known
    note(ctx.engine, ctx.source, ctx.actor,
         f"Through the Wrong Door: {ctx.actor.display_name} knows where {target.display_name} is and bounces the shot to it, "
         "so not seeing it gives no Disadvantage.", targets=(target,))
    return True
