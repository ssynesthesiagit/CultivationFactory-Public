"""Karma lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium, Karma
(owner's text: authority/typed_mechanics/rules_text.json).  Built on combat/ext/karma_imprints.py (the Debt/Grace ledger) and
karma_consumers.py; rows: feature block "lane9_karma" (combat/rules/feature_blocks.d/riders_lane9.json); typed effects "karma_*" below.

  Requirements      Chain of Consequence and Heavenly Retribution need three of your Debt Imprints on the target, Trial of the Ledger two of
                    your Imprints, Ten Thousand Debts, Judgment Writ and Debt Written on Bone one Debt Imprint (the action is offered only then).
  Chain of          5 CP and three Debt Imprints: failed save -- the next time the target deals damage before the end of your next turn, it
  Consequence       takes the same Psychic damage (at most 10 x CL); success -- PB + key Psychic and no Reactions until the start of its turn.
  Ten Thousand      failed save -- until the end of your next turn, the first time the target damages another creature it takes that much
  Debts             Psychic damage (8d10 for an attributed harmful condition); success -- 4d10 Psychic and no Reactions until the start of its next turn.
  Trial of the      failed save -- the first time each turn it harms another creature, 2d8 Psychic; the first time each turn it heals another,
  Ledger            2d8 Temporary HP; it repeats the Charisma save at the end of each of its turns.  Success: the first harm before the start
                    of your next turn costs it PB + key Psychic.
  Heavenly          every Debt Imprint on the target is consumed; failed save -- 4d10 Psychic per Imprint (at most PB of them) and Stunned
  Retribution       until the start of its next turn; success -- half and no Reactions until the start of its next turn.
  Judgment Writ     failed save -- for the fight, the first time each turn the target deals damage again it takes PB + key Psychic; success --
                    the same until the end of your next turn.
  Debt Written on   one Debt Imprint spent; the next time the creature deals damage: PB + key Psychic, or no Reactions until the end of its
  Bone              next turn.
  Merit Becomes     the first time each round the bearer restores HP to another creature it gains PB Temporary HP.
  Armor
  Borrowed Tomorrow Reaction, 8 CP, once a fight: you or an ally within 60 feet fails a saving throw (it succeeds instead -- a d20_rewrite rule)
                    or would drop to 0 HP (it drops to 1 instead).
  Fate Deferred     Reaction, 5 CP: damage that would drop you or an ally within 60 feet waits until the end of that creature's next turn.
  Karma-Sovereign   Record the Deed reaches 300 feet (karma_imprints.record_range).
  Incarnation

Judgment calls: Trial and Ten Thousand Debts also recognize attributed harmful conditions, whether the condition was cast directly or
                    imposed inside another rider's resolution (Air's No Steady Foot, a hold); the landed instance is classified by
                    combat/ext/karma_causes.py. Other "harm" and "heal" are damage dealt to, and HP restored to, another creature (the
                    Causes karma_imprints reads); Judgment
Writ's "same type of harmful Cause" is damage; Debt Written on Bone's third choice (no benefit from Advantage on the attack that dealt the
damage) cannot be taken back after the roll and is the GM's; the AI uses Fate Deferred only when the damage would drop the creature.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .retained_updates import record_instance_update

BLOCK = "lane9_karma"
K = "tianxia.talent.karma."
CHAIN_ID, TEN_ID, TRIAL_ID, RETRIBUTION_ID = K + "chain_of_consequence", K + "ten_thousand_debts_return_to_source", K + "trial_of_the_ledger", K + "heavenly_retribution"
WRIT_ID, BONE_ID, MERIT_ID, BORROWED_ID = K + "judgment_writ", K + "debt_written_on_bone", K + "merit_becomes_armor", K + "borrowed_tomorrow"
DEFERRED_ID, SOVEREIGN_ID = K + "fate_deferred", K + "karma_sovereign_incarnation"
BURDEN_ID = K + "burden_of_deeds"
C = "condition:typed."
DEFERRED = C + "karma_deferred"
# The engine retains _round_ flags at turn start; runtime-control snapshots
# persist this integer for both reaction branches and preview clones.
BORROWED_SPENT = "_round_karma_borrowed_tomorrow"
# Transient engine flag (never persisted): a Karma consequence is being paid, so the
# payout's own events cannot start another one.
PAYING = "_karma_paying_consequence"
# Fate Deferred's own delayed arrival, the same one-shot guard for its damage.
DEFERRED_PENDING = "_karma_deferring"
CHAIN, TEN, TRIAL, TRIAL_ONCE, WRIT, BONE, MERIT, SOVEREIGN = (C + "karma_chain", C + "karma_ten_thousand", C + "karma_trial", C + "karma_trial_once",
                                                               C + "karma_writ", C + "karma_bone", C + "karma_merit", C + "karma_sovereign")
NEEDS = {CHAIN_ID: ("debt", 3), RETRIBUTION_ID: ("debt", 3), TRIAL_ID: (None, 2), TEN_ID: ("debt", 1), WRIT_ID: ("debt", 1), BONE_ID: ("debt", 1),
         BURDEN_ID: ("debt", 1)}
BURDEN = C + "karma_burden"


@hook("compile_actions")
def burden_marked_allies(info: dict[str, Any]) -> list[Any] | None:
    """The printed requirement allows a marked creature on either team."""
    return [action.model_copy(update={"source_definition_id": action.source_definition_id + "#marked_ally",
                                     "display_name": "Burden of Deeds (ally or self)", "target_kind": "ALLY_OR_SELF"})
            for action in info["actions"]
            if (action.parameters or {}).get("typed", {}).get("source") == BURDEN_ID
            and action.target_kind == "HOSTILE_ENTITY"] or None


@effect("karma_burdens")
def burden_choices(ctx: Any, eff: dict[str, Any]) -> None:
    """After a failed save, select one printed burden per owned Debt Imprint.

    Repeated numeric penalties stack; duplicate reaction denial/disadvantage
    adds nothing and is omitted. The shared repeat group owns cleanup of all
    selected effects on successful repeat save or concentration expiry.
    """
    from .karma_imprints import held
    from ..typed_executor import run_effects

    if _feature(ctx.engine, ctx.source) != BURDEN_ID or ctx.target is None:
        return
    target = ctx.target
    chosen = []
    labels = ["Speed reduced by 5 feet", "-1 to attack rolls", "-1 to saving throws",
              "Cannot take Reactions", "Disadvantage on the next ability check before its next turn ends"]
    count = len(held(target, ctx.actor.entity_id, "debt"))
    for index in range(count):
        options = [label for label in labels if label not in labels[3:] or label not in chosen]
        if ctx.engine._effective_speed(target) <= 5 * chosen.count(labels[0]):
            options.remove(labels[0])  # no further mathematically meaningful Speed reduction
        picked = ask(ctx.engine, ctx.intent,
                     checkpoint_id(ctx.engine, "BURDEN", ctx.actor.entity_id, target.entity_id, index),
                     ctx.actor, CHOICE + "karma_burden", options, name="Burden of Deeds", feature_id=BURDEN_ID,
                     preferred=[labels[0] if labels[0] in options else labels[1]], target_id=target.entity_id,
                     prompt=f"Burden of Deeds: {target.display_name} failed its Charisma save. "
                            f"Choose burden {index + 1} of {count} (one per your Debt Imprint; Imprints are not spent). "
                            "The penalties last while you concentrate, up to 1 minute; a successful turn-end save ends them. "
                            "Costs 3 cultivation points for this Action.")
        if picked:
            chosen.append(picked[0])
    if not chosen:
        return
    effects = [{"type": "condition", "condition": "karma_burden", "applies_to": "target", "duration": "concentration",
                "repeat_save": {"ability": "CHA", "when": "end"},
                "condition_data": {"attack_penalty": chosen.count(labels[1]), "save_penalty": chosen.count(labels[2]),
                                   "rule": {"no_reactions": labels[3] in chosen},
                                   "label": "Burden of Deeds: " + "; ".join(chosen)}}]
    if labels[0] in chosen:
        effects.append({"type": "speed", "applies_to": "target", "flat": -5 * chosen.count(labels[0]), "duration": "concentration"})
    if labels[4] in chosen:
        effects.append({"type": "condition", "condition": "karma_burden_check", "applies_to": "target",
                        "condition_data": {"rule": {"check_mode": {"ALL": "DISADVANTAGE"}},
                                           "label": "Burden of Deeds: Disadvantage on the next ability check before this creature's next turn ends"},
                        "duration": "until_end_of_next_turn"})
    run_effects(ctx, [{"type": "rider_repeat_group", "name": "Burden of Deeds", "duration": "concentration", "effects": effects}])


@hook("d20_bonus")
def burden_attack_penalty(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """All native attack rolls, including legacy attacks, use the same penalty."""
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None:
        return None
    if (engine.d20_context(roll) or {}).get("kind") == "check":
        for key, condition in list(actor.conditions.items()):
            if condition.condition_id == C + "karma_burden_check":
                del actor.conditions[key]
                engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                                     actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": key, "reason": "CONSUMED"})
    if not str(roll.reason).startswith("ATTACK:"):
        return None
    penalty = sum(int(c.data.get("attack_penalty") or 0) for c in actor.conditions.values() if c.condition_id == BURDEN)
    return {"source_id": BURDEN_ID, "bonus": -penalty} if penalty else None


@hook("save_bonus")
def burden_save_penalty(engine: Any, target: Any, ability: str, dc: int, source_id: str, intent: Any) -> int | None:
    penalty = sum(int(c.data.get("save_penalty") or 0) for c in target.conditions.values() if c.condition_id == BURDEN)
    return -penalty if penalty else None


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             "cl": int(numbers.get("cl") or 1), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _feature(engine: Any, source: Any) -> str:
    action = engine.action_catalog.get(str(source or ""))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return str(typed.get("option_of") or typed.get("source") or "")


def _roll(engine: Any, actor: Any, count: int, sides: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _psychic(engine: Any, target: Any, amount: int, source: str, owner_id: str) -> None:
    if amount > 0 and target.active:
        engine._commit_damage(target, int(amount), "PSYCHIC", source, owner_id, None, reaction_depth=1)


def _token(actor: Any, edge: str, ahead: int = 1) -> str:
    from .effect_durations import token

    return token(edge, actor.entity_id, int(actor.turns_started) + ahead)


def _pay_key(ctx: Any) -> int:
    return int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0)


# ------------------------------------------------------------------------------------------------ requirements
@hook("candidate_allowed")
def imprint_requirements(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from .karma_imprints import held

    if action is None:
        return None
    need = NEEDS.get(_feature(engine, action.source_definition_id))
    if need is None:
        return None
    kind, count = need
    return all(t in engine.state.actors and len(held(engine.state.actors[t], actor.entity_id, kind)) >= count for t in candidate.target_ids or ()) \
        and bool(candidate.target_ids)


# ------------------------------------------------------------------------------------------------ the effects
@effect("karma_spend")
def karma_spend(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "karma_spend", "kind": "debt", "count": n | "all"}: the Imprints the talent consumes, spent as it is used."""
    from .karma_imprints import held, spend

    for target in ctx.targets or []:
        if target is None:
            continue
        count = len(held(target, ctx.actor.entity_id, eff.get("kind"))) if eff.get("count") == "all" else int(eff.get("count") or 1)
        ctx.damage_cache[("karma_spent", target.entity_id)] = spend(ctx.engine, ctx.actor, target, str(eff.get("kind") or "debt"), count, ctx.source)


