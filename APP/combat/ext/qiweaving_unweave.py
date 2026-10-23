"""Rapid Unweave and the wide unweaves: Qiweaving's Unweave Pattern in a fight
(rider lane C11, 2026-09-30; auto lanes AUTO12 2026-10-04, AUTO12f1 2026-10-05).

Source (owner text, authority/typed_mechanics/rules_text.json TAL_QIWEAVING_UNWEAVE_PATTERN and the Qiweaving talents, and the
Qiweaving chapter's core rules):
  Unweave Pattern: "Ritual Procedure ... Range: 30 feet. Target: One creature, object, location, or Active Qi Pattern. Attempt to end one
    Active Qi Pattern on the target. If the pattern's Pattern Rank is equal to or lower than half your Proficiency Bonus, rounded down,
    it ends automatically. Otherwise, make a Qiweaving Check against the pattern. Successful Check: The pattern ends. Failed Check: The
    pattern remains."  Augments: "Rapid Unweave - 1 CP: Reduce the Action Type to Action." "Broad Unweave - 1 CP: Attempt to unweave a
    number of additional Active Qi Patterns on the same target equal to half your Proficiency Bonus, rounded down." "Certain Unweave -
    1 CP: The automatic-ending threshold becomes your Proficiency Bonus instead of half your Proficiency Bonus."
  Vicious Unweave - Unweaving (+1 CP): "When you successfully end or counter an Active Qi Pattern with Unweave Pattern, choose one
    creature bearing, maintaining, or creating that pattern. That creature takes Force damage. ... 1d10 / 2d10 / 3d10 / 4d10 by
    Cultivation Level. A creature can take this damage from you only once per turn."
  Dazing Unweave - Unweaving (+1 CP): "When you successfully counter a technique with Unweave Pattern, the creature whose technique
    you countered makes an Intelligence saving throw. Failed Save: Until the end of its next turn, the creature has Disadvantage on
    attack rolls made as part of magical or cultivation techniques, and creatures have Advantage on saving throws against its
    magical or cultivation techniques."   NOT AUTOMATED (AUTO12f1): its trigger is *countering a technique*, and only a
    Reaction-economy counter can do that here (see "Not automated" below).
  False Completion - Unweaving (+1 CP): "When you successfully counter a technique with Unweave Pattern, the creature whose technique
    you countered makes an Intelligence saving throw. Failed Save: The creature believes the technique had its intended outward
    effect until the end of its next turn or until obvious evidence proves otherwise."   NOT AUTOMATED, as Dazing Unweave is.
  Grand Unweaving (CL 10+, Action, 20-foot-radius sphere, 3 CP): "Choose any number of Active Qi Patterns inside the area that you can
    perceive. Make one Qiweaving Check and compare the result to each chosen pattern's DC separately. Success Against a Pattern: That
    pattern ends. Failure Against a Pattern: That pattern remains."
  World-Circuit Severance (CL 15+, Action, 120 feet, 5 CP, once per long rest): "Choose up to a number of Active Qi Patterns you can
    perceive within range equal to your Proficiency Bonus. Make one Qiweaving Check with Advantage. Compare the result to each chosen
    pattern's DC. Success Against a Pattern: The pattern ends. Failure Against a Pattern: The pattern is suppressed until the start of
    your next turn instead."
  Core rules: an Active Qi Pattern is "an ongoing magical, spiritual, or cultivation effect" (a sphere mark, a maintained aura, a
    Concentration technique ...). "Pattern Rank: ... Sphere or cultivation effect with CP cost: CP spent to activate or maintain it,
    minimum 1. Mortal or basic talent with no CP cost: 1. Foundation Realm talent with no CP cost: 3. Core Formation Realm talent: 5.
    Nascent Soul Realm talent: 7." "Qiweaving Check: d20 + your Key Ability modifier + your Proficiency Bonus. The DC is usually 10 +
    the target effect's Pattern Rank."

How it runs. Every Qiweaver (the base ability) gets "Unweave Pattern (Rapid Unweave)" -- an Action, 1 CP, 30 feet -- aimed at a foe, and
an "(ally or self)" twin. It is offered only against a creature that bears an Active Qi Pattern: a condition, a mark or a modifier that a
typed technique put on it (bookkeeping records excepted). The user picks the pattern (and, with Broad Unweave, the extra ones); the
augments are asked as the Action resolves ("Certain Unweave" and "Broad Unweave", 1 CP each, paid then; the AI pays for Certain only
when it turns a check into an automatic ending). Pattern Rank: the CP its technique cost, else 1 / 3 / 5 / 7 by the Realm of its
talent's printed CL prerequisite (none / CL 5+ / 11+ / 17+). A rank at or below the threshold ends at once; otherwise the Qiweaving
Check against 10 + the rank. Removal is end_effect's public exact-instance removal (logged, replays).
  * Vicious Unweave is the one Unweaving augment that rides an *ending* pattern, which is the printed half of its trigger ("end or
    counter"): the Qiweaver chooses which of the creatures bearing, maintaining or creating the pattern takes its Realm-scaled Force
    damage, at most one creature per turn (an engine-named once-per-turn clock, so a later turn's Unweave reaches the same creature
    again). The choice is asked, because the printed word is "choose".
  * Grand Unweaving sweeps every perceived Active Qi Pattern on every creature inside its 20-foot sphere, allies and self included,
    with ONE Qiweaving Check compared against each chosen pattern's own DC -- a rank-7 pattern needs 17 where a rank-1 one needs 11,
    so the same roll can end one and leave the other.
  * World-Circuit Severance takes up to Proficiency Bonus perceived patterns within 120 feet with one check at Advantage; a failure
    suppresses the pattern until the START of your next turn (end_effect's public suppress with boundary "start", the same one its
    siblings use), and its use limit is once per long rest (once per fight -- there is no rest inside one). Severance's target domain
    is ANY_CREATURE, the printed target being a pattern.
  "you can perceive" is target_knowledge.located, the engine's own current-perception read (sight or a pinpointing sense), so a Hidden
  or Invisible creature that nothing locates is out of reach of both wide unweaves and their candidates.
Not automated:
  * Dazing Unweave and False Completion.  Both trigger on "when you successfully counter a *technique* with Unweave Pattern".
    At this table a counter is a Reaction-economy row: typed_reactions.on_technique_start offers the reactor's reaction
    candidates, and only the typed ``counter_technique`` effect (typed_executor.block_counter_technique, typed_executor.py:3475)
    sets the flag that stops the pending technique. Unweave Pattern is an Action, so it is never offered inside another creature's
    declaration window, and nothing observable says a counter succeeded: typed_executor.py:4008-4009 reads and clears
    ``engine._typed_countered`` without recording *who* countered or *with what*.  Running them off an ending pattern instead
    (what AUTO12 did) applied them to the wrong trigger, so they are left as printed table decisions here and their "+1 CP" variants
    are not compiled: the sheet lists both talents and why.  The seam they need is recorded in the lane report, not faked here.
  * the 10-minute ritual itself (outside fights); Domains and other areas (they are not on a creature); objects and locations as the
    target; Seize Pattern (it rewrites a technique's targets, which needs a target-rewrite seam this engine has no general form of);
    "the GM chooses which Bond talents make sense for a non-creature pattern" (Open Circuit).
Default-inert: only fighters who own Unweave Pattern get the actions, and the Vicious Unweave variant only when they own it.

Public API, shared with other Qiweaving plug-ins.
  pattern_rank(engine, item) -> int   the Active Qi Pattern's printed Pattern Rank (its technique's Cultivation Point cost,
                                       else 1 / 3 / 5 / 7 by the Realm its talent's printed CL prerequisite names).
  patterns(engine, holder) -> [(kind, key, item)]   every Active Qi Pattern on one creature, as the conditions and modifiers a
                                       typed technique left there.  Shared with combat/ext/qiweaving_bond.py, which reads
                                       them for Read Current's printed facts, so a Bond talent reports the same patterns an
                                       Unweave would reach.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, note
from . import source_eligibility
from .qiweaving_common import bond_reach, rules_text

BASE = "TAL_QIWEAVING_UNWEAVE_PATTERN"
RANGE_FT = 30
VICIOUS = "TAL_QIWEAVING_VICIOUS_UNWEAVE"
DAZING = "TAL_QIWEAVING_DAZING_UNWEAVE"
FALSE = "TAL_QIWEAVING_FALSE_COMPLETION"
GRAND = "TAL_QIWEAVING_GRAND_UNWEAVING"
SEVERANCE = "TAL_QIWEAVING_WORLD_CIRCUIT_SEVERANCE"
SEVERANCE_RANGE_FT = 120
# The "+1 CP" Unweaving choices that ride an ended pattern: the name the table sees, and the printed line it runs.
UNWEAVING = ((VICIOUS, "Vicious Unweave"),)
UNWEAVING_RIDERS = {rider: name for rider, name in UNWEAVING}
# The printed Unweaving augments that trigger only on *countering a technique*, which this table has no way to do
# (see the module docstring). They are deliberately not compiled, so no fighter is charged 1 CP for a line the engine
# cannot run; combat/rules/feature_status.d/zz_qiweaving_auto12.json says so on the sheet.
NEEDS_A_COUNTER = (DAZING, FALSE)
SEVERED = "_round_qiweaving_world_circuit"   # a turn flag kept across turns (the "_round_" keys survive turn resets)
# "A creature can take this damage from you only once per turn."  The once_per_turn: namespace is swept from every
# creature at the start of each turn (combat/turn_uses.py), so the clock is a turn and not the rest of the fight.
# A list of creature ids, so one Unweave Pattern cannot hit the same creature twice and another can hit a different one.
DAZED = "once_per_turn:qiweaving_vicious_unweave"
# Records that are not an effect on the creature: held Concentration, suppression, menu and setting picks, Hide, the Dying rules, the
# Warleader's Standard ("not magical, not a Formation"), and this plug-in's own Qiweaving markers (a Qiweaver does not unweave its own
# bookkeeping).
_BOOKKEEPING = ("concentration_held", "suppressed.", "menu", "setting", "hidden", "life_unconscious", "soul_lingering", "deathless_recovery",
                "warleader_standard", "qiweaving_", "suppression", "instant")
# The protected-power reader is shared (AUTO118r1f1): combat/ext/source_eligibility.py owns the owner's
# categories and the fail-closed rule, and combat/ext/end_effect.py asks the same question for Internal
# Hammer's "does not suppress Domains, Secret Inheritances, permanent transformations, artifacts". These two
# names stay as the spellings this module and its tests already use.
_PROTECTED = source_eligibility.PROTECTED
_DOMAIN_DECLARATION = source_eligibility.DOMAIN_DECLARATION


def _protected_classification(typed: dict[str, Any], text: str) -> bool:
    """Inspect category fields and direct declarations of the source's power.

    Owner-authored headings and labeled category fields identify protected
    powers, as do direct "You establish a Weather Domain" declarations. The
    Spear source joins its declaration to its Cost field; strip only that
    printed cost prefix before applying the same anchored declaration grammar.
    Core Formation is a Realm, not a Formation project; mentioning a protected
    target, prerequisite or Domain Armament does not classify the source.
    Typed source_category/pattern_category fields may supply explicit categories.

    Shared with combat/ext/end_effect.py; see combat/ext/source_eligibility.py.
    """
    return source_eligibility.protected_power(typed, text)


def _mechanic_of(action_id: str) -> str:
    return source_eligibility.mechanic_of(action_id)


def pattern_rank(engine: Any, item: Any) -> int:
    from ..typed_executor import CP_POOLS

    action = engine.action_catalog.get(str(getattr(item, "source_definition_id", "") or ""))
    if action is None:
        return 1
    cp = sum(int(amount) for resource_id, amount in action.costs if resource_id in CP_POOLS)
    if cp:
        return max(1, cp)
    text = rules_text().get(_mechanic_of(action.source_definition_id), "")
    match = re.search(r"Prerequisite:[^\n]*?\bCL (\d+)", text)
    cl = int(match.group(1)) if match else 1
    return 7 if cl >= 17 else 5 if cl >= 11 else 3 if cl >= 5 else 1


def patterns(engine: Any, holder: Any) -> list[tuple[str, str, Any]]:
    """(kind, key, item) for each Active Qi Pattern on ``holder``: what a typed technique left on it."""
    out = []
    for key, condition in holder.conditions.items():
        name = str(condition.condition_id)
        if not name.startswith("condition:typed.") or any(part in name for part in _BOOKKEEPING):
            continue
        action = engine.action_catalog.get(str(condition.source_definition_id or ""))
        if _supported_source(action):
            out.append(("condition", key, condition))
    for key, modifier in holder.modifiers.items():
        if str(modifier.target_field).startswith("suppressed:") or modifier.target_field == "attack_mode":
            continue
        action = engine.action_catalog.get(str(modifier.source_definition_id or ""))
        if _supported_source(action):
            out.append(("modifier", key, modifier))
    return out


def _supported_source(action: Any) -> bool:
    """Fail closed for unknown or protected source classifications.

    Printed headings/category fields and direct declarations classify Domains, Secret Inheritances,
    Formation projects, artifact and campaign workings. Protected categories
    stay unavailable until explicit permission is represented;
    their controlling conditions and modifiers are not ordinary dispellable
    patterns. Classification uses the original typed source, including variants.

    Shared with combat/ext/end_effect.py; see combat/ext/source_eligibility.py. This module's own
    ``rules_text`` is passed on, so pointing it at a fixture record redirects the shared reader too.
    """
    return source_eligibility.ordinary_source(action, rules_text)


def perceived(engine: Any, viewer: Any, holder: Any) -> bool:
    """"Active Qi Patterns ... that you can perceive": the engine's own current-perception read (sight, or a sense that
    pinpoints), so a Hidden or Invisible creature nothing locates is out of reach of a wide unweave."""
    from ..target_knowledge import located

    return located(engine, viewer, holder)


def _label(engine: Any, kind: str, item: Any, holder: Any = None) -> str:
    """What the table is choosing: the technique, what it left on the creature, who made it and the pattern's rank --
    and, for a wide unweave, which creature bears it, so two identical patterns from one creator on two creatures are
    two different options rather than the same one twice."""
    action = engine.action_catalog.get(str(item.source_definition_id or ""))
    owner = engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    what = str(item.condition_id).removeprefix("condition:typed.").replace("mark.", "").split(".")[0].replace("_", " ") if kind == "condition" \
        else str(item.target_field).replace("_", " ")
    text = (f"{getattr(action, 'display_name', 'a technique')} ({what}) from {getattr(owner, 'display_name', 'someone')}, "
            f"rank {pattern_rank(engine, item)}")
    return f"{text}, on {holder.display_name}" if holder is not None else text


@hook("compile_actions")
def unweave_actions(info: dict[str, Any]) -> list[Any] | None:
    if BASE not in set(info["owned_ids"]):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    primary = RESOURCE_IDS.get(str(info.get("primary") or ""))
    numbers = info.get("numbers") or {}
    owned = set(info["owned_ids"])
    reach = bond_reach(info, RANGE_FT)  # Meridian Grammar and the Domain widen Unweave Pattern with the bond
    made = []
    for suffix, name, target_kind in (("", "Unweave Pattern (Rapid Unweave)", "HOSTILE_ENTITY"),
                                      (".ally", "Unweave Pattern (Rapid Unweave, ally or self)", "ALLY_OR_SELF")):
        for rider, rider_name in ((None, None), *(row for row in UNWEAVING if row[0] in owned)):
            extra = 1 if rider else 0
            made.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.{BASE}.rapid{suffix}"
                + (f"+{rider.removeprefix('TAL_QIWEAVING_').lower()}" if extra else ""),
                display_name=name if not extra else f"{name} + {rider_name}", owner_id=info["actor_id"],
                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=target_kind, range_ft=reach,
                costs=((primary, 1 + extra),) if primary else (),
                parameters={"typed": {"effects": [{"type": "rapid_unweave", "applies_to": "target"}], "numbers": dict(numbers),
                                      "duration": {"kind": "instant"}, "riders": ["Cannot end protected area powers (Domains), secret inherited arts, long-term magical formation projects, artifact powers or campaign-scale magic without explicit permission. Effects whose source cannot be safely identified are not offered."], "source": BASE, "sphere": "tianxia.sphere.qiweaving"},
                            "expected_damage": 0, "rapid_unweave": True,
                            "unweaving": [rider] if extra else []}))
    return made


@hook("compile_action")
def wide_unweaves(action: Any, info: dict[str, Any]) -> Any | None:
    """Grand Unweaving and World-Circuit Severance are typed records the compiler already builds; give each its own
    resolution instead of a second action with the same name."""
    parameters = getattr(action, "parameters", None) or {}
    typed = parameters.get("typed") or {}
    source = str(typed.get("source") or "")
    if source not in (GRAND, SEVERANCE) or parameters.get("area_unweave"):
        return None
    if source == GRAND:
        effects = [{"type": "grand_unweaving", "applies_to": "creatures_in_area"}]
        riders = ["Grand Unweaving cannot affect Domains, secret inherited arts, long-term magical formation projects, artifact "
                 "powers or campaign-scale magic without explicit permission."]
    else:
        effects = [{"type": "world_circuit_severance", "applies_to": "target"}]
        riders = []
    updated = dict(typed)
    updated.update({"effects": effects, "riders": riders, "duration": {"kind": "instant"},
                    "source": source, "sphere": "tianxia.sphere.qiweaving"})
    return action.model_copy(update={
        "parameters": {**parameters, "typed": updated, "expected_damage": 0, "area_unweave": source},
        # "Choose up to a number of Active Qi Patterns you can perceive within range": the target is a pattern, not a
        # creature, so any creature may be named to aim at and the reach test in candidate_allowed is what offers it.
        **({"range_ft": SEVERANCE_RANGE_FT, "target_kind": "ANY_CREATURE"} if source == SEVERANCE else {}),
    })


@hook("candidate_allowed")
def something_to_unweave(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    which = parameters.get("area_unweave")
    if which == GRAND:
        return _any_pattern_in_area(engine, actor, candidate)
    if which == SEVERANCE:
        if actor.turn_flags.get(SEVERED):
            return False  # "Use Limit: Once per long rest" -- once per fight; there is no rest inside a fight
        return any(patterns(engine, other) for other in _perceived_in_range(engine, actor, candidate))
    if not parameters.get("rapid_unweave"):
        return None
    holders = [engine.state.actors[t] for t in getattr(candidate, "target_ids", None) or () if t in engine.state.actors] or [actor]
    return any(patterns(engine, holder) for holder in holders)


def _perceived_in_range(engine: Any, actor: Any, candidate: Any, reach: int = SEVERANCE_RANGE_FT) -> list[Any]:
    """The creatures a wide unweave can perceive within its printed range: the one the candidate names when it names
    one, otherwise every active creature inside the range, hidden ones only when something locates them."""
    named = [entity for entity in (getattr(candidate, "target_ids", None) or ()) if entity in engine.state.actors]
    pool = [engine.state.actors[entity] for entity in named] or [other for other in engine.state.actors.values() if other.active]
    return [other for other in pool if other.active and engine._distance_actor_to_actor(actor, other) <= reach
            and perceived(engine, actor, other)]


def _any_pattern_in_area(engine: Any, actor: Any, candidate: Any) -> bool:
    """Grand Unweaving is offered only where its sphere would reach a pattern the Qiweaver can perceive."""
    from ..typed_executor import area_cells

    centre = getattr(candidate, "destination", None)
    if centre is None:
        return False
    for cell in area_cells(engine, actor.position, centre, {"shape": "sphere", "size_ft": 20}):
        for other in engine.state.actors.values():
            if other.active and other.position == cell and patterns(engine, other) and perceived(engine, actor, other):
                return True
    return False


@hook("ai_candidate_allowed")
def ai_uses_a_wide_unweave_when_it_can_reach(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A wide unweave is the AI's when there is something to end; nothing else changes its choices."""
    which = (getattr(action, "parameters", None) or {}).get("area_unweave")
    if which == SEVERANCE:
        return not actor.turn_flags.get(SEVERED)
    return None


