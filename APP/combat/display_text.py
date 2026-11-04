"""Shared, read-only player-facing text helpers for the owner's printed records.

Shared by combat/status_text.py, combat/tabletop.py and combat/factory_compiler.py.
It only reformats text that already exists: it reads no engine state, prices
nothing, resolves no effect and never changes what a button does. Every helper here
is general -- it works from the printed text and the ability's name, never from an
ability id -- so one implementation serves every ability.

Two jobs:

  * ``printed_headers`` tidies the printed "Key: value" block that every printed
    ability carries (Action Type / Range / Area / Duration / Cost / Concentration /
    Tags...).  Two defects come from the same place: a free ability prints its cost
    as the literal ``None``, which reads as a broken value rather than "this costs
    nothing", and a few printed records lost the line break between two header
    lines, so the owner reads one run-together word (``Cost: NoneConcentration:
    Not required``).  Both are fixed here, once, for every ability.
  * ``augment_toggle_label`` names the fight button for an augment toggle, including
    the one that clears every augment back off an ability.
"""
from __future__ import annotations

import re
from typing import Any

#: What a free ability costs, said the way a player would say it. Printed as the whole
#: header line in place of a missing/``None`` cost, so it never shows a code value.
#:
#: It says only what it knows: no *resource* cost. An ability can cost no resources and
#: still take an Action, a Bonus Action or a Reaction -- Darkness, Minor Illusion, Shadow
#: Stash and Carry Voice are all printed with a missing cost *and* a timing
#: requirement -- so promising "no action" here would tell a player to use them for
#: free. The ability's own ``Action Type`` / ``Timing Detail`` header lines say what it
#: costs to use, and they are never touched.
FREE_COST_LINE = "Cost: no resource cost"
#: The same words, for a printed cost that goes on to explain itself ("None, or 1 CP
#: for extended use"): the owner's own words after it are kept.
FREE_COST_VALUE = "no resource cost"

#: Header keys the owner's printed records use. Only these split a run-together line,
#: so ordinary prose that happens to contain a colon is never touched.
HEADER_KEYS = (
    "Action Type", "Area", "Concentration", "Duration", "Effect", "Prerequisite",
    "Range", "Requirement", "Save", "Tag", "Tags", "Target", "Time", "Trigger",
    "Use Limit",
)

#: A printed header line: "Key: value" at the start of a line. The owner's records write
#: some headers in markdown bold ("**Cost:** 2 CP"), so the emphasis markers are allowed
#: around the key and the value is matched on the raw line.
_HEADER_LINE = re.compile(r"^[ \t]{0,3}(?:\*\*|__|`)*[A-Z][A-Za-z ]{0,28}(?:\*\*|__|`)*:")
#: The next header key appearing with no separator, e.g. "...None" + "Concentration: ".
_RUN_TOGETHER = re.compile(r"(?<=[A-Za-z0-9])(?=(?:%s): )" % "|".join(re.escape(key) for key in HEADER_KEYS))
#: A cost header line: the key up to its colon, and the value after it.  The key is
#: captured rather than matched literally because the owner writes the colon inside the
#: markdown bold ("**Cost:** None"), and both that and a bare "Cost: None" must be read.
_COST_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[^:\n]{0,24}):(?P<close>\*+|_+|`+)?(?P<value>.*)$")
#: Markdown emphasis, dropped before a header key or cost value is read.
_MARKUP = str.maketrans("", "", "*_`")
#: Values that mean the printed record never gave a cost. Text that already reads
#: correctly ("Cost: 0", "Cost: free") is left exactly as the owner printed it.
_MISSING_COST = {"", "none", "null", "nil", "-", "--", "—", "n/a", "na"}
#: A missing value at the start of a cost, but not the start of a longer word
#: ("Noneconcentration" is not a missing cost).
_LEADING_MISSING = re.compile(
    r"^(?:%s)(?=\W|$)" % "|".join(re.escape(marker) for marker in sorted(_MISSING_COST, key=len, reverse=True) if marker),
    re.I,
)


def _bare(text: str) -> str:
    """A header key or cost value with its markdown emphasis removed."""
    return str(text).translate(_MARKUP).strip()


def _split_run_together(line: str) -> str:
    """Put back the line break a printed record lost between two of its header lines.

    Only a line that is itself a header line is split, and only before one of
    ``HEADER_KEYS``, so "Duration: Concentration, up to 1 minute" is left alone.
    """
    if not _HEADER_LINE.match(line.strip()):
        return line
    return _RUN_TOGETHER.sub("\n", line)


def _readable_cost(line: str) -> str:
    """Say what a missing cost means instead of printing ``None``.

    A cost that is only a missing value becomes the plain ``FREE_COST_LINE``. A cost
    that then goes on to explain itself ("None, or 1 CP for extended use") keeps the
    header and the owner's own words, and only the missing word is put into English.
    """
    match = _COST_LINE.match(line)
    if match is None or _bare(match["key"]).casefold() != "cost":
        return line
    value = _bare(match["value"])
    if not _LEADING_MISSING.match(value):
        return line
    if value.rstrip(".,;:").strip().casefold() in _MISSING_COST:
        return f"{match['indent']}{FREE_COST_LINE}"
    replaced = _LEADING_MISSING.sub(FREE_COST_VALUE, value, count=1)
    return f"{match['indent']}{match['key']}:{match['close'] or ''} {replaced}"


def printed_headers(text: Any) -> str:
    """Tidy the printed header block of an ability's rules for a player.

    A missing or ``None`` cost reads as ``FREE_COST_LINE`` and two header lines that
    ran together are split back apart. The rules themselves are never changed, and
    text with no printed header block is returned unchanged apart from that cleanup.
    """
    lines = str(text or "").split("\n")
    out = []
    for line in lines:
        line = _split_run_together(line)
        for piece in line.split("\n"):
            out.append(_readable_cost(piece))
    return "\n".join(out)


def augment_toggle_label(ability_name: str, augment_name: str | None) -> str:
    """The fight button's label for an augment toggle on an ability.

    ``augment_name`` is the augment's printed name for one of the real choices, and
    ``None`` for the single button that clears every augment back off the ability.
    The clear button used to read "Augment Darkness: none", which reads as a broken
    value rather than the button that removes them all; it now says what it does.
    Every augmentable ability gets the same wording, and the real choices are
    unchanged. Display only: the label is not part of a candidate's identity.
    """
    name = str(ability_name or "this ability")
    if augment_name:
        return f"Augment {name}: {augment_name}"
    return f"Augment {name}: no augments (clears all of them)"
