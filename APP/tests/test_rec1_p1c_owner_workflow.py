from __future__ import annotations

from pathlib import Path

from app.models import CharacterSheetCreateRequest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_manual_chat_has_one_explicit_response_source_state() -> None:
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'let guidedCompleteResponseSource = {kind: "none", file: null};' in javascript
    assert 'guidedCompleteResponseSource = {kind: "file", file};' in javascript
    assert 'guidedCompleteResponseSource = {kind: "paste", file: null};' in javascript
    assert 'if (source.kind === "file")' in javascript
    assert 'else {' in javascript
    assert "guidedCompleteResponseFile" not in javascript
    assert 'id="guidedReplaceCompleteReply"' in html
    assert 'id="guidedRemoveCompleteReply"' in html
    assert 'Drop one response file at a time.' in javascript
    assert 'Any previously selected file was cleared.' in javascript
    assert 'The current response source was not changed.' in javascript


def test_p1c_owner_surface_keeps_authority_separation_and_advanced_details_collapsed() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Path locks (0–3)" in html
    assert "All three Path tracks still exist at level zero." in html
    ordinary_filter = html[html.index('id="sheetInsightAuthorityFilter"'):html.index("</select>", html.index('id="sheetInsightAuthorityFilter"'))]
    assert "Background-Origin" not in ordinary_filter
    assert "542 ordinary Insights" in html
    assert "resolved_automatic_base_components" in javascript
    assert "automatic Sphere components loaded" in javascript
    assert 'id="advancedExports"' in html
    assert "Developer / Diagnostics" in html
    assert "Next legal action" in html
    assert "ownerNextLegalAction" in javascript
    assert "Automatic base abilities" in javascript
    assert "Factory routing" in javascript
    assert "base-ability-player-text" in javascript
    assert "Not specified in the accepted component record" not in javascript


def test_character_descriptive_fields_are_optional_for_delegated_ai_proposals() -> None:
    request = CharacterSheetCreateRequest(working_name="", concept="", target_cl=1)
    assert request.working_name == ""
    assert request.concept == ""
