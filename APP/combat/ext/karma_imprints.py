"""Karmic Imprints: the Karma sphere's Debt and Grace ledger (system C, sys/resources-states 2026-09-29).

Owner text (authority/typed_mechanics/rules_text.json; Tianxia Sphere Compendium, Karma):
  * Imprints.  "A creature can hold a combined number of your Imprints up to your Proficiency Bonus, unless a talent says otherwise."
    A Debt Imprint punishes, a Grace Imprint protects: a talent cannot use a Grace Imprint to punish or a Debt Imprint to bless.  A single
    Cause normally creates one Imprint.  A spent Imprint's Cause cannot recreate it (an enemy strikes your ally, you record Debt and spend it
    on Return the Sting: the same strike cannot create another Debt).  "Petty inconvenience, accidental bumps, routine combat exchanges,
    empty promises, or purely mechanical exploitation should not automatically create a Cause unless the table agrees the scene gives it
    weight."
  * Record the Deed (Reaction, 60 ft, once per round): "You Witness a Cause created by a creature within range."  Debt when it deals
    meaningful damage to another creature, inflicts a harmful condition, breaks a clear oath, betrays a willing ally, steals something of
    real value, commands a minion to perform a harmful act, or performs another harmful act the GM approves; Grace when it restores Hit
    Points to another creature, prevents meaningful damage, removes a harmful condition, protects another creature at personal risk, keeps
    a difficult oath, repays a meaningful debt, or performs another selfless act the GM approves.
    Witness: you directly see or hear the act; it occurs against you; it occurs against a creature bound to you by a Karma talent; it
    violates your oath; it occurs inside your Karma Domain; or a talent says you may.
  * Ledger Seal Scripture: maximum Imprints per creature +1; "Once per round, when you use Record the Deed, you may spend 1 CP to place the
    Imprint without using your Reaction."
  * Court of Cause and Effect (Action, 7 CP, 30-foot aura centered on you, Concentration up to 1 minute): inside the Court your Record the
    Deed range is 120 feet and you may use it twice per round; a creature with one of your Debt Imprints that damages another creature takes
    Psychic damage equal to your Proficiency Bonus; a creature with one of your Grace Imprints that restores HP, prevents damage or
    willingly accepts harm for another gains Temporary HP equal to your Proficiency Bonus; a creature triggers each Debt or Grace effect
    only once per turn.
  * Oath of Mutual Defense: "If a bound creature willingly takes damage for another through this oath, you may place one Grace Imprint on
    that creature without using your Reaction.  This can occur only once per round."
  * Return the Sting (Reaction, 1 CP + one Debt Imprint): a creature with your Debt Imprint deals damage to you or an ally within 60 feet;
    it takes Psychic damage equal to PB + your key ability modifier, +1d8 at CL 11, +2d8 at CL 17.
Spheres 5e and D&D 5.5e say nothing about Imprints; the ledger follows the text above.

Plumbing.  An Imprint is a condition instance filed under the table's named-mark id (typed_executor.mark_condition_id("Debt Imprint",
holder)), so ``bears_mark``, ``requires_mark`` readings and the table's mark hover text work unchanged; several instances of one id stack
and their number is the creature's count.  Causes are read off the fight's own events (the ``event`` hook): DAMAGE_COMMITTED (a hostile
creature deals damage to the holder or a teammate), HEALING_APPLIED (a teammate heals another creature), CONDITION_APPLIED (a hostile
creature inflicts a harmful condition) and the ``damage_shared`` hook (a teammate takes damage for another).  Record the Deed spends the
holder's Reaction (asked of a player in Ask mode), or, with Ledger Seal Scripture and no Reaction to spend, 1 CP.  Effect type
"spend_imprint" spends Imprints for the talents that consume them (Return the Sting).  Hooks used: event, damage_shared, compile_block
("karma_ledger": kinds record, seal), effect.

Judgment calls (the printed text leaves them to the table or names no number):
  * Who holds a ledger: a character with Record the Deed (the Karma sphere's base ability) or with any Karma talent granted by a Path
    (Burden of Deeds, Court of Cause and Effect, ...): a Karma talent reached without the sphere still needs Imprints to work, and the
    owner asked for it (2026-09-28, the retired life_karma proxy).
  * "Meaningful damage": damage that got through (after reductions) from a creature of another team to the holder or its team.  Harm dealt
    by the holder's own side (self-defence), and friendly fire, are not recorded; the GM's "routine combat exchange" caution is left to the
    table, which can remove the Imprint.  A hostile healer's Grace and a Debt on an ally are never placed.
  * Grace goes to a teammate of the holder (never to the holder or an enemy): a healing that raised HP, or damage taken for another.
  * Witness: within range, and the act is against the holder, or the holder sees the actor or the victim, or is Blinded but can hear.
  * A single action creates at most one Imprint per holder and creature (several hits of one Attack action, or a hit that also inflicts a
    condition, record once).  Record the Deed uses the Reaction first; the Seal is the fallback (the holder needs its Reaction for the
    talents that answer a creature already carrying a Debt, which run before the damage event and so get the first claim).
  * Oath-breaking, betrayal, theft, keeping an oath, repaying a debt, removing a harmful condition and preventing damage are not detected
    (nothing in the fight's events carries them): the GM places those Imprints.  "Commanding a minion to harm" puts the Imprint on the
    visible actor; Debt Follows the Hand may move it.
  * Imprints last for the fight (there is no long rest inside one), so "do not fade" and "last until your next long rest" change nothing.
  * The Court's aura is 30 feet around the holder (it is centered on the holder and moves with it); its Debt and Grace clauses apply to a
    creature within it, once per creature per turn per clause.
Determinism: evented engine methods only; every placement, spend and payout is a logged event.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

DEBT, GRACE = "Debt Imprint", "Grace Imprint"
NAMES = {"debt": DEBT, "grace": GRACE}
BLOCK = "karma_ledger"
RECORD = "TAL_KARMA_RECORD_THE_DEED"
SEAL = "tianxia.talent.karma.ledger_seal_scripture"
COURT = "tianxia.talent.karma.court_of_cause_and_effect"
MUTUAL = "tianxia.talent.karma.oath_of_mutual_defense"
PREFIXES = ("TAL_KARMA_", "tianxia.talent.karma.")
COURT_CONDITION = "condition:typed.karma_court"
COURT_RANGE_FT, COURT_AURA_FT, RECORD_RANGE_FT = 120, 30, 60
_RECORDED = "_round_karma_recorded"  # on the holder: [round, uses]  ("_round_" keys survive the turn's reset)
_SEALED = "_round_karma_sealed"  # round of the holder's last Ledger Seal
_MUTUAL = "_round_karma_mutual"  # round of the holder's last Oath of Mutual Defense Grace
from .karma_causes import HARMFUL_CONDITIONS


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Feature block ``karma_ledger``: {"kind": "record" | "seal"}; each row carries the owner's numbers."""
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             "cl": int(numbers.get("cl") or 1)}]


