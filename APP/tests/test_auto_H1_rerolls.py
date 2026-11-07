"""Lane H1, family 2: rerolls that add a bonus, that help an ally, or that make a foe reroll an attack that hit the fighter (Heart-Devil
Counterflow, Memory Before Thought, Possession by the Past, Wheel Turns Once, Candle Against the Dark, Marginal Correction, Waking Dream
Revision, Painless Martyr, Shared Burden, Star-Soul Guidance, Stitch the Broken Technique, Laughing at Certain Death, Empty Cup)."""

import pytest

from tests.h1_support import ALLY, FOE, ME, amount, attack, duel, events, force_save, give, rewrites, script

COUNTERFLOW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.heart_devil_counterflow"
MEMORY = "tianxia.subpath.qi.bloodline_cultivator.feature.ancestral_memory_unsealed"
POSSESSION = "tianxia.tradition.spirit.ancestral_channeler.feature.possession_by_the_past"
WHEEL = "tianxia.subpath.qi.samsara_wheel_cultivator.feature.wheel_turns_once"
CANDLE = "tianxia.tradition.spirit.candlemaker.feature.candle_against_the_dark"
MARGINAL = "tianxia.tradition.spirit.echo_scribe.feature.marginal_correction"
WAKING = "tianxia.tradition.spirit.dreamweaver.feature.waking_dream_revision"
MARTYR = "tianxia.tradition.spirit.mercy_flayer.feature.painless_martyr"
BURDEN = "tianxia.tradition.spirit.grief_eater.feature.shared_burden"
STAR_SOUL = "tianxia.talent.stars.star_soul_guidance"
STITCH = "tianxia.talent.thread.stitch_the_broken_technique"
LAUGHING = "TAL_DRUNKEN_STYLE_LAUGHING_AT_CERTAIN_DEATH"
EMPTY_CUP = "tianxia.subpath.body.drunken_fist.feature.empty_cup"
DC = 16  # every saving throw modifier is +2


def _has(actor, condition):
    return any(c.condition_id.startswith(condition) for c in actor.conditions.values())


# --------------------------------------------------------------------------------------------------- a bonus rides the reroll
def test_heart_devil_counterflow_rerolls_adds_proficiency_bonus_and_backlashes_on_the_source():
    engine = duel(COUNTERFLOW)
    give(engine, ME, devil_qi=2)
    foe = engine.state.actors[FOE]
    hp = foe.current_hp
    # 3 + 2 fails DC 16; the reroll 12 + 2 = 14 still fails on the die but +4 (Proficiency Bonus) = 18 succeeds.
    script(engine, [3, 12, 5, 5, 5])
    force_save(engine, ME, "WIS", dc=DC, typed=True, condition="frightened")
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == COUNTERFLOW and amount(engine, ME, "devil_qi") == 0
    assert not _has(engine.state.actors[ME], "condition:core.frightened") and not _has(engine.state.actors[ME], "condition:typed.frightened")
    assert not any("frightened" in c.condition_id for c in engine.state.actors[ME].conditions.values())
    assert foe.current_hp == hp - 15  # 3d8, dice scripted to 5 each
    assert any("reaction" in c.condition_id for c in foe.conditions.values())
    assert not engine.state.actors[ME].reaction_available


def test_heart_devil_counterflow_without_the_bonus_reaching_the_dc_still_fails_and_no_backlash():
    engine = duel(COUNTERFLOW)
    give(engine, ME, devil_qi=2)
    foe = engine.state.actors[FOE]
    hp = foe.current_hp
    script(engine, [3, 2])
    force_save(engine, ME, "WIS", dc=DC, typed=True, condition="frightened")
    assert len(rewrites(engine)) == 1 and foe.current_hp == hp
    assert any("frightened" in c.condition_id for c in engine.state.actors[ME].conditions.values())


def test_memory_before_thought_rerolls_a_failed_save_or_check_for_two_resonance_once_a_round():
    engine = duel(MEMORY, primary="Resonance")
    script(engine, [2, 11, 2, 11])
    force_save(engine, ME, "CON", dc=DC, typed=True, condition="prone")
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "resonance") == 28
    assert not any("prone" in c.condition_id for c in engine.state.actors[ME].conditions.values())  # 11 + 2 + 4 = 17
    force_save(engine, ME, "CON", dc=DC)          # a Reaction and a round's use are gone
    assert len(rewrites(engine)) == 1


