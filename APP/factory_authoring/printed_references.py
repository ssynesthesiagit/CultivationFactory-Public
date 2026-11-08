"""Printed-reference admission for standalone stealth and legacy zone profiles.

New fight actions and zone profiles exchange IDs. Older saved profiles and the
standalone authoring API may carry a printed heading, resolved unambiguously
against immutable rules text, never against the editable display-label table.
"""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def source_headings():
    texts = json.loads((Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json").read_text())
    by_heading = {}
    for rid, text in texts.items():
        head = re.sub(r"^#+\s*", "", text.split("\n", 1)[0]).split(" - ", 1)[0]
        by_heading.setdefault(head, []).append(rid)
    return texts, by_heading


def printed_heading_id(heading):
    """Admit only a unique immutable heading, never an arbitrary display label."""
    _texts, headings = source_headings()
    matches = headings.get(heading) or []
    return matches[0] if len(matches) == 1 else None


def printed_reference_id(reference):
    texts, headings = source_headings()
    if reference in texts:
        return reference
    return printed_heading_id(reference) if reference in headings else reference