# ------------------------------------------------------------------------------------------------------------ the holders
def features(engine: Any, actor: Any) -> set[str]:
    """The Karma mechanic ids ``actor`` compiled: from its typed actions, reaction rows and passive rows."""
    found: set[str] = set()
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            typed = (action.parameters or {}).get("typed") or {}
            found.update(str(typed.get(key)) for key in ("source", "option_of") if typed.get(key))
    for store in ("typed_reaction_rows", "typed_passive_rows"):
        found.update(str(row.get("feature_id")) for row in (getattr(engine, store, None) or {}).get(actor.entity_id, []) if row.get("feature_id"))
    return {name for name in found if name.startswith(PREFIXES)}


def holders(engine: Any) -> list[tuple[Any, set[str]]]:
    """[(actor, its Karma mechanic ids)] of every active typed character holding a ledger; the compiled catalog is read once per size."""
    cache = getattr(engine, "_karma_owned", None)
    if not cache or cache[0] != (len(engine.action_catalog), len(engine.state.actors)):
        cache = ((len(engine.action_catalog), len(engine.state.actors)),
                 {actor.entity_id: features(engine, actor) for actor in engine.state.actors.values() if actor.entity_id in engine.typed_actor_ids})
        engine._karma_owned = cache
    return [(actor, cache[1][actor.entity_id]) for actor in engine.state.actors.values() if actor.active and cache[1].get(actor.entity_id)]


