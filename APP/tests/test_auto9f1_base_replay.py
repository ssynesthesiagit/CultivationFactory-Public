"""Opt-in paired baseline/tip AI comparison for the Alchemy lane; never reads live fights.

Set ``AUTO9F1_BASE_REPLAY`` to a task-owned folder holding four captures taken with
``tests/auto9f1_replay_evidence.py``, two in the pre-lane checkout and two in this one::

    <root>/base-control/  <root>/tip-control/      a fighter fight this lane does not touch
    <root>/base-alchemy/  <root>/tip-alchemy/      the Alchemist, every printed effect this lane changed

Both sides are played through the real table from the same seed **by the same capture script**, so the
transactions line up one for one. The alchemy pair is *meant* to differ; this test names every difference
it accepts and **fails on any difference it cannot name**, so an unintended payload field, saved value or
whole event cannot be waved through by not being listed.

What "named" means is :data:`INTENT`: each intent is one printed rule this lane changed, with the event
fields it is allowed to move. A difference is accepted only when *every* changed field of *every* event
in it, and every saved value that moved, is claimed by one of those intents **and** every claim is
inside its own bound -- whose record it is, who acted, at whom, from what, which way, by how much and with
which complete contents. Anything else is reported with the exact before/after values and fails.
"""
import json
import re
import os
from pathlib import Path
from typing import Mapping, NamedTuple

import pytest

from tests.auto9f1_replay_evidence import (ALCHEMIST, BINDING_DREGS, DASH_CLAUSE, SEVEN_FLAVOR,
                                           VOLATILE_EVENT_FIELDS, UnreadableSavedHistory, journal_sha256,
                                           journal_differences, mechanic, settled_clauses)

#: The conditions this lane may leave on a creature that the baseline never gave it: the sealed
#: Seven-Flavor preparation (finding 4) and Binding Dregs' solid-surface Dash clause, now settled as a
#: real condition when the save resolves (finding 5).
INTENDED_CONDITIONS = {"condition:typed.seven_flavor_types", "condition:typed.no_dash"}

#: Every GM reminder the tip stops printing, keyed by the exact opening the baseline printed and the
#: intent that claims it. A rider change is claimable only through one of these: there is no "the
#: reminder was reworded" escape hatch, so a rewrite nobody named cannot pass.
RETIRED_RIDERS = {
    "If the target is standing on a solid surface, it also cannot take the Dash action": "settled_dash_clause",
    "GM: once-per-turn Field Formula CP discount requires a pre-cost seam in the locked engine.":
        "withdrawn_engine_note",
    "GM: Select only a learned formula and a prepared pill;": "withdrawn_engine_note",
    "The area is not a wall and does not provide cover.": "withdrawn_printed_line",
}

#: The resource whose printed "Cost: 1 CP" the baseline charged twice for Furnace Vent (AUTO9's own
#: finding): the tip spends it once, so its remainder is never lower and never more than one higher.
STAMINA = "resource:core.stamina"

#: How far a pool may move under :data:`INTENT`'s ``printed_cost_once``: the one CP the baseline
#: charged a second time. A refund of any other size is somebody else's rule, so it is not claimed here.
PRINTED_CP = 1

#: The expiry each of this lane's own conditions is printed to end on. A lone condition event, or a
#: saved condition, that ends anywhere else is a duration nobody named.
PRINTED_EXPIRY = {"sealed_preparation": "UNTIL_REMOVED", "settled_dash_clause": "START_OF_SOURCE_NEXT_TURN"}

#: The damage types Seven-Flavor Furnace's printed Long Rest question offers, in its own words, so a
#: saved preparation recording anything else is not a value the printed rule can hold.
PREPARABLE_TYPES = frozenset({"acid", "cold", "fire", "lightning", "necrotic", "poison", "radiant", "thunder"})
#: The printed heading of the talent the preparation is remembered for, from its own rules text
#: (``authority/typed_mechanics/rules_text.json``, ``### Seven-Flavor Furnace - Volatile``).
SEVEN_FLAVOR_PRINTED = "Seven-Flavor Furnace"


def _printed_types(value):
    """A sealed preparation states which of the printed types it sealed, as one non-empty '|'-joined string."""
    parts = [part for part in str(value or "").split("|") if part]
    return bool(parts) and all(part in PREPARABLE_TYPES for part in parts)


def _preparation_label(value):
    """The condition pill names the printed talent that put the preparation there, so a label that does not
    is not the one the rule wrote. Only the printed heading is required, so player-facing wording may
    change; ``SEVEN_FLAVOR_PRINTED`` is that heading from the talent's own rules text."""
    return SEVEN_FLAVOR_PRINTED in str(value or "")


#: The **complete** data each of this lane's own conditions must record, each value checked by the named
#: predicate beside it. The sealed preparation records the types it sealed and the pill that says so; the
#: settled Dash clause is applied and lifted inside one turn, so it records nothing at all. A subset is
#: never enough: an added key is somebody else's value riding in on a claim (AUTO9r3 review, finding 2).
INTENDED_CONDITION_DATA = {"sealed_preparation": {"types": _printed_types, "label": _preparation_label},
                           "settled_dash_clause": {}}

#: The only payload fields a lone condition event may carry beside its condition id, so an inserted
#: ``CONDITION_APPLIED`` cannot smuggle in a data change the printed rule never had.
CONDITION_PAYLOAD_FIELDS = {"CONDITION_APPLIED": {"condition_id", "expires_on"},
                            "CONDITION_REMOVED": {"condition_id", "checkpoint"}}

#: The owner of these printed rules in the fixture fights below, and the creature that owns nothing this
#: lane printed. A claim has to be the *owner's* record: the review's counterexample is an unrelated
#: fighter's unrelated attack changing type, which no envelope difference would notice.
OWNER, FOREIGN = "actor:factory.1", "actor:factory.2"
#: The printed abilities the capture's own Alchemist was actually given (``ALCHEMIST`` in the evidence
#: harness, which builds the sheet), so a claim has to come from one of the owner's own formulae. A
#: compiled action's journal id carries a per-character prefix and an option suffix
#: (``action:typed.ecf05feaca.TAL_ALCHEMY_POISON_PILL#opt2``); both are stripped so the id reads as the
#: printed mechanic it is.
OWNED_SOURCES = frozenset(ALCHEMIST)
#: The one printed ability whose own rules text carries the Dash clause ("If the target is standing on a
#: solid surface, it also cannot take the Dash action"), so it is the only one that may settle it. Being
#: one of the owner's formulae is not enough: Furnace Vent is one too and prints no such clause
#: (AUTO9r4 review, finding 1). Named once by the evidence harness, which is the code that has to roll
#: saves against it, so the two cannot drift apart.
#: The system lifting a duration the printed rule named. The one source here that is not one of the
#: owner's formulae, and only ever a condition *removal*.
EXPIRATION_SOURCE = "system:combat.expiration"

#: Every difference this lane intends: the intent name, the printed rule it comes from, the exact
#: reminder openings or conditions or resources it is allowed to move, and the bound on each. Nothing
#: else is acceptable -- an intent names a rule, not a whole class of change.
INTENT = {
    "sealed_preparation":
        'Seven-Flavor Furnace\'s "choose up to three damage types" is a decision once per Long Rest, so the '
        "answer is remembered as the owner's own condition, which appears and nothing else moves (finding 4). "
        f"It is claimed only as a *gained* condition on the owner, applied by the owner's own talent to the "
        f"owner, ending at {PRINTED_EXPIRY['sealed_preparation']} and recording exactly the printed types and "
        "the pill that names this talent.",
    "prepared_damage_type":
        '"you may choose one of your selected damage types instead" is a choice between two sets, so the '
        "prepared type replaces the printed one on a damage roll and only on that field (finding 1). It is "
        "claimed only on the owner's own record, from one of the owner's own Alchemy formulae, at a creature, "
        "and only for a type the owner's own saved preparation prepared.",
    "printed_cost_once":
        'Furnace Vent\'s printed "Cost: 1 CP and one Reagent Stock" was charged twice; the tip charges it '
        f"once, so exactly the printed {PRINTED_CP} CP stops being spent and no pool ever ends lower, "
        f"further or differently -- and only on the owner's own Alchemy formulae.",
    "settled_dash_clause":
        '"If the target is standing on a solid surface, it also cannot take the Dash action" is settled when '
        f"the save resolves instead of printed as a reminder, from Binding Dregs -- the one printed ability "
        f"that clause belongs to, and no other formula this Alchemist owns -- on the creature that failed "
        f"the save against it, never on the caster, ending at the printed "
        f"{PRINTED_EXPIRY['settled_dash_clause']} (finding 5), and recording nothing else.",
    "withdrawn_engine_note":
        "The reminder named the build (a locked engine, a seam, an interpreter); the tip prints the rule "
        "in words a player can act on instead (checklist 13).",
    "withdrawn_printed_line":
        "A printed line that now sits in the ability's own text stops being repeated mid-fight.",
}


class Intended(NamedTuple):
    """Whose record this lane's printed rules are allowed to change, and what they may change it to.

    Read out of the capture itself (:func:`intended`) rather than typed in: the owner is the creature the
    tip's own saved preparation sits on, the prepared types are what that preparation records, and the
    creatures that may carry the Dash clause are the ones the fight's own rolled saves say failed it --
    so a claim is checked against the fight that produced it.

    ``lifecycles`` keeps that one step finer for the journal half: per side, every
    ``(transaction, creature)`` where Binding Dregs' clause settled on that creature **in the transaction
    that rolled its failed save**. A creature that failed once and passed a later save has a lifecycle only
    in the transaction that rolled its failure, so a clause applied during the successful cast has nothing
    to point at (AUTO9r5 review, finding 1).
    ``removals`` names the exact (transaction, creature, event index) of each removal that consumed
    an active lifetime at the recorded start of the caster's next turn.
    """

    owner: str
    prepared: frozenset
    dashed: frozenset = frozenset()
    lifecycles: Mapping = {}
    removals: Mapping = {}


def match_of(name):
    return next((Path(os.environ["AUTO9F1_BASE_REPLAY"]) / name).glob("Combat/Matches/*"))


