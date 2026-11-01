"""Insight rules text is request-scoped, never shared service-instance state.

The app builds one ``CharacterSheetService`` for the whole process
(``app/api.py``), and ``GET /api/characters/<id>/sheet`` and the
``/api/characters`` sweep are sync ``def`` handlers, so FastAPI runs them on the
threadpool together.  ``_insight_text_lookup`` lived on that shared instance, so
a concurrent non-compact ``sheet()`` for another project rewrote the dict
between population (from the sealed snapshot) and consumption (the insight
surface overlay), and the live page lost its Insight rules text.

This test re-enters ``sheet(OTHER)`` at the exact consumption point and asserts
the outer sheet still carries its own Insight text.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tests.test_character_sheet_complete_character as sheet_fixture
from character_sheet.service import CharacterSheetService

REFERENCE = sheet_fixture.PROJECT_ID
OTHER = "project.other-character"
LEDGER = "Character_Master_Ledger.json"
INSIGHT_ID = "insight.reference.locked"
# Comfortably above CharacterSheetService._RULES_TEXT_MIN_CHARS (200).
LOCKED_TEXT = "The locked printed Insight text carries the full rules paragraph. " * 5


def _locked_insight_row() -> dict:
    return {
        "record_id": INSIGHT_ID,
        "record_hash": "a" * 64,
        "display_name": "Rooted Stillness Insight",
        "one_line_description": "A one-line summary.",
        "full_description": LOCKED_TEXT,
        "full_description_source": "locked_typed_catalog_record",
    }


def _sealed_snapshot(*, insights: list[dict]) -> dict:
    """The sealed owner snapshot the sheet indexes its Insight lookup from."""

    return {
        "sheet_id": "sheet.request-scope",
        "identity": {"display_name": "Request Scope Fixture"},
        "readiness": {"advancement": "ADVANCEMENT_READY", "character_sheet": "CHARACTER_SHEET_READY"},
        "selected_record_sections": {"insights": insights},
    }


def test_concurrent_sheet_reentry_keeps_the_reference_sheets_insight_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(LOCKED_TEXT) >= CharacterSheetService._RULES_TEXT_MIN_CHARS
    service = sheet_fixture._service(tmp_path)
    service.db.migrate()
    sheet_fixture._sheet_stubs(service)

    # A candidate archive and an advancement-ready ledger are what make sheet()
    # load the sealed snapshot the Insight lookup is indexed from.
    ledger = {"character": {}, "readiness": {"advancement": "ADVANCEMENT_READY"}}
    service._compiled_artifacts = lambda _project_id: (
        {LEDGER: ledger},
        {"status": "READY", "projection_id": sheet_fixture.PROJECTION_ID, "eligible_for_command5": False},
    )
    snapshots = {
        REFERENCE: _sealed_snapshot(insights=[_locked_insight_row()]),
        # The concurrent re-entry is a project with no locked Insight rows, like
        # the /api/characters sweep sheet() that clobbered the shared dict.
        OTHER: _sealed_snapshot(insights=[]),
    }
    service._cached_snapshot = lambda project_id, **_kwargs: (snapshots[project_id], {"sheet_id": "sheet.request-scope"})

    # The candidate surface declares the insight with no printed text, which is
    # what the overlay fills in.
    original_surface_document = sheet_fixture._surface_document

    def surface_document_with_short_insight(member: str, *, display_name: str) -> dict:
        document = original_surface_document(member, display_name=display_name)
        if member == LEDGER:
            document = {
                **document,
                "schema_version": "TianxiaFoundry.CharacterMasterLedger.v1",
                "insights": [{"insight_id": INSIGHT_ID, "name": "Rooted Stillness Insight", "acquisition_cl": 3}],
            }
        return document

    monkeypatch.setattr(sheet_fixture, "_surface_document", surface_document_with_short_insight)
    sheet_fixture._write_candidate(service.db.settings.data_dir)

    overlay = CharacterSheetService._with_authenticated_insight_text
    state = {"reentered": 0, "inside": False}

    def overlay_during_a_concurrent_sheet(self, surfaces, *args, **kwargs):
        # A concurrent non-compact sheet() for another project on this shared
        # instance, landing at the consumption point.  compact responses skip
        # the indexing step, so the leak needs a non-compact re-entry.
        if not state["inside"]:
            state["inside"] = True
            state["reentered"] += 1
            try:
                self.sheet(OTHER)
            finally:
                state["inside"] = False
        return overlay(self, surfaces, *args, **kwargs)

    monkeypatch.setattr(
        CharacterSheetService, "_with_authenticated_insight_text", overlay_during_a_concurrent_sheet
    )

    result = service.sheet(REFERENCE)

    assert state["reentered"] == 1
    row = result["complete_character"]["surfaces"]["insights"]["data"][LEDGER]["insights"][0]
    assert row.get("full_description") == LOCKED_TEXT.strip()
    assert row.get("full_description_source") == "locked_typed_catalog_record"
    # No path may read stale state from the shared instance.
    assert not hasattr(service, "_insight_text_lookup")
