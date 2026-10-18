"""Shared rewrite registration/holder API for d20_rewrite_attacks, d20_rewrite_auspices, d20_rewrite_fate and d20_rewrite_rules.
The public saving_throw_context helper also supplies life_state's Soul-Lamp source and DC without an engine wrapper.

d20 rewrites: abilities whose printed text rerolls or replaces a d20 that was already rolled (automation lane H1, 2026-09-29).

The lock-round-2 hook ``d20_result(engine, roll, intent)`` (combat/roll_checkpoints.py) runs right after a deterministic d20 draw and
before the attack, save or check that rolled it reads the result; ONE plug-in may answer ``{source_id, operation: "reroll" | "replace",
natural_result}``. This module is that one owner. The abilities themselves are *rules* (combat/ext/d20_rewrite_rules.py and the
ability modules that register more): a rule says whose roll it may touch, when (a failed save, a hit against the holder, a natural 1),
what it costs, how often, and what it does to the die. This module does the rest for all of them: it finds the holders, works out
whether the roll failed, asks a player (Ask me) or lets the AI decide, pays, and answers the hook.

What a rule can know about the roll. The native engine supplies ``d20_context(roll)``: kind, DC/AC, actual target, ability/skill,
source and triggering action/actor. Native scopes also carry typed save outcomes and the caster. Unknown context stays unknown;
a "when you fail" rule does not fire when the caller cannot establish the DC. No engine methods are patched or wrapped here.

Timing and the die. A rewrite happens where the printed text puts it -- before the result is declared -- and the original die never
reaches the caller (``D20_REWRITTEN`` keeps both records). "Reroll" keeps the original mode and modifier (the hook's own operation);
a reroll with Advantage or Disadvantage, "use the higher/the lower", and "treat the roll as N" draw from the same deterministic stream
here (``roller.raw_d20``) and answer with a replacement. A save's optional signed ``save_bonus`` rechecks the effective total at
the unlocked roll checkpoint, before rewrite riders, save-result events and outcome consumers. This also works for legacy and
Concentration saves, without a late typed outcome override. ``costs_for`` optionally quotes state-qualified costs before consent.
The shared opposed_save_totals scope defers result-dependent riders until both final totals settle.
Rewrite-attached check bonuses use d20_bonus; rewrite-attached save bonuses use save_bonus exactly once.
Rewrite events stage numeric/forced outcomes immediately, but riders and result text
wait for d20_finalized after every additive provider. Pending finalizers are keyed
by roll_id so a nested roll cannot consume its parent's rider. Payment/on_use stay
at acceptance; finalization never repeats them. Opposed saves still await both totals.
Rules with op="bonus" run independently after the exclusive rewrite, through d20_bonus.
They recheck the effective roll, use the same eligibility/consent/payment/limit contract,
and yield accepted additive contributions without drawing or replacing a d20.
Each subsequent holder tests the total including earlier contributions; no global bonus limit is imposed.
They may compose with a reroll, but never reopen d20_result. Default rules remain rewrites.
Rule.outcome forces success or failure independently of totals; its default is inert.
Rule.before_outcome optionally hides the DC and outcome during consent while preserving the observed die and total.
Dream Ward uses this shared presentation contract; other rules retain their original transport.

Cost, limits, consent.
  * ``Rule.on_use(engine, holder, ctx)`` runs once after payment and limit spending in the shared resolver, before resistance.
    It is default-inert; usage rewards belong here, while result-dependent riders remain on ``after``/``after_resisted``.
  * A cost is a list of alternatives, each a list of (pool, amount): "cp" (the pool with most CP), "qi", "stamina", "resonance", "focus"
    (Martial Focus) or a named pool's slug ("rebirth_ember" -> resource:named.rebirth_ember; a Foundation's pool, "empty_bowl_mark" ->
    resource:foundation.empty_bowl_mark). A rule that spends the Reaction needs
    it (``typed_reactions._can_react``) and opens the reaction window like every other reaction.
  * "Once per round/turn" is a turn flag holding the round; "once per long rest or scene" is once per fight (there is no rest inside a
    fight; owner: once per scene = once per fight, once per week = once per day). Turn flags with ``_round_`` in the key survive the
    turn reset and are saved with the fight.
  * A player-controlled holder set to Ask me is asked (Use / Pass, the same question every Reaction asks: typed_reactions._consent);
    an AI holder, or a player on Auto, uses it when the rule says it is sensible (``ai`` on the rule; by default the roll must have
    failed the way the rule's trigger says, and a once-per-fight ability waits until the holder is hurt, the fight has gone on, or the failure costs it a condition).
  * Only one rule rewrites a roll (the hook's contract, and every printed text says a rerolled roll cannot be rerolled again). Independent
    additive save bonuses are consented and committed first, then compose with that rewrite. Rules are tried in (priority, holder, feature)
    order; a declined or unaffordable rule leaves the roll to the next.
Determinism: the die comes from the fight's own roller; every payment, window and note is a logged event.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal

from . import hook, note

BLOCK = "d20_rewrite"
RULES: dict[str, "Rule"] = {}
_PENDING = "_d20_pending"
_SAVE_EXTRA = "_d20_save_extra"
CHECKPOINT_LABELS = {  # the table's Ask me prompt says what happened (combat/tabletop_service.py _ASK_MOMENTS)
    "D20_REROLL_SAVE": "fails a saving throw (may reroll it)",
    "D20_REROLL_ATTACK": "is hit (may force the attacker to reroll)",
    "D20_REROLL_CHECK": "fails a check (may reroll it)",
    "D20_REROLL_ALLY": "an ally within reach has rolled (may let it reroll)",
    "D20_REWRITE_ROLL": "a creature within reach has rolled (may rewrite the d20)",
    "D20_ROLL_BONUS": "a creature has rolled (may add a bonus to the result)",
}


# ------------------------------------------------------------------------------------------------------------------- data
@dataclass
class Holder:
    """A creature that owns a rule: its compiled row (or the condition it bears), the feature that grants it."""
    actor: Any
    feature_id: str
    data: dict[str, Any]
    key: str  # what a limit is counted against (the row's feature id, or the condition instance)
    numbers: dict[str, int] = field(default_factory=dict)


@dataclass
class Rule:
    kind: str                                  # feature_blocks "kind" (or the id of a condition rule)
    name: str                                  # shown in the log
    rolls: tuple[str, ...] = ("save",)         # "save" | "attack" | "check"
    who: str = "self"                          # whose roll: self | ally | team | enemy | any
    range_ft: int | None = None                # for a roll that is not the holder's own
    see: bool = False                          # the holder must see the roller
    when: str = "failed"                       # failed | succeeded | hit | nat1 | any (hit: an attack roll that hits the holder)
    op: str = "reroll"                         # reroll | advantage | disadvantage | higher | lower | nat20 | nat1 | ten | choose | bonus
    abilities: tuple[str, ...] = ()            # saving throw abilities (three letters); empty: any
    costs: tuple[tuple[tuple[str, int], ...], ...] = ()   # alternatives; each a tuple of (pool, amount)
    costs_for: Callable[[Any, "Holder", "RollCtx"], tuple] | None = None  # pure optional state-qualified cost alternatives
    reaction: bool = False                     # spends the holder's Reaction
    limit: str | None = None                   # "round" | "turn" | "fight" | "target_fight" (once per fight for each creature helped)
    checkpoint: str = "D20_REROLL_SAVE"
    priority: int = 50
    feature: str | None = None                 # a mechanic that already has compiled rows of another block (its feature id); default: the d20_rewrite kind
    finder: Callable[[Any], Iterable[Holder]] | None = None   # default: the holder's compiled d20_rewrite rows of this kind (or of this feature)
    guard: Callable[[Any, Holder, "RollCtx"], bool] | None = None
    ai: Callable[[Any, Holder, "RollCtx"], bool] | None = None
    after: Callable[[Any, Holder, "RollCtx", Any], None] | None = None   # final additive RollRecord; opposed saves defer until final settlement
    bonus: Callable[[Any, Holder, "RollCtx"], int] | None = None         # signed modifier on the effective save, before observers
    drop_modifier: Callable[[Any, Holder, "RollCtx"], int] | None = None  # taken off the modifier for the new roll (a penalty/bonus that is gone)
    choose: Callable[[Any, Holder, "RollCtx"], int] | None = None         # the natural result to replace with (op "nat*" / "choose")
    say: Callable[[Any, Holder, "RollCtx", Any], str] | None = None        # the log line once done
    unwilling: str = ""                        # an enemy's roll: it makes a Charisma save first (the holder's Cultivation Save DC): "unchanged" (a
                                               # success leaves the roll alone) or "target_chooses" (a success lets the target pick between the two dice)
    after_resisted: Callable[[Any, Holder, "RollCtx"], None] | None = None   # the unwilling creature's save succeeded and the roll stands
    on_use: Callable[[Any, Holder, "RollCtx"], None] | None = None   # once after cost/limit commit, even if resisted or event hooks are nested
    note_only: bool = False                    # a rule kept for documentation: never fires
    replacement_options: tuple[int, ...] = ()  # manual owner's named replacement-die choices
    outcome: Literal["success", "failure"] | None = None  # explicit result, independent of numeric totals; None is inert
    before_outcome: bool = False  # consent sees the rolled die/total, but neither DC nor outcome
    additive_save_bonus: Callable[[Any, "Holder", "RollCtx"], int] | None = None  # composes with one actual die rewrite
    accept: Callable[[Any, Holder, "RollCtx"], bool] | None = None  # optional additional participant consent, before payment
    after_bonus: Callable[[Any, Holder, "RollCtx", Any, int], None] | None = None  # accepted additive contribution: original context, final roll, own signed bonus


def register(rule: Rule) -> Rule:
    RULES[rule.kind] = rule
    return rule


@dataclass
class RollCtx:
    """What is known about the d20 being rewritten."""
    engine: Any
    roll: Any
    kind: str
    roller: Any
    ability: str | None = None
    dc: int | None = None
    source_id: str | None = None
    target: Any = None            # attack: who is attacked (after any redirection)
    spec: dict[str, Any] | None = None
    ac: int | None = None
    resisted: bool = False                # the unwilling roller's Charisma save against the rule succeeded
    named: frozenset[str] = frozenset()   # a typed save: what a failure imposes ("frightened", "forced_movement", "damage:fire" ...)
    source_actor: Any = None              # a typed save: the creature whose ability forces it
    replacement: int | None = None
    source_name: str | None = None         # explicit label for a noncatalog save (e.g. Soul-Lamp Continuity)
    resolved_success: bool | None = None   # final opposed-save result, for deferred success-dependent riders

    @property
    def natural(self) -> int:
        return int(self.roll.natural_result or 0)

    @property
    def total(self) -> int:
        return int(self.roll.total)

    def succeeded(self) -> bool | None:
        """Effective outcome for eligibility, consent text and final riders.

        A settled result wins, then the shared typed save/check override staged
        by a rewrite. Explicit success/failure is independent of numeric totals;
        only unforced rolls compare their DC or use the native attack hit rules.
        None means the roll contract cannot establish an outcome.
        """
        if self.resolved_success is not None:
            return self.resolved_success
        if self.kind in ("save", "check"):
            outcome = (getattr(self.engine, "_typed_roll_outcome", None) or {}).get(self.roller.entity_id)
            if outcome in ("success", "failure"):
                return outcome == "success"
        if self.kind == "attack":
            if self.ac is None:
                return None
            from ..critical_attacks import hits
            return hits(self.natural, self.total, self.ac, (self.spec or {}).get('critical_threshold', 20))
        if self.dc is None:
            return None
        return self.total >= self.dc


# ---------------------------------------------------------------------------------------------------------- roll context
@contextmanager
def saving_throw_context(engine: Any, target: Any, ability: str, dc: int, source_id: str, *, source_name: str | None = None):
    """Native raw-save scope used by life_state's Soul-Lamp and rewrite display.

    Only the noncatalog display label is extension scratch; mechanical metadata
    belongs to the native scope. Both unwind on return, error and player pause.
    """
    label_key = "_d20_source_label"
    previous = engine.__dict__.get(label_key)
    engine.__dict__[label_key] = (target.entity_id, source_id, source_name)
    try:
        with engine.d20_scope({"kind": "save", "actor_id": target.entity_id,
                               "target_id": target.entity_id, "ability": str(ability).upper()[:3],
                               "dc": dc, "source_id": source_id}):
            yield
    finally:
        if previous is None:
            engine.__dict__.pop(label_key, None)
        else:
            engine.__dict__[label_key] = previous


@hook("roll_context_end")
def clear_save_scratch(engine: Any, context: dict[str, Any]) -> None:
    """Release this module's pre-save adjustments even on an escape or player pause."""
    if context["kind"] == "save":
        engine.__dict__.pop(_SAVE_EXTRA, None)


