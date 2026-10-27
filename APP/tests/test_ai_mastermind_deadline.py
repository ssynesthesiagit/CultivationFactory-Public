"""Mastermind keeps native rollout verification while bounding its search width."""

from combat import ai_lookahead, menu_rank
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, fight, context_for
from tests.test_ai_mastermind import Offline


def test_mastermind_bounds_rollout_and_keeps_verification(tmp_path, monkeypatch):
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    assert ai_lookahead.MAX_PLANS >= 1
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               equal=True, flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    assert context.tactics["tier"] == "MASTERMIND"
    assert "simulation" in context.tactics
    choice = LocalDeterministicController().choose_primary_action(context)
    assert any(part.component == "mastermind_lookahead"
               for score in choice.record.scored_alternatives for part in score.components)
    assert len(choice.record.scored_alternatives) == len(context.legal_candidates)
    assert any(candidate.actor_id == OWNER for candidate in context.legal_candidates)
