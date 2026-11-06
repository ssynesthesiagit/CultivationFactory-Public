"""BRS1F24 lead finding: a stale Body Refining authority pin must surface as a named error, never an empty insight list."""
from __future__ import annotations

import pytest

from app.core import FoundryError
from canonical_catalog import service
from factory_authoring import body_refining_variants


def test_stale_pin_raises_named_error_not_empty_list(monkeypatch: pytest.MonkeyPatch):
    def stale():
        raise ValueError("Body Refining version authority hash does not verify")

    monkeypatch.setattr(body_refining_variants, "authored_insights", stale)
    with pytest.raises(FoundryError) as caught:
        service._authored_insights()
    assert caught.value.code == "CANONICAL_BODY_REFINING_PIN_STALE"
    assert "Rebuild" in caught.value.message
    assert "does not verify" in caught.value.details["cause"]


def test_valid_pin_returns_supplements():
    rows = service._authored_insights()
    assert rows, "the pinned authority must supply Body Refining supplements"