def _failed_against(result, mechanic) -> frozenset:
    """The creatures that failed a save made against one printed ability, as **both** captures rolled it.

    Binding Dregs' Dash clause only settles when its save fails, so the creature that may carry it is
    the creature that rolled the failed save -- not any creature at all, and not the Alchemist who cast
    it. Both sides have to agree: *which* creature failed is itself a fact a behaviour change could move,
    and a disagreement is a difference nobody named, so nothing is claimed rather than absorbing it.
    """
    sides = {side: sorted(event["actor_id"] for event in (result.get("save_failures") or {}).get(side) or []
                         if _source_of(event) == mechanic)
             for side in ("baseline", "tip")}
    return frozenset(sides["tip"]) if sides["baseline"] == sides["tip"] else frozenset()


def intended(result) -> Intended:
    """The owner, the prepared types and the Dash clause's own lifecycle, read from the captures themselves.

    The preparation's saved key names the creature it is on, so the owner is the fight's own statement of
    who owns Seven-Flavor Furnace rather than a name this test made up; the Dash clause's carrier comes
    from the saves the same fight rolled against Binding Dregs, and its lifecycle from where that clause
    was settled against those saves.
    """
    owner, types = "", set()
    for actor_id, facts in (result.get("state", {}).get("actors", {}) or {}).get("tip", {}).items():
        for key, condition in facts["conditions"].items():
            if _instance_condition_id(key) != "condition:typed.seven_flavor_types":
                continue
            owner = owner or actor_id
            types |= {part for part in str((condition.get("data") or {}).get("types") or "").split("|") if part}
    lifecycles = {side: frozenset(map(tuple, (result.get("dash_lifecycles") or {}).get(side, {}).get("settled") or ()))
                  for side in ("baseline", "tip")}
    removals = {side: frozenset(map(tuple, (result.get("dash_lifecycles") or {}).get(side, {}).get("removed") or ()))
                for side in ("baseline", "tip")}
    return Intended(owner, frozenset(types), _failed_against(result, BINDING_DREGS), lifecycles, removals)


def _source_of(event) -> str:
    """The printed mechanic a journal event's source id names, prefix and option suffix removed."""
    return mechanic(event.get("source_definition_id"))


def _own_print(event, intended) -> bool:
    """Whether the event is one of the owner's own printed Alchemy formulae acting, by the owner."""
    return event.get("actor_id") == intended.owner and _source_of(event) in OWNED_SOURCES


def _retired_intent(text):
    """The intent claiming a reminder that stopped printing, or None when no printed rule explains it."""
    head = next((head for head in RETIRED_RIDERS if str(text).startswith(head)), None)
    return RETIRED_RIDERS[head] if head else None


def _condition_intent(condition_id):
    return "sealed_preparation" if condition_id == "condition:typed.seven_flavor_types" \
        else "settled_dash_clause" if condition_id == "condition:typed.no_dash" else None


#: A saved condition's key is "condition-instance:<condition id>:<actor id>", with the creating event
#: sequence already stripped; the condition id is what names the rule.
_CONDITION_IN_INSTANCE = re.compile(r"^condition-instance:(?P<condition_id>.+):actor:")


def _instance_condition_id(key):
    """The condition id inside a saved condition's key, or an empty string when the key is not one."""
    found = _CONDITION_IN_INSTANCE.match(key)
    return found.group("condition_id") if found else ""


#: The creature at the tail of a saved condition's key, so a claimed condition can be required to sit on
#: the owner whose printed rule put it there.
_INSTANCE_OWNER = re.compile(r":(?P<owner>actor:[^:]+)$")


def _instance_owner(key):
    """The creature a saved condition's key belongs to, or an empty string when the key is not one."""
    found = _INSTANCE_OWNER.search(key)
    return found.group("owner") if found else ""


def _envelope(event):
    """Everything about one event except its payload: its kind, who acted, at whom, and from what.

    Compared whole, so an event cannot change who it hit or which ability produced it while riding in
    on an allowed payload field.
    """
    envelope = {name: value for name, value in event.items()
                if name not in VOLATILE_EVENT_FIELDS and name != "payload"}
    return {name: sorted(value) if name == "target_ids" else value for name, value in envelope.items()}


def _who(event):
    """Who acted, at whom, and from what: an event's envelope without its kind or its payload."""
    return {name: value for name, value in _envelope(event).items() if name != "event_type"}


def _changed_fields(before, after):
    return {key for key in set(before.get("payload") or {}) | set(after.get("payload") or {})
            if (before.get("payload") or {}).get(key) != (after.get("payload") or {}).get(key)}


def _substitution(before, intended) -> bool:
    """Whether the printed substitution is what moved this damage: the owner's own Alchemy formula, out of
    one of its own abilities, at a creature.

    The type the row already offered is deliberately *not* required to be one of Acid, Fire, Poison or
    Force. A compiled option lists the substituted set beside its own type, so the Rotting Pill in the
    retained capture replaces a Necrotic this way; requiring the printed type to be in the substituted set
    would reject the lane's own fight (AUTO9r3, finding 2).
    """
    return _own_print(before, intended) and bool(before.get("target_ids"))


def _field_claims(before, after, intended):
    """(fields claimed, intents) for one event pair. Every changed field must be claimed and bounded."""
    claimed, claims = set(), set()
    for key in _changed_fields(before, after):
        was, now = (before.get("payload") or {}).get(key), (after.get("payload") or {}).get(key)
        intent = None
        if key == "damage_type" and before["event_type"] == "DAMAGE_COMMITTED":
            # The printed talent substitutes a type the owner prepared, on this field only: every other
            # field of the same event (the amount, what survived, what is left of the target) must
            # match, or the strict per-field pass rejects the pair. It has to be the owner's own formula
            # changing a type that owner's own saved preparation prepared.
            intent = "prepared_damage_type" \
                if str(now).lower() in intended.prepared and str(was) != str(now) \
                and _substitution(before, intended) else None
        elif key == "remaining" and before["event_type"] == "RESOURCE_SPENT" \
                and before["payload"].get("resource_id") == STAMINA:
            # The tip stops charging Furnace Vent's printed 1 CP twice, so the pool can only end
            # exactly one point higher than the baseline left it: never lower, never more -- and only on
            # the owner's own formulae.
            intent = "printed_cost_once" if isinstance(was, int) and isinstance(now, int) \
                and now - was == PRINTED_CP and _own_print(before, intended) else None
        elif key == "rider" and before["event_type"] == "GM_RIDER":
            intent = _retired_intent(was) if _own_print(before, intended) else None
        if intent:
            claimed.add(key)
            claims.add(intent)
    return claimed, claims


def _settled_there(event, side, transaction, intended) -> bool:
    """Whether the Dash clause settled on this very creature's own failed save, in this very transaction.

    The clause is Binding Dregs' own printed rider, so only the ability that prints it may settle it --
    another one of the owner's formulae prints no such clause -- and only on a creature whose save against
    *that* ability the fight rolled as failed **in the transaction that settled it**. The save resolves
    before the clause does, so they are one transaction: a creature that failed once and passed a later
    save has no clause to settle in the later cast, and an application there has nothing to point at.
    """
    if event.get("actor_id") != intended.owner or _source_of(event) != BINDING_DREGS:
        return False
    targets = {str(target) for target in (event.get("target_ids") or [])}
    lifecycle = (intended.lifecycles or {}).get(side) or frozenset()
    return bool(targets) and set(targets) <= intended.dashed \
        and all((transaction, target) in lifecycle for target in targets)


def _lifted_from(event, side, transaction, intended, event_index) -> bool:
    """Whether the system lifted the clause from a creature that was actually carrying it.

    The harness reports only removals that consumed an active lifetime at the caster's next turn.
    Match their exact event coordinates; an earlier application alone cannot authorize a removal.
    """
    targets = {str(target) for target in (event.get("target_ids") or [])}
    removals = (intended.removals or {}).get(side) or frozenset()
    return bool(targets) and all((transaction, target, event_index) in removals for target in targets)


def _placed_as(event, intent, intended, side, transaction, event_index=None) -> bool:
    """Whether this condition event is where the printed rule says the condition goes: the owner, the
    right source, at the right creature, off the save that actually earned it.
    """
    targets = [str(target) for target in (event.get("target_ids") or [])]
    if intent == "sealed_preparation":
        # "When you finish a Long Rest, choose up to three damage types": the answer is remembered on the
        # owner's own condition, so the owner's own talent puts it on the owner and on nobody else. It is
        # not settled by a save, so there is no failed save to bind it to.
        return event.get("actor_id") == intended.owner and _source_of(event) == SEVEN_FLAVOR \
            and targets == [intended.owner]
    return _settled_there(event, side, transaction, intended) \
        if event["event_type"] == "CONDITION_APPLIED" \
        else event.get("actor_id") == intended.owner and _source_of(event) == EXPIRATION_SOURCE \
        and _lifted_from(event, side, transaction, intended, event_index)


def _condition_event_claim(event, intended, side, transaction, event_index=None):
    """The intent claiming one condition event, bounded by the owner, the source, the creature, the printed
    expiry, the printed contents and -- for a clause that settles on a failed save -- that save."""
    payload = event.get("payload") or {}
    kind = event["event_type"]
    intent = _condition_intent(payload.get("condition_id"))
    if intent is None or set(payload) - CONDITION_PAYLOAD_FIELDS.get(kind, set()):
        return None
    if kind == "CONDITION_APPLIED" and payload.get("expires_on") != PRINTED_EXPIRY[intent]:
        return None
    if not _placed_as(event, intent, intended, side, transaction, event_index):
        return None
    return intent



def _saved_on(key, intent, actor_id, intended) -> bool:
    """Whether the creature a saved condition's key names is the one its printed rule puts it on.

    ``actor_id`` is the creature whose record the condition was read out of. A saved condition's key
    names the creature it sits on, so a key naming a *different* creature than the record holding it is a
    misfiled condition, not a placement that happens to be right -- and it is rejected here as well, or
    a foe-suffixed key parked in the caster's own record would pass as a correctly persisted restriction
    on that foe (AUTO9r5 review, finding 2).

    The two rules of this lane place their condition on different creatures. The preparation is the
    Alchemist's own answer to its own Long Rest question, so it is remembered on the Alchemist. The Dash
    clause is the *target's* burden -- "the target ... cannot take the Dash action" -- so it belongs on
    the creature whose save failed, which is the creature the fight's own journal rolled it on and never
    on the caster. Holding both to the owner would reject a correct fight that ended before the clause
    lifted, and accept an empty one the caster inflicted on themselves (AUTO9r4 review, finding 2).
    """
    holder = _instance_owner(key)
    if not holder or holder != actor_id:
        return False
    return holder == intended.owner if intent == "sealed_preparation" else holder in intended.dashed


