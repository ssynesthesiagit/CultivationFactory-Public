"""Shatter Without Waste through the engine, the Fracture Response
menu and a cold reload.

The printed rule -- once per turn, when Shatter Space or Shatter
Bloom would end one of your Lattice Spaces, you may instead set its
remaining duration to the end of your next turn, with no effect when
the space would already end by then -- is driven through the real
table: the foe ends up standing on the caster's Lattice Space with a
Fracture Mark, the Fracture Response menu offers Shatter Space, and
the answer runs the real Shatter Space resolution, the one place the
engine ends a Lattice Space, which now runs the general
lattice_space_ending seam the Insight observes.

* the table test proves the space survives Shatter Space with its
  zone clock rewritten to the end of the caster's next turn, and
  that the rewrite survives a cold reload and a full replay;
* the unit tests prove the once-per-turn allowance (a second
  Shatter Space in the same turn ends the space), the "would
  already end by then" clause, the no-duration-clock case, and that
  a fighter without the Insight shatters the space as before.
"""
import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import ice_fracture as I
from combat.ext.ice_second_pass import WASTE
from tests.test_formations import ME, _sheet, _turn
from tests.test_riders_lane9 import ROOT, THEM
from tests.test_r9i_choices import action, finish_turn, resolve
from tests.test_r9i_karma_persistence import act
from tests.test_tabletop_hunt6 import ALLY, LEFT, PROJECTS, RIGHT, on_hold
from tests.h1_support import sheet

# The unit fixtures compile their cultivator at CL 15, whose
# proficiency bonus is +4.
CL, PB = 15, 4


def _ice_insight_fight(insight=True, *, cl=CL, them_at=(5, 6), seed="R9ICE"):
    """ME: an Ice cultivator holding (or lacking) the Insight; THEM (team b)."""
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    document = {**SHEET, "equipment": [{"starting_kit": KIT}],
                 "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.ice"],
                                         "automatic_sphere_component_record_ids": ["ICE_BASE_SPENDING_A_FRACTURE_MARK"],
                                         "learned_talent_record_ids": []}}
    if insight:
        document["spheres_and_talents"]["cultivation_insight_record_ids"] = [WASTE]
    document["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    document["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"],
                                                 "primary_resource": {"name": "Qi", "maximum": 80},
                                                 "technique_save_dc": 30}
    bundles = [compile_character(document, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": [ME, THEM],
                                                 "team_by_actor": {ME: "team:a", THEM: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                        THEM: {"x": them_at[0], "y": them_at[1]}}})
    _turn(engine, ME)
    return engine


def _mark_and_lattice(engine, duration_rounds=None):
    """A one-minute Lattice Space under the foe, holding the foe's Fracture Mark."""
    caster, target = engine.state.actors[ME], engine.state.actors[THEM]
    I._lattice_at(engine, caster, target, "ICE_BASE_CRYSTALLIZE_PATH")
    if duration_rounds is not None:
        I.lattice_zones(engine, ME)[0].duration_rounds = duration_rounds
    I.give_mark(engine, caster, target, I.BASE)
    return caster, target


