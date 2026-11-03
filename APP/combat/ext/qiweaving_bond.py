"""Qiweaving's Bond package: the Qi Bond talents the table can actually apply (auto lanes AUTO12 2026-10-04,
AUTO12f1 and AUTO12r1f1 2026-10-05).

Source of truth (owner text, APP/authority/typed_mechanics/rules_text.json):
  Qi Bond (base ability): "While the bond lasts, you may use your Action on each of your turns to apply one Bond talent
    you know to the target."  On a hit it marks the target with the Qi Bond mark (typed data:
    authority/typed_mechanics/reviewed_final.d/riders_c11.json -- a mark that lasts as long as the Concentration).
  Draw Current - Bond: "When you apply this Bond talent to an unwilling bonded creature, it makes a Constitution saving
    throw. Failed Save: The target loses 1 CP, and you gain 1 Temporary CP. ... A creature cannot lose more CP to your
    Draw Current than your Proficiency Bonus per long rest. If the target has no CP, this talent has no effect ..."
  Feed Current - Bond: "When you apply this Bond talent to a willing bonded creature, spend 1 or more CP, up to your
    Proficiency Bonus. The target gains the same amount as Temporary CP. ... A creature can benefit from your Feed
    Current once per short rest."
  Throttle Current - Bond: "When you apply this Bond talent to a bonded creature, it makes a Constitution saving throw.
    Failed Save: The next technique the target activates before the start of your next turn that costs CP costs 1
    additional CP. If the target cannot or will not pay the additional CP, the technique fails and any Action spent on it
    is lost. The original CP is not spent. ... A creature can suffer this added cost from you only once per round."
  Circuit Lock: "When you apply Throttle Current, you may intensify it into a Circuit Lock. The bonded target makes a
    Constitution saving throw. Failed Save: Until the end of your next turn, the target cannot spend more CP on a single
    technique than your Proficiency Bonus. Successful Save: Throttle Current applies normally. ... Circuit Lock does not
    prevent a creature from using a Secret Inheritance, but the inheritance's visible Qi pattern may become strained or
    narratively exposed at the GM's discretion."
  Read Current - Bond: "When you apply this Bond talent, learn two of the following facts about the bonded target ..."
  Shared Reservoir: "When you maintain Qi Bond on a willing creature, you and the bonded creature may transfer CP between
    yourselves as an Action. The creature giving CP chooses how much to give, up to your Proficiency Bonus. Transferred
    CP cannot exceed the recipient's normal maximum CP. A creature can receive CP through your Shared Reservoir once per
    long rest."

Why a plug-in.  A Bond talent is applied to a creature the caster has already marked, not to a target it chooses, and
two of them change what that creature may *spend* on a later activation the caster does not choose.  Neither shape is an
ordinary typed effect on a chosen target, so the actions and the two standing rules are built here; the typed
records keep the printed line and the table announces what happened, so none of these talents leaves a "Rule reminder"
(see authority/typed_mechanics/reviewed_final.d/zz_qiweaving_auto12.json).

How it runs.
  * Each Bond talent the character owns compiles to one Action (``compile_actions``), aimed at any creature and offered
    (``candidate_allowed``) only against a creature carrying *this* character's Qi Bond mark inside the bond's range.  The
    bond's printed range grows with Meridian Grammar / Court of Ten Thousand Currents / Sovereign Qiweaver Incarnation, so
    the range is read from the compiled Qi Bond action when the character has one.
  * Every printed Constitution save goes through the engine's own save path (``_roll_save``: the caster's Cultivation Save
    DC, the target's save bonuses, Advantage/Disadvantage rows and the after-save reactions all still apply).
  * Draw Current takes the 1 point, capped at the caster's Proficiency Bonus per long rest and refused when the target
    has none.
  * Throttle Current leaves a dated marker that runs to the START of the CASTER's next turn (its printed "before the
    start of your next turn"), read at the target's next activation (``technique_start``, which runs after that
    activation's printed cost is paid).  There the TARGET is asked whether it will pay the extra point -- the printed
    words are "cannot or will not pay", and refusing is the target's own choice -- and on a refusal the printed cost is
    returned in full and the activation stopped ("the technique fails and any Action spent on it is lost ... The original
    CP is not spent").  The AI pays whenever it can.  "A creature can suffer this added cost from you only once per
    round" is a round clock on the target, so a second application in the same round is refused.
  * Circuit Lock's printed ceiling -- "the target cannot spend more CP on a single technique than your Proficiency
    Bonus" -- is a restriction on what the target may *spend*, not a discount: a technique priced above the cap is not
    affordable, so it is left out of that creature's menu by the documented ``candidate_allowed`` hook (both the player's
    and the AI's) and the documented ``candidate_unavailability`` hook says why on the button.  Nothing is refunded and
    no technique is ever made cheaper.  Two printed details the branch dropped are honoured here: the printed exception
    "Circuit Lock does not prevent a creature from using a Secret Inheritance", so one is never withheld however far
    above the cap it costs (read from the owner's own record by qiweaving_common.is_secret_inheritance), and where more
    than one caster has locked the same creature the STRONGEST lock is the one that holds, because each caster sets the
    cap from its own Proficiency Bonus.  The marker runs to the end of the CASTER's next turn (the printed "until the end
    of your next turn"), and a successful save falls back to Throttle Current, as printed.  Partly manual: a technique
    whose Cultivation Point cost is chosen at play ("spend up to N"), or one that starts outside the normal menu (a
    Reaction, a triggered activation), is not priced by the menu and so is not withheld -- the general seam this needs is
    a per-creature ceiling read in the shared cost path (combat/ext/technique_costs.py), which is a saved-fight lock
    item.  Until it exists the sheet says so, and so does every line the table prints when a lock lands, because a limit
    that is only partly automatic must never be announced as automatic in full.
  * Read Current reads its printed facts off the fight state; the player picks two BY CATEGORY (the labels name the kind
    of fact, never its answer, so nothing is revealed before the pick) and each is then answered plainly or left out when
    the fight holds nothing to answer it.  "The strongest visible sphere resonance" is read as the sphere of the highest
    Pattern Rank among the patterns on the target, ties reported together.
  * Shared Reservoir moves Cultivation Points between the bonded pair in one Action, in either direction, up to the
    caster's Proficiency Bonus, capped by the RECIPIENT's room in each direction (nothing is drained and thrown away).
    The GIVER is asked every time -- both directions, and a one-point transfer exactly like a larger one -- because the
    printed words are "The creature giving CP chooses how much to give", and it may choose none, which spends the Action
    and moves nothing.  "A creature can receive CP ... once per long rest" is counted on the creature that actually
    received them, in either direction.
  * Feed Current asks for and charges the caster's own 1..Proficiency Bonus spend.  The Temporary Cultivation Points the
    recipient gains are not spendable at this table yet -- that needs a spendable temporary pool in the sealed gate2
    engine, so it is listed as a lock-round item and announced in the log here instead.

Default-inert: without the Qi Bond mark, or without one of these talents, no action is offered and every hook returns
early.  No other fighter's costs, marks or menu change.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .qiweaving_common import bond_reach, is_secret_inheritance

BOND = "TAL_QIWEAVING_QI_BOND"
DRAW = "TAL_QIWEAVING_DRAW_CURRENT"
FEED = "TAL_QIWEAVING_FEED_CURRENT"
THROTTLE = "TAL_QIWEAVING_THROTTLE_CURRENT"
READ = "TAL_QIWEAVING_READ_CURRENT"
LOCK = "TAL_QIWEAVING_CIRCUIT_LOCK"
RESERVOIR = "TAL_QIWEAVING_SHARED_RESERVOIR"

MARK = "qi_bond"
THROTTLED = "condition:typed.qiweaving_throttled"
LOCKED = "condition:typed.qiweaving_circuit_lock"
DRAINS = "_round_qiweaving_draw_current"   # turn flags whose key starts with "_round_" survive turn resets
FED = "_round_qiweaving_feed_current"
RECEIVED = "_round_qiweaving_reservoir_received"
# "A creature can suffer this added cost from you only once per round": a round clock on the target, named per caster,
# in the once_per_round: namespace that survives the turn reset (gate2_engine._system_start_turn).
def _throttled_key(caster: Any) -> str:
    return f"once_per_round:qiweaving_throttle_current:{caster.entity_id}"

# (mechanic id, printed name, extra CP, target kind, must be on the caster's side, must hold a pool)
_TALENTS: tuple[tuple[str, str, int, str, bool, bool], ...] = (
    (DRAW, "Draw Current", 0, "ANY_CREATURE", False, False),
    (FEED, "Feed Current", 0, "ALLY_OR_SELF", True, False),
    (THROTTLE, "Throttle Current", 0, "ANY_CREATURE", False, False),
    (READ, "Read Current", 0, "ANY_CREATURE", False, False),
    (LOCK, "Circuit Lock", 2, "ANY_CREATURE", False, False),
    (RESERVOIR, "Shared Reservoir", 0, "ALLY_OR_SELF", True, True),
)

# The printed lines the table still decides, in plain rules words: no engine talk, no internal ids.
RIDERS: dict[str, list[str]] = {
    DRAW: ["The Temporary Cultivation Point you gain lasts until the end of your next turn and may be spent on sphere "
           "techniques and Path features. Tell the GM what you spend it on until then."],
    FEED: ["The Temporary Cultivation Points the creature gains last 1 minute and may be spent only on sphere techniques "
           "and Path features. Tell the GM what it spends them on until then."],
LOCK: ["This lock does not stop a creature from using a Secret Inheritance, but the GM may decide that its Qi pattern "
       "looks strained or gives it away.",
       "The table holds a creature back from a technique that costs more than the limit. A technique whose Cultivation "
       "Point cost is chosen as you play, or one that starts without being picked from the creature's list (a Reaction, "
       "or something that triggers), is not on that list: tell your GM, and the limit is applied by hand."],
}
# What the players are told at the moment the lock lands, so the partly automatic limit is never presented as automatic
# in full (change standard 13).  The same wording rides the ability above, so it reaches the sheet as well.
_CEILING_BY_HAND = ("The table holds this creature back from any technique that costs more. If a technique's Cultivation "
                    "Point cost is chosen as you play, or the technique starts as a Reaction rather than from this "
                    "creature's list, tell your GM: the limit is then applied by hand.")


# ------------------------------------------------------------------------------------------------ helpers
def _pb(ctx: Any) -> int:
    return int((ctx.numbers or {}).get("pb") or ctx.actor.proficiency_bonus)


def _pool_word(pool: str) -> str:
    from ..resource_labels import resource_name

    return resource_name(pool)


def _cp_pool(actor: Any) -> str | None:
    """The Cultivation Point pool this creature spends from: the one holding most among its printed pools."""
    from ..typed_executor import CP_POOLS

    pools = [pool for pool in CP_POOLS if actor.resource_maximums.get(pool, 0) > 0]
    return max(pools, key=lambda pool: actor.resources.get(pool, 0), default=None)


def _markers(holder: Any, condition_id: str) -> list[tuple[str, Any]]:
    return [(key, condition) for key, condition in holder.conditions.items() if condition.condition_id == condition_id]


def _uses(actor: Any, flag: str, entity_id: str) -> int:
    return sum(1 for entry in (actor.turn_flags.get(flag) or []) if entry == entity_id)


def _remember(actor: Any, flag: str, entity_id: str) -> None:
    actor.turn_flags[flag] = [*(actor.turn_flags.get(flag) or []), entity_id]


def _caster(engine: Any, condition: Any) -> Any:
    return engine.state.actors.get(str(condition.source_actor_id or "")) or engine.state.current_actor()


def _bonded(holder: Any, owner_id: str) -> bool:
    from ..typed_executor import bears_mark

    return bool(bears_mark(holder, owner_id, MARK))


def _sphere_of(engine: Any, source_id: str) -> str:
    action = engine.action_catalog.get(str(source_id or ""))
    return str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("sphere") or "")


@hook("choice_reactors")
def reservoir_givers(engine: Any) -> tuple[str, ...]:
    """Enroll bonded potential givers independently of unrelated reaction plans.

    Read the saved action catalog and bond marks, so reloads retain ownership.
    The service asks manual givers and lets AI givers answer automatically.
    No Shared Reservoir action or bond means no additional chooser.
    """
    owners = {action.owner_id for action in engine.action_catalog.values()
              if (getattr(action, "parameters", None) or {}).get("bond_talent") == RESERVOIR}
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if actor.active and any(_bonded(actor, owner) for owner in owners))


# ------------------------------------------------------------------------------------------------ the actions
@hook("compile_actions")
def bond_talents(info: dict[str, Any]) -> list[Any] | None:
    """One Action per owned Bond talent, aimed at any creature; only a bonded one is ever offered."""
    owned = set(info["owned_ids"])
    mine = [row for row in _TALENTS if row[0] in owned] if BOND in owned else []
    if not mine:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    primary = RESOURCE_IDS.get(str(info.get("primary") or ""))
    numbers = info.get("numbers") or {}
    reach = bond_reach(info)
    made = []
    for mechanic, name, extra_cp, target_kind, ally, giver in mine:
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{mechanic}.bond", display_name=name, owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=target_kind, range_ft=reach,
            costs=((primary, extra_cp),) if (primary and extra_cp) else (),
            parameters={"typed": {"effects": [{"type": "bond_talent", "talent": mechanic, "applies_to": "target"}],
                                  "numbers": dict(numbers), "duration": {"kind": "instant"},
                                  "riders": list(RIDERS.get(mechanic, ())), "source": mechanic,
                                  "sphere": "tianxia.sphere.qiweaving"},
                        "expected_damage": 0, "bond_talent": mechanic,
                        "bond_needs_ally": ally, "bond_needs_pool": giver}))
    # Qi Bond: "A willing creature, an unattended object, or an Active Qi Pattern you created is bonded automatically."
    # The typed Qi Bond action is a ranged Cultivation Attack (the unwilling case), so the willing creature gets its own
    # no-roll Bonus Action; objects are a separate target domain this table does not model.  It appears once the
    # character owns a Bond talent, because that is when the bond has something to be used for; a Qiweaver with no Bond
    # talent keeps exactly the menu they had.
    made.append(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{BOND}.willing", display_name="Qi Bond (willing creature)",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
        range_ft=reach, costs=(),
        parameters={"typed": {"effects": [{"type": "mark", "mark": MARK, "applies_to": "target",
                                           "duration": {"kind": "concentration"},
                                           "evidence": "A willing creature ... is bonded automatically."}],
                              "numbers": dict(numbers), "duration": {"kind": "minutes", "amount": 1, "concentration": True},
                              "riders": [], "source": BOND, "sphere": "tianxia.sphere.qiweaving"},
                    "expected_damage": 0, "bond_willing": True}))
    return made


@hook("candidate_allowed")
def only_a_bonded_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    talent = (getattr(action, "parameters", None) or {}).get("bond_talent")
    if not talent:
        return None
    reach = int(getattr(action, "range_ft", 0) or 0)
    holders = [engine.state.actors[entity] for entity in (getattr(candidate, "target_ids", None) or ())
               if entity in engine.state.actors]
    if not holders:
        return False
    parameters = action.parameters or {}
    for holder in holders:
        if not holder.active or not _bonded(holder, actor.entity_id):
            return False
        if reach and engine._distance_actor_to_actor(actor, holder) > reach:
            return False
        if parameters.get("bond_needs_ally") and holder.team_id != actor.team_id:
            return False
        if parameters.get("bond_needs_pool") and _cp_pool(holder) is None:
            return False
    return True


# ------------------------------------------------------------------------------------------------ the printed line each talent runs
@effect("bond_talent")
def bond_talent(ctx: Any, row: dict[str, Any]) -> None:
    handler = _HANDLERS.get(str(row.get("talent") or ""))
    holder = ctx.target
    if handler is None or holder is None or not holder.active:
        return
    if not _bonded(holder, ctx.actor.entity_id):
        ctx.rider(f"{holder.display_name} is not bound to you, so this Bond talent has nothing to work on.")
        return
    handler(ctx, holder)


def _fails(ctx: Any, holder: Any, evidence: str) -> bool:
    """The printed Constitution saving throw against the caster's Cultivation Save DC; True when it fails."""
    dc = int((ctx.numbers or {}).get("save_dc") or 10)
    roll = ctx.engine._roll_save(holder, "CON", dc, ctx.source)
    if roll is None:
        return False
    failed = roll.total < dc
    note(ctx.engine, ctx.source, ctx.actor, f"{holder.display_name} makes a Constitution saving throw for {evidence}: "
         f"{roll.total} against DC {dc} -- {'it fails' if failed else 'it succeeds'}.", (holder,))
    return failed


