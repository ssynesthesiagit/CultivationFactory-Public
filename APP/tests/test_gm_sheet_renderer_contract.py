"""Focused contract checks for the GM-style Character Sheet renderer stage.

These are deliberately static and deterministic: they pin the wiring that the
name-precedence fix and the GM-style viewer depend on, without needing a
browser or a live server. Rendered verification stays with the owner's Codex
in-app browser pass.
"""
from pathlib import Path
import json

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gm_sheet"


def test_scratch_library_fixture_contains_only_synthetic_identity() -> None:
    fixture = json.loads((FIXTURES / "scratch_library_rows.fixture.json").read_text(encoding="utf-8"))
    names = [row["name"] for row in fixture["rows"]]
    assert "Shen Lihuo" not in names
    assert "Synthetic Library Character" in names

APP_STATIC = Path(__file__).resolve().parents[1] / "static"


def _read(name: str) -> str:
    return (APP_STATIC / name).read_text(encoding="utf-8")


def test_sheet_view_model_loads_before_app_js() -> None:
    html = _read("index.html")
    view_model_pos = html.find("/static/sheet_view_model.js")
    app_pos = html.find("/static/app.js")
    assert view_model_pos != -1, "index.html must load sheet_view_model.js"
    assert app_pos != -1, "index.html must load app.js"
    assert view_model_pos < app_pos, "sheet_view_model.js must load before app.js"


def test_view_model_exposes_final_name_precedence() -> None:
    source = _read("sheet_view_model.js")
    assert "resolveOwnerFinalName" in source
    assert "PLACEHOLDER_NAMES" in source
    # The delegated-name placeholder must never win over a finalized name.
    assert '"ai-proposed character"' in source


def test_app_js_uses_the_view_model_for_library_and_sheet_names() -> None:
    source = _read("app.js")
    assert "TianxiaSheetViewModel.resolveOwnerFinalName" in source, (
        "renderCharacterLibrary must resolve card names through the shared "
        "final-name precedence helper"
    )
    assert "TianxiaSheetViewModel.buildSheetViewModel" in source, (
        "renderOwnerSheet must derive the sheet view from the shared model"
    )
    assert 'api("/api/characters", options)' in source, (
        "the library starts optional /api/characters enrichment with abort support"
    )
    assert "GM_LIBRARY_ENRICHMENT_TIMEOUT_MS" in source
    assert "requestGeneration !== gmLibraryRequestGeneration" in source
    assert "gmApplyCharacterEnrichment" in source
    # The library card path must not fall back to the placeholder label.
    library_start = source.index("async function renderCharacterLibrary")
    library_end = source.index("loadProjects = async function", library_start)
    library_body = source[library_start:library_end]
    assert "AI-proposed character" not in library_body


def test_owner_sheet_keeps_existing_export_and_workspace_wiring() -> None:
    source = _read("app.js")
    start = source.index("function renderOwnerSheet(")
    end = source.index("function setSelectedCharacterWorkspaceVisible", start)
    body = source[start:end]
    for required_id in (
        "gmExportPanel",
        "factoryWorkspaceExplanation",
        "prepareFactoryWorkspace",
        "factoryWorkspaceResult",
        "gmExportExplanation",
        "gmExportCharacter",
        "gmExportDownload",
        "gmExportResult",
    ):
        assert f'getElementById("{required_id}")' in body, f"renderOwnerSheet must keep updating {required_id}"
    # Recovery behavior stays reachable from the sheet itself.
    assert "restoreGuidedActiveBuild" in body
    # Loading and failure states render inside the viewer geometry with a
    # retry action and closed technical details.
    assert "function renderOwnerSheetPending" in source
    open_start = source.index("async function openOwnerCharacterSheet")
    open_body = source[open_start:source.index("function ownerStageLabel", open_start)]
    assert "renderOwnerSheetPending()" in open_body
    assert '"Try again"' in open_body
    assert "developer-diagnostics" in open_body


