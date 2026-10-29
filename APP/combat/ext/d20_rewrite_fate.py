"""Fate and Karma: abilities that put a chosen die where a rolled d20 was (automation lane H1, 2026-09-29), on combat/ext/d20_rewrite.py.

Owner text (authority/typed_mechanics/rules_text.json; Tianxia Sphere Compendium), restated in engine words:
  * Rewrite the Disaster (Fate, CL 15, Reaction, 12 CP, 1/long rest): 1 creature within 60 ft, on an attack, check or save; after the
    d20 is seen and before the outcome, the die becomes a nat 1 or a nat 20. Unwilling -> Cha save, and success leaves the roll alone.
    Using it: +2 Heaven's Notice.
  * Omen Glimpse (Fate Reader, CL 3): prepare 1 Omen die (1 Resonance, roll a d20, one held); Invoke the Omen (Reaction, 1 Resonance) on
    1 creature you can see within 60 ft making an attack, check or save: before the outcome, the d20 becomes the Omen die and the die is
    expended. Unwilling target whose replacement is worse -> Cha save; fail, the swap stands; succeed, the original roll stands, the
    target is Resonance Marked by you, and you keep the Omen die until the end of your next turn.
  * Sever One Thread (Fate Reader, CL 18, Reaction, 10 Resonance) -- Reroute the Roll: force a reroll of the d20 and pick the result.
    Unwilling -> Cha save first; fail, you pick; succeed, the target picks and also suffers 2 different ordinary Spiritual Pressure
    effects. Then Fate Tension maxes (Fate-Tangled), a Severed Thread Consequence is recorded, and there is no second use until it is
    resolved.
  * Stored Glimpse (Divination Cultivator, CL 3): roll a d20 and store it (Read an Omen: 10 minutes, 1 Qi; 1 slot, 2 at CL 11). Apply
    Stored Glimpse (once per round) before you or a creature you perceive within 60 ft rolls a d20: that roll uses the stored raw result,
    then the Glimpse is erased. It is not a nat 1 or nat 20 for crit, fumble or special triggers.
  * Reversal of Due Fortune (Karma, Reaction, 4 CP plus a matching Imprint, 1/short or long rest): on a nat 1 or nat 20 within 60 ft, a
    Grace Imprint turns the nat 1 into a nat 20 and a Debt Imprint the nat 20 into a nat 1. combat/ext/karma_consumers.py already answers
    a saving throw and an enemy's nat 20 against a fighter after the roll; this module adds the cases its notes list as unautomated: a
    teammate's attack or check that is a nat 1 (Grace), and an enemy's check that is a nat 20 (Debt).

  * Fortune Reversal (Fate, CL 10, Reaction, 6 CP, 1/short rest): on a nat 1 or nat 20 on an attack, check or save within 60 ft, flip it
    (nat 1 -> nat 20, nat 20 -> nat 1). Unwilling -> Cha save, roll unchanged on success. A Legendary, Domain-bearing or
    Secret-Inheritance-protected creature may force an opposed Cultivation Check first. Using it: +1 Heaven's Notice.

Judgment calls.
  * Fortune Reversal is used once a fight (short rest = the fight) and gains its Heaven's Notice whether or not the Charisma save holds
    the roll ("using this talent"); the Legendary / Domain / Secret Inheritance opposed check is the GM's (the table tracks none of them).
  * The table asks a player only when the result would change the outcome in the holder's side's favour (ally fails -> succeeds, foe
    succeeds -> fails); it would otherwise prompt on every d20 in sixty feet. An AI holder uses the same test.
  * Whose roll: "for us" means the roller is on the holder's side and the roll is good for it, or an enemy's roll that is bad for the
    holder's side (an attack roll is aimed at the holder's side; a save an enemy makes is against our effect).
  * Omen die and Stored Glimpses are prepared before the scene (the ritual is out of the fight): the first time a d20 is rolled in the
    fight the fighter has one prepared, rolled then from the fight's own stream and paid for then (1 Resonance / 1 Qi); if it cannot pay
    it starts without. A Stored Glimpse never counts as a natural 1 or 20 here either: the engine cannot tell a replaced die from a rolled
    one, so a recorded 1 or 20 is applied as 2 or 19.
  * Sever One Thread is used once a fight (the consequence must be resolved before a second use). Reroute the Roll rerolls once and the side
    picks the better result. Rider lane C8 (2026-09-30): afterwards Fate Tension goes to its maximum (Fate-Tangled) and a resisting target
    suffers two different Spiritual Pressure effects; Restore the Omen puts the last expended Omen result on the roll (same limit); the
    recorded Severed Thread Consequence stays the GM's. Invoke the Omen resisted: the creature is Resonance Marked and the die is kept
    until the end of your next turn.

Shared Fate/Karma roll-judgement API. The other d20-rewrite plug-ins that need to know whether a die favours the character
read it from this module's public name, not a private one: good_for_us says whether a natural die result on a roll is good for
the holder's side (None when the table cannot tell). combat/ext/d20_rewrite_auspices.py is the current consumer; a further one
must use this public name and be recorded here. The die-shuffling itself is the shared helper combat/ext/d20_rewrite_rules.py
(gain adds to a resource pool; run_rows is the d20 rider log).
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import hook, note
from .d20_rewrite import Holder, RULES, Rule, RollCtx, draw, pool_id, register, row_holders
from .d20_rewrite_rules import gain, rider, run_rows

ROD = "TAL_FATE_REWRITE_THE_DISASTER"
OMEN = "tianxia.tradition.spirit.fate_reader.feature.omen_glimpse"
SEVER = "tianxia.tradition.spirit.fate_reader.feature.sever_one_thread"
GLIMPSE = "tianxia.subpath.qi.divination_cultivator.feature.stored_glimpse"
REVERSAL = "tianxia.talent.karma.reversal_of_due_fortune"
FORTUNE = "TAL_FATE_FORTUNE_REVERSAL"
_OMEN = "_round_h1_omen"      # on the fighter: the Omen die (0: expended)
_OMEN_UNTIL = "_round_c8_omen_until"  # a retained Omen die ends at the end of this turn number (rider lane C8)
_OMEN_SPENT = "_round_c8_omen_spent"  # the last expended Omen result (Sever One Thread: Restore the Omen)
_GLIMPSE = "_round_h1_glimpse"  # on the fighter: [the Stored Glimpses]


def _always(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    return True  # the rule's own guard already asks for a roll the replacement turns in the holder's side's favour


# ------------------------------------------------------------------------------------------------- reading the roll
def _ours(holder: Holder, rc: RollCtx) -> bool:
    return rc.roller.team_id == holder.actor.team_id


def good_for_us(holder: Holder, rc: RollCtx, natural: int) -> bool | None:
    """Whether the roll with ``natural`` on the die is good for the holder's side (None: the table cannot tell)."""
    if rc.kind == "attack":
        if rc.ac is None:
            return None
        from ..critical_attacks import hits
        succeeds = hits(natural, natural + rc.roll.modifier, rc.ac, (rc.spec or {}).get('critical_threshold', 20))
    else:
        if rc.dc is None:
            return None
        succeeds = natural + rc.roll.modifier >= rc.dc
    return succeeds if _ours(holder, rc) else not succeeds


