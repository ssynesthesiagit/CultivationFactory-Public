from __future__ import annotations

import copy
from pathlib import Path

from combat.gate5_service import CombatService


ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path):
    service = CombatService(ROOT, tmp_path / "UserData")
    catalog = service.catalog()
    modes = {
        row["runtime_entity_id"]: "LOCAL_AUTO"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    created = service.create_match(
        encounter_id=catalog["encounters"][0]["stable_id"],
        display_name="R6.6.8 E4 projection regression",
        match_seed="R668-E4-PROJECTION",
        control_modes=modes,
        maximum_rounds=20,
    )
    match_id = created["match_id"]
    session = service._load_session(match_id)
    raw_state = session.engine.state.model_dump(mode="json")
    metadata = service._metadata_readonly(match_id, raw_state)
    live_state = service._history_state_view(raw_state, metadata)
    return service, match_id, metadata, catalog, live_state


def _project(service, match_id, metadata, catalog, state, *, mode: str):
    boundary = None
    if mode == "HISTORY":
        boundary = {
            "boundary_index": 0,
            "record_sequence": None,
            "transaction_id": None,
            "step_label": "Synthetic exact historical boundary",
            "canonical_state_sha256": None,
        }
    return service.presenter.project(
        match_id=match_id,
        metadata=metadata,
        state=state,
        catalog=catalog,
        mode=mode,
        candidates=(),
        feed=(),
        boundary=boundary,
    ).model_dump(mode="json", by_alias=True)


def _actor(projection: dict, actor_id: str) -> dict:
    return next(row for row in projection["actors"] if row["entity_id"] == actor_id)


def _finding_codes(actor: dict) -> set[str]:
    return {row["code"] for row in actor["findings"]}


def test_inactive_overlap_is_legal_and_projects_identically_live_and_history(tmp_path: Path) -> None:
    service, match_id, metadata, catalog, original = _fixture(tmp_path)
    state = copy.deepcopy(original)
    active, inactive = state["actors"][0], state["actors"][1]
    active["active"] = True
    inactive["active"] = False
    inactive["position"] = dict(active["position"])

    live = _project(service, match_id, metadata, catalog, state, mode="LIVE")
    history = _project(service, match_id, metadata, catalog, state, mode="HISTORY")

    for projection in (live, history):
        active_row = _actor(projection, active["entity_id"])
        inactive_row = _actor(projection, inactive["entity_id"])
        assert active_row["footprint"]["collision_free"] is True
        assert inactive_row["footprint"]["collision_free"] is True
        assert "actor_footprint_collision" not in _finding_codes(active_row)
        assert "actor_footprint_collision" not in _finding_codes(inactive_row)
        assert inactive_row["footprint"]["occupied_cells"] == [inactive["position"]]

    assert _actor(live, inactive["entity_id"])["footprint"] == _actor(history, inactive["entity_id"])["footprint"]


def test_active_active_overlap_remains_an_error(tmp_path: Path) -> None:
    service, match_id, metadata, catalog, original = _fixture(tmp_path)
    state = copy.deepcopy(original)
    first, second = state["actors"][0], state["actors"][1]
    first["active"] = True
    second["active"] = True
    second["position"] = dict(first["position"])

    projection = _project(service, match_id, metadata, catalog, state, mode="LIVE")
    for actor in (first, second):
        row = _actor(projection, actor["entity_id"])
        assert row["footprint"]["collision_free"] is False
        assert "actor_footprint_collision" in _finding_codes(row)


def test_blocked_geometry_remains_an_error_for_inactive_actor(tmp_path: Path) -> None:
    service, match_id, metadata, catalog, original = _fixture(tmp_path)
    state = copy.deepcopy(original)
    battlefield = catalog["battlefields"][0]
    blocked = next(
        cell
        for region in battlefield["terrain_regions"]
        if region["terrain_type"] == "BLOCKED"
        for cell in region["cells"]
    )
    actor = state["actors"][0]
    actor["active"] = False
    actor["position"] = dict(blocked)

    projection = _project(service, match_id, metadata, catalog, state, mode="LIVE")
    row = _actor(projection, actor["entity_id"])
    assert row["footprint"]["in_bounds"] is True
    assert row["footprint"]["collision_free"] is False
    assert "actor_footprint_collision" in _finding_codes(row)


def test_out_of_bounds_remains_an_error_for_inactive_actor(tmp_path: Path) -> None:
    service, match_id, metadata, catalog, original = _fixture(tmp_path)
    state = copy.deepcopy(original)
    battlefield = catalog["battlefields"][0]
    actor = state["actors"][0]
    actor["active"] = False
    actor["position"] = {"x": battlefield["width_squares"], "y": 0}

    projection = _project(service, match_id, metadata, catalog, state, mode="HISTORY")
    row = _actor(projection, actor["entity_id"])
    assert row["footprint"]["in_bounds"] is False
    assert row["footprint"]["collision_free"] is False
    assert "actor_footprint_out_of_bounds" in _finding_codes(row)
    assert "actor_footprint_collision" in _finding_codes(row)


def test_existing_one_by_one_projection_remains_unchanged(tmp_path: Path) -> None:
    service, match_id, metadata, catalog, state = _fixture(tmp_path)
    projection = _project(service, match_id, metadata, catalog, state, mode="LIVE")
    for actor in projection["actors"]:
        footprint = actor["footprint"]
        assert footprint["width_cells"] == 1
        assert footprint["height_cells"] == 1
        assert footprint["occupied_cells"] == [actor["position"]]
        assert footprint["in_bounds"] is True
        assert footprint["collision_free"] is True
        assert footprint["mechanics_authoritative"] is True
