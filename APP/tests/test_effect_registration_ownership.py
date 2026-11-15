"""An effect name has one owner regardless of plug-in import order."""
import pytest

from combat import ext


def test_duplicate_effect_rejects_before_replacing_handler_or_metadata(monkeypatch):
    monkeypatch.setattr(ext, "_EFFECTS", {})
    monkeypatch.setattr(ext, "_EFFECT_HARM", {})
    monkeypatch.setattr(ext, "_EFFECT_FORGE_REJECTION", {})

    @ext.effect("owned_effect", harmful=True, forge_rejection="Source-bound")
    def first():
        return "first"

    def second():
        return "second"

    with pytest.raises(ValueError, match="owned_effect.*already registered.*first"):
        ext.effect("owned_effect", harmful=False)(second)

    assert ext._EFFECTS == {"owned_effect": first}
    assert ext._EFFECT_HARM == {"owned_effect": True}
    assert ext._EFFECT_FORGE_REJECTION == {"owned_effect": "Source-bound"}


def test_reapplying_registration_to_the_same_function_remains_idempotent(monkeypatch):
    monkeypatch.setattr(ext, "_EFFECTS", {})
    monkeypatch.setattr(ext, "_EFFECT_HARM", {})
    monkeypatch.setattr(ext, "_EFFECT_FORGE_REJECTION", {})

    def handler():
        return "registered"

    register = ext.effect("owned_effect", harmful=False)
    assert register(handler) is handler
    assert register(handler) is handler
    assert ext._EFFECTS == {"owned_effect": handler}
