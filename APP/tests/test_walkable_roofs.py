"""Walkable roofs across authored maps, real service intents and cold recovery.

All actors are source-compiled synthetic Factory characters. Flight is gained by
the shipped Wind-Borne Body/Gather Current ability. No test patches movement,
falling, candidate admission, the controller, or saved state. Service submission
runs its real preview and Gate4PersistentSession.submit_intent, which commits
through PersistentMatchSession.execute_intent before a fresh service reload.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from app.models import TabletopRouteCommitRequest, TabletopRoutePreviewRequest
from combat import falling, flight
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.movement_routes import explicit_candidate
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from combat.targeting import line_of_effect
from tests.h1_support import ROOT, sheet


OWNER_PROJECT = "55550001"
FOE_PROJECT = "55550002"
OWNER, FOE = [FACTORY_ACTOR_PREFIX + project for project in (OWNER_PROJECT, FOE_PROJECT)]
WIND = "TAL_AIR_WIND_BORNE_BODY"
GATHER = "AIR_BASE_GATHER_CURRENT"


def roof_document(*, owner_start=(3, 3), foe_start=(10, 6), opening=None, door_open=True,
                  climb_check="none", hazards=(), roof_height_ft=10):
    walls = []
    for name, points in (
        ("north", [[4, 1], [8, 1]]),
        ("east", [[8, 1], [8, 5]]),
        ("south", [[4, 5], [8, 5]]),
        ("west", [[4, 1], [4, 5]]),
    ):
        walls.append({"id": name, "shape": "line", "points": points,
                      "blocks": "sight_and_movement", "height_ft": 10})
    roofs = {"enabled": True, "height_ft": roof_height_ft}
    if climb_check != "none":
        roofs["climb_check"] = climb_check
    if opening is not None:
        roofs["openings"] = [{"x": 6, "y": 3, **opening}]
    document = {
        "display_name": "Walkable roofs service yard", "width_squares": 12,
        "height_squares": 8, "walls": walls,
        "materials": [{"material": "floor:wood",
                       "cells": [[x, y] for y in range(2, 5) for x in range(5, 8)]}],
        "objects": [{"id": 1, "kind": "door", "x": 4, "y": 3,
                     "mount_axis": "v", "mount_line": 400, "height_ft": 10,
                     "interaction": "simple_door", "door_open": int(door_open),
                     "door_locked": 0, "door_jammed": 0}],
        "starts": {"team1": [list(owner_start)], "team2": [list(foe_start)]},
        "roofs": roofs,
    }
    if hazards:
        document["terrain"] = [{"type": "QI_HAZARD", "cells": [list(cell) for cell in hazards]}]
    return document


def roof_fight(tmp_path, *, owner_talents=(WIND,), foe_talents=(),
               seed="P20261010-05-ROOF-SERVICE", owner_strength=None, **map_options):
    for project, name, talents, initiative in (
        (OWNER_PROJECT, "Roof walker", owner_talents, 100),
        (FOE_PROJECT, "Roof opponent", foe_talents, -100),
    ):
        document = sheet(talents, cl=11)
        if project == OWNER_PROJECT and owner_strength is not None:
            strength = next(row for row in document['ability_scores_and_statistics']['abilities']
                            if row['ability'] == 'STR')
            strength.update(score=owner_strength, modifier=(owner_strength - 10) // 2)
        document["identity"]["display_name"] = name
        document["ability_scores_and_statistics"]["initiative"] = {"bonus": initiative}
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    saved_map = combat.tabletop_maps.save(roof_document(**map_options))
    arena_id = "battlefield:map." + saved_map["map_id"]
    match = combat.create_factory_match(
        project_ids=[OWNER_PROJECT], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        arena_id=arena_id, match_seed=seed, maximum_rounds=5,
    )
    mid = match["match_id"]
    assert combat._load_session(mid).engine.state.current_actor_id == OWNER
    return combat, TabletopService(combat, tmp_path), mid


def _payload(candidate):
    document = candidate.model_dump(mode="json")
    return {key: document[key] for key in (
        "candidate_id", "decision_id", "state_version", "actor_id", "target_ids",
        "destination", "option_ids",
    )}


def perform(combat, mid, predicate):
    session = combat._load_session(mid)
    candidate = next(candidate for candidate in session.engine.legal_candidates() if predicate(candidate))
    before = session.engine.state.state_version
    result = combat.submit_intent(mid, _payload(candidate), [], None, session=session)
    assert "preview_divergence" not in result
    assert session.engine.state.state_version > before
    return session, candidate


def gather(combat, mid):
    engine = combat._load_session(mid).engine
    sources = {action.source_definition_id for action in engine.action_catalog.values()
               if action.owner_id == engine.state.current_actor_id
               and action.parameters.get("typed", {}).get("source") == GATHER}
    session, _ = perform(combat, mid, lambda candidate: candidate.source_definition_id in sources)
    assert flight.profile(session.engine, session.engine.state.actors[session.engine.state.current_actor_id]).speed_ft == 30


def end_turn(combat, mid):
    return perform(combat, mid, lambda candidate: candidate.kind == "END_TURN")[0]


def route(combat, table, mid, points, *, mode="walk"):
    session = combat._load_session(mid)
    engine = session.engine
    path = tuple(Position(x=x, y=y, z=z) for x, y, z in points)
    candidate = explicit_candidate(engine, engine.state.current_actor_id, path, mode)
    before = engine.state.model_dump(mode="json")
    # Exercise the HTTP request-model boundary as well as the service seam;
    # otherwise an accepted native mode could still be rejected by the route API.
    preview_request = TabletopRoutePreviewRequest(
        decision_id=candidate.decision_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, waypoints=[point.model_dump(mode="json") for point in path],
        movement_mode=mode,
    )
    quoted = table.preview_move_path(mid, **preview_request.model_dump(mode="json"))
    assert quoted["status"] == "ROUTE_PREVIEW"
    assert quoted["candidate"]["candidate_id"] == candidate.candidate_id
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    commit_request = TabletopRouteCommitRequest(
        **preview_request.model_dump(mode="json"), candidate_id=candidate.candidate_id,
    )
    result = table.commit_move_path(mid, **commit_request.model_dump(mode="json"))
    assert result["status"] == "COMMITTED"
    assert "divergence_diagnostic" not in result
    return candidate


def rejected_route(combat, table, mid, points, *, mode="walk"):
    session = combat._load_session(mid)
    before = session.engine.state.model_dump(mode="json")
    events_before = [event.model_dump(mode="json") for event in session.engine.events]
    decision = combat.decision(mid, session=session)["context"]
    with pytest.raises(TabletopError) as raised:
        table.preview_move_path(
            mid, decision["decision_id"], decision["state_version"], decision["active_actor_id"],
            [{"x": x, "y": y, "z": z} for x, y, z in points], mode,
        )
    assert raised.value.code == "TABLETOP_ROUTE_INVALID"
    after = combat._load_session(mid).engine
    assert after.state.model_dump(mode="json") == before
    assert [event.model_dump(mode="json") for event in after.events] == events_before


def cold(combat, tmp_path, mid):
    before = combat._load_session(mid).engine
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    assert session.engine.state.model_dump(mode="json") == before.state.model_dump(mode="json")
    assert [event.model_dump(mode="json") for event in session.engine.events] == [
        event.model_dump(mode="json") for event in before.events]
    assert [roll.model_dump(mode="json") for roll in session.engine.rolls] == [
        roll.model_dump(mode="json") for roll in before.rolls]
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return fresh, TabletopService(fresh, tmp_path), session


def onto_roof(combat, table, mid, *, x=5):
    gather(combat, mid)
    actor = combat._load_session(mid).engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=3)
    path = [(3, 3, 0), (3, 3, 1), (3, 3, 2)] + [(column, 3, 2) for column in range(4, x + 1)]
    candidate = route(combat, table, mid, path, mode="fly")
    assert candidate.movement_cost_ft == (2 + x - 3) * 5


def test_rooftop_walk_avoids_an_equal_cost_opportunity_attack_with_service_reload(tmp_path):
    # Both fighters fly onto the roof (the owner first, the foe following on its own
    # turn). The owner's next turn has two equally short two-step routes from (4,3,2)
    # to (6,4,2): the one over (5,3) steps out of the foe's reach (an Opportunity
    # Attack), the one over (5,4) does not. Rooftop walking must use the same
    # safer-route policy as ordinary ground movement, so the attack-free route is the
    # one bound, committed and reloaded.
    combat, table, mid = roof_fight(tmp_path, owner_start=(3, 3), foe_start=(9, 3), foe_talents=(WIND,))
    onto_roof(combat, table, mid, x=4)
    end_turn(combat, mid)
    gather(combat, mid)
    route(combat, table, mid, [(9, 3, 0), (9, 3, 1), (9, 3, 2), (8, 3, 2),
                               (7, 3, 2), (6, 3, 2), (6, 2, 2)], mode="fly")
    end_turn(combat, mid)
    gather(combat, mid)
    engine = combat._load_session(mid).engine
    actor, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert actor.position == Position(x=4, y=3, z=2) and foe.position == Position(x=6, y=2, z=2)
    destination = Position(x=6, y=4, z=2)
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == "MOVE" and c.destination == destination)
    assert candidate.movement_cost_ft == 10
    assert candidate.metadata["expected_opportunity_attack_count"] == 0
    assert (5, 3) not in {(p.x, p.y) for p in candidate.canonical_path}, (
        "the equally short rooftop route that leaves the foe's reach must not be chosen")
    perform(combat, mid, lambda c: c.kind == "MOVE" and c.destination == destination)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination
    event = next(e for e in reversed(session.engine.events)
                 if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER)
    assert (5, 3) not in {(row["x"], row["y"]) for row in event.payload["path"]}


def test_fly_land_expire_walk_roof_and_edge_fall_survive_service_recovery(tmp_path):
    combat, table, mid = roof_fight(tmp_path)
    initial_hp = combat._load_session(mid).engine.state.actors[OWNER].current_hp
    onto_roof(combat, table, mid)
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=5, y=3, z=2)
    assert falling.supported(session.engine, actor)
    assert actor.current_hp == initial_hp
    assert session.engine.grid.line_of_sight(actor.position, Position(x=9, y=3, z=2))
    assert not session.engine.grid.line_of_sight(Position(x=5, y=3), Position(x=9, y=3))

    end_turn(combat, mid)
    ended = combat._load_session(mid).engine
    assert flight.profile(ended, ended.state.actors[OWNER]).speed_ft == 0
    end_turn(combat, mid)
    session = combat._load_session(mid)
    assert session.engine.state.current_actor_id == OWNER
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=5, y=3, z=2) and actor.current_hp == initial_hp
    before = actor.movement_remaining_ft
    candidate = route(combat, table, mid, [(5, 3, 2), (6, 3, 2)])
    assert candidate.movement_cost_ft == 5
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=6, y=3, z=2)
    assert actor.movement_remaining_ft == before - 5
    assert falling.supported(session.engine, actor)

    # Walking may leave one supported edge; the accepted path then falls.
    candidate = route(combat, table, mid, [(6, 3, 2), (5, 3, 2), (4, 3, 2), (3, 3, 2)])
    assert candidate.movement_cost_ft == 15
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=3)
    assert session.engine._has_condition(actor, "condition:typed.prone")
    falls = [event for event in session.engine.events if event.actor_id == OWNER
             and event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("fall_distance_ft")]
    assert len(falls) == 1 and falls[0].payload["fall_distance_ft"] == 10
    assert 1 <= falls[0].payload["damage_taken"] <= 6
    assert actor.current_hp == initial_hp - falls[0].payload["damage_taken"]


def test_flight_expiry_above_roof_lands_on_surface_instead_of_inside(tmp_path):
    combat, table, mid = roof_fight(tmp_path)
    gather(combat, mid)
    candidate = route(combat, table, mid,
                      [(3, 3, 0), (3, 3, 1), (3, 3, 2), (3, 3, 3), (4, 3, 3), (5, 3, 3)], mode="fly")
    assert candidate.movement_cost_ft == 25
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=5, y=3, z=3)
    assert not falling.supported(session.engine, actor), "a roof supports its surface, not empty air above it"
    end_turn(combat, mid)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=5, y=3, z=2)
    assert falling.supported(session.engine, actor)
    assert actor.current_hp == actor.maximum_hp
    assert not session.engine._has_condition(actor, "condition:typed.prone")
    falls = [event for event in session.engine.events if event.actor_id == OWNER
             and event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("fall_distance_ft")]
    assert len(falls) == 1 and falls[0].payload["fall_distance_ft"] == 5


def test_active_flyer_can_deliberately_jump_down_from_roof_and_reload(tmp_path):
    combat, table, mid = roof_fight(tmp_path)
    onto_roof(combat, table, mid, x=4)
    state = table.state(mid)
    owner = next(actor for actor in state["presentation"]["actors"] if actor["entity_id"] == OWNER)
    assert owner["on_roof"] is True and owner["roof_height_ft"] == 10
    assert owner["fly_speed_ft"] == 30 and owner["flying_movement_remaining_ft"] > 0
    edge = next(move for move in state["menu"]["moves"]
                if move["destination"] == {"x": 3, "y": 3, "z": 2})
    assert edge["can_jump_down"] is True
    before_hp = combat._load_session(mid).engine.state.actors[OWNER].current_hp
    candidate = route(combat, table, mid, [(4, 3, 2), (3, 3, 2)], mode="jump_down")
    assert candidate.movement_cost_ft == 5
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=3)
    assert flight.profile(session.engine, actor).speed_ft == 30
    falls = [event for event in session.engine.events if event.actor_id == OWNER
             and event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("fall_distance_ft")]
    assert len(falls) == 1 and falls[0].payload["fall_distance_ft"] == 10
    assert 1 <= falls[0].payload["damage_taken"] <= 6
    assert actor.current_hp == before_hp - falls[0].payload["damage_taken"]
    assert session.engine._has_condition(actor, "condition:typed.prone")


def test_ground_entry_uses_open_door_and_cannot_walk_through_wall(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_talents=())
    rejected_route(combat, table, mid, [(3, 3, 0), (3, 2, 0), (4, 2, 0)])
    candidate = route(combat, table, mid, [(3, 3, 0), (4, 3, 0), (5, 3, 0)])
    assert candidate.movement_cost_ft == 10
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=5, y=3)
    assert session.engine.grid.roof_height_at(5, 3) == 10
    assert actor.current_hp == actor.maximum_hp


def test_closed_door_blocks_ground_entry_and_keeps_roof_support(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_talents=(), door_open=False)
    rejected_route(combat, table, mid, [(3, 3, 0), (4, 3, 0), (5, 3, 0)])
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=3)
    assert session.engine.grid.roof_height_at(4, 3) == 10
    assert not session.engine.grid.volume_step_legal(Position(x=3, y=3), Position(x=4, y=3))


def test_climbing_grip_landing_and_deliberate_jump_down_survive_cold_recovery(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_start=(3, 2), owner_talents=())
    initial = combat._load_session(mid).engine.state.actors[OWNER]
    initial_hp, movement = initial.current_hp, initial.movement_remaining_ft
    first = route(combat, table, mid, [(3, 2, 0), (3, 2, 1)], mode="climb")
    assert first.movement_cost_ft == 10
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=2, z=1)
    assert actor.climbing and actor.current_hp == initial_hp
    assert actor.movement_remaining_ft == movement - first.movement_cost_ft
    second = route(combat, table, mid, [(3, 2, 1), (3, 2, 2), (4, 2, 2)], mode="climb")
    assert second.movement_cost_ft == 15  # ten feet for climbing, five for stepping onto support
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=4, y=2, z=2)
    assert falling.supported(session.engine, actor) and not actor.climbing
    assert actor.movement_remaining_ft == movement - first.movement_cost_ft - second.movement_cost_ft
    assert actor.current_hp == initial_hp
    assert not any(event.event_type == "CHECK_ROLLED" and event.source_definition_id == "system:combat.climbing"
                   for event in session.engine.events), "ordinary climbing does not roll Athletics"

    end_turn(combat, mid)
    end_turn(combat, mid)
    down = route(combat, table, mid, [(4, 2, 2), (3, 2, 2)], mode="jump_down")
    assert down.movement_cost_ft == 5
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=2) and not actor.climbing
    assert session.engine._has_condition(actor, "condition:typed.prone")
    falls = [event for event in session.engine.events if event.actor_id == OWNER
             and event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("fall_distance_ft")]
    assert len(falls) == 1 and falls[0].payload["fall_distance_ft"] == 10
    assert actor.current_hp == initial_hp - falls[0].payload["damage_taken"]


@pytest.mark.parametrize("check", ["slippery", "few_handholds"])
@pytest.mark.parametrize("seed,succeeds", [("P20261010-05-CLIMB-0", True), ("P20261010-05-CLIMB-1", False)])
def test_flagged_wall_checks_athletics_once_and_persists_outcome_and_cost(tmp_path, check, seed, succeeds):
    combat, table, mid = roof_fight(tmp_path, owner_start=(3, 2), owner_talents=(),
                                   climb_check=check, seed=seed)
    before = combat._load_session(mid).engine.state.actors[OWNER].movement_remaining_ft
    candidate = route(combat, table, mid, [(3, 2, 0), (3, 2, 1), (3, 2, 2), (4, 2, 2)], mode="climb")
    assert candidate.movement_cost_ft == 25
    _, _, session = cold(combat, tmp_path, mid)
    checks = [event for event in session.engine.events if event.event_type == "CHECK_ROLLED"
              and event.source_definition_id == "system:combat.climbing"]
    assert len(checks) == 1
    assert checks[0].payload["dc"] == 15 and checks[0].payload["check"] == "Athletics"
    recorded = checks[0].payload["actor"]
    success = recorded["total"] >= 15
    assert success is succeeds  # fixed real seeds cover both outcomes without replacing dice
    assert checks[0].payload["success"] is success
    actor = session.engine.state.actors[OWNER]
    assert actor.position == (Position(x=4, y=2, z=2) if success else Position(x=3, y=2))
    assert actor.movement_remaining_ft == before - (25 if success else 10)
    assert actor.current_hp == actor.maximum_hp


@pytest.mark.parametrize('owned,mode', [(True, 'ADVANTAGE'), (False, 'NORMAL')])
def test_sure_grip_roof_check_and_cold_reload(tmp_path, owned, mode):
    combat, table, mid = roof_fight(tmp_path, owner_start=(3, 2),
                                   owner_talents=('TAL_ATHLETICS_SURE_GRIP',) if owned else (),
                                   climb_check='slippery', seed='A2R01G-ROOF-GRIP')
    route(combat, table, mid, [(3, 2, 0), (3, 2, 1), (3, 2, 2), (4, 2, 2)], mode='climb')
    _, _, session = cold(combat, tmp_path, mid)
    checks = [e for e in session.engine.events if e.event_type == 'CHECK_ROLLED'
              and e.source_definition_id == 'system:combat.climbing']
    assert len(checks) == 1 and checks[0].payload['actor']['mode'] == mode


@pytest.mark.parametrize("opening", [None, {"kind": "trapdoor", "open": False},
                                      {"kind": "skylight", "open": False}])
def test_solid_roof_rejects_vertical_flight_without_mutation(tmp_path, opening):
    combat, table, mid = roof_fight(tmp_path, owner_start=(6, 3), opening=opening)
    gather(combat, mid)
    rejected_route(combat, table, mid, [(6, 3, 0), (6, 3, 1), (6, 3, 2)], mode="fly")
    _, _, session = cold(combat, tmp_path, mid)
    assert session.engine.state.actors[OWNER].position == Position(x=6, y=3)


@pytest.mark.parametrize("kind", ["trapdoor", "skylight"])
def test_open_roof_aperture_permits_vertical_flight_and_unsupported_fall(tmp_path, kind):
    combat, table, mid = roof_fight(tmp_path, owner_start=(6, 3), opening={"kind": kind, "open": True})
    gather(combat, mid)
    candidate = route(combat, table, mid, [(6, 3, 0), (6, 3, 1), (6, 3, 2)], mode="fly")
    assert candidate.movement_cost_ft == 10
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=6, y=3, z=2)
    assert not falling.supported(session.engine, actor)
    # The same aperture admits deliberate descent, with ordinary flight cost.
    down = route(combat, table, mid, [(6, 3, 2), (6, 3, 1), (6, 3, 0)], mode="fly")
    assert down.movement_cost_ft == 10
    route(combat, table, mid, [(6, 3, 0), (6, 3, 1), (6, 3, 2)], mode="fly")
    end_turn(combat, mid)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == Position(x=6, y=3)
    assert any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == OWNER
               and event.payload.get("fall_distance_ft") == 10 for event in session.engine.events)


@pytest.mark.parametrize("opening,sight,effect", [
    (None, False, False),
    ({"kind": "skylight", "open": False}, True, False),
    ({"kind": "trapdoor", "open": True}, True, True),
])
def test_roof_sight_effect_and_full_cover_agree_after_service_reload(tmp_path, opening, sight, effect):
    combat, table, mid = roof_fight(tmp_path, foe_start=(6, 3), opening=opening)
    onto_roof(combat, table, mid, x=6)
    _, _, session = cold(combat, tmp_path, mid)
    engine = session.engine
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert actor.position == Position(x=6, y=3, z=2) and target.position == Position(x=6, y=3)
    assert engine._line_of_sight_actor_to_actor(actor, target) is sight
    assert line_of_effect(engine, actor, target=target) is effect
    cover = engine.cover_from(engine._actor_volume(actor), OWNER, target, purpose="effect")
    assert cover["blocked"] is (not effect)
    assert cover["bonus"] == 0  # a solid slab is total blockage, not a numeric AC bonus
    if not effect:
        # A clear view through closed glass does not admit a flight descent.
        rejected_route(combat, table, mid, [(6, 3, 2), (6, 3, 1), (6, 3, 0)], mode="fly")


def test_roof_edge_supplies_partial_cover_to_a_supported_actor_after_reload(tmp_path):
    combat, table, mid = roof_fight(tmp_path, foe_start=(1, 3))
    onto_roof(combat, table, mid, x=4)
    _, _, session = cold(combat, tmp_path, mid)
    engine = session.engine
    low, top = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert top.position == Position(x=4, y=3, z=2)
    assert falling.supported(engine, top)
    assert engine._line_of_sight_actor_to_actor(low, top)
    assert line_of_effect(engine, low, target=top)
    cover = engine.cover_from(engine._actor_volume(low), FOE, top, purpose="effect")
    assert cover["blocked"] is False
    assert cover["bonus"] == 2  # preserve the native engine's numeric cover convention
    assert engine.grid.cover_bonus(Position(x=1, y=3, z=2), top.position) == 0


def test_local_ai_completes_a_rooftop_turn_and_cold_reloads(tmp_path):
    combat, table, mid = roof_fight(tmp_path, foe_start=(9, 3), foe_talents=(WIND,))
    onto_roof(combat, table, mid, x=5)
    end_turn(combat, mid)
    assert combat._load_session(mid).engine.state.current_actor_id == FOE
    gather(combat, mid)
    route(combat, table, mid, [(9, 3, 0), (9, 3, 1), (9, 3, 2), (8, 3, 2), (7, 3, 2)], mode="fly")
    end_turn(combat, mid)
    combat, table, session = cold(combat, tmp_path, mid)
    assert session.engine.state.current_actor_id == OWNER
    assert all(session.engine.state.actors[aid].position.z == 2 for aid in (OWNER, FOE))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    start_sequence = session.engine.state.event_sequence
    for _ in range(8):
        current = combat._load_session(mid)
        if current.engine.state.current_actor_id != OWNER or current.engine.state.terminal_result is not None:
            break
        result = table.auto_step(mid, start_sequence)
        assert result["status"] == "COMMITTED"
    _, _, session = cold(combat, tmp_path, mid)
    # The eighth accepted choice may itself end the turn. Inspect the state
    # after that commit instead of treating loop exhaustion as failure.
    assert session.engine.state.current_actor_id != OWNER or session.engine.state.terminal_result is not None, (
        "the local controller did not finish one bounded rooftop turn")
    events = [event for event in session.engine.events if event.sequence > start_sequence]
    assert any(event.actor_id == OWNER and event.event_type in {"ATTACK_ROLLED", "DAMAGE_ROLLED"}
               for event in events), "the AI turn must exercise combat from the roof"
    assert not any(event.payload.get("fall_distance_ft") for event in events)
    assert session.engine.state.actors[OWNER].position.z == 2