def save_extras(engine: Any) -> dict[str, Any]:
    """Scratch for the typed save about to be rolled (what a plug-in added to it before the roll, for a rule that undoes it afterwards);
    cleared when that save has been rolled."""
    return engine.__dict__.setdefault(_SAVE_EXTRA, {})






def context_of(engine: Any, roll: Any) -> RollCtx | None:
    """Read the native d20 context without recording wrappers or inferred DCs."""
    roller = engine.state.actors.get(roll.actor_id)
    context = engine.d20_context(roll)
    if roller is None or roll.natural_result is None or context is None:
        return None
    label = engine.__dict__.get("_d20_source_label")
    source_name = label[2] if label and label[:2] == (roller.entity_id, context["source_id"]) else None
    return RollCtx(engine, roll, context["kind"], roller, ability=context["ability"],
                   dc=context["dc"], source_id=context["source_id"],
                   target=engine.state.actors.get(context["target_id"]), spec=context["spec"], ac=context["ac"],
                   named=frozenset(context["named"]),
                   source_actor=engine.state.actors.get(context["source_actor_id"]), source_name=source_name)


# ---------------------------------------------------------------------------------------------------- pools and limits
def pool_id(actor: Any, name: str) -> str | None:
    """The resource id a cost names on this creature, or None when it has no such pool."""
    from ..typed_executor import CP_POOLS

    if name == "cp":
        pools = [pool for pool in CP_POOLS if actor.resource_maximums.get(pool, 0) > 0]
        return max(pools, key=lambda pool: actor.resources.get(pool, 0), default=None)
    core = {"qi": "resource:core.qi", "stamina": "resource:core.stamina", "resonance": "resource:core.resonance",
            "focus": "resource:core.martial_focus"}.get(name)
    # A Sphere or Path pool is resource:named.<slug>; a Foundation's pool (Empty Bowl Mark) is resource:foundation.<slug> (factory_compiler).
    for resource in ((core,) if core else (f"resource:named.{name}", f"resource:foundation.{name}")):
        if resource in actor.resources:
            return resource
    return None


