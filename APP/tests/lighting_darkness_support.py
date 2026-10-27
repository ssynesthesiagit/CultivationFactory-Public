"""Stable reference inputs for lighting tests that compile Darkness areas.

The public export replaces reference prose. Darkness still uses that prose for
legacy zone inference, and its talents use printed headings for shape categories.
Keep real mechanics and the real compiler/table; supply only these fixture inputs.
"""
import json
from contextlib import contextmanager

import pytest

from combat import factory_compiler


@contextmanager
def synthetic_darkness_rules(tmp_path, monkeypatch):
    """Scope synthetic compiler reference prose to one test, restoring both readers."""
    rules = {
        **factory_compiler._rules_text(),
        "TAL_DARK_PURE_DARKNESS": (
            "### Pure Darkness - Darkness\n"
            "Darkvision is reduced to 5 feet inside your Darkness.\n"
            "All other senses have their range reduced by half."),
        "TAL_DARK_PITCH_BLACK": (
            "### Pitch Black - Augment\n"
            "Apply Pure Darkness in addition to one other Darkness talent modifying the same area."),
    }
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"]["DARK_BASE_DARKNESS"]["description"] = [
        "Create a sphere of supernatural Darkness centered anywhere within range."]
    path = tmp_path / "lighting-darkness-authority.json"
    path.write_text(json.dumps(authority))
    with monkeypatch.context() as patch:
        patch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
        patch.setattr(factory_compiler, "_RULES_TEXT_CACHE", rules)
        yield


@pytest.fixture
def darkness_rules(tmp_path, monkeypatch):
    with synthetic_darkness_rules(tmp_path, monkeypatch):
        yield
