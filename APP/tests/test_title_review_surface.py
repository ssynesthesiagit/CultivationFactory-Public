from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import CharacterCreationDescriptiveFieldsRequest


_ROOT = Path(__file__).resolve().parents[2]
_API_SOURCE = (_ROOT / "APP/app/api.py").read_text(encoding="utf-8")
_HTML_SOURCE = (_ROOT / "APP/static/index.html").read_text(encoding="utf-8")
_JS_SOURCE = (_ROOT / "APP/static/app.js").read_text(encoding="utf-8")
_CSS_SOURCE = (_ROOT / "APP/static/styles.css").read_text(encoding="utf-8")


def test_descriptive_request_title_is_optional_and_bounded() -> None:
    request = CharacterCreationDescriptiveFieldsRequest(
        name="Public Fixture",
        title="The Quiet Cauldron",
        concept="A source-backed descriptive concept.",
    )
    assert request.title == "The Quiet Cauldron"
    assert CharacterCreationDescriptiveFieldsRequest().title is None

    with pytest.raises(ValidationError):
        CharacterCreationDescriptiveFieldsRequest(title="x" * 121)


def test_owner_view_route_and_review_form_carry_title_without_mechanics() -> None:
    assert "title=body.title" in _API_SOURCE
    assert '"title": projected_title' in _API_SOURCE
    assert '"title_provenance": projected_title_provenance' in _API_SOURCE

    assert 'id="guidedProposedTitle"' in _HTML_SOURCE
    assert 'maxlength="120"' in _HTML_SOURCE
    assert '<label>Title<input id="guidedProposedTitle"' in _HTML_SOURCE

    assert 'document.getElementById("guidedProposedTitle")' in _JS_SOURCE
    assert 'descriptiveFieldValue(projection, "title")' in _JS_SOURCE
    assert 'body: JSON.stringify({name: name || null, title: title || null, concept: concept || null})' in _JS_SOURCE
    assert '"guidedProposedTitle"' in _JS_SOURCE
    assert 'appendCandidateLine(host, "Title"' in _JS_SOURCE
    assert "Title: ${ownerText(identity.title" in _JS_SOURCE
    assert 'appendCandidateLine(host, "Title", descriptiveFieldValue' in _JS_SOURCE


def test_title_review_uses_existing_mobile_safe_descriptive_grid() -> None:
    assert _HTML_SOURCE.count('class="descriptive-fields-grid"') == 1
    assert ".descriptive-fields-grid" in _CSS_SOURCE
    assert ".descriptive-fields-grid { grid-template-columns: 1fr; }" in _CSS_SOURCE