def test_owner_sheet_exposes_provider_free_rebuild_for_persisted_gm_receipts() -> None:
    source = _read("app.js")
    owner_start = source.index("function renderOwnerSheet(")
    owner_end = source.index("function setSelectedCharacterWorkspaceVisible", owner_start)
    owner_body = source[owner_start:owner_end]
    assert "provider_free_rebuild_available" in owner_body
    assert "Rebuild Command 1–4 workspace" in owner_body
    assert "workspaceRebuildPending" in owner_body
    assert "ratifyButton.disabled = !gmAuthoringRatificationChallenge || workspaceRebuildPending" in owner_body
    author_start = source.index("const authorGmTacticalButton")
    author_end = source.index("const issueGmRatificationChallengeButton", author_start)
    author_body = source[author_start:author_end]
    assert "GM_AUTHORING_PERSISTED_REBUILD_PENDING" in author_body
    assert "provider-free workspace rebuild" in author_body
    ratify_start = source.index("const ratifyGmAuthoringButton")
    ratify_end = source.index("const refreshNonSphereButton", ratify_start)
    assert "workspaceRebuildPending" in source[ratify_start:ratify_end]


def test_gm_guidance_tab_is_read_only_and_uses_the_bounded_workspace_view() -> None:
    source = _read("app.js")
    assert 'factory-workspace/view' in source
    assert 'gm_guidance' in source
    assert 'GM guidance only — not a combat macro' in source
    assert 'Composite Playbooks' not in source
    assert 'Forged Techniques (custom technique authoring)' in source
    assert 'Immortal Arts' in source
    assert 'They grant no action, bonus, resource change, legality, or execution authority.' in source


def test_owner_mechanics_use_the_current_seventeen_surface_contract() -> None:
    view_model = _read("sheet_view_model.js")
    app = _read("app.js")
    for surface_id in (
        "overview_core_stats", "leveling", "background", "paths_subpaths", "spheres_talents", "insights",
        "actions", "forged_techniques", "manuals_recorded_arts", "immortal_arts",
        "foundation", "method", "companions", "equipment", "resources_states_suppression", "dao_i_ching", "diagnostics",
    ):
        assert surface_id in view_model
    assert "gmBuildCompleteCharacterSurfacePanel" in app
    assert "Character sheet mechanics" in app
    assert "gm-sheet-utility" in app
    assert "panel.dataset.gmUtility = \"gm_guidance\"" in app
    # The retired nested tab must not be added by renderOwnerSheet.
    owner_start = app.index("function renderOwnerSheet(")
    owner_end = app.index("function setSelectedCharacterWorkspaceVisible", owner_start)
    owner_body = app[owner_start:owner_end]
    assert "complete_character" not in owner_body
    # Owner 2026-09-23: GM guidance is its own tab, not a block under every tab.
    assert 'const guidanceTab = {id: "gm_guidance", label: "GM Guidance"}' in owner_body
    assert "gmBuildAuthoringPanel(model, sheet, {utility: true})" not in owner_body


def test_complete_renderer_preserves_occurrences_and_full_source_text() -> None:
    app = _read("app.js")
    for token in (
        "earned_feature_occurrences", "occurrence_id", "event_id", "required_path_level",
        "gmCompleteLevelRowCard", "Full source-backed rules and provenance", "record_text",
        "gm-complete-longtext", "textContent",
    ):
        assert token in app
    assert "Each earned occurrence is shown with its source binding" in app


def test_mobile_character_selector_stays_bounded_with_usable_touch_targets() -> None:
    styles = _read("styles.css")
    assert "max-height: min(42vh, 22rem)" in styles
    assert "overscroll-behavior: contain" in styles
    assert ".character-library-card button { min-height: 44px; }" in styles
    assert ".owner-character-sheet .gm-tab-button {\n  min-height: 44px;" in styles
