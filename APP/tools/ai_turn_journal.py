"""Byte-level journal comparison for the AI-turn measurement probe.

A shorter played journal is an intentional prefix (e.g. an until-turn run),
not a divergence. Never normalize JSON: the host requires identical bytes.
"""
from __future__ import annotations

import hashlib
import json
from itertools import zip_longest
from pathlib import Path


def journal_summary(journal: Path, reference: Path | None = None) -> dict:
    """Hash the played bytes and find the first differing played event, if any."""
    played = journal.read_bytes()
    lines = played.splitlines(keepends=True)
    events = [json.loads(line) for line in lines]
    first_difference = None
    if reference is not None:
        reference_lines = reference.read_bytes().splitlines(keepends=True)
        for line, expected, event in zip_longest(lines, reference_lines, events):
            if line is None:  # reference may legitimately continue beyond this run
                break
            if line != expected:
                first_difference = event["sequence"]
                break
    return {"journal_md5": hashlib.md5(played).hexdigest(),
            "last_sequence": events[-1]["sequence"] if events else 0,
            "first_different_sequence": first_difference}
