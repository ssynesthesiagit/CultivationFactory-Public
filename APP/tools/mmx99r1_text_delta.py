"""MMX99r1: compare the base cleaner (e9c34d96) with the fixed one, text by text.

The lane changes what the player reads, so "the fights still replay" is not
enough on its own: this lists EVERY printed text whose reading differs between
the two cleaners, so each one can be named as an intended difference or sent
back as an accident.

    APP=/var/tmp/auto-audit/wt-mmx99/APP BASE=/var/tmp/auto-audit/mmx99r1-base \
        python tools/mmx99r1_text_delta.py > /var/tmp/mmx99r1-text-delta.txt

BASE is an APP directory containing another revision's cleaner. With no BASE the
baseline is the frozen copy of e9c34d96's cleaner in
tests/fixtures/mmx99r1_base_cleaner_e9c34d96.py (not the original lane base
42e43e14, which has no shared cleaner), so this comparison needs no repository
history. Both cleaners read the same original head inputs, including uncleaned
condition readings. This measures cleaner differences, not all presentation
changes between two repository revisions.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

APP = pathlib.Path(os.environ.get("APP", pathlib.Path(__file__).resolve().parents[1]))
BASE = pathlib.Path(os.environ["BASE"]) if os.environ.get("BASE") else None
BASE_REF = "e9c34d96"
FROZEN_BASELINE = APP / "tests/fixtures/mmx99r1_base_cleaner_e9c34d96.py"
sys.path.insert(0, str(APP))

from combat.condition_text import READING, rules as condition_rules  # noqa: E402


def raw_condition_readings() -> dict[str, str]:
    """Use the catalogue's original inputs, before either cleaner can delete text."""
    table = condition_rules().get("conditions") or {}
    return {key: str(READING.get(key) or (table.get(key) or {}).get("_rule", ""))
            for key in sorted(set(table) | set(READING))}


def _load_base_cleaner():
    """The baseline cleaner: BASE's combat/player_text.py, else the frozen e9c34d96 copy."""
    path = BASE / "combat/player_text.py" if BASE is not None else FROZEN_BASELINE
    spec = importlib.util.spec_from_file_location("mmx99r1_base_player_text", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    base = _load_base_cleaner()
    from combat import player_text as head

    rules = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text(encoding="utf-8"))

    rows = []
    for key in sorted(rules):
        before, after = base.plain(rules[key]), head.plain(rules[key])
        if before != after:
            rows.append(("printed record", key, before, after))
    conditions = raw_condition_readings()
    for key, raw in conditions.items():
        before = base.reading(raw)
        after = head.reading(raw)
        if before != after:
            rows.append(("condition reading", key, before, after))

    print(f"cleaner baseline: {BASE if BASE is not None else BASE_REF}")
    print("inputs: original head printed records and uncleaned condition readings")
    print(f"texts compared: {len(rules) + len(conditions)}")
    print(f"texts changed: {len(rows)}")
    for kind, key, before, after in rows:
        print(f"\n=== {kind}: {key}\n  BASE: {before!r}\n  HEAD: {after!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
