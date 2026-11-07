"""A feature_blocks ``covers`` entry may name a printed rider by its short tail phrase.

The compiler drops a GM-only rider sentence when a covers entry matches it: a whole-sentence entry matches that sentence exactly, and
a tail phrase matches the sentence that ends with it. Both are checked here against the real ``_gm_lines`` filter, with the block
rules patched to a synthetic feature, so the check carries no private authority data and no printed rules text (fixture wording is
invented).
"""
from __future__ import annotations

import combat.factory_compiler as compiler

SENTENCE = "The Guild doubles its posted fee for any cart left in the eastern yard overnight."
ONCE = "The Guild doubles its posted fee for any cart left in the eastern yard overnight once."
OTHER = "The GM decides whether a handcart counts as a cart here."
MIDDLE = "The Guild waves the eastern yard fee unless the cart left overnight."


def _gm_lines(monkeypatch, covers, riders):
    monkeypatch.setattr("combat.typed_reactions.rules", lambda: {"features": {"M": {"covers": list(covers)}}})
    return compiler._gm_lines(list(riders), {"mechanic_id": "M"}, [])


def test_a_tail_phrase_hides_the_sentence_that_ends_with_it(monkeypatch):
    assert _gm_lines(monkeypatch, ["cart left in the eastern yard overnight."], [SENTENCE]) == []


def test_a_whole_sentence_covers_entry_still_matches_exactly(monkeypatch):
    assert _gm_lines(monkeypatch, [SENTENCE], [SENTENCE]) == []


def test_a_tail_phrase_leaves_other_sentences_alone(monkeypatch):
    assert _gm_lines(monkeypatch, ["cart left in the eastern yard overnight."], [SENTENCE, OTHER]) == [OTHER]


def test_a_tail_phrase_does_not_hide_a_sentence_that_merely_contains_it(monkeypatch):
    assert _gm_lines(monkeypatch, ["eastern yard fee"], [MIDDLE]) == [MIDDLE]


def test_a_tail_phrase_does_not_hide_a_sentence_with_more_words_after_it(monkeypatch):
    """The "... overnight once." sentence is a different rule, so it stays on the GM's line."""
    assert _gm_lines(monkeypatch, ["in the eastern yard overnight."], [ONCE]) == [ONCE]