def record_range(holder: Any) -> int:
    """Record the Deed's reach: 60 feet, 120 inside your Court, 300 while Karma-Sovereign Incarnation lasts (rider lane 9: its
    "your Record the Deed range becomes 300 feet"; combat/ext/karma_riders.py puts the condition on)."""
    if any(c.condition_id == "condition:typed.karma_sovereign" for c in holder.conditions.values()):
        return 300
    return COURT_RANGE_FT if court_up(holder) else RECORD_RANGE_FT


def court_up(holder: Any) -> bool:
    return any(c.condition_id == COURT_CONDITION for c in holder.conditions.values())


def capacity(holder: Any, owned: set[str]) -> int:
    """PB Imprints on one creature, one more with Ledger Seal Scripture."""
    return int(holder.proficiency_bonus) + (1 if SEAL in owned else 0)


# ------------------------------------------------------------------------------------------------------------- the store
def held(creature: Any, owner_id: str, kind: str | None = None) -> list[tuple[str, Any]]:
    """[(instance key, condition)] of the Imprints ``owner_id`` has on ``creature``, oldest first (``kind``: "debt", "grace" or both)."""
    from ..typed_executor import mark_condition_id

    ids = {mark_condition_id(name, owner_id): key for key, name in NAMES.items()}
    found = [(key, c) for key, c in creature.conditions.items() if ids.get(c.condition_id) and kind in (None, ids[c.condition_id])]
    return sorted(found, key=lambda pair: pair[1].applied_sequence)


def place(engine: Any, holder: Any, creature: Any, kind: str, source: str, cause: str) -> bool:
    """One Imprint of ``kind`` from ``holder`` on ``creature``; False when the creature already holds as many as the holder may place."""
    from ..typed_executor import mark_condition_id

    if not creature.active or creature.entity_id == holder.entity_id:
        return False
    if len(held(creature, holder.entity_id)) >= capacity(holder, features(engine, holder)):
        return False
    engine._apply_condition(creature, mark_condition_id(NAMES[kind], holder.entity_id), source, holder.entity_id, expires_on="UNTIL_REMOVED",
                            data={"cause": cause})
    return True


