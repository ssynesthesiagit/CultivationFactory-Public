"""Bounded native equal-build Tricky benchmark, opt-in: run through HeavyQ, not directly.

Runs only when CF_AI_BENCH=1 is set, or when the untracked marker APP/tests/.ai_bench_enabled exists
(git-ignored, so it is never committed or exported). Ordinary batches and public CI skip it.

48 fights: 3 builds x 2 standard bench maps x 4 fixed seeds x both seats.
Each build is identical on both sides (same talents, same starting kit, same
flight), so seat or initiative luck cancels. The opponent is the old AI: this
controller with the Tricky tactics profile removed. Both sides share the rules,
legality, reaction and table-style area paths. Timing includes a fresh context
and the controller. No source-history reads or monkeypatches.
"""
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import fight, OWNER, FOE

BENCH_MARKER = Path(__file__).with_name(".ai_bench_enabled")
BENCH_ENABLED = os.environ.get("CF_AI_BENCH") == "1" or BENCH_MARKER.exists()
pytestmark = pytest.mark.skipif(not BENCH_ENABLED,
    reason="opt-in bench: set CF_AI_BENCH=1 or create APP/tests/.ai_bench_enabled")

BUILDS = {
    # Caster: Fireball Art plus Flame Lash, both sides.
    "caster": dict(talents=["FIRE_TAL_FIREBALL_ART", "FIRE_TAL_FLAME_LASH"]),
    # Melee: a starting-kit jian for both sides, no talents.
    "melee": dict(melee=True),
    # Flier: hover/fly on both sides with the jian (flight tactics).
    "flier": dict(melee=True, flight=True),
}
ARENAS = ("battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard")
SEEDS = range(4)
ROUND_CAP = 20
STEP_CAP = 900
GATE = .85
DRAW_GATE = .10
DECISION_LIMIT = .5


OUT_DIR = Path(os.environ.get("CF_AI_BENCH_OUT", "/var/tmp/auto-audit/d1-fights/bench-tricky"))


def save_fight(combat, match_id, result, trace, folder, engine=None):
    """Copy one fight's Journal, controller decisions and metadata into OUT_DIR as .zst files (d1-fights layout).

    This harness drives engine.execute_intent directly, so the persistent Journal
    holds only the match genesis. Save the engine's own event log too: turn-start
    effects such as death saving throws are not decisions, so the trace alone
    cannot show them (DOWNED1, 2026-10-20).
    """
    folder.mkdir(parents=True, exist_ok=True)
    match_dir = combat._match_dir(match_id)
    for source, name in (("Journal.ndjson", "Journal.ndjson"), ("ControllerJournal.ndjson", "Agent_Decisions.jsonl")):
        path = match_dir / source
        if path.is_file():
            shutil.copyfile(path, folder / name)
            subprocess.run(["zstd", "-q", "-f", "--rm", str(folder / name)], check=False)
    if engine is not None:
        (folder / "Events.ndjson").write_text(
            "".join(json.dumps(event.model_dump(mode="json")) + "\n" for event in engine.events))
        subprocess.run(["zstd", "-q", "-f", "--rm", str(folder / "Events.ndjson")], check=False)
    (folder / "meta.json").write_text(json.dumps({"match_id": match_id, "result": result, "trace_rounds": len(trace)},
                                                 indent=2, default=str) + "\n")