def _condition_saved_claim(key, before, after, actor_id, intended):
    """The intent claiming one saved condition that moved; None for anything but a gained, printed one.

    A condition the baseline already had and the tip changed is never claimed here: rewriting a live
    condition's data or duration is a behaviour change somebody has to name, not a knock-on. A *gained* one
    has to sit on the creature its own printed rule places it on (:func:`_saved_on`), end at the printed
    expiry, and record **exactly** the printed contents -- every key and every value, not a subset
    (AUTO9r3 review, finding 2).
    """
    if before is not None or after is None:
        return None
    intent = _condition_intent(_instance_condition_id(key))
    if intent is None or (after or {}).get("expires_on") != PRINTED_EXPIRY[intent]:
        return None
    if not _saved_on(key, intent, actor_id, intended):
        return None
    data = (after or {}).get("data") or {}
    if set(data) != set(INTENDED_CONDITION_DATA[intent]):
        return None
    if not all(printed(data[name]) for name, printed in INTENDED_CONDITION_DATA[intent].items()):
        return None
    return intent


def _lone_claim(event, side, intended, transaction, event_index=None):
    """(intents, named) for one event that is on one side of the difference only.

    ``named`` is False when no printed rule of this lane explains the event at all, which rejects the
    whole edit: an event nobody named can never ride in beside one that is. A named rule is still only
    claimed on the owner's own record, from the owner's own formulae, and a clause that settles on a
    failed save is claimed only against the save rolled in this very transaction.
    """
    payload = event.get("payload") or {}
    kind = event["event_type"]
    if kind in CONDITION_PAYLOAD_FIELDS:
        intent = _condition_event_claim(event, intended, side, transaction, event_index)
        return ({intent}, True) if intent else (set(), False)
    if kind == "GM_RIDER":
        intent = _retired_intent(payload.get("rider")) if _own_print(event, intended) else None
        return ({intent}, True) if intent else (set(), False)
    if kind == "RESOURCE_SPENT" and payload.get("resource_id") == STAMINA:
        # Only the baseline's *extra* charge for the printed one CP may disappear. A spend on the tip's
        # side means this lane took more of the printed pool than the printed cost allows.
        return ({"printed_cost_once"}, True) \
            if side == "baseline" and payload.get("amount") == PRINTED_CP \
            and _own_print(event, intended) else (set(), False)
    return set(), False


def classify(edit, intended):
    """The intents claiming one minimal event difference; empty when any part of it is unclaimed.

    Strict per field, per envelope *and* per owner: a pair of events whose payload difference is explained
    still fails if one payload field moved for a reason nobody named, if the event now names a different
    creature, target or source, or if the whole event belongs to somebody other than the owner of the
    printed rule. An edit with events on one side only is accepted only when *every* one of those events
    is a named rule's own record.
    """
    claims = set()
    transactions = {"baseline": edit.get("baseline_transaction"), "tip": edit.get("tip_transaction")}
    if not edit["baseline"] or not edit["tip"]:
        for side in ("baseline", "tip"):
            indices = edit.get(f"{side}_event_indices") or [None] * len(edit[side])
            if len(indices) != len(edit[side]):
                return set()
            for event, index in zip(edit[side] or [], indices):
                got, named = _lone_claim(event, side, intended, transactions[side], index)
                if not named:
                    return set()
                claims |= got
        return claims
    if len(edit["baseline"]) != len(edit["tip"]):
        return set()
    for before, after in zip(edit["baseline"], edit["tip"]):
        if before["event_type"] != after["event_type"]:
            # A different kind of event on each side: only the Dash clause does this, where the reminder
            # that used to describe the clause is now a real condition. It is the same creature, at the
            # same target, from the same ability, and the condition is the printed one -- settled by the
            # tip transaction's own failed save, like every other application of it.
            retired = _retired_intent((before.get("payload") or {}).get("rider")) \
                if before["event_type"] == "GM_RIDER" and _own_print(before, intended) else None
            intent = _condition_event_claim(after, intended, "tip", transactions["tip"]) \
                if after["event_type"] == "CONDITION_APPLIED" else None
            if not retired or intent != retired or _who(before) != _who(after):
                return set()
            claims.add(retired)
            continue
        if _envelope(before) != _envelope(after):
            return set()
        claimed, got = _field_claims(before, after, intended)
        if claimed != _changed_fields(before, after):
            return set()
        claims |= got
    return claims


def classify_state(result, intended):
    """The intents claiming every saved value that moved; empty when any of them is unclaimed.

    The saved half is read from the state the final committed record rebuilds to, so it is the fight as
    the loader hands it back and not a periodic snapshot. A pool may only move the documented one point
    in the documented direction and a named condition may only be *gained* on the creature its own
    printed rule places it on, ending at the printed expiry and recording the complete printed contents;
    a hit point total, a square, an area or a live condition changing is never claimed here.

    ``actor_id`` is passed on to the condition check because the loader stores each condition inside the
    record of the creature it is on: a condition is only claimed when the creature its key names is the
    very record being read (AUTO9r5 review, finding 2).
    """
    claims = set()
    for key, moved in result["state"].items():
        if key != "actors":
            return set()  # whose turn, the round, or an area's square or damage types moved: name it first
        baseline, tip = moved["baseline"], moved["tip"]
        for actor_id in sorted(set(baseline) | set(tip)):
            was, now = baseline.get(actor_id, {}), tip.get(actor_id, {})
            for field in ("current_hp", "temporary_hp", "position"):
                if was.get(field) != now.get(field):
                    return set()
            for pool in sorted(set(was.get("resources") or {}) | set(now.get("resources") or {})):
                left, right = (was.get("resources") or {}).get(pool), (now.get("resources") or {}).get(pool)
                if left == right:
                    continue
                if pool == STAMINA and isinstance(left, int) and isinstance(right, int) \
                        and right - left == PRINTED_CP:
                    claims.add("printed_cost_once")
                else:
                    return set()
            for key_id in sorted(set(was.get("conditions") or {}) | set(now.get("conditions") or {})):
                left = (was.get("conditions") or {}).get(key_id)
                right = (now.get("conditions") or {}).get(key_id)
                if left == right:
                    continue
                claim = _condition_saved_claim(key_id, left, right, actor_id, intended)
                if not claim:
                    return set()
                claims.add(claim)
    return claims


#: The fixture fight's own printed source: one of the abilities the capture's Alchemist was given, with the
#: per-character prefix and option suffix a real journal id carries. Every case below starts from the owner
#: acting with one of its own formulae at another creature, so a case is rejected for the bound it is
#: about and not by accident.
PRINTED_SOURCE = "action:typed.fixture.TAL_ALCHEMY_FURNACE_VENT"


def _event(event_type, payload, **extra):
    return {"actor_id": OWNER, "event_type": event_type, "payload": payload,
            "source_definition_id": PRINTED_SOURCE, "target_ids": [FOREIGN], **extra}


#: The insertion this lane's own fight really makes: the sealed preparation, on the owner, for the rest,
#: applied by the owner's own talent to the owner.
PREPARED = {"condition_id": "condition:typed.seven_flavor_types", "expires_on": "UNTIL_REMOVED"}
#: The Dash clause the tip settles as a real condition instead of printing a reminder.
DASH = {"condition_id": "condition:typed.no_dash", "expires_on": "START_OF_SOURCE_NEXT_TURN"}


#: A preparation applied by the owner's own talent to the owner, which is what the real fight records.
OWN_PREPARATION = {"source_definition_id": SEVEN_FLAVOR, "target_ids": [OWNER]}
#: A condition the owner's own formula put on a creature that failed a save, as Binding Dregs does: the
#: one printed ability whose text carries the Dash clause, aimed at the creature whose save it lost.
DASH_SOURCE = f"action:typed.fixture.{BINDING_DREGS}"
OWN_DASH = {"source_definition_id": DASH_SOURCE, "target_ids": [FOREIGN]}
#: A creature that rolled no save against Binding Dregs, so no printed clause of that ability settles on
#: it however the Alchemist casts -- neither the caster nor a bystander the same fight happens to hold.
OTHER = "actor:factory.3"

#: The record the fixture fight's failed save was rolled in, and the one the clause settled in. One
#: sequence for the whole fixture fight, so a case is rejected for the bound it names rather than for
#: which record it happened to sit in; a case that is about the lifecycle gives its own sequences.
LIFECYCLE = 7


#: Stamp every edit with the record it was committed in, so an application can be bound to the save that
#: settled it. An edit that names its own ``*_transaction`` keeps it -- that is how the
#: earlier-failure/later-success case pins a different record for the same creature.
def _transacted(cases, sequence=LIFECYCLE):
    """Stamp each case's edit with the record it was committed in, so an application can be bound to the
    save that settled it.

    A case that names its own ``*_transaction`` keeps it -- that is how the earlier-failure/later-success
    case pins a different record for the same creature. A case may be a bare edit or an ``(edit, why)``
    pair, so the same helper stamps both lists.
    """
    for case in cases:
        edit = case[0] if isinstance(case, tuple) else case
        edit.setdefault("baseline_transaction", sequence)
        edit.setdefault("tip_transaction", sequence)
        for side in ("baseline", "tip"):
            edit.setdefault(f"{side}_event_indices", list(range(len(edit[side]))))
    return cases


#: The owner the fixtures' creatures are, as a classifier sees it: this Alchemist owns the printed rules
#: and prepared Acid, and the Dash clause's failed save landed on ``FOREIGN`` in record ``LIFECYCLE`` -- so
#: ``FOREIGN`` may carry it there and neither ``OWNER`` nor ``OTHER`` may. One record for both halves, so
#: the journal cases and the saved-state cases cannot drift apart and start describing different fights.
OWNER_INTENDED = Intended(OWNER, frozenset({"acid"}), frozenset({FOREIGN}),
                          {"baseline": frozenset({(LIFECYCLE, FOREIGN)}),
                           "tip": frozenset({(LIFECYCLE, FOREIGN)})},
                          {"tip": frozenset({(LIFECYCLE, FOREIGN, 0)})})


