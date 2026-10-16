"""Keep reviewed Insight inputs and the shipped generated authority in sync.

Merge conflict resolution can retain a valid main authority that predates this
lane's overrides. Existing table tests cover execution; this checks the source
admission boundary for every reviewed row, including narrative-only records.
"""
import json
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parents[1]
# Full app-relative literals let the CI dependency scanner distinguish the
# reviewed input from combat/rules/feature_blocks.d/opus1_insights.json.
REVIEWS = json.loads((APP / 'authority/typed_mechanics/reviewed_final.d/opus1_insights.json').read_text())['mechanics']
GENERATED = json.loads((APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']


@pytest.mark.parametrize('source_id', sorted(REVIEWS))
def test_reviewed_insight_is_present_in_shipped_authority(source_id):
    reviewed = REVIEWS[source_id]
    actual = GENERATED[source_id]
    assert actual['source']['text_sha256'] == reviewed['text_sha256']
    assert actual['typing_status'] == 'reviewed_final'
    assert actual['insight_selectable'] is True
    assert actual['insight_reviewed_text_sha256'] == reviewed['text_sha256']
    for field in ('activation', 'cost', 'duration', 'effects', 'riders', 'notes'):
        assert actual[field] == reviewed[field], (source_id, field)
