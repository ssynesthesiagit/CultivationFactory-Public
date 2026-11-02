"""Lane L21: Lightning Lash Flash applies its attack Advantage once at the table."""

from tests.h1_support import ROOT
from tests.r1i_service_support import FOE, candidate, fixture
from combat.gate5_service import CombatService


def test_flash_advantage_is_applied_once_after_table_reload(tmp_path):
    combat, table, match_id, _send, commit = fixture(
        tmp_path, ["TAL_LIGHTNING_LIGHTNING_LASH", "TAL_LIGHTNING_FLASH_REVEAL"], seed="L21-FLASH")
    commit(candidate(table, match_id, "Lightning Lash: Flash", FOE))
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert loaded.mechanical.replay()["status"] == "PASS"
    modifiers = [e for e in loaded.engine.events if e.event_type == "MODIFIER_APPLIED" and FOE in e.target_ids
                 and e.payload.get("target_field") == "incoming_attack_mode" and e.payload.get("value") == "ADVANTAGE"]
    assert len(modifiers) == 1
