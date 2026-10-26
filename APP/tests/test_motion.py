"""Movement passives (owner 2026-09-28: "still a bunch of stuff thats getting skipped"). combat/motion.py, the "motion"
blocks in combat/rules/feature_blocks.json."""

from pathlib import Path

from combat import motion
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.runner"


def _engine(talents: list[str], sphere: str = "tianxia.sphere.athletics", me_at=(3, 6), foe_at=(14, 6)):
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    engine = Gate4ControllerEngine(ROOT, match_seed="MOTION", typed_bundles=(compile_character(sheet, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, candidate):
    engine.execute_intent(ActionIntent(intent_id=candidate.candidate_id, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_the_passives_compile_as_automated_rows():
    bundle = compile_character({**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.athletics"], "learned_talent_record_ids": [
        "TAL_ATHLETICS_SWIFT_MOVEMENT", "TAL_ATHLETICS_MOBILITY", "TAL_ATHLETICS_AFTERIMAGE", "ATHLETICS_BASE_COORDINATED_MOVEMENT"]}}, actor_id=ME)
    kinds = {row["kind"] for row in bundle["typed_passives"] if row.get("block") == "motion"}
    assert kinds == {"speed_bonus", "oa_disadvantage", "afterimage", "regain_focus"}
    assert not {"Swift Movement", "Mobility", "Afterimage", "Coordinated Movement"} & set(bundle["diagnostics"]["skipped"]["passive"])


def test_swift_movement_adds_10_feet_while_martial_focus_is_held():
    engine = _engine(["TAL_ATHLETICS_SWIFT_MOVEMENT"])
    me = engine.state.actors[ME]
    base = me.speed_ft
    assert engine._effective_speed(me) == base + 10
    me.resources[motion.FOCUS] = 0
    assert engine._effective_speed(me) == base


def test_coordinated_movement_regains_focus_on_a_dash_action():
    engine = _engine(["ATHLETICS_BASE_COORDINATED_MOVEMENT"])
    me = engine.state.actors[ME]
    me.resources[motion.FOCUS] = 0
    dash = next(c for c in engine.legal_candidates() if c.source_definition_id == "system:combat.dash")
    _do(engine, dash)
    assert me.resources[motion.FOCUS] == 1


def test_afterimage_appears_after_moving_more_than_20_feet():
    engine = _engine(["TAL_ATHLETICS_AFTERIMAGE"])
    me = engine.state.actors[ME]
    far = next(c for c in engine.legal_candidates() if c.destination is not None and c.movement_cost_ft >= 25
               and c.source_definition_id.startswith("system:combat.move"))
    _do(engine, far)
    assert motion.has_afterimage(me)


def test_mobility_gives_opportunity_attacks_against_it_disadvantage():
    engine = _engine(["TAL_ATHLETICS_MOBILITY"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._typed_oa_attacker = foe.entity_id
    assert motion.attack_mode(engine, foe, me, melee=True, source="test") == "DISADVANTAGE"
    engine._typed_oa_attacker = None
    assert motion.attack_mode(engine, foe, me, melee=True, source="test") is None


def test_unimpeded_positioning_ignores_the_maps_difficult_squares():
    engine = _engine(["TAL_ATHLETICS_UNIMPEDED_POSITIONING"])
    me = engine.state.actors[ME]
    engine.grid.base_movement_cost[(4, 6)] = 2
    with motion.terrain_for(engine, me):
        assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 1
    assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 2
    me.resources[motion.FOCUS] = 0
    with motion.terrain_for(engine, me):
        assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 2


def test_an_unimpeded_move_stays_unimpeded_when_the_walls_resync_mid_move():
    """Fight audit 2026-09-29: a mid-move zones.sync_walls put the map's costs back and the move crashed."""
    from combat import zones

    engine = _engine(["TAL_ATHLETICS_UNIMPEDED_POSITIONING"])
    me = engine.state.actors[ME]
    engine.__dict__.pop("_wall_base", None)
    engine.grid.base_movement_cost[(4, 6)] = 4
    with motion.terrain_for(engine, me):
        with motion.terrain_for(engine, me):  # a listing made during the move (fight audit: nesting crashed)
            zones.sync_walls(engine)
        assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 1
    assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 4
    zones.sync_walls(engine)  # the map's own cost was kept as the base, not the stripped one
    assert engine.grid.movement_step_multiplier(Position(x=3, y=6), Position(x=4, y=6)) == 4
