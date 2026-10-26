#!/usr/bin/env python3
"""Offline MASTERMIND vs TRICKY strength benchmark with layer ablations. No model, deterministic per seed.

Every fight: equal builds, both arenas, every build from both seats, MASTERMIND on the boss seat against
TRICKY. Fights reuse tests/ai_mastermind_bench_support.py. Each MASTERMIND decision is timed on its own
(the TRICKY comparison runs after the timer stops) and compared with TRICKY's choice in the same state.

Usage:
  python3 tools/ai_bench.py [--seeds 3] [--configs full no_lookahead no_plays no_embeddings] [--out DIR]
Writes DIR/ai_bench_<config>.json and DIR/ai_bench.md (side-by-side table). DIR defaults to $CF_AI_BENCH_OUT
(required: there is no built-in output path). CF_AI_TIME_SCALE (default 1.0) multiplies measured seconds for the
budget check, so a slower machine can be compared with the reference budget without any host-name rule.
"""
import argparse, hashlib, json, math, os, shutil, statistics, sys, tempfile, time
from contextlib import contextmanager
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from combat import menu_rank
from combat.ai_mastermind import MastermindPlan
from combat.embedding_rank import EmbeddingError
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, FOE
from tests.ai_mastermind_bench_support import bench_fight, outcome, STEP_LIMIT

ARENAS = ("battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard")
# (talents, flight): ten equal builds. Both seats get the same build in every fight.
BUILDS = [
    (["FIRE_TAL_FIREBALL_ART", "FIRE_TAL_FLAME_LASH"], False),
    (["FIRE_TAL_FIREBALL_ART"], False),
    (["FIRE_TAL_FLAME_LASH"], False),
    (["AIR_BASE_WIND_LASH"], True),
    (["AIR_BASE_WIND_LASH", "FIRE_TAL_FLAME_LASH"], False),
    (["FIRE_TAL_FIREBALL_ART", "AIR_BASE_WIND_LASH"], True),
    (["FIRE_TAL_FLAME_LASH"], True),
    ([], False),
    (["FIRE_TAL_FIREBALL_ART"], True),
    (["AIR_BASE_WIND_LASH"], False),
]
BUDGET_SECONDS = 3.0
# Layer switches. The review's "tactics" layer is the base TurnPlan scorer, which has no separable switch
# (flight safety and placement gates live there), so it is not ablated; see the report.
CONFIGS = {
    "full": {},
    "no_lookahead": {"use_lookahead": False},
    "no_embeddings": {"use_embeddings": False},
    "no_plays": {"use_plays": False},
    "no_tactics": {"use_tactics": False},
}


class Offline:
    """Embedding service down: the fallback every offline run uses (no model is called)."""
    def embed(self, texts):
        raise EmbeddingError("offline benchmark")

    def prefetch(self, *args, **kwargs):
        pass


@contextmanager
def offline_and_switches(overrides):
    saved_client = (menu_rank.default_client, menu_rank._CLIENT)
    saved_switches = {name: getattr(MastermindPlan, name) for name in overrides}
    menu_rank.default_client = lambda: Offline()
    menu_rank._CLIENT = Offline()
    for name, value in overrides.items():
        setattr(MastermindPlan, name, value)
    try:
        yield
    finally:
        for name, value in saved_switches.items():
            setattr(MastermindPlan, name, value)
        menu_rank.default_client, menu_rank._CLIENT = saved_client


def wilson(wins, n, z=1.959964):
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _hp(actor):
    return max(0, actor.current_hp) + actor.temporary_hp


def _key(c):
    return (c.kind, c.source_definition_id, tuple(c.target_ids), str(c.destination))