def test_possession_by_the_past_pays_favor_first_then_resonance():
    engine = duel(POSSESSION, primary="Resonance")
    give(engine, ME, favor=1)
    script(engine, [2, 18])
    force_save(engine, ME, "DEX", dc=DC)
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "favor") == 0 and amount(engine, ME, "resonance") == 30
    engine.state.actors[ME].reaction_available = True
    # rider lane C8: "the ancestor's posture lingers until the start of your next turn. During that time, you cannot use
    # Possession by the Past again and cannot take Reactions" -- so not again before ME's next turn starts
    script(engine, [2, 18])
    force_save(engine, ME, "DEX", dc=DC)
    assert len(rewrites(engine)) == 1
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[ME].reaction_available = True
    script(engine, [2, 18])
    force_save(engine, ME, "DEX", dc=DC)
    assert len(rewrites(engine)) == 2 and amount(engine, ME, "resonance") == 28


def test_wheel_turns_once_rerolls_a_missed_attack_a_failed_check_and_grants_temporary_hp():
    engine = duel(WHEEL)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    script(engine, [2, 19])
    assert attack(engine, ME, FOE, bonus=0, ac=12) is True   # 2 misses AC 12, the reroll 19 hits
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == WHEEL and amount(engine, ME, "qi") == 27 and me.temporary_hp == 4
    me.reaction_available = True
    engine.state.round_number += 1
    script(engine, [2, 18])
    force_save(engine, ME, "STR", dc=DC)
    assert len(rewrites(engine)) == 2 and foe.current_hp <= foe.maximum_hp


# ----------------------------------------------------------------------------------------------- the fighter helps an ally reroll
def test_candle_against_the_dark_lets_an_ally_reroll_a_failed_mental_save():
    engine = duel(CANDLE, ally_mids=[], primary="Resonance")
    script(engine, [2, 17])
    roll = force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="frightened")
    (rewrite,) = rewrites(engine)
    assert rewrite.actor_id == ALLY and rewrite.source_definition_id == CANDLE
    assert roll.payload["natural_result"] == 17 and roll.payload["success"] is True
    assert amount(engine, ME, "resonance") == 28 and not engine.state.actors[ME].reaction_available
    assert engine.state.actors[ALLY].temporary_hp == 6  # the effect involves fear: Wisdom modifier + Proficiency Bonus, even on a success


def test_candle_against_the_dark_gives_temporary_hp_when_a_fear_effect_is_rerolled_and_ignores_a_strength_save_and_a_foe():
    engine = duel(CANDLE, ally_mids=[], primary="Resonance")
    script(engine, [2, 3])
    force_save(engine, ALLY, "STR", dc=DC)               # not Intelligence, Wisdom or Charisma
    force_save(engine, FOE, "WIS", dc=DC)                # a foe is not helped
    assert not rewrites(engine)
    script(engine, [2, 4])
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="frightened")  # rerolled, still fails: the fear effect lands
    assert len(rewrites(engine)) == 1 and engine.state.actors[ALLY].temporary_hp == 4 + 2


def test_marginal_correction_rerolls_with_advantage():
    engine = duel(MARGINAL, ally_mids=[], primary="Resonance")
    script(engine, [2, 5, 18])
    roll = force_save(engine, ALLY, "INT", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == MARGINAL and rewrite.payload["result"]["natural_result"] == 18
    assert roll.total == 20 and amount(engine, ME, "resonance") == 24


def test_waking_dream_revision_rehearses_success_for_an_ally_attack_once_a_round():
    engine = duel(WAKING, ally_mids=[], primary="Resonance")
    script(engine, [2, 17])
    assert attack(engine, ALLY, FOE, bonus=0, ac=12) is True
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "resonance") == 27
    engine.state.actors[ME].reaction_available = True
    script(engine, [2, 17])
    attack(engine, ALLY, FOE, bonus=0, ac=12, index=2)  # the same round: no second Rehearse
    assert len(rewrites(engine)) == 1


def test_painless_martyr_carries_the_failure_and_gains_a_mercy_scar():
    engine = duel(MARTYR, ally_mids=[], primary="Resonance")
    give(engine, ME, mercy_scar=0)
    script(engine, [2, 19])
    force_save(engine, ALLY, "CHA", dc=DC)
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "resonance") == 25 and amount(engine, ME, "mercy_scar") == 1


def test_painless_martyr_helps_an_ally_but_not_the_martyr():
    engine = duel(MARTYR, primary="Resonance")
    script(engine, [2, 19])
    force_save(engine, ME, "CHA", dc=DC)
    assert not rewrites(engine)


