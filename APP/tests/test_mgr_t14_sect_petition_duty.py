"""Native petition arithmetic and honest boundaries; not whole-row closure.

The source row is acquired through the real character compiler. No institution,
Standing, support receipt, Duty completion, or GM approval is fabricated here.
"""
import pytest

from combat.ext.sect_stewardship import MERIT, petition_band
from tests.hunt12_support import ME, FOE, fight, reload
from tests.test_auto97_sect_stewardship import (BASE_LIST, JOURNEY_KEY, force_journey_die, journey_game,
    journey_institution, journey_rolls, learn)
from tests.test_journey_activities_native import A, B

PETITION = "SECT_STEWARDSHIP_BASE_PETITIONING_THE_HALL"


@pytest.fixture(scope="module")
def catalog():
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    from tests.h1_support import ROOT
    return CanonicalCatalogAuthorityService(ROOT)


@pytest.mark.parametrize("rolled", [1, 2, 3, 4])
def test_petition_records_roll_and_unresolved_table_facts_after_cold_reload(tmp_path, monkeypatch, catalog, rolled):
    force_journey_die(monkeypatch, rolled)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    learn(act)
    request = BASE_LIST[0]
    before = cold().journey_state(jid)["actors"][A]["resources"][MERIT]
    # The printed facts are the table's: no institution/authority/Standing/support declaration, no petition.
    with pytest.raises(ValueError):
        act("sect_petition", {"institution": "hall", "request": request})
    journey_institution(world, [request])
    state = act("sect_petition", {"institution": "hall", "request": request})
    receipt = state["actors"][A]["source_states"][JOURNEY_KEY]["support"][-1]
    assert receipt["die"] == rolled
    assert receipt["band"] == petition_band(rolled)
    assert receipt["request"] == request
    assert "success" not in receipt, "the table, not the engine, says what the result means"
    assert receipt["fulfillment"]["description"].startswith(("Support", "Useful", "Exceptional"))
    assert state["actors"][A]["resources"][MERIT] == before - 1
    assert MERIT not in state["actors"][B]["resources"]
    rolls = journey_rolls(state)
    assert len(rolls) == 1 and rolls[0]["roll"]["reason"] == PETITION
    assert list(rolls[0]["roll"]["dice"]) == [rolled]
    assert cold().journey_state(jid) == state, "cold reload keeps the committed receipt"


def test_petition_is_not_granted_to_unrelated_character(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = reload(tmp_path, mid)
    assert MERIT not in engine.state.actors[ME].resources
    assert not any("petition." in c.source_definition_id for c in engine.legal_candidates())