def play_fight(scratch, n, arena, seed, talents, flight, boss, log):
    combat, _, session = bench_fight(scratch / f"fight-{n}", talents, equal=True, flight=flight,
        seed=f"AIUP2-bench-{seed}", arena_id=arena, start_turn=False, bench_starts=True)
    engine = session.engine
    boss_team = engine.state.actors[boss].team_id
    engine.state.actors[boss].ai_tier = "MASTERMIND"
    controller = LocalDeterministicController()

    def reaction(request):
        policy, _ = combat.policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")
    engine.set_reaction_provider(reaction)

    steps, last, row = 0, None, {"arena": arena, "seed": seed, "build": list(talents) + (["flight"] if flight else []),
        "boss": boss, "boss_turns": 0, "boss_actions": 0, "dealt": 0, "taken": 0, "decisions": [],
        "divergent": 0, "plays": []}
    digest = hashlib.sha256()
    while engine.state.terminal_result is None and steps < STEP_LIMIT:
        actor = engine.state.current_actor_id
        policy, _ = combat.policies.for_actor(actor)
        is_boss = actor == boss
        if is_boss and last != boss:
            row["boss_turns"] += 1
        last = actor
        before = {aid: _hp(a) for aid, a in engine.state.actors.items()}
        start = time.perf_counter()
        context = build_decision_context(engine, policy, for_ai=True)
        choice = controller.choose_primary_action(context)
        elapsed = time.perf_counter() - start
        by_id = {c.candidate_id: c for c in context.legal_candidates}
        candidate = by_id[choice.intent.candidate_id]  # KeyError: chosen action outside the legal menu
        explanation = choice.record.explanation
        if is_boss:
            if "Play: " not in explanation:
                raise AssertionError("MASTERMIND decision lacks its Play receipt")
            row["plays"].append(explanation.split("Play: ", 1)[1].split(" — ", 1)[0])
            row["decisions"].append(elapsed)
            if candidate.kind not in ("END_TURN", "HOLD_POSITION"):
                row["boss_actions"] += 1
            # TRICKY's choice in the same state; the timer above has already stopped.
            engine.state.actors[actor].ai_tier = "TRICKY"
            try:
                tricky_context = build_decision_context(engine, policy, for_ai=True)
                tricky = controller.choose_primary_action(tricky_context)
            finally:
                engine.state.actors[actor].ai_tier = "MASTERMIND"
            tricky_pick = {c.candidate_id: c for c in tricky_context.legal_candidates}[tricky.intent.candidate_id]
            if _key(tricky_pick) != _key(candidate):
                row["divergent"] += 1
        digest.update(json.dumps([engine.state.round_number, actor, candidate.kind, candidate.source_definition_id,
                                  list(candidate.target_ids), str(candidate.destination), explanation]).encode())
        engine.execute_intent(choice.intent)
        for aid, a in engine.state.actors.items():
            drop = before[aid] - _hp(a)
            if drop <= 0:
                continue
            if is_boss:
                if a.team_id != boss_team:
                    row["dealt"] += drop
                else:
                    row["taken"] += drop
            elif a.team_id == boss_team:
                row["taken"] += drop
        steps += 1
    terminal = engine.state.terminal_result
    row["replay_sha256"] = digest.hexdigest()
    row["rounds"] = engine.state.round_number
    row["incomplete"] = terminal is None
    row["outcome"] = "INCOMPLETE" if terminal is None else outcome(terminal, boss_team)
    row["steps"] = steps
    log(row)
    return row


def summarize(fights, budget_scale):
    counts = {name: sum(f["outcome"] == name for f in fights) for name in ("WIN", "LOSS", "DRAW", "INCOMPLETE")}
    decided = counts["WIN"] + counts["LOSS"]
    low, high = wilson(counts["WIN"], decided)
    rounds = sum(f["rounds"] for f in fights) or 1
    turns = sum(f["boss_turns"] for f in fights) or 1
    seconds = [s for f in fights for s in f["decisions"]]
    decisions = len(seconds)
    scaled_max = max(seconds, default=0) * budget_scale
    return {"fights": len(fights), **counts, "decided": decided,
            "decided_win_rate": counts["WIN"] / decided if decided else 0,
            "win_rate_95_low": low, "win_rate_95_high": high,
            "draw_rate": counts["DRAW"] / len(fights) if fights else 0,
            "dealt_per_round": sum(f["dealt"] for f in fights) / rounds,
            "taken_per_round": sum(f["taken"] for f in fights) / rounds,
            "actions_per_turn": sum(f["boss_actions"] for f in fights) / turns,
            "divergence_rate": sum(f["divergent"] for f in fights) / decisions if decisions else 0,
            "decisions": decisions,
            "seconds_median": statistics.median(seconds) if seconds else 0,
            "seconds_max": max(seconds, default=0),
            "seconds_max_scaled": scaled_max,
            "within_budget": scaled_max <= BUDGET_SECONDS,
            "plays": sorted({p for f in fights for p in f["plays"]})}


def time_scale():
    """Multiplier on measured seconds for the budget check (CF_AI_TIME_SCALE, default 1.0)."""
    return float(os.environ.get("CF_AI_TIME_SCALE", "1.0"))


