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
    # Printed "preserve, cauterize, spare, or end cleanly" scenes all run on the
    # table (foundation_mercy's native choices), so nothing is left to a GM
    # ruling and the record has no riders (owner rule 2026-10-20).
    assert row['coverage'] == expected['automation_coverage'] == 'FULL'
    assert row['range'] == expected['range'] == {'kind': 'feet', 'feet': 30}
    # The regression for F12R finding 1 is structural: the generated row must
    # not carry a GM rider for the cautery or clean-ending scenes. Text bodies
    # are not compared because public CI intentionally scrambles printed rules
    # text, which made this a false public failure.
    assert row['riders'] == expected['riders'] == [], 'cautery and clean endings are automated, not GM riders'
    assert row['notes'] and all(isinstance(note, str) and note for note in row['notes'])


def test_merge_keeps_shared_circuit_and_mercy_native_registrations():
    """Both inserted rows must survive the foundations3 merge, without effects."""
    authority = json.loads(
        (ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    reviewed = json.loads(
        (ROOT / 'authority/typed_mechanics/reviewed_final.d/foundations3.json').read_text())
    blocks = json.loads(
        (ROOT / 'combat/rules/feature_blocks.d/foundations3.json').read_text())
    shared = 'foundation.origin_spirit_body_v0_2B.refined_shared_circuit_memory'
    for feature, block in ((FEATURE, 'foundation_mercy'),
                           (shared, 'foundations3_shared_memory')):
        assert feature in reviewed['mechanics']
        assert authority['mechanics'][feature]['typing_status'] == 'reviewed_final'
        assert authority['mechanics'][feature]['effects'] == []
        assert blocks['features'][feature]['block'] == block
