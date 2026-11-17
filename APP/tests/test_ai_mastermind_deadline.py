"""Mastermind keeps native rollout verification while bounding its search width."""

from combat import ai_lookahead, menu_rank
import time
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



def test_lookahead_is_identical_under_slow_simulation(tmp_path, monkeypatch):
    """On 2026-11-14 look-ahead raced a 3 s wall clock in a thread, so AI choices changed with machine load; it now runs only on its checkpoint budget."""
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               equal=True, flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    controller = LocalDeterministicController()
    plain = controller.choose_primary_action(context)
    simulate = ai_lookahead.simulate

    def slow_simulate(*args, **kwargs):
        time.sleep(3.5)
        return simulate(*args, **kwargs)

    monkeypatch.setattr(ai_lookahead, "simulate", slow_simulate)
    slow = controller.choose_primary_action(context)
    assert any(part.component == "mastermind_lookahead"
               for score in plain.record.scored_alternatives for part in score.components)
    assert slow.record.scored_alternatives == plain.record.scored_alternatives
    assert slow.intent == plain.intent
    assert slow.record == plain.record