@pytest.mark.parametrize("edit,why", _transacted([
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID", "hp_damage": 9})],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID", "hp_damage": 10})]},
     "a damage amount moved"),
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"})],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "THUNDER"})]},
     "a damage type that was never prepared"),
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON", "hp_damage": 9})],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID", "hp_damage": 9},
                     target_ids=["actor:factory.3"])]},
     "the prepared damage type was aimed at another creature"),
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON"})],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"}, actor_id="actor:factory.3")]},
     "the prepared damage type was dealt by another creature"),
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON"})],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"}, source_definition_id="action:typed.other")]},
     "the prepared damage type came from another ability"),
    # The review's own counterexample: one envelope, both sides, and a type the owner prepared -- but it is
    # another fighter's own attack, so no envelope difference exists to notice.
    ({"kind": "replace",
      "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON"}, actor_id=FOREIGN, target_ids=[OWNER])],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"}, actor_id=FOREIGN, target_ids=[OWNER])]},
     "another creature's own damage changed to a type the owner prepared"),
    ({"kind": "replace",
      "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON"},
                          source_definition_id="action:typed.fixture.TAL_ALCHEMY_CHOKING_SMOKE_PELLET")],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"},
                     source_definition_id="action:typed.fixture.TAL_ALCHEMY_CHOKING_SMOKE_PELLET")]},
     "a prepared type came from a formula this Alchemist was not given"),
    ({"kind": "replace", "baseline": [_event("DAMAGE_COMMITTED", {"damage_type": "POISON"}, target_ids=[])],
      "tip": [_event("DAMAGE_COMMITTED", {"damage_type": "ACID"}, target_ids=[])]},
     "the prepared damage type reached no creature"),
    ({"kind": "replace", "baseline": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 20})],
      "tip": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 19})]},
     "the tip spent more of the printed pool than the baseline did"),
    ({"kind": "replace", "baseline": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 20})],
      "tip": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 22})]},
     "the printed pool was given back more than the printed one CP"),
    ({"kind": "replace",
      "baseline": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 20}, actor_id=FOREIGN)],
      "tip": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "remaining": 21}, actor_id=FOREIGN)]},
     "another creature's own pool was given back the printed one CP"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "amount": 1, "remaining": 20})]},
     "the tip spent the printed pool where the baseline did not"),
    ({"kind": "delete", "baseline": [_event("RESOURCE_SPENT", {"resource_id": STAMINA, "amount": 2,
                                                               "remaining": 20})], "tip": []},
     "more than the printed one CP stopped being spent"),
    ({"kind": "replace", "baseline": [_event("RESOURCE_SPENT", {"resource_id": "resource:named.reagent_stock",
                                                                 "remaining": 4})],
      "tip": [_event("RESOURCE_SPENT", {"resource_id": "resource:named.reagent_stock", "remaining": 3})]},
     "another pool's remainder moved"),
    ({"kind": "replace", "baseline": [_event("GM_RIDER", {"rider": "Aca demic: something happened."})],
      "tip": [_event("GM_RIDER", {"rider": "Aca demic: something else happened."})]},
     "a reminder was reworded with no named rule behind it"),
    ({"kind": "replace",
      "baseline": [_event("GM_RIDER", {"rider": "If the target is standing on a solid surface, it also "
                                                    "cannot take the Dash action"}, actor_id=FOREIGN)],
      "tip": [_event("GM_RIDER", {"rider": "Aca demic: something else happened."}, actor_id=FOREIGN)]},
     "another creature stopped printing a reminder this lane withdrew"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", {"condition_id": "condition:core.blessed"})]},
     "a condition this lane never prints appeared"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("PASSIVE_TRIGGERED", {"trigger": "Seven-Flavor Furnace"})]},
     "an event of a kind nothing here names appeared"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", PREPARED, **OWN_PREPARATION),
              _event("PASSIVE_TRIGGERED", {"trigger": "Seven-Flavor Furnace"}, **OWN_PREPARATION)]},
     "an unnamed event rode in beside the expected preparation"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", {"condition_id": "condition:typed.no_dash",
                                           "expires_on": "UNTIL_REMOVED"}, **OWN_DASH)]},
     "the settled Dash clause was left on a duration nobody printed"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", {**PREPARED, "data": {"types": "acid"}}, **OWN_PREPARATION)]},
     "the sealed preparation carried a data change the event never had"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", PREPARED, source_definition_id=SEVEN_FLAVOR, target_ids=[FOREIGN])]},
     "the preparation was remembered on a creature instead of on the owner"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", PREPARED, source_definition_id=SEVEN_FLAVOR, actor_id=FOREIGN,
                     target_ids=[FOREIGN])]},
     "the preparation was remembered by a creature that does not own the talent"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", PREPARED,
                     source_definition_id="action:typed.fixture.TAL_ALCHEMY_FURNACE_VENT",
                     target_ids=[OWNER])]},
     "the preparation was remembered by a formula instead of by the talent that owns it"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", DASH, source_definition_id=DASH_SOURCE,
                     actor_id=FOREIGN, target_ids=[FOREIGN])]},
     "the settled Dash clause was applied by another creature"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", DASH, source_definition_id=DASH_SOURCE,
                     target_ids=[])]},
     "the settled Dash clause landed on no creature"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_REMOVED", {"condition_id": "condition:typed.no_dash",
                                           "checkpoint": "START_OF_TURN"},
                     source_definition_id="action:typed.fixture.TAL_ALCHEMY_ANTIDOTE_PILL")]},
     "the settled Dash clause was lifted by a formula this Alchemist was not given"),
    # The review's bounds (AUTO9r4, finding 1). The cases above only ever reach a creature or an ability
    # that is *not* the owner's, so they pass before any source or target bound exists; each of these
    # keeps the actor and the ability the owner's own, which is what made the earlier bound too wide.
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", DASH)]},
     "another formula this Alchemist owns settled the Dash clause it prints no clause for"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", DASH, source_definition_id=DASH_SOURCE, target_ids=[OTHER])]},
     "the settled Dash clause landed on a creature that rolled no save against Binding Dregs"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_APPLIED", DASH, source_definition_id=DASH_SOURCE, target_ids=[OWNER])]},
     "the settled Dash clause landed on the Alchemist that cast it instead of on its target"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_REMOVED", {"condition_id": "condition:typed.no_dash",
                                           "checkpoint": "START_OF_TURN"}, target_ids=[FOREIGN])]},
     "another formula this Alchemist owns lifted the settled Dash clause"),
    ({"kind": "insert", "baseline": [],
      "tip": [_event("CONDITION_REMOVED", {"condition_id": "condition:typed.no_dash",
                                           "checkpoint": "START_OF_TURN"},
                     source_definition_id=EXPIRATION_SOURCE, target_ids=[OTHER])]},
     "the settled Dash clause was lifted from a creature that never carried it"),
    ({"kind": "replace", "baseline": [_event("GM_RIDER", {"rider": "The area is not a wall."})],
      "tip": [_event("PASSIVE_TRIGGERED", {"trigger": "World Within the Furnace"})]},
     "one event replaced another of an unrelated kind"),
    ({"kind": "replace",
      "baseline": [_event("GM_RIDER", {"rider": "If the target is standing on a solid surface, it also "
                                                    "cannot take the Dash action"}, target_ids=[FOREIGN])],
      "tip": [_event("CONDITION_APPLIED", DASH, target_ids=["actor:factory.3"])]},
     "the settled Dash clause landed on another creature"),
]))
def test_acceptance_rejects_a_difference_no_printed_rule_names(edit, why):
    """The point of the classifier: anything it cannot name is rejected, not accepted quietly.

    Each case is a difference the previous accept-list would have waved through or never seen -- a moved
    damage amount, another pool, an unnamed rewrite, an unnamed event beside a named one, a wrong
    target, a wrong duration, an excess refund -- and each must come back unclassified, which the
    acceptance test turns into a failure. The cases that need a *bound on the owner, the source or the
    target* rather than on the payload are the ones whose two sides share one envelope: nothing but
    :data:`Intended` can tell them apart (AUTO9r3 review, finding 2).
    """
    assert classify(edit, OWNER_INTENDED) == set(), f"{why} was accepted without a printed rule"


#: The reminder the baseline printed in place of the clause, opening exactly as
#: :data:`RETIRED_RIDERS` records it, with the envelope the tip's condition carries.
DASH_RIDER = {"rider": "If the target is standing on a solid surface, it also cannot take the Dash action "
                       "until the start of your next turn. / Timing Detail: Field Formula"}


@pytest.mark.parametrize("edit", _transacted([
    {"kind": "insert", "baseline": [],
     "tip": [_event("CONDITION_APPLIED", DASH, **OWN_DASH)]},
    {"kind": "insert", "baseline": [],
     "tip": [_event("CONDITION_REMOVED", {"condition_id": DASH_CLAUSE,
                                          "checkpoint": "START_OF_TURN"},
                    source_definition_id=EXPIRATION_SOURCE, target_ids=[FOREIGN])]},
    {"kind": "replace",
     "baseline": [_event("GM_RIDER", DASH_RIDER, source_definition_id=DASH_SOURCE)],
     "tip": [_event("CONDITION_APPLIED", DASH, **OWN_DASH)]},
]))
def test_the_settled_dash_clause_is_still_claimed_in_its_printed_shape(edit):
    """The Dash bound narrowed by the review has to still accept the fight's own clause.

    Every case is what the retained capture records: Binding Dregs aimed at the creature that lost its
    save, the clause ending at its printed duration, and the system lifting it at the checkpoint. Without
    these the rejections beside them would pass for the wrong reason -- a bound nothing satisfies rejects
    everything -- so the shape the rule actually has to accept is pinned here as well.
    """
    assert classify(edit, OWNER_INTENDED) == {"settled_dash_clause"}, \
        "the settled Dash clause in the printed shape was not claimed"


def _save_event(actor, ability, passed):
    """One rolled save, as a journal event: who rolled, what they were saving against, and how it went."""
    return {"event_type": "SAVE_ROLLED", "actor_id": actor,
            "source_definition_id": f"action:typed.fixture.{ability}",
            "payload": {"success": passed}}


