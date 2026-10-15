"""A merge must not restore Ash Mercy's unconditional temporary-HP rider."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE = 'foundation.red_lotus_ash_returning_v0_2B.refined_ash_mercy_boundary'


def test_generated_mercy_row_preserves_reviewed_paid_restraint_contract():
    authority = json.loads(
        (ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    reviewed = json.loads(
        (ROOT / 'authority/typed_mechanics/reviewed_final.d/foundations3.json').read_text())
    row = authority['mechanics'][FEATURE]
    expected = reviewed['mechanics'][FEATURE]
    assert row['typing_status'] == 'reviewed_final'
    assert row['effects'] == expected['effects'] == []
    assert row['coverage'] == expected['automation_coverage'] == 'CORE_WITH_RIDERS'
    assert row['range'] == expected['range'] == {'kind': 'feet', 'feet': 30}
    assert row['notes'] == expected['notes']
