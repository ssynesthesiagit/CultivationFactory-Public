"""Stock replay comparison ignores only display-only roll receipts (mode_sources).

Synthetic captures only (public CI safe; no saved fight, no replay run). The stock
replay (test_a2_glass_stock.py) compares everything except mode_sources. These tests
show that: a capture that differs only by receipts projects to the same bytes, while
any change to a mode, total, choice or other state field still changes the bytes.
"""
import json

from tests.roll_receipt_projection import without_roll_explanations


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _capture(receipts):
    """A small capture shape: a top-level roll, a nested reaction roll, and a state field."""
    return {
        'rolls': [
            {'mode': 'DISADVANTAGE', 'total': 4, 'mode_sources': receipts},
            {'mode': 'NORMAL', 'total': 12, 'nested': [{'mode': 'ADVANTAGE', 'total': 17,
                                                       'mode_sources': [{'effect': 'Fog'}]}]},
        ],
        'state': {'terminal_result': 'win', 'hp': {'ally': 7}},
    }


RECEIPTS = [{'effect': 'Prone', 'owner': 'Mira', 'kind': 'disadvantage', 'why': 'the attacker is Prone'}]


def test_stock_projection_excludes_only_roll_explanation_metadata():
    sample = {'mode': 'DISADVANTAGE', 'total': 4, 'mode_sources': [{'effect': 'Prone'}],
              'nested': [{'mode': 'NORMAL', 'mode_sources': [{'effect': 'Fog'}], 'total': 12}]}
    assert without_roll_explanations(sample) == {
        'mode': 'DISADVANTAGE', 'total': 4,
        'nested': [{'mode': 'NORMAL', 'total': 12}],
    }


def test_receipt_only_difference_projects_to_identical_bytes():
    with_receipts = _capture(RECEIPTS)
    without_receipts = _capture([])
    assert with_receipts != without_receipts
    assert _encoded(without_roll_explanations(with_receipts)) == _encoded(without_roll_explanations(without_receipts))


def test_mode_total_and_state_differences_are_still_compared():
    base = _capture(RECEIPTS)
    baseline = _encoded(without_roll_explanations(base))
    changed_mode = _capture(RECEIPTS)
    changed_mode['rolls'][0]['mode'] = 'NORMAL'
    changed_total = _capture(RECEIPTS)
    changed_total['rolls'][1]['nested'][0]['total'] = 18
    changed_state = _capture(RECEIPTS)
    changed_state['state']['hp']['ally'] = 6
    for changed in (changed_mode, changed_total, changed_state):
        assert _encoded(without_roll_explanations(changed)) != baseline
