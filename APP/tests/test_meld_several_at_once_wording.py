"""No Meld gate or reviewed row may say a creature benefits from only one Meld.

The owner struck the printed one-Meld limit on 2026-09-29 ("remove that text... it makes
no sense"): several Melds may be active at once. The game already works that way --
``combat/senses.py`` ``melds_of`` returns every active Meld, and each Meld sense asks
about its own talent only. What was left behind was prose: two live code comments beside
correct calls, and two reviewed data strings a reviewer reads when checking a row. Wrong
wording there is not cosmetic -- it is what a later edit reads as intent, which is how the
same stale sentence already had to be corrected in a third file.

These guards fail if the single-Meld wording returns. They are wording guards, not
behaviour: ``tests/test_auto_docket.py`` covers that several Melds really are active at once.
"""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1]

# Every place that states the Meld rule, so a new one is added here rather than left out.
# The first three are the Meld sense gates; the last two are reviewed prose.
GUARDED = (
    "combat/stealth.py",                         # Hide in Darkness gate
    "combat/zones.py",                           # Clearsight gate
    "combat/ext/tabik_dark.py",                  # Dark Slaughter gate
    "combat/rules/feature_status.d/docket.json",  # TAL_DARK_DARKVISION why
    "combat/rules/senses.json",                  # melds.evidence
)

# Sentences that assert a single Meld. The first is the struck printed line itself
# (owner_text_edits.json, TAL_DARK_MELD remove[0]); the rest are the wordings the three
# gates and the two data strings used before this fix.
BANNED = (
    "only one Meld",
    "the one Meld",                    # "only while it is the one Meld it benefits from"
    "the Meld its user benefits from",  # "while it is the Meld its user benefits from"
    "until it chooses another",         # a later grant replacing the Meld already held
)

# The one bare "one Meld" that is still true, and is still printed: the Meld action grants
# one Meld talent to one creature. Several of those may be active at the same time.
PRINTED_MELD_ACTION = "Grant the target one Meld talent you know"


def test_no_guarded_file_asserts_a_single_meld() -> None:
    for rel in GUARDED:
        text = (APP / rel).read_text(encoding="utf-8")
        for phrase in BANNED:
            assert phrase not in text, f"{rel} still asserts a single Meld: {phrase!r}"


def test_bare_one_meld_survives_only_in_the_printed_meld_action() -> None:
    """A spaced "one Meld" claims the character has a single Meld; the printed action's own
    "one Meld talent" does not. A hyphenated "one-Meld" cites the limit the owner struck."""
    for rel in GUARDED:
        text = (APP / rel).read_text(encoding="utf-8")
        residue = text.replace(PRINTED_MELD_ACTION, "")
        assert "one Meld" not in residue, (
            f"{rel} says 'one Meld' outside the printed Meld action; a Meld is one of the "
            "Melds a character benefits from, and several may be active at once"
        )
