"""A floor under a d20 roll (sys-resources-states 2026-09-29: Complete Mandala Auspice, TAL_FATE_COMPLETE_MANDALA_AUSPICE).

Source (owner text, authority/typed_mechanics/rules_text.json and the Sphere Compendium, Fate, Auspices):
  "When the target makes an ability check using a skill or tool proficiency, it treats a d20 roll of 9 or lower as a 10."
  "Release: The target releases this Auspice after an ally within 30 feet makes an ability check. If the d20 result was
   lower than 10, treat it as 10."
  Auspice rules: "If the Auspice is active on a willing creature, that creature can end it as a Reaction to gain the Release
  effect. If the creature is Incapacitated, it can release an Auspice only if the talent explicitly permits it."
The floor is D&D 5.5e's own reading of "treat a d20 roll of 9 or lower as a 10" (the Reliable Talent wording): the die stays
as rolled -- a natural 1 is still a 1 for anything that reads it -- and the total is worked out as if it were the floor.

Effect type "d20_floor" (an ability's typed effect): {"type": "d20_floor", "applies_to": "target" | "self" | "ally",
"floor": 10, "release": {"range_ft": 30}, "duration": ...}. It puts "condition:typed.d20_floor" on the subject, lasting as
any typed effect does (Concentration: it ends with the caster's). Where the engine rolls a skill check it calls
``ext.floored(engine, actor, roll, dc)`` (combat/ext/__init__.py), which asks the "check_floor" hook here.

Two readings, and one judgment call:
  * The bearer's own check is raised at once (the passive half of the text).
  * An ally's check is raised only by the bearer's Release, and a Release is a Reaction the bearer chooses to spend, so it
    is used only when it changes the outcome -- the check's DC is known, the ally rolled below the floor, and the floor
    would make it: an AI-controlled bearer does it on its own, a player-controlled Ask me bearer is asked (a button, the
    same question every Reaction asks). A check with no DC to beat (an opposed roll not made yet) is never Released for.
  * Every skill check the engine rolls (Stealth, Athletics/Acrobatics, Perception, Sleight of Hand, ...) is one "using a
    skill or tool proficiency" -- the engine does not model a check made with no skill at all (GM).
Releasing ends the Auspice: the caster's Concentration on it, and the condition, end (evented, in the log).
Determinism: the condition and the Concentration change only through the engine's evented methods.


One use, kept for a printed cost (Imbuement, Clarify and Cloud, owner 2026-10-04): ``"once": true`` with
``"keep": [["cp", 1]]``. The floor is then a single replacement: the first check it raises asks the printed payer whether to
spend the printed cost to keep the effect alive, and a payer who does not (or cannot) ends it there -- exactly the printed
"Once this replacement is used, the Mandate ends unless you spend 1 CP to keep it active". ``"keep_payer": "caster"`` names
who "you" is in that sentence: with it the Imbuement caster pays from its own Path pool (combat/ext/cp_pools.py), without it
the bearer does, which is the reading for a row that says the bearer spends. Either way the payment is a player decision
(asked, automatic for the AI), and paying leaves the floor available for the next check at the same price. Without ``once``
the floor never runs out, so an older saved row keeps its old behaviour byte for byte.

Three more documented keys, all optional and all defaulting to the behaviour an older row already had (AUTO20f1):
``"abilities": ["WIS"]`` narrows the floor to the printed "one *such* ability check" -- a check made with one of the listed
abilities, read from the roll's own d20 scope (``ext.floored`` publishes the caller's ability, and the engine's own
``d20_scope`` already carries it). A row without the key floors every check it is asked about, exactly as before.
``"optional": true`` makes the replacement the bearer's *choice*, which the printed "it may treat" is: the bearer is asked,
a decline leaves the roll as rolled and the effect alive, and the AI decides for itself. The payment question is a separate
one, asked only once the replacement has actually been used.

Who is asked, and who answers (AUTO20r1f1): a question goes to the bearer (the use) and to the printed payer (the keep cost),
and the creature that decides for itself is the one the table runs by computer -- ``ext.ai_controlled`` reads the match's own
recorded control mode, which is what separates a computer-run ally from a person-run one. Team membership is not a control
mode. A person at the table is asked on their own turn and on an AI turn alike, through the service's existing routing.

More than one floor on one bearer (AUTO20r1f1): the floors that could cover a roll are tried best first -- the highest floor,
and a floor that applies on its own before one that has to spend a replacement its bearer may decline. Declining an optional
Clarify therefore leaves the roll alone *for that Mandate* and still lets an unrelated Auspice raise it; two floor-10
Auspices where one is optional never spend the replacement to reach a number the other grants for free.

Every question names the ability that asked, the check that triggered it and the creature it affects, so two buffs on one
creature, or a caster paying its own cost, are not guesses (AUTO20r1f1). The ability's name is stored on the condition, so
it survives a table commit and reload -- beside the printed rule, not inside it (AUTO20r2f1): ``rule`` holds the mechanical
facts a saved row is read for, and Complete Mandala Auspice's own regression requires it to hold nothing but its two
printed numbers. The keep-cost question also separates the two things it is about: the sentence that reports the raised
roll names the skill the table actually rolled ("Insight (Wisdom)"), and the benefit being bought names the scope the row
really keeps ("the next low Wisdom ability check"), because a Wisdom Clarify covers Perception as well (AUTO20r2f1).

Shared end_auspice API used by fate_riders and d20_rewrite_auspices: end the exact granted auspice and matching concentration instance through evented helpers. end_auspice is the public entry point; a further consumer must use it directly.
"""