# ------------------------------------------------------------------------------------------------- Draw Current
def _draw(ctx: Any, holder: Any) -> None:
    if holder.team_id == ctx.actor.team_id:
        ctx.rider("Draw Current takes Cultivation Points from an unwilling bonded creature; bond a hostile creature to use it.")
        return
    pool = _cp_pool(holder)
    if pool is None or holder.resources.get(pool, 0) < 1:
        ctx.rider(f"{holder.display_name} has no Cultivation Points for Draw Current to take.")
        return
    pb = _pb(ctx)
    if _uses(ctx.actor, DRAINS, holder.entity_id) >= pb:
        ctx.rider(f"{holder.display_name} has already lost Cultivation Points to your Draw Current for this long rest "
                  f"({pb}, your Proficiency Bonus).")
        return
    if not _fails(ctx, holder, "Draw Current"):
        return
    ctx.engine._spend_resource(holder, pool, 1, ctx.source)
    _remember(ctx.actor, DRAINS, holder.entity_id)
    note(ctx.engine, ctx.source, ctx.actor, f"Draw Current: {holder.display_name} loses 1 {_pool_word(pool)} and you gain 1 "
         "Temporary Cultivation Point, which lasts until the end of your next turn.", (holder,))


# ------------------------------------------------------------------------------------------------- Feed Current
def is_feed_current_source(source: str) -> bool:
    """Whether a source definition id names this plug-in's Feed Current bond talent.

    Feed Current's typed actions are compiled as ``action:typed.<short>.TAL_QIWEAVING_FEED_CURRENT.bond``
    (see :func:`compile_actions`). A rider whose printed trigger names Feed Current checks the documented
    ``temporary_cp_granted`` provenance against this one predicate, so the granting plug-in stays the single
    place that knows its own source id and another grant of the same kind is left alone.
    """
    return f".{FEED}." in str(source or "") or str(source or "") == FEED


