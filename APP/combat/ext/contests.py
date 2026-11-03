"""Opt-in opposed checks shared by typed actions and technique reactions.

contest_against selects the actor's check and the defender's check/save/printed DC before
rolling, then runs on_success or on_fail on that defender. Multi-target rows
resolve separately. The resolver/result live in typed_executor; no persistent
objects, global changes, or inference from an actor's unrelated abilities.

A menu of printed alternatives is ranked by how often each one actually works, counted
over `D20_PAIRS` -- the 400 equally likely pairs of two d20s, which is also the unit a printed
difficulty is counted in (it draws no die, so its chance is that count twenty times over). That is
what lets a rolled check and a printed difficulty be compared at all: they are different units
until the die is put back in, and a "bigger number is a harder gate" shortcut gets ordinary
numbers wrong. `holds_against_die`, `reaches_difficulty` / `holds_against_difficulty` and
`printed_modifier` are the three pure pieces; `select_check` is the only place that composes them.
"""
from dataclasses import replace
from typing import Any

from . import effect
from .needle import CHOICE, ask, checkpoint_id

D20_PAIRS = 400  # two d20s are 400 equally likely pairs; a printed difficulty draws no die of its own,
                 # so its share of them is the same chance counted twenty times over


def holds_against_die(attacker_bonus: int, defender_bonus: int) -> int:
    """Out of `D20_PAIRS`: how often a defending d20 + ``defender_bonus`` holds against d20 + ``attacker_bonus``.

    A rolled contest is won only by the higher total, so the pairs that draw level hold for the defender.
    """
    gap = int(attacker_bonus) - int(defender_bonus)
    beaten = sum(min(20, max(0, roll + gap - 1)) for roll in range(1, 21))
    return D20_PAIRS - beaten


def reaches_difficulty(attacker_bonus: int, difficulty: int) -> int:
    """Out of `D20_PAIRS`: how often a d20 + ``attacker_bonus`` reaches a printed ``difficulty``.

    A fixed difficulty is met by getting to the number, so landing exactly on it is one of these rolls.
    """
    short = min(20, max(0, int(difficulty) - 1 - int(attacker_bonus)))
    return 20 * (20 - short)


def holds_against_difficulty(attacker_bonus: int, difficulty: int) -> int:
    """Out of `D20_PAIRS`: how often a d20 + ``attacker_bonus`` falls short of a printed ``difficulty``.

    The complement of `reaches_difficulty`: the same number a defence of this difficulty holds on.
    """
    return D20_PAIRS - reaches_difficulty(attacker_bonus, difficulty)


def printed_modifier(engine: Any, actor: Any, row: dict[str, Any], *, numbers: dict[str, Any] | None = None) -> int | None:
    """The bonus the d20 of one printed alternative carries, or None when it prints a difficulty.

    ``kind`` names the shape: ``cultivation`` (Proficiency Bonus plus Key Ability modifier), ``key_ability``
    (the creature's own Key Ability, no Proficiency Bonus), ``save`` (one saving throw) or a plain ability /
    skill check. A ``dc`` alternative prints a number instead of a die, so the caller resolves that number
    through `combat/save_dcs.py` and asks `reaches_difficulty` about it.
    """
    from ..ability_checks import ability_modifier, key_modifier, skill_bonus

    if row.get("kind") == "dc":
        return None
    ability = str(row.get("ability") or "").upper()
    if row.get("kind") == "cultivation":
        return int((numbers or {}).get("pb") or actor.proficiency_bonus) + int((numbers or {}).get("key_mod") or 0)
    if row.get("kind") == "key_ability":
        return key_modifier(engine, actor, numbers=numbers)
    if row.get("kind") == "save":
        return int(actor.saving_throws.get(ability, 0))
    fallback = (int(actor.dexterity_score) - 10) // 2 if ability == "DEX" else None
    modifier = ability_modifier(actor, ability, numbers=numbers, fallback=fallback)
    if row.get("skill"):
        modifier = skill_bonus(engine, actor, str(row["skill"]), modifier)
    return modifier


