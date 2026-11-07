"""Shared rider log helper for d20_rewrite_auspices and d20_rewrite_fate.

The abilities that reroll or replace a d20 (automation lane H1, 2026-09-29): rules for combat/ext/d20_rewrite.py.

Every rule is the owner's printed text (authority/typed_mechanics/rules_text.json). Ownership is the ``d20_rewrite`` row that
combat/rules/feature_blocks.d/auto_H1.json puts on a character that owns the feature (``kind`` = the rule); the Auspices are
carried by a condition instead (combat/ext/d20_rewrite_auspices.py).

Judgment calls that hold for the whole file (the printed text leaves them to the table):
  * "once per short rest / long rest / scene" is once per fight and "once per week" once per day (owner rulings), so a fight is the
    longest rest a limit sees.
  * "You must use the new result" is what a reroll does here: the original die never reaches its caller.
  * A saving-throw rule that names an effect's kind (Charmed, Frightened, forced movement ...) reads what the typed save imposes on
    failure; a save the table cannot classify (a zone, a hazard) does not match a rule that needs the kind.
  * "Fail" is the total against the DC the engine rolled against (a save) or a miss (an attack); a check whose DC the table cannot
    tell never counts as failed.
  * The AI uses a rule whenever its trigger is met, except an ability limited to once per fight, which waits until the holder is hurt,
    the second round has begun or the failure would impose a condition (combat/ext/d20_rewrite.py worth_it). A player on Ask me is
    asked every time.
  * Bell-Shell Guard: only its reroll is here (the Thunder reduction is its compiled reaction). It costs 1 CP (the Martial Focus variant
    needs a GM-approved bell, gong or shield-chime); "caused by sound, voice, thunder, or vibration" is a Concentration save forced by
    Thunder damage or by a Sound ability's damage, and "is Deafened" is a failed save whose failure would Deafen.
  * Perfect Counter-Evolution: the Affliction Response rerolls a failed save a hostile creature (or an unknown source) forces whose failure
    would impose one of Meridians Remember Affliction's conditions; the Adaptation is recorded immediately through adaptations.acquire and remains even after a successful reroll.
"""

from __future__ import annotations

from typing import Any

from . import hook, note
from .d20_rewrite import Holder, Rule, RollCtx, condition_holders, register, row_holders  # noqa: F401


def _pb(holder: Holder) -> int:
    return int(holder.numbers.get("pb") or 2)


def rider(engine: Any, holder: Holder, text: str) -> None:
    """A sentence the table cannot carry out on its own: the GM's line in the log."""
    engine._append_event("GM_RIDER", holder.feature_id, actor_id=holder.actor.entity_id, payload={"rider": text})


def _grants_temp_hp(engine: Any, holder: Holder, amount: int, target: Any, why: str) -> None:
    if amount > 0 and target.active:
        engine._grant_temp_hp(target, amount, holder.feature_id, holder.actor.entity_id)
        note(engine, holder.feature_id, holder.actor, f"{target.display_name} gains {amount} Temporary Hit Points ({why}).", (target,))


def _has_row(engine: Any, actor: Any, kind: str) -> bool:
    return any(row.get("block") == "d20_rewrite" and row.get("kind") == kind
               for row in (getattr(engine, "typed_passive_rows", None) or {}).get(actor.entity_id, []))