def spend(engine: Any, holder: Any, creature: Any, kind: str, count: int, source: str) -> int:
    """Spend up to ``count`` of ``holder``'s Imprints of ``kind`` on ``creature`` (oldest first); returns how many were spent."""
    spent = 0
    for key, condition in held(creature, holder.entity_id, kind)[:max(0, count)]:
        del creature.conditions[key]
        engine._append_event("CONDITION_REMOVED", source, actor_id=holder.entity_id, target_ids=(creature.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": key, "reason": "IMPRINT_SPENT"})
        spent += 1
    return spent


@effect("spend_imprint")
def spend_imprint(ctx: Any, eff: dict[str, Any]) -> None:
    """Typed effect {"type": "spend_imprint", "kind": "debt" | "grace", "count": n, "settles_strike": bool}: the ability's user spends
    Imprints it placed on the target creature.  ``settles_strike``: the damage that triggered a reaction cannot record its Debt again."""
    from ..typed_executor import _default_subject

    kind = "grace" if str(eff.get("kind")).lower() == "grace" else "debt"
    for subject in _default_subject(ctx, eff, harmful=kind == "debt"):
        spent = spend(ctx.engine, ctx.actor, subject, kind, int(eff.get("count") or 1), ctx.source)
        if spent and eff.get("settles_strike"):
            ctx.engine._karma_settled = (ctx.actor.entity_id, subject.entity_id)
        if spent:
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} spends {spent} {NAMES[kind]}{'s' if spent > 1 else ''} on {subject.display_name}.", (subject,))


# --------------------------------------------------------------------------------------------------------- Record the Deed
def _blind(creature: Any) -> bool:
    return any(str(c.condition_id).rsplit(".", 1)[-1] == "blinded" for c in creature.conditions.values())


def witnessed(engine: Any, holder: Any, actor: Any, victim: Any | None, range_ft: int) -> bool:
    """Whether ``holder`` Witnesses the act: it is within range, and is against the holder, or is seen (the actor or the victim), or is
    heard by a Blinded holder."""
    from .. import stealth
    from ..typed_executor import cant_hear

    if not holder.active or engine._distance_actor_to_actor(holder, actor) > range_ft:
        return False
    if victim is not None and victim.entity_id == holder.entity_id:
        return True
    if stealth.sees(engine, holder, actor) or (victim is not None and stealth.sees(engine, holder, victim)):
        return True
    return _blind(holder) and not cant_hear(holder)


def _cp_pool(actor: Any) -> str | None:
    from ..typed_executor import CP_POOLS

    pools = [pool for pool in CP_POOLS if actor.resource_maximums.get(pool, 0) > 0 and actor.resources.get(pool, 0) >= 1]
    return max(pools, key=lambda pool: actor.resources.get(pool, 0), default=None)


def _uses(engine: Any, holder: Any) -> int:
    flag = holder.turn_flags.get(_RECORDED)
    return int(flag[1]) if isinstance(flag, list) and flag and flag[0] == engine.state.round_number else 0


def record(engine: Any, holder: Any, owned: set[str], creature: Any, kind: str, victim: Any | None, cause: str, source: str | None = None) -> bool:
    """Record the Deed: one Imprint of ``kind`` on ``creature`` for ``cause``, if the holder may (room on the creature, a use left this
    round) and pays (its Reaction, or 1 CP with Ledger Seal Scripture)."""
    from .. import typed_reactions
    from .ability_source import compiled_feature_rows
    owned_row = next((r for r in compiled_feature_rows(engine, holder.entity_id, RECORD)
                      if r.get('block') == BLOCK and r.get('kind') == 'record'), None)
    if owned_row is None:
        return False
    if len(held(creature, holder.entity_id)) >= capacity(holder, owned) or _uses(engine, holder) >= (2 if court_up(holder) else 1):
        return False
    intent = getattr(engine, "_active_intent", None)
    key = f"{holder.entity_id}>{creature.entity_id}"
    if intent is not None and getattr(engine, "_karma_action", {}).get(key) is intent:
        return False  # one action creates one Imprint
    row = {**owned_row, "name": "Record the Deed", "ask": True}
    action = engine.action_catalog.get(source or "")
    action_name = action.display_name if action else ""
    if not action_name and source:
        # A protective Reaction is not necessarily an action-catalog entry.
        from ..status_text import printed_rules

        printed = printed_rules().get(source, "")
        action_name = printed.splitlines()[0].lstrip("# ") if printed else ""
    trigger = {"action_actor_id": creature.entity_id, "affected_id": creature.entity_id, "creature_name": creature.display_name,
               "source_definition_id": source, "action_name": action_name,
               "cause": cause, "imprint": NAMES[kind], "cost": "Reaction; no resource cost"}
    trigger.update( {'actor_id': creature.entity_id, 'target_id': victim.entity_id if victim else creature.entity_id,
               'karma_creature_id': creature.entity_id, 'karma_kind': kind, 'karma_cause': cause})
    how = None
    payment_pool = None
    if typed_reactions._can_react(engine, holder):
        if not typed_reactions._consent(engine, row, holder, "KARMIC_CAUSE", trigger=trigger):
            return False  # the player passed
        how = "Reaction"
    elif (SEAL in owned and holder.turn_flags.get(_SEALED) != engine.state.round_number and (pool := _cp_pool(holder)) is not None
          and typed_reactions._consent(engine, row, holder, "KARMIC_CAUSE",
                                      trigger={**trigger, "cost": f"1 Cultivation Point from your {pool.rsplit('.', 1)[-1].replace('_', ' ').title()} pool; no Reaction", "paying_pool": pool})):
        payment_pool = pool
        how = f"Ledger Seal, 1 {pool.rsplit('.', 1)[-1].replace('_', ' ').title()}"
    if how is None:
        return False
    from ..paid_relocation import activation

    with activation(engine, holder, RECORD):
        if payment_pool is None:
            typed_reactions._open(engine, row, holder, (creature.entity_id,), "KARMIC_CAUSE", {"cause": cause})
        else:
            engine._spend_resource(holder, payment_pool, 1, SEAL)
            holder.turn_flags[_SEALED] = engine.state.round_number
        if not place(engine, holder, creature, kind, RECORD, cause):
            return False
        holder.turn_flags[_RECORDED] = [engine.state.round_number, _uses(engine, holder) + 1]
        if intent is not None:
            engine._karma_action = {**getattr(engine, "_karma_action", {}), key: intent}
        total = len(held(creature, holder.entity_id))
        note(engine, RECORD, holder, f"{holder.display_name} records the deed ({how}): {creature.display_name} bears a {NAMES[kind]} ({cause}); "
             f"{total} of {capacity(holder, owned)}.", (creature,))
        return True


@hook("decision_text")
def record_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, str] | None:
    """Explain the specific witnessed deed without changing the decision contract."""
    if context.get("reaction_source_id") != f"reaction:typed.{RECORD}":
        return None
    from .ability_source import compiled_feature_rows
    if not compiled_feature_rows(engine, context.get('reactor_id'), RECORD):
        return None
    trigger = context.get("choice_trigger") or {}
    creature = engine.state.actors.get(trigger.get("action_actor_id"))
    name = trigger.get("creature_name") or (creature.display_name if creature is not None else "")
    if not name or not trigger.get("cause"):
        return None
    action = trigger.get("action_name") or "the triggering effect"
    return {"name": "Record the Deed", "cost": trigger["cost"],
            "trigger": f"{name}'s {action} caused {trigger['cause']}. Record a {trigger['imprint']} on {name}.",
            "summary": f"Place one {trigger['imprint']} on {name}. "
                       "An imprint records this deed for your Karma abilities to use later; placing it causes no damage or healing. "
                       "Debt Imprints let your Karma abilities punish the creature; Grace Imprints let them protect or bless it. "
                       "The table keeps it until spent or removed. Once per round (twice with Court of Cause and Effect)."}


