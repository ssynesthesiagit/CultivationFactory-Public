"""OPUS1: Insights reviewed as having no fight effect read as checked on the character sheet.

Every row of authority/typed_mechanics/reviewed_final.d/opus1_insights.json whose review is "no fight effect" must be
admitted by the exact-source gate, carry its printed out-of-fight lines for the Game Master, and say plainly why the
table runs nothing -- never an internal id. Rows that do run in fights are covered by their own table tests.
"""
import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER

REVIEWS = Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/reviewed_final.d/opus1_insights.json'
NO_FIGHT = sorted(key for key, row in json.loads(REVIEWS.read_text(encoding='utf-8'))['mechanics'].items()
                  if 'no fight effect' in row['reviewed_by'])


def test_the_review_file_lists_out_of_fight_insights():
    assert len(NO_FIGHT) >= 11


@pytest.mark.parametrize('insight', NO_FIGHT)
def test_out_of_fight_insight_reads_as_checked(insight):
    document = sheet([], cl=12)
    document.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = [insight]
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    row = next(row for row in bundle['diagnostics']['insights'] if row['id'] == insight)
    assert row['status'] == 'partial' and 'has been checked' in row['explanation'], row
    assert row['gm_decides'] and all('(' in line for line in row['gm_decides'])
    assert 'insight.' not in row['explanation'] and 'insight.' not in ' '.join(row['gm_decides'])
    assert not row['table_applies']
