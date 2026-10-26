"""Rope attachment must not mistake absent seat metadata for AI consent."""

import pytest

from combat import ext
from combat.ext.teleport_steps import destinations
from combat.gate2_runtime_models import ActionIntent
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, ROPE, ROPE_SWING, SWING, engine_of, find, play, table_fight,
)
from tests.test_a2_rope_swing_reattach import KEEP


def headless_engine(tmp_path):
    combat, table, mid = table_fight(
        tmp_path, [ROPE_SWING], kit=ROPE, map_doc=KEEP,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 5}},
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"})
    engine = engine_of(combat, mid)
    assert getattr(engine, "_gate4_reaction_provider", None) is None
    actor = engine.state.actors[FIGHTER]
    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == FIGHTER
                  and (row.parameters.get("typed") or {}).get("source") == ROPE_SWING
                  and str(row.economy) == "BONUS_ACTION")
    reach = max(engine.grid.width, engine.grid.height,
                engine.grid.altitude_ceiling_z + 1) * engine.grid.square_size_ft
    anchors = [cell for cell in destinations(engine, actor, reach, action=action)
               if cell.z > actor.position.z]
    assert anchors, "the refusal must be about missing control, not missing anchors"
    return combat, table, mid, engine, anchors


def attach(engine):
    candidate = next(row for row in engine.legal_candidates()
                     if row.actor_id == FIGHTER
                     and row.source_definition_id in engine.action_catalog
                     and (engine.action_catalog[row.source_definition_id].parameters.get("typed") or {}).get("source") == ROPE_SWING)
    engine.execute_intent(ActionIntent(
        intent_id="headless-rope-attach", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=FIGHTER, target_ids=candidate.target_ids, destination=candidate.destination))


@pytest.mark.parametrize("missing", ["attribute", "empty", "other_actor"])
def test_headless_attach_without_recorded_control_leaves_rope_unchanged(tmp_path, missing):
    _, _, _, engine, _ = headless_engine(tmp_path)
    if missing == "attribute":
        del engine.typed_control_modes
    else:
        engine.typed_control_modes = {"empty": {},
                                      "other_actor": {FOE: "MANUAL"}}[missing]
    attach(engine)
    actor = engine.state.actors[FIGHTER]
    assert not any(row.condition_id == SWING for row in actor.conditions.values())
    assert {"flight_suspended": 1} not in ext.run_strict("flight", engine, actor)


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO"])
def test_recorded_ai_can_attach_without_transport(tmp_path, mode):
    _, _, _, engine, anchors = headless_engine(tmp_path)
    engine.typed_control_modes[FIGHTER] = mode
    actor = engine.state.actors[FIGHTER]
    nearest = min(anchors, key=lambda cell: (
        engine.grid.distance_ft(actor.position, cell), cell.z, cell.y, cell.x))
    attach(engine)
    swing = next(row for row in actor.conditions.values() if row.condition_id == SWING)
    assert swing.data["anchor"] == [nearest.x, nearest.y, nearest.z]
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, actor)


def test_recorded_player_without_transport_does_not_choose_an_anchor(tmp_path):
    _, _, _, engine, _ = headless_engine(tmp_path)
    attach(engine)
    assert not any(row.condition_id == SWING
                   for row in engine.state.actors[FIGHTER].conditions.values())


def test_player_attach_still_prompts_and_persists_after_cold_reload(tmp_path):
    combat, table, mid, _, _ = headless_engine(tmp_path)
    result, prompts = play(table, mid, find(table, mid, ROPE_SWING))
    assert result["status"] == "COMMITTED"
    assert len(prompts) == 1
    assert prompts[0]["context"]["reaction_source_id"] == "choice:needle.rope_anchor"
    actor = engine_of(combat, mid).state.actors[FIGHTER]
    swing = next(row for row in actor.conditions.values() if row.condition_id == SWING)
    assert len(swing.data["anchor"]) == 3
    assert all(type(value) is int for value in swing.data["anchor"])
