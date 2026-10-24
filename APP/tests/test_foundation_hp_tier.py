"""A Refined feature that raises its Foundation's Hit Point increase (Golden Blood Root: Saint-Body Frame becomes 3 x PB)."""
import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_mechanics, verified_foundation_records
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, fixture, reload

FOUNDATION = 'ancient_desolate_sacred_body_v0_2C'
GOLDEN = 'foundation.' + FOUNDATION + '.refined_golden_blood_root'
FRAME = 'foundation.' + FOUNDATION + '.saint_body_frame'


def _mechanics():
    return resolve_initial_foundation_mechanics(verified_foundation_records()[FOUNDATION], ['tianxia.path.qi_cultivation'])


@pytest.mark.parametrize('ids,stage,expected', [
    ([FRAME], 'Awakened', 60),            # the calculator's 2 x PB is already in these 60
    ([FRAME, GOLDEN], 'Refined', 64),     # 3 x PB: one more Proficiency Bonus (PB 4)
    ([FRAME, GOLDEN], 'Perfected', 64)])
def test_golden_blood_root_raises_the_frame_to_three_proficiency_bonuses(tmp_path, ids, stage, expected):
    doc = sheet(ids, foundation={'foundation_id': FOUNDATION, 'stage': stage, 'mechanics': _mechanics()})
    bundle = compile_character(doc, actor_id=OWNER)
    assert compile_character(doc, actor_id=OWNER) == bundle
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, seed='HP-TIER')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].maximum_hp == expected
    assert engine.state.actors[ALLY].maximum_hp == 60


def test_golden_blood_root_rejects_changed_hp_provenance():
    mechanics = _mechanics()
    term = mechanics['hp_maximum_modifiers'][0]['formula']['root']['terms'][0]
    assert 'value' in term, 'the fixture formula shape changed; update this test'
    term['value'] = 3
    doc = sheet([FRAME, GOLDEN], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined', 'mechanics': mechanics})
    with pytest.raises(FoundryError) as error:
        compile_character(doc, actor_id=OWNER)
    assert error.value.code == 'COMBAT_FOUNDATION_HP_PROJECTION_INVALID'


def test_golden_blood_root_leaves_a_legacy_sheet_alone(tmp_path):
    doc = sheet([FRAME, GOLDEN], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined'})
    _, _, mid = fixture(tmp_path, [], owner_bundle=compile_character(doc, actor_id=OWNER), seed='HP-TIER-LEGACY')
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 60
