"""Karma talents that spend Imprints (system C2a, sys/resources-states 2026-09-29): Invoke the Ledger, Settle Minor Account, Grace Repaid,
Harm Returned, Grace Shelters the Innocent, Karmic Exchange, Reversal of Due Fortune.  The ledger itself (Debt and Grace Imprints as named
marks, Record the Deed, the Court) is combat/ext/karma_imprints.py.

Owner text (authority/typed_mechanics/rules_text.json; Tianxia Sphere Compendium, Karma):
  * Invoke the Ledger (Bonus Action, 60 ft, 1 CP + one Imprint): a creature carrying one of your Imprints.  Debt: it subtracts 1d4 from the
    next attack roll, ability check or saving throw it makes before the end of your next turn.  Grace: it adds 1d4.  A creature can be
    affected by only one Invoke die from you at a time.  CL 11: 1d6, CL 17: 1d8.
  * Settle Minor Account (Action, 60 ft, 1 CP + a matching Imprint).  Debt: Charisma save; failure, psychic 1d8 + key ability modifier and no
    Reactions until the start of its next turn; success, half damage and it keeps its Reactions.  Grace: Temporary HP 1d8 + key ability
    modifier, and it may immediately end one of Grappled, Prone, or Disadvantage on its next ability check.  2d8 at CL 5, 3d8 at CL 11, 4d8 at 17.
  * Grace Repaid (Reaction, 1 CP + a Grace Imprint): a creature carrying one of your Grace Imprints takes damage within 60 feet; reduce the
    damage by 1d8 + key ability modifier (2d8, 3d8, 4d8 at CL 5, 11, 17).
  * Harm Returned (Reaction, 3 CP + two Debt Imprints): a creature with at least two of your Debt Imprints deals damage to you or an ally
    within 60 feet; it takes psychic damage equal to half the triggering damage, at most 5 x CL; that damage cannot trigger Harm Returned,
    Return the Sting or similar talents.
  * Grace Shelters the Innocent (Reaction, 2 CP + a Grace Imprint): a creature carrying one of your Grace Imprints fails a saving throw
    against a harmful effect; add 1d6 to the save; if that turns failure into success the creature also gains Temporary HP equal to your
    Proficiency Bonus (a creature bound by your Red Thread of Fellowship that the effect would also harm gains the same).
  * Karmic Exchange (Reaction, 3 CP + a matching Imprint): a creature within 60 feet rolls an attack roll, ability check or saving throw;
    "after seeing the roll but before knowing the result" expend a Debt Imprint on it to subtract 1d6, or a Grace Imprint to add 1d6.  A roll
    can be affected by only one Karmic Exchange.  CL 17: 1d8.
  * Reversal of Due Fortune (Reaction, 4 CP + a matching Imprint, once per short or long rest): a creature within 60 feet rolls a natural 1 or
    20; a Grace Imprint turns a natural 1 into a natural 20, a Debt Imprint a natural 20 into a natural 1.  A Legendary or Secret effect may
    resist it with a Charisma save or opposed check.
Spheres 5e and D&D 5.5e have no Imprints; these follow the text above.

How each runs.
  * The die of Invoke the Ledger is a condition on the target (``condition:typed.karma_invoke.<owner>``, hover text says who and how big) that
    the target's own next d20 spends: the ``attack_bonus``, ``check_bonus`` and ``save`` hooks add it before a typed roll; an attack by a
    creature that is not a typed fighter (a monster) is settled after the roll (``event`` ATTACK_ROLLED, then ``hit_response`` turns a hit that
    the die would have turned into a miss).  It ends when spent or at the end of the owner's next turn.
  * Settle Minor Account, Grace Repaid, Harm Returned, Karmic Exchange, Grace Shelters and Reversal are the compiled reactions/actions of the
    authority entries (real CP costs, ``spend_imprint`` effects, the printed dice); this module adds what the generic machinery cannot say:
    ``candidate_allowed`` (an action is offered only against a creature that carries the matching Imprint), ``reaction_subject_allowed`` and
    ``reaction_ally_allowed`` (Harm Returned's two Debts, Exchange's matching Imprint, Shelters' failed save that the die could turn, Reversal's
    natural 1 or 20 on a save), and the effects ``karma_invoke``, ``karma_relief``, ``karma_exchange``, ``karma_shelter``, ``karma_reverse``.
  * Against a monster's attack roll (a target of the reaction only, since a monster's roll passes no pre-roll hook) Karmic Exchange's Debt die
    and Reversal's natural 20 are answered after the roll from ``hit_response``: that is the printed timing.

Judgment calls (the printed text leaves them to the table or names no number):
  * Karmic Exchange on a typed fighter's roll is offered before the roll (the generic creature_d20 hook: the die is rolled and added, an ally's
    or an enemy's); the printed "after seeing the roll" is followed only for the monster attacks above.  Ability checks are offered only where
    the engine rolls them through a typed action (grapple escape, contests, wall breach), as Invoke's die is.
  * Reversal on an attack roll is answered only for a natural 20 on a monster's or fighter's attack against a typed fighter (the natural 20
    becomes a 1 and the attack misses); a Grace natural 1 into 20 for an ally's attack (a miss turned into a hit) has no hook in the sealed
    attack roll (gate2).  On saves both directions run: the natural die is swapped and the save re-read against its DC.
  * Grace Shelters has no printed range; 60 feet, like the other Karma reactions.  Its Red Thread bonus creature and Reversal's Legendary/Secret
    resistance are riders (the Red Thread network is a GM-judged oath).
  * Settle's Grace ends Grappled, else Prone; "Disadvantage on its next ability check" is a rider.
Determinism: evented engine methods only; the dice go through the engine's roller and are recorded.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .karma_imprints import DEBT, GRACE, held, spend

K = "tianxia.talent.karma."
INVOKE, SETTLE = "TAL_KARMA_INVOKE_THE_LEDGER", "TAL_KARMA_SETTLE_MINOR_ACCOUNT"
REPAID, HARM, SHELTERS = K + "grace_repaid", K + "harm_returned", K + "grace_shelters_the_innocent"
EXCHANGE, REVERSAL = K + "karmic_exchange", K + "reversal_of_due_fortune"
DIE = "condition:typed.karma_invoke."
RANGE_FT = 60  # Grace Shelters prints none; the other reactions print 60


# ---------------------------------------------------------------------------------------------------------------- small helpers
def _roll_die(engine: Any, actor: Any, sides: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _last_roll(engine: Any, creature: Any) -> tuple[str | None, dict[str, Any]]:
    """The creature's newest d20 the engine logged (a saving throw or an attack roll) and its payload."""
    for event in reversed(engine.events[-40:]):
        if event.actor_id == creature.entity_id and event.event_type in ("SAVE_ROLLED", "ATTACK_ROLLED"):
            payload = event.payload or {}
            if event.event_type == "ATTACK_ROLLED" or payload.get("dc") is not None:
                return event.event_type, payload
    return None, {}


