"""Optional historical evidence reader; canonical stock tests run separately.

Supply an existing JUnit receipt with CF_CLINICAL_BEFORE_JUNIT. No private
checkout or nested test runner is required. Native tests cover actual mechanics;
API/setup failures never count as behavioral evidence.
"""
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

EXPECTED={
    'test_native_succor_luck_success_save_sacrifices_before_reroll':'assert not aegises',
    'test_native_containment_chosen_hostile_recipient':"zone.trigger_profile['veil_recipients']",
    'test_blood_consent_and_exact_one_source':'assert len(remaining)==1',
    'test_purify_sources[blinded-physical_impairment-0-excluded0-True]':'assert bool(held) is not ends',
    'test_ingrain_post_failed_save[Numb Channels]':'assert len(toxins)==1',
    'test_coagulate_native_temp_hp_bands[10]':'assert base+count<=e.state.actors[B].temporary_hp<=base+count*8',
}


def assert_behavioral_receipt(root):
    cases=root.findall('.//testcase')
    assert len(cases)==len(EXPECTED)
    assert {case.get('name') for case in cases}==set(EXPECTED)
    for case in cases:
        failure=case.find('failure')
        assert case.find('error') is None and case.find('skipped') is None
        allowed_types=('AssertionError','KeyError') if 'containment' in case.get('name') else ('AssertionError',)
        assert failure is not None and failure.get('type') in allowed_types
        text=failure.text or ''
        assert not any(token in text for token in ('AttributeError','ImportError','ModuleNotFoundError','journey_world_fact'))
        assert EXPECTED[case.get('name')] in text


def test_exact_base_rejects_the_six_native_regressions():
    receipt=os.environ.get('CF_CLINICAL_BEFORE_JUNIT')
    if not receipt:pytest.skip('Opt in with an explicit historical JUnit receipt; no private checkout required')
    assert_behavioral_receipt(ET.parse(Path(receipt)).getroot())


@pytest.mark.parametrize('setup_failure',[False,True],ids=['behavioral-assertions','missing-api-is-not-evidence'])
def test_historical_receipt_requires_reached_behavior(setup_failure):
    root=ET.Element('testsuite')
    for name,assertion in EXPECTED.items():
        case=ET.SubElement(root,'testcase',name=name)
        failure=ET.SubElement(case,'failure',type='AssertionError')
        failure.text=assertion
    if setup_failure:
        failure=root.findall('testcase')[2].find('failure')
        failure.set('type','AttributeError')
        failure.text="CombatService has no attribute 'journey_world_fact'"
        with pytest.raises(AssertionError):assert_behavioral_receipt(root)
    else:assert_behavioral_receipt(root)
