"""Cross-branch provider composition through real table commits and reloads."""
import pytest

from combat import ext
from combat.falling import Fall
from tests.test_a2_group_traditions_5 import Table, YOKAI_IDS


@pytest.mark.parametrize("lineage,speed", [("Kitsune", 40), ("Tengu", 50)])
def test_yokai_true_form_has_one_flight_provider_after_reload(tmp_path, lineage, speed):
    table = Table(tmp_path, YOKAI_IDS, pb=2)
    table.act("Yokai Lineage: " + lineage)
    table.act("True Yokai Form")
    table.reload()
    answers = [row for row in ext.run_strict("flight", table.engine, table.actor()) if row]
    assert len(answers) == 1
    assert answers[0]["fly_speed_ft"] == speed


def test_tengu_fall_protection_has_one_provider_after_reload(tmp_path):
    table = Table(tmp_path, YOKAI_IDS, pb=2)
    table.act("Yokai Lineage: Tengu")
    table.reload()
    actor = table.actor()
    answers = [row for row in ext.run_strict("falling_damage_distance", table.engine,
        actor, 50, Fall(actor.entity_id, 50, "test"), None) if row is not None]
    assert answers == [30]