def _saves(*rows):
    """One capture's rolled saves, as the harness hands them back: a single record carrying its events."""
    return {"sequence": LIFECYCLE,
            "events": [_save_event(actor, ability, passed) for actor, ability, passed in rows]}


def test_the_dash_carrier_is_the_creature_whose_save_the_fight_rolled_as_failed():
    """Where the qualifying target comes from, and what stops it being anybody at all.

    The clause is only claimed on a creature the captures say failed a save against Binding Dregs, so the
    three ways of getting that wrong have to be visible: a passed save names nobody, another ability's
    failed save is not this clause's, and two captures that disagree about who failed have not established
    a carrier at all rather than letting the tip answer for both.
    """
    from tests.auto9f1_replay_evidence import save_failures

    failed = save_failures([_saves((FOREIGN, BINDING_DREGS, False), (OWNER, "TAL_ALCHEMY_FURNACE_VENT", True))])
    assert failed == [{"actor_id": FOREIGN, "source_definition_id": DASH_SOURCE,
                       "transaction": LIFECYCLE, "event_index": 0}], \
        "a passed save was reported as a failed one, or a failure lost where in the fight it was rolled"
    agree = {"save_failures": {"baseline": failed, "tip": failed}}
    assert _failed_against(agree, BINDING_DREGS) == frozenset({FOREIGN})

    assert _failed_against(agree, "TAL_ALCHEMY_FURNACE_VENT") == frozenset(), \
        "another ability's failed save was read as this clause's own"
    assert _failed_against(agree, "TAL_ALCHEMY_BINDING_DREGS_OTHER") == frozenset(), \
        "an ability this Alchemist was never given named a carrier"
    assert _failed_against(agree, BINDING_DREGS) != frozenset({OWNER}), \
        "the caster was accepted as carrying its own target's clause"
    disagreeing = {"save_failures": {"baseline": failed,
                                     "tip": save_failures([_saves((OTHER, BINDING_DREGS, False))])}}
    assert _failed_against(disagreeing, BINDING_DREGS) == frozenset(), \
        "two captures disagreeing about who failed the save still named a carrier"


def _records(rows):
    """Committed records as ``commits`` hands them back: each row is ``(sequence, *events)``."""
    return [{"sequence": sequence, "events": list(events)} for sequence, *events in rows]


#: The negative case the review asked for, as the records the fight really committed: the same creature
#: loses Binding Dregs' save in record 4 and the clause settles there, then passes it in record 9. The
#: record-9 application is the regression under test -- it rode in on the earlier failure when the
#: fight's saves were only a creature set.
_EARLIER_FAILURE = _records([(4, _save_event(FOREIGN, BINDING_DREGS, False),
                              _event("CONDITION_APPLIED", DASH, **OWN_DASH))])
_LATER_SUCCESS = _records([(9, _save_event(FOREIGN, BINDING_DREGS, True),
                            _event("CONDITION_APPLIED", DASH, **OWN_DASH))])


def _life(records=None):
    """A capture's settled-clause lifecycle, derived from the saves and applications that capture rolled."""
    return settled_clauses(records or _EARLIER_FAILURE + _LATER_SUCCESS, DASH_CLAUSE, BINDING_DREGS)


def test_the_clause_is_bound_to_its_own_failed_save_not_to_any_failure_in_the_fight():
    """An earlier failure and a later success on the same creature, which is the case that has to fail.

    The clause settles when *its* save fails, so a creature that lost one save and passed a later one has
    a clause only in the record that rolled its failure. Reducing the fight's saves to a creature set let a
    tip-only application during the successful cast be claimed on the strength of the earlier failure --
    and a later regression that denied Dash after a save was passed could pass with it, since the tip's
    own application was in the accept-list. Here the lifecycle is derived from the rolled saves rather
    than typed in, and both the extra application and an expiration with no application behind it are
    rejected.
    """
    life = _life()
    assert life["failed"] == [FOREIGN], life
    assert life["settled"] == [[4, FOREIGN]], \
        "a passed save settled the clause, or the failure did not settle it at all"
    bounds = Intended(OWNER, frozenset({"acid"}), frozenset({FOREIGN}),
                      {"baseline": frozenset(), "tip": frozenset(map(tuple, life["settled"]))})
    applied = {"kind": "insert", "baseline": [],
               "tip": [_event("CONDITION_APPLIED", DASH, **OWN_DASH)]}
    assert classify({**applied, "tip_transaction": 9}, bounds) == set(), \
        "a clause applied during a save that was passed was claimed on an earlier failure"
    assert classify({**applied, "tip_transaction": 4}, bounds) == {"settled_dash_clause"}, \
        "the clause settled by the failure the fight really rolled was not claimed"

    # The review's other half: an expiration is not a claim of its own, it lifts the clause -- so it needs
    # a lifecycle to lift. Bounds with no settled clause at all (a fight that never applied one) must not
    # let an expiration stand on its own, and one in the successful cast's record cannot lean on the
    # failure the fight rolled earlier.
    nothing_settled = Intended(OWNER, frozenset({"acid"}), frozenset({FOREIGN}),
                               {"baseline": frozenset(), "tip": frozenset()})
    expiration = {"kind": "insert", "baseline": [],
                  "tip": [_event("CONDITION_REMOVED", {"condition_id": DASH_CLAUSE,
                                                       "checkpoint": "START_OF_TURN"},
                                 source_definition_id=EXPIRATION_SOURCE, target_ids=[FOREIGN])],
                  "tip_transaction": 4}
    assert classify(expiration, nothing_settled) == set(), \
        "an expiration with no application behind it was claimed"
    assert classify({**expiration, "tip_transaction": 3}, bounds) == set(), \
        "an expiration in a record before the clause was settled was claimed"
    for at in (5, 9):
        assert classify({**expiration, "tip_transaction": at}, bounds) == set(), \
            "an earlier application authorized a removal without a recorded expiry boundary"


def test_a_clause_is_not_settled_by_another_abilities_failure_or_by_the_casters_own():
    """The failure has to be against the ability whose text carries the clause, and on the target.

    Two abilities failing saves on the same creature is the other half of the provenance: being in the
    fight-wide failed set is not enough when the failure that settled *this* clause was somebody else's,
    or was rolled by the caster rather than by the creature carrying the burden.
    """
    for ability, roller, why in (("TAL_ALCHEMY_FURNACE_VENT", FOREIGN, "another ability's failure"),
                                 (BINDING_DREGS, OWNER, "the caster's own failure")):
        assert _life(_records([(4, _save_event(roller, ability, False),
                                _event("CONDITION_APPLIED", DASH, **OWN_DASH))]))["settled"] == [], \
            f"{why} settled Binding Dregs' clause on its target"
    assert _settled_there(_event("CONDITION_APPLIED", DASH, **OWN_DASH), "tip", 9, OWNER_INTENDED) is False, \
        "an application in a record with no failed save of its own was accepted"
    assert classify({"kind": "insert", "baseline": [],
                     "tip": [_event("CONDITION_APPLIED", DASH, **OWN_DASH)],
                     "tip_transaction": LIFECYCLE},
                    Intended(OWNER, frozenset({"acid"}), frozenset({FOREIGN}),
                             {"baseline": frozenset(), "tip": frozenset()})) == set(), \
        "an application was claimed with no failed save anywhere to settle it"


def _dash_expiration(checkpoint="START_OF_TURN", actor=OWNER):
    return _event("CONDITION_REMOVED", {"condition_id": DASH_CLAUSE, "checkpoint": checkpoint},
                  actor_id=actor, source_definition_id=EXPIRATION_SOURCE, target_ids=[FOREIGN])


def _turn_start(actor=OWNER):
    return _event("TURN_STARTED", {}, actor_id=actor, source_definition_id="system:combat.turn")


def _standing(actor=OWNER, event_type="STOOD_UP", checkpoint="STAND_UP"):
    return _event(event_type, {"checkpoint": checkpoint}, actor_id=actor,
                  source_definition_id="system:combat.stand_up", target_ids=[actor])


def _bounds_from_records(records):
    life = settled_clauses(records, DASH_CLAUSE, BINDING_DREGS)
    # Exercise the JSON wire representation and the production evidence-to-classifier adapter.
    result = json.loads(json.dumps({"dash_lifecycles": {"tip": life}}))
    bounds = intended(result)._replace(owner=OWNER, prepared=frozenset({"acid"}), dashed=frozenset({FOREIGN}))
    return life, bounds


def _claim_removal(records, transaction, index):
    from tests.auto9f1_replay_evidence import _edits

    life, bounds = _bounds_from_records(records)
    record = next(row for row in records if row["sequence"] == transaction)
    # Diff through this event, retaining its original prefix and index. Identical duplicates cannot
    # be distinguished by SequenceMatcher when the suffix is included; the full-edit test below
    # separately checks that a pair of removals is rejected as a whole.
    before = {**record, "events": record["events"][:index]}
    after = {**record, "events": record["events"][:index + 1]}
    edit, = _edits(before, after)
    return life, classify(edit, bounds)


def test_dash_removal_consumes_the_lifetime_at_the_actual_source_next_turn():
    records = _EARLIER_FAILURE + _records([
        (5, _dash_expiration(), _turn_start()),
        (9, _save_event(FOREIGN, BINDING_DREGS, True), _dash_expiration(), _turn_start()),
    ])
    life, claim = _claim_removal(records, 5, 0)
    assert life["removed"] == [[5, FOREIGN, 0]]
    assert claim == {"settled_dash_clause"}
    assert _claim_removal(records, 9, 1)[1] == set(), "a consumed lifetime authorized a later removal"


