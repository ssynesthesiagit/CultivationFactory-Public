#!/usr/bin/env python3
"""Build the treasure catalog from the pinned Bible's two treasury chapters.

The checked-in authority supplies published IDs and legacy metadata not printed
in the Bible. A changed or missing existing rule requires reconciliation before
regenerating; new IDs are appended in chapter order.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_treasure_weapon_authority import sha256_bytes, slug  # noqa: E402

CATALOG = "authority/Tianxia_Treasure_Catalog_Authority_R1.json"
TREASURY = "authority/bible/06_treasury_and_armory"
WONDROUS = f"{TREASURY}/04_treasures_and_artifacts.md"
CONSUMABLES = f"{TREASURY}/03_consumables_pills_and_talismans.md"
_ENTRY = re.compile(
    r"^### (?P<name>[^\n]+)\n(?P<meta>\*\*Grade:\*\* [^\n]+)\n"
    r"(?P<body>.*?)(?=^#{1,3} |^---$|\Z)", re.M | re.S,
)
_FIELD = re.compile(r"\*\*([A-Za-z ]+):\*\* (.+)|\*Spheres: (.+)\*")
_ENHANCEMENT = re.compile(
    r"\*\*\+(\d+) enhancement bonus to (Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\*\*",
    re.I,
)


def _entries(raw: bytes):
    text = raw.decode("utf-8")
    for match in _ENTRY.finditer(text):
        start = text.count("\n", 0, match.start()) + 1
        section = match[0].rstrip()
        fields = {}
        for part in match["meta"].split(" · "):
            field = _FIELD.fullmatch(part)
            if field is None:
                raise SystemExit(f"unreadable metadata for {match['name']}: {part!r}")
            key, value, spheres = field.groups()
            fields[key or "Spheres"] = value or spheres
        yield match["name"], fields, match["body"].strip(), {
            "line_start": start, "line_end": start + section.count("\n"),
            "section_sha256": sha256_bytes(section.encode("utf-8")),
        }


def _wondrous(fields: dict, body: str) -> dict:
    item_type, _, body_slot = fields["Type"].partition(" (")
    attunement = fields["Attunement"]
    slots = 0 if attunement == "No Attunement" else int(attunement.split()[0])
    row = {
        "item_type": item_type, "attunement_slots": slots,
        "value_gt": int(fields["Appraisal"].removesuffix(" GT").replace(",", "")),
        "body_slot": body_slot.removesuffix(")") or ("Fingers" if item_type == "Ring" else ""),
    }
    if match := _ENHANCEMENT.search(body):
        if not row["body_slot"] or not slots:
            raise SystemExit("ability-enhancing treasure must print a body slot and attunement cost")
        amount, ability = match.groups()
        row["ability_enhancement"] = {"ability": ability[:3].upper(), "bonus": int(amount)}
    return row


def _consumable(fields: dict, _body: str) -> dict:
    price, batch = fields["Price"].split(" GT per ")
    quantity, unit = batch.split(" ", 1)
    return {
        "family": fields["Family"], "activation": fields["Activation"],
        "batch_price_gt": int(price.replace(",", "")),
        "batch_quantity": int(quantity), "batch_unit": unit,
    }


def _rows(raw: bytes, existing: list[dict], kind: str, parse_fields, guarded_fields: tuple) -> list[dict]:
    identity = "treasure_id" if kind == "wondrous" else "consumable_id"
    by_name = {row["name"]: row for row in existing}
    next_number = max((row["number"] for row in existing), default=0) + 1
    defaults = {"family": "", "construction": ""} if kind == "wondrous" else {"tags": []}
    rows, seen, differences = [], set(), {}
    for name, fields, body, source in _entries(raw):
        if name in seen:
            raise SystemExit(f"duplicate Bible entry: {name}")
        seen.add(name)
        old = by_name.get(name)
        if old is None:
            old = {**defaults, "number": next_number,
                   identity: f"tianxia.treasure.{kind}.{next_number:03d}.{slug(name)}"}
            next_number += 1
        row = {**old, **parse_fields(fields, body), "name": name, "grade": fields["Grade"], "text": body,
               "sphere_influences": [sphere.strip() for sphere in fields["Spheres"].split(",")],
               "source": source}
        if name in by_name:
            changed = [key for key in guarded_fields if old[key] != row[key]]
            if changed:
                differences[name] = ", ".join(changed)
        rows.append(row)
    differences.update((name, "missing by name") for name in by_name.keys() - seen)
    if differences:
        label = "Wondrous" if kind == "wondrous" else "consumable"
        details = "\n".join(f"{name}: {reason}" for name, reason in sorted(differences.items()))
        raise SystemExit(f"STOPPED: {len(differences)} existing {label} rows differ from the Bible\n{details}")
    return sorted(rows, key=lambda row: row["number"])


def build(app: Path, baseline: dict, *, expected_counts=(208, 87)) -> dict:
    """Resolve printed data against the catalog's published names and IDs."""
    wondrous = (app / WONDROUS).read_bytes()
    consumables = (app / CONSUMABLES).read_bytes()
    rows = {
        "wondrous": _rows(wondrous, baseline["wondrous"], "wondrous", _wondrous,
                          ("grade", "attunement_slots", "text")),
        "consumables": _rows(consumables, baseline["consumables"], "consumable", _consumable,
                             ("grade", "activation", "family", "batch_price_gt", "batch_quantity", "batch_unit", "text")),
    }
    wondrous_count, consumable_count = expected_counts
    if [row["number"] for row in rows["wondrous"]] != list(range(1, wondrous_count + 1)):
        raise SystemExit(f"expected Wondrous Treasures 1-{wondrous_count}, found {len(rows['wondrous'])}")
    # Legacy consumable numbers have gaps for excluded Immortal entries.
    if len({row["number"] for row in rows["consumables"]}) != consumable_count:
        raise SystemExit(f"expected {consumable_count} consumables, found {len(rows['consumables'])}")
    return {
        **baseline, **rows,
        "sources": {
            "bible_treasures": {"path": WONDROUS, "sha256": sha256_bytes(wondrous)},
            "bible_consumables": {"path": CONSUMABLES, "sha256": sha256_bytes(consumables)},
        },
        "counts": {kind: len(entries) for kind, entries in rows.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP / CATALOG)
    args = parser.parse_args()
    baseline = json.loads((APP / CATALOG).read_text(encoding="utf-8"))
    authority = build(APP, baseline)
    args.output.write_text(json.dumps(authority, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(authority["counts"]), sha256_bytes(args.output.read_bytes()))


if __name__ == "__main__":
    main()