def _decided(engine: Any, creature: Any) -> str | None:
    return (getattr(engine, "_typed_roll_outcome", None) or {}).get(creature.entity_id)


def _decide(engine: Any, creature: Any, outcome: str) -> None:
    engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), creature.entity_id: outcome}


def _hostile(reactor: Any, other: Any) -> bool:
    return reactor.team_id != other.team_id


# ------------------------------------------------------------------------------------------------------- Invoke the Ledger
def _dice(creature: Any) -> list[tuple[str, Any]]:
    return [(key, c) for key, c in creature.conditions.items() if str(c.condition_id).startswith(DIE)]


@effect("karma_invoke")
def karma_invoke(ctx: Any, eff: dict[str, Any]) -> None:
    """Typed effect {"type": "karma_invoke", "kind": "debt" | "grace", "dice_by_cl": [...]}: the target carries the user's Invoke die."""
    from factory_authoring.typed_mechanics import dice_for_cl

    from ..typed_executor import _default_subject

    kind = "grace" if str(eff.get("kind")).lower() == "grace" else "debt"
    cl = int(ctx.numbers.get("cl") or 1)
    sides = int((dice_for_cl(eff.get("dice_by_cl"), cl) or {}).get("sides") or (8 if cl >= 17 else 6 if cl >= 11 else 4))
    owner = ctx.actor
    for subject in _default_subject(ctx, eff, harmful=kind == "debt"):
        condition_id = DIE + owner.entity_id
        ctx.engine._remove_condition(subject, condition_id, ctx.source)  # only one Invoke die from you at a time
        sign = "subtract" if kind == "debt" else "add"
        ctx.engine._apply_condition(
            subject, condition_id, ctx.source, owner.entity_id, expires_on="END_OF_MARKER_NEXT_TURN",
            data={"marker_turn": int(owner.turns_started), "kind": kind, "sides": sides,
                  "label": f"Invoke the Ledger: {'-' if kind == 'debt' else '+'}1d{sides}",
                  "reading": f"{owner.display_name}'s Invoke die: {sign} 1d{sides} {'from' if kind == 'debt' else 'to'} the next attack roll, ability check or "
                             f"saving throw this creature makes, until the end of {owner.display_name}'s next turn."})
        note(ctx.engine, ctx.source, owner, f"{owner.display_name} invokes the ledger on {subject.display_name} ({NAMES_LABEL[kind]}): the next attack roll, "
                                          f"check or save takes {'-' if kind == 'debt' else '+'}1d{sides}.", (subject,))


