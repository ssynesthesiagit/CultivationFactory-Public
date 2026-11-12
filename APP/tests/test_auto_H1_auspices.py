"""Lane H1, family 4: Harmonizing Cup Auspice and Empty Road Auspice. The Auspices are cast
from the menu as any action is; their Release is the bearer's Reaction."""

from combat.ext.d20_rewrite_auspices import CONDITION
from tests.h1_support import ALLY, FOE, ME, amount, attack, duel, force_save, held, rewrites, script, use

CUP = "TAL_FATE_HARMONIZING_CUP_AUSPICE"
ROAD = "TAL_FATE_EMPTY_ROAD_AUSPICE"
DC = 16


def _cast(mid, name, **kw):
    engine = duel(mid, **kw)
    use(engine, name, ME)
    engine.state.actors[ME].reaction_available = True
    return engine


def _auspices(engine, actor_id=ME):
    return held(engine.state.actors[actor_id], CONDITION)


def test_harmonizing_cup_is_cast_on_a_willing_creature_for_two_cp_and_lasts_as_its_concentration():
    engine = duel(CUP, ally_mids=[])
    use(engine, "Harmonizing Cup Auspice", ALLY)
    (auspice,) = _auspices(engine, ALLY)
    assert auspice.data["rule"]["d20_auspice"]["auspice"] == "harmonizing_cup" and amount(engine, ME, "qi") == 28
    assert engine.state.actors[ME].concentration is not None


def test_harmonizing_cup_rerolls_the_bearers_natural_one_once_a_round_for_free():
    engine = _cast(CUP, "Harmonizing Cup Auspice")
    script(engine, [1, 15, 1, 1, 15])
    roll = force_save(engine, ME, "DEX", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["original"]["natural_result"] == 1 and roll.total == 17 and amount(engine, ME, "qi") == 28
    assert engine.state.actors[ME].reaction_available
    engine.state.actors[ME].reaction_available = False   # (a Release is another matter: it is the bearer's Reaction)
    force_save(engine, ME, "DEX", dc=DC)            # once per round: a second natural 1 stays
    assert len(rewrites(engine)) == 1
    assert _auspices(engine)
    engine.state.round_number += 1
    force_save(engine, ME, "DEX", dc=DC)            # the next round it works again
    assert len(rewrites(engine)) == 2


def test_harmonizing_cup_rerolls_an_attack_and_a_check_natural_one_too():
    engine = _cast(CUP, "Harmonizing Cup Auspice")
    script(engine, [1, 18])
    assert attack(engine, ME, FOE, bonus=0, ac=12) is True
    assert len(rewrites(engine)) == 1


def test_harmonizing_cup_release_ends_the_auspice_and_makes_an_allys_failed_roll_reroll():
    engine = _cast(CUP, "Harmonizing Cup Auspice", ally_mids=[])
    script(engine, [4, 17])
    roll = force_save(engine, ALLY, "WIS", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.actor_id == ALLY and roll.total == 19
    assert not engine.state.actors[ME].reaction_available and not _auspices(engine) and engine.state.actors[ME].concentration is None


def test_harmonizing_cup_release_makes_a_foes_success_roll_again_but_not_a_roll_that_is_good_for_the_bearer():
    engine = _cast(CUP, "Harmonizing Cup Auspice")
    script(engine, [3])
    force_save(engine, FOE, "DEX", dc=DC)            # the foe fails: nothing to spoil
    assert not rewrites(engine) and _auspices(engine)
    script(engine, [19, 2])
    force_save(engine, FOE, "DEX", dc=DC)            # the foe passes: the bearer releases, the foe rolls again
    assert len(rewrites(engine)) == 1 and not _auspices(engine)


def test_harmonizing_cup_release_reaches_only_thirty_feet():
    engine = _cast(CUP, "Harmonizing Cup Auspice")
    engine.state.actors[FOE].position = engine.state.actors[FOE].position.model_copy(update={"x": 12})   # 45 feet away
    script(engine, [19, 2])
    force_save(engine, FOE, "DEX", dc=DC)
    assert not rewrites(engine)


def test_empty_road_gives_plus_five_and_disadvantage_to_typed_saves_and_release_rerolls_without_them():
    engine = _cast(ROAD, "Empty Road Auspice")
    me = engine.state.actors[ME]
    script(engine, [3, 4, 12])       # Disadvantage: 3 and 4 -> 3; 3 + 2 fails DC 16 - 5 = 11; the Release die is a single 12
    roll = force_save(engine, ME, "WIS", dc=DC, typed=True, condition="frightened")
    (rewrite,) = rewrites(engine)
    assert roll.payload["dc"] == DC - 5 and roll.payload["mode"] == "DISADVANTAGE"
    assert rewrite.payload["result"]["natural_result"] == 12 and not _auspices(engine) and not me.reaction_available
    # 12 + 2 = 14 beats the lowered DC 11 but not the real DC 16: without the Auspice's +5 the save still fails
    assert any("frightened" in c.condition_id for c in me.conditions.values())


def test_empty_road_release_succeeds_when_the_plain_roll_beats_the_real_dc():
    engine = _cast(ROAD, "Empty Road Auspice")
    me = engine.state.actors[ME]
    script(engine, [3, 4, 17])
    force_save(engine, ME, "WIS", dc=DC, typed=True, condition="frightened")
    assert len(rewrites(engine)) == 1 and not any("frightened" in c.condition_id for c in me.conditions.values())


def test_empty_road_lowers_the_dc_by_five_before_any_release():
    engine = _cast(ROAD, "Empty Road Auspice")
    engine.state.actors[ME].reaction_available = False
    script(engine, [9, 10])
    roll = force_save(engine, ME, "WIS", dc=DC, typed=True)
    assert roll.payload["dc"] == DC - 5 and roll.payload["mode"] == "DISADVANTAGE"
    assert roll.payload["natural_result"] == 9 and roll.payload["success"] is True   # the lower die, 9 + 2 = 11 against the lowered DC 11
