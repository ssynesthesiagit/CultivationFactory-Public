from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.core import Settings
from combat.footprint_registry import ACTOR_FOOTPRINTS, resolve_actor_footprint
from combat.footprints import (
    ActorFootprintDefinition,
    STANDARD_ACTOR_FOOTPRINT,
    project_actor_footprint,
)
from combat.gate2_runtime_models import Position


ROOT = Path(__file__).resolve().parents[1]


def test_current_compiled_actor_footprint_registry_is_exact_and_one_cell() -> None:
    assert set(ACTOR_FOOTPRINTS) == {"an_eui_early_book1_cl5", "lee_jia_early_book1_cl5", "ling_qi_early_outer_sect_cl5", "bai_meizhen_early_outer_sect_cl5", "bai_cui"}
    for actor_id, definition in ACTOR_FOOTPRINTS.items():
        assert definition.schema_name == "TianxiaActorFootprint.v1"
        assert definition.footprint_id == f"footprint:{actor_id}.1x1"
        assert definition.anchor_semantics == "TOP_LEFT"
        assert definition.is_single_cell is True
        assert definition.occupied_cells(Position(x=7, y=9)) == ((7, 9),)


def test_legacy_missing_actor_resolves_only_to_bounded_single_cell_compatibility() -> None:
    definition, mode = resolve_actor_footprint("legacy_actor_not_in_current_catalog")
    assert mode == "LEGACY_SINGLE_CELL"
    assert definition == STANDARD_ACTOR_FOOTPRINT
    assert definition.is_single_cell


def test_footprint_shape_validation_fails_closed() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ActorFootprintDefinition(
            footprint_id="footprint:bad.duplicate",
            width_cells=1,
            height_cells=1,
            occupied_relative_cells=(Position(x=0, y=0), Position(x=0, y=0)),
            source_definition_id="test:bad",
        )
    with pytest.raises(ValidationError, match="top-left anchor"):
        ActorFootprintDefinition(
            footprint_id="footprint:bad.anchor",
            width_cells=2,
            height_cells=1,
            occupied_relative_cells=(Position(x=1, y=0),),
            source_definition_id="test:bad",
        )
    with pytest.raises(ValidationError, match="orthogonally connected"):
        ActorFootprintDefinition(
            footprint_id="footprint:bad.disconnected",
            width_cells=3,
            height_cells=1,
            occupied_relative_cells=(Position(x=0, y=0), Position(x=2, y=0)),
            source_definition_id="test:bad",
        )


def test_projection_maps_anchor_to_exact_occupied_cells_and_reports_bounds_collision() -> None:
    definition = ActorFootprintDefinition.rectangle(
        2,
        2,
        footprint_id="footprint:test.2x2",
        source_definition_id="test:2x2",
    )
    good = project_actor_footprint(
        definition,
        Position(x=3, y=4),
        grid_width=20,
        grid_height=14,
        mechanics_authoritative=False,
        compatibility_mode="TYPED",
    )
    assert [(cell.x, cell.y) for cell in good.occupied_cells] == [(3, 4), (3, 5), (4, 4), (4, 5)]
    assert good.in_bounds is True
    assert good.collision_free is True
    assert good.mechanics_authoritative is False

    blocked = project_actor_footprint(
        definition,
        Position(x=3, y=4),
        grid_width=20,
        grid_height=14,
        blocked_cells={(4, 5)},
        mechanics_authoritative=False,
        compatibility_mode="TYPED",
    )
    assert blocked.in_bounds is True
    assert blocked.collision_free is False

    edge = project_actor_footprint(
        definition,
        Position(x=19, y=13),
        grid_width=20,
        grid_height=14,
        mechanics_authoritative=False,
        compatibility_mode="TYPED",
    )
    assert edge.in_bounds is False
    assert edge.collision_free is False


def test_live_combat_sheet_projects_exact_authoritative_one_cell_footprints_without_state_migration(tmp_path: Path) -> None:
    settings = Settings.from_env(ROOT, tmp_path / "UserData")
    with TestClient(create_app(settings)) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/combat/catalog").json()
        created = client.post(
            "/api/combat/matches",
            headers=headers,
            json={
                "encounter_id": catalog["encounters"][0]["stable_id"],
                "display_name": "Footprint E1",
                "match_seed": "R668-FOOTPRINT-E1",
                "control_modes": {},
                "maximum_rounds": 20,
            },
        )
        assert created.status_code == 200, created.text
        match_id = created.json()["match_id"]
        raw_state = client.get(f"/api/combat/matches/{match_id}").json()["state"]
        presentation = client.get(f"/api/combat/matches/{match_id}/presentation").json()

        # E1 adds a read-only compilation/projection seam and deliberately does
        # not reinterpret or migrate Gate 3 match-state/journal payloads.
        assert all("footprint" not in actor for actor in raw_state["actors"])
        for actor in presentation["actors"]:
            footprint = actor["footprint"]
            assert footprint["schema"] == "TianxiaActorFootprintProjection.v1"
            assert footprint["anchor_x"] == actor["position"]["x"]
            assert footprint["anchor_y"] == actor["position"]["y"]
            assert footprint["width_cells"] == footprint["height_cells"] == 1
            assert footprint["occupied_cells"] == [actor["position"]]
            assert footprint["in_bounds"] is True
            assert footprint["collision_free"] is True
            assert footprint["mechanics_authoritative"] is True
            assert footprint["compatibility_mode"] == "TYPED"


def test_browser_consumes_typed_footprint_projection_without_visual_inference() -> None:
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    assert "function combatActorFootprint(actor)" in script
    assert "const footprint = combatActorFootprint(actor)" in script
    assert "token.dataset.footprintWidth" in script
    assert "token.dataset.footprintHeight" in script
    assert "footprint.mechanics_authoritative" in script
    assert "footprint.occupied_cells" in script
    assert 'token.classList.add("unsupported-footprint")' in script
    assert "token.disabled = true" in script
    assert ".combat-token.unsupported-footprint" in css
    assert ".combat-token-layer" in css