# ------------------------------------------------------------------------------------------------------------ the Court
@effect("karma_court")
def karma_court(ctx: Any, eff: dict[str, Any]) -> None:
    """Court of Cause and Effect: the holder's Court stands (until its Concentration ends)."""
    holder, engine = ctx.actor, ctx.engine
    engine._remove_condition(holder, COURT_CONDITION, ctx.source)
    engine._apply_condition(holder, COURT_CONDITION, ctx.source, holder.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                            data={"label": "Court of Cause and Effect",
                                  "reading": "Record the Deed reaches 120 feet and may be used twice per round; a creature within 30 feet with one of your Debt "
                                             "Imprints that damages another takes your Proficiency Bonus in Psychic damage, and one with your Grace Imprint that heals "
                                             "or takes harm for another gains that much Temporary HP (once per creature per turn for each)."})
    note(engine, ctx.source, holder, f"{holder.display_name} opens the Court of Cause and Effect: Record the Deed reaches 120 feet and may be used twice per round.")


def _court_pays(engine: Any, creature: Any, kind: str, why: str) -> None:
    """Each Court whose holder's Debt (or Grace) the creature carries, within its aura: PB Psychic damage (Debt) or PB Temporary HP (Grace)."""
    turn = engine.state.round_number * 1000 + engine.state.current_slot_index
    for holder, _ in holders(engine):
        if not court_up(holder) or not held(creature, holder.entity_id, kind) or not creature.active:
            continue
        if engine._distance_actor_to_actor(holder, creature) > COURT_AURA_FT:
            continue
        flag = f"_round_karma_court_{kind}_{holder.entity_id}"
        if creature.turn_flags.get(flag) == turn:
            continue
        creature.turn_flags[flag] = turn
        amount = int(holder.proficiency_bonus)
        if kind == "debt":
            note(engine, COURT, holder, f"{creature.display_name} carries {holder.display_name}'s Debt and {why}: the Court deals {amount} psychic damage.", (creature,))
            engine._commit_damage(creature, amount, "PSYCHIC", COURT, holder.entity_id, None, reaction_depth=2)
        else:
            note(engine, COURT, holder, f"{creature.display_name} carries {holder.display_name}'s Grace and {why}: the Court gives {amount} Temporary HP.", (creature,))
            engine._grant_temp_hp(creature, amount, COURT, holder.entity_id)


# ------------------------------------------------------------------------------------------------------------- the Causes
def _actors(engine: Any, kwargs: dict[str, Any]) -> tuple[Any | None, Any | None]:
    ids = kwargs.get("target_ids") or ()
    return engine.state.actors.get(kwargs.get("actor_id") or ""), engine.state.actors.get(ids[0]) if ids else None


