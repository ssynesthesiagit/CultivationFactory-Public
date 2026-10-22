"""Native passenger choice, consent and physical Painted Passage regressions.

These cases use manifested actors and table commits, never a passenger receipt.
They do not certify the unfinished acquisition and world-boundary contracts.
"""
import pytest

from tests.test_mgr_t14_sol_subpath_living_painting import setup, create
from tests.worker2_support import OWNER, ALLY, candidate, settle, reload

SUBJECT = "choice:needle.painted_passage_subject"
CONSENT = "choice:needle.painted_passage_consent"


def crane_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    aid = create(combat, table, mid, "crane", "FORCE")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    return combat, table, mid, aid


@pytest.mark.parametrize("passenger", [OWNER, ALLY])
@pytest.mark.parametrize("consent", ["accept", "refuse"])
def test_table_passage_passenger_owns_consent_and_cold_replays(tmp_path, passenger, consent):
    combat, table, mid, aid = crane_turn(tmp_path)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[passenger].model_copy(deep=True)
    # Both nearby creatures fit this route. The former implementation always
    # selected the owner, and moved it without asking either creature.
    row = candidate(combat, mid, "Painted Passage", at=(2, 4))
    assert row.destination.z == 0
    count = len(engine.events)
    prompts = settle(table, mid, row.candidate_id, {SUBJECT: passenger, CONSENT: consent})
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == CONSENT]
    assert len(asked) == 1 and asked[0]["context"]["reactor_id"] == passenger
    engine = reload(tmp_path, mid)
    after = engine.state.actors[passenger]
    assert after.position == (row.destination if consent == "accept" else before.position)
    assert after.movement_remaining_ft == before.movement_remaining_ft
    assert not engine.state.actors[aid].action_available
    movements = [e for e in engine.events[count:] if e.event_type == "MOVEMENT_COMMITTED"
                 and e.actor_id == passenger]
    if consent == "accept":
        assert movements and all(not e.payload.get("teleport") for e in movements)
        assert movements[-1].payload["destination"] == row.destination.model_dump(mode="json")
    else:
        assert not movements


def test_passage_route_checks_whole_passenger_body_not_only_anchor(tmp_path):
    from combat.ext.painting_forms import passage_path
    from combat.gate2_runtime_models import Position

    combat, table, mid, aid = crane_turn(tmp_path)
    engine = reload(tmp_path, mid)
    crane, passenger = engine.state.actors[aid], engine.state.actors[OWNER]
    destination = Position(x=2, y=7)
    assert passage_path(engine, crane, passenger, destination, 20)
    # A pure geometry negative control; no fabricated gameplay success state.
    engine.grid.blocked.add((2, 7))
    assert not passage_path(engine, crane, passenger, destination, 20)


def test_passage_three_dimensional_route_retains_requested_height(tmp_path):
    from combat.ext.painting_forms import passage_path
    from combat.gate2_runtime_models import Position

    combat, table, mid, aid = crane_turn(tmp_path)
    engine = reload(tmp_path, mid)
    crane, passenger = engine.state.actors[aid], engine.state.actors[OWNER]
    destination = Position(x=2, y=7, z=1)
    path = passage_path(engine, crane, passenger, destination, 20)
    assert path and path[0] == passenger.position and path[-1] == destination
    assert all(max(abs(a.x-b.x), abs(a.y-b.y), abs(a.z-b.z)) == 1 for a, b in zip(path, path[1:]))


@pytest.mark.parametrize("destination,accepted", [((6, 5), True), ((2, 4), False)])
def test_automatic_passenger_decides_from_own_position_not_shared_team(tmp_path, destination, accepted):
    combat, table, mid, aid = crane_turn(tmp_path)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    start = engine.state.actors[ALLY].position
    row = candidate(combat, mid, "Painted Passage", at=destination)
    prompts = settle(table, mid, row.candidate_id, {SUBJECT: ALLY})
    # Same friendly passenger in both cases: the native automatic decision
    # accepts its useful approach and refuses its retreat at full Hit Points.
    assert not any(p["context"]["reaction_source_id"] == CONSENT for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].position == (row.destination if accepted else start)


@pytest.mark.parametrize("boundary", ["sealed Formation boundary", "spatial lock boundary"])
def test_native_owner_map_boundary_is_validated_saved_and_consumed_after_reload(tmp_path, boundary):
    from combat.tabletop import TabletopMapStore, to_battlefield
    from tests.test_mgr_t14_sol_subpath_living_painting import FEATURE
    from tests.worker2_support import FOE, fixture

    root = tmp_path / "combat_maps"
    store = TabletopMapStore(root)
    saved = store.save({"map_id": "painted-boundaries", "display_name": "Painted boundary acceptance",
        "width_squares": 16, "height_squares": 12,
        "materials": [{"material": "terrain:" + boundary,
                       "cells": [[x, y] for x in range(16) for y in range(12)]}]})
    # The boundary is an owner declaration through the ordinary map producer,
    # not a condition or success receipt installed on a passenger.
    loaded = TabletopMapStore(root).get(saved["map_id"])
    assert loaded["materials"] == saved["materials"]
    combat, table, mid = fixture(tmp_path, [], cl=6, owner_features=[FEATURE],
        battlefield=to_battlefield(loaded), positions={OWNER: {"x": 3, "y": 6},
            ALLY: {"x": 4, "y": 5}, FOE: {"x": 12, "y": 9}})
    aid = create(combat, table, mid, "crane", "FORCE")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == aid
    assert not any(getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Painted Passage"
                   for c in engine.legal_candidates())
