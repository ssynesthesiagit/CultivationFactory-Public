"""The Thread Sphere's two line-correction reactions: Puppet-Line Correction and Borrow the Ally's Arm
(automation lane AUTO19, 2026-10-04; corrected by AUTO19f1, 2026-10-05).

Source (owner text: APP/authority/typed_mechanics/rules_text.json ``tianxia.talent.thread.puppet_line_correction``
and ``TAL_THREAD_BORROW_THE_ALLY_S_ARM``; the Sphere Compendium's Thread chapter -- there is no Spheres 5e or D&D 5.5e
equivalent to fall back on):

  Puppet-Line Correction -- "Trigger: A creature connected to your Thread Line makes an attack roll, Strength check,
    Dexterity check, or Dexterity saving throw.  Cost: 2 CP.  Effect: If the creature is willing, it adds your Proficiency
    Bonus to the roll.  If the creature is unwilling, it makes a Wisdom saving throw.  On a failure, subtract your
    Proficiency Bonus from the roll.  On a success, the roll is unaffected."

  Borrow the Ally's Arm -- "Trigger: A willing ally connected to one of your Thread Lines misses with a melee attack or
    fails a Strength or Dexterity ability check.  Cost: 1 CP.  Effect: You pull, guide, brace, or correct the ally's
    motion.  The ally may add your Proficiency Bonus to the roll.  This can turn a failure into a success."

Why a plug-in rather than typed rows.  Both talents print ONE effect whose SIGN depends on the rolling creature's
willingness, and Borrow the Ally's Arm answers only rolls that have already come out wrong ("misses", "fails").
``combat/typed_reactions.py``'s generic ``creature_d20`` reaction (``on_d20_pending``) is the engine's home for "somebody
else's roll, answered before it": it applies the top-level ``attack_modifier`` rows and then signs that single amount
from team membership alone, so it cannot answer a willing creature differently from an unwilling one, and it runs
before the d20 exists, when "misses" and "fails" are not yet known.  The documented ``d20_bonus`` seam
(``combat/roll_checkpoints.py``; the hook list in ``combat/ext/__init__.py``) runs with the d20 in hand and its native
context, so one shared implementation answers both talents exactly as printed.

Readings, stated because the printed text leaves them to the table:

* **Willingness is the affected creature's answer, not the weaver's guess.** "If the creature is willing ...
  If the creature is unwilling ..." describes what the rolling creature does, so it is asked of that creature through
  the shared consent transport (``combat/ext/willing_targets.asks_consent``), never inferred from which side it
  stands on. A creature the table runs on its own decides for itself -- an allied asker is accepted and a hostile
  one refused -- and a player controlling it is asked, whether it is that creature's own turn or somebody else's, so
  a willing opposing creature can still be helped and an unwilling ally can still refuse. Borrow the Ally's Arm is
  printed for "a willing ally", so it additionally never answers a creature on the other side.
* **The printed price is paid for the attempt, not for its outcome.** "Cost: 2 CP" (1 CP for Borrow) is charged, and
  the Reaction spent, when the Thread user chooses to use the talent. "On a success, the roll is unaffected" says
  what the saving throw does to the roll, not that the activation is free, so a creature that resists successfully
  still costs the weaver the printed price and the Reaction. There is no printed refund.
* **A refusal is only as bad as the talent's own text says.** Puppet-Line Correction is hostile to an unwilling
  creature and prints the Wisdom saving throw, so its consent question quotes it. Borrow the Ally's Arm prints
  none: it is guidance for "a willing ally", so refusing leaves the roll exactly as it was and the Thread user
  spends neither CP nor the Reaction -- which is what the code does, and what the question now says.
* **Each talent asks its own question.** The two offers on one roll are different offers at different prices, so
  a creature that refuses the cheaper Borrow the Ally's Arm (1 CP, "nothing happens at all") is asked again about
  Puppet-Line Correction (2 CP, a Wisdom saving throw) rather than having the first answer counted for both. One
  willingness answer is remembered per line, creature and talent, and only for that same roll.
* The cheaper printed option is offered first for a creature both talents reach (Borrow the Ally's Arm at 1 CP,
  before Puppet-Line Correction at 2 CP).

Thread range is Draw the Line's own printed range -- "Range: Mundane 20 feet, Qi Thread 30 feet" -- read by the
shared queries of combat/ext/thread_common.py.

Inert without the talent: every answer starts from this module's own feature-block passive row, so a character without
the talent has nothing to run and an old saved fight replays unchanged.  No engine or core class is patched and no
saved-fight field is added: the answer is the roll's own modifier plus an existing D20_REWRITTEN event.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import hook, note
from .d20_rewrite import context_of
from .needle import CHOICE, ask, checkpoint_id, numbers_of
from .thread_common import thread_line_held_by, thread_range_ft
from .willing_targets import asks_consent

BLOCK = "thread_correction"
PUPPET = "tianxia.talent.thread.puppet_line_correction"
BORROW = "TAL_THREAD_BORROW_THE_ALLY_S_ARM"
COST = {PUPPET: 2, BORROW: 1}
NAME = {PUPPET: "Puppet-Line Correction", BORROW: "Borrow the Ally's Arm"}
KIND = {PUPPET: "puppet_line_correction", BORROW: "borrow_the_ally_s_arm"}
CP_POOLS_HINT = "CP (cultivation points from your Qi, Stamina or other pool)"


# ------------------------------------------------------------------------------- ownership (feature-block passive rows)
@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Record that this Thread user owns the talent (combat/typed_reactions.compile_blocks' plug-in block).

    The talent's own typed effects are empty on purpose: the printed bonus is answered here, from the roll, not by
    the before-the-roll generic reaction row.  This row is what makes the character own the talent at the table.
    """
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": str(spec.get("kind") or ""), "cp": int(spec.get("cp") or 0)}]


