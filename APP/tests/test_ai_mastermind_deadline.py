"""The optional native rollout must not hold a live Mastermind decision."""

from combat import ai_lookahead
from tests.ai_tiers_native_support import fight, context_for, OWNER


def test_mastermind_skips_synchronous_belief_preparation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("deadline-safe Mastermind must not construct a belief engine")

    monkeypatch.setattr(ai_lookahead, "own_snapshot", forbidden)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                              equal=True, flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    assert context.tactics["tier"] == "MASTERMIND"
    assert "simulation" not in context.tactics
    assert context.legal_candidates
    assert any(candidate.actor_id == OWNER for candidate in context.legal_candidates)
