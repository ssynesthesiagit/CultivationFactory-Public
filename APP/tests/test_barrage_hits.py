"""Owner Barrage and Scorching Ray sequence rules, exercised with compiled characters."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent

_spec = importlib.util.spec_from_file_location("sweep_athletics_helpers", Path(__file__).with_name("test_review_sw-athletics.py"))
helpers = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(helpers)

BOW = "Barrage: Gong Jian (Bow and Arrow)"
FOLLOW = "Barrage follow-up: Gong Jian (Bow and Arrow)"


def _fight(*talents, dc=50, hp=400, foe_at=(4, 6)):
    bundle = helpers._bundle(helpers.BARRAGE, list(talents), helpers.BOW_KIT, dc=dc)
    return helpers._engine(bundle, foe_hp=hp, foe_at=foe_at)


def _use(engine, name):
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name)
    return helpers._use(engine, name)


def _use_target(engine, name, target):
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name)
    candidate = next(row for row in engine.legal_candidates() if row.display_name == name and row.target_ids == (target,))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"test:{name}:{target}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=helpers.ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def test_blowback_requires_second_hit_of_same_barrage_and_pushes_on_failed_save():
    engine = _fight("TAL_BARRAGE_BLOWBACK_BARRAGE")
    _use(engine, BOW)
    assert helpers._foe(engine).position.x == 4
    _use(engine, FOLLOW)
    assert helpers._foe(engine).position.x == 5
    assert any("Blowback Barrage" in (event.payload or {}).get("rider", "") for event in engine.events
               if event.event_type == "GM_RIDER")


def test_separate_primary_barrage_resets_its_hit_count():
    engine = _fight("TAL_BARRAGE_BLOWBACK_BARRAGE")
    _use(engine, BOW)
    helpers._ready(engine)  # another Attack action in the same turn, before using the earlier follow-up
    _use(engine, BOW)
    assert helpers._foe(engine).position.x == 4
    _use(engine, FOLLOW)
    assert helpers._foe(engine).position.x == 5


def test_interleaved_weapons_keep_their_own_barrage_counts():
    engine = _fight("TAL_BARRAGE_BLOWBACK_BARRAGE")
    _use(engine, BOW)
    helpers._ready(engine)
    _use(engine, "Barrage: Fei Biao (Flying Dart) thrown")
    assert helpers._foe(engine).position.x == 4
    _use(engine, FOLLOW)
    assert helpers._foe(engine).position.x == 5


def test_blowback_collision_makes_the_target_prone_instead_of_moving_it():
    other_id = "actor:factory.blocker"
    main = helpers._bundle(helpers.BARRAGE, ["TAL_BARRAGE_BLOWBACK_BARRAGE"], helpers.BOW_KIT, dc=50)
    blocker = helpers._bundle("", [], helpers.BOW_KIT, actor_id=other_id)
    engine = Gate4ControllerEngine(helpers.ROOT, match_seed="BARRAGE-COLLISION", typed_bundles=(main, blocker),
                                   roster_setup={"primary_actor_ids": [helpers.ME, AN, other_id],
                                                 "team_by_actor": {helpers.ME: "team:a", AN: "team:b", other_id: "team:b"},
                                                 "starting_positions": {helpers.ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6},
                                                                        other_id: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(helpers.ME)
    engine.state.current_actor_id = helpers.ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    engine.state.actors[AN].maximum_hp = 400
    engine.state.actors[AN].current_hp = 400
    _use_target(engine, BOW, AN)
    _use_target(engine, FOLLOW, AN)
    assert engine.state.actors[AN].position.x == 4
    assert "typed.prone" in helpers._conditions(engine.state.actors[AN])


@pytest.mark.parametrize("dc,expected_speed", [(50, 0), (-40, 20)])
def test_pinning_volley_only_after_second_same_target_hit(dc, expected_speed):
    engine = _fight("TAL_BARRAGE_PINNING_VOLLEY", dc=dc)
    if dc < 0:
        helpers._foe(engine).saving_throws["DEX"] = 1000
    _use(engine, BOW + " + Pinning Volley")
    assert engine._effective_speed(helpers._foe(engine)) == 30
    _use(engine, FOLLOW)
    assert engine._effective_speed(helpers._foe(engine)) == expected_speed


def test_blitz_focus_recovers_only_at_second_hit():
    engine = _fight("TAL_BARRAGE_BLITZ_FOCUS")
    helpers._me(engine).resources["resource:core.martial_focus"] = 0
    _use(engine, BOW)
    assert helpers._resource(helpers._me(engine), "core.martial_focus") == 0
    _use(engine, FOLLOW)
    assert helpers._resource(helpers._me(engine), "core.martial_focus") == 1


def test_hammering_affects_follow_up_damage_only():
    engine = _fight("TAL_BARRAGE_HAMMERING_SHOTS")
    first = _use(engine, BOW + " + Hammering Shots")
    second = _use(engine, FOLLOW)
    assert helpers._damage_expressions(first) == ["1d8+3"]
    assert helpers._damage_expressions(second) == ["1d8+3"]
    plain = _fight("TAL_BARRAGE_HAMMERING_SHOTS")
    _use(plain, BOW)
    assert helpers._damage_expressions(_use(plain, FOLLOW)) == ["1d8+0"]


def test_distracting_shot_is_a_primary_choice_that_forgoes_follow_up():
    engine = _fight("TAL_BARRAGE_DISTRACTING_SHOT", foe_at=(6, 6))
    events = _use(engine, BOW + " + Distracting Shot")
    attacks = [event for event in events if event.event_type == "ATTACK_ROLLED"]
    assert attacks and (attacks[0].payload or {}).get("mode") == "ADVANTAGE"
    assert FOLLOW not in helpers._legal(engine)


def test_court_recovers_focus_after_two_hits_while_active():
    engine = _fight("TAL_BARRAGE_COURT_OF_FALLING_STARS")
    _use(engine, "Court of Falling Stars")
    assert helpers._resource(helpers._me(engine), "core.martial_focus") == 0
    helpers._ready(engine)  # the next turn supplies a Bonus Action for the follow-up
    _use_target(engine, BOW, AN)
    assert helpers._resource(helpers._me(engine), "core.martial_focus") == 0
    _use(engine, FOLLOW)
    assert helpers._resource(helpers._me(engine), "core.martial_focus") == 1


def test_court_ends_when_the_caster_becomes_incapacitated():
    engine = _fight("TAL_BARRAGE_COURT_OF_FALLING_STARS")
    _use(engine, "Court of Falling Stars")
    assert "typed.court_of_falling_stars" in helpers._conditions(helpers._me(engine))
    engine._apply_condition(helpers._me(engine), "condition:typed.incapacitated", "test:incapacitated", AN,
                            expires_on="END_OF_HOLDER_NEXT_TURN")
    assert "typed.court_of_falling_stars" not in helpers._conditions(helpers._me(engine))


def test_court_ally_choice_gives_one_attack_advantage_after_two_hits():
    ally_id = "actor:factory.ally"
    main = helpers._bundle(helpers.BARRAGE, ["TAL_BARRAGE_COURT_OF_FALLING_STARS"], helpers.BOW_KIT)
    ally_bundle = helpers._bundle("", [], helpers.BOW_KIT, actor_id=ally_id)
    engine = Gate4ControllerEngine(helpers.ROOT, match_seed="BARRAGE-COURT-ALLY", typed_bundles=(main, ally_bundle),
                                   roster_setup={"primary_actor_ids": [helpers.ME, AN, ally_id],
                                                 "team_by_actor": {helpers.ME: "team:a", ally_id: "team:a", AN: "team:b"},
                                                 "starting_positions": {helpers.ME: {"x": 3, "y": 6}, AN: {"x": 6, "y": 6},
                                                                        ally_id: {"x": 3, "y": 7}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(helpers.ME)
    engine.state.current_actor_id = helpers.ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    engine.state.actors[AN].maximum_hp = 400
    engine.state.actors[AN].current_hp = 400
    _use(engine, "Court of Falling Stars")
    _use_target(engine, "Court of Falling Stars: choose ally", ally_id)
    assert "typed.court_falling_stars_ally" in helpers._conditions(engine.state.actors[ally_id])
    helpers._ready(engine)
    _use_target(engine, BOW, AN)
    assert "Court of Falling Stars: choose ally" not in helpers._legal(engine)
    assert "typed.court_falling_stars_target" not in helpers._conditions(engine.state.actors[AN])
    _use_target(engine, FOLLOW, AN)
    assert "typed.court_falling_stars_target" in helpers._conditions(engine.state.actors[AN])
    engine.state.current_slot_index = engine.state.initiative_order.index(ally_id)
    engine.state.current_actor_id = ally_id
    engine._system_start_turn()
    name = "Gong Jian (Bow and Arrow) attack"
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, ally_id)
    candidate = next(row for row in engine.legal_candidates() if row.display_name == name and row.target_ids == (AN,))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="court-ally-attack", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ally_id, target_ids=candidate.target_ids))
    attack = next(event for event in engine.events[before:] if event.event_type == "ATTACK_ROLLED")
    assert (attack.payload or {}).get("mode") == "ADVANTAGE"
    assert "typed.court_falling_stars_ally" not in helpers._conditions(engine.state.actors[ally_id])


def test_scorching_rays_burns_on_second_ray_not_first():
    engine = helpers._engine(helpers._bundle("tianxia.sphere.fire", ["FIRE_TAL_SCORCHING_RAY_ART"], helpers.BOW_KIT), foe_hp=400)
    rows = [name for name in helpers._legal(engine) if "Scorching Ray Art" in name]
    assert rows
    events = _use(engine, rows[0])
    attacks = [idx for idx, event in enumerate(events) if event.event_type == "ATTACK_ROLLED"]
    burns = [idx for idx, event in enumerate(events) if event.event_type == "CONDITION_APPLIED"
             and (event.payload or {}).get("condition_id") == "condition:typed.burning"]
    assert len(attacks) >= 2 and len(burns) == 1 and attacks[1] < burns[0]


def test_cascading_attack_is_a_button_for_a_different_target_and_cannot_chain():
    other_id = "actor:factory.foe2"
    main = helpers._bundle(helpers.BARRAGE, ["TAL_BARRAGE_CASCADING_BARRAGE"], helpers.BOW_KIT)
    other = helpers._bundle("", [], helpers.BOW_KIT, actor_id=other_id)
    engine = Gate4ControllerEngine(helpers.ROOT, match_seed="BARRAGE-CASCADE", typed_bundles=(main, other),
                                   roster_setup={"primary_actor_ids": [helpers.ME, AN, other_id],
                                                 "team_by_actor": {helpers.ME: "team:a", AN: "team:b", other_id: "team:b"},
                                                 "starting_positions": {helpers.ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6},
                                                                        other_id: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(helpers.ME)
    engine.state.current_actor_id = helpers.ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    engine.state.actors[AN].current_hp = 1
    engine.state.actors[other_id].armor_class = -50
    _use_target(engine, BOW, AN)
    choices = [row for row in engine.legal_candidates() if row.display_name == "Cascading Barrage: Gong Jian (Bow and Arrow)"]
    assert choices and all(row.target_ids == (other_id,) for row in choices)
    _use_target(engine, "Cascading Barrage: Gong Jian (Bow and Arrow)", other_id)
    assert "Cascading Barrage: Gong Jian (Bow and Arrow)" not in helpers._legal(engine)
