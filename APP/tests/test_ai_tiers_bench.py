"""Bounded AIUP1 equal-build native fight benchmark, run only through HeavyQ.

Uses the same compiled-sheet/persisted fight setup as the table regressions.
The baseline is this controller's unmodified legacy scorer/representatives with
the new detached tactics profile absent. No source-history reads or monkeypatches.
Both sides share the Dao policy and every rules/legality/reaction path.
Fixtures use real hexadecimal project IDs and the arena\u0027s own legal starts.
"""
import json
import platform
import time

from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from tests.test_ai_tiers_tricky import fight, OWNER, FOE


def test_fixed_seed_equal_build_tricky_benchmark(tmp_path, capsys):
    controller = LocalDeterministicController()
    results, decisions, contexts, scoring = [], [], [], []
    # The two shipped Factory bench arenas; paired seats prevent initiative or
    # side assignment from silently counting as a tactics improvement.
    for arena in ("battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"):
        for seed in range(5):
            for tricky in (OWNER, FOE):
                path = tmp_path / f"{arena.rsplit(':', 1)[-1]}-{seed}-{tricky.rsplit('-', 1)[-1]}"
                combat, _, session = fight(path, ["FIRE_TAL_FIREBALL_ART", "FIRE_TAL_FLAME_LASH"],
                    equal=True, seed=f"AIUP1-bench-{seed}", arena_id=arena, start_turn=False, bench_starts=True)
                engine = session.engine

                def reaction(request):
                    policy, _ = combat.policies.for_actor(request["reactor_id"])
                    choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
                    return choice.decision, choice.record.model_dump(mode="json")
                engine.set_reaction_provider(reaction)
                steps = 0
                while engine.state.terminal_result is None and steps < 180:
                    actor = engine.state.current_actor_id
                    policy, _ = combat.policies.for_actor(actor)
                    start = time.perf_counter()
                    context = build_decision_context(engine, policy, for_ai=True)
                    context_seconds = time.perf_counter() - start
                    contexts.append(context_seconds)
                    if actor != tricky:
                        context = context.model_copy(update={"tactics": {}})
                    start = time.perf_counter()
                    choice = controller.choose_primary_action(context)
                    elapsed = time.perf_counter() - start
                    if actor == tricky:
                        scoring.append(elapsed)
                        decisions.append(context_seconds + elapsed)
                    engine.execute_intent(choice.intent)
                    steps += 1
                terminal = engine.state.terminal_result
                winner = terminal.winning_team_id if terminal else None
                results.append({"map": arena, "seed": seed, "tricky": tricky, "steps": steps,
                    "winner": winner, "win": winner == engine.state.actors[tricky].team_id,
                    "terminal": terminal.kind if terminal else "STEP_LIMIT"})
    wins = sum(r["win"] for r in results)
    report = {"host": platform.node(), "fights": len(results), "wins": wins,
              "win_rate": wins / len(results), "tricky_decisions": len(decisions),
              "maximum_decision_seconds": max(decisions),
              "maximum_controller_seconds": max(scoring),
              "maximum_context_seconds": max(contexts), "results": results}
    (tmp_path / "AIUP1-bench.json").write_text(json.dumps(report, indent=2) + "\n")
    with capsys.disabled():
        print("AIUP1 BENCH " + json.dumps(report), flush=True)
    summary = (f"{wins}/{len(results)} wins ({wins / len(results):.1%}); "
               f"max decision={max(decisions):.4f}s, controller={max(scoring):.4f}s, "
               f"context={max(contexts):.4f}s; host={platform.node()}")
    assert report["win_rate"] >= .65, summary
    assert report["maximum_decision_seconds"] <= .5, summary