from __future__ import annotations

from ..paid_relocation import activation

import re
from typing import Any

from . import ai_controlled, effect, hook, note

CONDITION = "condition:typed.d20_floor"
CHECKPOINT = "ALLY_CHECK_ROLLED"


def _rule(condition: Any) -> dict[str, Any]:
    from ..typed_executor import is_active_typed_condition

    if not is_active_typed_condition(condition):
        return {}
    return ((condition.data or {}).get("rule") or {}).get("d20_floor") or {}


def _keep_cost(rule: dict[str, Any]) -> list[Any]:
    """A printed "spend N CP to keep it active" cost: [["cp", 1]] -> [("resource id", 1)] is resolved by the payer."""
    return [list(row) for row in (rule.get("keep") or []) if isinstance(row, (list, tuple)) and len(row) == 2]


def _scope_abilities(rule: dict[str, Any]) -> list[str]:
    """The abilities this floor covers, upper-cased three-letter codes; empty when the row names none (and so covers
    every check, which is what an older saved row did)."""
    return [str(value).upper()[:3] for value in rule.get("abilities") or [] if str(value).strip()]


def _check_ability(engine: Any, roll: Any) -> str:
    """The ability of the check being floored, or "" when the table records none.

    Two places carry it, and neither is this plug-in's business to add: the roll's own d20 scope
    (``engine.d20_context``), which the engine's own checks set, and the roll's reason, which names the skill for every
    skill check the table rolls (``CHECK:<source>:<Skill>``, mapped through the table's own skill list)."""
    try:
        ability = str((engine.d20_context(roll) or {}).get("ability") or "")[:3].upper()
    except Exception:  # pragma: no cover - a plug-in never decides a printed rule on a broken engine
        ability = ""
    if ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        return ability
    _, _, tail = str(getattr(roll, "reason", "") or "").partition(":")
    label = tail.rpartition(":")[2] or tail
    if label in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        return label
    from ..tabletop import ABILITY_NAMES, SKILLS

    spelled = next((code for code, name in ABILITY_NAMES.items() if name.lower() == label.strip("() ").lower()), "")
    return spelled or next((code for name, code in SKILLS if name.lower() == label.strip("() ").lower()), "")


def _covers(engine: Any, rule: dict[str, Any], roll: Any) -> bool:
    """Whether this floor covers the check the table is rolling now (the printed "one *such* ability check")."""
    wanted = _scope_abilities(rule)
    return not wanted or _check_ability(engine, roll) in wanted


def _payer(engine: Any, bearer: Any, condition: Any, rule: dict[str, Any]) -> Any:
    """Who the printed "spend ... to keep it active" names. ``"keep_payer": "caster"`` is "you" in a sentence whose
    subject is the caster (Imbuement's Clarify); otherwise it is the bearer."""
    if str(rule.get("keep_payer") or "bearer").lower() == "caster":
        return engine.state.actors.get(condition.source_actor_id) or bearer
    return bearer


def _source_name(engine: Any, condition: Any, rule: dict[str, Any]) -> str:
    """The plain name of the ability that granted this floor ("Place Mandate: Clarify").

    Presentation, so it lives beside the printed rule on the condition (``data["source_name"]``) and not inside it:
    a row's rule dictionary is the printed rule and nothing else, and Complete Mandala Auspice's own regression
    (tests/test_sys_resources_states.py) requires its rule to stay exactly ``{"floor": 10, "release_range_ft": 30}``.
    A row saved before the name existed reads it from inside the rule if it is there, and otherwise from the action
    catalog, which is the table's own record of what the feature is called; a feature id nothing in the catalog
    knows names nothing, so a player is never shown an internal id (AUTO20r1f1, AUTO20r2f1)."""
    stored = str((condition.data or {}).get("source_name") or rule.get("source_name") or "").strip()
    if stored:
        return stored
    action = (getattr(engine, "action_catalog", {}) or {}).get(str(condition.source_definition_id))
    name = str(getattr(action, "display_name", "") or "").strip()
    return name if name and name != str(condition.source_definition_id) else ""