NAMES_LABEL = {"debt": DEBT, "grace": GRACE}


def _spend_die(engine: Any, creature: Any, what: str) -> int:
    """The creature's Invoke dice, rolled and used up on the d20 it is about to make (or just made): the signed total."""
    from ..typed_executor import expire_marks

    if not any(str(c.condition_id).startswith(DIE) for c in creature.conditions.values()):
        return 0
    expire_marks(engine)
    total = 0
    for key, condition in sorted(_dice(creature), key=lambda pair: pair[1].applied_sequence):
        data = condition.data or {}
        owner = engine.state.actors.get(condition.source_actor_id or "")
        del creature.conditions[key]
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id or "karma:invoke", actor_id=condition.source_actor_id,
                             target_ids=(creature.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": key, "reason": "INVOKE_DIE_USED"})
        rolled = _roll_die(engine, creature, int(data.get("sides") or 4), "KARMA_INVOKE")
        signed = -rolled if data.get("kind") == "debt" else rolled
        total += signed
        note(engine, INVOKE, owner or creature, f"Invoke the Ledger: {creature.display_name}'s {what} takes {signed:+d} ({'Debt' if signed < 0 else 'Grace'} 1d{data.get('sides')}).", (creature,))
    return total


@hook("attack_bonus")
def die_on_attack(ctx: Any, actor: Any) -> int | None:
    return _spend_die(ctx.engine, actor, "attack roll") or None


@hook("check_bonus")
def die_on_check(ctx: Any, actor: Any) -> int | None:
    return _spend_die(ctx.engine, actor, "ability check") or None


@hook("save")
def die_on_save(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    bonus = _spend_die(ctx.engine, subject, "saving throw")
    return {"bonus": bonus} if bonus else None


@hook("event")
def die_on_roll(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """An attack roll rolled with an Invoke die still standing on its maker (a monster's roll passes no pre-roll hook): spend the die now,
    and leave the number for ``hit_response``, which can still turn the hit into a miss."""
    if event_type != "ATTACK_ROLLED":
        return
    engine._karma_die = None
    attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
    ids = tuple(kwargs.get("target_ids") or ())
    target = engine.state.actors.get(ids[0]) if ids else None
    typed = getattr(engine, "typed_actor_ids", set())
    # Only a Debt die on a hit against a typed fighter can still change something (hit_response); a typed attacker's die went in before its roll.
    if attacker is None or target is None or attacker.entity_id in typed or target.entity_id not in typed or not (kwargs.get("payload") or {}).get("provisional_hit"):
        return
    if any(str(c.condition_id).startswith(DIE) and (c.data or {}).get("kind") == "debt" for c in attacker.conditions.values()):
        engine._karma_die = (attacker.entity_id, _spend_die(engine, attacker, "attack roll"))


# ---------------------------------------------------------------------------------------------- Settle Minor Account (Grace)
@effect("karma_relief")
def karma_relief(ctx: Any, eff: dict[str, Any]) -> None:
    """Settle Minor Account's Grace: the creature "may immediately end one of ... Grappled, Prone, or Disadvantage on its next ability
    check": Grappled first, else Prone (the Disadvantage is a rider)."""
    from ..typed_executor import _default_subject

    for subject in _default_subject(ctx, eff, harmful=False):
        for name in ("grappled", "prone"):
            found = next((c.condition_id for c in subject.conditions.values() if str(c.condition_id).rsplit(".", 1)[-1] == name), None)
            if found is not None:
                ctx.engine._remove_condition(subject, found, ctx.source)
                note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name}'s Grace frees {subject.display_name} of being {name.title()}.", (subject,))
                break


# -------------------------------------------------------------------------------------------- the reactions' own conditions
def _consents_to_payment(engine: Any, reactor: Any, row: dict[str, Any], subject: Any, checkpoint: str) -> bool:
    """Ask with the generic reaction gates; the accepted branch owns payment and aftermath."""
    from .. import typed_reactions as tr

    engine._karma_post_roll = True
    try:
        if not tr._can_trigger(engine, reactor, row) or not tr._generic_affordable(engine, reactor, row) or not tr._generic_in_range(engine, reactor, subject, row):
            return False
        if not tr._subject_ok(engine, reactor, subject, row) or not tr._consent(engine, row, reactor, checkpoint):
            return False
    finally:
        engine._karma_post_roll = False
    return True


def _pay_accepted(engine: Any, reactor: Any, row: dict[str, Any], subject: Any, checkpoint: str) -> None:
    from .. import typed_reactions as tr

    tr._open(engine, row, reactor, (subject.entity_id,), checkpoint)
    tr._spend_generic(engine, reactor, row)
    if not row.get("free"):
        reactor.reaction_available = False


def _resolved(engine: Any, reactor: Any, row: dict[str, Any], subject: Any, checkpoint: str, payload: dict[str, Any]) -> None:
    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=reactor.entity_id, target_ids=(subject.entity_id,),
                         payload={"checkpoint": checkpoint, "roll": "attack", **payload})


@effect("karma_exchange")
def karma_exchange(ctx: Any, eff: dict[str, Any]) -> None:
    """Karmic Exchange, after its die was rolled and added by the generic pre-roll hook: expend the matching Imprint and note the roll as taken."""
    roller = ctx.target
    if roller is None:
        return
    kind = "debt" if _hostile(ctx.actor, roller) else "grace"
    if spend(ctx.engine, ctx.actor, roller, kind, 1, ctx.source):
        ctx.engine._karma_exchanged = {**(getattr(ctx.engine, "_karma_exchanged", None) or {}), roller.entity_id: True}
        sides = 8 if int(ctx.numbers.get("cl") or 0) >= 17 else 6  # "At CL 17, the die becomes 1d8"
        note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} exchanges a {NAMES_LABEL[kind]} on {roller.display_name}'s roll "
                                                f"({'subtracts' if kind == 'debt' else 'adds'} 1d{sides}).", (roller,))


