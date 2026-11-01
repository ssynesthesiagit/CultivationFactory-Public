"""Reactions that re-aim an attack before it is rolled, on the lock round's ``retarget_attack`` hook (automation lane H2, 2026-09-29;
through the shared owner combat/ext/redirection.py).

Misdirected Attack (Scoundrel, Escape; rules_text.json TAL_SCOUNDREL_MISDIRECTED_ATTACK)
  Reaction; trigger is an Opportunity Attack provoked by your movement. Contest Dirty Trick against the attacker before that attack
  resolves. Success: no ordinary Dirty Trick result; instead the triggering attack is turned on one other legal creature in the
  attacker's reach, rolled once with the original attack roll against the new target's AC, and you take nothing from it. Failure:
  the Opportunity Attack resolves against you as usual.
  How it runs: when a Factory fighter's Opportunity Attack (typed_reactions.opportunity_attack) is declared against the owner and
  another creature is a legal target of that very attack (in the attacker's reach and sight, the engine's own test), the owner is
  asked which creature to turn it on (or to decline); the built-in AI takes it when one of the attacker's own side is there, the
  lowest Armor Class first. The Reaction is spent and the Dirty Trick is the contest the talent's typed reaction already uses (the
  owner's d20 + attack bonus against the attacker's d20 + that attack's bonus). A success re-aims the attack, which is then rolled
  once against the new target (the "original attack roll": it has not been rolled yet); a failure leaves it on the owner.
  If no other legal target exists, the compiled reaction still negates the attack on a success, as before (nowhere else for it to
  go); with one, that reaction stays silent (declining the redirect declines the Reaction).
Judgment calls: only an Opportunity Attack by a Factory fighter is recognised (a fixture monster's opportunity attack has no marker);
the table lists every legal creature, the AI only turns it on the attacker's side.

Harmonious Body (Jujutsu CL14; tianxia.subpath.body.jujutsu.feature.harmonious_body): the whole Reaction at the melee attack's
declaration -- the attacker's Strength save, then the failure option chosen with the Reaction (redirect to another legal creature in
its reach, move it 10 feet away, or knock it Prone: the last two make the attack miss without a roll when they apply), or on a
success the 2d8 + Constitution reduction parked for that attack's hit. See harmonious_body below.

Redirecting Shield / Perfect Redirection (Shield): after the attack roll, not before -- a missed attack that the Shield fighter's
Active Defense answered is sent, for Martial Focus, at a new legal target in the attacker's reach or range with the same roll (the
after_miss hook, the way flowing_river.py plays Bend the Blade). See redirecting_shield below.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id
from .redirection import legal_target, owns, provider

MISDIRECTED = "TAL_SCOUNDREL_MISDIRECTED_ATTACK"


def _generic_row(engine: Any, actor: Any, feature_id: str) -> dict[str, Any] | None:
    from .. import typed_reactions

    return next((row for row in typed_reactions._rows(engine, actor.entity_id, "generic") if row.get("feature_id") == feature_id), None)


def _attack_bonus(engine: Any, context: dict[str, Any]) -> int:
    action = engine.action_catalog.get(context.get("source_id") or "")
    return int(((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("attack_bonus") or 0) if action is not None else 0)


def _others(engine: Any, attacker: Any, defender: Any, range_ft: int | None) -> list[Any]:
    """Every other creature the declared attack could legally be made against, the attacker's side (lowest AC) first."""
    rows = [row for row in engine.state.actors.values() if row.entity_id not in (attacker.entity_id, defender.entity_id)
            and legal_target(engine, attacker, row, range_ft)]
    return sorted(rows, key=lambda row: (row.team_id != attacker.team_id, row.armor_class + engine._ac_modifier(row), row.current_hp, row.entity_id))


