"""Recorded Arts are request-scoped, never shared service-instance state.

The app builds one ``CharacterSheetService`` for the whole process
(``app/api.py``), and ``/api/characters`` (``list_characters``) runs
``sheet(compact=True)`` for every project on that same instance.  Both endpoints are sync ``def``, so
FastAPI runs them on the threadpool and the library sweep overlaps a real
page's ``/api/characters/<id>/sheet`` request.

The reference character ("Grey Lantern Ascetic", 33 Recorded Arts) rendered its
Manuals tab with the 11 Manual cards and no Recorded Arts section because the
sweep's (empty) row list overwrote the reference request's rows between
population and consumption.  This test re-enters ``sheet()`` for another
project at the exact consumption point and asserts the outer sheet still
carries its own arts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.test_character_sheet_complete_character as sheet_fixture
from character_creation.constructed_arts.records import RECORDED_ART_PACK_ID
from character_sheet.service import CharacterSheetService

REFERENCE = sheet_fixture.PROJECT_ID
OTHER = "project.other-character"
MODEL_V1 = "Tianxia_GM_Character_Model_v1.json"


def _reference_arts() -> list[dict]:
    return [
        {
            "record_id": f"art.reference.{index}",
            "parent_manual_record_id": f"manual.reference.{index}",
            "display_name": f"Root-Seizing Clinch {index}",
            "associated_sphere_record_ids": ["tianxia.sphere.wrestling"],
            "learning_dc": 18 + index,
        }
        for index in range(3)
    ]


def _insert_project(service: CharacterSheetService, project_id: str) -> None:
    with service.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,quality_target,
               project_json,compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id, "Request scope fixture", "draft", 0,
                "2026-09-13T00:00:00Z", "2026-09-13T00:00:00Z",
                "1", "1", "1", "rival/boss", "{}",
                "DRAFT_COMPATIBILITY_PROJECTION_NOT_FACTORY_COMPILABLE",
                "NOT_IMPLEMENTED_PHASE2R", "NOT_RUN_NO_COMPILED_CHARACTER",
            ),
        )


def _insert_recorded_art(service: CharacterSheetService, project_id: str, arts: list[dict]) -> None:
    with service.db.transaction() as conn:
        for art in arts:
            record = {
                "record_id": art["record_id"],
                "content_type": "recorded_art",
                "display_name": art["display_name"],
                "content_binding": {"pack_id": RECORDED_ART_PACK_ID},
                "compatibility": {
                    "factory": {"constructed_art": {"bundle": {"recorded_arts": [dict(art)]}}},
                },
            }
            conn.execute(
                """INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json)
                   VALUES(?,?,?,?,?,?)""",
                (project_id, art["record_id"], RECORDED_ART_PACK_ID, "1", "0" * 64, json.dumps(record)),
            )


def test_library_sweep_reentry_keeps_the_reference_sheets_recorded_arts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = sheet_fixture._service(tmp_path)
    service.db.migrate()
    sheet_fixture._sheet_stubs(service)
    for project_id in (REFERENCE, OTHER):
        _insert_project(service, project_id)
    arts = _reference_arts()
    _insert_recorded_art(service, REFERENCE, arts)

    # The candidate archive declares the manuals surface with no arts, which is
    # what the overlay fills in.
    original_surface_document = sheet_fixture._surface_document

    def surface_document_with_empty_arts(member: str, *, display_name: str) -> dict:
        document = original_surface_document(member, display_name=display_name)
        if member == MODEL_V1:
            document = {**document, "recorded_arts": []}
        return document

    monkeypatch.setattr(sheet_fixture, "_surface_document", surface_document_with_empty_arts)
    sheet_fixture._write_candidate(service.db.settings.data_dir)

    overlay = CharacterSheetService._with_authenticated_recorded_arts
    state = {"sweeping": False}

    def overlay_during_a_library_sweep(self, surfaces, *args, **kwargs):
        # The /api/characters sweep (list_characters) runs sheet(compact=True) for another
        # project on this shared instance at the consumption point.
        if not state["sweeping"]:
            state["sweeping"] = True
            try:
                self.sheet(OTHER, compact=True)
            finally:
                state["sweeping"] = False
        return overlay(self, surfaces, *args, **kwargs)

    monkeypatch.setattr(
        CharacterSheetService, "_with_authenticated_recorded_arts", overlay_during_a_library_sweep
    )

    result = service.sheet(REFERENCE)

    document = result["complete_character"]["surfaces"]["manuals_recorded_arts"]["data"][MODEL_V1]
    assert [(row["record_id"], row["learning_dc"]) for row in document["recorded_arts"]] == [
        (art["record_id"], art["learning_dc"]) for art in arts
    ]
    # No path may read stale rows from the shared instance.
    assert not hasattr(service, "_recorded_art_rows")