def affordable(actor: Any, costs: tuple[tuple[tuple[str, int], ...], ...]) -> tuple[tuple[str, int], ...] | None:
    """The first alternative the creature can pay, () when the rule costs nothing, None when none can be paid."""
    if not costs:
        return ()
    for alternative in costs:
        if all((resource := pool_id(actor, pool)) is not None and actor.resources.get(resource, 0) >= amount for pool, amount in alternative):
            return alternative
    return None


def pay(engine: Any, actor: Any, alternative: tuple[tuple[str, int], ...], source: str) -> None:
    for pool, amount in alternative:
        engine._spend_resource(actor, pool_id(actor, pool), amount, source)


def _limit_key(rule: Rule, holder: Holder, roller: Any) -> str | None:
    if rule.limit == "target_fight":
        return f"_round_h1_fight:{holder.key}:{roller.entity_id}"
    if rule.limit in ("fight",):
        return f"_round_h1_fight:{holder.key}"
    if rule.limit in ("round", "turn"):
        return f"_round_h1_round:{holder.key}"
    return None


def limit_spent(engine: Any, rule: Rule, holder: Holder, roller: Any) -> bool:
    key = _limit_key(rule, holder, roller)
    if key is None:
        return False
    value = holder.actor.turn_flags.get(key)
    return bool(value) if rule.limit in ("fight", "target_fight") else value == engine.state.round_number


def spend_limit(engine: Any, rule: Rule, holder: Holder, roller: Any) -> None:
    key = _limit_key(rule, holder, roller)
    if key is not None:
        holder.actor.turn_flags[key] = True if rule.limit in ("fight", "target_fight") else engine.state.round_number


# ------------------------------------------------------------------------------------------------------------- finding
def row_holders(kind: str, feature: str | None = None) -> Callable[[Any], list[Holder]]:
    """Creatures with a compiled ``d20_rewrite`` row of this kind, or (``feature``) any compiled row of that mechanic, whatever its block."""
    def find(engine: Any) -> list[Holder]:
        found, seen = [], set()
        for store in ("typed_passive_rows", "typed_reaction_rows"):
            for actor_id, rows in sorted((getattr(engine, store, None) or {}).items()):
                actor = engine.state.actors.get(actor_id)
                if actor is None or not actor.active:
                    continue
                for row in rows:
                    if row.get("held_back") or not ((row.get("block") == BLOCK and row.get("kind") == kind)
                                                    or (feature is not None and row.get("feature_id") == feature)):
                        continue
                    if (actor_id, row.get("feature_id")) in seen:
                        continue
                    seen.add((actor_id, row.get("feature_id")))
                    found.append(Holder(actor, str(row.get("feature_id")), row, str(row.get("feature_id")),
                                        {"pb": int(row.get("pb") or actor.proficiency_bonus or 2), "key_mod": int(row.get("key_mod") or 0),
                                         "cl": int(row.get("cl") or 1)}))
        return found
    return find


def condition_holders(condition_id: str) -> Callable[[Any], list[Holder]]:
    """Creatures bearing a condition the rule reads (an Auspice): the bearer holds the rule, the condition is its data."""
    def find(engine: Any) -> list[Holder]:
        found = []
        for actor_id, actor in sorted(engine.state.actors.items()):
            if not actor.active:
                continue
            for iid, condition in sorted(actor.conditions.items()):
                if condition.condition_id == condition_id:
                    found.append(Holder(actor, str(condition.source_definition_id), dict(condition.data or {}), iid))
        return found
    return find


def _holders(engine: Any, *, bonuses: bool = False) -> list[tuple[Rule, Holder]]:
    pairs = []
    for rule in RULES.values():
        if rule.note_only or (rule.op == "bonus") != bonuses:
            continue
        for holder in (rule.finder or row_holders(rule.kind, rule.feature))(engine):
            pairs.append((rule, holder))
    return sorted(pairs, key=lambda pair: (pair[0].priority, pair[1].actor.entity_id, pair[1].feature_id, pair[1].key))


def _in_reach(engine: Any, rule: Rule, holder: Holder, roller: Any) -> bool:
    if rule.who == "self":
        return roller.entity_id == holder.actor.entity_id
    same_team = roller.team_id == holder.actor.team_id
    if roller.entity_id == holder.actor.entity_id:
        if rule.who not in ("team", "any"):
            return False
    elif rule.who == "ally" and not same_team or rule.who == "team" and not same_team or rule.who == "enemy" and same_team:
        return False
    if roller.entity_id != holder.actor.entity_id:
        if rule.range_ft is not None and engine._distance_actor_to_actor(holder.actor, roller) > rule.range_ft:
            return False
        if rule.see:
            from .. import stealth

            if not stealth.sees(engine, holder.actor, roller):
                return False
    return True