def test_fixed_seed_equal_build_tricky_benchmark(tmp_path, capsys):
    controller = LocalDeterministicController()
    results, decisions, contexts, scoring = [], [], [], []
    for build, options in BUILDS.items():
        for arena in ARENAS:
            for seed in SEEDS:
                for tricky in (OWNER, FOE):
                    path = tmp_path / f"{build}-{arena.rsplit(':', 1)[-1]}-{seed}-{tricky.rsplit('-', 1)[-1]}"
                    combat, mid, session = fight(path, equal=True, seed=f"AIUP1-bench-{seed}", arena_id=arena,
                                               start_turn=False, bench_starts=True, maximum_rounds=ROUND_CAP, **options)
                    engine = session.engine

                    def reaction(request):
                        policy, _ = combat.policies.for_actor(request["reactor_id"])
                        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
                        return choice.decision, choice.record.model_dump(mode="json")
                    engine.set_reaction_provider(reaction)
                    steps = 0
                    trace = []
                    while engine.state.terminal_result is None and steps < STEP_CAP:
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
                        picked = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
                        trace.append({"round": context.round_number, "actor": actor.rsplit("-", 1)[-1],
                            "tricky": actor == tricky, "choice": picked.display_name,
                            "from": engine.state.actors[actor].position.model_dump(), "targets": picked.target_ids,
                            "hp": {a.entity_id.rsplit("-", 1)[-1]: a.current_hp for a in context.actors},
                            "resources": dict(engine.state.actors[actor].resources),
                            "context_s": round(context_seconds, 4), "controller_s": round(elapsed, 4),
                            "top": [{"name": next(c.display_name for c in context.legal_candidates
                                                if c.candidate_id == s.candidate_id), "total": s.total,
                                     "parts": {p.component: p.value for p in s.components if p.value}}
                                    for s in choice.record.scored_alternatives[:3]]})
                        engine.execute_intent(choice.intent)
                        steps += 1
                    terminal = engine.state.terminal_result
                    winner = terminal.winning_team_id if terminal else None
                    results.append({"build": build, "map": arena, "seed": seed, "tricky": tricky, "steps": steps,
                        "winner": winner, "win": winner == engine.state.actors[tricky].team_id,
                        "loss": winner is not None and winner != engine.state.actors[tricky].team_id,
                        "draw": winner is None,
                        "terminal": terminal.kind if terminal else "STEP_LIMIT",
                        "rounds": engine.state.round_number,
                        "hp_left": {a.entity_id.rsplit("-", 1)[-1]: a.current_hp for a in engine.state.actors.values()}})
                    save_fight(combat, mid, results[-1], trace, OUT_DIR / f"{build}-{arena.rsplit(':', 1)[-1]}-s{seed}-{tricky.rsplit('-', 1)[-1]}",
                               engine=engine)
                    with capsys.disabled():
                        print("AIUP1 FIGHT " + json.dumps({"build": build, "map": arena, "seed": seed,
                            "tricky": tricky, "winner": winner, "terminal": results[-1]["terminal"],
                            "rounds": results[-1]["rounds"], "steps": steps, "trace": trace}), flush=True)
    wins = sum(r["win"] for r in results)
    losses = sum(r["loss"] for r in results)
    draws = sum(r["draw"] for r in results)
    decided = wins + losses
    by_build = {b: sum(r["win"] for r in results if r["build"] == b) / sum(r["build"] == b for r in results)
                for b in BUILDS}
    report = {"host": platform.node(), "fights": len(results), "wins": wins, "losses": losses, "draws": draws,
              "win_rate": wins / decided if decided else 0.0, "draw_rate": draws / len(results),
              "by_build": by_build, "round_cap": ROUND_CAP, "tricky_decisions": len(decisions),
              "maximum_decision_seconds": max(decisions),
              "maximum_controller_seconds": max(scoring),
              "maximum_context_seconds": max(contexts), "results": results}
    (tmp_path / "AIUP1-bench.json").write_text(json.dumps(report, indent=2) + "\n")
    with capsys.disabled():
        print("AIUP1 BENCH " + json.dumps(report), flush=True)
    summary = (f"WIN {wins} LOSS {losses} DRAW {draws} of {len(results)} fights; "
               f"win rate of decided {report['win_rate']:.1%}, draw rate {report['draw_rate']:.1%}; by build {by_build}; "
               f"max decision={max(decisions):.4f}s, controller={max(scoring):.4f}s, "
               f"context={max(contexts):.4f}s; host={platform.node()}")
    assert len(results) >= 40
    assert report["win_rate"] >= GATE, summary
    assert report["draw_rate"] <= DRAW_GATE, summary
    assert report["maximum_decision_seconds"] <= DECISION_LIMIT, summary
