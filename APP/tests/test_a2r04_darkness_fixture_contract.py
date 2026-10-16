"""Clearsight's self-immunity fixture must opt in to harmful self recipients."""
import pytest

from combat.gate5_service import CombatService
from tests.test_darkness_and_stealth import (
    ROOT, _darkness_at_the_table, _darkness_zone, _inside_readings, inclusive_darkness,
)


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
