"""Owner rule 2026-10-10: owner-written name/concept/title always win; the AI may only add to them.
Real case: a locked concept with two spaces after a period blocked a build (AI/browser collapse spaces)."""
from character_creation import delegated_choice_authority as dca

OWNER = "This is an evil demonic cultivator.  He comes from the jungle.\nHe wields a blowgun."
COLLAPSED = "This is an evil demonic cultivator. He comes from the jungle. He wields a blowgun."


def test_whitespace_only_difference_keeps_owner_exact_text():
    assert dca._owner_wins(OWNER, COLLAPSED) == OWNER
    assert dca._owner_wins(OWNER, "  " + COLLAPSED + " ") == OWNER


def test_ai_addition_is_kept():
    added = COLLAPSED + " His blowgun darts carry spores."
    assert dca._owner_wins(OWNER, added) == added


def test_ai_change_is_replaced_by_owner_text_without_blocking():
    assert dca._owner_wins(OWNER, COLLAPSED.replace("blowgun", "spear")) == OWNER
    assert dca._owner_wins(OWNER, "") == OWNER
    assert dca._owner_wins(OWNER, None) == OWNER


def test_name_addition_and_change():
    assert dca._owner_wins("Kai", "Kai the Rotbloom") == "Kai the Rotbloom"
    assert dca._owner_wins("Kai", "Kael") == "Kai"


def test_embedded_word_is_a_replacement_not_an_addition():
    assert dca._owner_wins("Kai", "Kaiden") == "Kai"
    assert dca._owner_wins("Kai", "Makai") == "Kai"
    assert dca._owner_wins("Iron Monk", "Iron Monkey") == "Iron Monk"
    assert dca._owner_wins("Kai", "Kai, the Rotbloom") == "Kai, the Rotbloom"
