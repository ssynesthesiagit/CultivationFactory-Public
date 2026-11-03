"""Arc table coverage with legal precharges under riders/c13.

14cd285f (approved C13r3.review.md, merged 51edf97d) restricts Gather
Charge to willing creatures; charge_setup/commit_charge use real hostile hits.
"""
import pytest
from combat import typed_executor as te
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, charge_setup, commit_charge, OWNER, FOE, SECOND


@pytest.mark.parametrize("ai_owner", [False, True])
@pytest.mark.parametrize("selection", ["DECLINE", "USE"])
def test_single_arc_recipient_table_preview_decline_reload_replay(tmp_path, ai_owner, selection):
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_LIGHTNING_LASH"], bundle_transform=charge_setup)
    commit_charge(table, mid, send, SECOND)
    cid = candidate(table, mid, "Lightning Lash: Arc", FOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(cid, auto=ai_owner)
    if not ai_owner:
        assert result["status"] == "REACTION_REQUIRED"
        p = result["reaction"]
        assert p["context"]["reaction_source_id"] == "choice:needle.arc"
        assert len(p["choice"]["options"]) == 1
        assert p["choice"]["allow_decline"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        result = send(cid, [{**p["context"], "selection": selection, "option_ids": [SECOND] if selection == "USE" else []}])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert before["actors"][SECOND]["current_hp"] - loaded.engine.state.actors[SECOND].current_hp == (4 if ai_owner or selection == "USE" else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("recipient", [OWNER, SECOND])
def test_gather_charge_willing_menu_commit_reload_replay(tmp_path, recipient):
    """riders/c13, approved C13r3.review.md: self/allies legal, enemies excluded."""
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_LIGHTNING_LASH"], allies=[SECOND])
    groups = [g for g in table.state(mid)["menu"]["actions"] if "Gather Charge" in g["label"]]
    targets = {t for g in groups for o in g["options"] for t in o.get("target_ids", [])}
    assert targets == {OWNER, SECOND}
    label = "Gather Charge: Charge Yourself" if recipient == OWNER else "Gather Charge: Charge a Willing Creature"
    commit(candidate(table, mid, label, recipient))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert te.bears_mark(loaded.engine.state.actors[recipient], OWNER, "Charged")
    assert not te.bears_mark(loaded.engine.state.actors[FOE], OWNER, "Charged")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
