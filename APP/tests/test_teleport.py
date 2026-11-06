"""Teleports aimed at a square (owner 2026-09-28: "empty step and ive noticed this with others, that the only options are
on tokens and when i click them nothing happens"). combat/factory_compiler.py _target_kind, combat/gate4_engine.py
_action_candidates, combat/typed_executor.py _teleport."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.stepper"


def _engine():
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.void"], "learned_talent_record_ids": ["TAL_VOID_EMPTY_STEP"]}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="TELEPORT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def test_empty_step_is_aimed_at_open_squares_within_20_feet_and_moves_its_user():
    engine = _engine()
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Empty Step")]
    assert steps and all(c.destination is not None and c.target_ids == (ME,) for c in steps)
    me = engine.state.actors[ME]
    assert all(engine._distance_actor_to_cell(me, c.destination) <= 20 for c in steps)
    assert Position(x=7, y=6) in {c.destination for c in steps} and Position(x=8, y=6) not in {c.destination for c in steps}
    pick = next(c for c in steps if c.destination == Position(x=7, y=6))
    engine.execute_intent(ActionIntent(intent_id="step", decision_id=pick.decision_id, candidate_id=pick.candidate_id,
                                       state_version=pick.state_version, actor_id=ME, target_ids=pick.target_ids, destination=pick.destination))
    assert engine.state.actors[ME].position == Position(x=7, y=6)
    moved = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME]
    assert moved and moved[-1].payload["teleport"] is True


def test_the_squares_are_marked_for_players_not_the_built_in_ai():
    """combat/gate4_context.py drops "teleport" candidates from the built-in AI's menu (it has no sense of where to go)."""
    steps = [c for c in _engine().legal_candidates() if c.display_name.startswith("Empty Step")]
    assert all((c.metadata or {}).get("teleport") for c in steps)
