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
* every entry in the seam's own table produces text, so a mistyped key cannot silently do nothing;
* the seam yields to any other plug-in that already describes the same button (and only a key in its
  SUPERSEDES list may speak over one), so it never takes words away;
* a chunk that cannot compile fails the inventory instead of shrinking it.

The inventory compiles synthetic characters that own every typed record (the same authoring tool the
lane used: tools/empty_card_inventory.py). The fast guards use its chunked pass (~700 records per sheet,
tools.empty_card_inventory.CHUNK): an empty button's own record is always compiled beside it, so the
chunks see every card the full sheet would, in seconds instead of minutes. That is a claim about the
chunker, so one test compiles the authoritative full sheet (one character owning every record) and
fails if the chunked pass misses a single id. The few ids whose words live on another chunk are named in
CROSS_RECORD, and the full-sheet test proves the list stays honest.
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
    # another chunk owns. The full-sheet test below is what proves that superset claim.
    return inventory(chunked=True)


@pytest.fixture(scope="module")
def full_cards() -> list[dict]:
    """The authoritative sheet: one synthetic character owning every typed record.

    No chunk fallback: if that sheet cannot compile, the test fails instead of quietly checking chunks and
    claiming the full sheet passed. Slow on purpose (one compile per module); the chunked fixture keeps the
    other guards fast.
    """
    return inventory(allow_chunk_fallback=False)


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


def test_full_sheet_has_no_empty_card(full_cards):
    """The review's blocking check: the whole sheet, not only the chunker's approximation."""
    empty = _empty(full_cards)
    new = sorted(empty - UNWRITTEN)
    assert new == [], (
        "these action cards render with no body on the full sheet; write their text in "
        "combat/ext/action_card_text.py (or in the plug-in that builds them): " + ", ".join(new))


def test_chunked_inventory_is_a_superset_of_the_full_sheet(cards, full_cards):
    """An empty card the chunked guard cannot see would slip past every fast test."""
    missed = sorted(_empty(full_cards) - _empty(cards))
    assert missed == [], (
        "the chunked inventory misses empty cards that the full sheet shows, so the fast guards are not a "
        "superset; fix the chunker or name the ids' records so every chunk carries their text: "
        + ", ".join(missed))


def test_full_sheet_has_no_picker_only_card(full_cards):
    thin = sorted(_tail(row["id"]) for row in full_cards
                  if row["body_origin"] != "none" and _picker_only(row["body"]))
    assert thin == [], ("these full-sheet cards only say which option they pick, with no rule behind it: "
                        + ", ".join(thin))


def test_every_card_text_record_names_printed_text():
    """A mistyped or renamed printed record would leave the card with its lead sentence and nothing else."""
    from combat.rule_help import printed_rule_text

    missing = sorted(f"{key} -> {record}" for key, (_lead, record) in CARDS.items()
                     if record and not printed_rule_text(record))
    assert missing == [], ("combat/ext/action_card_text.py names printed records that no longer exist, so "
                           "those cards would silently lose the rulebook text: " + ", ".join(missing))


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


def test_card_text_yields_to_another_plugins_more_specific_text():
    """Review 071551 blocking 2: the seam must not overwrite a plug-in's own words for the same button.

    combat/ext/action_help.py already describes a shared "escape a grapple" control, and the card body is
    the first non-empty button_description (combat/action_text.py), read in module-name order -- this
    module sorts first. So the seam answers only for buttons no other hook describes.
    """
    from combat.action_text import describe_action

    row = {"source_definition_id": "action:typed.deadbeef.qi5_break_chains",
           "display_name": "Break Chains of Qi", "economy": "ACTION", "range_ft": 5,
           "parameters": {"typed": {"effects": [{"type": "escape_grapple"}], "numbers": {"escape_bonus": 2}}}}
    assert card_text(row) is None, "the seam shadowed action_help's own escape-a-grapple text"
    assert describe_action(row).startswith("Action: escape a grapple"), (
        "the card body must be the plug-in's escape text, not the seam's Break Chains of Qi lead")


def test_card_text_keeps_its_words_where_the_generic_helper_would_be_wrong():
    """The Tackle button is deliberately in SUPERSEDES: the generic Unarmed Strike helper says "Action: use
    Grapple in place of one unarmed attack", but Tackle is a Bonus Action after a Dash with the replaced
    attack taken out (combat/ext/wrestling_tackle.py)."""
    from combat.ext.action_card_text import SUPERSEDES

    assert SUPERSEDES <= set(CARDS), "a SUPERSEDES key that is not a CARDS entry would silently do nothing"
    row = {"source_definition_id": "action:typed.deadbeef.unarmed.grapple.tackle",
           "display_name": "Tackle: Grapple", "economy": "BONUS_ACTION", "range_ft": 5,
           "parameters": {"typed": {"unarmed_option": "grapple", "effects": [
               {"type": "save", "ability": "STR_OR_DEX",
                "on_fail": [{"type": "condition", "condition": "grappled", "applies_to": "target"}]}]}}}
    text = card_text(row)
    assert isinstance(text, str) and text.startswith("Bonus Action in a turn you took the Dash action"), text


def test_chunked_bundles_raise_when_a_chunk_cannot_compile(monkeypatch):
    """Review 071551 blocking 1: a failed chunk must fail the inventory, not shrink it.

    The old chunked path only printed the failure, so every guard passed on a partial inventory while those
    cards were never compiled.
    """
    from tools import empty_card_inventory as tool

    mechanics = {"m1": {"sphere_id": "s1"}, "m2": {"sphere_id": "s2"}}
    monkeypatch.setattr(tool, "CHUNK", 1)

    def flaky(sheet, **_kwargs):
        learned = (sheet.get("spheres_and_talents") or {}).get("learned_talent_record_ids") or []
        if "m1" in learned:
            raise ValueError("chunk m1 failed")
        return {"action_catalog": []}

    monkeypatch.setattr(tool, "compile_character", flaky)
    with pytest.raises(RuntimeError, match="chunk m1 failed"):
        tool._bundles(mechanics, chunked=True)

