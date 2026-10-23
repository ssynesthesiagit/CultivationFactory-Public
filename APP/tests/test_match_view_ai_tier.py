"""The match view always reports a playable AI difficulty, with and without overrides."""
from combat.ai_tiers import TIERS
from combat.gate5_service import CombatService
from tests.ai_tiers_native_support import FOE, OWNER, ROOT, fight


def tiers(view):
    return {row["entity_id"]: row["ai_tier"] for row in view["state"]["actors"]}


def test_match_view_imports_ai_tiers_and_reports_tier_without_metadata(tmp_path):
    combat, match_id, _session = fight(tmp_path)
    assert TIERS == ("TRICKY", "MASTERMIND")
    assert tiers(combat.get_match(match_id)) == {OWNER: "TRICKY", FOE: "TRICKY"}


def test_match_view_reports_and_persists_a_fight_owner_ai_tier(tmp_path):
    combat, match_id, _session = fight(tmp_path)
    view = combat.set_controller_mode(match_id, actor_id=FOE, controller_mode="LOCAL_AUTO",
                                      ai_tier="MASTERMIND")
    assert tiers(view) == {OWNER: "TRICKY", FOE: "MASTERMIND"}
    resumed = CombatService(ROOT, tmp_path).get_match(match_id)
    assert resumed["metadata"]["ai_tiers"] == {FOE: "MASTERMIND"}
    assert tiers(resumed) == {OWNER: "TRICKY", FOE: "MASTERMIND"}
