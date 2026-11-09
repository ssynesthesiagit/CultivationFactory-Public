"""Turn seat decision records into training rows: state, options, label.

Reads the live decision log (seat_decisions.jsonl, plus its .1 rotation) and,
with --backfill-matches, saved fights' Agent_Decisions.jsonl files. Those
older rows keep the chosen and built-in menu entries but not the exact prompt
text, so they are exported with state set to null and marked "source":
"backfill". Output is one JSON object per line.

The live recorder and the saved match log both write a row for the same
decision, keyed by (match_id, decision_id). A saved row is skipped when that
exact key already has a live row, so the same decision is never exported
twice. Older saved rows from before the saved log carried decision_id have
no such key and are kept rather than collapsed together, since a shared
"missing" id does not mean they are the same decision.

Usage:
  seat_records_export.py --data-dir DIR --out rows.jsonl
  seat_records_export.py --data-dir DIR --out rows.jsonl --backfill-matches DIR/Combat/Matches
"""
import argparse
import json
from pathlib import Path

FILE_NAME = "seat_decisions.jsonl"


def read_lines(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def training_row(record):
    """One row: what the seat saw, what it could pick, and the label it chose.

    The label is the chosen offered id. built_in_id is the teacher label for
    the same menu. Rows without an offered id (fallbacks outside the menu)
    keep label None so training can skip them.
    Ranked plans export each prompt response separately. record_type identifies
    navigation versus combat steps; plan_decision_id links them to the assembled
    plan without assigning that plan the final End frame's label.
    """
    return {"source": "live", "match_id": record.get("match_id"), "decision_id": record.get("decision_id"),
            "kind": record.get("kind"), "provider_id": record.get("provider_id"),
            "state": record.get("prompt"), "options": record.get("options", {}),
            "label": record.get("chosen_id"), "teacher_label": record.get("built_in_id"),
            "chosen": record.get("chosen"), "built_in_pick": record.get("built_in_pick"),
            "fallback": record.get("fallback"),
            "probabilities": record.get("probabilities"),
            **{key: record[key] for key in ("plan_decision_id", "record_type", "reply", "attempt",
                                          "assembled_plan", "plan_fallback") if key in record}}


def backfill_row(match_id, row):
    """A saved-fight decision in the live schema, or None when it cannot be rebuilt.

    The live runner saves chosen, built_in_pick, decision.choice and decision.probabilities
    (see runner._decide). Only D1 letter rows also keep decision_menu, the full
    offered menu, so only those get labels. Other saved rows keep no offered
    menu and are skipped rather than given invented ids.

    chosen and built_in_pick are the actual executed answer and the built-in
    teacher's raw pick (an action id for TURN, a structured response for
    REACTION); they are kept as-is, separately from label/teacher_label,
    which are the same values translated into the saved D1 letter menu and
    are often null because that translation only exists for a letter reply.
    """
    offered = row.get("decision_menu")
    if not isinstance(offered, dict) or not offered:
        return None
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    chosen = decision.get("choice")
    pick = row.get("built_in_pick")
    built = pick if isinstance(pick, str) and pick in offered else None
    return {"source": "backfill", "match_id": match_id, "decision_id": row.get("decision_id"),
            "kind": row.get("kind"), "provider_id": row.get("provider_id"), "state": None,
            "options": offered, "label": chosen if chosen in offered else None,
            "teacher_label": built,
            "chosen": row.get("chosen"), "built_in_pick": row.get("built_in_pick"),
            "fallback": row.get("fallback"), "probabilities": decision.get("probabilities")}


def export(data_dir, out, backfill=None):
    data_dir = Path(data_dir)
    rows = []
    for path in (data_dir / (FILE_NAME + ".1"), data_dir / FILE_NAME):
        rows += [training_row(r) for r in read_lines(path)]
    # The same decision can be in both the live log and a saved fight's own
    # Agent_Decisions.jsonl. Skip a backfilled row only when its (match_id,
    # decision_id) exactly matches a live row; a missing decision_id (older
    # saved rows) never counts as a match, so historical rows are kept.
    live_keys = {(r["match_id"], r["decision_id"]) for r in rows if r["decision_id"] is not None}
    if backfill is not None:
        for log in sorted(Path(backfill).glob("*/Agent_Decisions.jsonl")):
            match_id = log.parent.name
            built = (backfill_row(match_id, r) for r in read_lines(log) if r.get("kind") in {"TURN", "REACTION"})
            for row in built:
                if row is None:
                    continue
                if row["decision_id"] is not None and (row["match_id"], row["decision_id"]) in live_keys:
                    continue
                rows.append(row)
    Path(out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--backfill-matches")
    args = parser.parse_args(argv)
    count = export(args.data_dir, args.out, args.backfill_matches)
    print(f"wrote {count} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
