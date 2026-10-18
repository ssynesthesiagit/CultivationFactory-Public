"""Height decisions through native candidates, committed intents and cold loads.

The preparation hook runs inside a real Hold transaction. It supplies controlled
flight/position facts, which the ordinary event reducer must persist; it does
not replace movement, reach, targeting, controller scoring or attack resolution.
"""
import json

import pytest

from combat import attack_reach, falling, flight, target_knowledge, targeting
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet


ME = "actor:factory.height_ai"
FOE = "actor:factory.height_foe"
FLIGHT = "condition:typed.height_ai_flight"
BOW_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
    {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 1},
]}}
AXE_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1},
]}}
SPEAR_KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1},
]}}


def _intent(candidate):
    return ActionIntent(
        intent_id=f"test:height:{candidate.candidate_id}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=candidate.option_ids,
    )


def _manual(session, kind):
    candidate = next(c for c in session.engine.legal_candidates() if c.kind == kind)
    session.submit_intent(_intent(candidate), primary_decision_record=None, reaction_provider=None)


def _cold(data, mid):
    service = CombatService(ROOT, data)
    session = service._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    return service, session


def _fight(data, *, foes=None, my_kit=BOW_KIT, foe_kit=AXE_KIT, terrain=(),
           my_position=None, mids_by_actor=None):
    """Public synthetic bundles and a sealed empty arena, without live userdata."""
    positions = {ME: my_position or {"x": 5, "y": 4}, **(foes or {FOE: {"x": 6, "y": 4}})}
    mids_by_actor = mids_by_actor or {}
    bundles = tuple(compile_character(sheet(mids_by_actor.get(aid, ()),
                                           kit=my_kit if aid == ME else foe_kit), actor_id=aid)
                    for aid in positions)
    arena = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    arena.update(stable_id="battlefield:test.height_ai", width_squares=12, height_squares=10,
                 starting_positions=positions, terrain_regions=list(terrain))
    service = CombatService(ROOT, data)
    session = service.persistence.create_match(
        match_seed="P20261010-04-HEIGHT", maximum_rounds=10, typed_bundles=bundles, battlefield=arena,
        roster_setup={"primary_actor_ids": list(positions),
                      "team_by_actor": {aid: "team:one" if aid == ME else "team:two" for aid in positions},
                      "starting_positions": positions},
    )
    for _ in positions:
        if session.engine.state.current_actor_id == ME:
            break
        _manual(session, "END_TURN")
    assert session.engine.state.current_actor_id == ME
    return service, session


def _grant(engine, aid=ME, *, expires_on=None, condition_id=FLIGHT, speed=30, hover=True):
    engine._apply_condition(engine.state.actors[aid], condition_id, "test:height:flight", aid,
                            expires_on=expires_on, data={"fly_speed_ft": speed, "flight_hover": int(hover)})


def _place(engine, aid, position):
    actor = engine.state.actors[aid]
    before = actor.position
    actor.position = position
    engine._append_event("MOVEMENT_COMMITTED", "test:height:placement", actor_id=aid,
                         payload={"destination": position.model_dump(mode="json"),
                                  "path": [before.model_dump(mode="json"), position.model_dump(mode="json")],
                                  "cost_ft": 0, "forced": True})


def _prepare(monkeypatch, data, session, callback, *, before_reload=None):
    from combat.gate4_engine import Gate4ControllerEngine
    def prepare(engine):
        callback(engine)
        # Reactions were already spent; ordinary reach still threatens the next
        # turn. Existing flight suites exercise ascent's opportunity attacks.
        for actor in engine.state.actors.values():
            if actor.entity_id != ME:
                actor.reaction_available = False
                engine._append_event("REACTION_RESOLVED", "test:height:spent", actor_id=actor.entity_id)
        # Flight lifecycle cannot depend on the context's truncated event window.
        for index in range(13):
            engine._append_event("PASSIVE_TRIGGERED", "test:height:elapsed", actor_id=ME,
                                 payload={"log": f"Preparation checkpoint {index}."})
    original = Gate4ControllerEngine._append_event
    def on_event(engine, event_type, *args, **kwargs):
        event = original(engine, event_type, *args, **kwargs)
        if event_type == "HOLD_POSITION_COMMITTED":
            prepare(engine)
        return event
    with monkeypatch.context() as scope:
        scope.setattr(Gate4ControllerEngine, "_append_event", on_event)
        _manual(session, "HOLD_POSITION")
    if before_reload is not None:
        before_reload(session)
    return _cold(data, session.match_id)


