"""Shared Shi combat fixtures for Shi and parser-duplicate tests."""
from pathlib import Path
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.shi"
DAO = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}


def _bundle(talents, *, sphere="tianxia.sphere.pressure_points", foundation=None, equipment=(DAO,)):
    sheet = {**SHEET, "equipment": list(equipment), "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    if foundation:
        sheet = {**sheet, "foundation": foundation}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="SHI", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _hit_with(engine, name_prefix, *, attempts=10):
    """Attack with the named action until one lands (the dice decide, tests/test_iron_fist.py's pattern);
    returns True once it does."""
    me = engine.state.actors[ME]
    for attempt in range(attempts):
        strike = next((c for c in engine.legal_candidates() if c.display_name.startswith(name_prefix)), None)
        assert strike is not None, f"{name_prefix!r} should be a legal candidate"
        before = len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"])
        engine.execute_intent(ActionIntent(intent_id=f"hit{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]) > before:
            return True
        engine.state.current_actor_id = ME
        me.action_available = True
    return False


def _hit_with_dao(engine, *, attempts=10):
    return _hit_with(engine, "Dao ", attempts=attempts)