def _feed(ctx: Any, holder: Any) -> None:
    pool = _cp_pool(ctx.actor)
    affordable = min(_pb(ctx), int(ctx.actor.resources.get(pool, 0))) if pool else 0
    if affordable < 1:
        ctx.rider("Feed Current needs 1 or more Cultivation Points, up to your Proficiency Bonus.")
        return
    if _uses(ctx.actor, FED, holder.entity_id):
        ctx.rider(f"{holder.display_name} can benefit from your Feed Current only once per short rest.")
        return
    labels = {str(n): f"{n} {_pool_word(pool)}{'s' if n > 1 else ''}" for n in range(1, affordable + 1)}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "feed_current", ctx.actor.entity_id, holder.entity_id), ctx.actor,
                 CHOICE + "feed_current", list(labels), labels=labels, minimum=1, maximum=1, target_id=holder.entity_id,
                 name="Feed Current", preferred=[str(affordable)],
                 prompt=f"Feed Current on {holder.display_name}: how many Cultivation Points do you spend?") or [str(affordable)]
    amount = max(1, min(affordable, int(picked[0])))
    ctx.engine._spend_resource(ctx.actor, pool, amount, ctx.source)
    _remember(ctx.actor, FED, holder.entity_id)
    # General seam: anything that grants a printed Temporary CP to a creature (Shared Breath Method's
    # Feed Current rider, and any future grant of the same kind) subscribes here. Default-inert: with
    # no provider registered this returns an empty list and nothing about Feed Current changes.
    from .. import ext
    ext.run("temporary_cp_granted", ctx.engine, holder, ctx.actor, amount, ctx.source)
    note(ctx.engine, ctx.source, ctx.actor, f"Feed Current: you spend {amount} {_pool_word(pool)} and {holder.display_name} gains "
         f"{amount} Temporary Cultivation Points, lasting 1 minute and spendable only on sphere techniques and Path features.",
         (holder,))