def _choose(service, session):
    policy, _ = service.policies.for_actor(session.engine.state.current_actor_id)
    before = session.engine.state.model_dump(mode="json")
    events = [event.model_dump(mode="json") for event in session.engine.events]
    rolls = [roll.model_dump(mode="json") for roll in session.engine.rolls]
    context = build_decision_context(session.engine, policy, for_ai=True)
    choice = service.controller.choose_primary_action(context)
    assert session.engine.state.model_dump(mode="json") == before
    assert [event.model_dump(mode="json") for event in session.engine.events] == events
    assert [roll.model_dump(mode="json") for roll in session.engine.rolls] == rolls
    candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    return context, choice, candidate


def _commit(service, session, choice, data):
    session.execute_controller_choice(choice, controller=service.controller, policy_library=service.policies)
    return _cold(data, session.match_id)


def _ranged_sources(engine, aid=ME):
    from combat.attack_provenance import ranged_attacks
    return {row["source_id"] for row in ranged_attacks(engine, engine.state.actors[aid])}


def _melee_actions(engine, aid):
    actor = engine.state.actors[aid]
    return [engine.action_catalog[source] for source in actor.action_ids
            if source in engine.action_catalog and attack_reach.melee(engine.action_catalog[source])]


@pytest.mark.parametrize("enemy_kit", [AXE_KIT, SPEAR_KIT], ids=["ordinary-reach", "spear-reach"])
def test_flier_uses_lowest_safe_attacking_height_then_fires_and_reloads(monkeypatch, tmp_path, enemy_kit):
    # Occupied adjacent ground squares make flight useful, instead of demanding
    # ascent when an equally safe, shorter walk would be sensible.
    foes = {f"{FOE}_{dx}_{dy}": {"x": 5 + dx, "y": 4 + dy}
            for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)}
    service, session = _fight(tmp_path, foes=foes, foe_kit=enemy_kit)
    reach = max(attack_reach.maximum(session.engine, session.engine.state.actors[aid], action) or 0
                for aid in foes for action in _melee_actions(session.engine, aid))
    assert reach >= 5
    if enemy_kit == SPEAR_KIT:
        assert reach > 5, "The second scenario must exercise more than ordinary five-foot reach."
    budget = reach + session.engine.grid.square_size_ft
    def prepare(engine):
        _grant(engine)
        flight.spend(engine.state.actors[ME], 30 - budget)
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    _, choice, candidate = _choose(service, session)
    assert candidate.kind == "MOVE" and candidate.destination.z > 0
    assert candidate.movement_cost_ft <= budget
    service, session = _commit(service, session, choice, tmp_path)
    engine, actor = session.engine, session.engine.state.actors[ME]
    assert actor.position == candidate.destination
    assert not any(engine._target_in_range(engine.state.actors[aid], actor, action)
                   for aid in foes for action in _melee_actions(engine, aid))
    # No unnecessary extra altitude is possible within the minimal escape budget.
    assert actor.position.z * engine.grid.square_size_ft == budget
    _, shot, attack = _choose(service, session)
    assert attack.source_definition_id in _ranged_sources(engine)
    before = len(engine.events)
    _, session = _commit(service, session, shot, tmp_path)
    assert any(event.event_type == "ATTACK_ROLLED" and event.actor_id == ME
               and event.source_definition_id == attack.source_definition_id
               for event in session.engine.events[before:])