def pattern_dc(rank: int) -> int:
    """"The DC is usually 10 + the target effect's Pattern Rank": one Qiweaving Check is compared against this."""
    return 10 + max(0, int(rank))


def _roll_check(ctx: Any, holder: Any, *, advantage: bool = False) -> tuple[int, dict[str, Any]]:
    """One Qiweaving Check: the d20, its modifier and the recorded roll. The total is compared against each pattern's
    own DC by the caller, so one roll can end a low-rank pattern and leave a high-rank one."""
    from . import run as run_hooks

    modifier = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0) + sum(run_hooks("check_bonus", ctx, ctx.actor))
    roll = ctx.engine.roll_check(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f"CHECK:{ctx.source}",
                                 modes=("ADVANTAGE",) if advantage else ())
    ctx.engine._record_roll(roll)
    return int(roll.total), roll


def _record_check(ctx: Any, holder: Any, roll: Any, compared: list[tuple[str, int, bool]]) -> None:
    """One CHECK_ROLLED for the one roll, carrying every pattern it was compared against (its own DC and outcome), so
    the recorded roll stays one roll and no single DC pretends to be the whole check."""
    _first_name, first_dc, first_success = compared[0]
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
                             target_ids=((holder or ctx.actor).entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": first_dc, "success": first_success,
                                      "skill": "Qiweaving Check",
                                      "compared": [{"pattern": name, "dc": dc, "success": success}
                                                   for name, dc, success in compared]})