@effect("karma_shelter")
def karma_shelter(ctx: Any, eff: dict[str, Any]) -> None:
    """Grace Shelters the Innocent: expend the Grace Imprint, add 1d6 to the failed save; if it now succeeds the creature gains Temporary HP
    equal to the user's Proficiency Bonus."""
    engine, subject = ctx.engine, ctx.target
    kind_, rolled = _last_roll(engine, subject) if subject is not None else (None, {})
    if subject is None or kind_ != "SAVE_ROLLED" or not spend(engine, ctx.actor, subject, "grace", 1, ctx.source):
        return
    die = _roll_die(engine, ctx.actor, 6, "KARMA_SHELTER")
    total, dc = int(rolled.get("total") or 0) + die, int(rolled.get("dc") or 0)
    if total >= dc:
        _decide(engine, subject, "success")
        amount = int(ctx.numbers.get("pb") or ctx.actor.proficiency_bonus)
        engine._grant_temp_hp(subject, amount, ctx.source, ctx.actor.entity_id)
        note(engine, ctx.source, ctx.actor, f"{ctx.actor.display_name}'s Grace Shelters {subject.display_name}: +{die} on the save ({total} against DC {dc}) turns it into a success, "
                                            f"and it gains {amount} Temporary HP.", (subject,))
    else:
        note(engine, ctx.source, ctx.actor, f"{ctx.actor.display_name}'s Grace Shelters {subject.display_name}: +{die} on the save ({total} against DC {dc}) is not enough.", (subject,))