def test_shared_burden_carry_the_echo_costs_resonance_or_sorrow_and_leaves_an_echo():
    engine = duel(BURDEN, ally_mids=[], primary="Resonance")
    script(engine, [2, 19])
    force_save(engine, ALLY, "INT", dc=DC)
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "resonance") == 26
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in engine.state.actors[ME].modifiers.values())
    engine2 = duel(BURDEN, ally_mids=[], primary="Qi")
    give(engine2, ME, sorrow_burden=2)
    script(engine2, [2, 19])
    force_save(engine2, ALLY, "INT", dc=DC)
    assert len(rewrites(engine2)) == 1 and amount(engine2, ME, "sorrow_burden") == 0


def test_star_soul_guidance_helps_each_creature_once_and_only_against_fear_charm_possession_or_movement():
    engine = duel(STAR_SOUL, ally_mids=[])
    script(engine, [2, 2, 18, 2, 18])
    force_save(engine, ALLY, "WIS", dc=DC)                 # the effect is not named: not eligible
    assert not rewrites(engine)
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="charmed")
    assert len(rewrites(engine)) == 1
    engine.state.actors[ME].reaction_available = True
    engine.state.actors[ME].resources["resource:core.qi"] = 30
    script(engine, [2, 18])
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="charmed")   # the same creature again this fight
    assert len(rewrites(engine)) == 1
    script(engine, [2, 18])
    force_save(engine, ME, "WIS", dc=DC, typed=True, condition="frightened")  # another creature (the star-reader itself)
    assert len(rewrites(engine)) == 2


def test_stitch_the_broken_technique_rerolls_a_failed_concentration_save_once():
    engine = duel(STITCH)
    from combat.gate2_engine import SYSTEM_CONCENTRATION

    script(engine, [2, 18, 2, 18])
    engine._roll_save(engine.state.actors[ME], "CON", DC, SYSTEM_CONCENTRATION)
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "qi") == 27
    engine.state.actors[ME].reaction_available = True
    engine._roll_save(engine.state.actors[ME], "CON", DC, SYSTEM_CONCENTRATION)   # once per short rest: a fight
    assert len(rewrites(engine)) == 1
    engine._roll_save(engine.state.actors[ME], "CON", DC, "test:not-concentration")
    assert len(rewrites(engine)) == 1


# ----------------------------------------------------------------------------------------------- a foe rerolls an attack that hit
def test_laughing_at_certain_death_makes_the_attacker_reroll_with_disadvantage():
    engine = duel(LAUGHING)
    me = engine.state.actors[ME]
    me.current_hp = 40
    give(engine, ME, focus=1)
    script(engine, [12, 4, 16])   # the hit (12 + 5 >= 14), then two dice for Disadvantage
    assert attack(engine, FOE, ME, bonus=5) is False
    (rewrite,) = rewrites(engine)
    assert rewrite.actor_id == FOE and rewrite.payload["result"]["natural_result"] == 4
    assert amount(engine, ME, "focus") == 0 and not me.reaction_available
    me.reaction_available = True
    give(engine, ME, focus=1)
    script(engine, [12, 4, 16])
    assert attack(engine, FOE, ME, bonus=5, index=2) is not None
    assert len(rewrites(engine)) == 1  # once per long rest, and the save half shares the use


def test_laughing_at_certain_death_rerolls_its_own_failed_dexterity_or_wisdom_save_with_advantage():
    engine = duel(LAUGHING)
    engine.state.actors[ME].current_hp = 40
    give(engine, ME, focus=1)
    script(engine, [2, 3, 17])
    roll = force_save(engine, ME, "WIS", dc=DC)
    assert len(rewrites(engine)) == 1 and roll.total == 19
    assert any("half its Speed" in (e.payload or {}).get("rider", "") for e in events(engine, "GM_RIDER"))


def test_laughing_at_certain_death_leaves_a_miss_alone():
    engine = duel(LAUGHING)
    engine.state.actors[ME].current_hp = 40
    give(engine, ME, focus=1)
    script(engine, [2])
    assert attack(engine, FOE, ME, bonus=1) is False
    assert not rewrites(engine) and amount(engine, ME, "focus") == 1


def test_empty_cup_rerolls_a_hit_with_disadvantage_for_two_stamina_once_a_round():
    engine = duel(EMPTY_CUP, primary="Stamina")
    script(engine, [13, 6, 18, 13, 6, 18])
    assert attack(engine, FOE, ME, bonus=5) is False
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "stamina") == 28
    # Rider lane C7 (2026-09-30): the printed "move up to 10 feet without provoking" now runs (it was a GM line here).
    assert any(e.actor_id == ME and (e.payload or {}).get("without_provoking") for e in events(engine, "MOVEMENT_COMMITTED"))
    engine.state.actors[ME].reaction_available = True
    assert attack(engine, FOE, ME, bonus=5, index=2) is not None
    assert len(rewrites(engine)) == 1
