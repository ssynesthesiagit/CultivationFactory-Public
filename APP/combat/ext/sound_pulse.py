"""Dissonant Pulse after actual Sound damage, using existing transactional hooks.

New compilations seal a sound_pulse passive instead of prepaid Note variants.
Historical catalogs lack that passive and keep their original execution route.
Attack damage waits for after_hit_choice so the Note's ordinary Resonance cannot
overwrite the chosen longer mark. Other typed damage (including zone damage)
offers immediately. Payment and the failed-save choice share transaction rollback.
"""
from dataclasses import replace

from . import effect, hook, note
from .choice_costs import Payment
from .cp_pools import of
from .needle import answerable, ask, checkpoint_id
from ..typed_executor import mark_condition_id, run_effects, strike_record

FEATURE = "TAL_SOUND_DISSONANT_PULSE"
BLOCK = "sound_pulse"
USED = "condition:typed.sound_pulse_used"
SOUND = "tianxia.sphere.sound"


@hook("compile_block")
def compile_pulse(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "choice_owner": True}]
    return None


@hook("compile_passives")
def pulse_numbers(rows, info):
    """Seal the owner's save DC, independent of the damaging action's DC."""
    return [{**row, "save_dc": int(info["numbers"]["save_dc"])}
            if row.get("block") == BLOCK and row.get("feature_id") == FEATURE else row
            for row in rows]


def owned(engine, actor):
    return any(row.get("block") == BLOCK and row.get("feature_id") == FEATURE
               for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, []))