def _skill_of(engine: Any, roll: Any) -> str:
    """The skill the table rolled, in plain words, or "".

    The roll's own d20 scope names it ("Insight"), which is where every check the engine raises carries it. The roll's
    reason is only a fallback, and only when its tail is plainly a name: a check rolled against an action carries that
    action's id there, and an internal id is never player text (AUTO20r1f1)."""
    try:
        skill = str((engine.d20_context(roll) or {}).get("skill") or "").strip()
    except Exception:  # pragma: no cover - a plug-in never reads player text off a broken engine
        skill = ""
    if skill:
        return skill
    tail = str(getattr(roll, "reason", "") or "").partition(":")[2].rpartition(":")[2].strip()
    return tail if re.fullmatch(r"[A-Za-z][A-Za-z '\-]*", tail or "x") else ""


def _check_label(engine: Any, rule: dict[str, Any], roll: Any) -> str:
    """The check being floored, in the words a player would use: the skill the table named and the ability it
    uses, e.g. "Insight (Wisdom)", "Wisdom", or "this ability check" when the roll records neither."""
    from .escape_dc_text import ability_name

    codes = _scope_abilities(rule)
    code = _check_ability(engine, roll) or (codes[0] if codes else "")
    named = ability_name(code) if code else ""
    skill = _skill_of(engine, roll)
    if skill and skill.lower() != named.lower():
        return f"{skill} ({named})" if named else skill
    return named or "this ability check"


def _scope_label(rule: dict[str, Any]) -> str:
    """What the floor still covers after the roll it just raised: the printed "one *such* ability check" scope,
    not the skill that happened to trigger it (AUTO20r2f1).

    A Wisdom Clarify stores ``abilities: ["WIS"]``, so keeping it alive for an Insight check also keeps it for the
    next Perception check. Saying "the next low Insight (Wisdom) roll" would promise the payer a narrower benefit
    than the row grants, so this names the ability the choice was made from and leaves the triggering skill to the
    sentence that reports the roll that was raised."""
    from .escape_dc_text import ability_name

    codes = _scope_abilities(rule)
    if not codes:
        return "ability check"
    return f"{' or '.join(ability_name(code) for code in codes)} ability check"



