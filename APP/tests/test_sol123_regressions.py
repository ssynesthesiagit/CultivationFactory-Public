"""25.x integration: nested recovery must survive a table commit in both modes."""
import pytest

from combat.gate4_persistence import Gate4Persistence
from tests.test_riders_c8_recovery import _recovery_case


@pytest.mark.parametrize("rules", [{}, {"zero_hp": "dying_2024"}])
@pytest.mark.parametrize("recovery", ["stable", "natural20"])
def test_nested_recovery_clears_record_after_commit_reload(tmp_path, monkeypatch, rules, recovery):
    create = Gate4Persistence.create_match

    def configured(self, **kwargs):
        kwargs["roster_setup"] = {**kwargs["roster_setup"], "rules": rules}
        return create(self, **kwargs)

    monkeypatch.setattr(Gate4Persistence, "create_match", configured)
    _recovery_case(tmp_path, "MANUAL", recovery, "none")
