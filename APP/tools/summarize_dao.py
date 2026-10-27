"""SOL166 benchmark summary plus offline Dao-policy agreement.

Usage: python summarize_dao.py results.json disposable-fight-root
Old logs retain only built_in_pick: report unknown top-2 rather than guessing.
New seat logs retain dao_policy_top2 (turn keys or reaction answer dicts).
Fidelity concerns the first step, not the execution/replanning of a whole turn.
Fallbacks and STEP records are not model decisions and are excluded.
"""
import json
import math
from pathlib import Path
import statistics
import sys


def dao_fidelity(decisions):
    measured = []
    for d in decisions:
        if d.get("kind") not in {"TURN", "REACTION"} or d.get("fallback"):
            continue
        chosen = d["chosen"][0] if d["kind"] == "TURN" else d["chosen"]
        # Compare mechanical fields only, never a transport/fallback annotation.
        def mechanical(value):
            if isinstance(value, dict):
                return {k: value.get(k) for k in ("selection", "option_ids", "spend")}
            return value
        chosen = mechanical(chosen)
        preferred = mechanical(d["built_in_pick"])
        ranking = d.get("dao_policy_top2")
        top1 = chosen == preferred
        top2 = (chosen in [mechanical(v) for v in ranking[:2]] if ranking is not None else
                True if top1 else None)
        measured.append({"fighter": d["actor_id"], "kind": d["kind"],
                         "top1": top1, "top2": top2})

    def aggregate(rows):
        known = [r for r in rows if r["top2"] is not None]
        return {"model_decisions": len(rows),
                "top1": sum(r["top1"] for r in rows),
                "top1_rate": sum(r["top1"] for r in rows) / len(rows) if rows else None,
                "top2": sum(r["top2"] for r in known), "top2_measured": len(known),
                "top2_unknown": len(rows) - len(known),
                "top2_rate": sum(r["top2"] for r in known) / len(known) if known else None}
    return {"overall": aggregate(measured),
            "per_fighter": {fighter: aggregate([r for r in measured if r["fighter"] == fighter])
                            for fighter in sorted({r["fighter"] for r in measured})},
            "decisions": measured}


def summarize(rows, root):
    root = Path(root)
    outcomes, all_decisions, decision_sources = [], {}, []
    for row in rows:
        index = int(row["seed"].rsplit("-", 1)[1])
        logs = list((root / f"{row['arm']}-{index}").rglob("Agent_Decisions.jsonl"))
        decisions = [d for log in logs for d in map(json.loads, log.read_text().splitlines())
                     if d.get("kind") in {"TURN", "REACTION"}]
        # An empty/STEP-only capture must not erase retained benchmark decisions.
        # Report the selected source so an empty or mislocated root is visible.
        source = "capture" if decisions else "metrics"
        if not decisions:
            decisions = [d for d in row.get("decisions", [])
                         if d.get("kind") in {"TURN", "REACTION"}]
        decision_sources.append({"arm": row["arm"], "seed": row["seed"],
                                 "source": source if decisions else "missing",
                                 "decisions": len(decisions), "logs": len(logs)})
        all_decisions.setdefault(row["arm"], []).extend(decisions)
        outcomes.append({"arm": row["arm"], "pair": row["pair"], "seed": row["seed"],
                         "result": "win" if row.get("winner") == "team:factory" else
                                   "loss" if row.get("winner") == "team:opponents" else
                                   "draw" if row.get("terminal") else "capped",
                         **{k: row.get(k) for k in ("terminal", "hp", "replay", "calls", "censored", "error_type")}})
    aggregates = []
    # Preserve original arms and include named models such as Qwen/Haiku/Luna.
    present = {row["arm"] for row in rows}
    arms = [arm for arm in dict.fromkeys(["mirror", "iteration0", "iteration1", *all_decisions])
            if arm in present]
    for arm in arms:
        matches = [r for r in rows if r["arm"] == arm]
        ds = all_decisions.get(arm, [])
        successful = [d for d in ds if not d["fallback"]]
        latency = sorted(d["latency_ms"] for d in ds)
        def agrees(d):
            return (d["chosen"][0] if d["kind"] == "TURN" else d["chosen"]) == d["built_in_pick"]
        calls = sum(r.get("calls", 0) for r in matches)
        aggregates.append({"arm": arm, "fights": len(matches), "decisions": len(ds),
                           "calls": calls, "fallbacks": sum(bool(d["fallback"]) for d in ds),
                           "invalid_replies": sum(d.get("invalid_replies", int(bool(d["fallback"]))) for d in ds),
                           "invalid_counter": "measured" if arm == "iteration1" else "inferred scripted formatting failure" if arm == "iteration0" else "not applicable",
                           "latency_p50_ms": statistics.median(latency) if latency else None,
                           "latency_p95_ms": latency[math.ceil(.95 * len(latency)) - 1] if latency else None,
                           "tokens": "unknown" if ds else "not applicable",
                           "successful_agreement": f"{sum(agrees(d) for d in successful)}/{len(successful)}" if ds else None,
                           "mean_prompt_chars": round(sum(r.get("prompt_chars", 0) for r in matches) / calls) if calls else None,
                           "wins": sum(r.get("winner") == "team:factory" for r in matches),
                           "losses": sum(r.get("winner") == "team:opponents" for r in matches),
                           "draws": sum(bool(r.get("terminal")) and r.get("winner") is None for r in matches),
                           "capped": sum(not r.get("terminal") for r in matches),
                           "replay_passes": sum(r.get("replay") == "PASS" for r in matches),
                           "dao_fidelity": dao_fidelity(ds)})
    return {"aggregate": aggregates, "outcomes": outcomes,
            "decision_sources": decision_sources,
            "dao_fidelity": dao_fidelity([d for ds in all_decisions.values() for d in ds])}


if __name__ == "__main__":
    print(json.dumps(summarize(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])), indent=2))
