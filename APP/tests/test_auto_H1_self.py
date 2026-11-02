"""Lane H1, family 1: a fighter rerolls its own failed roll (Broken Gourd Recovery, Indomitable Body, Ash-Shedding Reversal, Ancestral
Battle Dress and Scripture, Chain-Breaker's Lesson). Each is a real compiled character; the dice are scripted so the first save fails
and the reroll lands where the case needs it; the roll is forced through the engine's own save code."""

import pytest

from tests.h1_support import ME, amount, duel, events, force_save, give, rewrites, script

BROKEN_GOURD = "TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY"
INDOMITABLE = "tianxia.path.body_refining.feature.indomitable_body"
ASH_SHEDDING = "tianxia.subpath.body.phoenix_rebirth_body.feature.ash_shedding_reversal"
BATTLE_DRESS = "tianxia.talent.equipment.ancestral_battle_dress"
SCRIPTURE = "tianxia.talent.equipment.ancestral_battle_dress_scripture"
DC = 16  # the character's save modifier is +2 in every ability


@pytest.mark.parametrize("typed", [False, True])
def test_broken_gourd_rerolls_a_failed_dexterity_save_once_and_spends_focus(typed):
    engine = duel(BROKEN_GOURD)
    give(engine, ME, focus=1)
    engine.state.actors[ME].current_hp = 40
    script(engine, [3, 19])
    roll = force_save(engine, ME, "DEX", dc=DC, typed=typed)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == BROKEN_GOURD and rewrite.payload["operation"] == "reroll"
    assert rewrite.payload["original"]["natural_result"] == 3 and rewrite.payload["result"]["natural_result"] == 19
    assert amount(engine, ME, "focus") == 0
    if typed:
        assert roll.payload["success"] is True and roll.payload["natural_result"] == 19
    else:
        assert roll.total == 21
    # used up for the rest of the fight: a second failed save stays failed
    script(engine, [3, 19])
    force_save(engine, ME, "DEX", dc=DC, typed=typed)
    assert len(rewrites(engine)) == 1


def test_broken_gourd_ignores_other_abilities_a_success_and_a_missing_focus():
    engine = duel(BROKEN_GOURD)
    give(engine, ME, focus=1)
    engine.state.actors[ME].current_hp = 40
    script(engine, [3, 19, 15, 19])
    force_save(engine, ME, "STR", dc=DC)            # not a Dexterity save
    force_save(engine, ME, "DEX", dc=DC)            # 15 + 2 = 17: a success, nothing to reroll
    assert not rewrites(engine) and amount(engine, ME, "focus") == 1
    give(engine, ME, focus=0)
    script(engine, [3, 19])
    force_save(engine, ME, "DEX", dc=DC)
    assert not rewrites(engine)


def test_broken_gourd_states_the_move_it_leaves_to_the_table_only_on_a_new_success():
    engine = duel(BROKEN_GOURD)
    give(engine, ME, focus=1)
    engine.state.actors[ME].current_hp = 40
    script(engine, [3, 19])
    force_save(engine, ME, "DEX", dc=DC)
    # This automatic engine fixture now takes the native granted step.
    assert not any("move up to 10 feet" in (e.payload or {}).get("rider", "") for e in events(engine, "GM_RIDER"))
    position = engine.state.actors[ME].position
    assert 0 < max(abs(position.x - 3), abs(position.y - 6)) * 5 <= 10
    assert len(events(engine, "MOVEMENT_COMMITTED")) == 1
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "focus") == 0
    engine = duel(BROKEN_GOURD)
    give(engine, ME, focus=1)
    engine.state.actors[ME].current_hp = 40
    script(engine, [3, 4])
    force_save(engine, ME, "DEX", dc=DC)
    assert not any("move up to 10 feet" in (e.payload or {}).get("rider", "") for e in events(engine, "GM_RIDER"))
    assert not events(engine, "MOVEMENT_COMMITTED")
    assert len(rewrites(engine)) == 1  # the focus is still spent: the reroll happened, it just failed again


def test_indomitable_body_spends_three_stamina_once_per_round_on_any_save():
    engine = duel(INDOMITABLE, primary="Stamina")
    script(engine, [2, 18, 2, 18])
    before = amount(engine, ME, "stamina")
    force_save(engine, ME, "WIS", dc=DC)
    assert len(rewrites(engine)) == 1 and amount(engine, ME, "stamina") == before - 3
    force_save(engine, ME, "CON", dc=DC)            # the same round: not again
    assert len(rewrites(engine)) == 1
    engine.state.round_number += 1
    script(engine, [2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert len(rewrites(engine)) == 2


def test_indomitable_body_needs_the_stamina():
    engine = duel(INDOMITABLE, primary="Stamina")
    give(engine, ME, stamina=2)
    script(engine, [2, 18])
    force_save(engine, ME, "WIS", dc=DC)
    assert not rewrites(engine)


def test_ash_shedding_reversal_is_a_reaction_for_strength_dexterity_or_constitution_saves():
    engine = duel(ASH_SHEDDING)
    give(engine, ME, rebirth_ember=2)
    script(engine, [2, 2, 18])
    force_save(engine, ME, "WIS", dc=DC)
    assert not rewrites(engine)
    force_save(engine, ME, "CON", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == ASH_SHEDDING and amount(engine, ME, "rebirth_ember") == 0
    assert not engine.state.actors[ME].reaction_available
    assert events(engine, "REACTION_WINDOW_OPENED")[-1].source_definition_id == ASH_SHEDDING
    # The 5-foot step on the new success is no longer a GM log line: rider lane C7 made it a real move the player is asked about
    # (tests/test_riders_c7.py::test_ash_shedding_reversal_rerolls_for_two_embers_and_steps_on_a_success). This save is rolled
    # outside any action, where nobody can be asked, so the step is declined and ME stays put.
    assert not any("5 feet" in (e.payload or {}).get("rider", "") for e in events(engine, "GM_RIDER"))
    me = engine.state.actors[ME]
    assert (me.position.x, me.position.y) == (3, 6)


def test_ash_shedding_reversal_needs_the_reaction_and_two_embers():
    engine = duel(ASH_SHEDDING)
    give(engine, ME, rebirth_ember=1)
    script(engine, [2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert not rewrites(engine)
    give(engine, ME, rebirth_ember=2)
    engine.state.actors[ME].reaction_available = False
    script(engine, [2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert not rewrites(engine)


def test_ancestral_battle_dress_rerolls_once_a_fight_and_the_scripture_adds_temporary_hp():
    engine = duel([BATTLE_DRESS, SCRIPTURE])
    engine.state.actors[ME].current_hp = 30  # hurt: a once-per-fight ability is used when the fighter is
    script(engine, [2, 18, 2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert len(rewrites(engine)) == 1
    me = engine.state.actors[ME]
    assert me.temporary_hp == 4 + 2  # PB + the sheet's key modifier (CON +2)
    force_save(engine, ME, "CON", dc=DC)
    assert len(rewrites(engine)) == 1


def test_ancestral_battle_dress_alone_grants_no_temporary_hp_and_a_healthy_fighter_keeps_it_for_later():
    engine = duel(BATTLE_DRESS)
    script(engine, [2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert not rewrites(engine)                      # unhurt in round 1: the AI saves it
    engine.state.actors[ME].current_hp = 20
    script(engine, [2, 18])
    force_save(engine, ME, "CON", dc=DC)
    assert len(rewrites(engine)) == 1 and engine.state.actors[ME].temporary_hp == 0