def test_unconstrained_flier_prefers_the_lowest_useful_attacking_height(monkeypatch, tmp_path):
    # The ordinary-reach case above spends the entire allowance on the minimal
    # escape, so it cannot tell "lowest useful height" from "highest affordable
    # height". Here the flier keeps its whole Fly-30 allowance: every altitude
    # from the minimum escape up to +30 ft is an equally safe attacking
    # position, and only a real preference keeps it at the lowest one.
    foes = {f"{FOE}_{dx}_{dy}": {"x": 5 + dx, "y": 4 + dy}
            for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)}
    service, session = _fight(tmp_path, foes=foes, foe_kit=AXE_KIT)
    engine = session.engine
    reach = max(attack_reach.maximum(engine, engine.state.actors[aid], action) or 0
                for aid in foes for action in _melee_actions(engine, aid))
    square = engine.grid.square_size_ft
    assert reach % square == 0
    lowest = (reach + square) // square  # first altitude outside every melee reach
    assert lowest > 0
    # No movement is spent, so every higher safe attacking height is affordable.
    service, session = _prepare(monkeypatch, tmp_path, session, _grant)
    context, choice, candidate = _choose(service, session)
    engine = session.engine
    assert candidate.kind == "MOVE"
    safe_heights = sorted({c.destination.z for c in context.legal_candidates
                           if c.kind == "MOVE"
                           and c.metadata.get("flight_tactics", {}).get("destination", {}).get("safe_attack")})
    # Several safe attacking heights are offered: the minimum and higher ones.
    assert lowest in safe_heights, "The minimal escape height must still allow a safe attack."
    assert max(safe_heights) > lowest, "Higher safe attacking heights must be offered too."
    assert candidate.destination.z == lowest, (
        f"An unconstrained flier climbed to {candidate.destination.z} instead of the lowest useful height {lowest}.")
    service, session = _commit(service, session, choice, tmp_path)
    engine, actor = session.engine, session.engine.state.actors[ME]
    assert actor.position.z == lowest
    assert not any(engine._target_in_range(engine.state.actors[aid], actor, action)
                   for aid in foes for action in _melee_actions(engine, aid))
    # It can still attack from the lowest safe height, and does on the next step.
    _, shot, attack = _choose(service, session)
    assert attack.source_definition_id in _ranged_sources(engine)
    before = len(engine.events)
    _, session = _commit(service, session, shot, tmp_path)
    assert any(event.event_type == "ATTACK_ROLLED" and event.actor_id == ME
               and event.source_definition_id == attack.source_definition_id
               for event in session.engine.events[before:])


def test_grounded_creature_fires_at_high_flier_instead_of_chasing_its_ground_projection(monkeypatch, tmp_path):
    service, session = _fight(tmp_path)
    def prepare(engine):
        _grant(engine, FOE)
        _place(engine, FOE, Position(x=6, y=4, z=4))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    engine = session.engine
    assert not any(engine._target_in_range(engine.state.actors[ME], engine.state.actors[FOE], action)
                   for action in _melee_actions(engine, ME))
    _, choice, candidate = _choose(service, session)
    assert candidate.source_definition_id in _ranged_sources(engine)
    assert candidate.target_ids == (FOE,)
    before = len(engine.events)
    _, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].position.z == 0
    assert any(event.event_type == "ATTACK_ROLLED" and event.actor_id == ME
               for event in session.engine.events[before:])


@pytest.mark.parametrize("deadline", ["current-end", "next-start"])
def test_expiring_flight_lands_before_end_turn_even_when_grant_event_is_old(monkeypatch, tmp_path, deadline):
    service, session = _fight(tmp_path)
    def prepare(engine):
        expires = ("END_OF_CURRENT_TURN" if deadline == "current-end" else
                   f"START_OF_SLOT_AT:{engine.state.round_number + 1}:{engine.state.current_slot_index}")
        _grant(engine, expires_on=expires)
        _place(engine, ME, Position(x=5, y=4, z=4))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    context, choice, candidate = _choose(service, session)
    assert not any(event["event_type"] == "CONDITION_APPLIED" for event in context.recent_events)
    assert candidate.kind == "MOVE" and candidate.destination.z == 0
    hp = session.engine.state.actors[ME].current_hp
    service, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].position.z == 0
    _manual(session, "END_TURN")
    if deadline == "next-start":
        while session.engine.state.current_actor_id != ME:
            _manual(session, "END_TURN")
    _, session = _cold(tmp_path, session.match_id)
    actor = session.engine.state.actors[ME]
    assert flight.profile(session.engine, actor).speed_ft == 0
    assert actor.current_hp == hp
    assert not any(event.payload.get("fall_distance_ft") for event in session.engine.events)
    assert not any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())


@pytest.mark.parametrize("survival", ["permanent", "overlap", "hover", "suspended", "next-end"])
def test_safe_flier_attacks_without_pointless_climb_or_unnecessary_landing(monkeypatch, tmp_path, survival):
    service, session = _fight(tmp_path, foes={FOE: {"x": 8, "y": 4}})
    def prepare(engine):
        if survival in {"hover", "suspended"}:
            _grant(engine, expires_on="END_OF_CURRENT_TURN")
            engine._apply_condition(engine.state.actors[ME], FLIGHT + "_support", "test:height:support", ME,
                                    expires_on=None, data={"flight_" + survival: 1})
        elif survival == "next-end":
            _grant(engine, expires_on=f"END_OF_TURN_AT:{ME}:{engine.state.actors[ME].turns_started + 1}")
        else:
            _grant(engine)
        if survival == "overlap":
            _grant(engine, condition_id=FLIGHT + "_short", expires_on="END_OF_CURRENT_TURN")
        _place(engine, ME, Position(x=5, y=4, z=2))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    _, choice, candidate = _choose(service, session)
    assert candidate.source_definition_id in _ranged_sources(session.engine)
    assert candidate.target_ids == (FOE,)
    _, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].position == Position(x=5, y=4, z=2)