# ------------------------------------------------------------------------------------------------- Throttle Current / Circuit Lock
def _throttled_mark(ctx: Any, holder: Any) -> None:
    """The dated Throttle Current marker on a bonded creature: its extra point lasts until the START of the caster's
    next turn (the printed "before the start of your next turn"), not the end of the target's."""
    from ..typed_executor import stated_expiry

    expires = stated_expiry(ctx, {"expires_on": "START_OF_SOURCE_NEXT_TURN"}, holder, condition=True)
    ctx.engine._apply_condition(holder, THROTTLED, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"label": "Throttle Current",
                                      "reading": f"{ctx.actor.display_name}'s Throttle Current: the next technique this creature activates before "
                                                 f"the start of {ctx.actor.display_name}'s next turn that costs Cultivation Points costs 1 more. "
                                                 "If it cannot or will not pay that extra point the technique fails, the Action is lost, "
                                                 "and the Cultivation Points it had already spent are returned."})


def _arm_throttle(ctx: Any, holder: Any) -> bool:
    """Put the dated surcharge marker on ``holder`` and stamp the round clock; False when the target has already
    suffered this added cost from this caster this round ("only once per round"), which leaves the first one alone."""
    key = _throttled_key(ctx.actor)
    if holder.turn_flags.get(key) == int(ctx.engine.state.round_number):
        ctx.rider(f"{holder.display_name} has already suffered this added cost from your Throttle Current this round.")
        return False
    holder.turn_flags[key] = int(ctx.engine.state.round_number)
    _throttled_mark(ctx, holder)
    return True


