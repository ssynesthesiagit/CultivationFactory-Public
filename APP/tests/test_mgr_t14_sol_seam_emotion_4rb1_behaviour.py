"""MGR-T14 Sol seam Emotion 4RB1: the four cited records get past setup.

The earlier behaviour-diff scripts stopped at setup. This pins the setup
contract they depended on: a sheet carries a WIS ability score and modifier,
and each of the four cited Emotion records, once acquired at its Cultivation
Level, reaches the compiled action catalog. Public-CI safe: no private
fixtures, no git-history reads, no live servers.
"""
import pytest

from combat.ext.emotion_cultivator import PULSE, HEART, CONTAGION, WEAVER
from combat.feature_access import acquire
from combat.factory_compiler import compile_character
from tests.h1_support import sheet

RECORDS = [
    (CONTAGION, 6),   # emotional_contagion
    (HEART, 10),      # heartbreak_and_heartmend
    (WEAVER, 18),     # heartweaver
    (PULSE, 3),       # emotional_pulse
]


def _wisdom(doc):
    return next(a for a in doc['ability_scores_and_statistics']['abilities'] if a['ability'] == 'WIS')


def _acquired(feature, level):
    doc = sheet([], cl=level, score=14)
    doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    return acquire(doc, feature, {'kind': 'scripture',
                                  'reference': 'Recorded standard Emotion Scripture instruction',
                                  'classification': 'Restricted Scripture'})


def test_setup_sheet_carries_wisdom_score_and_modifier():
    w = _wisdom(sheet([], cl=10, score=14))
    assert w['score'] == 14 and w['modifier'] == 2


@pytest.mark.parametrize('feature,level', RECORDS)
def test_each_cited_record_reaches_the_action_catalog_past_setup(feature, level):
    doc = _acquired(feature, level)
    assert feature in doc['path_and_subpath']['path_feature_record_ids']
    assert _wisdom(doc)['modifier'] == 2
    bundle = compile_character(doc, actor_id='actor:factory.emotion.4rb1')
    sources = [(a.get('parameters', {}).get('typed') or {}).get('source') for a in bundle['action_catalog']]
    assert feature in sources