@pytest.mark.parametrize("own_flight", [False, True], ids=["grounded-observer", "flying-observer"])
def test_hidden_enemy_altitude_and_capability_do_not_change_height_decision(monkeypatch, tmp_path, own_flight):
    contexts, choices = [], []
    for label, altitude in (("ground", 0), ("air", 8)):
        data = tmp_path / label
        service, session = _fight(data, foes={FOE: {"x": 9, "y": 4}})
        def prepare(engine):
            if own_flight:
                _grant(engine)
                _place(engine, ME, Position(x=5, y=4, z=2))
            engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:hide", FOE,
                                    expires_on=None)
            _grant(engine, FOE, speed=10 if altitude == 0 else 30)
            _place(engine, FOE, Position(x=9, y=4, z=altitude))
        service, session = _prepare(monkeypatch, data, session, prepare)
        viewer, enemy = session.engine.state.actors[ME], session.engine.state.actors[FOE]
        assert not target_knowledge.located(session.engine, viewer, enemy)
        context, choice, _ = _choose(service, session)
        if not own_flight:
            assert all("flight_tactics" not in candidate.metadata for candidate in context.legal_candidates)
        contexts.append(context.model_dump(mode="json", by_alias=True))
        choices.append(choice.model_dump(mode="json", by_alias=True))
    assert contexts[0] == contexts[1]
    assert choices[0] == choices[1]


@pytest.mark.parametrize("terrain_type", ["BLOCKED", "SIGHT_BLOCKED"], ids=["line-of-effect", "line-of-sight"])
def test_height_projection_does_not_credit_shots_through_blocked_paths(monkeypatch, tmp_path, terrain_type):
    terrain = [{"terrain_type": terrain_type, "movement_cost": 1,
                "cells": [{"x": 7, "y": y} for y in range(10)]}]
    service, session = _fight(tmp_path, foes={FOE: {"x": 9, "y": 4}}, terrain=terrain)
    def prepare(engine):
        _grant(engine)
        _place(engine, ME, Position(x=5, y=4, z=2))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    engine = session.engine
    actor, enemy = engine.state.actors[ME], engine.state.actors[FOE]
    assert not target_knowledge.can_see(engine, actor, enemy)
    if terrain_type == "BLOCKED":
        assert not targeting.line_of_effect(engine, actor, target=enemy)
    else:
        assert targeting.line_of_effect(engine, actor, target=enemy)
    context, choice, _ = _choose(service, session)
    assert not any(c.target_ids == (FOE,) for c in context.legal_candidates
                   if c.source_definition_id in _ranged_sources(engine))
    for candidate in context.legal_candidates:
        tactic = candidate.metadata.get("flight_tactics", {})
        for point in (tactic.get("current"), tactic.get("destination")):
            if point is not None:
                assert FOE not in point.get("attack_target_ids", ())
    _commit(service, session, choice, tmp_path)


def test_context_and_choice_are_identical_after_fresh_reload(monkeypatch, tmp_path):
    service, session = _fight(tmp_path)
    def prepare(engine):
        _grant(engine, expires_on="END_OF_CURRENT_TURN")
        _place(engine, ME, Position(x=5, y=4, z=3))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    context, choice, _ = _choose(service, session)
    mid = session.match_id
    del service, session
    service, session = _cold(tmp_path, mid)
    restored_context, restored_choice, _ = _choose(service, session)
    assert restored_context.model_dump(mode="json", by_alias=True) == context.model_dump(mode="json", by_alias=True)
    assert restored_choice.model_dump(mode="json", by_alias=True) == choice.model_dump(mode="json", by_alias=True)
    _commit(service, session, restored_choice, tmp_path)


