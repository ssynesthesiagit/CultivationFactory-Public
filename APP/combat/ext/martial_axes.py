"""Axes sphere mechanics that need a hook instead of a plain typed effect (worker martial, 2026-09-28,
"automate every aspect before another playtest"). Lingfeng the Ember Artisan owns almost all of this sphere's
records; Wen Ying and Ning Kai share a handful of the Hewing Strike riders.

Deep Bite ("you may spend 1 CP, 1 Stamina, or expend Martial Focus to make the Bite last for 1 minute") had a
modifier that already charged its cost (extra_cp/martial_focus in reviewed_final.d/martial.json) but typed no
effect at all -- paying a resource for nothing. The cost is already enforced structurally (apply_modifiers adds
it to the chosen variant's own costs before this ever runs); this file only needs to deliver the extension: it
finds the Bite mark this hit just placed on the target and re-applies it for 10 rounds (the round clock of
combat/ext/effect_durations.py, "1 minute" in combat/rules/typed_conditions.json's "duration_rounds"; it was
UNTIL_REMOVED while nothing counted rounds; Bite still has its own release valve, the target's own
Athletics/Acrobatics check against the wielder's Cultivation Save DC, via TAL_AXES_DEEP_BITE's own printed
text). A Drive/Hook/Hamper/Split Guard variant chosen alongside Deep Bite never placed Bite in the first place,
so the guard below simply finds nothing to extend -- a wasted resource on a misplay, not a broken mechanic.

Headsman's Calm ("When you reduce a hostile creature to 0 HP with an axe attack ... you may regain Martial
Focus if it is absent. Once per short or long rest ... choose one hostile creature ... Disadvantage on its
next attack roll") never compiled at all (TAL_AXES_HEADSMAN_S_CALM has no modifier and modifies no named
ability -- it is its own free trigger off any axe kill) and sat in diagnostics.skipped["passive"]. Modelled
as an automatic policy, matched to the Ironroot Demon Bone Regeneration pattern (ironroot_daemonic.py): a
rational fighter always wants the free Martial Focus back, so it fires on every qualifying kill; "once per
short or long rest" has no rest-tracking within a single fight, so the fear effect fires once per fight
(the more conservative reading -- a real rest would refresh it, a fight rarely contains one)."""

from __future__ import annotations

from typing import Any

from . import effect, hook

AXE_WORDS = ("axe", "hatchet", "francisca", "tomahawk")


def _is_axe_hit(ctx: Any) -> bool:
    if ctx.typed.get("sphere") == "tianxia.sphere.axes":
        return True
    return any(word in ctx.action.display_name.lower() for word in AXE_WORDS)


@effect("axes_deep_bite_extend")
def deep_bite_extend(ctx: Any, effect_row: dict[str, Any]) -> None:
    from ..typed_executor import clock_expiry, mark_condition_id

    target = ctx.target
    if target is None:
        return
    condition_id = mark_condition_id("Bite", ctx.actor.entity_id)
    if not any(condition.condition_id == condition_id for condition in target.conditions.values()):
        return  # this hit did not place Bite (Drive/Hook/Hamper/Split Guard chosen instead of Bite/Lodging Cast)
    ctx.engine._remove_condition(target, condition_id, ctx.source)
    ctx.engine._apply_condition(target, condition_id, ctx.source, ctx.actor.entity_id,
                                expires_on=clock_expiry(ctx.engine, "minutes") or "UNTIL_REMOVED")
    if effect_row.get("escape_policy") == 1:
        from .escape_options import escape_option
        escape_option(ctx, {"guards": [condition_id], "kind": "check", "abilities": ["STR", "DEX"],
                            "skills": {"STR": "Athletics", "DEX": "Acrobatics"},
                            "help": True, "help_mode": "advantage", "skill_proficiency": True,
                            "name": "Deep Bite"})
    if effect_row.get("escape_policy") != 1:
        ctx.rider("Deep Bite: this Bite lasts up to 1 minute (10 rounds) instead of just until your next turn (the target can "
                  "still end it early with its own Athletics/Acrobatics check).")
        return
    from . import note
    note(ctx.engine, ctx.source, ctx.actor, "Deep Bite: this Bite lasts up to 1 minute (10 rounds). Use Break free (an Action) to make a "
              "Strength (Athletics) or Dexterity (Acrobatics) check against the axe user's Cultivation Save DC. "
              "Success ends this Bite. An adjacent ally can use Help to give the check Advantage.", targets=[target])



