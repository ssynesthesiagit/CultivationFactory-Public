"""A rejected movement destination is recognised by its type, not by its message text (review F18R brittle match).

subject_repositioning re-asks the controller only for needle.InvalidCellOption. A genuine ValueError whose message
happens to start with the same words must surface as a bug, not be taken for a controller's rejection.
"""
import pytest

from combat.ext import needle


def test_malformed_cell_option_raises_the_typed_rejection():
    with pytest.raises(needle.InvalidCellOption):
        needle.parse_cell('cell:1')


def test_typed_rejection_is_still_a_value_error():
    assert issubclass(needle.InvalidCellOption, ValueError)


def test_plain_value_error_with_the_same_words_is_not_a_controller_rejection():
    exc = ValueError('Invalid cell option: a genuine bug')
    assert not isinstance(exc, needle.InvalidCellOption)