def fight_plan(seeds, first_seed=0, arenas=ARENAS, builds=BUILDS):
    """Every fight of a configuration in one fixed order: (number, seed, arena, talents, flight, boss)."""
    plan, n = [], 0
    for seed in range(first_seed, first_seed + seeds):
        for arena in arenas:
            for talents, flight in builds:
                for boss in (OWNER, FOE):
                    n += 1
                    plan.append((n, seed, arena, talents, flight, boss))
    return plan


def run_fight(name, number, seed, arena, talents, flight, boss, scratch, log):
    """One fight under one configuration, so a single CI test can run one fight within its time limit."""
    budget_scale = time_scale()
    with offline_and_switches(CONFIGS[name]):
        row = play_fight(scratch, number, arena, seed, talents, flight, boss, log)
    return {"configuration": name, "switches": CONFIGS[name], "time_scale": budget_scale,
            **summarize([row], budget_scale), "results": [row]}


def run_config(name, seeds, scratch, log, arenas=ARENAS, builds=BUILDS, first_seed=0):
    parts = [run_fight(name, *case, scratch, log) for case in fight_plan(seeds, first_seed, arenas, builds)]
    return merge_reports(parts)[0]


def merge_reports(parts):
    """Join per-seed reports of one configuration and recompute its summary over all fights."""
    by_name = {}
    for part in parts:
        by_name.setdefault(part["configuration"], []).append(part)
    merged = []
    for name, group in by_name.items():
        fights = [row for part in group for row in part["results"]]
        scale = group[0]["time_scale"]
        merged.append({"configuration": name, "switches": group[0]["switches"],
                       "time_scale": scale, **summarize(fights, scale), "results": fights})
    return merged


def markdown(reports):
    lines = ["# MASTERMIND vs TRICKY benchmark and ablation (offline, equal builds, both seats)", "",
             "| config | fights | W | L | D | incomplete | decided win rate [95% CI] | draw rate | dealt/round | taken/round | actions/turn | differs from TRICKY | s/decision median | s/decision max (scaled) | within 3 s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        lines.append(f"| {r['configuration']} | {r['fights']} | {r['WIN']} | {r['LOSS']} | {r['DRAW']} | {r['INCOMPLETE']} | "
                     f"{r['decided_win_rate']:.1%} [{r['win_rate_95_low']:.1%}, {r['win_rate_95_high']:.1%}] | {r['draw_rate']:.1%} | "
                     f"{r['dealt_per_round']:.2f} | {r['taken_per_round']:.2f} | {r['actions_per_turn']:.2f} | "
                     f"{r['divergence_rate']:.1%} | {r['seconds_median']:.3f} | {r['seconds_max']:.3f} ({r['seconds_max_scaled']:.3f}) | "
                     f"{'yes' if r['within_budget'] else 'NO'} |")
    lines += ["", f"Time scale {reports[0]['time_scale']}. Plays seen: " +
              "; ".join(f"{r['configuration']}: {len(r['plays'])}" for r in reports) + ".", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--configs", nargs="+", default=["full"], choices=sorted(CONFIGS))
    ap.add_argument("--out", default=os.environ.get("CF_AI_BENCH_OUT"), required=not os.environ.get("CF_AI_BENCH_OUT"))
    ap.add_argument("--combine", nargs="+", metavar="JSON",
                    help="build the side-by-side table from existing ai_bench_<config>.json files; runs no fights")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.combine:
        reports = merge_reports([json.loads(Path(p).read_text()) for p in args.combine])
        out.mkdir(parents=True, exist_ok=True)
        (out / "ai_bench.md").write_text(markdown(reports))
        print(markdown(reports), flush=True)
        return 0
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="ai_bench_"))
    reports = []
    try:
        def log(row):
            print("AIUP2 FIGHT " + json.dumps({k: row[k] for k in ("outcome", "arena", "seed", "boss", "rounds",
                  "dealt", "taken", "divergent")}), flush=True)
        for name in args.configs:
            report = run_config(name, args.seeds, scratch, log)
            reports.append(report)
            (out / f"ai_bench_{name}.json").write_text(json.dumps(report, indent=2) + "\n")
            print(f"AIUP2 CONFIG {name}: decided win rate {report['decided_win_rate']:.3f}, fights {report['fights']}", flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    (out / "ai_bench.md").write_text(markdown(reports))
    print(markdown(reports), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