def test_large_enemy_threat_uses_occupied_height_instead_of_anchor_distance(monkeypatch, tmp_path):
    from combat.dynamic_size import apply_growth
    service, session = _fight(tmp_path)
    def prepare(engine):
        _grant(engine)
        _place(engine, ME, Position(x=5, y=4, z=2))
        apply_growth(engine, engine.state.actors[FOE], "Large", "test:height:growth",
                     source_actor_id=FOE, expires_on=None)
        flight.spend(engine.state.actors[ME], 25)
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    engine = session.engine
    actor, enemy = engine.state.actors[ME], engine.state.actors[FOE]
    assert enemy.transformed_size_category == "Large"
    assert engine._distance_actor_to_actor(actor, enemy) == 5
    context, choice, candidate = _choose(service, session)
    current = context.legal_candidates[0].metadata["flight_tactics"]["current"]
    assert FOE in current["melee_threat_ids"]
    assert candidate.kind == "MOVE"
    _, session = _commit(service, session, choice, tmp_path)
    engine = session.engine
    assert not any(engine._target_in_range(engine.state.actors[FOE], engine.state.actors[ME], action)
                   for action in _melee_actions(engine, FOE))
    assert any(c.source_definition_id in _ranged_sources(engine) and c.target_ids == (FOE,)
               for c in engine.legal_candidates())


def test_expiring_flier_can_land_on_the_square_it_just_left(monkeypatch, tmp_path):
    # Gate4 upgrades briefly initialize the stock roster before restoring the
    # saved roster; isolated spare cells accommodate that constructor without
    # opening a second landing route out of this shaft.
    free = {(5, 4), (6, 4), (0, 0), (0, 1), (0, 2), (0, 3), (0, 4)}
    terrain = [{"terrain_type": "BLOCKED", "movement_cost": 1,
                "cells": [{"x": x, "y": y} for x in range(12) for y in range(10)
                          if (x, y) not in free]}]
    service, session = _fight(tmp_path, terrain=terrain)
    service, session = _prepare(monkeypatch, tmp_path, session,
                                lambda engine: _grant(engine, expires_on="END_OF_CURRENT_TURN"))
    start = session.engine.state.actors[ME].position
    ascent = next(c for c in session.engine.legal_candidates()
                  if c.kind == "MOVE" and c.destination == start.model_copy(update={"z": 2}))
    session.submit_intent(_intent(ascent), primary_decision_record=None, reaction_provider=None)
    service, session = _cold(tmp_path, session.match_id)
    context, choice, candidate = _choose(service, session)
    assert start in context.movement_endpoints
    assert candidate.kind == "MOVE" and candidate.destination == start
    _, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].position == start
    assert not any(event.payload.get("fall_distance_ft") for event in session.engine.events)


def test_imminent_landing_recovers_an_interrupted_controller_prepare(monkeypatch, tmp_path):
    from combat.gate3_storage import Gate3InjectedCrash
    service, session = _fight(tmp_path)
    def prepare(engine):
        _grant(engine, expires_on="END_OF_CURRENT_TURN")
        _place(engine, ME, Position(x=5, y=4, z=3))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    _, choice, candidate = _choose(service, session)
    assert candidate.kind == "MOVE" and candidate.destination.z == 0
    def interrupt(stage, _):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash("height decision after durable PREPARE")
    with pytest.raises(Gate3InjectedCrash, match="durable PREPARE"):
        session.execute_controller_choice(choice, controller=service.controller, policy_library=service.policies,
                                          failure_injector=interrupt)
    mid = session.match_id
    del service, session
    _, recovered = _cold(tmp_path, mid)
    assert recovered.engine.state.actors[ME].position == candidate.destination
    records = [json.loads(line) for line in recovered.controller_journal_path.read_text().splitlines()]
    assert records[-1]["record_type"] == "CONTROLLER_COMMIT"
    assert records[-1]["recovered_from_incomplete_prepare"] is True
    assert recovered.verify()["controller_open_transactions"] == []


def test_two_turn_flight_deadline_starts_descent_before_the_last_turn(monkeypatch, tmp_path):
    service, session = _fight(tmp_path, foes={FOE: {"x": 8, "y": 4}})
    def prepare(engine):
        _grant(engine, expires_on=f"END_OF_TURN_AT:{ME}:{engine.state.actors[ME].turns_started + 1}")
        _place(engine, ME, Position(x=5, y=4, z=9))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    # Forty-five feet exceeds one later Fly-30 allowance. Waiting to begin the
    # descent on the final turn would strand the actor above the ground.
    assert flight.remaining(session.engine, session.engine.state.actors[ME], "fly") == 30
    hp = session.engine.state.actors[ME].current_hp
    _, choice, candidate = _choose(service, session)
    assert candidate.kind == "MOVE" and 0 < candidate.destination.z <= 6
    service, session = _commit(service, session, choice, tmp_path)
    _manual(session, "END_TURN")
    while session.engine.state.current_actor_id != ME:
        _manual(session, "END_TURN")
    service, session = _cold(tmp_path, session.match_id)
    assert session.engine.state.actors[ME].position.z > 0
    assert flight.profile(session.engine, session.engine.state.actors[ME]).speed_ft == 30
    _, choice, candidate = _choose(service, session)
    assert candidate.kind == "MOVE" and candidate.destination.z == 0
    _, session = _commit(service, session, choice, tmp_path)
    _manual(session, "END_TURN")
    _, session = _cold(tmp_path, session.match_id)
    actor = session.engine.state.actors[ME]
    assert actor.position.z == 0 and actor.current_hp == hp
    assert flight.profile(session.engine, actor).speed_ft == 0
    assert not any(event.payload.get("fall_distance_ft") for event in session.engine.events)


