"""Buffs cast before a fight (owner 2026-09-29: "allow at the beginning of the fights 2 persistent buffs for each entry";
rulings: 10 minutes or longer, Melds included, paid from the starting CP, at most one Concentration, the AI picks its best
two). combat/prefight.py (cast as the match is made, Gate2Engine.__init__), CombatService._with_prefight."""

import pytest

from combat import prefight, senses
from combat.ext import query
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from tests.test_auto_docket import DARK, ME, QI, ROOT, _my_turn, _sheet

NIGHT_SIGHT = "tianxia.talent.stars.night_sight_meridian"  # 1 Qi, 1 hour, no Concentration
KARMIC_SIGHT = "tianxia.talent.karma.karmic_sight"  # 1 Qi, Concentration, up to 10 minutes
SHEET = _sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT", NIGHT_SIGHT, KARMIC_SIGHT],
               spheres=["tianxia.sphere.dark", "tianxia.sphere.stars", "tianxia.sphere.karma"])


def _bundle(picks=None):
    bundle = compile_character(SHEET, actor_id=ME)
    return CombatService._with_prefight(object.__new__(CombatService), bundle, None if picks is None else {ME: picks})


def _engine(bundle):
    engine = Gate4ControllerEngine(ROOT, match_seed="PREFIGHT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    _my_turn(engine)  # the buffs were cast as the match was made
    return engine


def _named(bundle, name):
    return next(option["action_id"] for option in bundle["prefight"]["options"] if option["name"] == name)


def test_the_options_are_long_buffs_and_the_melds_by_their_ritual():
    options = {option["name"]: option for option in compile_character(SHEET, actor_id=ME)["prefight"]["options"]}
    assert {"Meld: Clearsight", "Meld: Clearsight (Persistent)", "Meld: Darkvision", "Night-Sight Meridian", "Karmic Sight"} <= set(options)
    assert options["Meld: Clearsight"]["costs"] == [] and options["Meld: Clearsight"]["concentration"] is True  # Action; no CP cost
    assert [amount for _resource, amount in options["Meld: Clearsight (Persistent)"]["costs"]] == [2]  # Persistent Meld's 2 CP
    assert options["Karmic Sight"]["concentration"] is True and options["Night-Sight Meridian"]["concentration"] is False
    assert "Darkness" not in options  # an area to place is not a buff cast beforehand


def test_unavailable_selection_error_does_not_echo_an_action_id():
    bundle = compile_character(SHEET, actor_id=ME)
    with pytest.raises(ValueError, match="^That choice is not available for this fighter before the fight\\.$"):
        prefight.validate(["action:typed.private.internal_id"], bundle["prefight"]["options"], prefight.starting_pools(bundle))


def test_the_ai_picks_a_persistent_meld_and_a_buff_without_concentration():
    bundle = _bundle()
    assert [next(o["name"] for o in bundle["prefight"]["options"] if o["action_id"] == pick) for pick in bundle["prefight"]["picks"]] == \
        ["Meld: Clearsight (Persistent)", "Night-Sight Meridian"]
    assert bundle["senses"]["meld_start"] is None  # the chosen Meld, not a free one besides


def test_plug_ins_without_setup_choices_leave_pre_fight_bundle_unchanged():
    compiled = compile_character(SHEET, actor_id=ME)
    assert "setup_choices" not in compiled["prefight"]
    assert query("prefight_setup_choices", compiled) == []
    prepared = _bundle()
    assert "setup_choices" not in prepared["prefight"]


def test_the_picks_are_paid_and_take_effect_as_the_fight_is_made():
    bundle = _bundle()
    start = next(row["initial"] for row in bundle["actor_template"]["resources"] if row["resource_id"] == QI)
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    assert senses.meld_of(engine, me) == "TAL_DARK_CLEARSIGHT" and me.concentration is None
    assert me.resources[QI] == start - 3  # Persistent Meld 2 + Night-Sight Meridian 1
    assert [e for e in engine.events if e.source_definition_id == prefight.SOURCE and e.event_type == "PASSIVE_TRIGGERED"]
    before = len(engine.events)
    engine.state.current_actor_id = AN
    engine._system_start_turn()  # a later turn casts nothing again
    assert not [e for e in engine.events[before:] if e.source_definition_id == prefight.SOURCE]


def test_a_ritual_meld_holds_concentration_and_a_player_may_pick_none():
    bundle = _bundle()
    engine = _engine(_bundle([_named(bundle, "Meld: Darkvision"), _named(bundle, "Night-Sight Meridian")]))
    me = engine.state.actors[ME]
    assert senses.meld_of(engine, me) == "TAL_DARK_DARKVISION" and me.concentration is not None
    engine = _engine(_bundle([]))
    assert senses.meld_of(engine, engine.state.actors[ME]) is None  # no Meld picked: none, not a free one


def test_two_different_melds_may_be_cast_before_a_fight():  # owner 2026-09-29 struck the one-Meld line
    bundle = compile_character(SHEET, actor_id=ME)
    picks = [_named(bundle, "Meld: Clearsight (Persistent)"), _named(bundle, "Meld: Darkvision (Persistent)")]
    assert prefight.validate(picks, bundle["prefight"]["options"], prefight.starting_pools(bundle)) == picks
    engine = _engine(_bundle(picks))
    assert senses.melds_of(engine, engine.state.actors[ME]) == ["TAL_DARK_CLEARSIGHT", "TAL_DARK_DARKVISION"]


@pytest.mark.parametrize("names, why", [
    (["Meld: Clearsight (Persistent)", "Night-Sight Meridian", "Karmic Sight"], "At most 2"),
    (["Meld: Clearsight", "Karmic Sight"], "Concentration"),
    (["Meld: Clearsight", "Meld: Clearsight (Persistent)"], "each Meld only once"),
])
def test_the_rules_for_a_players_picks(names, why):
    bundle = compile_character(SHEET, actor_id=ME)
    with pytest.raises(ValueError, match=why):
        prefight.validate([_named(bundle, name) for name in names], bundle["prefight"]["options"], prefight.starting_pools(bundle))
    with pytest.raises(ValueError, match="Not enough CP"):
        prefight.validate([_named(bundle, "Night-Sight Meridian")], bundle["prefight"]["options"], {QI: 0})


def test_each_option_carries_its_printed_rules_for_the_hover():  # owner 2026-09-30: hover a pre-fight cast to read it
    options = {option["name"]: option for option in compile_character(SHEET, actor_id=ME)["prefight"]["options"]}
    clearsight = options["Meld: Clearsight"]
    darkvision = options["Meld: Darkvision"]
    assert "immune to negative effects created by your Darkness talents" in clearsight["description"]
    assert "this fighter" in clearsight["description"]
    assert "Darkvision out to 60 feet" in darkvision["description"]
    assert "this fighter" in darkvision["description"]
    regular = options["Night-Sight Meridian"]
    assert "Dim Light does not impose Disadvantage" in regular["description"]
    assert regular["costs"] == [[QI, 1]]
    assert regular["duration"] == "1 hour"
    options = list(options.values())
    assert options and all(isinstance(option.get("description"), str) for option in options)
    assert all(option["description"].strip() for option in options), [o["name"] for o in options if not o["description"].strip()]