@provider(30)
def misdirected_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    from .. import typed_reactions
    from ..typed_executor import _contest

    if getattr(engine, "_typed_oa_attacker", None) != attacker.entity_id or attacker.team_id == defender.team_id:
        return None  # not an Opportunity Attack made for the defender's movement
    row = _generic_row(engine, defender, MISDIRECTED) if owns(engine, defender, "misdirected_attack") else None
    if row is None or not typed_reactions._can_react(engine, defender) or not typed_reactions._generic_affordable(engine, defender, row):
        return None
    others = _others(engine, attacker, defender, context.get("range_ft"))
    if not others:
        return None  # nowhere to send it: the compiled reaction may still negate it
    labels = {row_.entity_id: f"Misdirected Attack: turn it on {row_.display_name}" for row_ in others}
    picked = ask(engine, intent, checkpoint_id(engine, "MISDIRECTED", defender.entity_id, attacker.entity_id), defender,
                 CHOICE + "misdirected_attack", list(labels), labels=labels, preferred=[others[0].entity_id],
                 prompt=f"Dirty Trick {attacker.display_name} to turn its Opportunity Attack on another creature?", allow_decline=True,
                 automatic=others[0].team_id == attacker.team_id, target_id=defender.entity_id, default="decline")
    chosen = next((row_ for row_ in others if picked and row_.entity_id == picked[0]), None)
    if chosen is None:
        return None
    with activation(engine, defender, row["feature_id"]):
        typed_reactions._open(engine, row, defender, (attacker.entity_id,), "ATTACK_DECLARED")
        typed_reactions._spend_generic(engine, defender, row)
        defender.reaction_available = False
        ctx = typed_reactions._generic_context(engine, defender, attacker, {**row, "effects": []}, intent)
        theirs = engine.roller.d20(modifier=_attack_bonus(engine, context), actor_id=attacker.entity_id, reason="REACTION_CONTEST")
        engine._record_roll(theirs)
        success = _contest(ctx, theirs.total, "REACTION_CONTEST",
                           f"Dirty Trick for Misdirected Attack to turn {attacker.display_name}'s Opportunity Attack "
                           f"away from {defender.display_name} onto {chosen.display_name}")
        engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=defender.entity_id, target_ids=(attacker.entity_id, chosen.entity_id),
                             payload={"reaction": "misdirected_attack", "success": success, "against": theirs.total})
        if not success:
            ctx.rider(f"Misdirected Attack: the Dirty Trick fails; the Opportunity Attack resolves against {defender.display_name}.")
            return None
        ctx.rider(f"Misdirected Attack: {attacker.display_name}'s Opportunity Attack is turned on {chosen.display_name}.")
        return {"source_id": f"ability:{MISDIRECTED}", "target_id": chosen.entity_id, "cover_bonus": 0}


