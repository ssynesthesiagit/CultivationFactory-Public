"""Queued offline check of full native prone/flier preparation.

The cProfile breakdown is an opt-in diagnostic: set CF_AI_PROFILE=1 to print it.
The default run only asserts the decision (never a profiler, never a clock).
"""
import cProfile
import io
import json
import os
import pstats

import pytest

from combat import menu_rank
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, fight
from tests.test_ai_mastermind import Offline


@pytest.mark.parametrize("position", [(17, 8), (12, 7)])
def test_late_prone_preparation_is_decided_with_standing_option(tmp_path, monkeypatch, capsys, position):
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], equal=True, flight=True,
        band="rival/boss", foe_at={"x": position[0], "y": position[1] - 1})
    engine = session.engine
    actor = engine.state.actors[OWNER]
    actor.position = Position(x=position[0], y=position[1])
    actor.current_hp = 1
    engine.state.round_number = 6
    # Evented condition application invalidates the native menu after setup.
    engine._apply_condition(actor, "condition:typed.prone", "test:late-posture", OWNER, expires_on=None)
    policy, _ = combat.policies.for_actor(OWNER)
    profile = cProfile.Profile() if os.environ.get("CF_AI_PROFILE") else None
    if profile:
        profile.enable()
    context = build_decision_context(engine, policy, for_ai=True)
    choice = LocalDeterministicController().choose_primary_action(context)
    if profile:
        profile.disable()
        out = io.StringIO()
        pstats.Stats(profile, stream=out).sort_stats("cumulative").print_stats(45)
        with capsys.disabled():
            print("AIUP2 PRONE PROFILE " + json.dumps({"position": actor.position.model_dump(),
                "preparation": context.preparation_ns / 1e9,
                "candidates": len(context.legal_candidates), "profile": out.getvalue()}), flush=True)
    selected = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert "standing_cost_ft" in selected.metadata
    engine.execute_intent(choice.intent)