@effect("karma_reverse")
def karma_reverse(ctx: Any, eff: dict[str, Any]) -> None:
    """Reversal of Due Fortune on a saving throw: a Grace Imprint turns a natural 1 into a natural 20, a Debt Imprint a natural 20 into a
    natural 1; the save is read again against its DC."""
    engine, subject = ctx.engine, ctx.target
    kind_, rolled = _last_roll(engine, subject) if subject is not None else (None, {})
    if subject is None or kind_ != "SAVE_ROLLED":
        return
    kind = "debt" if _hostile(ctx.actor, subject) else "grace"
    natural = int(rolled.get("natural_result") or 0)
    if natural != (20 if kind == "debt" else 1) or not spend(engine, ctx.actor, subject, kind, 1, ctx.source):
        return
    total = int(rolled.get("total") or 0) - natural + (1 if kind == "debt" else 20)
    dc = int(rolled.get("dc") or 0)
    _decide(engine, subject, "success" if total >= dc else "failure")
    note(engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} reverses {subject.display_name}'s natural {natural} into a {1 if kind == 'debt' else 20} "
                                        f"({NAMES_LABEL[kind]}): the save is {total} against DC {dc}, a {'success' if total >= dc else 'failure'}.", (subject,))


# ------------------------------------------------------------------------------------------------------------ the gates
def _rows(engine: Any, actor: Any, kind: str, feature: str) -> list[dict[str, Any]]:
    from .. import typed_reactions as tr

    return [row for row in tr._ordered_generic_rows(engine, actor.entity_id, kind) if row.get("feature_id") == feature]


@hook("damage_pending")
def remember_source(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str | None) -> None:
    """Who dealt the damage now being weighed: the ally reactions' hook (reaction_ally_allowed) is not given the source."""
    engine._karma_source = (target.entity_id, source_actor_id)