@hook("reaction_subject_allowed")
def _misdirected_negates_only_without_a_target(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """The compiled reaction (a success negates the attack) answers only when no other legal target is there: with one, a success
    must redirect ("Redirect the triggering attack against one other legal target"), which the provider above has already offered."""
    if row.get("feature_id") != MISDIRECTED or not owns(engine, reactor, "misdirected_attack"):
        return None
    pending = getattr(engine, "_typed_pending_attack", None) or {}
    if pending.get("attacker") != other.entity_id or pending.get("target") != reactor.entity_id:
        return None
    return False if _others(engine, other, reactor, int(pending.get("reach") or 5)) else None


# ------------------------------------------------------------------------------------------------ Harmonious Body (Jujutsu CL14)
HARMONIOUS = "tianxia.subpath.body.jujutsu.feature.harmonious_body"
PARKED = "harmonious_body_parked:"  # + attacker id: the success branch's damage reduction, parked for that attack's hit


def _harmonious_options(engine: Any, attacker: Any, defender: Any, range_ft: int | None) -> dict[str, str]:
    labels = {f"redirect:{row.entity_id}": f"Harmonious Body: if it fails, the attack goes to {row.display_name}"
              for row in _others(engine, attacker, defender, range_ft)}
    labels["prone"] = "Harmonious Body: if it fails, knock it Prone (the attack misses)"
    labels["move"] = "Harmonious Body: if it fails, move it 10 feet away (the attack misses if you leave its reach)"
    return labels


@provider(40)
def harmonious_body(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Harmonious Body (Reaction, 3 Stamina, once per round, Strength save made before the attack roll). Fail: pick one -- redirect
    the attack at another legal creature in the attacker's reach with the same attack roll; move the attacker up to 10 feet (out of
    reach and the attack misses); or knock it Prone (the attack misses). Success: the attack resolves as usual and its damage drops
    by 2d8 + Constitution modifier.
    The failure option is chosen when the Reaction is taken (it matters only on a failure), so the table asks once; the built-in AI
    redirects onto the attacker's own side when it can, otherwise knocks it Prone. A typed melee attack only (typed_executor reads
    the miss); the talent's compiled reaction (save and the success reduction only) is kept silent below."""
    from .. import typed_reactions
    from ..typed_executor import run_effects

    effect_row = context.get("effect") if isinstance(context.get("effect"), dict) else None
    action = engine.action_catalog.get(context.get("source_id") or "")
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    if (effect_row is None or typed.get("range_ft") or str(effect_row.get("attack_kind") or "").startswith("ranged")
            or attacker.team_id == defender.team_id or not owns(engine, defender, "harmonious_body")):
        return None
    row = _generic_row(engine, defender, HARMONIOUS)
    reach = int(typed_reactions.opportunity_reach(engine, defender) or 5)
    if (row is None or not typed_reactions._can_react(engine, defender) or not typed_reactions._generic_affordable(engine, defender, row)
            or typed_reactions._once_used(engine, defender, row) or engine._distance_actor_to_actor(defender, attacker) > reach):
        return None
    range_ft = context.get("range_ft")
    labels = _harmonious_options(engine, attacker, defender, range_ft)
    ally_side = next((key for key in labels if key.startswith("redirect:")
                      and engine.state.actors[key.split(":", 1)[1]].team_id == attacker.team_id), None)
    picked = ask(engine, intent, checkpoint_id(engine, "HARMONIOUS", defender.entity_id, attacker.entity_id), defender,
                 CHOICE + "harmonious_body", list(labels), labels=labels, preferred=[ally_side or "prone"],
                 prompt=f"Harmonious Body (3 Stamina, your Reaction) against {attacker.display_name}'s attack?", allow_decline=True,
                 target_id=defender.entity_id, default="decline")
    choice = picked[0] if picked and picked[0] in labels else None
    if choice is None:
        return None
    with activation(engine, defender, row["feature_id"]):
        typed_reactions._open(engine, row, defender, (attacker.entity_id,), "ATTACK_DECLARED")
        typed_reactions._spend_generic(engine, defender, row)
        defender.reaction_available = False
        on_fail = ([{"type": "condition", "condition": "prone", "applies_to": "target",
                     "evidence": "Knock the attacker Prone. The triggering attack misses."}] if choice == "prone" else
                   [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
                     "evidence": "Move the attacker up to 10 feet."}] if choice == "move" else [])
        engine._harmonious_result = None
        ctx = typed_reactions._generic_context(engine, defender, attacker, {**row, "effects": []}, intent)
        run_effects(ctx, [{"type": "save", "ability": "str", "applies_to": "target", "evidence": "The target makes the saving throw before resolving its attack roll",
                           "on_fail": [*on_fail, {"type": "harmonious_body_result", "result": "fail"}],
                           "on_success": [{"type": "harmonious_body_result", "result": "success"}]}])
        result, engine._harmonious_result = engine._harmonious_result, None
        if result == "success":
            reduction = next((branch for eff in row.get("effects") or [] if isinstance(eff, dict)
                              for branch in eff.get("on_success") or [] if isinstance(branch, dict) and branch.get("type") == "damage_modifier"), None)
            amount = typed_reactions._generic_amount(engine, defender, row, reduction) if reduction else 0
            if amount:
                key = f"typed_hit_reduction:{attacker.entity_id}"
                defender.turn_flags[key] = int(defender.turn_flags.get(key) or 0) + amount
                defender.turn_flags[PARKED + attacker.entity_id] = amount
            ctx.rider(f"Harmonious Body: {attacker.display_name} holds its footing; if the attack hits, its damage is reduced by {amount}.")
            return None
        if result != "fail":
            return None
        if choice.startswith("redirect:"):
            chosen = engine.state.actors.get(choice.split(":", 1)[1])
            if chosen is not None and legal_target(engine, attacker, chosen, range_ft):
                ctx.rider(f"Harmonious Body: {attacker.display_name}'s attack is turned on {chosen.display_name}.")
                return {"source_id": f"ability:{HARMONIOUS}", "target_id": chosen.entity_id, "cover_bonus": 0}
            return None
        if choice == "move" and attacker.active and engine._distance_actor_to_actor(attacker, defender) <= int(range_ft or 5):
            ctx.rider(f"Harmonious Body: {defender.display_name} is still within {attacker.display_name}'s reach; the attack goes on.")
            return None
        engine._typed_negated = {*getattr(engine, "_typed_negated", set()), (attacker.entity_id, defender.entity_id)}
        ctx.rider(f"Harmonious Body: {attacker.display_name}'s attack misses.")
        return None


