from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_map_centered_owner_workspace_exposes_modular_surfaces() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert {
        "combatOwnerWorkspace", "combatTeamRail" if False else "combatActorCards",
        "combatBattlefieldViewport", "combatBoard", "combatFloatingSheet",
        "combatPinnedSheetPanel", "combatSheetConnector", "combatCurrentTurnPanel",
        "combatInitiative", "combatEventFeed", "combatHistoryPanel", "combatMobileTabs",
        "combatCharacterDialog", "combatToggleGeometry", "combatToggleNameplates",
        "combatCenterTurn", "combatZoomIn", "combatZoomOut", "combatZoomFit",
        "combatReturnSetup", "combatScreenIntro",
    }.issubset(ids)
    assert 'data-mobile-panel="map"' in html
    assert 'data-mobile-panel="teams"' in html
    assert 'data-mobile-panel="feed"' in html
    assert 'data-mobile-panel="history"' in html
    assert "Advanced persistence and verification" in html
    assert "Deferred manual decision controls" in html


def test_inspection_state_is_separate_from_candidate_and_authoritative_state() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    for variable in (
        "combatSelectedActorId", "combatPinnedActorId", "combatFollowCurrentTurn",
        "combatNameplatesVisible", "combatGeometryOverlayMode", "combatViewportZoom",
        "combatMobileTab", "combatExpandedSheetSection", "combatSelectedCandidateId",
    ):
        assert f"let {variable}" in script
    assert "combatSelectedActorId = actorId" in script
    assert "combatSelectedCandidateId = actorId" not in script
    assert "selectCombatActor(actor.entity_id, token)" in script
    assert "chooseCombatMove(x, y)" in script
    assert "combatWorkspaceMode === \"technical\"" in script


def test_owner_surfaces_use_one_live_or_historical_presentation_contract() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "/presentation`" in script
    assert "/presentation?boundary=${combatHistoryIndex}`" in script
    assert "combatPresentation?.actors" in script
    assert "combatPresentation?.teams" in script
    assert "combatPresentation?.battlefield" in script
    assert "combatPresentation?.feed" in script
    assert "combatPresentation?.initiative_order" in script
    assert "renderCombatSheetInto(host, actor, displayMode)" in script
    assert 'renderCombatSheetInto(pinned, pinnedActor, "pinned")' in script
    assert 'renderCombatSheetInto(floating, selected, "floating")' in script


def test_tokens_and_combat_sheet_are_semantic_and_exact_id_linked() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'token.dataset.actorId = actor.entity_id' in script
    assert 'token.setAttribute("aria-label", accessible)' in script
    assert "combat-token-team-badge" in script
    assert "combat-token-hp" in script
    assert "combat-token-condition" in script
    assert "combatHasCharacterAuthorityDetails" in script
    assert "combatHasPersistentCharacterSheet" in script
    assert "openCombatCharacterAuthorityDetails(actor)" in script
    assert "openCombatPersistentCharacterSheet(actor)" in script
    assert "actor.sheet_link.route_kind" in script
    assert "display_name.toLowerCase" not in script


def test_geometry_overlay_is_projection_driven_and_view_only() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "combatPresentation?.battlefield?.terrain_regions" in script
    assert "combatGeometryOverlayMode" in script
    assert 'host.classList.toggle("geometry-hidden"' in script
    assert "mechanical_authority" not in script.split("function renderCombatBoard()", 1)[1].split("function combatSheetButton", 1)[0]
    assert "combatViewportZoom" in script
    assert "actor.position" in script
    assert "actor.position =" not in script


def test_responsive_mobile_bottom_sheet_and_accessibility_contracts() -> None:
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert '@media (max-width: 760px)' in css
    assert '.combat-sheet-floating[data-mobile-sheet-state="collapsed"]' in css
    assert '.combat-sheet-floating[data-mobile-sheet-state="medium"]' in css
    assert '.combat-sheet-floating[data-mobile-sheet-state="expanded"]' in css
    assert "min-height: 44px" in css
    assert ".combat-mobile-tabs" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "event.key !== \"Escape\"" in script
    assert "aria-current" in script
    assert "aria-selected" in script
    assert "outline: 3px solid var(--combat-gold)" in css


def test_open_match_hides_setup_and_compact_layout_uses_bottom_sheet() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    assert 'id="combatReturnSetup"' in html
    assert 'id="combatScreenIntro"' in html
    assert "function setCombatWorkspaceActive(active)" in script
    assert "setup.hidden = active" in script
    assert "intro.hidden = active" in script
    assert "setCombatWorkspaceActive(true)" in script
    assert "function combatUsesBottomSheet()" in script
    assert "viewport.clientWidth < 620" in script
    assert "combat-sheet-bottom-mode" in script
    assert ".r667-combat-shell.combat-sheet-bottom-mode .combat-sheet-floating" in css


def test_grid_rows_coordinates_and_token_fit_are_authoritative() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")

    assert 'host.style.setProperty("--board-columns", battlefield.width_squares)' in script
    assert 'host.style.setProperty("--board-rows", battlefield.height_squares)' in script
    assert 'token.dataset.gridX = String(anchorX)' in script
    assert 'token.dataset.gridY = String(anchorY)' in script
    assert 'token.dataset.gridCell = `${anchorX},${anchorY}`' in script
    assert 'group.style.gridColumn = `${anchorX + 1} / span ${width}`' in script
    assert 'group.style.gridRow = `${anchorY + 1} / span ${height}`' in script

    assert 'grid-template-columns: repeat(var(--board-columns), minmax(0, 1fr))' in css
    assert 'grid-template-rows: repeat(var(--board-rows), minmax(0, 1fr))' in css
    assert 'calc(100% / var(--board-rows))' in css
    assert 'width: min(82%, calc(100% - 6px))' in css
    assert 'max-width: 100%' in css
    assert 'width: 155%' not in css
    assert 'width: 170%' not in css
