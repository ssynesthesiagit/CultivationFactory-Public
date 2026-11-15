"""Void Step remembers real personal perception, not hypothetical historical rays."""
import pytest

from combat import ext, zones
from combat.candidate_knowledge import query
from combat.canonical import canonical_sha256
from combat.ext import void_touched_cultivator as void
from combat.gate2_runtime_models import CandidateKind, Position, ZoneState
from tests.void_family_support import acquired, bundle
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

DESTINATION = Position(x=5, y=6)
DEPARTURE = Position(x=3, y=6)
SMOKE = "zone:test.void-step-initial-smoke"
DISPERSE = "action:test.void-step-disperse-smoke"


@ext.hook("match_initialize")
def _initial_smoke(engine):
    """A synthetic initial scene zone exists before anyone's first observation."""
    if DISPERSE not in engine.action_catalog:
        return
    zone = ZoneState(
        zone_id=SMOKE, source_definition_id=DISPERSE, owner_id=OWNER,
        center=Position(x=4, y=6), radius_cells=0,
        affected_cells=tuple(Position(x=4, y=y) for y in range(engine.grid.height)),
        concentration_link=False, duration_rounds=100, created_round=1,
        trigger_profile={"kind": "NOCTURNE"})
    engine.state.zones[SMOKE] = zone
    engine._append_event("ZONE_CREATED", DISPERSE, actor_id=OWNER,
                         payload={"zone": zone.model_dump(mode="json")})


@ext.effect("test_void_step_disperse_smoke")
def _disperse_smoke(ctx, row):
    zones.remove(ctx.engine, ctx.engine.state.zones[SMOKE], "test scene smoke dispersed")


def _scene(tmp_path, acquired, *, surveyed):
    service, project = acquired
    owner = bundle(service, project, OWNER)
    owner["actor_template"]["action_ids"].append(DISPERSE)
    owner["action_catalog"].append({
        "source_definition_id": DISPERSE, "display_name": "Disperse test smoke", "owner_id": OWNER,
        "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
        "parameters": {"typed": {"source": DISPERSE, "numbers": {}, "duration": {"kind": "instant"},
                                  "effects": [{"type": "test_void_step_disperse_smoke"}]}}})
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)

    def arena(document):
        # A second, unchanged sight screen will hide the destination from the
        # later position, after the initial smoke disappears.
        document["terrain_regions"] = [{
            "region_id": "test.later-sight-screen", "terrain_type": "SIGHT_BLOCKED",
            "movement_cost": 1, "description": "An ordinary opaque screen",
            "cells": [{"x": x, "y": 8} for x in range(5)]}]

    combat, table, mid = fixture(
        tmp_path, [], cl=3, owner_bundle=owner, battlefield_transform=arena,
        positions={OWNER: (DESTINATION if surveyed else DEPARTURE).model_dump(mode="json"),
                   ALLY: {"x": 12, "y": 10}, FOE: {"x": 14, "y": 12}},
        seed=f"VOID-PERCEPTION-{surveyed}")
    if surveyed:
        engine = reload(tmp_path, mid)
        walk = next(c for c in engine.legal_candidates()
                    if c.kind == CandidateKind.MOVE and c.destination == DEPARTURE)
        settle(table, mid, walk.candidate_id)
    return combat, table, mid


@pytest.mark.parametrize("surveyed", [False, True])
@pytest.mark.parametrize("personal_ai", [False, True])
def test_initial_smoke_admits_only_genuinely_surveyed_destinations(
        acquired, tmp_path, monkeypatch, surveyed, personal_ai):
    monkeypatch.setenv("CF_COMBAT_AI_SLICES_1_2", "1" if personal_ai else "0")
    combat, table, mid = _scene(tmp_path, acquired, surveyed=surveyed)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not engine._line_of_sight_actor_to_cell(actor, DESTINATION)
    assert engine.grid.line_of_sight(actor.position, DESTINATION)  # bare geometry is insufficient
    assert void.precisely_known(engine, actor, DESTINATION) is surveyed
    if personal_ai:
        # Both providers share the journal contract; neither may erase the other.
        assert any(OWNER in e.payload.get("personal_observations", {})
                   and void.KNOWN_CELLS in e.payload["personal_observations"] for e in engine.events)
        if surveyed:
            from combat.ext.ai_movement import latest_receipt

            assert latest_receipt(engine)[OWNER]["creatures"][FOE]["mode"] == "LAST_OBSERVED"

    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    engine = reload(tmp_path, mid)

    def landings():
        return {c.destination for c in engine.legal_candidates()
                if void.family_source(engine.action_catalog.get(c.source_definition_id)) == void.VOID_STEP}

    assert (DESTINATION in landings()) is surveyed
    with query(engine):
        assert (DESTINATION in landings()) is surveyed

    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    prompts = settle(table, mid, candidate(combat, mid, "Void Step").candidate_id,
                     picks={"choice:needle.teleport_destination":
                            ["cell:5,6" if surveyed else "cell:3,5"]})
    picker = next(p for p in prompts
                  if p["context"]["reaction_source_id"] == "choice:needle.teleport_destination")
    assert ("cell:5,6" in {o["id"] for o in picker["choice"]["options"]}) is surveyed
    assert ((5, 6) in {(c["x"], c["y"]) for c in picker["choice"]["map_pick"]["cells"]}) is surveyed
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.position == (DESTINATION if surveyed else Position(x=3, y=5))
    assert actor.resources["resource:core.qi"] == 28


def test_changed_geometry_does_not_retroactively_survey_old_positions(acquired, tmp_path):
    combat, table, mid = _scene(tmp_path, acquired, surveyed=False)
    engine = reload(tmp_path, mid)
    walk = next(c for c in engine.legal_candidates()
                if c.kind == CandidateKind.MOVE and c.destination == Position(x=3, y=10))
    settle(table, mid, walk.candidate_id)
    settle(table, mid, candidate(combat, mid, "Disperse test smoke").candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not engine.state.zones[SMOKE].active
    assert not engine._line_of_sight_actor_to_cell(actor, DESTINATION)
    assert engine.grid.line_of_sight(DEPARTURE, DESTINATION)
    assert not void.precisely_known(engine, actor, DESTINATION)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    engine = reload(tmp_path, mid)
    with query(engine):
        assert DESTINATION not in {c.destination for c in engine.legal_candidates()
                                   if void.family_source(engine.action_catalog.get(c.source_definition_id)) == void.VOID_STEP}
