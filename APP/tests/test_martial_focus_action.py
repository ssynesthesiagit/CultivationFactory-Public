"""Owner ruling: regain Martial Focus as an Action (system:martial_focus.regain)."""
from pathlib import Path

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from combat.ext.martial_focus_action import FOCUS, HELD, REGAIN
from tests.h1_support import sheet
from tests.test_lock2_prepared import request

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.martial_focus_action"


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _fighter(focus=0):
    bundle = compile_character(sheet([], primary="Stamina", cl=10), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MF-REGAIN", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    actor = engine.state.actors[ME]
    assert actor.resource_maximums[FOCUS] == 1, "a compiled character owns a Martial Focus pool of 1"
    actor.resources[FOCUS] = focus
    _turn(engine, ME)
    return engine, actor


def _offered(engine):
    return [c for c in engine.legal_candidates() if c.source_definition_id == REGAIN]


def _refusals(engine, actor):
    action = engine.action_catalog[REGAIN]
    return ext.run_strict("candidate_unavailability", engine, actor, None, action)


def test_regain_is_an_action_that_restores_exactly_one_focus_and_logs_it():
    engine, actor = _fighter(focus=0)
    action = engine.action_catalog[REGAIN]
    assert action.economy == "ACTION" and action.target_kind == "SELF" and action.resolution_kind == "TYPED"
    assert not action.parameters.get("player_only")
    candidate, = _offered(engine)
    engine.execute_intent(request(engine, candidate))
    assert actor.resources[FOCUS] == 1
    assert not actor.action_available
    logs = [e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"]
    assert [text for text in logs if text.endswith("regains 1 Martial Focus with an Action.")]
    assert not _offered(engine), "the spent Action and full Focus both block a second regain"


def test_refused_with_plain_reason_when_focus_is_already_held():
    engine, actor = _fighter(focus=1)
    assert not _offered(engine)
    assert HELD in _refusals(engine, actor)


def test_not_offered_to_an_actor_without_a_focus_pool():
    engine, actor = _fighter(focus=0)
    del actor.resource_maximums[FOCUS]
    del actor.resources[FOCUS]
    assert not _offered(engine)
    assert not any(REGAIN in reply for reply in ext.run_strict("additional_actions", engine, actor))
