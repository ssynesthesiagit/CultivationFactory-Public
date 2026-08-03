from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate4_context import build_decision_context
from combat.gate4_persistence import Gate4Persistence, _read_jsonl
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService

ROOT = Path(__file__).resolve().parents[1]


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".writer.lock"
    }


def _create_service_match(tmp_path: Path, *, seed: str = "R667-PRESENTATION-ARCHITECTURE"):
    service = CombatService(ROOT, tmp_path / "UserData")
    catalog = service.catalog()
    modes = {
        row["runtime_entity_id"]: "LOCAL_AUTO"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    created = service.create_match(
        encounter_id=catalog["encounters"][0]["stable_id"],
        display_name="Combat Sheet architecture test",
        match_seed=seed,
        control_modes=modes,
        maximum_rounds=20,
    )
    return service, created["match_id"]


def _actor(projection: dict, actor_id: str) -> dict:
    return next(row for row in projection["actors"] if row["entity_id"] == actor_id)


def test_plan_sidecar_matches_uploaded_architecture_amendment() -> None:
    plan = Path("/mnt/data/R6_6_7_COMBAT_SCREEN_COMBAT_SHEET_ARCHITECTURE_PLAN_R2-1.md")
    sidecar = Path("/mnt/data/R6_6_7_COMBAT_SCREEN_COMBAT_SHEET_ARCHITECTURE_PLAN_R2.md.sha256")
    if not plan.is_file() or not sidecar.is_file():
        pytest.skip("uploaded architecture amendment is not mounted in this test environment")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(plan.read_bytes()).hexdigest() == expected


def test_live_projection_uses_exact_ids_and_one_normalized_combat_sheet_shape(tmp_path: Path) -> None:
    service, match_id = _create_service_match(tmp_path)
    projection = service.presentation(match_id)

    assert projection["schema"] == "TianxiaFactoryCombatPresentation.v1"
    assert projection["mode"] == "LIVE"
    assert len(projection["actors"]) == 5
    assert set(projection["initiative_order"]).issubset({row["entity_id"] for row in projection["actors"]})
    assert len({row["entity_id"] for row in projection["actors"]}) == 5
    assert projection["battlefield"]["mechanical_source_sha256"] == hashlib.sha256(
        (ROOT / "combat_gate1/generated/Battlefield.json").read_bytes()
    ).hexdigest()

    primary = [row for row in projection["actors"] if row["primary_combatant"]]
    assert len(primary) == 4
    for row in primary:
        assert row["sheet_link"]["available"] is True
        assert row["sheet_link"]["route_kind"] == "CHARACTER_AUTHORITY_DETAILS"
        assert row["sheet_link"]["character_sheet_identity"] == f"character_mapping:{row['entity_id']}"
        authority = service.character_authority(row["sheet_link"]["character_sheet_identity"])
        assert authority["source_character_id"] == row["entity_id"]
        assert authority["source_revision_sha256"] == row["source_character_revision_sha256"]
        assert row["action_definitions"]
        assert len(row["action_definitions"]) == len(row["action_availability"])

    cui = _actor(projection, "bai_cui")
    assert cui["owner_id"] == "bai_meizhen_early_outer_sect_cl5"
    assert cui["sheet_link"]["available"] is False
    assert cui["sheet_link"]["finding"] == "companion_has_no_independent_character_sheet"


def test_projection_is_read_only_for_legacy_match_without_factory_metadata(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate4Persistence(ROOT, userdata)
    session = persistence.create_match(match_seed="R667-READONLY-PRESENTATION", maximum_rounds=20)
    service = CombatService(ROOT, userdata)
    metadata_path = session.store.match_dir / "FactoryIntegration.json"
    assert not metadata_path.exists()
    before = _tree_hashes(session.store.match_dir)
    projection = service.presentation(session.match_id)
    after = _tree_hashes(session.store.match_dir)

    assert projection["mode"] == "LIVE"
    assert before == after
    assert not metadata_path.exists()


def test_historical_projection_never_leaks_live_values(tmp_path: Path) -> None:
    service, match_id = _create_service_match(tmp_path, seed="R667-HISTORY-BOUNDARY")
    genesis = service.presentation(match_id, boundary_index=0)
    committed = service.local_step(match_id)
    assert committed["status"] == "COMMITTED"
    live = service.presentation(match_id)
    historical = service.presentation(match_id, boundary_index=0)

    assert historical["mode"] == "HISTORY"
    assert historical["boundary"]["boundary_index"] == 0
    assert historical["state_version"] == genesis["state_version"] == 0
    assert live["state_version"] == 1
    assert historical["actors"] == genesis["actors"]
    assert historical["zones"] == genesis["zones"]
    assert historical["feed"] == genesis["feed"]
    assert all(
        "historical_mode" in availability["disabled_reason_codes"]
        for actor in historical["actors"]
        for availability in actor["action_availability"]
    )


def test_background_and_token_visuals_cannot_change_mechanics(tmp_path: Path) -> None:
    service, match_id = _create_service_match(tmp_path, seed="R667-VISUAL-MECHANICAL-ISOLATION")
    before = service.presentation(match_id)
    metadata_path = service._metadata_path(match_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["visual_assets"]["map"] = {
        "asset_id": "battlemap:presentation-only:test",
        "public_url": "/presentation-only/background.png",
        "source": "test",
        "mechanical_authority": False,
    }
    metadata["visual_assets"]["tokens"]["an_eui_early_book1_cl5"] = {
        "asset_id": "token:presentation-only:test",
        "public_url": "/presentation-only/token.png",
        "source": "test",
        "sha256": "0" * 64,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    after = service.presentation(match_id)

    assert before["battlefield"] == after["battlefield"]
    for actor_id in before["initiative_order"]:
        left = _actor(before, actor_id)
        right = _actor(after, actor_id)
        for field in (
            "entity_id", "position", "hit_points", "defenses", "speed_ft",
            "movement_remaining_ft", "turn_state", "resources", "conditions",
            "action_definitions", "action_availability", "features",
        ):
            assert left[field] == right[field]
    assert before["map_visual"] != after["map_visual"]
    assert _actor(before, "an_eui_early_book1_cl5")["visual"] != _actor(after, "an_eui_early_book1_cl5")["visual"]


def test_typed_geometry_drives_cover_independently_of_overlay_visibility(tmp_path: Path) -> None:
    service, match_id = _create_service_match(tmp_path, seed="R667-COVER-AUTHORITY")
    projection = service.presentation(match_id)
    grid = SquareGrid.load(ROOT / "combat_gate1/generated/Battlefield.json")
    projected_cover = {(row["x"], row["y"]) for row in projection["battlefield"]["cover_cells"]}
    assert projected_cover == grid.cover

    covered_pairs = []
    for sy in range(grid.height):
        for sx in range(grid.width):
            for ey in range(grid.height):
                for ex in range(grid.width):
                    start, end = Position(x=sx, y=sy), Position(x=ex, y=ey)
                    if start != end and grid.cover_bonus(start, end) > 0:
                        covered_pairs.append((start, end))
                        break
                if covered_pairs:
                    break
            if covered_pairs:
                break
        if covered_pairs:
            break
    assert covered_pairs, "accepted battlefield must expose at least one mechanically covered ray"
    start, end = covered_pairs[0]
    assert grid.cover_bonus(start, end) == 2
    assert projection["map_visual"].get("mechanical_authority") is not True


def test_manual_adapter_uses_same_validator_journal_and_replay_path(tmp_path: Path) -> None:
    persistence = Gate4Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="R667-MANUAL-SEAM", maximum_rounds=20)
    policy_library = PolicyLibrary(ROOT)
    active_id = session.engine.state.current_actor_id
    policy, _ = policy_library.for_actor(active_id)
    context = build_decision_context(session.engine, policy)
    selected = context.legal_candidates[0]
    manual = ManualControllerAdapter(lambda supplied: (selected.candidate_id, ()))
    choice = manual.choose_primary_action(context)

    assert choice.intent.candidate_id == selected.candidate_id
    assert choice.intent.actor_id == selected.actor_id
    assert choice.intent.state_version == 0
    session.execute_controller_choice(choice, controller=manual, policy_library=policy_library)

    assert session.engine.state.state_version == 1
    rows = _read_jsonl(session.controller_journal_path)
    assert [row["record_type"] for row in rows] == ["CONTROLLER_PREPARE", "CONTROLLER_COMMIT"]
    assert rows[0]["primary_decision_record"]["controller_id"] == manual.controller_id
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["state"]["state_version"] == 1

    next_active = session.engine.state.current_actor_id
    next_policy, _ = policy_library.for_actor(next_active)
    next_context = build_decision_context(session.engine, next_policy)
    stale = ManualControllerAdapter(lambda supplied: (selected.candidate_id, ()))
    with pytest.raises(ValueError, match="GATE2_STALE_OR_ILLEGAL_CANDIDATE"):
        stale.choose_primary_action(next_context)


def test_presentation_and_character_authority_api_routes(tmp_path: Path) -> None:
    settings = Settings.from_env(ROOT, tmp_path / "UserData")
    with TestClient(create_app(settings)) as client:
        token = client.get("/api/session").json()["token"]
        catalog = client.get("/api/combat/catalog").json()
        modes = {
            row["runtime_entity_id"]: "LOCAL_AUTO"
            for row in catalog["projections"]
            if row.get("primary_combatant")
        }
        created = client.post(
            "/api/combat/matches",
            headers={"x-foundry-token": token},
            json={
                "encounter_id": catalog["encounters"][0]["stable_id"],
                "display_name": "API presentation test",
                "match_seed": "R667-PRESENTATION-API",
                "control_modes": modes,
                "maximum_rounds": 20,
            },
        )
        assert created.status_code == 200, created.text
        match_id = created.json()["match_id"]
        projection = client.get(f"/api/combat/matches/{match_id}/presentation")
        assert projection.status_code == 200, projection.text
        actor = next(row for row in projection.json()["actors"] if row["sheet_link"]["available"])
        authority = client.get(actor["sheet_link"]["route"])
        assert authority.status_code == 200, authority.text
        assert authority.json()["source_character_id"] == actor["entity_id"]
        historical = client.get(f"/api/combat/matches/{match_id}/presentation?boundary=0")
        assert historical.status_code == 200
        assert historical.json()["mode"] == "HISTORY"