def _throttle(ctx: Any, holder: Any) -> None:
    if not _fails(ctx, holder, "Throttle Current"):
        return
    _arm_throttle(ctx, holder)


def _lock(ctx: Any, holder: Any) -> None:
    from ..typed_executor import stated_expiry

    pb = _pb(ctx)
    if not _fails(ctx, holder, "Circuit Lock"):
        # "When you apply Throttle Current, you may intensify it into a Circuit Lock" is ONE save, and "Successful Save:
        # Throttle Current applies normally": a target that saves against the intensification is throttled, not locked.
        # Its surcharge is Throttle Current's printed effect, so it is applied here without a second save.
        _arm_throttle(ctx, holder)
        return
    # "Until the end of your next turn": the caster's own next turn (END_OF_SOURCE_TURN_AT, read off the caster's turn
    # counter), named from the printed words rather than guessed from the target's turn.
    expires = stated_expiry(ctx, {"evidence": "Until the end of your next turn, the target cannot spend more CP on a "
                                             "single technique than your Proficiency Bonus."}, holder, condition=True)
    ctx.engine._apply_condition(holder, LOCKED, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"cap": pb, "label": "Circuit Lock",
                                      "reading": f"{ctx.actor.display_name}'s Circuit Lock: until the end of its next turn this "
                                                 f"creature cannot spend more than {pb} Cultivation Points on a single "
                                                 f"technique, and a Secret Inheritance is never held back by it. "
                                                 f"{_CEILING_BY_HAND}"})
    note(ctx.engine, ctx.source, ctx.actor, f"Circuit Lock: {holder.display_name} cannot spend more than {pb} Cultivation "
         f"Points on a single technique until the end of your next turn, and a Secret Inheritance is never held back by "
         f"it. {_CEILING_BY_HAND}", (holder,))


def _cp_spend(action: Any) -> int:
    """What one activation's printed cost spends in Cultivation Points."""
    from ..typed_executor import CP_POOLS

    return sum(int(amount) for resource, amount in (getattr(action, "costs", None) or ()) if resource in CP_POOLS)


def _active_locks(actor: Any) -> list[tuple[int, Any]]:
    """(cap, condition) for every Circuit Lock still on this creature, strongest (lowest) cap first.

    Each caster sets the ceiling from its OWN Proficiency Bonus, so two casters can hold one creature at once and the
    binding one is the strongest -- the smallest cap.  The order the markers happen to be stored in is not the rule, so
    the caps are sorted rather than taken first-found (AUTO12r1f1 finding 3).  A marker with no stored cap (an older
    saved fight) is ignored, which leaves that one restriction off rather than reading as no limit at all."""
    rows = [(int((condition.data or {}).get("cap") or 0), condition) for _key, condition in _markers(actor, LOCKED)]
    return sorted(((cap, condition) for cap, condition in rows if cap > 0), key=lambda row: row[0])


def _locked_below(actor: Any, action: Any) -> int:
    """The strongest Circuit Lock cap this action breaks, or 0.  "cannot spend more CP on a single technique than your
    Proficiency Bonus" is a ceiling on spending, so a technique priced above it is not affordable for that creature.

    The order of the questions is the point (AUTO12r2f1).  The creature's own conditions are read first and the printed
    classification is asked last, so a creature with no Circuit Lock -- which is every fighter in every ordinary fight --
    costs one condition lookup and no Qiweaving work at all.  Only an action that really is priced above the cap is
    worth the classification, and only that one can be a Secret Inheritance.

    The printed exception is honoured: "Circuit Lock does not prevent a creature from using a Secret Inheritance", so a
    Secret Inheritance is never withheld here, however far above the cap it costs (AUTO12r1f1 finding 2)."""
    if action is None:
        return 0
    locks = _active_locks(actor)
    if not locks:
        return 0
    cap = locks[0][0]
    if _cp_spend(action) <= cap:
        return 0
    return 0 if is_secret_inheritance(action) else cap