@effect("rapid_unweave")
def unweave(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import CP_POOLS
    from .end_effect import remove_instance
    from .needle import CHOICE, ask, checkpoint_id

    holder = ctx.target or ctx.actor
    found = patterns(ctx.engine, holder)
    if not found:
        ctx.rider(f"Unweave Pattern: {holder.display_name} bears no Active Qi Pattern.")
        return
    pb = int(ctx.numbers.get("pb") or 2)
    labels = {key: _label(ctx.engine, kind, item) for kind, key, item in found}
    # The AI prefers what its side wants gone: the target's own side's patterns on a foe, the other side's on an ally.
    preferred = sorted((key for kind, key, item in found
                        if (getattr(ctx.engine.state.actors.get(str(getattr(item, "source_actor_id", "") or "")), "team_id", None) == holder.team_id)
                        == (holder.team_id != ctx.actor.team_id)), key=lambda key: -pattern_rank(ctx.engine, next(i for _, k, i in found if k == key)))
    pool = next((p for p in CP_POOLS if p in ctx.actor.resources), None)
    augments = []
    affordable = int(ctx.actor.resources.get(pool, 0)) if pool else 0
    options = [name for name in ("certain", "broad") if affordable >= 1]
    if options:
        top = next((i for _, k, i in found if k == (preferred or [found[0][1]])[0]), found[0][2])
        rank = pattern_rank(ctx.engine, top)
        wants = ["certain"] if pb // 2 < rank <= pb and "certain" in options else []
        augments = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "rapid_unweave_augments", ctx.actor.entity_id), ctx.actor,
                       CHOICE + "rapid_unweave_augments", options, minimum=0, maximum=min(2, affordable), allow_decline=True,
                       preferred=wants, default="first" if wants else "decline", default_count=len(wants), name="Unweave Pattern",
                       labels={"certain": "Certain Unweave (1 CP): patterns of rank up to your Proficiency Bonus end automatically",
                               "broad": f"Broad Unweave (1 CP): also unweave {pb // 2} more pattern(s) on {holder.display_name}"},
                       prompt=f"Unweave Pattern on {holder.display_name}: add augments?") or []
        for _name in augments:
            ctx.engine._spend_resource(ctx.actor, pool, 1, ctx.source)
    count = 1 + (pb // 2 if "broad" in augments else 0)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "rapid_unweave", ctx.actor.entity_id, holder.entity_id), ctx.actor,
                 CHOICE + "rapid_unweave", list(labels), labels=labels, minimum=1, maximum=min(count, len(labels)), name="Unweave Pattern",
                 preferred=preferred[:count] or [found[0][1]], default_count=min(count, len(labels)), target_id=holder.entity_id,
                 prompt=f"Unweave Pattern: choose the Active Qi Pattern{'s' if count > 1 else ''} on {holder.display_name} to unweave.") \
        or [found[0][1]]
    threshold = pb if "certain" in augments else pb // 2
    ended: list[tuple[Any, Any]] = []
    for key in picked[:count]:
        kind, _, item = next(row for row in found if row[1] == key)
        if key not in (holder.conditions if kind == "condition" else holder.modifiers):
            continue
        rank = pattern_rank(ctx.engine, item)
        name = labels[key]
        # A pattern at or below the automatic threshold ends without a check; each other pattern is compared against
        # its own DC, so one Unweave Pattern that reaches two patterns rolls once per pattern it must test.
        success = rank <= threshold
        if not success:
            total, roll = _roll_check(ctx, holder)
            dc = pattern_dc(rank)
            success = total >= dc
            _record_check(ctx, holder, roll, [(name, dc, success)])
        if success:
            remove_instance(ctx, holder, kind, key, item)
            ended.append((kind, item))
            note(ctx.engine, ctx.source, ctx.actor, f"Unweave Pattern: {ctx.actor.display_name} unweaves {name} on {holder.display_name}"
                 + (" (it ends at once: low rank)." if rank <= threshold else "."), (holder,))
        else:
            note(ctx.engine, ctx.source, ctx.actor, f"Unweave Pattern: {name} on {holder.display_name} holds (the Qiweaving Check fails).", (holder,))
    for talent in (ctx.action.parameters or {}).get("unweaving") or []:
        for kind, item in ended:
            unweaving_rider(ctx, talent, holder, kind, item)


