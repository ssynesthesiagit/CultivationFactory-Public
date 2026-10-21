"""Clearsight's self-immunity fixture must opt in to harmful self recipients."""
import json

import pytest

from combat.gate5_service import CombatService
from tests.test_darkness_and_stealth import (
    ROOT, SHIPPED_OVERRIDES, _darkness_at_the_table, _darkness_zone, _inside_readings, inclusive_darkness,
)


def test_the_fixture_adds_the_one_rule_the_shipped_data_does_not_state():
    """The default half of the parametrization is the player's real data.

    The tests need the caster to be one of the Darkness area's creatures before
    Clearsight's immunity can be observed; the shipped file does not rule
    Darkness inclusive, so the fixture supplies that fact. If a real owner
    ruling is ever shipped for ``DARK_BASE_DARKNESS``, the fixture is no longer
    needed and this test fails so the pair is revisited instead of silently
    testing a rule the game does not use.
    """
    shipped = json.loads(SHIPPED_OVERRIDES.read_text(encoding="utf-8"))["abilities"]
    assert "DARK_BASE_DARKNESS" not in shipped, \
        f"Darkness now has a shipped recipient ruling: {shipped.get('DARK_BASE_DARKNESS')}"


@pytest.mark.parametrize("inclusive_darkness", [False, True], indirect=True)
def test_self_darkness_eligibility_survives_table_commit_reload(tmp_path, inclusive_darkness):
    combat, mid, actor, foe, engine, session = _darkness_at_the_table(
        tmp_path, clearsight=False, running_meld=False)
    assert _darkness_zone(engine).active
    assert any("hearing" in row for row in _inside_readings(engine, actor)) is inclusive_darkness
    assert any("hearing" in row for row in _inside_readings(engine, foe))
    session.mechanical.explicit_snapshot()
    fresh = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
    assert _darkness_zone(fresh).active
    assert any("hearing" in row for row in _inside_readings(fresh, actor)) is inclusive_darkness
    assert any("hearing" in row for row in _inside_readings(fresh, foe))