# ------------------------------------------------------------------------------------------- a fighter rerolls its own failed roll
def _gourd_step(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    if result.total < (rc.dc or 0):
        return
    if holder.data.get("kind") != "broken_gourd_native":
        rider(engine, holder, f"{holder.actor.display_name} may move up to 10 feet to a legal space without provoking Opportunity Attacks "
                             "(Broken Gourd Recovery: the new result succeeds).")
        return
    from .rider_choices import step
    step(engine, holder.actor, "broken_gourd_step", "Broken Gourd Recovery", rc.roller, 10, holder.feature_id,
         trigger="your failed Dexterity save succeeds after spending 1 Martial Focus to reroll",
         ignored_oa=[a.entity_id for a in engine.state.actors.values() if a.entity_id != holder.actor.entity_id])


register(Rule(
    "broken_gourd", "Broken Gourd Recovery", feature="TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY",
    rolls=("save",), abilities=("DEX",), costs=((("focus", 1),),), limit="fight", after=_gourd_step))

register(Rule(
    "indomitable_body", "Indomitable Body", rolls=("save",), costs=((("stamina", 3),),), limit="round"))

ASH = "tianxia.subpath.body.phoenix_rebirth_body.feature.ash_shedding_reversal"
FURNACE = "tianxia.subpath.body.phoenix_rebirth_body.feature.furnace_without_fuel"


def _furnace(engine: Any, actor: Any) -> bool:
    return any(str(row.get("feature_id") or "") == FURNACE for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _ash_guard(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    """A failed Strength, Dexterity or Constitution save; with Furnace Without Fuel also any save against Paralyzed or Stunned
    (Petrified is ``ash_shedding_petrified``'s, for 3 Embers)."""
    named = set(rc.named or ())
    if _furnace(engine, holder.actor) and "petrified" in named:
        return False
    return str(rc.ability or "").upper()[:3] in ("STR", "DEX", "CON") or (_furnace(engine, holder.actor) and bool({"paralyzed", "stunned"} & named))


def _ash_step(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    """On the new success, move up to 5 feet along a legal route without provoking (rider lane C7: it was a log line)."""
    if result.total < (rc.dc or 0) or not holder.actor.active:
        return
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(engine, holder.actor, 5)
    if not paths:
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "ash_step", holder.actor.entity_id),
                 holder.actor, "choice:needle.ash_shedding_step", sorted(paths), allow_decline=True, default="decline",
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=holder.actor.entity_id,
                 prompt="Ash-Shedding Reversal: the save succeeds; move up to 5 feet without provoking?")
    if picked and picked[0] in paths:
        step(engine, holder.actor, paths[picked[0]], ASH)


register(Rule(
    "ash_shedding_reversal", "Ash-Shedding Reversal", rolls=("save",), costs=((("rebirth_ember", 2),),),
    reaction=True, guard=_ash_guard, after=_ash_step))
register(Rule(
    "ash_shedding_petrified", "Ash-Shedding Reversal (Petrified)", feature=ASH, rolls=("save",), costs=((("rebirth_ember", 3),),), reaction=True,
    guard=lambda engine, holder, rc: _furnace(engine, holder.actor) and "petrified" in set(rc.named or ()), after=_ash_step))


def _battle_dress_temp_hp(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    if _has_row(engine, holder.actor, "ancestral_battle_dress_scripture"):
        # "Proficiency Bonus + your Equipment key ability modifier, minimum 1": the Equipment key modifier is not a sheet number the
        # table keeps, so the sheet's key modifier stands in for it.
        _grants_temp_hp(engine, holder, max(1, _pb(holder) + int(holder.numbers.get("key_mod") or 0)), holder.actor,
                        "Ancestral Battle Dress Scripture, after the reroll")


register(Rule("ancestral_battle_dress", "Ancestral Battle Dress", rolls=("save",), limit="fight", after=_battle_dress_temp_hp))
register(Rule("ancestral_battle_dress_scripture", "Ancestral Battle Dress Scripture", note_only=True))


def _escape_context(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    """Checks and saves "made to escape" a grip: Grappled, Restrained, Bound, chains, ropes, nets, manacles."""
    from ..typed_executor import CONDITION_PREFIX

    held = {c.condition_id for c in rc.roller.conditions.values()}
    grips = {CONDITION_PREFIX + name for name in ("grappled", "pinned", "restrained")}
    return bool(held & grips) and "escape" in str(rc.source_id or "").lower()


register(Rule("chain_breakers_lesson", "Chain-Breaker's Lesson", rolls=("save", "check"), limit="fight", guard=_escape_context))


# ------------------------------------------------------------------------------------------------------------------ small helpers
MENTAL = ("INT", "WIS", "CHA")
FEAR_AND_CHARM = {"charmed", "frightened", "possessed"}


def run_rows(engine: Any, holder: Holder, targets: list[Any], rows: list[dict[str, Any]]) -> None:
    """Run typed effect rows as the holder's ability (the executor's own blocks: damage, conditions, Temporary HP ...)."""
    from .. import typed_executor

    if not targets:
        return
    base = next(iter(engine.action_catalog.values()))
    action = base.model_copy(update={"source_definition_id": holder.feature_id, "display_name": str(holder.data.get("name") or holder.feature_id)})
    numbers = {**holder.numbers, "save_dc": 8 + _pb(holder) + int(holder.numbers.get("key_mod") or 0)}
    ctx = typed_executor.Context(engine, holder.actor, action, engine._active_intent, {"numbers": numbers}, list(targets), targets[0], {})
    typed_executor.run_effects(ctx, rows)


def gain(engine: Any, holder: Holder, pool: str, amount: int = 1) -> None:
    from .d20_rewrite import pool_id

    resource = pool_id(holder.actor, pool)
    if resource is not None:
        engine._gain_resource(holder.actor, resource, amount, holder.feature_id)


def _made_it(rc: RollCtx, result: Any) -> bool:
    """The resolver has already included the printed bonus in this effective total."""
    if rc.resolved_success is not None:
        return rc.resolved_success
    return rc.dc is not None and result.total >= rc.dc


def _named(rc: RollCtx, *names: str) -> bool:
    return bool(rc.named & set(names))


# ---------------------------------------------------------------------------------- a fighter rerolls its own failed roll, and adds Proficiency Bonus
def _bonus_pb(engine: Any, holder: Holder, rc: RollCtx) -> int:
    return _pb(holder)


def _counterflow_backlash(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    source = rc.source_actor
    if not _made_it(rc, result) or source is None or source.team_id == holder.actor.team_id or not source.active:
        return
    from .. import stealth

    if engine._distance_actor_to_actor(holder.actor, source) > 120 or not stealth.sees(engine, holder.actor, source):
        return
    run_rows(engine, holder, [source], [
        {"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic"],
         "evidence": "Counterflow Backlash: 3d8 Psychic or Necrotic damage"},
        {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn", "evidence": "It cannot take Reactions until the start of its next turn."}])


register(Rule("heart_devil_counterflow", "Heart-Devil Counterflow", rolls=("save",), costs=((("devil_qi", 2),),), reaction=True, limit="round",
              bonus=_bonus_pb, after=_counterflow_backlash))
register(Rule("memory_before_thought", "Memory Before Thought", rolls=("save", "check"), costs=((("resonance", 2),),), reaction=True, limit="round",
              bonus=_bonus_pb))
def _possession_posture(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    # the effect is resolved and then the ancestor's posture stays until the holder's next turn starts: no Reactions then
    # (combat/ext/ancestral_channeler.py, which also runs the Old Guard option; rider lane C8).
    from .ancestral_channeler import posture

    posture(engine, holder.actor, holder.feature_id)
    note(engine, holder.feature_id, holder.actor, f"{holder.actor.display_name}'s ancestor's posture stays until its next turn starts: "
                                                  "no Reactions (so no Possession by the Past again) until then.")


register(Rule("possession_by_the_past", "Possession by the Past", rolls=("save",), costs=((("favor", 1),), (("resonance", 2),)), reaction=True,
              after=_possession_posture))


def _wheel_turns(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    # "After the reroll, choose one" of five; the first is a Mantle switch the table does not track, so the fighter takes the
    # Temporary Hit Points (a player is not offered a menu: judgment call).
    _grants_temp_hp(engine, holder, _pb(holder), holder.actor, "Wheel Turns Once, after the reroll")


register(Rule("wheel_turns_once", "Wheel Turns Once", rolls=("save", "attack", "check"), costs=((("qi", 3),),), reaction=True, limit="round",
              after=_wheel_turns))


# ------------------------------------------------------------------------------------------------- a fighter lets an ally reroll
def _candle_temp_hp(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    if _named(rc, "frightened", "charmed", "possessed"):
        wisdom = int(holder.actor.saving_throws.get("WIS", 0))  # "Wisdom modifier + Proficiency Bonus"
        _grants_temp_hp(engine, holder, max(0, wisdom + _pb(holder)), rc.roller, "Candle Against the Dark, after the reroll")
    # "After this reaction resolves, choose one": Burn Bright or Take the Soot (combat/ext/candlemaker.py keeps the Soul Candle).
    from .candlemaker import after_candle

    after_candle(engine, holder.actor, rc.roller, rc.source_id, rc.source_actor, holder.feature_id)


register(Rule("candle_against_the_dark", "Candle Against the Dark", rolls=("save",), who="team", range_ft=30, abilities=MENTAL, costs=((("resonance", 2),),),
              reaction=True, checkpoint="D20_REROLL_ALLY", after=_candle_temp_hp))
register(Rule("marginal_correction", "Marginal Correction (Reroute the Line)", rolls=("save", "check"), who="team", range_ft=60, costs=((("resonance", 6),),),
              reaction=True, op="advantage", checkpoint="D20_REROLL_ALLY",
              guard=lambda engine, holder, rc: rc.kind == "check" or rc.ability in MENTAL))
register(Rule("waking_dream_rehearse_success", "Waking Dream Revision (Rehearse Success)", rolls=("save", "attack", "check"), who="team", range_ft=60,
              see=True, costs=((("resonance", 3),),), reaction=True, limit="round", checkpoint="D20_REROLL_ALLY"))


def _mercy_scar(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    from .mercy_flayer import gain_scar

    gain_scar(engine, holder.actor, holder.feature_id, forced=True)  # Martyr's Limit: at the maximum a Scar ruptures first
    outcome = (getattr(engine, "_typed_roll_outcome", None) or {}).get(rc.roller.entity_id)
    succeeded = outcome == "success" or (outcome is None and rc.dc is not None and result.total >= rc.dc)
    if rc.source_actor is not None and rc.source_actor.team_id != holder.actor.team_id and succeeded:
        # a successful reroll leaves the hostile source Resonance Marked by the holder (rider lane C8: was a GM line)
        run_rows(engine, holder, [rc.source_actor], [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                                      "evidence": "the hostile source becomes Resonance Marked by you"}])


def _martyr_limit(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    """Painless Martyr needs room under the Mercy Scar maximum: at the maximum it can only be used if a Scar is ruptured first
    (rider lane C8)."""
    from .d20_rewrite import pool_id
    from .mercy_flayer import ordinary_scars

    actor = holder.actor
    pool = pool_id(actor, "mercy_scar")
    return pool is None or actor.resources.get(pool, 0) < actor.resource_maximums.get(pool, 0) or ordinary_scars(actor) >= 1


register(Rule("painless_martyr", "Painless Martyr (Carry the Failure)", feature="tianxia.tradition.spirit.mercy_flayer.feature.painless_martyr", rolls=("save",), who="ally", range_ft=30, abilities=MENTAL,
              costs=((("resonance", 5),),), reaction=True, checkpoint="D20_REROLL_ALLY", guard=_martyr_limit, after=_mercy_scar))


def _echo(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    """Shared Burden, after the reroll and whatever its outcome: the holder takes one lesser emotional echo until the end of its
    next turn -- Frightened, no Reactions, Speed -10 feet, Disadvantage on its next attack, or another ordinary Spiritual Pressure
    effect (the Grief Eater picks, asked; rider lane C8: it used to be always Disadvantage). The AI keeps Disadvantage on its next
    attack."""
    from . import needle

    options = {"attack": "Disadvantage on your next attack roll", "speed": "Speed reduced by 10 feet until the end of your next turn",
               "reactions": "No Reactions until the end of your next turn", "frightened": "Frightened until the end of your next turn"}
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "CARRY_THE_ECHO", holder.actor.entity_id), holder.actor,
                        "choice:needle.grief_eater.carry_the_echo", list(options), labels=options, preferred=["attack"],
                        prompt="Carry the Echo: which lesser emotional echo do you suffer?", name="Shared Burden (Carry the Echo)",
                        feature_id=holder.feature_id)
    pick = chosen[0] if chosen and chosen[0] in options else "attack"
    if pick == "attack":
        engine._add_modifier(holder.actor, holder.feature_id, "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
    else:
        until = {"kind": "until_end_of_your_next_turn"}
        row = {"speed": {"type": "speed", "applies_to": "target", "flat": -10, "duration": until, "evidence": "Speed reduced by 10 feet"},
               "reactions": {"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "unable to take Reactions"},
               "frightened": {"type": "condition", "applies_to": "target", "condition": "frightened", "duration": until, "evidence": "Frightened"}}[pick]
        run_rows(engine, holder, [holder.actor], [row])
    note(engine, holder.feature_id, holder.actor, f"{holder.actor.display_name} suffers an emotional echo: {options[pick]}.")
    from .grief_eater import field_answer

    field_answer(engine, holder.actor, rc.roller, engine._active_intent)  # the Mourning Field's Temporary HP when it absorbs a hostile effect


register(Rule("shared_burden", "Shared Burden (Carry the Echo)", feature="tianxia.tradition.spirit.grief_eater.feature.shared_burden", rolls=("save",), who="ally", range_ft=30, abilities=MENTAL,
              costs=((("resonance", 4),), (("sorrow_burden", 2),)), reaction=True, checkpoint="D20_REROLL_ALLY", after=_echo))
def star_soul_bonus(engine: Any, holder: Holder, rc: RollCtx) -> int:
    """Star-Soul Guidance uses Stars' shared, owner-qualified Aligned query."""
    from .stars import aligned

    return _pb(holder) if aligned(engine, holder.actor, rc.roller, recipient=True) else 0


register(Rule("star_soul_guidance", "Star-Soul Guidance", rolls=("save",), who="team", range_ft=30, costs=((("cp", 3),),), reaction=True, limit="target_fight", bonus=star_soul_bonus,
              checkpoint="D20_REROLL_ALLY", guard=lambda engine, holder, rc: _named(rc, "charmed", "frightened", "possessed", "forced_movement")))
def _famine_saint_temp_hp(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    # On a successful save it gains Temporary HP equal to the holder's Proficiency Bonus + its cultivation ability modifier.
    if rc.dc is not None and result.total >= rc.dc:
        _grants_temp_hp(engine, holder, max(0, _pb(holder) + int(holder.numbers.get("key_mod") or 0)), rc.roller, "Famine Saint Intercession, after the reroll")


# Its scope (fear and exhaustion, plus hungers no typed save can name: despair, magical hunger, thirst, famine aura, deprivation,
# devouring, spiritual consumption): the table tags fear (Frightened) and Exhaustion; the rest stay with the GM.
register(Rule("famine_saint_intercession", "Famine Saint Intercession", rolls=("save",), who="team", range_ft=30, costs=((("empty_bowl_mark", 1),),),
              reaction=True, checkpoint="D20_REROLL_ALLY", guard=lambda engine, holder, rc: _named(rc, "frightened", "exhaustion"),
              after=_famine_saint_temp_hp))
register(Rule("stitch_the_broken_technique", "Stitch the Broken Technique", rolls=("save",), costs=((("cp", 3),),), reaction=True, limit="target_fight",
              bonus=_bonus_pb, guard=lambda engine, holder, rc: rc.source_id == "system:combat.concentration"))


# ------------------------------------------------------------------------------------------- rerolls that ride another feature's reaction
BELL_SHELL = "TAL_SOUND_BELL_SHELL_GUARD"
COUNTER_EVOLUTION = "tianxia.subpath.body.heaven_answering_adaptive_body.feature.perfect_counter_evolution"
SOUND_SOURCES = ("TAL_SOUND_", "SOUND_BASE_", "tianxia.talent.sound.")
AFFLICTIONS = ("blinded", "charmed", "frightened", "paralyzed", "poisoned", "restrained", "stunned")   # Meridians Remember Affliction's list


def _damage_behind_concentration(engine: Any, roller: Any) -> Any:
    """The damage that forced this Concentration save: the roller's latest DAMAGE_COMMITTED, when no other roll has been made since
    (the engine rolls the save right after committing the damage). None for a Concentration save that damage did not force."""
    for event in reversed(engine.events):
        if event.event_type == "DAMAGE_COMMITTED" and roller.entity_id in (event.target_ids or ()):
            return event
        if event.event_type in ("SAVE_ROLLED", "ATTACK_ROLLED", "TURN_STARTED", "DAMAGE_COMMITTED"):
            return None
    return None


def _sound_caused(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    """Bell-Shell Guard's reroll: a failed save that would Deafen, or a failed Concentration save forced by Thunder damage or by damage from a
    Sound ability ("caused by sound, voice, thunder, or vibration")."""
    from ..gate2_engine import SYSTEM_CONCENTRATION

    if "deafened" in rc.named:
        return True
    if rc.source_id != SYSTEM_CONCENTRATION:
        return False
    damage = _damage_behind_concentration(engine, rc.roller)
    return damage is not None and (str((damage.payload or {}).get("damage_type") or "").upper() == "THUNDER"
                                   or str(damage.source_definition_id or "").startswith(SOUND_SOURCES))


register(Rule("bell_shell_guard", "Bell-Shell Guard", feature=BELL_SHELL, rolls=("save",), who="team", range_ft=30, costs=((("cp", 1),),), reaction=True,
              checkpoint="D20_REROLL_ALLY", guard=_sound_caused))


def _hostile_affliction(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    from .adaptations import COUNTER_ROUND
    source = rc.source_actor
    return (holder.actor.turn_flags.get(COUNTER_ROUND) != engine.state.round_number
            and bool(rc.named & set(AFFLICTIONS)) and (source is None or source.team_id != holder.actor.team_id))


def _adaptation(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    from .adaptations import acquire, COUNTER_ROUND
    from .needle import ask, checkpoint_id
    actor = holder.actor
    actor.turn_flags[COUNTER_ROUND] = engine.state.round_number
    options = sorted(rc.named & set(AFFLICTIONS))
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "counter_affliction", actor.entity_id),
                 actor, "choice:needle.counter_affliction", options,
                 labels={o: o.title() for o in options}, prompt=f"Perfect Counter-Evolution: choose {actor.display_name}'s Affliction Adaptation.")
    if picked:
        acquire(engine, actor, "afflictions", {"condition": picked[0], "by": getattr(rc.source_actor, "entity_id", ""),
                "source": rc.source_id or "", "ability": rc.ability, "dc": rc.dc}, source=holder.feature_id)


register(Rule("perfect_counter_evolution", "Perfect Counter-Evolution (Affliction Response)", feature=COUNTER_EVOLUTION, rolls=("save",),
              costs=((("stamina", 2),),), reaction=True, limit="round", guard=_hostile_affliction, after=_adaptation))


# ---------------------------------------------------------------------------------------- a fighter makes a foe reroll an attack that hit it
def _foe_reroll_riders(text: str):
    def after(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
        rider(engine, holder, text)
    return after


register(Rule("laughing_at_certain_death_attack", "Laughing at Certain Death", rolls=("attack",), who="enemy", when="hit", op="disadvantage",
              costs=((("focus", 1),),), reaction=True, limit="fight", checkpoint="D20_REROLL_ATTACK",
              after=_foe_reroll_riders("If the rerolled attack misses, the fighter may redirect it to another legal target within its reach or range (Laughing at Certain Death).")))
register(Rule("laughing_at_certain_death_save", "Laughing at Certain Death", rolls=("save",), abilities=("DEX", "WIS"), op="advantage", costs=((("focus", 1),),),
              reaction=True, limit="fight",
              after=lambda engine, holder, rc, result: rider(
                  engine, holder, f"{holder.actor.display_name} may move up to half its Speed without provoking after the effect resolves "
                                  "(Laughing at Certain Death: the new result succeeds).") if result.total >= (rc.dc or 0) else None))
EMPTY_CUP_MOVED = "_empty_cup_moved"


def _empty_cup_move(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    """Empty Cup (rider lane C7): after the reroll the holder moves up to 10 feet without provoking Opportunity Attacks, and during
    that move may fall Prone or stand from Prone. The rerolled attack is then resolved against the new space: it hits only if it can
    still reach. The defender picks a square within 10 feet along a legal route (or stays) plus falling Prone or standing; the attack
    is rechecked in empty_cup_reach_check (hit_response) against the new space."""
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import routes, step

    actor = holder.actor
    attacker = getattr(rc.roller, "entity_id", None) and rc.roller
    intent = getattr(engine, "_active_intent", None)
    paths = routes(engine, actor, 10) if actor.active else {}
    if paths:
        far = sorted(paths, key=lambda key: (-(engine.grid.distance_ft(paths[key][-1], attacker.position) if attacker is not None else 0), key))
        chosen = ask(engine, intent, checkpoint_id(engine, "empty_cup_move", actor.entity_id), actor, "choice:needle.empty_cup_move",
                     [*far, "stay"], labels={**{key: "Move to " + key.removeprefix("cell:") for key in far}, "stay": "Stay where you are"},
                     prompt=f"Empty Cup: after the rerolled attack against {actor.display_name}, move up to 10 feet without provoking.",
                     target_id=actor.entity_id)
        if chosen and chosen[0] in paths:
            step(engine, actor, paths[chosen[0]], holder.feature_id)
    prone = any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())
    posture = ask(engine, intent, checkpoint_id(engine, "empty_cup_posture", actor.entity_id), actor, "choice:needle.empty_cup_posture",
                  ["stand" if prone else "fall_prone"], allow_decline=True, default="decline",
                  labels={"stand": "Stand up from Prone", "fall_prone": "Fall Prone"},
                  prompt=f"Empty Cup: {actor.display_name} may {'stand up' if prone else 'fall Prone'} during this movement.",
                  target_id=actor.entity_id)
    if posture == ["fall_prone"]:
        engine._apply_condition(actor, "condition:typed.prone", holder.feature_id, actor.entity_id, expires_on="STAND_UP")
    elif posture == ["stand"]:
        for iid, condition in list(actor.conditions.items()):
            if condition.condition_id == "condition:typed.prone":
                actor.conditions.pop(iid)
                engine._append_event("CONDITION_REMOVED", holder.feature_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    if attacker is not None:
        from .attack_scope import current

        frame = current(engine)
        engine.__dict__[EMPTY_CUP_MOVED] = (attacker.entity_id, actor.entity_id, id(frame) if frame is not None else None)


@hook("hit_response")
def empty_cup_reach_check(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    """The rerolled attack still hits only if it can reach the Empty Cup user's new space (the attack's own reach/range check)."""
    from .attack_scope import current

    moved = engine.__dict__.get(EMPTY_CUP_MOVED)
    frame = current(engine)
    if not moved or moved[0] != attacker.entity_id or moved[1] != target.entity_id or moved[2] != (id(frame) if frame is not None else None):
        return None
    engine.__dict__[EMPTY_CUP_MOVED] = None
    check = (spec or {}).get("target_check")
    if check is not None and not check():
        note(engine, "Empty Cup", target, f"Empty Cup: {attacker.display_name}'s rerolled attack can no longer reach {target.display_name}; it misses.",
             (attacker,))
        return effective_ac, False
    return None


register(Rule("empty_cup", "Empty Cup", rolls=("attack",), who="enemy", when="hit", op="disadvantage", costs=((("stamina", 2),),), reaction=True, limit="round",
              checkpoint="D20_REROLL_ATTACK", after=_empty_cup_move))
