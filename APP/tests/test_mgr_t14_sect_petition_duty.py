"""Native petition arithmetic and honest boundaries; not whole-row closure.

The source row is acquired through the real character compiler. No institution,
Standing, support receipt, Duty completion, or GM approval is fabricated here.
"""
import pytest

from combat.ext.sect_stewardship import MERIT, petition_band
from tests.hunt12_support import ME, FOE, candidate, fight, reload, send
from tests.test_auto97_sect_stewardship import force_merit_die, petition_logs

PETITION = "SECT_STEWARDSHIP_BASE_PETITIONING_THE_HALL"


@pytest.mark.parametrize("rolled", [1, 2, 3, 4])
def test_petition_records_roll_and_unresolved_table_facts_after_cold_reload(tmp_path, monkeypatch, rolled):
    force_merit_die(monkeypatch, rolled)
    combat, table, mid = fight(tmp_path, [PETITION])
    chosen = candidate(combat, mid, lambda c: c.source_definition_id.endswith("petition.ordinary"))
    session = combat._load_session(mid)
    action = session.engine.action_catalog[chosen.source_definition_id]
    description = action.parameters["description"]
    assert "non-combat Action during a scene, or during downtime" in description
    assert "appropriate hall" in description
    before = session.engine.state.actors[ME].resources[MERIT]
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"

    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources[MERIT] == before - 1
    assert MERIT not in engine.state.actors[FOE].resources
    check = [e for e in engine.events if e.event_type == "CHECK_ROLLED"][-1]
    assert check.actor_id == ME
    assert check.payload["merit_die"] == rolled
    assert check.payload["merit_die_size"] == 4
    assert check.payload["success"] is None
    # The established plug-in note event is inspected below, rather than
    # manufacturing a receipt for supplies or private institutional knowledge.
    reminders = [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"]
    assert any("non-combat Action" in text and "GM confirms" in text for text in reminders)
    assert any("does not grant goods, access, introductions, or information automatically" in text
               for text in reminders)
    assert petition_band(rolled) in petition_logs(engine)[-1]
    assert "GM confirms the appropriate authority, your Standing there, and the actual support" in petition_logs(engine)[-1]


def test_petition_is_not_granted_to_unrelated_character(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = reload(tmp_path, mid)
    assert MERIT not in engine.state.actors[ME].resources
    assert not any("petition." in c.source_definition_id for c in engine.legal_candidates())