@effect("harmonious_body_result")
def _harmonious_result(ctx: Any, spec: dict[str, Any]) -> None:
    ctx.engine._harmonious_result = spec.get("result")


@hook("reaction_subject_allowed")
def _harmonious_body_is_the_provider(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """The compiled reaction (the save and the success reduction, no failure branch) never answers: the provider above plays it."""
    return False if row.get("feature_id") == HARMONIOUS and owns(engine, reactor, "harmonious_body") else None


@hook("after_miss")
def _harmonious_unpark(ctx: Any, target: Any) -> None:
    """"If it hits, reduce its damage": a miss leaves nothing parked for the attacker's next hit."""
    amount = target.turn_flags.pop(PARKED + ctx.actor.entity_id, None)
    if amount:
        key = f"typed_hit_reduction:{ctx.actor.entity_id}"
        left = int(target.turn_flags.get(key) or 0) - int(amount)
        if left > 0:
            target.turn_flags[key] = left
        else:
            target.turn_flags.pop(key, None)


@hook("after_hit")
def _harmonious_spent(ctx: Any, target: Any, kind: str) -> None:
    target.turn_flags.pop(PARKED + ctx.actor.entity_id, None)  # the damage step takes the parked reduction itself


# ------------------------------------------------------------------------------------------------ Redirecting Shield (Shield)
REDIRECTING = "TAL_SHIELD_REDIRECTING_SHIELD"
ACTIVE_DEFENSE = "SHIELD_BASE_ACTIVE_DEFENSE"
FOCUS = "resource:core.martial_focus"


def _missed_roll(engine: Any, attacker: Any, target: Any) -> tuple[Any | None, bool]:
    """Return this miss and whether its own post-roll Active Defense window answered it."""
    roll = next((event for event in reversed(engine.events)
                 if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker.entity_id
                 and target.entity_id in (event.target_ids or ())), None)
    if roll is None:
        return None, False
    from ..attack_outcomes import attempt_end

    # Active Defense is now post-roll. Restrict the window lookup to this
    # attempt, rather than letting an earlier swing's window leak forward.
    start = roll.sequence - 1
    end = attempt_end(engine, attacker.entity_id, start)
    defended = any(event.event_type == "REACTION_WINDOW_OPENED"
                   and event.actor_id == target.entity_id
                   and event.source_definition_id == ACTIVE_DEFENSE
                   and attacker.entity_id in (event.target_ids or ())
                   for event in engine.events[start:end])
    return roll, defended


@hook("after_miss")
def redirecting_shield(ctx: Any, target: Any) -> None:
    """When a weapon attack misses a creature that benefits from your Active Defense, you may spend Martial Focus to aim that attack
    at one other legal target: a melee attack at a creature within the attacker's original reach, a ranged attack at a creature
    inside the attack's original range from the attacker. The original attack roll is compared to the new target's AC and the attack
    keeps its original damage and effects. Perfect Redirection: spell attacks and Cultivation Attacks count too. The creature
    benefiting is the Shield fighter itself (its Active Defense answered this attack; Cover Ally is not played). The table picks the
    new target or declines; the AI takes a creature of the attacker's side the roll would hit, the lowest Armor Class first."""
    from ..typed_executor import Context, run_effects

    engine, attacker = ctx.engine, ctx.actor
    if (not target.active or attacker.team_id == target.team_id or not owns(engine, target, "redirecting_shield")
            or target.resources.get(FOCUS, 0) < 1 or getattr(engine, "_redirection_busy", False)):
        return
    if ctx.typed.get("weapon") is None and not owns(engine, target, "perfect_redirection"):
        return  # a weapon attack (Perfect Redirection: any attack roll)
    attack = next((row for row in ctx.typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    roll, defended = _missed_roll(engine, attacker, target)
    if attack is None or roll is None or not defended:
        return
    ranged = bool(ctx.typed.get("range_ft"))
    range_ft = int(ctx.typed.get("long_range_ft") or ctx.typed.get("range_ft") or ctx.action.range_ft or 0) if ranged \
        else int(ctx.action.reach_ft or ctx.action.range_ft or 5)
    total, natural = int((roll.payload or {}).get("modified_total") or 0), int((roll.payload or {}).get("natural_result") or 0)
    ac = {row.entity_id: row.armor_class + engine._ac_modifier(row) for row in engine.state.actors.values()}
    others = sorted(_others(engine, attacker, target, range_ft),
                    key=lambda row: (row.team_id != attacker.team_id, not (natural != 1 and total >= ac[row.entity_id]), ac[row.entity_id], row.entity_id))
    if not others:
        return
    labels = {row.entity_id: f"Redirecting Shield: the missed attack ({total}) at {row.display_name} (AC {ac[row.entity_id]})" for row in others}
    best = others[0]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "REDIRECTING_SHIELD", target.entity_id, attacker.entity_id), target,
                 CHOICE + "redirecting_shield", list(labels), labels=labels, preferred=[best.entity_id],
                 prompt=f"Redirecting Shield (1 Martial Focus): send {attacker.display_name}'s missed attack at another creature?",
                 allow_decline=True, automatic=best.team_id == attacker.team_id and natural != 1 and total >= ac[best.entity_id],
                 target_id=target.entity_id, default="decline")
    chosen = next((row for row in others if picked and row.entity_id == picked[0]), None)
    if chosen is None:
        return
    engine._spend_resource(target, FOCUS, 1, f"passive:{REDIRECTING}")
    hit = natural != 1 and (natural == 20 or total >= ac[chosen.entity_id])
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{REDIRECTING}", actor_id=target.entity_id, target_ids=(attacker.entity_id, chosen.entity_id),
                         payload={"trigger": "Redirecting Shield", "total": total, "ac": ac[chosen.entity_id], "hit": hit})
    if not hit:
        return
    on_hit = [row for row in attack.get("on_hit") or [] if isinstance(row, dict)]
    if not any(row.get("type") == "damage" for row in on_hit) and not attack.get("no_damage"):
        on_hit = [{"type": "damage", "weapon_damage": True}, *on_hit]
    engine._redirection_busy = True  # the redirected attack is not redirected again
    try:
        run_effects(Context(engine, attacker, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, {}), on_hit)
    finally:
        engine._redirection_busy = False