@effect("karma_mark")
def karma_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "karma_mark", "what": "chain" | "ten" | "trial" | "trial_once" | "writ" | "writ_short" | "bone", ...}: the condition that waits
    for the target's next harm (or heal)."""
    engine, caster = ctx.engine, ctx.actor
    what = str(eff.get("what"))
    cl, pb_key = int(ctx.numbers.get("cl") or 1), _pay_key(ctx)
    for target in ctx.targets or []:
        if target is None or not target.active:
            continue
        if what == "chain":
            engine._apply_condition(target, CHAIN, ctx.source, caster.entity_id, expires_on=_token(caster, "end"),
                                    data={"cap": 10 * cl, "label": "Chain of Consequence: its next damage returns to it as Psychic damage"})
        elif what == "ten":
            engine._apply_condition(target, TEN, ctx.source, caster.entity_id, expires_on=_token(caster, "end"),
                                    data={"label": "Ten Thousand Debts: the first harm it deals returns to it"})
        elif what == "trial":
            engine._apply_condition(target, TRIAL, ctx.source, caster.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                                    data={"repeat_save": {"ability": "CHA", "dc": int(ctx.numbers.get("save_dc") or 10), "when": "end"},
                                          "label": "Trial of the Ledger: harm costs 2d8 Psychic, a heal gives 2d8 Temporary HP"})
        elif what == "trial_once":
            engine._apply_condition(target, TRIAL_ONCE, ctx.source, caster.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"amount": pb_key, "label": "Trial of the Ledger: its first harm costs Psychic damage"})
        elif what in ("writ", "writ_short"):
            engine._apply_condition(target, WRIT, ctx.source, caster.entity_id,
                                    expires_on="UNTIL_REMOVED" if what == "writ" else _token(caster, "end"),
                                    data={"amount": pb_key, "label": "Judgment Writ: each turn, its first harm costs Psychic damage"})
        elif what == "bone":
            engine._apply_condition(target, BONE, ctx.source, caster.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                    data={"choice": eff.get("choice"), "amount": pb_key, "label": f"Debt Written on Bone: {eff.get('choice')}"})