def _trigger_met(rule: Rule, holder: Holder, rc: RollCtx) -> bool:
    if rule.when == "any":
        return True
    if rule.when == "nat1":
        return rc.natural == 1
    if rule.when == "hit":  # an attack roll that hits the holder
        return rc.kind == "attack" and rc.target is not None and rc.target.entity_id == holder.actor.entity_id and rc.succeeded() is True
    outcome = rc.succeeded()
    if outcome is None:
        return False
    return outcome is (rule.when == "succeeded")


def eligible(engine: Any, rule: Rule, holder: Holder, rc: RollCtx) -> tuple[tuple[str, int], ...] | None:
    """The alternative the holder would pay when this rule may rewrite the roll now, else None. Pure: no consent, no payment."""
    from .. import typed_reactions

    actor = holder.actor
    if rc.kind not in rule.rolls or not actor.active or actor.life_state in ("DYING", "STABLE"):
        return None
    if rule.additive_save_bonus is not None and rc.kind != "save":
        return None
    if rule.abilities and rc.kind == "save" and rc.ability not in rule.abilities:
        return None
    if not _in_reach(engine, rule, holder, rc.roller) or not _trigger_met(rule, holder, rc):
        return None
    if rule.reaction and not typed_reactions._can_react(engine, actor):
        return None
    if limit_spent(engine, rule, holder, rc.roller) or (rule.guard is not None and not rule.guard(engine, holder, rc)):
        return None
    return affordable(actor, rule.costs_for(engine, holder, rc) if rule.costs_for else rule.costs)


def beneficiary(holder: Holder, rc: RollCtx) -> Any:
    """Whom the rule protects: the roller when it is on the holder's side, else the creature the roll is aimed at (or the holder)."""
    if rc.roller.team_id == holder.actor.team_id:
        return rc.roller
    return rc.target if rc.target is not None and rc.target.team_id == holder.actor.team_id else holder.actor


def worth_it(engine: Any, rule: Rule, holder: Holder, rc: RollCtx) -> bool:
    """The AI's judgement: a rule with its own ``ai`` decides; a once-per-fight ability waits until whom it protects is hurt (a tenth of
    its Hit Points gone), the second round has begun, the failure imposes a condition or forced movement, or the roll is a critical
    hit; anything else is used whenever its trigger is met."""
    if rule.ai is not None:
        return bool(rule.ai(engine, holder, rc))
    if rule.limit == "fight":
        actor = beneficiary(holder, rc)
        hurt = actor.current_hp * 10 <= actor.maximum_hp * 9
        return hurt or engine.state.round_number >= 2 or bool(rc.named) or (rc.kind == "attack" and rc.natural == 20)
    return True


def check_source_id(engine: Any, reason: str) -> str:
    """Resolve CHECK's action before skill/contest suffixes, preserving ID namespaces.

    Prefer the longest catalog ID (including variants). System/noncatalog checks
    strip only known check suffixes so a suffix-free namespaced ID stays intact.
    """
    source = reason.removeprefix("CHECK:")
    candidate = source
    while candidate:
        if candidate in engine.action_catalog:
            return candidate
        candidate = candidate.rpartition(":")[0]
    suffixes = {"actor", "defender", "acrobatics", "animal handling", "arcana", "athletics",
                "deception", "history", "insight", "intimidation", "investigation", "medicine",
                "nature", "perception", "performance", "persuasion", "religion", "sleight of hand",
                "stealth", "survival"}
    base, sep, suffix = source.rpartition(":")
    return base if sep and suffix.casefold() in suffixes else source


def roll_source_name(engine: Any, rc: RollCtx) -> str:
    """A catalog action name or readable noncatalog source, without roll suffixes."""
    if rc.source_name:
        return rc.source_name
    source_id = check_source_id(engine, "CHECK:" + str(rc.source_id or "")) if rc.kind == "check" else rc.source_id
    action = engine.action_catalog.get(source_id)
    if action is not None:
        return action.display_name
    source = str(source_id or "")
    if not source:
        return {"check": "Ability Check", "attack": "Attack", "save": "Saving Throw"}.get(rc.kind, "Roll")
    source = source.split("#", 1)[0].rsplit(":", 1)[-1].rsplit(".", 1)[-1]
    return source.removeprefix("TAL_").replace("_", " ").replace("-", " ").title() or "Roll"


def roll_scope(rc: RollCtx, rule: Rule) -> dict[str, Any]:
    """The active roll as the general trigger transport's extra details, for the text the player reads.

    A reroll prompt is asked from inside ``roller.d20``, before the engine records the roll, so the
    current roll is in no event yet and cannot be read back from the history. These keys carry it
    instead, which is what the presentation reads (decision_text.trigger_text). Every value is an
    integer, a string or null, so the request stays serialisable through a table commit and reload.

    ``roll_guarantee`` is what the printed rule itself promises, used only when the table cannot
    read the result: a rule that fires on a failed save or on a hit says so even without a recorded
    outcome, while a rule that fires on ``any`` roll (Invoke the Omen) promises nothing and must
    not be described as a failure. MMX71r review, owner 2026-10-02.
    """
    outcome = rc.succeeded()
    return {"roll_record_id": rc.roll.roll_id,
            "roll_roller_id": rc.roller.entity_id,
            "roll_ability": rc.ability,
            "roll_dc": None if rule.before_outcome else rc.dc,
            "roll_natural": rc.natural,
            "roll_total": rc.total,
            "roll_outcome": "unknown" if rule.before_outcome else {True: "success", False: "failure", None: "unknown"}[outcome],
            "roll_guarantee": "unknown" if rule.before_outcome else {"failed": "failure", "hit": "success"}.get(rule.when, "unknown"),
            "roll_victim_id": getattr(rc.target, "entity_id", None)}


