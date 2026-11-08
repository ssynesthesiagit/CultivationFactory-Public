"""BRS1F28 (F27R finding 3): linear-menu cues are cut at a whole word, never mid-word."""

from character_creation.creative_controller import linear_menus as lm


def test_long_cue_is_cut_at_a_word_boundary_within_the_bound():
    cue = ("Blooming Body Refining variant grants Temporary Health Points equal to your "
           "Proficiency Bonus each time you complete a short rest, and then you may choose again later")
    out = lm._bounded_cue(cue, "fallback")
    assert len(out) <= lm.MAX_CUE_LENGTH
    assert cue.startswith(out)
    assert cue[len(out)] == " ", f"cut mid-word: {out!r}"
    assert not out.endswith(" ")


def test_cue_that_fits_is_not_truncated():
    assert lm._bounded_cue("Choose a Body Refining variant.", "fallback") == "Choose a Body Refining variant."
