"""Resonance Breaker: one benefit from a qualifying successful Music Check.

Uses music_insights' single owned row and existing resource, condition and choice
contracts. effect_check_resolved is a general end_effect notification; explicit
opposed-check metadata also reaches the same public settlement helper. Neither
source names nor a hidden enemy's statistics imply a Music check or a disruption.
Manual choices retain every qualifying ally; AI uses only located creatures.
"""
from . import hook, note, run_checkpoint
from .music_insights import owned
from .needle import ask, checkpoint_id, option_spec, ai_controlled
from .cp_pools import of

FEATURE = "insight.resonance-breaker"
CHOICE = "choice:insights7e.resonance_breaker"
USED = "_round_ins7e_resonance_breaker_scene"
FOCUS = "resource:core.martial_focus"
SPHERES = {"tianxia.sphere." + s for s in ("sound", "music", "war", "formations", "formation", "spirit", "spirit_awakening", "spirit_companions")}
PURPOSES = {"suppress", "disrupt", "identify"}


def eligible_source(source):
    """Recorded Sphere or Spirit Awakening Path provenance, never a name guess."""
    return (source in SPHERES or str(source or "").startswith("tianxia.path.spirit_awakening."))


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


def settle(ctx, affected, check, success, *, effect_sphere, disrupted):
    """One committed check, explicit subject/source facts, and one owned choice."""
    engine, owner = ctx.engine, ctx.actor
    row = owned(engine, owner, FEATURE)
    if (not row or not success or owner.turn_flags.get(USED)
            or check.get("name") != "Music Check" or not eligible_source(effect_sphere)
            or check.get("purpose") not in PURPOSES):
        return
    pb = int(row["numbers"]["pb"])
    cp = of(owner)
    labels = {}
    if cp:
        labels["cp"] = "Regain 1 Cultivation Point, up to your maximum"
    if FOCUS in owner.resources:
        labels["focus"] = "Regain Martial Focus, up to its maximum"
    from ..target_knowledge import located
    from ..relations import ALLY, relation
    allies = [a for a in engine.state.actors.values() if a.active
              and relation(engine, owner, a) == ALLY and engine._distance_actor_to_actor(owner, a) <= 30]
    allies.sort(key=lambda a: a.entity_id)
    for a in allies:
        labels["ally:" + a.entity_id] = f"{a.display_name}: gain {pb} Temporary Hit Points"
    if check.get("purpose") in {"suppress", "disrupt"} and disrupted is not None and disrupted.active:
        labels["concentration"] = f"{disrupted.display_name}: Disadvantage on its next Concentration save before your next turn starts"
    if not labels:
        return
    automatic = [key for key in labels if not key.startswith("ally:") or located(engine, owner, engine.state.actors[key[5:]])]
    if "concentration" in automatic and not located(engine, owner, disrupted):
        automatic.remove("concentration")
    # Rank from the owner's own resource state, never hidden enemy HP or plans.
    preferred = (["cp"] if cp and owner.resources.get(cp, 0) < owner.resource_maximums.get(cp, 0) else [])
    if not preferred and FOCUS in owner.resources and owner.resources[FOCUS] == 0:
        preferred = ["focus"]
    if not preferred:
        preferred = [k for k in automatic if k.startswith("ally:")][:1] or automatic[:1]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "RESONANCE_BREAKER", affected.entity_id),
        owner, CHOICE, list(labels), labels=labels, preferred=preferred, automatic_options=automatic,
        allow_decline=True, name="Resonance Breaker", feature_id=FEATURE, target_id=affected.entity_id,
        prompt=f"Resonance Breaker: {ctx.action.display_name} succeeded on a Music Check affecting {affected.display_name}. Choose one benefit: regain 1 Cultivation Point, regain Martial Focus, give one ally within 30 feet Temporary Hit Points equal to your Proficiency Bonus, or hamper the disrupted creature's next Concentration save before your next turn starts. Once per scene; no extra action or resource cost.")
    if not picked:
        return
    owner.turn_flags[USED] = 1
    key = picked[0]
    if key == "cp":
        engine._gain_resource(owner, cp, 1, FEATURE)
    elif key == "focus":
        engine._gain_resource(owner, FOCUS, 1, FEATURE)
    elif key.startswith("ally:"):
        engine._grant_temp_hp(engine.state.actors[key[5:]], pb, FEATURE, owner.entity_id)
    elif key == "concentration":
        engine._apply_condition(disrupted, "condition:typed.concentration_mode", FEATURE, owner.entity_id,
            expires_on="START_OF_SOURCE_NEXT_TURN", data={
                "rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                "label": "Disadvantage on the next Concentration save before the musician's next turn starts"})
    note(engine, FEATURE, owner, f"Resonance Breaker: {labels[key]}; the once-per-scene benefit is spent.", targets=(affected,), benefit=key)


@hook("effect_check_resolved")
def effect_check(ctx, holder, item, check, success):
    source = ctx.engine.action_catalog.get(item.source_definition_id)
    typed = (source.parameters or {}).get("typed") or {} if source else {}
    provenance = typed.get("sphere") or typed.get("source")
    settle(ctx, holder, check, success, effect_sphere=provenance,
           disrupted=ctx.engine.state.actors.get(item.source_actor_id))


@hook("opposed_check_resolved")
def opposed(ctx, target, result, actor_check, target_check):
    # Identification and other Music Checks name their actual effect's Sphere
    # and operation in their check spec. Missing provenance grants no rider.
    run_checkpoint("resonance_breaker_check", ctx, target, actor_check, result.success)


@hook("resonance_breaker_check")
def identified(ctx, target, check, success):
    settle(ctx, target, check, success, effect_sphere=check.get("effect_sphere"),
           disrupted=ctx.engine.state.actors.get(check.get("disrupted_actor_id")))