def test_local_step_uses_memoized_candidates_and_matches_cold_controller_choice(monkeypatch, tmp_path):
    service, session = _fight(tmp_path)
    def prepare(engine):
        _grant(engine, expires_on="END_OF_CURRENT_TURN")
        _place(engine, ME, Position(x=5, y=4, z=3))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    service.set_controller_mode(session.match_id, actor_id=ME, controller_mode="LOCAL_AUTO")
    service, session = _cold(tmp_path, session.match_id)
    direct, choice, candidate = _choose(service, session)
    policy, _ = service.policies.for_actor(ME)
    canonical = service._legal_candidates(session, knowledge_only=True)
    # Prepared inputs replace the former runtime method override. Prospective
    # endpoints still query their projected position, not the origin menu.
    assert "legal_candidates" not in session.engine.__dict__
    memoized = build_decision_context(session.engine, policy, for_ai=True,
                                      prepared_candidates=canonical)
    assert "legal_candidates" not in session.engine.__dict__
    assert memoized.model_dump(mode="json", by_alias=True) == direct.model_dump(mode="json", by_alias=True)
    result = service.local_step(session.match_id)
    assert result["status"] == "COMMITTED"
    assert result["record"] == choice.record.model_dump(mode="json", by_alias=True)
    _, session = _cold(tmp_path, session.match_id)
    assert candidate.kind == "MOVE" and candidate.destination.z == 0
    assert session.engine.state.actors[ME].position == candidate.destination


