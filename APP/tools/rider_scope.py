"""Read and import Pro's rider classifications; this tool does not alter combat rules."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
DATA = APP / "combat/rules/feature_status.d/rider_scope.d"
REASONS = set("campaign social information out_of_fight gm_judgment not_a_rule".split())
KINDS = set("damage healing condition save attack movement economy resource duration area targeting trigger senses other".split())
FIELDS = {"HASNT": "effect_kind", "CANT_TABLE": "reason", "DONE_ELSEWHERE": "evidence", "NEEDS_RULING": "note"}

def authority():
    return json.loads(AUTHORITY.read_text())["mechanics"]

def group(record, mode="sphere"):
    return (record.get("sphere_id") or record.get("kind") or "unknown") if mode == "sphere" else (record.get("kind") or "unknown")

def entries():
    result = []
    for path in sorted(DATA.glob("*.json")):
        result.extend(json.loads(path.read_text()))
    return result

def validate(batch, records, expected):
    if not isinstance(batch, dict) or not isinstance(batch.get("batch"), str) or not isinstance(batch.get("riders"), list):
        raise ValueError("expected batch and riders")
    seen = set()
    for row in batch["riders"]:
        if not isinstance(row, dict):
            raise ValueError("rider must be an object")
        mid, index = row.get("mechanic_id"), row.get("index")
        if not isinstance(mid, str) or type(index) is not int or index < 0:
            raise ValueError("invalid mechanic_id or index")
        key = (mid, index)
        if key in seen:
            raise ValueError(f"duplicate rider: {key}")
        seen.add(key)
        riders = records.get(mid, {}).get("riders", [])
        if index >= len(riders) or row.get("text60") != riders[index][:60]:
            raise ValueError(f"unknown or stale rider: {key}")
        cls = row.get("class")
        if cls not in FIELDS or not isinstance(row.get(FIELDS[cls]), str) or not row[FIELDS[cls]].strip():
            raise ValueError(f"missing or invalid classification: {key}")
        if cls == "HASNT" and row["effect_kind"] not in KINDS or cls == "CANT_TABLE" and row["reason"] not in REASONS:
            raise ValueError(f"invalid classification enum: {key}")
        if cls == "DONE_ELSEWHERE" and not re.fullmatch(r".+:\d+", row["evidence"]):
            raise ValueError(f"invalid evidence citation: {key}")
    if seen != expected:
        raise ValueError(f"batch membership mismatch: {len(expected - seen)} missing, {len(seen - expected)} extra")

def import_batch(path):
    batch = json.loads(Path(path).read_text())
    current = entries()
    name = batch.get("batch")
    expected = {(r["mechanic_id"], r["index"]) for r in current if r["batch"] == name}
    if not expected:
        raise ValueError(f"unknown batch: {name}")
    records = authority()
    validate(batch, records, expected)
    updated = [r for r in current if r["batch"] != name]
    pending = {(r["mechanic_id"], r["index"], r["text60"]): r["pending_merge"]
               for r in current if r.get("class") == "HASNT" and r.get("pending_merge")}
    for row in batch["riders"]:
        imported = dict(row, batch=name, by="pro")
        imported.pop("pending_merge", None)  # Pipeline attribution is not part of Pro's input.
        key = (row["mechanic_id"], row["index"], row["text60"])
        if row["class"] == "HASNT" and key in pending:
            imported["pending_merge"] = pending[key]
        updated.append(imported)
    write_entries(updated, records)

def write_entries(rows, records):
    groups = defaultdict(list)
    for row in rows:
        name = group(records[row["mechanic_id"]]).removeprefix("tianxia.sphere.")
        name = re.sub(r"[^a-z0-9_-]+", "_", name.lower())
        groups[name].append(row)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, values in groups.items():
        (DATA / (name + ".json")).write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")

def stale(rows, records):
    for row in rows:
        riders = records.get(row["mechanic_id"], {}).get("riders", [])
        i = row["index"]
        if i >= len(riders) or riders[i][:60] != row["text60"]:
            yield row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import"); imp.add_argument("file")
    totals = sub.add_parser("totals"); totals.add_argument("--by", choices=["sphere", "kind", "reason"])
    todo = sub.add_parser("todo"); todo.add_argument("sphere")
    sub.add_parser("stale")
    args = parser.parse_args()
    if args.command == "import":
        import_batch(args.file)
        return
    rows, records = entries(), authority()
    if args.command == "stale":
        print(json.dumps(list(stale(rows, records)), ensure_ascii=False, indent=2)); return
    if args.command == "todo":
        selected = [r for r in rows if r["class"] == "HASNT" and group(records[r["mechanic_id"]]).removeprefix("tianxia.sphere.").lower() == args.sphere.lower().removeprefix("tianxia.sphere.")]
        print(json.dumps(selected, ensure_ascii=False, indent=2)); return
    counts = Counter()
    for row in rows:
        if args.by == "reason":
            key = row.get("reason", "(none)")
        elif args.by:
            key = group(records[row["mechanic_id"]], args.by)
        else:
            key = row["class"]
        counts[key] += 1
    print(json.dumps(dict(sorted(counts.items())), indent=2))

if __name__ == "__main__":
    main()