def offer(ctx, target):
    if not owned(ctx.engine, ctx.actor) or not target.active:
        return
    # The printed trigger needs no sight, but an automatic chooser must not
    # spend against an unperceived creature found only by area resolution.
    if not answerable(ctx.engine, ctx.actor):
        from ..senses import perceives
        from ..relations import ENEMY, relation
        if relation(ctx.engine, ctx.actor, target) != ENEMY or not perceives(ctx.engine, ctx.actor, target):
            return
    if any(c.condition_id == USED for c in ctx.actor.conditions.values()):
        return
    pool = of(ctx.actor)
    if pool is None or int(ctx.actor.resources.get(pool, 0)) < 1:
        return
    payment = Payment(pool, 1)
    chosen = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, "sound_pulse_pay", ctx.source, target.entity_id),
                 ctx.actor, "choice:needle.sound_pulse_pay", ["pulse"],
                 labels={"pulse": f"Spend {payment.quote()} from your cultivation pool to force a Constitution save"},
                 name="Dissonant Pulse", feature_id=FEATURE, target_id=target.entity_id,
                 allow_decline=True, payment=payment,
                 prompt=f"Dissonant Pulse: {ctx.actor.display_name}'s {ctx.action.display_name} damaged "
                        f"{target.display_name}. Spend {payment.quote()} to force a Constitution saving throw; "
                        "on a failure, choose a penalty. On a success, apply Resonance until your next turn starts. "
                        "Resonance marks the creature for extra effects from your Sound talents. Once per turn.")
    if not chosen:
        return
    payment.pay(ctx.engine, ctx.actor, ctx.source)
    ctx.engine._apply_condition(ctx.actor, USED, ctx.source, ctx.actor.entity_id,
                                expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Dissonant Pulse used this turn"})
    row = next(row for row in ctx.engine.typed_passive_rows[ctx.actor.entity_id]
               if row.get("block") == BLOCK and row.get("feature_id") == FEATURE)
    typed = {**ctx.typed, "numbers": {**ctx.numbers, "save_dc": row["save_dc"]}}
    sub = replace(ctx, typed=typed, target=target, targets=[target], damage_cache={}).with_source(FEATURE)
    run_effects(sub, [{"type": "save", "applies_to": "target", "ability": "con",
                      "on_fail": [{"type": "sound_pulse_failure"}],
                      "on_success": [{"type": "mark", "applies_to": "target", "mark": "Resonance",
                                      "duration": {"kind": "until_start_of_your_next_turn"}}]}])
    note(ctx.engine, FEATURE, ctx.actor,
         f"Dissonant Pulse: {ctx.actor.display_name} spends {payment.quote()} after "
         f"{ctx.action.display_name} damages {target.display_name}.", (target,))


@hook("damage_dealt")
def sound_damage(ctx, target, amount):
    # Standing zones use a child Context without a sphere field. Their action is
    # the actual sealed zone-creating action, never inferred from recent events.
    sphere = ctx.typed.get("sphere") or (ctx.action.parameters.get("typed") or {}).get("sphere")
    # Only the contributing packet qualifies: a paid Sound rider does not
    # reclassify its enclosing weapon hit (or ordinary Thunder damage).
    from .sound_strikes import FEATURES
    sound_rider = ctx.effect_source in {f"passive:{feature}" for feature in FEATURES}
    if amount <= 0 or (sphere != SOUND and not sound_rider) or not owned(ctx.engine, ctx.actor):
        return
    if sound_rider:
        # Attached on-hit effects run after after_hit_choice. Their own damage
        # is the trigger; waiting for that earlier hook would lose the offer.
        offer(ctx, target)
        return
    record = strike_record(ctx)
    if record is not None:
        record.setdefault("sound_pulse_damage", {})[target.entity_id] = True
        return
    offer(ctx, target)


@hook("after_hit_choice")
def after_sound_hit(ctx, target, kind):
    record = strike_record(ctx)
    if record and record.get("sound_pulse_damage", {}).pop(target.entity_id, False):
        offer(ctx, target)


@hook("effect_subject_allowed")
def retain_longer_resonance(ctx, eff, subject):
    """A later ordinary Note must not shorten the chosen next-turn-end grant."""
    if eff.get("type") != "mark" or eff.get("mark") != "Resonance" or not owned(ctx.engine, ctx.actor):
        return None
    duration = eff.get("duration")
    if not isinstance(duration, dict) or duration.get("kind") != "until_start_of_your_next_turn":
        return None
    cid = mark_condition_id("Resonance", ctx.actor.entity_id)
    if any(c.condition_id == cid and c.source_definition_id == FEATURE
           and c.expires_on == "END_OF_MARKER_NEXT_TURN" for c in subject.conditions.values()):
        return False
    return None


@effect("sound_pulse_failure")
def failed_pulse(ctx, eff):
    if not owned(ctx.engine, ctx.actor) or ctx.target is None:
        return
    target = ctx.target
    options = {
        "concentration": {"type": "disadvantage", "on": "next Concentration saving throw",
                          "duration": "until_start_of_next_turn"},
        "reactions": {"type": "reaction_denied", "duration": "until_start_of_next_turn"},
        "speed": {"type": "speed", "flat": -10, "duration": "until_start_of_next_turn"},
        "resonance": {"type": "mark", "mark": "Resonance",
                      "duration": {"kind": "until_end_of_your_next_turn"}},
    }
    labels = {
        "concentration": "Disadvantage on its next Concentration save before your next turn starts",
        "reactions": "Cannot take Reactions until your next turn starts",
        "speed": "Speed reduced by 10 feet until your next turn starts",
        "resonance": "Resonance until your next turn ends: your Sound talents can gain extra effects",
    }
    chosen = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, "sound_pulse_failure", ctx.source, target.entity_id),
                 ctx.actor, "choice:needle.sound_pulse_failure", list(options), labels=labels,
                 preferred=["reactions"], name="Dissonant Pulse", feature_id=FEATURE,
                 target_id=target.entity_id,
                 prompt_context={"cost": "No additional cost; the 1 cultivation point for Dissonant Pulse is already paid"},
                 prompt=f"Dissonant Pulse after {ctx.action.display_name}: {target.display_name} failed its "
                        "Constitution saving throw. Choose its penalty; you have already paid 1 cultivation point.")
    if chosen:
        run_effects(ctx, [{**options[chosen[0]], "applies_to": "target"}])