@pytest.mark.parametrize("movement_budget", [None, 30], ids=["entry-step", "full-turn"])
def test_hidden_gravity_domain_owner_still_suppresses_unsafe_projected_flight(monkeypatch, tmp_path, movement_budget):
    owner = "actor:factory.height_domain_owner"
    domain_source = "tianxia.talent.gravity.gravity_domain"
    service, session = _fight(
        tmp_path, my_position={"x": 3, "y": 4},
        foes={FOE: {"x": 1, "y": 4}, owner: {"x": 10, "y": 4}},
        mids_by_actor={owner: [domain_source]},
    )
    _manual(session, "END_TURN")
    while session.engine.state.current_actor_id != owner:
        _manual(session, "END_TURN")
    # The persistent area is created by the compiled ability's native intent.
    domain = next(c for c in session.engine.legal_candidates()
                  if c.source_definition_id in session.engine.action_catalog
                  and session.engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source") == domain_source)
    session.submit_intent(_intent(domain), primary_decision_record=None, reaction_provider=None)
    _manual(session, "END_TURN")
    while session.engine.state.current_actor_id != ME:
        _manual(session, "END_TURN")
    def prepare(engine):
        zone = next(z for z in engine.state.zones.values() if z.owner_id == owner and z.active)
        actor = engine.state.actors[ME]
        outside = [Position(x=x, y=4, z=2) for x in range(10)
                   if not engine._in_zone(actor.model_copy(update={"position": Position(x=x, y=4, z=2)}), zone)]
        start = max(outside, key=lambda position: position.x)
        entry = start.model_copy(update={"x": start.x + 1})
        assert engine._in_zone(actor.model_copy(update={"position": entry}), zone)
        _grant(engine, hover=False, expires_on="END_OF_CURRENT_TURN" if movement_budget else None)
        _place(engine, ME, start)
        # Domain also creates hostile difficult terrain; leave enough movement
        # for one real priced entry, rather than assuming a five-foot cost.
        entry_cost = flight.step_cost(engine, actor, start, entry, mode="fly")
        allowance = entry_cost if movement_budget is None else movement_budget
        flight.spend(actor, flight.remaining(engine, actor, "fly") - allowance)
        engine._apply_condition(engine.state.actors[owner], "condition:typed.invisible", "test:height:hide_owner", owner,
                                expires_on=None)
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    engine, actor = session.engine, session.engine.state.actors[ME]
    assert not target_knowledge.located(engine, actor, engine.state.actors[owner])
    assert flight.profile(engine, actor).speed_ft == 30
    context, choice, selected = _choose(service, session)
    zone = next(z for z in engine.state.zones.values() if z.owner_id == owner and z.active)
    inside, unevaluated_inside, unsafe_supported_routes = [], [], []
    for candidate in context.legal_candidates:
        tactics = candidate.metadata.get("flight_tactics", {})
        for assessment in (tactics.get("current"), tactics.get("destination")):
            if assessment is not None:
                assert owner not in assessment["distances_ft"]
                assert owner not in assessment["attack_target_ids"]
                assert owner not in assessment["melee_threat_ids"]
        if candidate.kind != "MOVE":
            continue
        projected = actor.model_copy(deep=True, update={"position": candidate.destination})
        assessment = tactics["destination"]
        native_fall = falling.required(engine, projected)
        assert assessment["fall_required"] is native_fall
        route_fall = any(falling.required(engine, actor.model_copy(deep=True, update={"position": position}))
                         for position in candidate.canonical_path[1:])
        assert assessment["path_requires_fall"] is route_fall
        if falling.supported(engine, projected) and route_fall:
            unsafe_supported_routes.append(candidate)
            assert not assessment["safe_attack"]
        if not candidate.destination.z:
            continue
        if not engine._in_zone(projected, zone):
            continue
        assert flight.profile(engine, projected).speed_ft == 0
        assert native_fall
        assert not assessment["safe_attack"]
        if assessment["evaluated"]:
            inside.append(candidate)
        else:
            unevaluated_inside.append(candidate)
    if movement_budget is None:
        assert inside, "The menu must exercise evaluated endpoints inside the unseen owner's real Domain."
    else:
        assert unevaluated_inside, "The full move menu must exercise support facts beyond the 64 exact attack queries."
        assert unsafe_supported_routes, "A safe endpoint must not hide an airborne fall along its canonical path."
    if movement_budget is None:
        assert selected.source_definition_id in _ranged_sources(engine)
        assert selected.target_ids == (FOE,)
    else:
        assert selected.kind == "MOVE" and selected.destination.z == 0
        facts = selected.metadata["flight_tactics"]["destination"]
        assert not facts["fall_required"] and not facts["path_requires_fall"] and not facts["path_blocked"]
    hp = actor.current_hp
    _, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].current_hp == hp


def test_expiring_terrain_discount_does_not_underprice_next_turn_descent(monkeypatch, tmp_path):
    from combat import zones
    from combat.gate2_runtime_models import ZoneState
    discount = "condition:typed.body_adrenaline_juggernaut"
    service, session = _fight(tmp_path, foes={FOE: {"x": 8, "y": 4}},
                              mids_by_actor={ME: ["TAL_BERSERKER_JUGGERNAUT"]})
    def prepare(engine):
        actor = engine.state.actors[ME]
        _grant(engine, expires_on=f"END_OF_TURN_AT:{ME}:{actor.turns_started + 1}")
        engine._apply_condition(actor, discount, "test:height:terrain_discount", ME,
                                expires_on="END_OF_CURRENT_TURN")
        _place(engine, ME, Position(x=5, y=4, z=5))
        # A recorded volumetric area affects flying movement. Ground-painted
        # difficult terrain would not exercise the native flight price rule.
        zone = ZoneState(
            zone_id="zone:typed.height_difficult", source_definition_id="test:height:difficult",
            owner_id=FOE, center=Position(x=5, y=4, z=3), radius_cells=10,
            affected_cells=tuple(Position(x=x, y=y) for x in range(12) for y in range(10)),
            concentration_link=False, created_round=engine.state.round_number,
            trigger_profile={"kind": zones.KIND, "shape": "cube", "size_ft": 100, "difficult": "all"},
        )
        engine.state.zones[zone.zone_id] = zone
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=FOE,
                             payload={"zone": zone.model_dump(mode="json")})
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    engine, actor = session.engine, session.engine.state.actors[ME]
    down = actor.position.model_copy(update={"z": actor.position.z - 1})
    assert flight.step_cost(engine, actor, actor.position, down, mode="fly") == 5
    future_actor = actor.model_copy(deep=True)
    future_actor.conditions = {key: row for key, row in future_actor.conditions.items() if row.condition_id != discount}
    assert flight.step_cost(engine, future_actor, future_actor.position, down, mode="fly") == 10
    # Its 25-foot descent is cheap enough now, but would cost 50 after this
    # turn's discount expires, beyond the one remaining Fly-30 allowance.
    _, choice, candidate = _choose(service, session)
    assert candidate.kind == "MOVE" and candidate.destination.z == 0
    hp = actor.current_hp
    _, session = _commit(service, session, choice, tmp_path)
    assert session.engine.state.actors[ME].position.z == 0
    assert session.engine.state.actors[ME].current_hp == hp


