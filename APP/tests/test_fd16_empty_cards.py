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

# Bodies that carry no information about the button: the shared picker sentence with no rule behind it.
PICKER_ONLY = "This button picks:"


def _picker_only(body: str) -> bool:
    """A body that stops at the picker sentence: "This button picks: X." with no rule behind it."""
    text = " ".join(body.split())
    if not text.startswith(PICKER_ONLY):
        return False
    return text[len(PICKER_ONLY):].count(".") <= 1


@pytest.fixture(scope="module")
def cards() -> list[dict]:
    return inventory()


def test_no_player_visible_card_renders_empty(cards):
    empty = {row["id"] for row in cards if row["body_origin"] == "none"}
    new = sorted(empty - UNWRITTEN)
    assert new == [], (
        "these action cards render with no body; write their text in combat/ext/action_card_text.py (or in "
        "the plug-in that builds them) instead of leaving the title and cost alone:\n" + "\n".join(new))


def test_unwritten_allowlist_only_shrinks(cards):
    empty = {row["id"] for row in cards if row["body_origin"] == "none"}
    stale = sorted(UNWRITTEN - empty)
    assert stale == [], ("these ids are listed as unwritten but now render a body; delete them from "
                         "UNWRITTEN:\n" + "\n".join(stale))


def test_no_card_body_is_only_the_picker_sentence(cards):
    thin = sorted(row["id"] for row in cards
                  if row["body_origin"] != "none" and _picker_only(row["current_body"]))
    assert thin == [], "these cards only say which option they pick, with no rule behind it:\n" + "\n".join(thin)


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
