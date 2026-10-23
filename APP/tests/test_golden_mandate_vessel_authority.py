"""Golden Mandate Vessel: the shipped authority carries the reviewed record, not an obsolete rider.

The builder merges every reviewed_final.d file into the generated authority that the combat compiler reads.
A reviewed correction that never reaches the generated file leaves runtime consumers describing finished
clauses as unfinished. Public synthetic check: reads only the repository's shipped authority files.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
KEY = 'foundation.golden_mandate_seal_v0_2B.golden_mandate_vessel'


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_shipped_authority_matches_reviewed_vessel_record():
    reviewed = _load(APP / 'authority/typed_mechanics/reviewed_final.d/a2_foundations_2.json')['mechanics'][KEY]
    shipped = _load(APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json')['mechanics'][KEY]
    assert shipped['riders'] == reviewed['riders']
    assert shipped['riders'], 'the Vessel record must keep its printed-rule rider'
    assert shipped['typing_status'] == 'reviewed_final'
    assert shipped['source']['text_sha256'] == reviewed['text_sha256']


def test_shipped_vessel_rider_drops_obsolete_automation_disclaimer():
    shipped = _load(APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json')['mechanics'][KEY]
    text = ' '.join(shipped['riders'])
    assert 'still need combat automation' not in text
    assert 'Hostile saves with printed command' not in text
    assert 'Advantage against fear, charm' in text
    assert 'Hit Points include your Proficiency Bonus once' in text