def _rows(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("kind")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK}


# ------------------------------------------------------------------------------- who may answer
def _bears_line(engine: Any, roller: Any, weaver: Any) -> bool:
    """The Thread Line mark ``weaver`` placed on ``roller`` (the shared query of combat/ext/thread_common.py)."""
    return thread_line_held_by(engine, roller, weaver)


def _melee_roll(engine: Any, rc: Any) -> bool:
    from ..attack_reach import melee

    action = engine.action_catalog.get(str(rc.source_id or ""))
    if action is not None:
        return bool(melee(action))
    return int((rc.spec or {}).get("range_ft") or 0) <= 5  # an unbound roll: a reach-sized attack is melee


def _covers(rc: Any, talent: str) -> bool:
    """Whether this roll is one the printed trigger names."""
    ability = str(rc.ability or "").upper()
    if talent == PUPPET:  # "an attack roll, Strength check, Dexterity check, or Dexterity saving throw"
        return rc.kind == "attack" or (rc.kind == "save" and ability == "DEX") or (rc.kind == "check" and ability in ("STR", "DEX"))
    # "misses with a melee attack or fails a Strength or Dexterity ability check"
    if rc.kind == "attack":
        return rc.ac is not None and rc.total < int(rc.ac) and _melee_roll(rc.engine, rc)
    return rc.kind == "check" and ability in ("STR", "DEX") and rc.dc is not None and rc.total < int(rc.dc)


def _pool(weaver: Any) -> str:
    from ..typed_executor import CP_POOLS

    pools = [pool for pool in CP_POOLS if weaver.resource_maximums.get(pool, 0) > 0]
    return max(pools, key=lambda pool: weaver.resources.get(pool, 0), default="")


def _answers(engine: Any, rc: Any) -> list[tuple[Any, str, str]]:
    """(Thread user, talent id, CP pool id) able to answer this roll: in Thread range, thread still on the roller,
    Reaction free and enough CP for the printed price. The cheaper printed option comes first."""
    out = []
    for weaver in engine.state.actors.values():
        if not weaver.active or weaver.entity_id == rc.roller.entity_id or not weaver.reaction_available:
            continue
        rows = _rows(engine, weaver)
        if not rows or engine._distance_actor_to_actor(weaver, rc.roller) > thread_range_ft(engine, weaver):
            continue
        if not _bears_line(engine, rc.roller, weaver):
            continue
        pool = _pool(weaver)
        if not pool:
            continue
        for talent in (BORROW, PUPPET):
            row = rows.get(KIND[talent])
            if row is None or weaver.resources.get(pool, 0) < int(row.get("cp") or COST[talent]):
                continue
            if talent == BORROW and weaver.team_id != rc.roller.team_id:
                continue  # printed "a willing ally": never an enemy's roll
            if _covers(rc, talent):
                out.append((weaver, talent, pool))
    return out


# ------------------------------------------------------------------------------- the printed answers
_ABILITY_NAME = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence",
                 "WIS": "Wisdom", "CHA": "Charisma"}


