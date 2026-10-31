"""Mastermind keeps native rollout verification while bounding its search width."""

from combat import ai_lookahead, ai_mastermind, menu_rank
from threading import Event, Thread
from time import monotonic
from combat.gate4_models import CandidateScore
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
    # Keep this assertion about successful verification independent of slow CI.
    monkeypatch.setattr(ai_mastermind, "DECISION_BUDGET_SECONDS", 30.0)
    assert context.tactics["tier"] == "MASTERMIND"
    assert "simulation" in context.tactics
    choice = LocalDeterministicController().choose_primary_action(context)
    assert any(part.component == "mastermind_lookahead"
               for score in choice.record.scored_alternatives for part in score.components)
    assert len(choice.record.scored_alternatives) == len(context.legal_candidates)
    assert any(candidate.actor_id == OWNER for candidate in context.legal_candidates)

    # Hold native verification indefinitely, independently of caller timing.
    entered, release, finished = Event(), Event(), Event()
    calls = []
    def slow_verify(*args, **kwargs):
        calls.append(1)
        entered.set()
        release.wait(10)
        return {}
    monkeypatch.setattr(ai_lookahead, "verify", slow_verify)
    plan = ai_mastermind.MastermindPlan(context)
    candidates = {c.candidate_id: c for c in context.legal_candidates}
    scores = [CandidateScore(candidate_id=c.candidate_id, option_ids=(), total=0, components=())
              for c in context.legal_candidates]
    plan._deadline = monotonic() + 1.0
    result = []
    def choose():
        result.extend(plan.with_self_followups(scores, candidates))
        finished.set()
    caller = Thread(target=choose, daemon=True)
    caller.start()
    try:
        assert entered.wait(2), "verification never started"
        assert finished.wait(3), "caller blocked on native verification"
        assert len(result) == len(scores)
        assert not any(p.component == "mastermind_lookahead" for s in result for p in s.components)
        # A second decision must not start another obsolete worker.
        plan._deadline = monotonic() + 1.0
        assert len(plan.with_self_followups(scores, candidates)) == len(scores)
        assert len(calls) == 1
    finally:
        release.set()
        caller.join(timeout=3)
