"""Lane L21: Charged Needle must stay off unrelated Lightning attacks at the table."""

from tests.h1_support import ROOT
from tests.r1i_service_support import FOE, candidate, fixture
from combat.gate5_service import CombatService


def test_charged_needle_does_not_ride_lightning_lash_after_table_reload(tmp_path):
    combat, table, match_id, _send, commit = fixture(
        tmp_path, ["TAL_LIGHTNING_LIGHTNING_LASH", "TAL_LIGHTNING_CHARGED_NEEDLE"], seed="L21-NEEDLE")
    commit(candidate(table, match_id, "Lightning Lash: Flash", FOE))
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert not any(e.source_definition_id.endswith("CHARGED_NEEDLE") for e in loaded.engine.events)
    lash_events = [e.event_type for e in loaded.engine.events if "Lightning Lash" in e.source_definition_id]
    assert "SAVE_ROLLED" not in lash_events
    assert all(c.condition_id != "condition:no_cp_regain" for actor in loaded.engine.state.actors.values()
               for c in actor.conditions.values())
