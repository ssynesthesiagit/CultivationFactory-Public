"""Shared sheet helper keeps a missing Foundation status missing.

Synthetic fixture: the helper is given a Foundation with no status. The sheet must
not invent `status: active`, because the Golden Mandate and Foundation code treat a
missing status as unknown (unavailable), and an invented status hides that path.
"""
from tests.h1_support import sheet

MANDATE_FEATURE = 'foundation.golden_mandate_seal_v0_2B.golden_mandate_vessel'


def test_foundation_without_status_is_not_given_one():
    doc = sheet([MANDATE_FEATURE], foundation={'foundation_id': 'golden_mandate_seal_v0_2B', 'stage': 'Awakened'})
    assert doc['foundation'] == {'foundation_id': 'golden_mandate_seal_v0_2B', 'stage': 'Awakened'}
    assert 'status' not in doc['foundation']


def test_foundation_with_explicit_status_keeps_it():
    doc = sheet([MANDATE_FEATURE], foundation={'foundation_id': 'golden_mandate_seal_v0_2B', 'stage': 'Awakened', 'status': 'suppressed'})
    assert doc['foundation']['status'] == 'suppressed'