@hook("candidate_allowed")
def circuit_lock_ceiling(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A Circuit Locked creature is not offered a technique it cannot pay for: it "cannot spend more CP on a single
    technique than your Proficiency Bonus" until the end of the caster's next turn, and where more than one caster has
    locked it, the strongest of those limits is the one that holds.  Only the ceiling is withheld -- every other
    technique, every Secret Inheritance, and the whole menu of every other fighter is untouched.  Nothing is refunded and
    no technique is ever made cheaper; ``circuit_lock_explains_its_ceiling`` says why on the button."""
    return False if _locked_below(actor, action) else None


@hook("candidate_unavailability")
def circuit_lock_explains_its_ceiling(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    """Why the Circuit Locked technique is not on the menu, in the plain words of the printed line, naming the caster
    whose lock is the one that holds.  Default-inert: None for every other refusal, so the table's usual explanation
    still shows."""
    if _locked_below(actor, action):
        cap, lock = _active_locks(actor)[0]
        holder = _caster(engine, lock)
        return (f"Circuit Lock: until the end of {holder.display_name}'s next turn you cannot spend more than {cap} Cultivation "
                f"Points on a single technique, and {getattr(action, 'display_name', 'this technique')} costs more than that.")
    return None


@hook("technique_start")
def throttle_surcharge(engine: Any, actor: Any, action: Any) -> bool | None:
    """Throttle Current's extra point, read at the target's next activation.

    The activation's printed cost is already paid, so the extra point is charged on top.  The TARGET is asked whether it
    will pay ("If the target cannot or will not pay the additional CP"), and refusing returns the printed cost and stops
    the activation, which is what "the technique fails and any Action spent on it is lost. The original CP is not spent"
    means at this table.  An AI target pays whenever it can.
    """
    from ..typed_executor import CP_POOLS
    from .needle import CHOICE, ask, checkpoint_id

    listed = tuple(getattr(action, "costs", None) or ())
    paid_cp = [(resource, amount) for resource, amount in listed if resource in CP_POOLS and amount > 0]
    if not paid_cp:
        return None
    held_markers = _markers(actor, THROTTLED)
    if not held_markers:
        return None
    from ..technique_costs import refund

    # All these restrictions apply to this next activation. Consume them together:
    # _remove_condition removes every instance with this condition name.
    engine._remove_condition(actor, THROTTLED, held_markers[0][1].source_definition_id)
    for _key, held in held_markers:
        resource, amount = paid_cp[0]
        affordable = actor.resources.get(resource, 0) >= 1
        intent = getattr(engine, "_active_intent", None)
        wants = ask(engine, intent, checkpoint_id(engine, "throttle_current", str(held.source_actor_id or ""), actor.entity_id),
                    actor, CHOICE + "throttle_current", ["pay", "refuse"],
                    labels={"pay": f"Pay the extra 1 {_pool_word(resource)} and use {action.display_name}",
                            "refuse": f"Refuse the extra 1 {_pool_word(resource)}: {action.display_name} fails and the Action is lost"},
                    minimum=1, maximum=1, name="Throttle Current",
                    preferred=["pay"] if affordable else ["refuse"],
                    prompt=(f"Throttle Current ({engine.state.actors[str(held.source_actor_id)].display_name if held.source_actor_id in engine.state.actors else 'a Qiweaver'})"
                            f" makes your {action.display_name} cost 1 extra {_pool_word(resource)}. Do you pay it?")) \
            or ["pay" if affordable else "refuse"]
        if affordable and wants[0] == "pay":
            engine._spend_resource(actor, resource, 1, held.source_definition_id)
            note(engine, held.source_definition_id, _caster(engine, held),
                 f"Throttle Current: {actor.display_name} pays 1 extra {_pool_word(resource)} for {action.display_name}.", (actor,))
            continue
        for pool, spent in paid_cp:
            if spent:
                refund(engine, actor, action.source_definition_id, listed, pool, spent, held.source_definition_id)
        reason = "will not pay" if affordable else "cannot pay"
        note(engine, held.source_definition_id, _caster(engine, held),
             f"Throttle Current stops {actor.display_name}'s {action.display_name}: it {reason} the extra {_pool_word(resource)}, so "
             "the technique fails, the Action is lost, and the Cultivation Points already spent are returned.", (actor,))
        return True  # a failed technique cannot incur another surcharge after refund
    return None


# ------------------------------------------------------------------------------------------------- Read Current
# The six printed facts, each with the question the table is asked about it.  The menu names the KIND of fact only: the
# answer is revealed after the pick, so choosing two of six does not hand over six answers.
_FACTS: tuple[tuple[str, str], ...] = (
    ("cp", "How many Cultivation Points it has left"),
    ("concentration", "Whether it is maintaining Concentration"),
    ("patterns", "How many Active Qi Patterns affect it (none, one, several or many)"),
    ("sphere", "The strongest sphere resonance on it"),
    ("stability", "Whether its circulation is stable or disturbed"),
    ("rank", "Whether a visible Active Qi Pattern on it is of low Pattern Rank"),
)


def _strongest_sphere(engine: Any, found: list[tuple[str, str, Any]]) -> str:
    """The sphere of the highest Pattern Rank among the Active Qi Patterns on the creature: the table reads "the strongest
    visible sphere resonance" as the resonance of the pattern that took the most Cultivation Points to put up.  Ties are
    reported together rather than silently picking one."""
    from .qiweaving_unweave import pattern_rank

    best, spheres = -1, []
    for _kind, _key, item in found:
        rank = pattern_rank(engine, item)
        sphere = _sphere_of(engine, item.source_definition_id)
        if not sphere:
            continue
        if rank > best:
            best, spheres = rank, [sphere]
        elif rank == best and sphere not in spheres:
            spheres.append(sphere)
    return ", ".join(sorted(sphere.rsplit(".", 1)[-1].replace("_", " ") for sphere in spheres))


def _fact_text(engine: Any, holder: Any, key: str, found: list[tuple[str, str, Any]], pb: int) -> str:
    from .qiweaving_unweave import pattern_rank

    if key == "cp":
        pool = _cp_pool(holder)
        return (f"it has {int(holder.resources.get(pool, 0))} {_pool_word(pool)} left" if pool
                else "it has no Cultivation Points to read")
    if key == "concentration":
        return "it is maintaining Concentration" if holder.concentration is not None else "it is not maintaining Concentration"
    if key == "patterns":
        count = len(found)
        category = "none" if count == 0 else "one" if count == 1 else "several" if count < 4 else "many"
        return f"{count} Active Qi Pattern(s) affect it -- {category}"
    if key == "sphere":
        spheres = _strongest_sphere(engine, found)
        return f"the strongest visible sphere resonance on it is {spheres}" if spheres else ""
    if key == "stability":
        if any(condition.condition_id == "condition:typed.turbulent" for condition in holder.conditions.values()):
            return "its circulation is turbulent"
        strained = any(condition.condition_id.endswith("riposte") or "suppressed" in condition.condition_id
                       for condition in holder.conditions.values())
        return "its circulation is strained" if strained else "its circulation is stable"
    low = [item for _kind, _key, item in found if pattern_rank(engine, item) <= pb]
    return ("one Active Qi Pattern on it is of low Pattern Rank, no higher than your Proficiency Bonus" if low
            else "no Active Qi Pattern on it is of low Pattern Rank, or it bears none at all")


def _read(ctx: Any, holder: Any) -> None:
    """"learn two of the following facts about the bonded target": the player picks two of the six printed facts BY KIND
    (the options name the kind, never its answer) and each is then answered in plain words."""
    from .qiweaving_unweave import patterns

    pb = _pb(ctx)
    found = patterns(ctx.engine, holder)
    wanted = [key for key, _question in _FACTS if _fact_text(ctx.engine, holder, key, found, pb)]
    if len(wanted) < 2:
        note(ctx.engine, ctx.source, ctx.actor, f"Read Current on {holder.display_name}: there is too little on it to read.",
             (holder,))
        return
    answers = {key: _fact_text(ctx.engine, holder, key, found, pb) for key in wanted}
    labels = {key: question for key, question in _FACTS if key in wanted}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "read_current", ctx.actor.entity_id, holder.entity_id), ctx.actor,
                 CHOICE + "read_current", wanted, labels=labels, minimum=2, maximum=2, target_id=holder.entity_id,
                 name="Read Current", preferred=wanted[:2], default_count=2,
                 prompt=f"Read Current on {holder.display_name}: which two of these do you read?") or wanted[:2]
    for key in picked[:2]:
        note(ctx.engine, ctx.source, ctx.actor, f"Read Current on {holder.display_name}: {answers[key]}", (holder,))


# ------------------------------------------------------------------------------------------------- Shared Reservoir
def _cp_phrase(amount: int, pool: str) -> str:
    """The amount of Cultivation Points, said properly: the sheet's own name for the pool, plural above one."""
    return f"{amount} {_pool_word(pool)}"   # the sheet's own name for the pool; no plural ("4 Stamina", as the sheet says it)


def _room(actor: Any, pool: str) -> int:
    """How many Cultivation Points this creature may still take ("Transferred CP cannot exceed the recipient's normal
    maximum CP")."""
    return max(0, int(actor.resource_maximums.get(pool, 0)) - int(actor.resources.get(pool, 0)))


GIVE_NOTHING = "give_nothing"   # the giver's own answer that nothing moves: "chooses how much" includes none


def _reservoir(ctx: Any, holder: Any) -> None:
    """Transfer Cultivation Points either way between the bonded pair, as an Action.

    Two printed rules decide the shape: "The creature giving CP chooses how much to give, up to your Proficiency Bonus"
    (the GIVER is asked, every time and in both directions -- the caster when the caster gives, the bonded creature
    when it gives -- and it may choose none), and "Transferred CP cannot exceed the recipient's normal maximum CP" (each
    direction is capped by the room the RECIPIENT has left, so points are never drained and thrown away). "A creature
    can receive CP through your Shared Reservoir once per long rest" is counted on the creature that actually received
    them, so giving once does not stop a later receipt by the caster and receiving once does not stop a later gift to
    the bonded creature.  Which WAY the points move is the caster's, because the Action being spent is the caster's
    and the printed text offers the transfer jointly ("you and the bonded creature may transfer"); the amount, and the
    right to give nothing at all, belong to the creature giving them.
    """
    mine, theirs = _cp_pool(ctx.actor), _cp_pool(holder)
    if mine is None or theirs is None:
        ctx.rider("Neither of you has a Cultivation Points pool to draw on.")
        return
    pb = _pb(ctx)
    # (direction, recipient, recipient pool, room left, what the giver holds, giver pool, giver name)
    ways = {
        "to_them": (holder, theirs, _room(holder, theirs), int(ctx.actor.resources.get(mine, 0)), mine, ctx.actor),
        "to_me": (ctx.actor, mine, _room(ctx.actor, mine), int(holder.resources.get(theirs, 0)), theirs, holder),
    }
    spare = {name: min(pb, room, held) for name, (who, pool, room, held, giver_pool, giver) in ways.items()
             if room >= 1 and held >= 1 and not _uses(who, RECEIVED, ctx.actor.entity_id)}
    if not spare:
        ctx.rider("Neither of you can move Cultivation Points right now: one of you is at its maximum, the other holds none, "
                  "and a creature can receive Cultivation Points through your Shared Reservoir only once per long rest.")
        return
    labels = {"to_them": lambda n: f"You give {holder.display_name} up to {_cp_phrase(n, ways['to_them'][4])}",
              "to_me": lambda n: f"{holder.display_name} gives you up to {_cp_phrase(n, ways['to_me'][4])}"}
    labels = {name: words(spare[name]) for name, words in labels.items() if name in spare}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "reservoir", ctx.actor.entity_id, holder.entity_id), ctx.actor,
                 CHOICE + "reservoir", list(spare), labels=labels, minimum=1, maximum=1, target_id=holder.entity_id,
                 name="Shared Reservoir", preferred=[next(iter(spare))],
                 prompt=f"Shared Reservoir with {holder.display_name}: which way do the Cultivation Points move?") or [next(iter(spare))]
    recipient, recipient_pool, _room_left, held, giver_pool, giver = ways[picked[0]]
    # The printed giver owns the amount: "The creature giving CP chooses how much to give".
    amount = _amount(ctx, "reservoir_give" if picked[0] == "to_them" else "reservoir_take", giver, recipient,
                     {str(n): _cp_phrase(n, giver_pool) for n in range(1, spare[picked[0]] + 1)},
                     spare[picked[0]])
    if amount < 1:
        # The giver is the one who decides, and "how much" includes none: the Action is spent and nothing moves.
        note(ctx.engine, ctx.source, ctx.actor, f"Shared Reservoir: {giver.display_name} chooses to give no Cultivation "
             f"Points, so none move.", (recipient,))
        return
    ctx.engine._spend_resource(giver, giver_pool, amount, ctx.source)
    ctx.engine._gain_resource(recipient, recipient_pool, amount, ctx.source)
    _remember(recipient, RECEIVED, ctx.actor.entity_id)
    if recipient is ctx.actor:
        note(ctx.engine, ctx.source, ctx.actor, f"Shared Reservoir: {holder.display_name} gives you {amount} {_pool_word(giver_pool)}.",
             (holder,))
    else:
        note(ctx.engine, ctx.source, ctx.actor, f"Shared Reservoir: you give {amount} {_pool_word(giver_pool)} to {recipient.display_name}.",
             (recipient,))


