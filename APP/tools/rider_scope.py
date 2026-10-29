"""Read-only rider scope inventory; unreviewed riders are explicitly unclassified.

Annotations live in feature_status.d beside feature-level scope; exact rider text
guards against silently transferring a classification to a changed or moved rider.
Run from APP with: python -m tools.rider_scope
"""
from collections import Counter
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
CLASSES = ("CANT_TABLE", "HASNT", "DONE_ELSEWHERE", "NEEDS_RULING")


def totals(mechanics, status_dir):
    counts = Counter({name: 0 for name in CLASSES})
    seen = set()
    for path in sorted(status_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for mechanic, annotations in data.get("rider_scope", {}).items():
            riders = mechanics[mechanic].get("riders", [])
            for row in annotations:
                index = row["index"]
                key = (mechanic, index)
                if (key in seen or not isinstance(index, int) or isinstance(index, bool)
                        or index < 0 or index >= len(riders) or row["text"] != riders[index]):
                    raise ValueError(f"duplicate or stale rider annotation: {key}")
                if row["class"] not in CLASSES or not row.get("reason") or not row.get("by"):
                    raise ValueError(f"incomplete rider annotation: {key}")
                if row["class"] == "DONE_ELSEWHERE" and not row.get("citation"):
                    raise ValueError(f"missing code citation: {key}")
                seen.add(key)
                counts[row["class"]] += 1
    counts["UNCLASSIFIED"] = sum(len(m.get("riders", [])) for m in mechanics.values()) - len(seen)
    return counts


def main():
    authority = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
    counts = totals(authority["mechanics"], APP / "combat/rules/feature_status.d")
    for name in (*CLASSES, "UNCLASSIFIED"):
        print(f"{name}: {counts[name]}")


if __name__ == "__main__":
    main()
