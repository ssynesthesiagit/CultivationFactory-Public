"""Shield-Breaking Eye, using ordinary Study and the shared Needle transport.

The study_creature effect/checkpoint is general: it observes an actually seen
creature after spending the Study Action. Providers must gate their own rows.
Visible shields, Dodge and source-authored visible_defensive_posture facts are
observable; unknown defensive magic is never inferred from an AC number.
"""
from . import effect, hook, note, run_strict
from .needle import ask, checkpoint_id, option_spec
from .passive_rows import row_of

FEATURE = "insight.shield-breaking-eye"
BLOCK = "shield_breaking_eye"
CHOICE = "choice:insights7e.shield_breaking_eye"
LABEL = "Study: Shield-Breaking Eye"


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "kind": BLOCK, "player_outcome":
            "Study a visible creature with a shield or obvious defensive posture to learn which of Strength, Dexterity or Wisdom best resists your Sabers pressure. Costs an Action; no Qi."}]


@hook("compile_actions")
def compile_actions(info):
    if FEATURE not in info["owned_ids"]:
        return []
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shield_breaking_eye",
        display_name=LABEL, owner_id=info["actor_id"], economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="ANY_CREATURE", costs=(),
        parameters={"study_action": 1, "expected_damage": 0, "typed": {
            "source": FEATURE, "effects": [{"type": "study_creature"}],
            "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}})]


def visible_posture(engine, target):
    """General observable posture query; missing facts are inert.

    Source providers may supply visible_defensive_posture(engine, target) or
    mark an evented condition with integer visible_defensive_posture=1. This
    does not make concealed bonuses or private character statistics visible.
    """
    from ..armour import shield_bonus_earning
    from .shield_wielding import GUARDED_CONDITION
    from .flowing_second_pass import GUARD
    return (shield_bonus_earning(engine, target) > 0
        or any(c.condition_id in ("condition:core.dodge", GUARDED_CONDITION, GUARD)
               or c.data.get("visible_defensive_posture") == 1 for c in target.conditions.values())
        or any(value is True for value in run_strict("visible_defensive_posture", engine, target)))


@hook("candidate_allowed")
def study_allowed(engine, actor, candidate, action):
    if not action or (action.parameters.get("typed") or {}).get("source") != FEATURE:
        return None
    from ..target_knowledge import can_see
    return bool(candidate.target_ids) and all(
        (target := engine.state.actors.get(tid)) is not None and target.active
        and can_see(engine, actor, target) and visible_posture(engine, target)
        for tid in candidate.target_ids)


@effect("study_creature", harmful=False)
def study(ctx, eff):
    from ..target_knowledge import can_see
    for target in ctx.targets:
        if target.active and can_see(ctx.engine, ctx.actor, target):
            run_strict("creature_studied", ctx, target)


@hook("choice_options")
def options(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("creature_studied")
def resistance_reading(ctx, target):
    if not row_of(ctx.engine, ctx.actor.entity_id, BLOCK, BLOCK) or not visible_posture(ctx.engine, target):
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SHIELD_BREAKING_EYE", target.entity_id),
        ctx.actor, CHOICE, ["learn"], labels={"learn": "Learn the strongest defense against Sabers pressure"},
        preferred=["learn"], allow_decline=True, target_id=target.entity_id,
        prompt=f"Shield-Breaking Eye: {ctx.actor.display_name} uses {ctx.action.display_name} to Study {target.display_name}. Learn whether Strength, Dexterity or Wisdom best resists your Sabers pressure? The Study costs an Action, with no extra Qi or Reaction.")
    if not chosen:
        return
    names = {"STR": "Strength", "DEX": "Dexterity", "WIS": "Wisdom"}
    strongest = max(int(target.saving_throws.get(key, 0)) for key in names)
    tied = [names[key] for key in names if int(target.saving_throws.get(key, 0)) == strongest]
    words = " and ".join(tied)
    note(ctx.engine, FEATURE, ctx.actor,
        f"Shield-Breaking Eye: {target.display_name}'s {words} "
        + ("are equally most likely" if len(tied) > 1 else "is most likely")
        + " to resist your Sabers pressure. This reading reveals no exact modifier.",
        targets=(target,), strongest_defenses=",".join(tied))
