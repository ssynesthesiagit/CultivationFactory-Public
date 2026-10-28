"""Merged material and virtual-wall routes stay reachable at the real table."""
import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto8f1_table_support import OWNER, reload_identical
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics import (
    AFTERIMAGE, GLIDE, MOBILITY, MULTIPLE, SHARK, commit, game, move_at,
)


@pytest.mark.parametrize("mode,x,z,cost", [("swim", 5, 0, 15), ("climb", 3, 1, 10)])
def test_material_and_air_routes_coexist_for_humans_and_ai_and_commit_reload(
    tmp_path, monkeypatch, mode, x, z, cost
):
    service, table, mid = game(
        tmp_path, [SHARK, GLIDE, "TAL_ATHLETICS_WALL_STUNT", "TAL_ATHLETICS_AIR_STUNT"],
        material="soil", height_ft=10,
    )
    # Explicit runtime dependency: the public exporter cannot infer this
    # dynamically loaded feature-block input from the Air Stunt talent ID.
    import json
    data = json.loads((ROOT / 'combat/rules/feature_blocks.d/mgr-t16-athletics4.json').read_text())
    assert data['features']['TAL_ATHLETICS_AIR_STUNT']['kind'] == 'air_stunt'
    engine = service._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    from combat.roof_movement import profile
    assert profile(engine, actor).virtual_wall
    assert not engine.grid.roof_surfaces
    before = engine.state.model_dump(mode="json")
    # These are the same native candidates offered to model/AI seats. Neither
    # capability may replace the other's routes, even on a map without roofs.
    for seat in ("MANUAL", "LOCAL_AUTO", "API_AUTO"):
        with monkeypatch.context() as patch:
            patch.setitem(engine.typed_control_modes, OWNER, seat)
            offers = engine._movement_candidates(actor)
            assert any(c.destination == Position(x=5, y=6)
                       and c.metadata.get("movement_mode") == "swim" for c in offers)
            assert any(c.destination == Position(x=3, y=6, z=1)
                       and c.metadata.get("movement_mode") == "climb" for c in offers)
    assert engine.state.model_dump(mode="json") == before

    move = move_at(table, mid, x, mode=mode, z=z)
    assert move["cost_ft"] == cost
    remaining = actor.movement_remaining_ft
    commit(table, mid, move)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].position == Position(x=x, y=6, z=z)
    assert fresh.state.actors[OWNER].movement_remaining_ft == remaining - cost
    receipt = next(e for e in reversed(fresh.events)
                   if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER)
    assert receipt.payload["movement_mode"] == mode
    assert receipt.payload["cost_ft"] == cost
    reload_identical(service, mid, tmp_path)


def test_afterimage_counts_only_selected_committed_steps_across_cold_reload(tmp_path):
    service, table, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOBILITY])
    for x, selected, earned, created in (
        (4, MOBILITY, 0, False),
        (8, AFTERIMAGE, 20, False),
        (9, AFTERIMAGE, 25, True),
    ):
        commit(table, mid, move_at(table, mid, x), lambda prompt:
               ["one"] if "motion_count" in prompt["context"]["reaction_source_id"] else [selected])
        fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
        actor = fresh.state.actors[OWNER]
        assert actor.turn_flags.get("athletics_afterimage_distance_ft", 0) == earned
        assert any(c.condition_id == "condition:typed.afterimage"
                   for c in actor.conditions.values()) is created
        reload_identical(service, mid, tmp_path)
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