def test_a_lattice_space_ended_by_shatter_space_lasts_until_the_next_turn(tmp_path, monkeypatch):
    """The table: the Fracture Response menu's Shatter Space keeps the space."""
    combat, table, mid = _ice_table_fight(tmp_path, insight=True)

    def prepare(engine):
        caster, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        I._lattice_at(engine, caster, target, "ICE_BASE_CRYSTALLIZE_PATH")
        I.give_mark(engine, caster, target, I.BASE)

    on_hold(monkeypatch, prepare)
    resolve(lambda answers: act(table, mid, action(table, mid, "Hold position"), answers), {})
    monkeypatch.undo()
    # The foe's turn starts standing on the Lattice Space and marked:
    # the Fracture Response menu offers Shatter Space, whose resolution
    # asks which occupied space to shatter and which damage type. The
    # Insight claims the ending and keeps the space until the caster's
    # next turn instead of shattering it now.
    where = combat._load_session(mid).engine.state.actors[RIGHT].position
    cell = f"{where.x},{where.y}"
    seen = []
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        seen = finish_turn(table, mid, {"choice:needle.fracture_response": ["shatter"],
                                        "choice:needle.shatter_space": [cell],
                                        "choice:needle.shatter_type": ["COLD"],
                                        "choice:needle.preserve_lattice": ["keep"]})
    assert "choice:needle.fracture_response" in seen, seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert I.lattice_cells(engine, LEFT), "the Insight keeps the Lattice Space alive"
    caster = engine.state.actors[LEFT]
    zone = I.lattice_zones(engine, LEFT)[0]
    assert zone.duration_rounds is None
    assert zone.trigger_profile["end_after_owner_turn"] == caster.turns_started + 1
    assert int(caster.turns_started) >= int(engine.state.round_number)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_a_second_shatter_space_in_the_same_turn_ends_the_space():
    """The once-per-turn allowance is spent by the first ending."""
    engine = _ice_insight_fight(insight=True)
    caster, target = _mark_and_lattice(engine)
    I._shatter(engine, caster, target, CL, PB)
    assert I.lattice_cells(engine, ME)
    zone = I.lattice_zones(engine, ME)[0]
    assert zone.duration_rounds is None
    assert zone.trigger_profile["end_after_owner_turn"] == caster.turns_started + 1
    I.give_mark(engine, caster, target, I.BASE)  # a fresh mark: a second Shatter Space this turn
    I._shatter(engine, caster, target, CL, PB)
    assert not I.lattice_cells(engine, ME), "the once-per-turn allowance is spent"


def test_a_space_that_would_already_end_by_then_is_left_to_shatter():
    """A space ending at or before the end of the caster's next turn gains nothing."""
    engine = _ice_insight_fight(insight=True)
    caster, target = _mark_and_lattice(engine, duration_rounds=1)
    I._shatter(engine, caster, target, CL, PB)
    assert not I.lattice_cells(engine, ME), "the one-round space already ends by then"


def test_a_space_outlasting_the_next_turn_is_kept_until_its_end():
    """A space lasting past the end of the caster's next turn is shortened to it."""
    engine = _ice_insight_fight(insight=True)
    caster, target = _mark_and_lattice(engine, duration_rounds=3)
    I._shatter(engine, caster, target, CL, PB)
    assert I.lattice_cells(engine, ME)
    zone = I.lattice_zones(engine, ME)[0]
    assert zone.duration_rounds is None
    assert zone.trigger_profile["end_after_owner_turn"] == caster.turns_started + 1


def test_a_space_with_no_duration_clock_is_kept_until_the_next_turn():
    """A space that lasts until dismissed would outlast the boundary, so it is kept."""
    engine = _ice_insight_fight(insight=True)
    caster, target = _mark_and_lattice(engine, duration_rounds=None)
    I._shatter(engine, caster, target, CL, PB)
    assert I.lattice_cells(engine, ME)
    zone = I.lattice_zones(engine, ME)[0]
    assert zone.duration_rounds is None
    assert zone.trigger_profile["end_after_owner_turn"] == caster.turns_started + 1


def test_a_fighter_without_the_insight_shatters_the_space_as_before():
    """The seam is default-inert: without the Insight the space ends as before."""
    engine = _ice_insight_fight(insight=False)
    caster, target = _mark_and_lattice(engine)
    I._shatter(engine, caster, target, CL, PB)
    assert not I.lattice_cells(engine, ME)


def _ice_table_fight(tmp_path, *, insight=True, cl=15):
    """A three-fighter Hunt6-yard match whose left fighter is an Ice
    cultivator holding (or lacking) the Insight."""
    for name in ("left", "ally", "right"):
        document = sheet(["ICE_BASE_SPENDING_A_FRACTURE_MARK"] if name == "left" else [], cl=cl)
        if insight and name == "left":
            document["spheres_and_talents"]["cultivation_insight_record_ids"] = [WASTE]
        document["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Hunt6 yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]],
                                    opponent_actor_ids=[RIGHT],
                                    control_modes={a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
                                    arena_id="battlefield:map.hunt6-yard", match_seed="HUNT6-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid
