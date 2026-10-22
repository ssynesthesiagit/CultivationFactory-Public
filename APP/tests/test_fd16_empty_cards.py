"""FD-16 guard: no player-visible action card may render with an empty body.

Owner feedback desk FD-16 reported a card titled "Break Chains of Qi" whose body was only
"Action / Range Self / Words used: Qi" -- a compiled button that had a name, an economy and a cost but no
words. The card body is resolved once, by combat/action_text.py: the row's own description, a plug-in's
button_description, the printed record its typed.source names, then the table's compiled evidence. A
button built with none of those renders empty, and nothing failed: the card kept its title and its cost
line, so the hole looked like a design choice.

combat/ext/action_card_text.py is the seam that gives those buttons their own words, keyed by the
button's compiled name. This test keeps the hole closed:

* every compiled button in the table's own card inventory must resolve a body;
* the inventory's unwritten ids are listed explicitly, and an entry that no longer renders empty fails
  (the allowlist may only shrink);
* a body made only of the shared "This button picks: X." filler is not a body;
* every entry in the seam's own table produces text, so a mistyped key cannot silently do nothing.

The inventory compiles synthetic characters that own every typed record (the same authoring tool the
lane used: tools/empty_card_inventory.py). It is slow, but it is the only way to see the buttons a
character only gets by owning another record.
"""
from __future__ import annotations

import pytest

from combat.ext.action_card_text import CARDS, card_text
from tools.empty_card_inventory import inventory


# Cards whose body is still unwritten. FD-16 wrote every one the inventory found, so this set is empty:
# adding an id here is a promise to write it, and the second test fails until the entry is removed.
UNWRITTEN: frozenset[str] = frozenset()

# Buttons whose text lives on a record outside their inventory chunk (the Unarmed Strike's grapple draws its
# words from the Wrestling and Iron Fist records). Keyed by the button's own tail, not the character hash, so
# the entry survives a changed synthetic sheet. Like UNWRITTEN, this list may only shrink.
CROSS_RECORD: frozenset[str] = frozenset({"unarmed.grapple"})

# Bodies that carry no information about the button: the shared picker sentence with no rule behind it.
PICKER_ONLY = "This button picks:"


def _tail(identifier: str) -> str:
    """A compiled button id -> its own name, without the synthetic character's hash."""
    return identifier.split(".", 2)[-1]


def _picker_only(body: str) -> bool:
    """A body that stops at the picker sentence: "This button picks: X." with no rule behind it.

    A picker followed by the owning feature's printed rule (a "####" heading and its text) is a real body,
    so the whole body is judged rather than its first line.
    """
    text = " ".join(body.split())
    if not text.startswith(PICKER_ONLY) or "####" in body:
        return False
    rest = text[len(PICKER_ONLY):].strip()
    return rest.endswith(".") and rest.count(".") <= 1


@pytest.fixture(scope="module")
def cards() -> list[dict]:
    # Chunked on purpose: seconds instead of the full sheet's minutes, and still a superset of the empty cards
    # (an empty button's own record is always compiled with it). CROSS_RECORD carries the few ids whose text
    # another chunk owns.
    return inventory(chunked=True)


def _empty(cards: list[dict]) -> set[str]:
    return {_tail(row["id"]) for row in cards if row["body_origin"] == "none"}


def test_no_player_visible_card_renders_empty(cards):
    empty = _empty(cards)
    new = sorted(empty - UNWRITTEN - CROSS_RECORD)
    assert new == [], (
        "these action cards render with no body; write their text in combat/ext/action_card_text.py (or in "
        "the plug-in that builds them) instead of leaving the title and cost alone: " + ", ".join(new))


def test_unwritten_allowlist_only_shrinks(cards):
    empty = _empty(cards)
    stale = sorted(UNWRITTEN - empty)
    assert stale == [], ("these ids are listed as unwritten but now render a body; delete them from "
                         "UNWRITTEN: " + ", ".join(stale))


def test_cross_record_allowlist_only_shrinks(cards):
    empty = _empty(cards)
    stale = sorted(CROSS_RECORD - empty)
    assert stale == [], ("these ids now render a body inside their own chunk; delete them from CROSS_RECORD: "
                         + ", ".join(stale))


def test_no_card_body_is_only_the_picker_sentence(cards):
    thin = sorted(_tail(row["id"]) for row in cards
                  if row["body_origin"] != "none" and _picker_only(row["body"]))
    assert thin == [], "these cards only say which option they pick, with no rule behind it: " + ", ".join(thin)


def test_every_card_text_entry_produces_a_body():
    """The seam itself: a mistyped key would compile and silently render nothing."""
    for key in CARDS:
        row = {"source_definition_id": f"action:typed.deadbeef.{key}", "display_name": key,
               "parameters": {}, "economy": "ACTION"}
        text = card_text(row)
        assert isinstance(text, str) and text.strip(), key


def test_card_text_is_inert_for_another_plugins_button():
    row = {"source_definition_id": "action:typed.deadbeef.weapon.strike", "display_name": "Strike",
           "parameters": {}, "economy": "ACTION"}
    assert card_text(row) is None