@pytest.mark.parametrize("middle", [
    [(5, _dash_expiration()), (6, _turn_start())],  # earlier transaction, correct checkpoint label
    [(5, _dash_expiration(actor=FOREIGN), _turn_start(FOREIGN)), (6, _turn_start())],
    [(5, _dash_expiration("END_OF_TURN"), _turn_start())],
    [(5, _dash_expiration(), _event("ACTION_DECLARED", {}), _turn_start())],
    [(5, _dash_expiration(), _standing(FOREIGN), _turn_start())],
    [(5, _dash_expiration(), _standing(event_type="ACTION_DECLARED"), _turn_start())],
    [(5, _dash_expiration(), _standing(event_type="CONDITION_REMOVED", checkpoint="END_OF_TURN"),
      _turn_start())],
    [(5, _dash_expiration()), (6, _standing(), _turn_start())],
    [(5, _dash_expiration(), _standing(), _event("ACTION_DECLARED", {}), _turn_start())],
    [(5, _turn_start(), _dash_expiration())],  # same transaction, after the boundary
    [(5, _turn_start()), (6, _dash_expiration(), _turn_start())],  # missed first next turn
])
def test_dash_removal_rejects_premature_wrong_checkpoint_and_late_expiration(middle):
    life, bounds = _bounds_from_records(_EARLIER_FAILURE + _records(middle))
    assert life["removed"] == []
    for record in _records(middle):
        for index, event in enumerate(record["events"]):
            if event["event_type"] == "CONDITION_REMOVED":
                assert classify({"kind": "insert", "baseline": [], "tip": [event],
                                 "tip_transaction": record["sequence"], "tip_event_indices": [index]},
                                bounds) == set()


@pytest.mark.parametrize("housekeeping", [[], [_standing(event_type="CONDITION_REMOVED"), _standing()]])
def test_dash_duplicate_removals_in_one_transaction_do_not_share_event_coordinates(housekeeping):
    from tests.auto9f1_replay_evidence import _edits

    records = _EARLIER_FAILURE + _records([(5, _dash_expiration(), _dash_expiration(),
                                          *housekeeping, _turn_start())])
    life, claim = _claim_removal(records, 5, 0)
    assert life["removed"] == [[5, FOREIGN, 0]]
    assert claim == {"settled_dash_clause"}
    assert _claim_removal(records, 5, 1)[1] == set()
    _, bounds = _bounds_from_records(records)
    before = {"sequence": 5, "events": [*housekeeping, _turn_start()]}
    edit, = _edits(before, records[-1])
    assert classify(edit, bounds) == set(), "one valid removal hid its duplicate in the same edit"


def test_dash_can_be_applied_again_after_a_consumed_lifetime():
    records = _EARLIER_FAILURE + _records([
        (5, _dash_expiration(), _turn_start()),
        (9, _save_event(FOREIGN, BINDING_DREGS, False), _event("CONDITION_APPLIED", DASH, **OWN_DASH)),
        (10, _dash_expiration(), _turn_start()),
    ])
    assert _claim_removal(records, 10, 0)[1] == {"settled_dash_clause"}


def test_prone_casters_dash_expiry_is_claimed_from_committed_reloaded_table_history(monkeypatch, tmp_path):
    """Actual turn-start standing must not hide the caster's correctly timed Dash expiration."""
    from tests.auto9f1_replay_evidence import STOCK, commits
    from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, turn
    from tests.test_lock_choices import install

    # Use the documented roll-result hook to settle both real saves deterministically; no engine
    # method or persisted state is patched. The table still records and replays the resolved rolls.
    install(monkeypatch, "d20_result", lambda engine, roll, context:
            {"source_id": "test:prone-dash-expiry", "operation": "replace", "natural_result": 1}
            if engine.d20_context().get("kind") == "save" else None)
    combat, table, mid = fight(tmp_path, owned=[BINDING_DREGS], effects=STOCK,
                               primary="Stamina", seed="AUTO9F1-ALCHEMY", foe_ac=12)
    turn(combat, table, mid)
    act(combat, table, mid, "Test setup")
    act(combat, table, mid, "end")
    turn(combat, table, mid)
    act(combat, table, mid, "Binding Dregs")
    engine = reload(combat, mid)
    assert any(c.condition_id == DASH_CLAUSE for c in engine.state.actors[RIGHT].conditions.values())
    act(combat, table, mid, "end")
    act(combat, table, mid, "Shove: Prone")
    engine = reload(combat, mid)
    assert any(c.expires_on == "STAND_UP" for c in engine.state.actors[LEFT].conditions.values())
    assert any(c.condition_id == DASH_CLAUSE for c in engine.state.actors[RIGHT].conditions.values())
    act(combat, table, mid, "end")
    engine = reload(combat, mid)
    assert not any(c.expires_on == "STAND_UP" for c in engine.state.actors[LEFT].conditions.values())
    assert not any(c.condition_id == DASH_CLAUSE for c in engine.state.actors[RIGHT].conditions.values())
    records = commits(next(tmp_path.rglob("GenesisState.json")).parent)
    life = settled_clauses(records, DASH_CLAUSE, BINDING_DREGS)
    assert len(life["removed"]) == 1, life
    transaction, target, index = life["removed"][0]
    assert target == RIGHT
    record = next(row for row in records if row["sequence"] == transaction)
    suffix = record["events"][index + 1:]
    stood = next(i for i, e in enumerate(suffix) if e["event_type"] == "STOOD_UP")
    started = next(i for i, e in enumerate(suffix) if e["event_type"] == "TURN_STARTED")
    assert stood < started and suffix[stood]["actor_id"] == LEFT
    from tests.auto9f1_replay_evidence import _edits
    result = json.loads(json.dumps({"dash_lifecycles": {"tip": life}}))
    bounds = intended(result)._replace(owner=LEFT, dashed=frozenset({RIGHT}))
    before = {**record, "events": record["events"][:index]}
    after = {**record, "events": record["events"][:index + 1]}
    edit, = _edits(before, after)
    assert classify(edit, bounds) == {"settled_dash_clause"}


@pytest.mark.parametrize("events", [
    [_event("CONDITION_APPLIED", DASH, **OWN_DASH), _save_event(FOREIGN, BINDING_DREGS, False)],
    [_save_event(FOREIGN, BINDING_DREGS, False), _save_event(FOREIGN, BINDING_DREGS, True),
     _event("CONDITION_APPLIED", DASH, **OWN_DASH)],
])
def test_dash_lifetime_requires_its_own_preceding_failed_save(events):
    life = settled_clauses(_records([(4, *events), (5, _dash_expiration(), _turn_start())]),
                           DASH_CLAUSE, BINDING_DREGS)
    assert life["settled"] == [] and life["removed"] == []


@pytest.mark.parametrize("scenario", ["control", "alchemy"])
def test_documented_comparison_cli_serializes_readable_table_captures(tmp_path, scenario):
    """Real committed/reloaded histories cover both empty and populated lifecycle JSON via the CLI."""
    import subprocess
    import sys
    from tests.auto9f1_replay_evidence import APP_ROOT, capture

    captured = capture(tmp_path, scenario, steps=1)
    match = Path(captured["match"])
    result = journal_differences(match, match)
    assert json.loads(json.dumps(result)) == result
    assert result["byte_identical"] and not result["differences"]
    life = result["dash_lifecycles"]["tip"]
    if scenario == "alchemy":
        assert life["settled"] and life["removed"], "capture never exercised an active Dash lifetime"
    else:
        assert life == {"failed": [], "settled": [], "removed": []}
    completed = subprocess.run([sys.executable, "-m", "tests.auto9f1_replay_evidence", "compare",
                                str(match), str(match)], cwd=APP_ROOT, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == result


#: A saved actor with nothing this lane changed: 30 hit points on a fixed square, no pool, no condition.
PLAIN = {"current_hp": 30, "temporary_hp": 0, "position": {"x": 3, "y": 6},
         "resources": {}, "conditions": {}}
#: The saved condition this lane adds: the sealed preparation with the types it sealed and the pill that
#: names the talent, exactly as the retained capture saved it. A saved condition is keyed by its instance,
#: which carries the creating sequence and the creature it is on.
PREPARATION_KEY = f"condition-instance:condition:typed.seven_flavor_types:{OWNER}"
PREPARATION_DATA = {"types": "acid",
                    "label": f"{SEVEN_FLAVOR_PRINTED}: your Alchemy formulas may deal Acid damage instead of "
                             "the printed Acid, Fire, Poison or Force, until you change or remove it"}
PREPARATION = {"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED", "data": PREPARATION_DATA}}}
#: The one pool this lane's own refund moves: the printed CP the baseline charged a second time, so the
#: tip's remainder is exactly one point higher and nothing else about the pool moves.
POOL_BEFORE, POOL_AFTER = {"resources": {STAMINA: 19}}, {"resources": {STAMINA: 20}}
#: The tip side of a saved comparison whose every difference is claimed: one spare printed CP and the
#: sealed preparation, and nothing else.
ALLOWED = {**PLAIN, **POOL_AFTER, **PREPARATION}


#: Two creatures the fixtures use, so the saved-state cases are the shape the loader really rebuilds:
#: the Alchemist that owns the printed rules and the foe it acts on. The preparation belongs to the
#: Alchemist and the Dash clause to the foe, so a one-actor record could not tell them apart.
FOREIGN_PLAIN = {"current_hp": 30, "temporary_hp": 0, "position": {"x": 4, "y": 6},
                 "resources": {}, "conditions": {}}


def _state(baseline, tip, foe_baseline=None, foe_tip=None):
    """The saved-state half of a comparison: **two** creatures, as the baseline left them and as the tip did.

    Both creatures are named in the actors map because the loader stores each creature's conditions inside
    that creature's own record, and ``classify_state`` has to be handed the enclosing actor to know which
    record a saved condition was read from (AUTO9r5 review, finding 2). ``foe_tip`` is where a target's
    own restriction is saved, and ``foe_baseline`` is that same untouched record, so a gained condition on
    the foe is a real change and not an actor appearing on one side only.
    """
    before = {OWNER: baseline, FOREIGN: FOREIGN_PLAIN if foe_baseline is None else foe_baseline}
    after = {OWNER: tip, FOREIGN: FOREIGN_PLAIN if foe_tip is None else foe_tip}
    return {"state": {"actors": {"baseline": before, "tip": after}}}


def test_the_two_allowed_saved_changes_are_the_only_ones_claimed():
    """What the classifier accepts on the saved side, so the rejections below cannot pass vacuously.

    Each of these is the *same* shape as a rejection case below with the forbidden change left out, so
    the rejections prove the forbidden half is what turns the answer into an empty set.
    """
    assert classify_state(_state(PLAIN, PLAIN), OWNER_INTENDED) == set(), \
        "an unchanged saved state must claim nothing; the acceptance test wants at least one claim"
    assert classify_state(_state({**PLAIN, **POOL_BEFORE}, ALLOWED), OWNER_INTENDED) == \
        {"printed_cost_once", "sealed_preparation"}
    assert classify_state(_state({**PLAIN, **POOL_BEFORE}, {**PLAIN, **POOL_AFTER}), OWNER_INTENDED) == \
        {"printed_cost_once"}
    assert classify_state(_state(PLAIN, {**PLAIN, **PREPARATION}), OWNER_INTENDED) == {"sealed_preparation"}