def _would_help(holder: Holder, rc: RollCtx, natural: int) -> bool:
    """The roll is bad for the holder's side now and ``natural`` on the die would make it good."""
    return good_for_us(holder, rc, rc.natural) is False and good_for_us(holder, rc, natural) is True


def _worse_for_roller(holder: Holder, rc: RollCtx, natural: int) -> bool:
    return not _ours(holder, rc) and rc.natural != natural


# --------------------------------------------------------------------------------------------- Rewrite the Disaster
def _disaster_value(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return 20 if _ours(holder, rc) else 1


def _gain_notice(engine: Any, holder: Holder, rc: RollCtx) -> None:
    """Printed usage reward: paid once whether the replacement takes or is resisted."""
    gain(engine, holder, "heaven_s_notice", 2)


register(Rule(
    "rewrite_the_disaster", "Rewrite the Disaster", feature=ROD, rolls=("save", "attack", "check"), who="any", range_ft=60, when="any", op="choose",
    costs=((("cp", 12),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", unwilling="unchanged", choose=_disaster_value,
    guard=lambda engine, holder, rc: holder.actor.entity_id in (getattr(engine, "typed_ask_reactors", None) or ())
    or _would_help(holder, rc, _disaster_value(engine, holder, rc)),
    replacement_options=(1, 20), ai=_always, on_use=_gain_notice))


# ------------------------------------------------------------------------------------------------ Fortune Reversal
def _flipped(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return 20 if rc.natural == 1 else 1


def _one_notice(engine: Any, holder: Holder, rc: RollCtx, result: Any = None) -> None:
    gain(engine, holder, "heaven_s_notice", 1)


register(Rule(
    "fortune_reversal", "Fortune Reversal", feature=FORTUNE, rolls=("save", "attack", "check"), who="any", range_ft=60, when="any", op="choose",
    costs=((("cp", 6),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", unwilling="unchanged", choose=_flipped,
    guard=lambda engine, holder, rc: rc.natural in (1, 20) and _would_help(holder, rc, _flipped(engine, holder, rc)), ai=_always,
    after=_one_notice, after_resisted=lambda engine, holder, rc: _one_notice(engine, holder, rc)))


# ------------------------------------------------------------------------------------------------------- Omen die
def _die_slot(actor: Any) -> int | None:
    value = actor.turn_flags.get(_OMEN)
    return None if value is None else int(value)


def omen_holders(engine: Any) -> list[Holder]:
    """Fighters with Omen Glimpse; each has its Omen die prepared (paid and rolled) the first time a d20 is rolled in the fight."""
    holders = row_holders("omen_glimpse", OMEN)(engine)
    for holder in holders:
        actor = holder.actor
        if _die_slot(actor) is None:
            with activation(engine, actor, holder.feature_id):
                pool = pool_id(actor, "resonance")
                paid = pool is not None and actor.resources.get(pool, 0) >= 1
                if paid:
                    engine._spend_resource(actor, pool, 1, holder.feature_id)
                value = int(engine.roller.raw_d20(modifier=0, actor_id=actor.entity_id, reason="OMEN_DIE").natural_result) if paid else 0
                engine.state.roll_counter = engine.roller.counter
                actor.turn_flags[_OMEN] = value
                if paid:
                    note(engine, holder.feature_id, actor, f"{actor.display_name} has prepared an Omen die before the scene (1 Resonance).")
    return holders


def _omen_value(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return int(_die_slot(holder.actor) or 0)


def _omen_guard(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    die = _omen_value(engine, holder, rc)
    return die > 0 and _would_help(holder, rc, die)


def _omen_after(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    holder.actor.turn_flags[_OMEN_SPENT] = int(_die_slot(holder.actor) or 0)  # Sever One Thread's Restore the Omen (rider lane C8)
    holder.actor.turn_flags[_OMEN] = 0
    holder.actor.turn_flags.pop(_OMEN_UNTIL, None)
    note(engine, holder.feature_id, holder.actor, f"{holder.actor.display_name}'s Omen die is expended.")


def _omen_kept(engine: Any, holder: Holder, rc: RollCtx) -> None:
    """Invoke the Omen, target saves: the original roll stands, the target becomes Resonance Marked by the holder, and the holder
    keeps the Omen die until the end of its next turn (rider lane C8: was a GM line)."""
    run_rows(engine, holder, [rc.roller], [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                            "evidence": "the creature becomes Resonance Marked by you"}])
    holder.actor.turn_flags[_OMEN_UNTIL] = int(holder.actor.turns_started) + 1
    note(engine, holder.feature_id, holder.actor, f"{holder.actor.display_name} keeps the Omen die until the end of its next turn.", (rc.roller,))


@hook("turn_end")
def omen_retained_until(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    until = actor.turn_flags.get(_OMEN_UNTIL)
    if until is not None and custom_turn_due(actor, until, actor.turn_flags, _OMEN_UNTIL, nominal=nominal):
        actor.turn_flags[_OMEN] = 0  # the retained Omen die is gone at the end of your next turn
        actor.turn_flags.pop(_OMEN_UNTIL, None)


@hook("nominal_slot_boundary")
def nominal_omen(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        omen_retained_until(engine, actor, nominal=True)


register(Rule("omen_glimpse", "Invoke the Omen", feature=OMEN, rolls=("save", "attack", "check"), who="any", range_ft=60, see=True, when="any", op="choose",
              costs=((("resonance", 1),),), reaction=True, checkpoint="D20_REWRITE_ROLL", unwilling="unchanged", choose=_omen_value, guard=_omen_guard,
              after=_omen_after, after_resisted=_omen_kept, finder=omen_holders))


# --------------------------------------------------------------------------------------------------- Sever One Thread
def _reroute(engine: Any, holder: Holder, rc: RollCtx) -> int:
    """Reroute the Roll: one fresh d20; the side that picks (the holder, or the target if it resisted) takes the better result for itself."""
    fresh = int(draw(engine, rc.roll).natural_result)
    old = rc.natural
    holder_picks = not rc.resisted
    want_high = _ours(holder, rc) == holder_picks  # the holder wants an ally's roll high and a foe's low; a resisting foe wants its own high
    return max(old, fresh) if want_high else min(old, fresh)


def _sever_after(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    """Severed-Thread Consequence (rider lane C8): Fate Tension goes to its maximum (Fate-Tangled: the pool full), and a resisted
    Reroute gives the target two different ordinary Spiritual Pressure effects as one exceptional package; the recorded consequence
    stays the GM's."""
    pool = pool_id(holder.actor, "fate_tension")
    if pool is not None:
        room = holder.actor.resource_maximums.get(pool, 0) - holder.actor.resources.get(pool, 0)
        if room > 0:
            engine._gain_resource(holder.actor, pool, room, holder.feature_id)
    if rc.resisted and rc.roller.active:
        run_rows(engine, holder, [rc.roller], [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different ordinary Spiritual Pressure effects"},
                                               {"type": "spiritual_pressure", "applies_to": "target", "different": True,
                                                "evidence": "two different ordinary Spiritual Pressure effects"}])
    rider(engine, holder, f"Sever One Thread: {holder.actor.display_name} is Fate-Tangled and records one Severed Thread Consequence from the fixed list; "
                          "no second use until it is resolved.")


register(Rule("sever_one_thread", "Sever One Thread (Reroute the Roll)", feature=SEVER, rolls=("save", "attack", "check"), who="any", range_ft=90, when="any", op="choose",
              costs=((("resonance", 10),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", unwilling="target_chooses", choose=_reroute,
              guard=lambda engine, holder, rc: good_for_us(holder, rc, rc.natural) is False, after=_sever_after))


def _restored(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return int(holder.actor.turn_flags.get(_OMEN_SPENT) or 0)


# Restore the Omen (rider lane C8): when the holder spent an Omen die on the triggering roll or on a roll directly connected to it this
# scene, the final d20 becomes the expended Omen result instead; an unwilling target makes the same Charisma save. Same once-a-fight
# limit (holder key).
register(Rule("sever_one_thread_restore", "Sever One Thread (Restore the Omen)", feature=SEVER, rolls=("save", "attack", "check"), who="any", range_ft=90,
              when="any", op="choose", costs=((("resonance", 10),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", unwilling="unchanged",
              choose=_restored, guard=lambda engine, holder, rc: _restored(engine, holder, rc) > 0 and good_for_us(holder, rc, rc.natural) is False
              and good_for_us(holder, rc, _restored(engine, holder, rc)) is True, after=_sever_after, priority=51))


# ------------------------------------------------------------------------------------------------------ Stored Glimpse
def glimpse_holders(engine: Any) -> list[Holder]:
    """Fighters with Stored Glimpse; each has its Glimpses recorded the first time a d20 is rolled in the fight (1 Qi each)."""
    holders = row_holders("stored_glimpse", GLIMPSE)(engine)
    for holder in holders:
        actor = holder.actor
        if _GLIMPSE not in actor.turn_flags:
            with activation(engine, actor, holder.feature_id):
                slots = 2 if int(holder.numbers.get("cl") or 1) >= 11 else 1
                glimpses = []
                pool = pool_id(actor, "qi")
                for _ in range(slots):
                    if pool is None or actor.resources.get(pool, 0) < 1:
                        break
                    engine._spend_resource(actor, pool, 1, holder.feature_id)
                    glimpses.append(int(engine.roller.raw_d20(modifier=0, actor_id=actor.entity_id, reason="STORED_GLIMPSE").natural_result))
                engine.state.roll_counter = engine.roller.counter
                actor.turn_flags[_GLIMPSE] = glimpses
                if glimpses:
                    note(engine, holder.feature_id, actor, f"{actor.display_name} carries {len(glimpses)} Stored Glimpse{'s' if len(glimpses) > 1 else ''} into the scene.")
    return holders


def _glimpse_pick(holder: Holder, rc: RollCtx) -> int | None:
    """The Stored Glimpse to apply: the highest for a roll of its own side, the lowest against a foe's, when it beats an average die (10.5)."""
    glimpses = [int(value) for value in holder.actor.turn_flags.get(_GLIMPSE) or []]
    if not glimpses:
        return None
    best = max(glimpses) if _ours(holder, rc) else min(glimpses)
    return best if (best >= 11 if _ours(holder, rc) else best <= 10) else None


def _glimpse_value(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return min(19, max(2, int(_glimpse_pick(holder, rc) or 10)))  # never a natural 1 or 20 (the printed text)


def _glimpse_after(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    glimpses = list(holder.actor.turn_flags.get(_GLIMPSE) or [])
    pick = _glimpse_pick(holder, rc)
    if pick in glimpses:
        glimpses.remove(pick)
    holder.actor.turn_flags[_GLIMPSE] = glimpses


register(Rule("stored_glimpse", "Apply Stored Glimpse", feature=GLIMPSE, rolls=("save", "attack", "check"), who="any", range_ft=60, see=True, when="any", op="choose",
              limit="round", checkpoint="D20_REWRITE_ROLL", choose=_glimpse_value, finder=glimpse_holders,
              guard=lambda engine, holder, rc: _glimpse_pick(holder, rc) is not None, after=_glimpse_after))


# ------------------------------------------------------------------------------------------------ Reversal of Due Fortune
def _imprints(holder: Holder, rc: RollCtx) -> str | None:
    """"grace" for a teammate's natural 1, "debt" for an enemy's natural 20, when the holder has that Imprint on the roller."""
    from .karma_imprints import held

    kind = "grace" if _ours(holder, rc) and rc.natural == 1 else "debt" if not _ours(holder, rc) and rc.natural == 20 else None
    return kind if kind and held(rc.roller, holder.actor.entity_id, kind) else None


def _reversal_value(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return 20 if _imprints(holder, rc) == "grace" else 1


def _reversal_after(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    from .karma_imprints import spend

    # the roll is the new one now: a natural 20 came from a Grace Imprint's 1, a natural 1 from a Debt Imprint's 20
    kind = "grace" if result.natural_result == 20 else "debt"
    spend(engine, holder.actor, rc.roller, kind, 1, holder.feature_id)


register(Rule("reversal_of_due_fortune", "Reversal of Due Fortune", feature=REVERSAL, rolls=("attack", "check"), who="any", range_ft=60, when="any", op="choose",
              costs=((("cp", 4),),), reaction=True, limit="fight", checkpoint="D20_REWRITE_ROLL", choose=_reversal_value,
              guard=lambda engine, holder, rc: _imprints(holder, rc) is not None and (rc.kind != "attack" or (_ours(holder, rc) and rc.target is not None)),
              ai=_always, after=_reversal_after))