def select_check(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any], side: str,
                 opposing: dict[str, Any] | None = None) -> dict[str, Any]:
    """A printed alternative belongs to its roller; the AI takes the one that works most often.

    Every alternative is scored out of `D20_PAIRS` by how often its own roller gets what it came for -- the
    attacker's land rate, the defender's hold rate, which are complements of each other -- so a printed
    difficulty and a rolled check sit on one scale with the d20 actually in the arithmetic. That is what
    makes them comparable: against a +7 Sound Check a difficulty of 15 is reached by 13 rolls in 20, while a
    defending +7 check is beaten by 19 in 40, so the check holds more often even though 15 is the bigger
    number.

    ``opposing`` is the other side's printed check: the alternative it has already chosen when this is the
    defender's turn to answer, or the whole spec it chooses from when this is the attacker's. A rolled attack
    improves exactly with its own bonus whatever the defence turns out to be, so the attacker is measured
    against the best defence the opponent could print rather than a guess; with no ``opposing`` at all the
    alternatives are ranked against a plain +0 attack.
    """
    options = spec.get("options") or [spec]
    if len(options) == 1:
        return dict(options[0])
    choices = {str(i): row for i, row in enumerate(options)}
    defending = side == "target"
    foe_rows = list((opposing or {}).get("options") or ([opposing] if opposing else []))

    def numbers_for(who: Any) -> dict[str, Any]:
        from .needle import numbers_of

        return ctx.numbers if who is ctx.actor else numbers_of(ctx.engine, who)

    def bonus_of(who: Any, row: dict[str, Any]) -> int | None:
        """What the d20 of this alternative carries, or None when it prints a difficulty instead."""
        return printed_modifier(ctx.engine, who, row, numbers=numbers_for(who))

    def difficulty_of(who: Any, row: dict[str, Any]) -> int:
        from ..save_dcs import save_dc

        return save_dc(ctx.engine, who, str(row.get("basis") or "save_dc"))

    def attack_on() -> int:
        """The attack already made, as a d20 bonus: the alternative the opponent chose, when it is known."""
        bonuses = [bonus_of(opponent, row) for row in foe_rows]
        return max((bonus for bonus in bonuses if bonus is not None), default=0)

    def defence_against(attack: int) -> int:
        """How well the opponent's best printed alternative holds against a d20 + ``attack``.

        Nothing printed to measure against (no ``opposing``) is read as one defending d20 and no die,
        which keeps the ranking among a menu of rolled checks in the order their bonuses run: a bigger
        attack bonus can only help, whatever the defence turns out to be.
        """
        rows = foe_rows or [{"kind": "check"}]
        holds = []
        for row in rows:
            if row.get("kind") == "dc":
                holds.append(holds_against_difficulty(attack, difficulty_of(opponent, row)))
            else:
                holds.append(holds_against_die(attack, bonus_of(opponent, row)))
        return max(holds, default=0)

    def strength(row: dict[str, Any]) -> int:
        """Out of `D20_PAIRS`: how often this alternative hands its own roller what it came for."""
        mine = bonus_of(subject, row)
        if row.get("kind") == "dc":
            # A printed difficulty draws no defending die: the attacker has to reach the number itself.
            attack = mine if mine is not None else attack_on()
            lands = reaches_difficulty(attack, difficulty_of(subject, row))
            return D20_PAIRS - lands if defending else lands
        if defending:
            return holds_against_die(attack_on(), mine)
        return D20_PAIRS - defence_against(mine)

    from .rider_choices import trigger_name

    reaction = str(ctx.action.display_name or "an opposed check")
    trigger = trigger_name(ctx.engine)
    opening = (f"{reaction} against {opponent.display_name}" if trigger in ("", reaction)
               else f"{reaction} against {opponent.display_name} using {trigger}")
    # A tie is only a thing between two rolled checks: facing a printed difficulty there is nothing to
    # roll for, and reaching that number exactly succeeds. A menu offering both has to state both rules,
    # or the player is told a tie rule applies to the difficulty they did not pick.
    kinds = [row.get("kind") for row in choices.values()]
    printed, rolled = "dc" in kinds, any(kind != "dc" for kind in kinds)
    if printed and rolled:
        closing = ("choose what to roll or which difficulty to meet: a rolled check has to be beaten by a higher "
                   "total, and a tie leaves the situation unchanged, while a printed difficulty is met by a total "
                   "that reaches it exactly.")
    elif printed:
        closing = "choose the difficulty the opposing roll must meet; a total that reaches it exactly succeeds."
    else:
        closing = "choose your opposing roll. A tie leaves the situation unchanged."
    chosen = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, "contest_" + side, ctx.source, ctx.actor.entity_id, opponent.entity_id),
                 subject, CHOICE + "contest_" + side, list(choices),
                 preferred=[max(choices, key=lambda key: strength(choices[key]))], target_id=opponent.entity_id,
                 labels={key: str(row.get("label") or row.get("skill") or row.get("ability")) for key, row in choices.items()},
                 prompt=f"{opening}: {subject.display_name}, {closing}")
    return dict(choices[chosen[0]])