@hook("event")
def causes(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("DAMAGE_COMMITTED", "HEALING_APPLIED", "CONDITION_APPLIED") or not getattr(engine, "typed_actor_ids", None):
        return
    actor, victim = _actors(engine, kwargs)
    # Earlier subscribers and Court payments can append follow-up events.
    # The dispatcher retains the originating event independently of that tail.
    event = kwargs.get("originating_event")
    source = event.source_definition_id if event is not None else None
    if actor is None or victim is None or actor.entity_id == victim.entity_id:
        return
    payload = kwargs.get("payload") or {}
    if event_type == "DAMAGE_COMMITTED":
        settled = getattr(engine, "_karma_settled", None)  # (holder, creature): a Debt spent on this creature's strike (Return the Sting)
        if settled and actor.entity_id == settled[1]:
            engine._karma_settled = None  # the spend's own psychic damage comes from the holder and leaves it standing
        else:
            settled = None
        if int(payload.get("reduced_to") or 0) < 1:
            return
        _court_pays(engine, actor, "debt", f"damages {victim.display_name}")
        if actor.team_id == victim.team_id:
            return  # friendly fire is not recorded
        for holder, owned in holders(engine):
            if holder.team_id == victim.team_id and settled != (holder.entity_id, actor.entity_id):  # a spent Debt's strike records no new one
                if witnessed(engine, holder, actor, victim, record_range(holder)):
                    record(engine, holder, owned, actor, "debt", victim, f"meaningful damage to {victim.display_name}", source)
    elif event_type == "HEALING_APPLIED":
        if int(payload.get("after") or 0) <= int(payload.get("before") or 0):
            return
        _court_pays(engine, actor, "grace", f"restores {victim.display_name}'s HP")
        for holder, owned in holders(engine):
            if holder.team_id == actor.team_id and holder.entity_id != actor.entity_id \
                    and witnessed(engine, holder, actor, victim, record_range(holder)):
                record(engine, holder, owned, actor, "grace", victim, f"restored {victim.display_name}'s Hit Points", source)
    else:
        harmful = str(payload.get("condition_id") or "").rsplit(".", 1)[-1]
        if harmful in HARMFUL_CONDITIONS and actor.team_id != victim.team_id:
            for holder, owned in holders(engine):
                if holder.team_id == victim.team_id and witnessed(engine, holder, actor, victim, record_range(holder)):
                    record(engine, holder, owned, actor, "debt", victim, f"inflicted {harmful.title()} on {victim.display_name}", source)


@hook("turn_end")
def _forget_settled(engine: Any, actor: Any) -> None:
    engine._karma_settled = None


@hook("damage_shared")
def took_the_blow(engine: Any, taker: Any, target: Any, row: dict[str, Any], source_actor_id: str | None, taken: int) -> None:
    """A creature takes damage for another: Grace ("protects another creature at personal risk"); an Oath of Mutual Defense bond lets the
    Oath's caster place it without a Reaction, once per round; the Court gives the taker Temporary HP."""
    if taken < 1 or taker.entity_id == target.entity_id:
        return
    _court_pays(engine, taker, "grace", f"takes harm for {target.display_name}")
    owner = engine.state.actors.get(row.get("owner") or "")
    if row.get("kind") == "mutual_defense" and owner is not None and owner.active and owner.entity_id != taker.entity_id:
        owned = features(engine, owner)
        if MUTUAL in owned and owner.turn_flags.get(_MUTUAL) != engine.state.round_number and place(engine, owner, taker, "grace", MUTUAL, "took damage for a bound creature"):
            owner.turn_flags[_MUTUAL] = engine.state.round_number
            note(engine, MUTUAL, owner, f"{owner.display_name} places a Grace Imprint on {taker.display_name} without a Reaction (Oath of Mutual Defense): "
                 f"{len(held(taker, owner.entity_id))} of {capacity(owner, owned)}.", (taker,))
            return
    for holder, owned in holders(engine):
        if holder.team_id == taker.team_id and holder.entity_id != taker.entity_id \
                and witnessed(engine, holder, taker, target, record_range(holder)):
            record(engine, holder, owned, taker, "grace", target, f"took damage for {target.display_name}", row.get("feature_id"))