# ------------------------------------------------------------------------------------------------ the Unweaving rider
def unweaving_rider(ctx: Any, talent: str, bearer: Any, kind: str, item: Any) -> None:
    """Vicious Unweave on a pattern Unweave Pattern just ended.  The printed bearer is any creature "bearing,
    maintaining, or creating that pattern", so the Qiweaver is asked which one takes the damage; the creature that made
    the pattern is preferred when it is still in the fight, the creature it was unweaved from otherwise."""
    if talent == VICIOUS:
        _vicious(ctx, bearer, kind, item)


def _maker(engine: Any, item: Any) -> Any:
    return engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))


def _vicious(ctx: Any, bearer: Any, kind: str, item: Any) -> None:
    """Force damage by Cultivation Level (1d10 / 2d10 / 3d10 / 4d10), to one chosen creature, at most once per turn
    from this Qiweaver."""
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import _deal  # the shared damage commit every typed row uses
    from .needle import CHOICE, ask, checkpoint_id

    if not bearer.active:
        return
    taken = [entry for entry in (ctx.actor.turn_flags.get(DAZED) or [])]
    maker = _maker(ctx.engine, item)
    # "bearing, maintaining, or creating": the creature it was unweaved from bears it, and its creator maintains it.
    named: dict[str, Any] = {}
    for candidate in (bearer, maker):
        if candidate is not None and candidate.active and candidate.entity_id not in taken and candidate.entity_id not in named:
            named[candidate.entity_id] = candidate
    if not named:
        return
    order = [actor.entity_id for actor in (maker, bearer) if actor is not None and actor.entity_id in named]
    options = [entity for entity in order if entity in named]
    labels = {entity: f"{named[entity].display_name}"
                     + (" created this Active Qi Pattern" if named[entity] is maker else " bears this Active Qi Pattern")
              for entity in options}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "vicious_unweave", ctx.actor.entity_id, bearer.entity_id),
                 ctx.actor, CHOICE + "vicious_unweave", options, labels=labels, minimum=1, maximum=1, target_id=bearer.entity_id,
                 name="Vicious Unweave", preferred=options[:1],
                 prompt=(f"Vicious Unweave: you ended an Active Qi Pattern on {bearer.display_name}. Which creature takes the Force damage?")
                 ) or options[:1]
    target = named.get(str(picked[0])) or named[options[0]]
    cl = int(ctx.numbers.get("cl") or 1)
    dice = 4 if cl >= 17 else 3 if cl >= 11 else 2 if cl >= 5 else 1
    ctx.actor.turn_flags[DAZED] = [*(ctx.actor.turn_flags.get(DAZED) or []), target.entity_id]
    roll = ctx.engine.roller.roll(DiceSpec(count=dice, sides=10, modifier=0), actor_id=ctx.actor.entity_id,
                                   reason=f"DAMAGE:{ctx.source}:vicious_unweave")
    ctx.engine._record_roll(roll)
    note(ctx.engine, ctx.source, ctx.actor, f"Vicious Unweave: {target.display_name} takes {dice}d10 force damage "
         f"({roll.total}).", (target,))
    _deal(ctx, target, int(roll.total), "FORCE")