@pytest.mark.parametrize("forbidden,why", [
    ({"current_hp": 29}, "a creature's hit points moved"),
    ({"temporary_hp": 4}, "a creature's temporary hit points moved"),
    ({"position": {"x": 4, "y": 6}}, "a creature moved"),
    ({"resources": {STAMINA: 20, "resource:named.reagent_stock": 3}}, "another pool moved"),
    ({"resources": {STAMINA: 17}}, "the printed pool ended lower"),
    ({"resources": {STAMINA: 22}}, "the printed pool was given back more than the printed one CP"),
    ({"conditions": {**PREPARATION["conditions"],
                     "condition-instance:condition:core.blessed:actor:factory.1":
                     {"expires_on": "UNTIL_REMOVED", "data": {}}}}, "an unnamed condition appeared"),
    ({"conditions": {PREPARATION_KEY: {"expires_on": "START_OF_SELF_NEXT_TURN", "data": PREPARATION_DATA}}},
     "the sealed preparation was given a duration nobody printed"),
    ({"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED", "data": {"label": "prepared"}}}},
     "the sealed preparation recorded no types"),
    # The three the review named for the saved side: an added key, a value that is not a printed damage
    # type, and a pill that does not name the talent. A subset of the right keys is never enough.
    ({"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED",
                                       "data": {**PREPARATION_DATA, "unexpected_modifier": 99}}}},
     "the sealed preparation carried a value no printed rule names"),
    ({"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED",
                                       "data": {**PREPARATION_DATA, "types": "acid|chaos"}}}},
     "the sealed preparation recorded a damage type the printed question never offers"),
    ({"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED",
                                       "data": {**PREPARATION_DATA, "types": ""}}}},
     "the sealed preparation recorded no damage type at all"),
    ({"conditions": {PREPARATION_KEY: {"expires_on": "UNTIL_REMOVED",
                                       "data": {**PREPARATION_DATA, "label": "prepared"}}}},
     "the sealed preparation's pill did not name the talent that put it there"),
    ({"conditions": {f"condition-instance:condition:typed.seven_flavor_types:{FOREIGN}":
                     {"expires_on": "UNTIL_REMOVED", "data": PREPARATION_DATA}}},
     "the sealed preparation was saved on a creature that does not own the talent"),
    ({"conditions": {f"condition-instance:condition:typed.no_dash:{OTHER}":
                     {"expires_on": "START_OF_SOURCE_NEXT_TURN", "data": {}}}},
     "the settled Dash clause was saved on a creature that rolled no save against Binding Dregs"),
    ({"conditions": {f"condition-instance:condition:typed.no_dash:{OWNER}":
                     {"expires_on": "START_OF_SOURCE_NEXT_TURN", "data": {}}}},
     "the settled Dash clause was saved on the Alchemist that cast it instead of on its target"),
    ({"conditions": {**PREPARATION["conditions"],
                     f"condition-instance:condition:typed.no_dash:{FOREIGN}":
                     {"expires_on": "START_OF_SOURCE_NEXT_TURN", "data": {"amount": 1}}}},
     "the settled Dash clause recorded an amount the printed clause never had"),
])
def test_acceptance_rejects_a_saved_value_no_printed_rule_names(forbidden, why):
    """The saved half is held to the same rule as the journal.

    Every case is a change **on top of** the two this lane allows -- the spare printed CP and the sealed
    preparation are both present on the tip side -- so nothing can pass by looking like a fight whose only
    difference is an allowed one, and the baseline side really is the untouched state, not a copy of it.
    """
    assert classify_state(_state({**PLAIN, **POOL_BEFORE}, ALLOWED), OWNER_INTENDED) == \
        {"printed_cost_once", "sealed_preparation"}, "the allowed change this case builds on is not claimed"
    assert classify_state(_state({**PLAIN, **POOL_BEFORE}, {**ALLOWED, **forbidden}), OWNER_INTENDED) == set(), \
        f"{why} was accepted without a printed rule"


#: The settled Dash clause as the loader rebuilds it: keyed by its own instance and naming the creature
#: it sits on, which is the creature whose save it lost -- the shape the real fight's journal records at
#: ``target_ids``. The condition is held in that creature's **own** record, because that is where the
#: loader puts it.
DASH_KEY = f"condition-instance:{DASH_CLAUSE}:{FOREIGN}"
DASH_SAVED = {"expires_on": PRINTED_EXPIRY["settled_dash_clause"], "data": {}}


def _foe_holding(conditions):
    """The foe's saved record holding exactly these conditions: the two-actor shape a target's own
    restriction is persisted in. The keys are condition-instance ids, so they are passed as a mapping
    rather than as keyword arguments."""
    return {**FOREIGN_PLAIN, "conditions": dict(conditions)}


def test_the_saved_dash_clause_belongs_to_the_creature_that_failed_the_save():
    """The Dash clause is the *target's* burden, so it is saved on the target and nowhere else.

    A capture that ends while the clause is still up -- before the start of the caster's next turn lifts
    it -- leaves the condition on the creature that failed the save. Requiring the caster to hold it
    instead (AUTO9r4 review, finding 2) would reject exactly that correct fight, so the positive case is
    pinned here: on the affected creature it is claimed, and on the caster and on a creature that rolled
    no save against Binding Dregs it is not. One unclaimed condition condemns the whole saved state --
    that is what the classifier does everywhere -- so those two come back empty rather than short of
    one claim.
    """
    assert classify_state(_state({**PLAIN, **POOL_BEFORE}, ALLOWED, foe_tip=_foe_holding({DASH_KEY: DASH_SAVED})),
                          OWNER_INTENDED) == {"printed_cost_once", "sealed_preparation", "settled_dash_clause"}, \
        "the settled Dash clause was not claimed on the creature whose save it actually lost"
    for holder, why in ((OWNER, "the Alchemist that cast it"), (OTHER, "a creature that rolled no save")):
        key = f"condition-instance:{DASH_CLAUSE}:{holder}"
        assert classify_state(_state({**PLAIN, **POOL_BEFORE}, ALLOWED, foe_tip=_foe_holding({key: DASH_SAVED})),
                              OWNER_INTENDED) == set(), \
            f"the settled Dash clause was accepted on {why}"


def test_a_saved_condition_must_name_the_record_it_is_saved_in():
    """A saved condition's key names its creature, so it has to be filed under that same creature.

    The review's finding: the condition's *key* carried the foe while the record holding it was the
    caster's, and the check read only the key, so a caster's record carrying a foe-suffixed condition was
    accepted as a correctly persisted restriction on that foe. The loader stores a condition in the record
    of the creature it is on, so a key and a record naming different creatures is a misfiled condition
    and nothing this lane may claim (AUTO9r5 review, finding 2).
    """
    # Each case is a two-actor state in which the *only* thing wrong is which record holds a condition
    # naming the other creature: both creatures are present on both halves with identical hit points,
    # squares and pools, so nothing else in the comparison can reject these for a different reason. The
    # saved contents are the printed ones for whichever condition is being misfiled, so the case is about
    # the filing and not about the data check.
    cases = ((DASH_CLAUSE, DASH_SAVED, FOREIGN, "owner", "the caster's own record"),
             (DASH_CLAUSE, DASH_SAVED, OWNER, "foe", "the foe's own record"),
             ("condition:typed.seven_flavor_types",
              {"expires_on": PRINTED_EXPIRY["sealed_preparation"], "data": PREPARATION_DATA},
              FOREIGN, "owner", "the caster's own record"),
             ("condition:typed.seven_flavor_types",
              {"expires_on": PRINTED_EXPIRY["sealed_preparation"], "data": PREPARATION_DATA},
              OWNER, "foe", "the foe's own record"))
    for condition_id, saved, holder, record, why in cases:
        key = f"condition-instance:{condition_id}:{holder}"
        own_before = {**PLAIN, **POOL_BEFORE, "conditions": PREPARATION["conditions"]}
        if record == "owner":
            own_after = {**ALLOWED, "conditions": {**PREPARATION["conditions"], key: saved}}
            foe_tip = _foe_holding({})
        else:
            own_after = ALLOWED
            foe_tip = _foe_holding({key: saved})
        assert classify_state(_state(own_before, own_after, foe_tip=foe_tip), OWNER_INTENDED) == set(), \
            f"a {condition_id.split(':')[-1]} condition naming {holder} was accepted in {why}"


def test_the_saved_dash_clause_reaches_its_own_data_check():
    """The extra-key rejection has to be the *data* that rejects, not the creature it sits on.

    The review's other half: this case used to fail at the owner check, before the data was ever read,
    so it proved nothing about the contents. Key, expiry and carrier are now identical to the accepted
    case and to each other -- the same creature that just claimed the clause above -- and ``data`` is the
    single thing that differs, so the empty contents being accepted is what makes the rejection mean
    something.
    """
    for data, expected in (({}, {"printed_cost_once", "sealed_preparation", "settled_dash_clause"}),
                           ({"amount": 1}, set())):
        assert classify_state(
            _state({**PLAIN, **POOL_BEFORE}, ALLOWED, foe_tip=_foe_holding({DASH_KEY: {**DASH_SAVED, "data": data}})),
            OWNER_INTENDED) == expected, \
            f"the settled Dash clause holding {data or 'no contents'} was not held to its own data check"


def test_acceptance_rejects_a_live_condition_that_changed():
    """A condition the baseline already granted and the tip rewrote is never claimed: its data and its
    duration are a behaviour change somebody has to name, not a knock-on of this lane's own effects."""
    key = f"condition-instance:condition:typed.alchemy_court_damage:{OWNER}"
    before = {**PLAIN, **POOL_BEFORE, "conditions": {key: {"expires_on": "START_OF_SLOT_AT:15:0",
                                                          "data": {"amount": 2}}}}
    after = {**ALLOWED, "conditions": {**PREPARATION["conditions"], key: {"expires_on": "START_OF_SLOT_AT:9:0",
                                                                       "data": {"amount": 9}}}}
    assert classify_state(_state(before, after), OWNER_INTENDED) == set(), \
        "a live condition's duration and amount were rewritten"


