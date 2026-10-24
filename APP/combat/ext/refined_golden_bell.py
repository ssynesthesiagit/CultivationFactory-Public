"""Refined Golden Bell's four mutually exclusive, activation-bound choices.

Uses the existing technique_used, choice, save/check-hazard and flat damage
reduction contracts. The linked stance instance owns expiry and replacement.
Round-use receipts are committed events, so changing turns or cold reloading
cannot refresh the first-packet reduction. Pure defense quotes never spend it.
"""
from . import hook, note
from .needle import ask, checkpoint_id, option_spec
from .passive_rows import row_of

FEATURE = "insight.refined-golden-bell"
BLOCK = "refined_golden_bell"
CHOICE = "choice:insights7.refined_golden_bell"
CONDITION = "condition:typed.refined_golden_bell"
STANCE = "condition:typed.stance.golden_bell_circulation"
LABELS = {
    "temporary_hp": "Gain temporary hit points equal to twice your Proficiency Bonus",
    "anchoring": "Advantage on checks and saves against forced movement and being knocked Prone",
    "force_resistance": "Resistance to Force damage",
    "first_packet": "Reduce your first damage packet each round by your Proficiency Bonus",
}
HAZARDS = {"forced_movement", "prone", "push", "pull"}


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "kind": BLOCK, "pb": int(numbers.get("pb") or 2),
                 "player_outcome": "Choose one Golden Bell refinement each activation; it ends with that activation."}]
    return None


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


def active(engine, actor):
    """Read an owned refinement only while its exact granting stance is active."""
    if not row_of(engine, actor.entity_id, BLOCK, BLOCK):
        return None
    parents = {c.instance_id for c in actor.conditions.values() if c.condition_id == STANCE}
    return next((c for c in actor.conditions.values() if c.condition_id == CONDITION
                 and c.data.get("stance_instance") in parents), None)


@hook("technique_used")
def refine(ctx):
    row = row_of(ctx.engine, ctx.actor.entity_id, BLOCK, BLOCK)
    if row is None:
        return
    # Only a stance actually applied by this activation qualifies. An unrelated
    # technique used while Golden Bell runs must not select or refresh anything.
    events = ctx.engine.events[getattr(ctx, "technique_event_start", len(ctx.engine.events)):]
    applied = {e.payload.get("instance_id") for e in events if e.event_type == "CONDITION_APPLIED"
               and ctx.actor.entity_id in e.target_ids and e.payload.get("condition_id") == STANCE}
    stance = next((c for c in ctx.actor.conditions.values() if c.instance_id in applied
                   and c.condition_id == STANCE), None)
    if stance is None:
        return
    pb = int(row["pb"])
    # Uses only the creature's own known temporary HP, never enemy statistics.
    preferred = "temporary_hp" if ctx.actor.temporary_hp < 2 * pb else "first_packet"
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "REFINED_GOLDEN_BELL", stance.instance_id),
        ctx.actor, CHOICE, list(LABELS), labels=LABELS, preferred=[preferred], allow_decline=False,
        prompt=f"Refined Golden Bell: {ctx.actor.display_name} activates {ctx.action.display_name}. "
               "Choose one refinement for yourself; it replaces your previous refinement and ends when this "
               "Golden Bell activation ends. No extra action or Stamina cost.")
    if not chosen:
        return
    ctx.engine._remove_condition(ctx.actor, CONDITION, FEATURE)
    ctx.engine._apply_condition(ctx.actor, CONDITION, FEATURE, ctx.actor.entity_id,
        expires_on=stance.expires_on, data={"choice": chosen[0], "pb": pb,
            "stance_instance": stance.instance_id, "label": f"Refined Golden Bell: {LABELS[chosen[0]]}"})
    if chosen[0] == "temporary_hp":
        ctx.engine._grant_temp_hp(ctx.actor, 2 * pb, FEATURE, ctx.actor.entity_id)
    note(ctx.engine, FEATURE, ctx.actor, f"Refined Golden Bell: {LABELS[chosen[0]]}; "
         "this refinement ends with the current Golden Bell activation.", choice=chosen[0])


@hook("event", nested=True)
def end_with_stance(engine, event_type, kwargs):
    payload = kwargs.get("payload") or {}
    if event_type != "CONDITION_REMOVED" or payload.get("condition_id") not in {STANCE, CONDITION}:
        return
    for aid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(aid)
        if actor is not None and row_of(engine, aid, BLOCK, BLOCK):
            if payload.get("condition_id") == CONDITION:
                # A detached removal snapshot is the general ending contract.
                # Clear only this activation's remaining HP pool; an unrelated
                # larger pool, or an already depleted pool, must remain intact.
                from .temp_hp_grants import held_grant
                ended = kwargs.get("ended_effect") or {}
                held = held_grant(engine.events, aid)
                if (ended.get("data", {}).get("choice") == "temporary_hp" and held
                        and held[0] == FEATURE and held[2] >= int(ended.get("applied_sequence") or 0)
                        and actor.temporary_hp > 0):
                    before = actor.temporary_hp
                    actor.temporary_hp = 0
                    engine._append_event("TEMP_HP_GRANTED", FEATURE, actor_id=aid, target_ids=(aid,),
                        payload={"before": before, "after": 0, "offered": 0, "reason": "Golden Bell activation ended"})
                continue
            for c in list(actor.conditions.values()):
                if c.condition_id == CONDITION and c.data.get("stance_instance") == payload.get("instance_id"):
                    engine._remove_condition(actor, CONDITION, FEATURE)


@hook("damage_defenses")
def force_resistance(engine, target, damage_type, typed, source_actor_id):
    c = active(engine, target)
    if c is not None and c.data["choice"] == "force_resistance":
        return [{"kind": "resistance", "damage_types": ["FORCE"], "feature_id": FEATURE}]
    return None


@hook("save")
def anchoring_save(ctx, subject, ability, named):
    c = active(ctx.engine, subject)
    if c is not None and c.data["choice"] == "anchoring" and HAZARDS.intersection(str(x).lower() for x in named or ()):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("ability_check_hazards")
def anchoring_check(engine, actor, ability, skill, hazards):
    c = active(engine, actor)
    if c is not None and c.data["choice"] == "anchoring" and HAZARDS.intersection(str(x).lower() for x in hazards or ()):
        return "ADVANTAGE"
    return None


@hook("damage_reduction")
def first_packet(engine, target, damage_type, typed, source_actor_id, applied=False):
    c = active(engine, target)
    if c is None or c.data["choice"] != "first_packet":
        return 0
    used = any(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == FEATURE
               and e.actor_id == target.entity_id and e.payload.get("reduction_round") == engine.state.round_number
               for e in reversed(engine.events))
    if used:
        return 0
    pb = int(c.data["pb"])
    if applied:
        note(engine, FEATURE, target, f"Refined Golden Bell reduces {target.display_name}'s first damage packet "
             f"this round by {pb}, after Resistance and Vulnerability and before other flat reductions.",
             reduction_round=int(engine.state.round_number), reduction=pb)
    return pb