@hook("reaction_ally_allowed")
def ally_gate(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """Harm Returned: the creature that dealt the damage carries at least two of the reactor's Debt Imprints."""
    if row.get("feature_id") != HARM:
        return None
    source = getattr(engine, "_karma_source", None)
    dealer = engine.state.actors.get(source[1] or "") if source and source[0] == subject.entity_id else None
    return None if dealer is not None and len(held(dealer, reactor.entity_id, "debt")) >= 2 else False


@hook("reaction_subject_allowed")
def subject_gate(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool | None:
    feature = row.get("feature_id")
    if feature not in (HARM, EXCHANGE, SHELTERS, REVERSAL) or other is None:
        return None
    hostile, after_roll = _hostile(reactor, other), getattr(engine, "_karma_post_roll", False)
    if feature == HARM:
        return None if len(held(other, reactor.entity_id, "debt")) >= 2 else False
    if not held(other, reactor.entity_id, "debt" if hostile else "grace"):
        return False
    if feature == EXCHANGE:
        return False if (getattr(engine, "_karma_exchanged", None) or {}).get(other.entity_id) else None
    if after_roll:
        return None
    kind_, rolled = _last_roll(engine, other)
    if kind_ != "SAVE_ROLLED":
        return False  # an attack roll is settled from hit_response; the rest is not a roll this module can change
    total, dc, natural = int(rolled.get("total") or 0), int(rolled.get("dc") or 0), int(rolled.get("natural_result") or 0)
    if feature == SHELTERS:
        far = engine._distance_actor_to_actor(reactor, other) > RANGE_FT
        return False if hostile or far or _decided(engine, other) == "success" or total >= dc or dc - total > 6 else None
    if hostile:  # a natural 20 turned into a 1 must change a success into a failure
        return None if natural == 20 and total >= dc and total - 19 < dc and _decided(engine, other) != "failure" else False
    return None if natural == 1 and total < dc and total + 19 >= dc and _decided(engine, other) != "success" else False


@hook("turn_end")
def forget(engine: Any, actor: Any) -> None:
    engine._karma_exchanged = {}


@hook("event")
def roll_over(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A roll is over: the next one may be affected by a Karmic Exchange again."""
    if event_type in ("SAVE_ROLLED", "ATTACK_ROLLED") and getattr(engine, "_karma_exchanged", None):
        engine._karma_exchanged = {key: value for key, value in engine._karma_exchanged.items() if key != kwargs.get("actor_id")}


# ---------------------------------------------------------------------------------- answers after a monster's attack roll
@hook("hit_response")
def hit_answer(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> dict[str, Any] | None:
    """A hit on a typed fighter, answered after the roll: an Invoke die the attacker spent on it, then Reversal (a natural 20 becomes a 1)
    and Karmic Exchange's Debt die (a monster's roll passes no pre-roll hook; a typed fighter's is shaped before it is rolled)."""
    from ..paid_relocation import activation

    stash, engine._karma_die = getattr(engine, "_karma_die", None), None
    if stash and stash[0] == attacker.entity_id and stash[1]:
        total += stash[1]
        if stash[1] < 0 and natural < int(spec.get("critical_threshold", 20)) and total < effective_ac:
            return {'armor_class': effective_ac - stash[1], 'hit': False, 'miss_reason': 'armor_class'}
    if target.team_id == attacker.team_id:
        return None
    for reactor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not reactor.active or reactor.team_id == attacker.team_id or reactor.entity_id not in getattr(engine, "typed_actor_ids", set()):
            continue
        if not held(attacker, reactor.entity_id, "debt"):
            continue
        if natural == 20:
            for row in _rows(engine, reactor, "creature_nat", REVERSAL):
                if 20 in (row.get("natural") or (1, 20)) and _consents_to_payment(engine, reactor, row, attacker, "D20_NATURAL"):
                    with activation(engine, reactor, row["feature_id"]):
                        _pay_accepted(engine, reactor, row, attacker, "D20_NATURAL")
                        if not spend(engine, reactor, attacker, "debt", 1, REVERSAL):
                            continue
                        note(engine, REVERSAL, reactor, f"{reactor.display_name} reverses {attacker.display_name}'s natural 20 into a 1 (Debt Imprint): the attack misses.", (attacker,))
                        _resolved(engine, reactor, row, attacker, "D20_NATURAL", {"natural": 1})
                        return {'armor_class': effective_ac, 'hit': False,
                                'miss_reason': 'natural_replaced', 'natural_result': 1}
        elif attacker.entity_id not in getattr(engine, "typed_actor_ids", set()):
            row = next(iter(_rows(engine, reactor, "creature_d20", EXCHANGE)), None)
            die = next((e for e in (row or {}).get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack_modifier"), None)
            if row is None or die is None or (getattr(engine, "_karma_exchanged", None) or {}).get(attacker.entity_id):
                continue
            if total >= effective_ac + int((die.get("dice") or {}).get("sides") or 6) or not _consents_to_payment(engine, reactor, row, attacker, "D20_PENDING"):
                continue  # the die could not turn it into a miss, or the player passed
            with activation(engine, reactor, row["feature_id"]):
                _pay_accepted(engine, reactor, row, attacker, "D20_PENDING")
                from .. import typed_reactions as tr

                amount = tr._generic_amount(engine, reactor, row, die)
                spend(engine, reactor, attacker, "debt", 1, EXCHANGE)
                engine._karma_exchanged = {**(getattr(engine, "_karma_exchanged", None) or {}), attacker.entity_id: True}
                missed = natural < int(spec.get("critical_threshold", 20)) and total - amount < effective_ac
                note(engine, EXCHANGE, reactor, f"{reactor.display_name} exchanges a Debt Imprint on {attacker.display_name}'s attack roll: -{amount} "
                                                f"({total - amount} against AC {effective_ac}), {'a miss' if missed else 'it still hits'}.", (attacker,))
                _resolved(engine, reactor, row, attacker, "D20_PENDING", {"bonus": -amount})
                if missed:
                    return {'armor_class': effective_ac + amount, 'hit': False, 'miss_reason': 'armor_class'}
    return None


# --------------------------------------------------------------------------------------------- what the menu offers
@hook("candidate_allowed")
def offer(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Invoke the Ledger and Settle Minor Account: only against a creature carrying the matching Imprint of the user's (Invoke: with no Invoke
    die of the user's on it already)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    feature = typed.get("option_of") or typed.get("source")
    if feature not in (INVOKE, SETTLE):
        return None
    label = str(typed.get("option_label") or "").lower()
    kind = "debt" if label.startswith("debt") else "grace" if label.startswith("grace") else None
    ids = list(getattr(candidate, "target_ids", None) or ())
    target = engine.state.actors.get(ids[0]) if ids else None
    if kind is None or target is None:
        return None
    if not held(target, actor.entity_id, kind):
        return False
    if feature == INVOKE and any(c.source_actor_id == actor.entity_id for _, c in _dice(target)):
        return False
    return None