def _consent(engine: Any, rule: Rule, holder: Holder, rc: RollCtx) -> bool:
    from .. import typed_reactions

    if holder.actor.entity_id not in (getattr(engine, "typed_ask_reactors", None) or ()):
        return worth_it(engine, rule, holder, rc)
    from ..reaction_trigger import trigger_scope

    # The retained end-turn intent carries answers, not the hazard's identity.
    source_actor = rc.source_actor if rc.kind == "save" else rc.roller if rc.kind == "attack" else None
    from ..decision_text import costs_text

    alternative = affordable(holder.actor, rule.costs_for(engine, holder, rc) if rule.costs_for else rule.costs) or ()
    resolved = [(pool_id(holder.actor, pool), amount) for pool, amount in alternative]
    display = {"d20_rewrite_name": rule.name,
               "cost": ("Reaction + " if rule.reaction else "") + (costs_text(resolved) or "no resource cost"),
               "paying_pool": next((resource for resource, _ in resolved if resource and resource != "resource:core.martial_focus"), "")}
    with trigger_scope(engine, rule.checkpoint,
                       actor_id=getattr(source_actor, "entity_id", None),
                       target_id=rc.roller.entity_id, source_id=rc.source_id, roll_kind=rc.kind,
                       action_name=roll_source_name(engine, rc),
                       **display, **roll_scope(rc, rule)):
        if rule.replacement_options:
            from . import needle

            preferred = str(rule.choose(engine, holder, rc)) if rule.choose else str(rule.replacement_options[0])
            source = roll_source_name(engine, rc)
            roll_name = {"attack": "attack roll", "save": "saving throw", "check": "ability check"}.get(rc.kind, rc.kind)
            if rc.kind == "save" and rc.ability:
                roll_name = f"{rc.ability} {roll_name}"
            prompt = (f"{rule.name}: {rc.roller.display_name} rolled a {roll_name} for {source} "
                      f"(observed d20: {rc.natural}); choose the replacement d20")
            intent = engine._active_intent
            picked = needle.ask(engine, intent, f"{rule.checkpoint}:{rc.roll.roll_id}", holder.actor,
                                f"choice:needle.{rule.kind}", [str(value) for value in rule.replacement_options],
                                labels={str(value): f"Natural {value}: replace the observed d20 with {value}" for value in rule.replacement_options},
                                prompt=prompt, preferred=[preferred],
                                allow_decline=True, target_id=rc.roller.entity_id,
                                feature_id=holder.feature_id, prompt_context=display)
            if not picked:
                return False
            rc.replacement = int(picked[0])
            return True
        return typed_reactions._consent(engine, {"feature_id": holder.feature_id, "ask": True}, holder.actor, rule.checkpoint)


# --------------------------------------------------------------------------------------------------------------- the hook
def draw(engine: Any, roll: Any, mode: str = "NORMAL") -> Any:
    """A fresh d20 for the same roll (same modifier and reason) from the fight's own stream; it does not open the hook again."""
    return engine.roller.raw_d20(modifier=roll.modifier, actor_id=roll.actor_id, reason=roll.reason, mode=mode)


_draw = draw


def save_dc(holder: Holder) -> int:
    """The holder's Cultivation Save DC (8 + Proficiency Bonus + key ability modifier) for a save its ability forces."""
    return 8 + int(holder.numbers.get("pb") or 2) + int(holder.numbers.get("key_mod") or 0)


def _answer(engine: Any, rule: Rule, holder: Holder, rc: RollCtx) -> tuple[dict[str, Any], str]:
    """The hook's answer for this rule and a description of how the new die came about."""
    roll = rc.roll
    if rule.op == "reroll":
        return {"source_id": holder.feature_id, "operation": "reroll"}, "rerolls"
    if rule.op == "normal":  # a reroll without the Advantage or Disadvantage the first roll had
        drawn = _draw(engine, roll, "NORMAL")
        return ({"source_id": holder.feature_id, "operation": "replace", "natural_result": int(drawn.natural_result)},
                f"rerolls without Advantage or Disadvantage ({drawn.natural_result})")
    if rule.op in ("advantage", "disadvantage"):
        drawn = _draw(engine, roll, rule.op.upper())
        return ({"source_id": holder.feature_id, "operation": "replace", "natural_result": int(drawn.natural_result)},
                f"rerolls with {rule.op.capitalize()} ({', '.join(str(d) for d in drawn.dice)})")
    if rule.op in ("higher", "lower"):
        drawn = _draw(engine, roll, "NORMAL")
        pick = max if rule.op == "higher" else min
        return ({"source_id": holder.feature_id, "operation": "replace", "natural_result": pick(int(drawn.natural_result), rc.natural)},
                f"rolls again ({drawn.natural_result}) and takes the {rule.op}")
    if rule.op == "ten":
        return {"source_id": holder.feature_id, "operation": "replace", "natural_result": 10}, "treats the roll as 10"
    if rule.op in ("nat20", "nat1"):
        value = 20 if rule.op == "nat20" else 1
        return {"source_id": holder.feature_id, "operation": "replace", "natural_result": value}, f"turns the d20 into a natural {value}"
    if rule.op == "choose" and rule.choose is not None:
        value = rc.replacement if rc.replacement is not None else int(rule.choose(engine, holder, rc))
        return {"source_id": holder.feature_id, "operation": "replace", "natural_result": value}, f"replaces the d20 with {value}"
    raise ValueError(f"unknown d20 rewrite op {rule.op}")