@effect("karma_psychic")
def karma_psychic(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "karma_psychic", "amount": "pb_key" | "4d10", "no_reactions": bool}: a Karma talent's damage on a successful save."""
    for target in ctx.targets or []:
        if target is None:
            continue
        amount = _pay_key(ctx) if eff.get("amount") == "pb_key" else _roll(ctx.engine, ctx.actor, 4, 10, "DAMAGE:" + ctx.source)
        _psychic(ctx.engine, target, amount, ctx.source, ctx.actor.entity_id)
        if eff.get("no_reactions") and target.active:
            ctx.engine._apply_condition(target, C + "reaction_denied", ctx.source, ctx.actor.entity_id, expires_on=_token(target, "start"),
                                        data={"label": "No Reactions"})


@effect("karma_retribution")
def karma_retribution(ctx: Any, eff: dict[str, Any]) -> None:
    """Heavenly Retribution: every Debt Imprint on the target is consumed; the damage is 4d10 per Imprint consumed, at most PB of them."""
    from .karma_imprints import held, spend

    engine, caster = ctx.engine, ctx.actor
    dc = int(ctx.numbers.get("save_dc") or 10)
    for target in ctx.targets or []:
        if target is None or not target.active:
            continue
        count = min(len(held(target, caster.entity_id, "debt")), int(ctx.numbers.get("pb") or 2))
        spend(engine, caster, target, "debt", len(held(target, caster.entity_id, "debt")), ctx.source)
        damage = _roll(engine, caster, 4 * max(1, count), 10, "DAMAGE:" + ctx.source)
        roll = engine._roll_save(target, "CHA", dc, ctx.source)
        failed = roll is not None and int(roll.total) < dc
        _psychic(engine, target, damage if failed else damage // 2, ctx.source, caster.entity_id)
        if not target.active:
            continue
        if failed:
            from ..typed_executor import condition_immune

            if not condition_immune(engine, target, "stunned"):  # "Stunned until the start of its next turn"
                engine._apply_condition(target, C + "stunned", ctx.source, caster.entity_id, expires_on=_token(target, "start"), data={"label": "Stunned"})
        else:
            engine._apply_condition(target, C + "reaction_denied", ctx.source, caster.entity_id, expires_on=_token(target, "start"),
                                    data={"label": "No Reactions"})


# ------------------------------------------------------------------------------------------------ the waiting conditions
# The printed consequences whose payout reads a non-damage Debt Cause as well as damage
# (a harmful condition alone comes due). Chain of Consequence and Judgment Writ, and Debt
# Written on Bone, are paid by damage only.
HARMFUL_WAITERS = (TEN, TRIAL, TRIAL_ONCE)


def _own_payout(event: Any) -> bool:
    """Whether this event is a Karma consequence's own payment, never a new Cause."""
    source = str(getattr(event, "source_definition_id", "") or "")
    return source.startswith(K) and source in (CHAIN_ID, TEN_ID, TRIAL_ID, WRIT_ID, BONE_ID, DEFERRED_ID)


@hook("event", nested=True)
def karma_harmful_conditions(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A harmful condition that lands on another creature is a Debt Cause for Ten
    Thousand Debts, Trial of the Ledger (repeated and successful-save) and Debt
    Written on Bone -- including one imposed inside another event subscriber, such
    as No Steady Foot's Dexterity failure or a rider's hold.

    Nested delivery is opt-in, so this is the only Condition subscriber: the damage
    and healing branches below keep their exact legacy root-only delivery. Inert
    unless the creature inflicting the condition already carries one of those Karma
    conditions, and a consequence being paid never starts another one.
    """
    if event_type != "CONDITION_APPLIED" or engine.__dict__.get(PAYING):
        return
    if _own_payout(kwargs.get("originating_event")):
        return
    payload = kwargs.get("payload") or {}
    doer = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if doer is None or not any(c.condition_id in HARMFUL_WAITERS for c in doer.conditions.values()):
        return  # no Karma consequence is waiting on this creature's next harm
    targets = [t for t in kwargs.get("target_ids") or () if t != doer.entity_id]
    if not targets:
        return
    from .karma_causes import inflicted_harm

    if any(inflicted_harm(engine, payload, target_id) for target_id in targets):
        _harmed(engine, doer, None)


@hook("event")
def karma_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Damage and healing a Karma consequence waits for (root events only)."""
    if _own_payout(kwargs.get("originating_event")):
        return  # its own payout is not a new harm
    payload = kwargs.get("payload") or {}
    doer = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    targets = [t for t in kwargs.get("target_ids") or () if doer is None or t != doer.entity_id]
    if doer is None or not targets:
        return
    if event_type == "DAMAGE_COMMITTED" and int(payload.get("reduced_to") or 0) > 0:
        _harmed(engine, doer, int(payload.get("reduced_to") or 0))
    elif event_type == "HEALING_APPLIED" and int(payload.get("after") or 0) > int(payload.get("before") or 0):
        _healed(engine, doer)


def _harmed(engine: Any, doer: Any, amount: int | None) -> None:
    """Pay every Karma consequence this harm comes due on, once each.

    A consequence's own payment -- its Psychic damage, the No Reactions it imposes, a
    reaction it provokes -- is never a new harm, so payment runs under PAYING and the
    engine's nested-dispatch depth limit is never the only recursion control.
    """
    if engine.__dict__.get(PAYING):
        return
    engine.__dict__[PAYING] = True
    try:
        _pay_harm(engine, doer, amount)
    finally:
        engine.__dict__[PAYING] = False


def _pay_harm(engine: Any, doer: Any, amount: int | None) -> None:
    turn = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    for held in list(doer.conditions.values()):
        cid = held.condition_id
        if cid not in (CHAIN, TEN, TRIAL, TRIAL_ONCE, WRIT, BONE):
            continue
        if amount is None and cid not in HARMFUL_WAITERS:
            continue  # These three rules explicitly include non-damage Debt Causes.
        data = held.data or {}
        if cid in (TRIAL, WRIT) and data.get("turn") == turn:
            continue  # "the first time each turn"
        owner = held.source_actor_id
        if cid == CHAIN:
            engine._remove_condition(doer, CHAIN, CHAIN_ID)
            _psychic(engine, doer, min(amount, int(data.get("cap") or amount)), CHAIN_ID, owner)
        elif cid == TEN:
            engine._remove_condition(doer, TEN, TEN_ID)
            consequence = amount if amount is not None else _roll(engine, doer, 8, 10, "TEN_THOUSAND_DEBTS")
            _psychic(engine, doer, consequence, TEN_ID, owner)
        elif cid == TRIAL:
            held.data["turn"] = turn
            record_instance_update(engine, doer, "condition", held.instance_id, held)
            _psychic(engine, doer, _roll(engine, doer, 2, 8, "TRIAL_OF_THE_LEDGER"), TRIAL_ID, owner)
        elif cid == TRIAL_ONCE:
            engine._remove_condition(doer, TRIAL_ONCE, TRIAL_ID)
            _psychic(engine, doer, int(data.get("amount") or 2), TRIAL_ID, owner)
        elif cid == WRIT:
            held.data["turn"] = turn
            record_instance_update(engine, doer, "condition", held.instance_id, held)
            _psychic(engine, doer, int(data.get("amount") or 2), WRIT_ID, owner)
        elif cid == BONE:
            engine._remove_condition(doer, BONE, BONE_ID)
            if data.get("choice") == "Deny Reactions":
                engine._apply_condition(doer, C + "reaction_denied", BONE_ID, owner, expires_on="END_OF_HOLDER_NEXT_TURN", data={"label": "No Reactions"})
            else:
                _psychic(engine, doer, int(data.get("amount") or 2), BONE_ID, owner)
        if not doer.active:
            return


def _healed(engine: Any, doer: Any) -> None:
    turn = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    for held in _held(doer, TRIAL):
        if (held.data or {}).get("heal_turn") != turn:
            held.data["heal_turn"] = turn
            record_instance_update(engine, doer, "condition", held.instance_id, held)
            engine._grant_temp_hp(doer, _roll(engine, doer, 2, 8, "TRIAL_OF_THE_LEDGER"), TRIAL_ID, held.source_actor_id)
    for held in _held(doer, MERIT):
        if (held.data or {}).get("round") != engine.state.round_number:
            held.data["round"] = engine.state.round_number  # "the first time each round it ... restores HP"
            record_instance_update(engine, doer, "condition", held.instance_id, held)
            engine._grant_temp_hp(doer, int((held.data or {}).get("pb") or 2), MERIT_ID, held.source_actor_id)


@hook("technique_used")
def karma_used(ctx: Any) -> None:
    source = str(ctx.typed.get("source") or "")
    if source == MERIT_ID:
        for target in ctx.targets or []:
            if target is not None:
                ctx.engine._apply_condition(target, MERIT, MERIT_ID, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                            data={"pb": int(ctx.numbers.get("pb") or 2), "label": "Merit Becomes Armor: healing another gives Temporary HP"})
    elif source == SOVEREIGN_ID:
        ctx.engine._apply_condition(ctx.actor, SOVEREIGN, SOVEREIGN_ID, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                    data={"label": "Karma-Sovereign Incarnation: Record the Deed reaches 300 feet"})


# ------------------------------------------------------------------------------------------------ Borrowed Tomorrow, Fate Deferred
def _borrowed_ready(engine: Any, reactor: Any, subject: Any) -> bool:
    from .. import typed_reactions
    from .d20_rewrite import pool_id

    cp = pool_id(reactor, "cp")
    return (bool(rows(engine, reactor, "borrowed")) and reactor.active and subject.team_id == reactor.team_id
            and engine._distance_actor_to_actor(reactor, subject) <= 60 and typed_reactions._can_react(engine, reactor)
            and cp is not None and reactor.resources.get(cp, 0) >= 8
            and not reactor.turn_flags.get(BORROWED_SPENT))


def _borrowed_pay(engine: Any, reactor: Any, subject: Any, why: str) -> None:
    from .d20_rewrite import pool_id

    engine._spend_resource(reactor, pool_id(reactor, "cp"), 8, BORROWED_ID)
    reactor.reaction_available = False
    reactor.turn_flags[BORROWED_SPENT] = 1  # No long-rest transition within a fight.
    engine._append_event("REACTION_WINDOW_OPENED", BORROWED_ID, actor_id=reactor.entity_id, target_ids=(subject.entity_id,), payload={"checkpoint": why})
    note(engine, BORROWED_ID, reactor, f"Borrowed Tomorrow: {subject.display_name} borrows against Heaven (a Karmic Burden follows).")


@hook("would_drop")
def borrowed_hold(engine: Any, target: Any, pending: int, source_actor_id: Any) -> int | None:
    for reactor in engine.state.actors.values():
        if not _borrowed_ready(engine, reactor, target):
            continue
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "BORROWED", reactor.entity_id, target.entity_id), reactor,
                     CHOICE + "borrowed_tomorrow", ["hold"], labels={"hold": "Borrowed Tomorrow (Reaction, 8 CP): it drops to 1 HP instead"},
                     allow_decline=True, target_id=target.entity_id, prompt=f"{target.display_name} would drop to 0 HP: Borrowed Tomorrow?")
        if picked:
            with activation(engine, reactor, BORROWED_ID):
                _borrowed_pay(engine, reactor, target, "DROP_TO_ZERO")
                return max(0, int(target.current_hp) + int(target.temporary_hp) - 1)
    return None