def test_simultaneous_expiries_warn_about_native_transient_loss_of_support(monkeypatch, tmp_path):
    service, session = _fight(tmp_path, foes={FOE: {"x": 8, "y": 4}})
    def prepare(engine):
        actor = engine.state.actors[ME]
        _grant(engine, hover=False)
        # Native expiry removes these rows in application order. Hover goes
        # away while Fly Speed is still zero, so the later restoration of Fly
        # Speed cannot undo the fall already triggered by losing Hover.
        engine._apply_condition(actor, FLIGHT + "_hover", "test:height:hover", ME,
                                expires_on="END_OF_CURRENT_TURN", data={"flight_hover": 1})
        engine._apply_condition(actor, FLIGHT + "_zero", "test:height:zero", ME,
                                expires_on="END_OF_CURRENT_TURN", data={"fly_speed_zero": 1})
        _place(engine, ME, Position(x=5, y=4, z=3))
    service, session = _prepare(monkeypatch, tmp_path, session, prepare)
    actor = session.engine.state.actors[ME]
    assert flight.profile(session.engine, actor).speed_ft == 0
    assert not falling.required(session.engine, actor)
    context, _, _ = _choose(service, session)
    assert not any(c.kind == "MOVE" for c in context.legal_candidates)
    assert all(c.metadata["flight_tactics"]["flight_ending"] for c in context.legal_candidates)
    # This fixture cannot descend while its Fly Speed is zero. Execute the real
    # boundary to prove the warning describes the engine's ordered expiry,
    # rather than falsely promising that an AI movement choice can save it.
    hp = actor.current_hp
    _manual(session, "END_TURN")
    _, session = _cold(tmp_path, session.match_id)
    actor = session.engine.state.actors[ME]
    assert actor.position.z == 0 and actor.current_hp < hp
    assert flight.profile(session.engine, actor).speed_ft == 30
    assert any(event.payload.get("fall_distance_ft") for event in session.engine.events)


def test_simultaneous_expiry_warning_is_identical_live_reordered_and_cold(monkeypatch, tmp_path):
    from combat.canonical import canonical_sha256
    service, session = _fight(tmp_path, foes={FOE: {"x": 8, "y": 4}})
    snapshots = []
    def prepare(engine):
        actor = engine.state.actors[ME]
        _grant(engine, hover=False)
        # Apply Hover first but give it a key that sorts after suppression in
        # the canonical saved JSON. The decision must conservatively account
        # for either native removal order without depending on dictionary order.
        engine._apply_condition(actor, FLIGHT + "_zzz_hover", "test:height:hover", ME,
                                expires_on="END_OF_CURRENT_TURN", data={"flight_hover": 1})
        engine._apply_condition(actor, FLIGHT + "_aaa_zero", "test:height:zero", ME,
                                expires_on="END_OF_CURRENT_TURN", data={"fly_speed_zero": 1})
        _place(engine, ME, Position(x=5, y=4, z=3))
    def snapshot(prepared):
        context, choice, _ = _choose(service, prepared)
        assert all(c.metadata["flight_tactics"]["flight_ending"] for c in context.legal_candidates)
        snapshots.append((context.model_dump(mode="json", by_alias=True), choice.model_dump(mode="json", by_alias=True)))
    def inspect_live(prepared):
        actor = prepared.engine.state.actors[ME]
        original = actor.conditions
        assert list(original) != sorted(original), "The fixture must really differ from canonical save order."
        before = canonical_sha256(prepared.engine.state.model_dump(mode="json"))
        snapshot(prepared)
        actor.conditions = dict(reversed(tuple(original.items())))
        assert canonical_sha256(prepared.engine.state.model_dump(mode="json")) == before
        snapshot(prepared)
        actor.conditions = original
    service, session = _prepare(monkeypatch, tmp_path, session, prepare, before_reload=inspect_live)
    snapshot(session)
    assert snapshots[0] == snapshots[1] == snapshots[2]
