"""Command 5 display merge must read the Foundation registry source shape.

The non-sphere Foundation mechanics registry seals a Foundation's locator as
``{"artifact", "artifact_sha256", "section_number", "section_sha256"}`` and the
projector carries that object onto the Character Master Ledger row.  The
owner-sheet display card maps the same locator to ``{"path", "anchor",
"sha256"}`` with the canonical ``foundation:<id>`` anchor
(``non_sphere_authority.service``).  Command 5 compares the two rows before
merging display fields; it must compare them on the same identity instead of
reading three empty fields from the registry shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core import FoundryError
from factory_authoring.command5_profile import CharacterGMCommand5Profile
from tests.test_future_pipeline_repairs import _command4_workspace, _command5_selected_method_foundation_fixture

ARTIFACT = "Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md"
ARTIFACT_SHA256 = "c" * 64
FOUNDATION_ID = "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
DISPLAY_SOURCE = {"path": ARTIFACT, "anchor": f"foundation:{FOUNDATION_ID}", "sha256": ARTIFACT_SHA256}
REGISTRY_SOURCE = {"artifact": ARTIFACT, "artifact_sha256": ARTIFACT_SHA256, "section_number": 6, "section_sha256": "d" * 64}


def _registry_fixture() -> tuple[dict, dict]:
    sheet_response, master = _command5_selected_method_foundation_fixture()
    snapshot = sheet_response["owner_character_sheet"]
    snapshot["foundation"].update({
        "record_id": FOUNDATION_ID,
        "source": dict(DISPLAY_SOURCE),
        "source_path": ARTIFACT,
        "source_anchor": DISPLAY_SOURCE["anchor"],
        "source_hash": ARTIFACT_SHA256,
    })
    master["foundation"].update({"record_id": FOUNDATION_ID, "source": dict(REGISTRY_SOURCE)})
    return sheet_response, master


def _models(sheet_response: dict, master: dict, workspace: Path):
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    return profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=sheet_response,
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
        master=master,
    )


def test_command5_merges_display_onto_registry_shaped_foundation_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _registry_fixture()

    gm_model, view, _tabs = _models(sheet_response, master, workspace)

    foundation = gm_model["foundation"]
    assert foundation["record_id"] == FOUNDATION_ID
    assert foundation["source"] == DISPLAY_SOURCE
    assert foundation["source_anchor"] == f"foundation:{FOUNDATION_ID}"
    assert foundation["full_description"] == "Authenticated selected foundation rules."
    assert foundation["mechanics_authority"] == {"source": "master-ledger"}
    assert view["foundation"] == foundation


@pytest.mark.parametrize(
    ("field", "value"),
    [("artifact_sha256", "e" * 64), ("artifact", "Other_Catalog.md")],
)
def test_command5_rejects_registry_foundation_source_that_differs_from_the_display_card(
    tmp_path: Path, field: str, value: str,
) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _registry_fixture()
    master["foundation"]["source"][field] = value

    with pytest.raises(FoundryError) as caught:
        _models(sheet_response, master, workspace)
    assert caught.value.code == "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID"


def test_command5_does_not_synthesize_a_registry_anchor_for_other_surfaces(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    master["method"]["source"] = {"artifact": "authority/selected-records.json", "artifact_sha256": "s" * 64}

    with pytest.raises(FoundryError) as caught:
        _models(sheet_response, master, workspace)
    assert caught.value.code == "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID"
