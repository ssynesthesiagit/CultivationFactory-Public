"""Guard the general source-qualified conversion fold; no ability ownership fixtures."""
import pytest
from combat.defense_conversion import immunity_result


def test_default_and_legacy_boolean_contract():
    assert immunity_result(['a'], ['f'], []) == (True, False)
    assert immunity_result(['a'], ['f'], [False]) == (True, False)
    assert immunity_result(['a'], ['f'], [True]) == (False, True)
    assert immunity_result([], [], [True]) == (False, False)


def test_converting_one_source_keeps_overlapping_immunity():
    assert immunity_result(['a', 'b'], [], [{'modifier_ids': ['a']}]) == (True, True)
    assert immunity_result(['a'], [], [{'modifier_ids': ['a']}]) == (False, True)
    assert immunity_result([], ['f'], [{'feature_ids': ['f']}]) == (False, True)
    assert immunity_result(['a'], [], [{'feature_ids': ['a']}]) == (True, False)


@pytest.mark.parametrize('reply', [1, 'all', {'unknown': []}, {'modifier_ids': ['']}, {'feature_ids': 'f'}])
def test_malformed_conversion_is_rejected(reply):
    with pytest.raises(ValueError):
        immunity_result(['a'], ['f'], [reply])
