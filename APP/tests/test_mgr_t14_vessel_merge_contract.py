"""Keep the reviewed Vessel/Guard merge runnable and its authority source-backed."""
import json
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('reviewed_file,ability', [
    ('authority/typed_mechanics/reviewed_final.d/mgr_t14_spirit_vessel_value.json',
     'origin_spirit_vessel'),
    ('authority/typed_mechanics/reviewed_final.d/foundations3.json', 'returning_source_guard'),
])
def test_merged_authority_preserves_reviewed_vessel_and_guard(reviewed_file, ability):
    """Choosing main's generated file alone must not erase reviewed lane inputs."""
    key = 'foundation.origin_spirit_body_v0_2B.' + ability
    authority = APP / 'authority'
    reviewed = json.loads((APP / reviewed_file).read_text())['mechanics'][key]
    generated = json.loads((authority / 'Tianxia_Typed_Mechanics_Authority_R1.json')
                           .read_text())['mechanics'][key]
    assert generated['typing_status'] == 'reviewed_final'
    assert generated['source']['text_sha256'] == reviewed['text_sha256']
    for field in ('effects', 'riders', 'modifier', 'allow_self_source'):
        if field in reviewed:
            assert generated.get(field) == reviewed[field], (ability, field)


@pytest.mark.parametrize('path,ability,block', [
    ('combat/rules/feature_blocks.d/mgr_t14_spirit_vessel_value.json',
     'origin_spirit_vessel', 'foundations3_spirit_value'),
    ('combat/rules/feature_blocks.d/foundations3.json',
     'generate_spirit_source_dew', 'generate'),
])
def test_native_spirit_runtime_inputs_are_available(path, ability, block):
    """These glob-loaded compiler inputs must accompany the table regressions.

    Full paths declare real runtime resources to the public dependency scanner;
    their basenames also occur under reviewed_final.d and are ambiguous alone.
    """
    key = 'foundation.origin_spirit_body_v0_2B.' + ability
    features = json.loads((APP / path).read_text())['features']
    assert features[key]['block'] == block


def test_guard_consumers_keep_the_shared_payment_receipt_helper():
    """The RB2 collection failure removed this service regression's import."""
    from tests.test_mgr_t14_ling_guard_sum import assert_guard_paid_before_new_dew
    from tests.test_mgr_t14_guard_parent import assert_guard_paid_before_new_dew as consumer_helper

    assert consumer_helper is assert_guard_paid_before_new_dew


def test_native_water_shield_runtime_input_is_available():
    """The native reduction regression must compile the shipped Shield hook."""
    features = json.loads((APP / 'combat/rules/feature_blocks.d/auto38_water.json')
                          .read_text())['features']
    assert features['TAL_WATER_WATER_SHIELD']['block'] == 'water_defenses'
