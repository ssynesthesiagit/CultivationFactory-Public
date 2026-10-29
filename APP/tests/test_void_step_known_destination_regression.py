"""Known, occluded Void Step landings stay reachable through both real menus.

Knowledge comes from the traveller's committed walk, not patched sight/knowledge
or another creature's observations. Stores and acquisition evidence are synthetic.
"""
import pytest

from combat.candidate_knowledge import query
from combat.ext import void_touched_cultivator as void
from combat.gate2_runtime_models import CandidateKind, Position
from tests.void_family_support import acquired, bundle
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

DESTINATION = Position(x=5, y=6)
DEPARTURE = Position(x=3, y=6)


def _wall(arena):
    arena["terrain_regions"] = [{
        "region_id": "test.ordinary-wall", "terrain_type": "BLOCKED", "movement_cost": 0,
        "description": "Five-foot-thick ordinary stone wall",
        "cells": [{"x": 4, "y": y} for y in range(5, 8)],
    }]


def _table(tmp_path, acquired, *, surveyed=True):
    service, project = acquired
    combat, table, mid = fixture(
        tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
        positions={OWNER: (DESTINATION if surveyed else DEPARTURE).model_dump(mode="json"),
                   ALLY: {"x": 15, "y": 10}, FOE: {"x": 15, "y": 12}},
        battlefield_transform=_wall, seed="VOID-STEP-KNOWN-DESTINATION")
    if surveyed:
        # Walk around the wall via the native table, leaving a persisted record
        # that this traveller really knew the destination before losing sight.
        engine = reload(tmp_path, mid)
        walk = next(c for c in engine.legal_candidates()
                    if c.kind == CandidateKind.MOVE and c.destination == DEPARTURE)
        settle(table, mid, walk.candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position == DEPARTURE
    assert not engine._line_of_sight_actor_to_cell(actor, DESTINATION)
    assert void.precisely_known(engine, actor, DESTINATION) is surveyed
    # An ally can see the far side, but that must not grant the traveller knowledge.
    assert engine._line_of_sight_actor_to_cell(engine.state.actors[ALLY], DESTINATION)
    return combat, table, mid


def test_table_picker_offers_and_commits_a_surveyed_square_behind_ordinary_wall(acquired, tmp_path):
    combat, table, mid = _table(tmp_path, acquired)
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if g["label"] == "Void Step")
    assert group["destination_choice"] is True
    prompts = settle(
        table, mid, candidate(combat, mid, "Void Step").candidate_id,
        picks={"choice:needle.teleport_destination": ["cell:5,6"]})
    picker = next(p for p in prompts
                  if p["context"]["reaction_source_id"] == "choice:needle.teleport_destination")
    assert "cell:5,6" in {o["id"] for o in picker["choice"]["options"]}
    assert (5, 6) in {(c["x"], c["y"]) for c in picker["choice"]["map_pick"]["cells"]}
    prompt = picker["context"]["choice_trigger"]["prompt"]
    assert "Void Step" in prompt and "destination rules" in prompt
    assert "square it can see" not in prompt
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.position == DESTINATION
    assert actor.resources["resource:core.qi"] == 28
    assert not actor.bonus_action_available


@pytest.mark.parametrize("surveyed", [False, True])
def test_ai_and_canonical_candidates_use_only_the_travellers_known_landings(acquired, tmp_path, surveyed):
    combat, _, mid = _table(tmp_path, acquired, surveyed=surveyed)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    engine = reload(tmp_path, mid)

    def landings():
        return {c.destination for c in engine.legal_candidates()
                if void.family_source(engine.action_catalog.get(c.source_definition_id)) == void.VOID_STEP}

    canonical = landings()
    with query(engine):
        observed = landings()
    assert (DESTINATION in canonical) is surveyed
    assert (DESTINATION in observed) is surveyed
    assert Position(x=4, y=6) not in canonical | observed  # solid wall, never a landing
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 30