@effect("d20_floor")
def grant(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    floor = int(eff.get("floor") or 0)
    if floor < 2:
        return
    release = eff.get("release") if isinstance(eff.get("release"), dict) else {}
    keep = _keep_cost(eff)
    abilities = _scope_abilities(eff)
    payer = ctx.actor if str(eff.get("keep_payer") or "bearer").lower() == "caster" else None
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is None or not subject.active:
            continue
        for iid, condition in list(subject.conditions.items()):  # a second Auspice of the kind replaces the first
            if condition.condition_id == CONDITION and condition.source_definition_id == ctx.source \
                    and condition.source_actor_id == ctx.actor.entity_id:
                ctx.engine._remove_condition(subject, condition.condition_id, ctx.source)
        what = (f"an ability check using {' or '.join(code.title() for code in abilities)}" if abilities
                else "an ability check using a skill or tool proficiency")
        # "The next time" belongs to a printed single replacement; a row with no ``once`` keeps working on
        # every roll, and must not tell the player it is spent after the first one (AUTO20r1f1).
        reading = ((f"The next time {subject.display_name} makes {what}, " if eff.get("once")
                    else f"Each time {subject.display_name} makes {what}, ")
                   + f"a d20 roll of {floor - 1} or lower counts as a {floor}.")
        if eff.get("optional"):
            reading += (f" {subject.display_name} chooses whether to use it on each such roll, and a roll it does not use "
                        "is left as it came up.")
        if release.get("range_ft"):
            reading += (f" It can also end early: if an ally within {int(release['range_ft'])} feet rolls lower than {floor} on "
                        "an ability check and spending the Auspice would turn that failure into a success, the ally's roll "
                        "counts as a " + str(floor) + " and the Auspice ends there.")
        if eff.get("once"):
            reading += (f" It raises one low roll and no more; the moment it does, {payer.display_name if payer else subject.display_name} "
                        f"may spend {' or '.join(f'{amount} {str(resource).upper()}' for resource, amount in keep) or 'nothing'} "
                        "to keep this going, or the effect ends there.")

        rule = {"floor": floor, "release_range_ft": int(release.get("range_ft") or 0)}
        if eff.get("once"):
            rule["once"] = True
        if keep:
            rule["keep"] = keep
        if abilities:
            rule["abilities"] = abilities
        if eff.get("optional"):
            rule["optional"] = True
        if payer is not None:
            rule["keep_payer"] = "caster"
        data = {"rule": {"d20_floor": rule},
                "label": f"A roll of {floor - 1} or lower counts as a {floor} on {what}", "reading": reading}
        # The ability's own name, so a later question can name the ability that asked (AUTO20r1f1). It is player
        # text, so it is stored beside the printed rule rather than inside it (AUTO20r2f1): every granted floor's
        # rule dictionary is read by its own regression, and Complete Mandala Auspice's is required to hold nothing
        # but its two printed numbers.
        granted_by = str(getattr(ctx, "action", None).display_name or "").strip() if getattr(ctx, "action", None) else ""
        if granted_by and granted_by != str(ctx.source):
            data["source_name"] = granted_by
        ctx.engine._apply_condition(
            subject, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
            data=data)


def end_auspice(engine: Any, bearer: Any, condition: Any, why: str) -> None:
    """End this bearer's grant; other recipients and concentration copies stay."""
    from .. import concentration

    concentration.end_recipient(engine, engine.state.actors.get(condition.source_actor_id),
                                condition.source_definition_id, bearer, why,
                                applied_sequence=condition.applied_sequence)



def _release(engine: Any, actor: Any, roll: Any, dc: int | None) -> int | None:
    """A bearer within range of the ally's check Releases the Auspice when that turns the ally's failure into a success."""
    from .. import typed_reactions

    if dc is None or roll.total >= dc:
        return None
    for bearer in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if bearer.entity_id == actor.entity_id or bearer.team_id != actor.team_id:
            continue
        for condition in list(bearer.conditions.values()):
            if condition.condition_id != CONDITION or not _rule(condition):
                continue
            rule = _rule(condition)
            floor, reach = int(rule.get("floor") or 0), int(rule.get("release_range_ft") or 0)
            if not reach or roll.natural_result >= floor or roll.total + floor - roll.natural_result < dc:
                continue
            if engine._distance_actor_to_actor(bearer, actor) > reach or not typed_reactions._can_react(engine, bearer):
                continue
            row = {"feature_id": condition.source_definition_id, "ask": True}
            if not typed_reactions._consent(engine, row, bearer, CHECKPOINT):
                continue
            with activation(engine, bearer, condition.source_definition_id):
                typed_reactions._open(engine, row, bearer, (actor.entity_id,), CHECKPOINT)
                bearer.reaction_available = False
                note(engine, condition.source_definition_id, bearer,
                     f"{bearer.display_name} releases the Auspice: {actor.display_name}'s d20 {roll.natural_result} counts as {floor}.", (actor,))
                end_auspice(engine, bearer, condition, "RELEASED")
                return floor
    return None


def _ranked(own: list[tuple[Any, dict[str, Any]]]) -> list[tuple[Any, dict[str, Any]]]:
    """The floors that could cover this roll, best first: the highest floor, and a floor that applies on its
    own before one that has to spend a replacement its bearer may decline (AUTO20r1f1).

    With two Auspices of floor 10 on one bearer, an unconditional one is used without asking anything,
    and the optional Clarify that would have to be spent to reach the same number is never asked.
    """
    return sorted(own, key=lambda pair: (int(pair[1].get("floor") or 0), not pair[1].get("optional")), reverse=True)


@hook("check_floor")
def check_floor(engine: Any, actor: Any, roll: Any, dc: int | None) -> int | None:
    own = [(condition, _rule(condition)) for condition in actor.conditions.values()
           if condition.condition_id == CONDITION and _rule(condition) and _covers(engine, _rule(condition), roll)]
    if not own:
        return _release(engine, actor, roll, dc)
    for condition, rule in _ranked(own):
        floor = int(rule.get("floor") or 0)
        if roll.natural_result >= floor:
            return floor
        if rule.get("optional") and not _accepted(engine, actor, condition, rule, roll):
            # "it may treat a roll lower than 10 as a 10": a decline leaves the roll as rolled and this
            # effect alive -- but another floor this roll really does qualify for may still raise it
            # (AUTO20r1f1: declining one Mandate used to silence an unrelated Auspice on the same bearer).
            continue
        note(engine, "d20_floor", actor, f"{actor.display_name}'s roll of {roll.natural_result} counts as {floor}.")
        if rule.get("once"):
            _spent(engine, actor, condition, rule, roll)
        return floor
    return None


def _accepted(engine: Any, bearer: Any, condition: Any, rule: dict[str, Any], roll: Any) -> bool:
    """The printed "it may": the bearer is asked whether to use the replacement. Asked on the player's turn and on an AI
    turn, answered for the AI without a prompt, and a decline (or nobody there to answer) leaves the roll alone."""
    from . import needle

    floor = int(rule.get("floor") or 10)
    natural = int(getattr(roll, "natural_result", 0) or 0)
    check = _check_label(engine, rule, roll)
    named = _source_name(engine, condition, rule)
    subject = f"{named} on {bearer.display_name}" if named else f"an effect on {bearer.display_name}"
    picked = needle.ask(engine, None, needle.checkpoint_id(engine, "D20_FLOOR_USE", condition.source_definition_id,
                                                           bearer.entity_id),
                        bearer, needle.CHOICE + "d20_floor_use", ["use", "skip"],
                        labels={"use": f"Count the {check} roll of {natural} as a {floor}",
                                "skip": f"Leave the {check} roll of {natural} as it came up"},
                        preferred=["use"], allow_decline=True, name=f"Use this low {check} roll as a {floor}",
                        prompt=(f"{subject} lets {bearer.display_name} treat a d20 roll of {floor - 1} or lower as a "
                                f"{floor} on {check}. {bearer.display_name} just rolled {natural} on {check}. Count that "
                                f"{check} roll as a {floor}?"),
                        automatic=ai_controlled(engine, bearer), target_id=bearer.entity_id,
                        default="decline")
    return bool(picked) and picked[0] == "use"


def _spent(engine: Any, bearer: Any, condition: Any, rule: dict[str, Any], roll: Any) -> None:
    """"Once this replacement is used, the Mandate ends unless you spend 1 CP to keep it active": the printed payer is
    asked. They may keep paying for the next low roll; a decline, or a payer who cannot afford it, ends the effect now --
    which is what the printed sentence says happens when the cost is not spent."""
    from . import cp_pools, needle
    from .choice_costs import payable

    amount = sum(int(value) for resource, value in _keep_cost(rule) if str(resource).lower() == "cp")
    payer = _payer(engine, bearer, condition, rule)
    pool = cp_pools.of(payer, at_least=amount) if amount else None
    payment = payable(payer, pool, amount) if pool else None
    floor = int(rule.get("floor") or 10)
    paid = False
    if payment is not None:
        named = _source_name(engine, condition, rule)
        subject = f"{named} on {bearer.display_name}" if named else f"this effect on {bearer.display_name}"
        check = _check_label(engine, rule, roll)
        scope = _scope_label(rule)
        picked = needle.ask(engine, None, needle.checkpoint_id(engine, "D20_FLOOR_KEEP", condition.source_definition_id,
                                                                payer.entity_id),
                            payer, needle.CHOICE + "d20_floor_keep", ["keep", "end"],
                            labels={"keep": f"Spend {payment.quote()} so it can raise one more low {scope}",
                                    "end": "Let the effect end now"},
                            preferred=["keep"], allow_decline=True, name="Keep the effect going",
                            prompt=(f"{subject} has just raised {bearer.display_name}'s {check} roll to a {floor}. "
                                    f"{payer.display_name} may spend {payment.quote()} to keep it active for the next "
                                    f"low {scope}; if it is not spent, the effect ends. Pay, or let it end?"),
                            automatic=ai_controlled(engine, payer), target_id=bearer.entity_id,
                            default="decline",
                            prompt_context={"cost": payment.quote(), "paying_pool": payment.pool})
        if picked and picked[0] == "keep":
            with activation(engine, payer, f"{condition.source_definition_id}.d20_floor.keep"):
                payment.pay(engine, payer, f"{condition.source_definition_id}.d20_floor.keep")
                note(engine, condition.source_definition_id, payer,
                     f"{payer.display_name} spends {payment.quote()} to keep the effect on {bearer.display_name} going.", (bearer,))
                paid = True
    if not paid:
        note(engine, condition.source_definition_id, payer,
             f"The effect has raised one low roll and nothing was spent to keep it, so it ends on {bearer.display_name}.", (bearer,))
        end_auspice(engine, bearer, condition, "FLOOR_SPENT")
