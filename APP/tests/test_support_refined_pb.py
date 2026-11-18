"""Refined Dew Returns to Source / Outward: the support spend's Temporary Hit Points grow by one Proficiency Bonus."""
import pytest

from tests.test_a2_foundations4 import ALLY, T, V, candidate, reload, settle, setup


@pytest.mark.parametrize('foundation,ability', [(T, 'Preserving Moon Breath'), (V, 'Spring Renewal Pulse')])
@pytest.mark.parametrize('stage,expected', [('Awakened', 6), ('Refined', 10)])  # PB 4 + key 2; Refined adds one more PB
def test_refined_support_spend_adds_one_proficiency_bonus_to_the_temporary_hit_points(tmp_path, foundation, ability, stage, expected):
    combat, table, mid = setup(tmp_path, foundation, held=1, stage=stage, prepare=True)
    settle(table, mid, candidate(combat, mid, ability, target=ALLY).candidate_id)
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == expected