def _amount(ctx: Any, tag: str, chooser: Any, recipient: Any, labels: dict[str, str], ceiling: int) -> int:
    """How many Cultivation Points to move, up to the printed ceiling ("The creature giving CP chooses how much to
    give, up to your Proficiency Bonus").

    The GIVER is asked every time -- including when only one point is on offer, which is still that creature's choice --
    and giving nothing is one of the answers, because "how much" plainly includes none.  ``chooser`` is the creature
    actually giving them, so a player-controlled bonded creature is asked on its own side -- including on an AI turn --
    and an AI giver answers itself.  Zero means the giver refused and no points move.
    """
    if ceiling < 1:
        return 0
    options = {str(n): labels[str(n)] for n in range(1, ceiling + 1)}
    options[GIVE_NOTHING] = "Give nothing: no Cultivation Points move"
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, tag, ctx.actor.entity_id, recipient.entity_id), chooser,
                 CHOICE + tag, list(options), labels=options, minimum=1, maximum=1, target_id=recipient.entity_id,
                 name="Shared Reservoir", preferred=[str(ceiling)],
                 prompt=f"Shared Reservoir: {chooser.display_name} chooses how many Cultivation Points to give "
                        f"{recipient.display_name}.") or [str(ceiling)]
    if not picked or picked[0] == GIVE_NOTHING or picked[0] not in options:
        return 0
    return max(1, min(ceiling, int(picked[0])))


_HANDLERS = {DRAW: _draw, FEED: _feed, THROTTLE: _throttle, READ: _read, LOCK: _lock, RESERVOIR: _reservoir}