# ------------------------------------------------------------------------------------------------ the wide unweaves
def _sweep(ctx: Any, holders: list[Any], *, advantage: bool, failure: str, ceiling: int | None) -> None:
    """ONE Qiweaving Check, compared against each chosen pattern's DC separately ("Make one Qiweaving Check and
    compare the result to each chosen pattern's DC separately").  A rank-1 pattern needs 11 and a rank-7 one 17, so the
    same roll can end the first and leave the second.  ``failure`` is "remain" or "suppress"."""
    from .end_effect import remove_instance, suppress
    from .needle import CHOICE, ask, checkpoint_id

    found = [(holder, kind, key, item) for holder in holders if holder.active
             for kind, key, item in patterns(ctx.engine, holder)]
    if not found:
        ctx.rider("There is no Active Qi Pattern in reach to unweave.")
        return
    # Each option names the creature it is on: the same Active Qi Pattern from the same creator on two creatures is
    # two different things to end, and the table has to be able to tell them apart.
    labels = {f"{holder.entity_id}|{key}": _label(ctx.engine, kind, item, holder) for holder, kind, key, item in found}
    order = list(labels)
    cap = min(len(order), ceiling if ceiling else len(order))
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "wide_unweave", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "wide_unweave", order, labels=labels, minimum=1, maximum=cap, name=ctx.action.display_name,
                 preferred=order[:cap], default_count=cap, prompt=f"{ctx.action.display_name}: which Active Qi Patterns do you unweave?") \
        or order[:cap]
    chosen = [row for row in found if f"{row[0].entity_id}|{row[2]}" in picked[:cap]]
    total, roll = _roll_check(ctx, None, advantage=advantage)
    # One record of the one roll, listing each pattern with the DC it was measured against and its own outcome.
    outcomes = [(pattern_dc(pattern_rank(ctx.engine, item)), total >= pattern_dc(pattern_rank(ctx.engine, item)))
                for _holder, _kind, _key, item in chosen]
    _record_check(ctx, None, roll, [(labels[f"{holder.entity_id}|{key}"], dc, success)
                                    for (holder, _kind, key, _item), (dc, success) in zip(chosen, outcomes)])
    for (holder, kind, key, item), (dc, success) in zip(chosen, outcomes):
        if key not in (holder.conditions if kind == "condition" else holder.modifiers):
            continue
        name = labels[f"{holder.entity_id}|{key}"]
        if success:
            remove_instance(ctx, holder, kind, key, item)
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.action.display_name}: the Qiweaving Check ({total}) beats {dc}, so {name} on "
                 f"{holder.display_name} ends.", (holder,))
        elif failure == "suppress":
            # "suppressed until the start of your next turn": boundary "start", so the suppression lasts through the
            # caster's next turn and lifts at its start (end_effect's default would lift it at that turn's END).
            suppress(holder, kind, key, item, rounds=1, boundary="start", by=ctx.actor, engine=ctx.engine)
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.action.display_name}: the Qiweaving Check ({total}) fails against {dc}, so {name} on "
                 f"{holder.display_name} is suppressed until the start of your next turn.", (holder,))
        else:
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.action.display_name}: the Qiweaving Check ({total}) fails against {dc}, so {name} "
                 f"on {holder.display_name} remains.", (holder,))


@effect("grand_unweaving")
def grand_unweaving(ctx: Any, row: dict[str, Any]) -> None:
    """Every Active Qi Pattern on every creature the Qiweaver perceives inside the 20-foot sphere -- any side, its own
    included -- with one Qiweaving Check between them."""
    _sweep(ctx, [holder for holder in ctx.targets if holder.active and perceived(ctx.engine, ctx.actor, holder)],
           advantage=False, failure="remain", ceiling=None)


@effect("world_circuit_severance")
def world_circuit_severance(ctx: Any, row: dict[str, Any]) -> None:
    """Up to Proficiency Bonus perceived patterns within 120 feet, one Qiweaving Check with Advantage; a failure
    suppresses until the start of your next turn instead."""
    ctx.actor.turn_flags[SEVERED] = ctx.engine.state.round_number
    holders = [other for other in ctx.engine.state.actors.values()
               if other.active and ctx.engine._distance_actor_to_actor(ctx.actor, other) <= SEVERANCE_RANGE_FT
               and perceived(ctx.engine, ctx.actor, other)]
    _sweep(ctx, holders, advantage=True, failure="suppress", ceiling=int(ctx.numbers.get("pb") or 2))