HEADSMANS_CALM_BLOCK = "axes_headsmans_calm"


@hook("compile_block")
def compile_headsmans_calm(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block != HEADSMANS_CALM_BLOCK:
        return None
    return [row]


def _passive_rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == block]


@hook("after_hit")
def headsmans_calm(ctx: Any, target: Any, kind: str) -> None:
    if not _passive_rows(ctx.engine, ctx.actor, HEADSMANS_CALM_BLOCK) or not _is_axe_hit(ctx):
        return
    if target.active and target.current_hp > 0:
        return  # did not reduce the creature to 0 HP
    from ..factory_compiler import RESOURCE_IDS

    focus = RESOURCE_IDS["martial_focus"]
    if focus in ctx.actor.resources and ctx.actor.resources.get(focus, 0) < 1:
        ctx.engine._gain_resource(ctx.actor, focus, 1, "TAL_AXES_HEADSMAN_S_CALM")
        ctx.rider("Headsman's Calm: regained Martial Focus.")
    flag = "headsmans_calm_fear_used"
    if ctx.actor.turn_flags.get(flag):
        return
    hostiles = [a for a in ctx.engine.state.actors.values() if a.active and a.entity_id != ctx.actor.entity_id
               and a.team_id != ctx.actor.team_id and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30]
    if not hostiles:
        return
    ctx.actor.turn_flags[flag] = True
    chosen = min(hostiles, key=lambda a: (ctx.engine._distance_actor_to_actor(ctx.actor, a), a.entity_id))
    from ..typed_executor import Context, run_effects

    inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, ctx.damage_cache)
    run_effects(inner, [{"type": "disadvantage", "applies_to": "target", "on": "next attack roll it makes against you",
                         "expires_on": "END_OF_HOLDER_NEXT_TURN"}])
    ctx.rider(f"Headsman's Calm: once this fight, {chosen.entity_id} has Disadvantage on its next attack roll against you "
              "(once per short/long rest in the printed text; this table has no in-fight rest to key off, so it is once per fight).")


# ------------------------------------------------------------------------------------------------ Cast Axe: Turning Cast (rider lane C13)
@effect("axes_turning_cast")
def turning_cast(ctx: Any, eff: dict[str, Any]) -> None:
    """Cast Axe, Turning Cast: "If the target is no more than one size larger than you, it must choose either to be pushed 5 feet or to have
    its Speed reduced by 5 feet until the start of your next turn." The size gate is the typed row around this effect; the choice is the
    target's own (its player is asked; the built-in AI takes the push, the first printed choice)."""
    from ..typed_executor import run_effects
    from .rider_choices import pick

    target = ctx.target
    if target is None or not target.active:
        return
    labels = {"push": f"{target.display_name} is pushed 5 feet away from {ctx.actor.display_name}",
              "slow": f"{target.display_name}'s Speed is 5 feet lower until the start of {ctx.actor.display_name}'s next turn"}
    chosen = pick(ctx.engine, target, "axes_turning_cast", "Turning Cast", ["push", "slow"], subject=target, labels=labels,
                  preferred=["push"], optional=False, trigger=f"{ctx.actor.display_name}'s Cast Axe hits")
    if (chosen or ["push"])[0] == "slow":
        run_effects(ctx, [{"type": "speed", "applies_to": "target", "flat": -5, "duration": "until_start_of_next_turn",
                           "evidence": "have its Speed reduced by 5 feet until the start of your next turn"}])
    else:
        run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "direction": "away", "distance_ft": 5,
                           "evidence": "be pushed 5 feet"}])