@hook("d20_result")
def rewrite(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    from .. import ext as _ext  # noqa: F401 -- package import order

    if roll.natural_result is None:
        return None
    try:
        pairs = _holders(engine)
        # Additive adjustments are independent of the single die-rewrite slot.
        # Resolve those first so holder/registration order cannot hide a legal
        # bonus behind a reroll or replacement.
        pairs = sorted(pairs, key=lambda pair: (pair[0].additive_save_bonus is None,
                                                pair[0].priority, pair[1].actor.entity_id,
                                                pair[1].feature_id, pair[1].key))
        rc = context_of(engine, roll) if pairs else None
    except Exception as exc:  # noqa: BLE001 -- a bad rule never ends a fight
        from . import _log
        _log("d20_result", rewrite, exc, (engine,))
        return None
    if rc is None:
        return None
    additives: list[tuple[Rule, Holder, tuple[tuple[str, int], ...], int]] = []
    additive_total = 0
    for rule, holder in pairs:
        try:
            alternative = eligible(engine, rule, holder, rc)
        except Exception as exc:  # noqa: BLE001
            from . import _log
            _log("d20_result", rewrite, exc, (engine,))
            continue
        if alternative is None:
            continue
        if not _consent(engine, rule, holder, rc):   # may pause the fight for a player: never inside the try
            continue
        if rule.accept is not None and not rule.accept(engine, holder, rc):
            continue
        from .. import typed_reactions

        if rule.additive_save_bonus is not None:
            # A numeric save benefit does not consume the roll's one rewrite slot.
            # Commit it now, then keep looking for a genuine reroll/replacement.
            with activation(engine, holder.actor, holder.feature_id):
                if rule.reaction:
                    typed_reactions._open(engine, {"feature_id": holder.feature_id}, holder.actor, (rc.roller.entity_id,), rule.checkpoint,
                                          {"roll_id": roll.roll_id})
                pay(engine, holder.actor, alternative, holder.feature_id)
                spend_limit(engine, rule, holder, rc.roller)
                if rule.on_use is not None:
                    rule.on_use(engine, holder, rc)
            amount = int(rule.additive_save_bonus(engine, holder, rc))
            if amount:
                additives.append((rule, holder, alternative, amount))
                additive_total += amount
                # Later rules must see the save that the committed bonus will
                # produce. Keep the original die but carry the effective total.
                effective_roll = rc.roll.model_copy(update={
                    "modifier": rc.roll.modifier + amount,
                    "total": rc.roll.total + amount,
                })
                rc = replace(rc, roll=effective_roll)
            continue

        with activation(engine, holder.actor, holder.feature_id):
            if rule.reaction:
                typed_reactions._open(engine, {"feature_id": holder.feature_id}, holder.actor, (rc.roller.entity_id,), rule.checkpoint,
                                      {"roll_id": roll.roll_id})
            pay(engine, holder.actor, alternative, holder.feature_id)
            spend_limit(engine, rule, holder, rc.roller)
            # Usage riders do not depend on D20_REWRITTEN event-hook delivery (turn hooks may suppress it).
            if rule.on_use is not None:
                rule.on_use(engine, holder, rc)
            rc.resisted = False
            if rule.unwilling and rc.roller.team_id != holder.actor.team_id:
                saved = engine._roll_save(rc.roller, "CHA", save_dc(holder), holder.feature_id)
                rc.resisted = saved is not None and saved.total >= save_dc(holder)
                if rc.resisted:
                    note(engine, holder.feature_id, holder.actor, f"{rc.roller.display_name} resists {rule.name} (Charisma save {saved.total} against DC "
                         f"{save_dc(holder)}).", (rc.roller,))
                    if rule.unwilling == "unchanged":
                        if rule.after_resisted is not None:
                            rule.after_resisted(engine, holder, rc)
                        if additives:
                            # Resistance leaves this rewrite untouched, but it
                            # cannot undo independent bonuses already paid for.
                            first_rule, first_holder, _cost, _amount = additives[0]
                            preserve_pending(engine, _PENDING)
                            engine.__dict__[_PENDING] = {
                                "rule": first_rule, "holder": first_holder, "ctx": rc,
                                "how": "keeps the original d20", "additives": additives,
                            }
                            retain(engine, _PENDING, capture(engine))
                            return {"source_id": first_holder.feature_id, "operation": "replace",
                                    "natural_result": rc.natural, "save_bonus": additive_total,
                                    "user_id": first_holder.actor.entity_id}
                        return None
            answer, how = _answer(engine, rule, holder, rc)
            # Who used the ability. The roll being rewritten often belongs to a different
            # creature (an ally rerolls another's save), and the fight log reads this as
            # "the user rerolled the roller", so the owner travels with the answer.
            answer["user_id"] = holder.actor.entity_id
            if rc.kind == "save":
                delta = (int(rule.bonus(engine, holder, rc)) if rule.bonus else 0) - (int(rule.drop_modifier(engine, holder, rc)) if rule.drop_modifier else 0)
                if additive_total + delta:
                    answer["save_bonus"] = additive_total + delta
            preserve_pending(engine, _PENDING)
            engine.__dict__[_PENDING] = {"rule": rule, "holder": holder, "ctx": rc, "how": how, "additives": additives}
            retain(engine, _PENDING, capture(engine))
            return answer
    if additives:
        # An additive rule may stand alone; keep the die and route its bonus
        # through the same native save checkpoint as a composed rewrite.
        rule, holder, _cost, _amount = additives[0]
        preserve_pending(engine, _PENDING)
        engine.__dict__[_PENDING] = {"rule": rule, "holder": holder, "ctx": rc, "how": "keeps the original d20", "additives": additives}
        retain(engine, _PENDING, capture(engine))
        return {"source_id": holder.feature_id, "operation": "replace", "natural_result": rc.natural,
                "save_bonus": additive_total, "user_id": holder.actor.entity_id}
    return None


@hook("d20_bonus", priority=100)
def optional_roll_bonus(engine: Any, roll: Any, intent: Any) -> Iterable[dict[str, Any]]:
    """Consented additive rules on the effective roll, after ordinary bonuses.

    Reuse rewrite eligibility and costs but never enter its exclusive selection
    or pending-rider state. Both participants consent before payment; a pause or
    error propagates to the caller's transaction. Rules own their on_use spending
    and return a signed bonus, while the checkpoint owns the final event/record.
    Only op="bonus" rules enter this path; existing rules remain unchanged.
    """
    pairs = _holders(engine, bonuses=True)
    rc = context_of(engine, roll) if pairs else None
    if rc is None:
        return None
    for rule, holder in pairs:
        rc = context_of(engine, roll)
        if rc is None:
            return
        alternative = eligible(engine, rule, holder, rc)
        if alternative is None or not _consent(engine, rule, holder, rc):
            continue
        if rule.accept is not None and not rule.accept(engine, holder, rc):
            continue
        if rule.bonus is None or rule.unwilling or rule.outcome is not None or rule.after is not None:
            raise ValueError("additive rules require bonus and cannot rewrite outcomes or attach rewrite riders")
        from .. import typed_reactions

        with activation(engine, holder.actor, holder.feature_id):
            if rule.reaction:
                typed_reactions._open(engine, {"feature_id": holder.feature_id}, holder.actor,
                                      (rc.roller.entity_id,), rule.checkpoint, {"roll_id": roll.roll_id})
            pay(engine, holder.actor, alternative, holder.feature_id)
            spend_limit(engine, rule, holder, rc.roller)
            if rule.on_use is not None:
                rule.on_use(engine, holder, rc)
            bonus = rule.bonus(engine, holder, rc)
            if type(bonus) is not int:
                raise ValueError("additive rule bonus must be an integer")
            roll_name = {"attack": "attack roll", "save": "saving throw", "check": "ability check"}[rc.kind]
            note(engine, holder.feature_id, holder.actor,
                 f"{holder.actor.display_name} uses {rule.name}: adds {bonus} to {rc.roller.display_name}'s "
                 f"{roll_name} "
                 f"(total {rc.total} becomes {rc.total + bonus}).", (rc.roller,))
            if rule.after_bonus is not None:
                preserve_pending(engine, "_d20_bonus_finalizers")
                entries = engine.__dict__.setdefault("_d20_bonus_finalizers", {}).setdefault(roll.roll_id, [])
                key = ("_d20_bonus_finalizers", roll.roll_id, len(entries))
                entries.append((rule, holder, rc, bonus, key))
                retain(engine, key, capture(engine))
            yield {"source_id": holder.feature_id, "user_id": holder.actor.entity_id, "bonus": bonus}
            # Resume only after the checkpoint records this contribution. Later
            # holders see its numeric result and persisted spending/limits.
            roll = roll.model_copy(update={"modifier": roll.modifier + bonus, "total": roll.total + bonus})


@hook("d20_finalized")
def finalize_additive_bonuses(engine: Any, result: Any, intent: Any) -> None:
    """Settle accepted additive riders on this exact roll, after all bonuses.

    Keep the pre-contribution context and own amount so providers can distinguish
    their rescue from another provider's. Strict checkpoint transaction rollback
    handles a pause/error; nested rolls cannot consume another roll's callbacks.
    No callback means no pending state or event changes for existing rules.
    """
    if "_d20_bonus_finalizers" not in engine.__dict__:
        return
    preserve_pending(engine, "_d20_bonus_finalizers")
    finalizers = engine.__dict__["_d20_bonus_finalizers"]
    entries = finalizers.pop(result.roll_id, [])
    if not finalizers:
        engine.__dict__.pop("_d20_bonus_finalizers", None)
    for rule, holder, rc, amount, key in entries:
        with causal_scope(engine, take(engine, key)):
            rule.after_bonus(engine, holder, rc, result, amount)


@hook("event", nested=True)
def after_rewrite(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Stage rewrite bonuses/forced outcomes before additive eligibility checks."""
    if event_type != "D20_REWRITTEN":
        return
    preserve_pending(engine, _PENDING)
    pending = engine.__dict__.pop(_PENDING, None)
    if pending is None:
        return
    with causal_scope(engine, take(engine, _PENDING)):
        from ..gate2_runtime_models import RollRecord

        rule, holder, rc = pending["rule"], pending["holder"], pending["ctx"]
        result = RollRecord.model_validate((kwargs.get("payload") or {})["result"])
        _align_outcome(engine, rule, holder, rc, result)
        if rc.kind in ("check", "attack"):
            delta = (engine.__dict__.get("_d20_rewrite_check_bonuses", {}).get(result.roll_id) or {}).get("bonus", 0)
            result = result.model_copy(update={"modifier": result.modifier + delta, "total": result.total + delta})
        pending["rewritten"] = result
        preserve_pending(engine, "_d20_rewrite_finalizers")
        engine.__dict__.setdefault("_d20_rewrite_finalizers", {})[result.roll_id] = pending
        retain(engine, ("_d20_rewrite_finalizers", result.roll_id), capture(engine))


@hook("d20_finalized")
def finalize_rewrite(engine: Any, result: Any, intent: Any) -> None:
    """Settle one rewrite's text/rider after all numeric additions, exactly once.

    The strict checkpoint keeps choice pauses transactional. Unconditional riders
    still run once, while fixed-DC success riders read the final effective total.
    Opposed riders retain their later after_save_resolved outcome contract.
    """
    preserve_pending(engine, "_d20_rewrite_finalizers")
    finalizers = engine.__dict__.get("_d20_rewrite_finalizers", {})
    pending = finalizers.pop(result.roll_id, None)
    if not finalizers:
        engine.__dict__.pop("_d20_rewrite_finalizers", None)
    if pending is None:
        return
    with causal_scope(engine, take(engine, ("_d20_rewrite_finalizers", result.roll_id))):
        rule, holder, rc = pending["rule"], pending["holder"], pending["ctx"]
        rc_after = replace(rc, roll=result)
        outcome = rule.outcome == "success" if rule.outcome is not None else rc_after.succeeded()
        opposed_save = rc.kind == "save" and engine.__dict__.get("_d20_rewrite_opposed_save") == (rc.roller.entity_id, rc.source_id)
        # Describe this rewrite's own adjustment, while reporting the final
        # total: another holder's donation must not be credited to this ability.
        adjustment = int(pending["rewritten"].modifier) - int(rc.roll.modifier)
        detail = (f" ({rc.natural} -> {result.natural_result})" if result.natural_result != rc.natural or not adjustment else "")
        if rc.kind == "save" and adjustment:
            total_label = "final save total" if result.modifier != pending["rewritten"].modifier else "save total"
            detail += (f"; {'adds' if adjustment > 0 else 'subtracts'} {abs(adjustment)} "
                       f"({total_label} {result.total} against DC {rc.dc})")
        how = "rechecks" if rule.op == "choose" and adjustment else pending["how"]
        roll_name = {"save": "saving throw", "attack": "attack roll", "check": "ability check"}.get(rc.kind, rc.kind)
        line = rule.say(engine, holder, rc, result) if rule.say else (
            f"{holder.actor.display_name} uses {rule.name}: {rc.roller.display_name} {how} the {roll_name}"
            + detail + (". The contest resolves after both creatures' roll adjustments." if opposed_save else f" and {'succeeds' if outcome else 'fails'}." if outcome is not None else "."))
        note(engine, holder.feature_id, holder.actor, line, (rc.roller,))
        for additive_rule, additive_holder, _cost, amount in pending.get("additives", ()):
            note(engine, additive_holder.feature_id, additive_holder.actor,
                 f"{additive_holder.actor.display_name} uses {additive_rule.name}: adds {amount} to {rc.roller.display_name}'s saving throw.", (rc.roller,))
        if rule.after is not None:
            if opposed_save:
                # A success-dependent rider must await the final opposing total too.
                preserve_pending(engine, "_d20_rewrite_save_riders")
                engine.__dict__.setdefault("_d20_rewrite_save_riders", {})[(rc.roller.entity_id, rc.source_id)] = (rule, holder, rc_after, result)
                retain(engine, ("_d20_rewrite_save_riders", rc.roller.entity_id, rc.source_id), capture(engine))
            else:
                rule.after(engine, holder, rc_after, result)


@hook("after_save_resolved")
def opposed_save_rider(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    """Resolve an owned rewrite rider using the final save outcome, including forced outcomes."""
    preserve_pending(ctx.engine, "_d20_rewrite_save_riders")
    pending = ctx.engine.__dict__.get("_d20_rewrite_save_riders", {})
    answer = pending.pop((subject.entity_id, ctx.source), None)
    if not pending:
        preserve_pending(ctx.engine, "_d20_rewrite_save_riders")
        ctx.engine.__dict__.pop("_d20_rewrite_save_riders", None)
    if answer is not None:
        rule, holder, rc, result = answer
        with causal_scope(ctx.engine, take(ctx.engine, ("_d20_rewrite_save_riders", subject.entity_id, ctx.source))):
            rule.after(ctx.engine, holder, replace(rc, resolved_success=not failed), result)


@contextmanager
def opposed_save_totals(engine: Any, subject: Any, source_id: str):
    """Typed opposed resolver requests numeric rewrites for this exact save.

    Fixed-DC saves retain their existing outcome contract. Nested saves and
    preview exceptions restore the prior scope; nothing enters saved state.
    """
    key = "_d20_rewrite_opposed_save"
    previous = engine.__dict__.get(key)
    engine.__dict__[key] = (subject.entity_id, source_id)
    try:
        yield
    except BaseException:
        preserve_pending(engine, "_d20_rewrite_save_riders")
        pending = engine.__dict__.get("_d20_rewrite_save_riders", {})
        pending.pop((subject.entity_id, source_id), None)
        take(engine, ("_d20_rewrite_save_riders", subject.entity_id, source_id))
        if not pending:
            preserve_pending(engine, "_d20_rewrite_save_riders")
            engine.__dict__.pop("_d20_rewrite_save_riders", None)
        raise
    finally:
        if previous is None:
            engine.__dict__.pop(key, None)
        else:
            engine.__dict__[key] = previous


def _align_outcome(engine: Any, rule: Rule, holder: Holder, rc: RollCtx, result: Any) -> None:
    """Keep explicit outcomes separate from numeric bonuses on rewritten saves/checks.

    Forced save/check outcomes use the typed override regardless of totals.
    Numeric attack/check changes use d20_bonus; all saves already include their native save_bonus.
    """
    if rc.kind not in ("save", "check", "attack"):
        return
    if rule.outcome is not None:
        if rc.kind == "save":
            preserve_pending(engine, "_d20_forced_native_saves")
            engine.__dict__.setdefault("_d20_forced_native_saves", {})[rc.roll.roll_id] = {
                "target_id": rc.roller.entity_id, "outcome": rule.outcome, "source_id": holder.feature_id}
    if rule.outcome is not None and rc.kind in ("save", "check"):
        engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), rc.roller.entity_id: rule.outcome}
        note(engine, holder.feature_id, holder.actor,
             f"{rule.name}: {rc.roller.display_name}'s {rc.kind} {'succeeds' if rule.outcome == 'success' else 'fails'} regardless of the final totals.", (rc.roller,))
    if rc.kind == "save":
        return  # native save_bonus already changed this record's effective total
    delta = (int(rule.bonus(engine, holder, rc)) if rule.bonus else 0) - (int(rule.drop_modifier(engine, holder, rc)) if rule.drop_modifier else 0)
    if delta:
        engine.__dict__.setdefault("_d20_rewrite_check_bonuses", {})[result.roll_id] = {
            "source_id": holder.feature_id, "bonus": delta}



@hook("d20_bonus")
def rewritten_check_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Consume a rewrite's printed attack/check bonus via the existing bonus seam."""
    pending = engine.__dict__.get("_d20_rewrite_check_bonuses", {})
    answer = pending.pop(roll.roll_id, None)
    if not pending:
        engine.__dict__.pop("_d20_rewrite_check_bonuses", None)
    return answer


# ---------------------------------------------------------------------------------------------------------------- compile
@hook("decision_text")
def decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, str] | None:
    """Describe the registered printed option for an owned d20 rewrite.

    Option names come from the existing rule registration, never an ability-id
    switch in the presentation core. This read-only hook is inert for other rows.
    """
    import re
    from ..decision_text import plain

    feature = str(context.get("reaction_source_id") or "").removeprefix("reaction:typed.")
    reactor = context.get("reactor_id")
    checkpoint = str(context.get("checkpoint") or "").removeprefix("TYPED:").split("@")[0]
    if context.get("extension_choice"):
        return None
    # The source feature may own several abilities (e.g. Ancestral Memory).
    # Name the exact registered optional rewrite without a second subscriber.
    name = (context.get("choice_trigger") or {}).get("d20_rewrite_name")
    metadata = {"name": name} if name else {}
    rows = [row for store in ("typed_passive_rows", "typed_reaction_rows")
            for row in (getattr(engine, store, None) or {}).get(reactor, [])]
    for row in rows:
        if row.get("feature_id") != feature or row.get("held_back"):
            continue
        rule = (RULES.get(row.get("kind")) if row.get("block") == BLOCK else
                next((rule for rule in RULES.values() if rule.feature == feature and rule.checkpoint == checkpoint), None))
        if rule is None or rule.checkpoint != checkpoint:
            continue
        option = re.search(r"\(([^)]+)\)$", rule.name) if rule else None
        if not option:
            continue
        label = option[1]
        printed = plain(printed_rules.get(feature, ""))
        selected = next((line.removeprefix("- ") for line in printed.splitlines()
                         if line.removeprefix("- ").startswith(label + ":")), "")
        if selected:
            return {**metadata, "summary": selected,
                    "table_note": f"Use runs {label}. This prompt does not choose the other printed options."}
    return metadata or None


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Feature block ``d20_rewrite``: {"kind": <rule kind>} or {"kinds": [...]} for a feature that is several rules; each row carries the
    owner's numbers."""
    if block != BLOCK:
        return None
    kinds = list(spec.get("kinds") or [spec.get("kind")])
    return [{**row, "block": BLOCK, "kind": kind, "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             "cl": int(numbers.get("cl") or 1), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})} for kind in kinds]


@hook("save_result_outcome")
def native_forced_save(engine, target, ability, dc, roll, source, intent):
    """Consume only the exact d20's forced outcome after native save modifiers."""
    pending = engine.__dict__.get("_d20_forced_native_saves") or {}
    reply = pending.get(roll.roll_id)
    if reply is None or reply["target_id"] != target.entity_id:
        return None
    preserve_pending(engine, "_d20_forced_native_saves")
    pending.pop(roll.roll_id)
    if getattr(engine, "_d20_rewrite_opposed_save", None) == (target.entity_id, source):
        # The opposing total may still change. Keep the actual draw/modifier
        # and let the opposed resolver consume the staged explicit outcome.
        return None
    return {"source_id": reply["source_id"], "outcome": reply["outcome"]}
