"""Saved Challenge provenance shared by Guardian and Plain-Truth Fist.

Both abilities historically store ``condition:typed.challenged``. Distinguish
Deed Follows Word by its existing source, without changing old saved conditions.
"""

DEED_CHALLENGE_SOURCE = "tianxia.tradition.spirit.plain_truth_fist.feature.deed_follows_word"


def is_deed_challenge(condition):
    """Whether this is the Plain-Truth completion, rather than Guardian Challenge."""
    return (condition.condition_id == "condition:typed.challenged"
            and condition.source_definition_id == DEED_CHALLENGE_SOURCE)