def _register_rule() -> None:
    from .d20_rewrite import Holder, Rule, register

    def finder(engine: Any) -> list[Any]:
        return [Holder(a, BORROWED_ID, row, BORROWED_ID, {"pb": row["pb"], "key_mod": row["key_mod"], "cl": row["cl"]})
                for a in engine.state.actors.values() if a.active for row in rows(engine, a, "borrowed")]

    def guard(engine: Any, holder: Any, rc: Any) -> bool:
        return _borrowed_ready(engine, holder.actor, rc.roller)

    def after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
        holder.actor.turn_flags[BORROWED_SPENT] = 1
        note(engine, BORROWED_ID, holder.actor, f"Borrowed Tomorrow: {rc.roller.display_name}'s failed save becomes a success (a Karmic Burden follows).")

    register(Rule("borrowed_tomorrow", "Borrowed Tomorrow", rolls=("save",), who="team", range_ft=60, when="failed", op="choose",
                  costs=((("cp", 8),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", feature=BORROWED_ID, finder=finder,
                  guard=guard, choose=lambda engine, holder, rc: 20,
                  bonus=lambda engine, holder, rc: max(0, int(rc.dc) - (20 + int(rc.roll.modifier))) if rc.dc is not None else 0,
                  after=after,
                  ai=lambda engine, holder, rc: True))


_register_rule()


@hook("incoming_damage")
def fate_deferred(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    from .. import typed_reactions
    from .d20_rewrite import pool_id

    if amount <= 0 or str(source_definition_id) == DEFERRED_ID or engine.__dict__.get(DEFERRED_PENDING):
        return None
    for reactor in engine.state.actors.values():
        if not rows(engine, reactor, "deferred") or not reactor.active or reactor.team_id != target.team_id:
            continue
        cp = pool_id(reactor, "cp")
        if engine._distance_actor_to_actor(reactor, target) > 60 or cp is None or reactor.resources.get(cp, 0) < 5 or not typed_reactions._can_react(engine, reactor):
            continue
        lethal = amount >= int(target.current_hp) + int(target.temporary_hp)
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "FATE_DEFERRED", reactor.entity_id, target.entity_id), reactor,
                     CHOICE + "fate_deferred", ["defer"], labels={"defer": f"Fate Deferred (Reaction, 5 CP): the {amount} damage waits a turn"},
                     allow_decline=True, target_id=target.entity_id, default="first" if lethal else "decline",
                     prompt=f"{target.display_name} would take {amount} {damage_type} damage: Fate Deferred?")
        if not picked:
            continue
        with activation(engine, reactor, DEFERRED_ID):
            engine._spend_resource(reactor, cp, 5, DEFERRED_ID)
            reactor.reaction_available = False
            engine._append_event("REACTION_WINDOW_OPENED", DEFERRED_ID, actor_id=reactor.entity_id, target_ids=(target.entity_id,), payload={"checkpoint": "DAMAGE_PENDING"})
            # Each payment owns an evented instance. Keep it until the arrival hook
            # consumes it, rather than letting expiry discard the obligation first.
            engine._apply_condition(target, DEFERRED, DEFERRED_ID, reactor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"amount": int(amount), "type": str(damage_type), "due": int(target.turns_started) + 1})
            note(engine, DEFERRED_ID, target, f"Fate Deferred: {amount} {damage_type} damage waits until the end of {target.display_name}'s next turn.")
            return amount
    return None


@hook("turn_end")
def deferred_arrives(engine: Any, actor: Any) -> None:
    """The delayed damage arrives, and cannot itself be deferred (DEFERRED_PENDING)."""
    for instance_id, condition in list(actor.conditions.items()):
        if condition.condition_id != DEFERRED or int(actor.turns_started) < int(condition.data["due"]):
            continue
        part = condition.data
        del actor.conditions[instance_id]
        engine._append_event("CONDITION_REMOVED", DEFERRED_ID, actor_id=condition.source_actor_id,
                             target_ids=(actor.entity_id,), payload={"condition_id": DEFERRED, "instance_id": instance_id,
                                                                     "reason": "DEFERRED_DAMAGE_ARRIVES"})
        note(engine, DEFERRED_ID, actor, f"Fate Deferred: the delayed {part['amount']} {part['type']} damage arrives.")
        engine.__dict__[DEFERRED_PENDING] = True
        try:
            engine._commit_damage(actor, int(part["amount"]), str(part["type"]).upper(), DEFERRED_ID, condition.source_actor_id, None, reaction_depth=1)
        finally:
            engine.__dict__[DEFERRED_PENDING] = False
