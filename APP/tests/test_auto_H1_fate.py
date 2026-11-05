"""Lane H1, family 3: Fate and Karma abilities that put a chosen die where a rolled d20 was (Rewrite the Disaster, Omen Glimpse, Sever
One Thread, Stored Glimpse, Reversal of Due Fortune's attack and check cases)."""

from combat.ext import karma_imprints
from tests.h1_support import ALLY, FOE, ME, amount, attack, duel, events, force_save, give, rewrites, script

ROD = "TAL_FATE_REWRITE_THE_DISASTER"
OMEN = "tianxia.tradition.spirit.fate_reader.feature.omen_glimpse"
SEVER = "tianxia.tradition.spirit.fate_reader.feature.sever_one_thread"
GLIMPSE = "tianxia.subpath.qi.divination_cultivator.feature.stored_glimpse"
REVERSAL = "tianxia.talent.karma.reversal_of_due_fortune"
DC = 16  # +2 to every save


def test_rewrite_the_disaster_turns_an_allys_failed_save_into_a_natural_twenty():
    engine = duel(ROD, ally_mids=[], cl=15)
    give(engine, ME, heaven_s_notice=0)
    engine.state.actors[ALLY].current_hp = 30
    script(engine, [5])
    roll = force_save(engine, ALLY, "DEX", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["operation"] == "replace" and rewrite.payload["result"]["natural_result"] == 20 and roll.total == 22
    assert amount(engine, ME, "qi") == 18 and not engine.state.actors[ME].reaction_available and amount(engine, ME, "heaven_s_notice") == 2
    engine.state.actors[ME].reaction_available = True
    script(engine, [5])
    force_save(engine, ALLY, "DEX", dc=DC)   # once per long rest (a fight)
    assert len(rewrites(engine)) == 1


def test_rewrite_the_disaster_turns_a_foes_success_into_a_natural_one_unless_it_resists():
    engine = duel(ROD, cl=15)
    script(engine, [18, 3])          # the foe passes, then fails its Charisma save (DC 8 + 4 + 2 = 14)
    roll = force_save(engine, FOE, "DEX", dc=10)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 1 and roll.total < 10 and amount(engine, ME, "qi") == 18
    engine = duel(ROD, cl=15)
    give(engine, ME, heaven_s_notice=0)
    script(engine, [18, 20])         # the Charisma save succeeds: the roll stands, the cost is paid
    roll = force_save(engine, FOE, "DEX", dc=10)
    assert not rewrites(engine) and roll.natural_result == 18 and amount(engine, ME, "qi") == 18 and amount(engine, ME, "heaven_s_notice") == 2


def test_rewrite_the_disaster_is_not_offered_when_it_would_change_nothing():
    engine = duel(ROD, ally_mids=[], cl=15)
    script(engine, [1, 19])
    force_save(engine, ALLY, "DEX", dc=DC + 40)     # not even a 20 saves
    force_save(engine, ALLY, "DEX", dc=DC)          # already a success
    assert not rewrites(engine) and amount(engine, ME, "qi") == 30


def test_rewrite_the_disaster_makes_a_foes_hit_a_miss_and_an_allys_miss_a_hit():
    engine = duel(ROD, ally_mids=[], cl=15)
    script(engine, [14, 3])          # the hit, then the foe's failed Charisma save
    assert attack(engine, FOE, ALLY, bonus=5, ac=15) is False    # 19 hits AC 15; a natural 1 misses
    assert len(rewrites(engine)) == 1
    engine.state.actors[ME].reaction_available = True
    engine.state.actors[ME].resources["resource:core.qi"] = 30
    engine.state.actors[ME].turn_flags.pop("_round_h1_fight:TAL_FATE_REWRITE_THE_DISASTER", None)
    script(engine, [2])
    assert attack(engine, ALLY, FOE, bonus=0, ac=15, index=2) is True   # a natural 20 hits
    assert len(rewrites(engine)) == 2


def test_omen_glimpse_prepares_a_die_then_replaces_one_d20_with_it():
    engine = duel(OMEN, ally_mids=[], primary="Resonance", cl=6)
    script(engine, [4, 17])          # the ally's failed save, then the Omen die prepared for the scene
    roll = force_save(engine, ALLY, "WIS", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 17 and roll.total == 19
    assert amount(engine, ME, "resonance") == 28          # 1 to prepare, 1 to invoke
    assert engine.state.actors[ME].turn_flags["_round_h1_omen"] == 0
    engine.state.actors[ME].reaction_available = True
    script(engine, [3])
    force_save(engine, ALLY, "WIS", dc=DC)
    assert len(rewrites(engine)) == 1                     # the die is expended


def test_omen_glimpse_is_kept_when_a_foe_resists_and_is_not_used_when_it_would_not_help():
    engine = duel(OMEN, primary="Resonance", cl=6)
    script(engine, [18, 3, 20])      # a foe's success; the Omen die is a 3; the foe's Charisma save is a 20 (it resists)
    force_save(engine, FOE, "DEX", dc=10)
    assert not rewrites(engine) and engine.state.actors[ME].turn_flags["_round_h1_omen"] == 3   # a 3 would fail DC 10 - keep it: nothing to resist
    engine = duel(OMEN, primary="Resonance", cl=6)
    script(engine, [18, 1, 20])
    force_save(engine, FOE, "DEX", dc=10)
    assert len(rewrites(engine)) == 0 or engine.state.actors[ME].turn_flags["_round_h1_omen"] in (0, 1)


def test_sever_one_thread_rerolls_and_the_holder_takes_the_better_result_for_an_ally():
    engine = duel(SEVER, ally_mids=[], primary="Resonance", cl=18)
    engine.state.actors[ALLY].current_hp = 30
    script(engine, [4, 15])
    roll = force_save(engine, ALLY, "CON", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 15 and roll.total == 17 and amount(engine, ME, "resonance") == 20
    assert any("Fate-Tangled" in (e.payload or {}).get("rider", "") for e in events(engine, "GM_RIDER"))


def test_sever_one_thread_a_foe_that_fails_its_charisma_save_gets_the_worse_of_two_dice():
    engine = duel(SEVER, primary="Resonance", cl=18)
    engine.state.actors[ME].current_hp = 30
    script(engine, [16, 2, 3])       # the foe's success, its Charisma save 2 (fails), then the reroll 3
    roll = force_save(engine, FOE, "DEX", dc=10)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 3 and roll.natural_result == 3


def test_stored_glimpse_is_rolled_for_the_scene_and_replaces_an_allys_roll_once_per_round():
    engine = duel(GLIMPSE, ally_mids=[], cl=3)
    script(engine, [3, 16])          # the ally's failed save, then the Glimpse
    roll = force_save(engine, ALLY, "DEX", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 16 and roll.total == 18
    assert amount(engine, ME, "qi") == 29 and engine.state.actors[ME].turn_flags["_round_h1_glimpse"] == []
    assert not engine.state.actors[ME].reaction_available is False  # it is no Reaction


def test_stored_glimpse_never_counts_as_a_natural_one_or_twenty():
    engine = duel(GLIMPSE, ally_mids=[], cl=3)
    script(engine, [3, 20])
    roll = force_save(engine, ALLY, "DEX", dc=DC)
    assert roll.natural_result == 19


def test_stored_glimpse_is_saved_for_a_foe_when_it_is_low():
    engine = duel(GLIMPSE, cl=3)
    script(engine, [15, 4])          # a foe's success; the Glimpse is a 4: replace it
    roll = force_save(engine, FOE, "DEX", dc=10)
    assert len(rewrites(engine)) == 1 and roll.natural_result == 4


def test_reversal_of_due_fortune_turns_an_allys_natural_one_attack_into_a_twenty_with_a_grace_imprint():
    engine = duel(REVERSAL, ally_mids=[])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert karma_imprints.place(engine, me, ally, "grace", REVERSAL, "test")
    script(engine, [1])
    assert attack(engine, ALLY, FOE, bonus=0, ac=15) is True
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 20 and amount(engine, ME, "qi") == 26
    assert not karma_imprints.held(ally, ME, "grace") and not me.reaction_available


def test_reversal_of_due_fortune_needs_the_grace_imprint():
    engine = duel(REVERSAL, ally_mids=[])
    script(engine, [1])
    attack(engine, ALLY, FOE, bonus=0, ac=15)
    assert not rewrites(engine) and amount(engine, ME, "qi") == 30
