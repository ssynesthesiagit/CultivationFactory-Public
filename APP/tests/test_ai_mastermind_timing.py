"""Offline worst-menu timing probe, queued like every other test.

The flier/Air case was the prior benchmark's slowest menu. Report native work
separately from the bounded rollout wait. For a non-Swarmlord host, estimate a
Swarmlord up to 50% slower on native Python work; do NOT scale wall-clock waits,
because the planner reduces its remaining wait on a slower machine.
"""
import json
import platform
import time
from pathlib import Path

import pytest

from combat import ai_lookahead, ai_mastermind, menu_rank
from combat.embedding_rank import EmbeddingError
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, context_for, fight


@pytest.mark.parametrize("arena", ["battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"])
@pytest.mark.parametrize("wounded", [False, True])
def test_air_flier_whole_decision_budget(tmp_path, monkeypatch, capsys, arena, wounded):
    class Offline:
        def embed(self, texts):
            raise EmbeddingError("offline timing")
        def prefetch(self, *args, **kwargs):
            pass
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
        equal=True, flight=True, arena_id=arena, foe_at={"x": 3, "y": 7})
    if wounded:
        actor = session.engine.state.actors[OWNER]
        actor.current_hp = max(1, actor.maximum_hp // 5)
        session.engine.state.round_number = 8
        session.engine._apply_condition(actor, "condition:typed.prone", "test:timing", OWNER, expires_on=None)
    intervals = []
    native_verify = ai_lookahead.verify
    def measured_verify(*args, **kwargs):
        start = time.perf_counter()
        result = native_verify(*args, **kwargs)
        intervals.append((start, time.perf_counter()))
        return result
    monkeypatch.setattr(ai_lookahead, "verify", measured_verify)
    start = time.perf_counter()
    context = context_for(combat, session)
    assert context.own_knowledge.creatures, "time a located enemy, not just an empty search menu"
    choice = LocalDeterministicController().choose_primary_action(context)
    end = time.perf_counter()
    elapsed = end - start
    before = intervals[0][0] - start if intervals else elapsed
    tail = end - intervals[-1][1] if intervals else 0
    # Conservative remaining-time bound: native work gets 1.5x as long, while
    # the caller's deadline stays fixed. Final record construction is outside
    # the optional worker, so scale it separately too.
    factor = 1.0 if platform.node().lower() == "swarmlord" else 1.5
    estimate = max(ai_mastermind.DECISION_SECONDS, factor * before) + factor * tail
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    row = {"host": platform.node(), "cpu": cpu, "arena": arena, "wounded": wounded,
           "seconds": elapsed, "before_rollout_seconds": before,
           "record_tail_seconds": tail, "native_work_scale": factor,
           "swarmlord_estimated_bound_seconds": estimate, "options": len(context.legal_candidates)}
    with capsys.disabled():
        print("AIUP2 TIMING " + json.dumps(row), flush=True)
    assert choice.intent.candidate_id in {c.candidate_id for c in context.legal_candidates}
    # Wall-clock numbers are printed for the bench report only, never asserted:
    # host load and machine name make them non-deterministic in the default run.
