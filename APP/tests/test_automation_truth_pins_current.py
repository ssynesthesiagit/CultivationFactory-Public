"""Every reviewed-source pin must match the source shipped in this checkout.

The automation-truth proofs fail closed, but each proof only reads the dependency
paths its own bounded shape needs.  A stale whole-file pin on a shared dependency
(``combat/ext/__init__.py`` after a doc edit, for example) can therefore leave the
pinned review silently pointing at older bytes while only the proofs that happen
to read that file go red.  This check covers every path either pin table names, so
a branch that changes a pinned file without a reviewed refresh fails here with the
exact file to re-review.

It hashes the working tree only: no ``git show``/history read, no private fixture,
so the public mirror can run it.  Refresh with::

    python3 tools/build_automation_truth_pins.py --reviewed-ref HEAD --write
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools import automation_truth_effects
from tools import automation_truth_plugin_proofs

ROOT = Path(__file__).resolve().parents[2]

PINS: dict[str, list[tuple[str, str]]] = {}
for _table, _pins in (
    ("automation_truth_effects", automation_truth_effects._REVIEWED_SHA256),
    ("automation_truth_plugin_proofs", automation_truth_plugin_proofs._REVIEWED_SHA256),
):
    for _relative, _digest in _pins.items():
        PINS.setdefault(_relative, []).append((_table, _digest))


@pytest.mark.parametrize("relative", sorted(PINS))
def test_reviewed_pin_matches_checked_in_source(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file(), f"{relative} is pinned by the automation-truth proofs but missing"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    stale = [f"{table} ({digest[:12]}...)" for table, digest in PINS[relative] if digest != actual]
    assert not stale, (
        f"{relative} changed after its review; stale pin(s): {', '.join(stale)}. "
        "Re-review the change, then run tools/build_automation_truth_pins.py --reviewed-ref HEAD --write."
    )