def _what_is_rolled(rc: Any) -> str:
    """The roll in plain words, for the prompt and the fight log (a player knows only basic D&D)."""
    action = rc.engine.action_catalog.get(str(rc.source_id or ""))
    suffix = f" for {action.display_name}" if action is not None else ""
    if rc.kind == "attack":
        return "an attack roll" + suffix
    ability = _ABILITY_NAME.get(str(rc.ability or "").upper(), "an ability")
    return (f"a {ability} saving throw" if rc.kind == "save" else f"a {ability} check") + suffix


def _resists(engine: Any, weaver: Any, roller: Any, talent: str) -> int:
    """"it makes a Wisdom saving throw.  On a failure, subtract your Proficiency Bonus from the roll.  On a success, the
    roll is unaffected."  Returns the signed bonus to add (0 when the save succeeds). The printed cost and the
    Reaction are already spent: the printed text refunds neither."""
    dc = int(numbers_of(engine, weaver).get("save_dc") or 10)
    roll = engine._roll_save(roller, "WIS", dc, talent)
    if roll is None or roll.total >= dc:
        note(engine, talent, weaver, f"{NAME[talent]}: {roller.display_name} shrugs your line off -- its Wisdom saving throw against your "
             f"Cultivation Save DC ({dc}) succeeds, so its roll is unchanged. You still spent your Reaction and {COST[talent]} CP.", (roller,))
        return 0
    note(engine, talent, weaver, f"{NAME[talent]}: {roller.display_name} fails the Wisdom saving throw against your Cultivation Save DC "
         f"({dc}), so your line pulls its roll down by your Proficiency Bonus ({int(weaver.proficiency_bonus)}).", (roller,))
    return -int(weaver.proficiency_bonus)


