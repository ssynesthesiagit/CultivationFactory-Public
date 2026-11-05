#!/usr/bin/env python3
"""Observed phase-1 measurements, paired comparisons, then limited inference.

No fight outcome or win rate is inferred from a decision replay. Unknown
reference/usefulness labels are reported as unknown, not counted as failures.
"""
import argparse
from collections import defaultdict
import itertools
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.menuprune_replay import canonical, identity, jsonl


def metric(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    if field.endswith("_top_k_in_menu"):
        values = [v for group in values for v in group]
    return {"n": len(values), "percent": 100 * sum(bool(v) for v in values) / len(values) if values else None}


def mean(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return statistics.mean(values) if values else None


def summarize(rows, expected_decisions=200):
    if not 1 <= expected_decisions <= 200:
        raise ValueError("Expected decisions must be 1..200")
    groups, by_model, seen = defaultdict(list), defaultdict(dict), set()
    for row in rows:
        key = (row["model"], row["arm"], *identity(row))
        if key in seen:
            raise ValueError("Duplicate replay identity: refusing double-counted evidence")
        seen.add(key)
        groups[row["model"], row["arm"]].append(row)
        by_model[row["model"]].setdefault(identity(row), {})[row["arm"]] = row
    table = []
    for (model, arm), group in sorted(groups.items()):
        table.append({"model": model, "arm": arm, "decisions": len(group),
            "successful": sum(r.get("pick") is not None and not r.get("error") for r in group),
            "builtin_coverage": metric(group, "built_in_in_menu"),
            "mastermind_coverage": metric(group, "mastermind_top_k_in_menu"),
            "tricky_coverage": metric(group, "tricky_top_k_in_menu"),
            "end_while_useful": metric(group, "end_while_useful"),
            "only_in_larger_menu": metric(group, "only_in_larger_menu"),
            "fallback": metric(group, "fallback"),
            "menu_size": mean(group, "menu_size"), "menu_bytes": mean(group, "menu_bytes"),
            "candidate_ms": mean(group, "candidate_generation_ms"),
            "inference_ms": mean(group, "inference_ms"),
            "ordering_confounds": sum(bool(r.get("common_order_changed")) for r in group),
            "errors": [r["error"] for r in group if r.get("error")]})
    paired = []
    for model, decisions in sorted(by_model.items()):
        valid = []
        for arms in decisions.values():
            if (set(arms) == {"A", "B", "C"} and
                all(r.get("pick") is not None and not r.get("error") and not r.get("fallback") and
                    r.get("a_byte_identical") and not r.get("common_order_changed") for r in arms.values()) and
                len({r.get("state_sha256") for r in arms.values()}) == 1):
                valid.append(arms)
        pairs = {}
        for left, right in itertools.combinations("ABC", 2):
            matches = sum(canonical(arms[left]["pick"]) == canonical(arms[right]["pick"]) for arms in valid)
            pairs[left + right] = 100 * matches / len(valid) if valid else None
        agreed = sum(len({canonical(arms[a]["pick"]) for a in "ABC"}) == 1 for arms in valid)
        agreement = 100 * agreed / len(valid) if valid else None
        complete = len(valid) == expected_decisions and len(decisions) == expected_decisions
        paired.append({"model": model, "complete_valid_triplets": len(valid),
                       "observed_decisions": len(decisions), "expected_decisions": expected_decisions,
                       "pair_agreement_percent": pairs, "abc_agreement_percent": agreement,
                       "stop": complete and agreement >= 95})
    return {"observation": table, "paired_measurement": paired,
            "inference": "Stop only with complete, unconfounded >=95% A/B/C agreement; otherwise inspect differences/errors. No live-default recommendation or fight outcome is implied."}


def show_metric(value):
    return "unknown" if value["percent"] is None else f'{value["percent"]:.1f}% (n={value["n"]})'


def number(value):
    return "unknown" if value is None else f"{value:.1f}"


def render(report):
    lines = ["# MENUPRUNE1", "", "## Observation (phase 1; no fight outcomes)", "",
        "| Model | Arm | Rows / success | Built-in | MASTERMIND top-k | TRICKY top-k | END while useful | Larger-only | Fallback | Menu count / bytes | Candidate ms | Inference ms |",
        "|---|---|---:|---|---|---|---|---|---|---|---:|---:|"]
    for row in report["observation"]:
        cells = [row["model"], row["arm"], f'{row["decisions"]} / {row["successful"]}']
        cells += [show_metric(row[k]) for k in ("builtin_coverage", "mastermind_coverage",
                  "tricky_coverage", "end_while_useful", "only_in_larger_menu", "fallback")]
        cells += [number(row["menu_size"]) + " / " + number(row["menu_bytes"]),
                  number(row["candidate_ms"]), number(row["inference_ms"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Paired measurement", ""]
    for row in report["paired_measurement"]:
        pairs = ", ".join(k + "=" + number(v) + "%" for k, v in row["pair_agreement_percent"].items())
        lines.append(f'- {row["model"]}: {row["complete_valid_triplets"]}/{row["expected_decisions"]} valid triplets; '
                     f'{pairs}; ABC={number(row["abc_agreement_percent"])}%; stop={row["stop"]}.')
    lines += ["", "## Errors and confounds", ""]
    for row in report["observation"]:
        lines.append(f'- {row["model"]}/{row["arm"]}: {row["ordering_confounds"]} common-order changes; {len(row["errors"])} errors.')
        for error in sorted(set(row["errors"])):
            lines.append("  - " + error.replace("\n", " "))
    lines += ["", "## Inference", "", report["inference"], ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--expected-decisions", type=int, default=200)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = summarize([row for path in args.files for row in jsonl(path)], args.expected_decisions)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print(render(report))


if __name__ == "__main__":
    main()
