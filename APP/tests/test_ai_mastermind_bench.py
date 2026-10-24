"""Fixed-seed, equal-build native MASTERMIND/TRICKY gate; queued, no live model.

Standard pillar/mist bench maps, paired seats, five builds/situations per map.
Offline proposals are intentional: CI must prove the service-down fallback.
The live CPU transport has its own opt-in host timing tool; no model is called.
"""
import json
import platform
import time

from combat.embedding_rank import EmbeddingError
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, FOE
from tests.ai_mastermind_bench_support import bench_fight, outcome, summarize, STEP_LIMIT


def run_benchmark(tmp_path, monkeypatch, capsys, *, label="gate"):
    from combat import menu_rank
    class Offline:
        def embed(self, texts):
            raise EmbeddingError("offline benchmark")
        def prefetch(self, *args, **kwargs):
            pass
    monkeypatch.setattr(menu_rank, "default_client", lambda: Offline())
    monkeypatch.setattr(menu_rank, "_CLIENT", Offline())
    controller = LocalDeterministicController()
    results, timings, plays = [], [], set()
    builds = [
        (["FIRE_TAL_FIREBALL_ART", "FIRE_TAL_FLAME_LASH"], False),
        (["FIRE_TAL_FIREBALL_ART"], False),
        (["FIRE_TAL_FLAME_LASH"], False),
        (["AIR_BASE_WIND_LASH"], True),
        (["AIR_BASE_WIND_LASH", "FIRE_TAL_FLAME_LASH"], False),
    ]
    for arena in ("battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"):
        for seed, (talents, flight) in enumerate(builds):
            for boss in (OWNER, FOE):
                path = tmp_path / f"{arena.rsplit(':', 1)[-1]}-{seed}-{boss[-4:]}"
                combat, _, session = bench_fight(path, talents, equal=True, flight=flight,
                    seed=f"AIUP2-bench-{seed}", arena_id=arena, start_turn=False, bench_starts=True)
                engine = session.engine
                engine.state.actors[boss].ai_tier = "MASTERMIND"

                def reaction(request):
                    policy, _ = combat.policies.for_actor(request["reactor_id"])
                    choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
                    return choice.decision, choice.record.model_dump(mode="json")
                engine.set_reaction_provider(reaction)
                steps, trace = 0, []
                while engine.state.terminal_result is None and steps < STEP_LIMIT:
                    actor = engine.state.current_actor_id
                    policy, _ = combat.policies.for_actor(actor)
                    start = time.perf_counter()
                    context = build_decision_context(engine, policy, for_ai=True)
                    choice = controller.choose_primary_action(context)
                    elapsed = time.perf_counter() - start
                    candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
                    if actor == boss:
                        timings.append(elapsed)
                        assert "Play: " in choice.record.explanation
                        play = choice.record.explanation.split("Play: ", 1)[1].split(" — ", 1)[0]
                        if candidate.kind not in {"END_TURN", "HOLD_POSITION"} and play != "Keep the next opening":
                            plays.add(play)
                    else:
                        assert "Play: " not in choice.record.explanation
                    trace.append({"round": context.round_number, "boss": actor == boss,
                                  "choice": candidate.display_name, "explanation": choice.record.explanation,
                                  "seconds": round(elapsed, 4),
                                  "preparation_seconds": round(context.preparation_ns / 1e9, 4),
                                  "top": [{"candidate": s.candidate_id, "total": s.total,
                                           "parts": {p.component: p.value for p in s.components if p.value}}
                                          for s in choice.record.scored_alternatives[:3]]})
                    trace[-1]["selected_source"] = candidate.source_definition_id
                    trace[-1]["own_hp"] = engine.state.actors[actor].current_hp
                    engine.execute_intent(choice.intent)
                    trace[-1]["executed"] = True
                    steps += 1
                terminal = engine.state.terminal_result
                winner = terminal.winning_team_id if terminal else None
                row = {"map": arena, "seed": seed, "boss": boss, "steps": steps,
                       "winner": winner, "outcome": outcome(terminal, engine.state.actors[boss].team_id),
                       "rounds": engine.state.round_number, "terminal": terminal.kind}
                results.append(row)
                with capsys.disabled():
                    print("AIUP2 FIGHT " + json.dumps({**row, "trace": trace}), flush=True)
    report = {"host": platform.node(), **summarize(results), "plays": sorted(plays), "decisions": len(timings),
              "maximum_decision_seconds": max(timings),
              "swarmlord_time_scale": 1 if platform.node().lower() == "swarmlord" else 1.5,
              "maximum_swarmlord_scaled_seconds": max(timings) * (1 if platform.node().lower() == "swarmlord" else 1.5),
              "results": results}
    (tmp_path / "AIUP2-bench.json").write_text(json.dumps(report, indent=2) + "\n")
    with capsys.disabled():
        print("AIUP2 BENCH " + json.dumps(report), flush=True)
    return report


def test_equal_build_mastermind_gate(tmp_path, monkeypatch, capsys):
    report = run_benchmark(tmp_path, monkeypatch, capsys)
    assert report["decided_win_rate"] >= .60, report
    assert report["draw_rate"] <= .10, report
    assert len(report["plays"]) >= 3, report
    assert report["maximum_swarmlord_scaled_seconds"] <= 3, report