@hook("d20_bonus")
def line_correction(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    if roll.natural_result is None or getattr(engine, "_thread_correction_rolling", False):
        return None
    rc = context_of(engine, roll)
    if rc is None or rc.kind not in ("attack", "save", "check"):
        return None
    consent: dict[tuple[str, str, str], bool] = {}  # one willingness answer per line, creature and TALENT
    for weaver, talent, pool in _answers(engine, rc):
        if not _weaver_agrees(engine, intent, weaver, rc, talent):
            continue
        willing = _is_willing(engine, intent, weaver, rc, talent, consent)
        if talent == BORROW and not willing:
            continue  # printed "a willing ally": a refusal ends this option, not the question
        with activation(engine, weaver, talent):
            engine.__dict__["_thread_correction_rolling"] = True  # the Wisdom save this may roll is not a second answer
            try:
                cost = COST[talent]
                engine._spend_resource(weaver, pool, cost, talent)   # "Cost: 2 CP" is the price of the attempt
                from ..activation_payments import reaction_completed
                from ..typed_reactions import spend_reaction

                spend_reaction(engine, weaver, {"feature_id": talent})
                reaction_completed(engine, weaver, talent)
                bonus = int(weaver.proficiency_bonus) if willing else _resists(engine, weaver, rc.roller, talent)
                if not bonus:
                    return None  # a resisted roll is left alone, as printed; the price and the Reaction are spent
                sign = "adds your Proficiency Bonus to" if bonus > 0 else "subtracts your Proficiency Bonus from"
                note(engine, talent, weaver, f"{NAME[talent]}: your line {sign} {rc.roller.display_name}'s {_what_is_rolled(rc)} "
                     f"(you spend your Reaction and {cost} CP).", (rc.roller,))
                engine._append_event("REACTION_RESOLVED", talent, actor_id=weaver.entity_id, target_ids=(rc.roller.entity_id,),
                                     payload={"checkpoint": "D20_BONUS", "bonus": bonus, "roll": rc.kind, "willing": willing})
                return {"source_id": talent, "bonus": bonus, "user_id": weaver.entity_id}
            finally:
                engine.__dict__.pop("_thread_correction_rolling", None)
    return None


# ------------------------------------------------------------------------------- the two questions
def _weaver_agrees(engine: Any, intent: Any, weaver: Any, rc: Any, talent: str) -> bool:
    """The Thread user chooses to spend the printed price and the Reaction; False passes on this roll. A player is
    asked and an AI Thread user answers through the same shared chooser."""
    from .choice_prompt import action_context

    # A saving creature is affected by the source's action; it is not using
    # that action itself. Unknown save sources must stay unattributed.
    actor = rc.source_actor if rc.kind == "save" else rc.roller
    context = action_context(engine, actor, str(rc.source_id or ""), rc.roller)
    context.update(cost=f"your Reaction and {COST[talent]} {CP_POOLS_HINT}", paying_pool=_pool(weaver))
    prompt = (f"{NAME[talent]} -- you pull, brace or correct {rc.roller.display_name}, which is connected to one of your "
              f"Thread Lines, while it rolls {_what_is_rolled(rc)}. Using this costs your Reaction and {COST[talent]} "
              f"{CP_POOLS_HINT}. "
              + (f"If {rc.roller.display_name} is willing, it adds your Proficiency Bonus (+{weaver.proficiency_bonus}) to that "
                 f"roll; if it is unwilling, it must first make a Wisdom saving throw against your Cultivation Save DC, and only "
                 f"a failure takes your Proficiency Bonus ({weaver.proficiency_bonus}) off that roll."
                 if talent == PUPPET else
                 f"A willing {rc.roller.display_name} adds your Proficiency Bonus (+{weaver.proficiency_bonus}) to that roll, "
                 f"which can turn a miss or a failure into a success."))
    picked = ask(engine, intent, checkpoint_id(engine, "thread_correction", f"{talent}:{rc.roller.entity_id}"), weaver,
                 CHOICE + f"thread_correction.{talent}", [NAME[talent]], labels={NAME[talent]: prompt}, name=NAME[talent],
                 feature_id=talent, preferred=[NAME[talent]], allow_decline=True, target_id=rc.roller.entity_id,
                 prompt=prompt, prompt_context=context)
    return bool(picked)


def _is_willing(engine: Any, intent: Any, weaver: Any, rc: Any, talent: str,
                answered: dict[tuple[str, str, str], bool]) -> bool:
    """"If the creature is willing ... If the creature is unwilling ..." -- the rolling creature's own answer, asked
    through the shared consent transport rather than read off which side it stands on.

    What refusing costs is the talent's own printed text, and the two talents print different consequences.
    Puppet-Line Correction is hostile to an unwilling creature -- "it makes a Wisdom saving throw.  On a failure,
    subtract your Proficiency Bonus from the roll" -- so its question says so.  Borrow the Ally's Arm prints no
    such thing: it is guidance for "a willing ally", and a refusal only means the Thread user does not spend the
    1 CP or the Reaction on it at all.  The first cut of this module used Puppet's wording for both, which
    described a saving throw and a penalty Borrow the Ally's Arm never applies and pressured a player into
    accepting using consequences that do not exist.

    One answer per line, creature AND talent, because the two questions are about different offers at different
    prices.  Refusing Borrow the Ally's Arm's 1 CP guidance says only that nothing happens at all; it is not an
    answer to Puppet-Line Correction's 2 CP correction, and the creature is asked again for that one rather than
    having its roll pulled down on a saving throw it was never told about.
    """
    key = (weaver.entity_id, rc.roller.entity_id, talent)
    if key not in answered:
        dc = int(numbers_of(engine, weaver).get("save_dc") or 10)
        cost = f"{COST[talent]} {CP_POOLS_HINT}"
        if talent == PUPPET:
            refusal = (f"Refuse, and {rc.roller.display_name} must first make a Wisdom saving throw against "
                       f"{weaver.display_name}'s Cultivation Save DC ({dc}); only a failure takes {weaver.display_name}'s "
                       f"Proficiency Bonus ({weaver.proficiency_bonus}) off that roll, and a success leaves the roll as it is.")
        else:
            refusal = (f"Refuse, and nothing happens at all: {rc.roller.display_name}'s roll is left exactly as it is, "
                       f"and {weaver.display_name} spends no CP and keeps their Reaction.")
        prompt = (f"{weaver.display_name} offers to help with {_what_is_rolled(rc)} using a Thread Line, through "
                  f"{NAME[talent]}. Accept, and {rc.roller.display_name}'s roll gains {weaver.display_name}'s "
                  f"Proficiency Bonus (+{weaver.proficiency_bonus}) while {weaver.display_name} spends their Reaction "
                  f"and {cost}. {refusal} Accept or refuse?")
        answered[key] = asks_consent(engine, intent, rc.roller, NAME[talent], prompt,
                                     prefer_accept=weaver.team_id == rc.roller.team_id, asker=weaver)
    return answered[key]
