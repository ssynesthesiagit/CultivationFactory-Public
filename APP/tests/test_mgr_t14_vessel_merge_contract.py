"""Keep the reviewed Vessel/Guard merge runnable and its authority source-backed."""
import json
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('reviewed_file,ability', [
    ('mgr_t14_spirit_vessel_value.json', 'origin_spirit_vessel'),
    ('foundations3.json', 'returning_source_guard'),
])
def test_merged_authority_preserves_reviewed_vessel_and_guard(reviewed_file, ability):
    """Choosing main's generated file alone must not erase reviewed lane inputs."""
    key = 'foundation.origin_spirit_body_v0_2B.' + ability
    authority = APP / 'authority'
    reviewed = json.loads((authority / 'typed_mechanics/reviewed_final.d' / reviewed_file)
                          .read_text())['mechanics'][key]
    generated = json.loads((authority / 'Tianxia_Typed_Mechanics_Authority_R1.json')
                           .read_text())['mechanics'][key]
    assert generated['typing_status'] == 'reviewed_final'
    assert generated['source']['text_sha256'] == reviewed['text_sha256']
    for field in ('effects', 'riders', 'modifier', 'allow_self_source'):
        if field in reviewed:
            assert generated.get(field) == reviewed[field], (ability, field)


def test_guard_consumers_keep_the_shared_payment_receipt_helper():
    """The RB2 collection failure removed this service regression's import."""
    from tests.test_mgr_t14_ling_guard_sum import assert_guard_paid_before_new_dew
    from tests.test_mgr_t14_guard_parent import assert_guard_paid_before_new_dew as consumer_helper

    assert consumer_helper is assert_guard_paid_before_new_dew
