"""Keep pre-25.x defeat/replay fixtures on their original saved rules.

New service fights deliberately use 2024 dying. These tests exercise historical
immediate-defeat and exact captures; SOL113 separately covers the new default.
Only fixture creation changes, never runtime state, choices or assertions.
"""
import pytest

from combat.gate4_persistence import Gate4Persistence


@pytest.fixture
def legacy_finalized_turns(monkeypatch):
    """Create an unstamped historical fixture; retain all its original assertions."""
    create = Gate4Persistence.create_match

    def create_legacy(self, **kwargs):
        setup = dict(kwargs.get("roster_setup") or {})
        rules = dict(setup.get("rules") or {})
        rules.pop("finalized_turns", None)
        kwargs["roster_setup"] = {**setup, "rules": rules}
        return create(self, **kwargs)

    monkeypatch.setattr(Gate4Persistence, "create_match", create_legacy)


@pytest.fixture
def legacy_zero_hp(monkeypatch):
    create = Gate4Persistence.create_match

    def create_legacy(self, **kwargs):
        setup = dict(kwargs.get("roster_setup") or {})
        rules = dict(setup.get("rules") or {})
        rules.pop("zero_hp", None)
        rules.pop("finalized_turns", None)
        kwargs["roster_setup"] = {**setup, "rules": rules}
        return create(self, **kwargs)

    monkeypatch.setattr(Gate4Persistence, "create_match", create_legacy)