def test_the_saved_state_comes_from_the_last_commit_and_not_from_a_snapshot(tmp_path):
    """The saved half must be the state the loader rebuilds, not the newest snapshot on disk.

    Snapshots are periodic -- every tenth commit and on a round change (``combat/gate3_storage.py``,
    ``should_snapshot``) -- and the real loader takes the newest valid snapshot and replays every later
    commit on top of it. So a fight that carried on after a snapshot holds *older* numbers in that file
    than the fight is left with. Here a real fight writes a snapshot on purpose, commits one more turn
    after it, and the state reported for the fight must be the later one while the newest snapshot still
    says the earlier.
    """
    from tests.auto9f1_replay_evidence import final_committed_state, state_facts
    from tests.hunt36_support import LEFT, RIGHT, act, fight

    combat, table, mid = fight(tmp_path, effects=[{
        "type": "gain_resource", "resource_id": "resource:named.reagent_stock", "amount": 3,
        "applies_to": "self", "duration": "instant",
        "evidence": "Scenario setup: three Reagent Stock, so the saved pool is observable."}],
        foe_hp=500, foe_ac=1)
    act(combat, table, mid, "Test setup")
    match = next(tmp_path.rglob("GenesisState.json")).parent
    combat._load_session(mid).mechanical.explicit_snapshot()

    snapshot = sorted((match / "Snapshots").glob("*.json"))[-1]
    anchored = json.loads(snapshot.read_text(encoding="utf-8"))["state"]
    assert anchored["current_actor_id"] == LEFT, "the snapshot was not taken while the owner was acting"

    act(combat, table, mid, "end")  # one more committed record, after the snapshot's anchor
    facts = state_facts(match)
    assert snapshot == sorted((match / "Snapshots").glob("*.json"))[-1], \
        "the fight wrote a second snapshot, so the newest one is no longer the stale one"
    assert facts["current_actor_id"] == RIGHT, \
        f"the reported state is the snapshot's ({anchored['current_actor_id']}), not the last commit's"
    loaded = combat._load_session(mid).engine.state
    for actor_id, reported in facts["actors"].items():
        assert reported["current_hp"] == loaded.actors[actor_id].current_hp, actor_id
        assert reported["resources"] == dict(sorted(loaded.actors[actor_id].resources.items())), actor_id
    commits = [row for row in map(json.loads, (match / "Journal.ndjson").read_text().splitlines())
               if row["record_type"] == "COMMIT"]
    state, source = final_committed_state(match)
    assert source["record_sequence"] == commits[-1]["record_sequence"] > int(snapshot.stem.split("_")[1]), \
        f"the reported state came from record {source['record_sequence']}, not the last commit"
    assert source["canonical_state_sha256"] == commits[-1]["post_state_sha256"], source


def test_acceptance_rejects_a_saved_area_a_turn_or_a_round_that_moved():
    """Not an actor at all: whose turn it is, the round, and an area's square or damage types."""
    for key, baseline, tip in (("zones", {}, {"z": {}}), ("round_number", 1, 2),
                               ("current_actor_id", OWNER, FOREIGN)):
        assert classify_state({"state": {key: {"baseline": baseline, "tip": tip}}}, OWNER_INTENDED) == set(), \
            f"{key} moved"


def unreadable_heads(result) -> list[str]:
    """The sides whose saved history was not read back, each with the reason the loader gave.

    A comparison is only worth anything when both sides' states were actually rebuilt, so this is checked
    by the acceptance tests themselves rather than left to the reader of a comparison: reporting an
    unreadable history as "no state" made two unreadable halves compare equal (AUTO9r3 review, finding 1).
    """
    reasons = []
    for side in ("baseline", "tip"):
        head = (result.get("state_head") or {}).get(side) or {}
        if head.get("kind") != "final_committed_record":
            reasons.append(f"the {side} saved history was not read: "
                           f"{head.get('reason', head) if head else 'no record was reported'}")
    return reasons


def control_failures(result) -> list[str]:
    """Every reason checklist 12's control fails, so all of them are reported at once and the first is the
    saved history neither half could be read from."""
    failures = unreadable_heads(result)
    if not result.get("transaction_counts_match"):
        failures.append(f"the transaction counts differ: {result['baseline_transactions']} baseline, "
                        f"{result['tip_transactions']} tip")
    if not result.get("byte_identical"):
        failures.append(f"the journals are not byte-identical: {result['baseline_journal_sha256']} baseline, "
                        f"{result['tip_journal_sha256']} tip")
    if result.get("differences"):
        failures.append(f"{len(result['differences'])} transaction(s) differ: {result['differences'][:2]}")
    if result.get("state"):
        failures.append(f"the saved state differs: {json.dumps(result['state'], sort_keys=True)[:2000]}")
    return failures


@pytest.mark.skipif(not os.environ.get("AUTO9F1_BASE_REPLAY"),
                    reason="requires task-owned paired baseline/tip captures")
def test_a_fight_this_lane_does_not_touch_is_byte_identical():
    """Checklist 12's control: same seed, same script, same bytes -- no change for anyone else."""
    result = journal_differences(match_of("base-control"), match_of("tip-control"))
    failures = control_failures(result)
    assert not failures, "\n".join([*failures, json.dumps(result["state_head"], indent=2, sort_keys=True)])


def test_two_unreadable_saved_histories_cannot_pass_the_control_check(tmp_path):
    """A control whose two locks or journals the loader refuses must fail, not compare as two empty states.

    This is the shape of the review's finding: ``final_committed_state`` reported a history it could not
    rebuild as an empty state, and two empty states are equal, so every assertion of the control passed
    while nothing had been compared at all. Here a real saved fight is broken the way a rewritten or
    truncated journal breaks one -- the committed state hash no longer reproduces -- and the comparison has
    to refuse instead of reporting an empty half. The second half of the test pins the acceptance check
    itself, on the exact result the previous harness produced for two unreadable captures.
    """
    from tests.auto9f1_replay_evidence import final_committed_state
    from tests.hunt36_support import act, fight

    combat, table, mid = fight(tmp_path, foe_hp=500, foe_ac=1)
    act(combat, table, mid, "end")
    match = next(tmp_path.rglob("GenesisState.json")).parent
    journal = match / "Journal.ndjson"
    lines = journal.read_text(encoding="utf-8").splitlines()
    commit = next(index for index, line in enumerate(lines)
                  if json.loads(line)["record_type"] == "COMMIT")
    record = json.loads(lines[commit])
    lines[commit] = json.dumps({**record, "post_state_sha256": "0" * 64})
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(UnreadableSavedHistory) as raised:
        final_committed_state(match)
    assert str(match) in str(raised.value), raised.value
    with pytest.raises(UnreadableSavedHistory):
        journal_differences(match, match)  # both sides unreadable: the control's own first step refuses

    swallowed = {  # the exact result the previous harness produced for two unreadable captures
        "baseline_journal_sha256": journal_sha256(match), "tip_journal_sha256": journal_sha256(match),
        "byte_identical": True, "baseline_transactions": 1, "tip_transactions": 1,
        "transaction_counts_match": True, "totals": {}, "state": {}, "differences": [],
        "state_head": {side: {"kind": "unreadable", "reason": "Gate3Error: the journal does not bind"}
                       for side in ("baseline", "tip")}}
    assert control_failures(swallowed), "two unreadable saved histories would pass the control check again"


@pytest.mark.skipif(not os.environ.get("AUTO9F1_BASE_REPLAY"),
                    reason="requires task-owned paired baseline/tip captures")
def test_the_alchemist_fight_only_differs_where_this_lane_intends():
    """Checklist 12: every difference is classified, and each classification names a printed rule."""
    result = journal_differences(match_of("base-alchemy"), match_of("tip-alchemy"))
    assert not unreadable_heads(result), \
        json.dumps(result["state_head"], indent=2, sort_keys=True)
    assert result["transaction_counts_match"], result
    assert not result["byte_identical"], \
        "the Alchemist fight should exercise this lane's changes and did not"

    # The owner and the prepared types are the fight's own statements, read from the tip's saved
    # preparation, so every claim below is checked against who owns the printed rule and what it sealed.
    bounds = intended(result)
    assert bounds.prepared == {"acid"}, \
        f"the fight did not prepare a damage type, so the substitution was never exercised: {bounds}"
    assert bounds.owner, "the tip capture saved no preparation, so it owns nothing to bound a claim with"

    unclassified, seen = [], set()
    for difference in result["differences"]:
        for edit in difference["edits"]:
            claims = classify(edit, bounds)
            seen |= claims
            if not claims:
                unclassified.append((difference["transaction"], edit))
    assert not unclassified, (
        "a difference no printed rule of this lane explains:\n"
        + "\n".join(f"  transaction {index}: {edit}" for index, edit in unclassified))
    assert seen, "the Alchemist fight was accepted without a single named difference"

    state_claims = classify_state(result, bounds)
    assert state_claims, (
        "a saved value moved that no printed rule of this lane claims:\n"
        + json.dumps({"state": result["state"], "state_head": result["state_head"]}, indent=2,
                     sort_keys=True)[:4000])
    seen |= state_claims

    # Every condition the tip gained is one this lane prints; none was lost.
    assert set(result["totals"]["conditions"]["gained"]) <= INTENDED_CONDITIONS, result["totals"]["conditions"]
    assert not result["totals"]["conditions"]["lost"], result["totals"]["conditions"]
    # The tip spends no more of the printed pool than the baseline did, anywhere in the fight.
    assert not result["totals"]["spent"]["gained"], result["totals"]["spent"]
    assert set(result["totals"]["damage"]["lost"]) <= {"NECROTIC", "POISON"}, result["totals"]["damage"]
    assert not result["totals"]["damage"]["gained"], result["totals"]["damage"]
    for text in result["totals"]["riders"]["lost"]:
        assert _retired_intent(text), f"a reminder stopped printing and no printed rule explains it: {text}"
    print(f"classified differences: {sorted(seen)}")
    for name in sorted(seen):
        print(f"  {name}: {INTENT[name]}")