def _optional(sub: Any, opponent: Any, rider: dict[str, Any]) -> bool:
    """A printed "you may" on a won contest is the actor's own decision.

    Asked through the ordinary checkpoint, so it is put to the player on their own turn and
    on a hostile's, and an AI combatant answers it for itself (combat/ext/needle.ask). Nothing
    answering takes the printed benefit, which is what the AI would choose anyway.
    The prompt names what triggered the contest, the creature it landed on, and -- from the
    row's own ``reading``, when it has one -- what accepting actually does, so a player is
    never asked to answer for a phrase they have not been told.
    """
    from .rider_choices import trigger_name

    label = str(rider.get("label") or "the extra benefit").rstrip(". ")
    reaction = str(sub.action.display_name or "the check")
    trigger = trigger_name(sub.engine)
    opening = (f"{reaction} against {opponent.display_name}" if trigger in ("", reaction)
               else f"{reaction} against {opponent.display_name} using {trigger}")
    reading = str(rider.get("reading") or "").strip()
    explain = f" {reading}" if reading else ""
    chosen = ask(sub.engine, sub.intent,
                 checkpoint_id(sub.engine, "contest_optional", sub.source, sub.actor.entity_id, opponent.entity_id),
                 sub.actor, CHOICE + "contest_optional", ["apply", "skip"],
                 labels={"apply": f"Apply {label}", "skip": f"Skip {label}"},
                 preferred=["apply"], allow_decline=True, target_id=opponent.entity_id,
                 name=label,
                 prompt=f"{opening}: apply {label}? The check was won by {rider.get('margin')} or more.{explain}")
    return bool(chosen) and chosen[0] == "apply"


@effect("contest_against")
def contest_against(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_subjects, resolve_opposed_check, run_effects

    for target in effect_subjects(ctx, row, harmful=True):
        if target is ctx.actor or not target.active:
            continue
        sub = replace(ctx, targets=[target], target=target)
        ours = select_check(sub, ctx.actor, target, row["actor_check"], "actor", opposing=row["target_check"])
        theirs = select_check(sub, target, ctx.actor, row["target_check"], "target", opposing=ours)
        result = resolve_opposed_check(sub, target, ours, theirs,
                                      save_fail_effects=row.get("on_success") or [],
                                      save_success_effects=row.get("on_fail") or [])
        branch = row.get("on_success" if result.success else "on_fail") or []
        run_effects(sub, [dict(e) for e in branch])
        if result.success:
            for rider in row.get("success_by") or []:
                if result.margin < int(rider["margin"]):
                    continue
                if rider.get("optional") and not _optional(sub, target, {**rider, "margin": result.margin}):
                    continue
                run_effects(sub, [dict(e) for e in rider.get("effects") or []])
