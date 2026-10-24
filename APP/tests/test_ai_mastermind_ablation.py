"""Same seeds/builds/maps/seats for each optional planner refinement; no live model.

The embedding ablation measures the offline fallback, not unmeasured live-model
quality. The required service-down configuration is explicitly identified.
"""
import json
import time

import pytest

from combat.ai_mastermind import MastermindPlan
from combat import ai_tactics, ai_lookahead, placement_menu
from tests.test_ai_mastermind_bench import run_benchmark


@pytest.mark.parametrize("label,embeddings,lookahead", [
    ("plays", False, False), ("plays_embeddings", True, False),
    ("plays_lookahead", False, True), ("all", True, True),
])
def test_fixed_seed_ablation(tmp_path, monkeypatch, capsys, label, embeddings, lookahead):
    monkeypatch.setattr(MastermindPlan, "use_embeddings", embeddings)
    monkeypatch.setattr(MastermindPlan, "use_lookahead", lookahead)
    phases = {}
    for module, name in [(ai_tactics, "annotate_flight"), (ai_tactics, "owned_profile"),
                         (ai_lookahead, "own_snapshot"), (placement_menu, "annotate")]:
        original = getattr(module, name)
        def timed(*args, _fn=original, _name=name, **kwargs):
            start = time.perf_counter()
            try:
                return _fn(*args, **kwargs)
            finally:
                engine = args[0]
                current = engine.state.actors.get(engine.state.current_actor_id)
                if current is not None and current.ai_tier == "MASTERMIND":
                    phases[_name] = max(phases.get(_name, 0), time.perf_counter() - start)
        monkeypatch.setattr(module, name, timed)
    report = run_benchmark(tmp_path, monkeypatch, capsys, label=label)
    report.update(configuration=label, embedding_transport="offline", maximum_phase_seconds=phases)
    with capsys.disabled():
        print("AIUP2 ABLATION " + json.dumps(report), flush=True)
    assert report["fights"] == 20
    assert report["draw_rate"] <= .10, report
    assert len(report["plays"]) >= 3, report
