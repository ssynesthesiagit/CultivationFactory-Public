"""A Refined feature that raises its Foundation's Hit Point increase (Golden Blood Root: Saint-Body Frame becomes 3 x PB)."""
import pytest
from tests.rw172_foundation_fixture import synthetic_foundations

pytestmark = pytest.mark.usefixtures('synthetic_foundations')

from tests.foundation_catalog_edit_support import edit_catalog, assert_saved_hp_services
from combat.factory_compiler import compile_character
from non_sphere_authority import foundation_mechanics
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, fixture, reload

FOUNDATION = 'ancient_desolate_sacred_body_v0_2C'
GOLDEN = 'foundation.' + FOUNDATION + '.refined_golden_blood_root'
FRAME = 'foundation.' + FOUNDATION + '.saint_body_frame'


def _mechanics():
    return foundation_mechanics.resolve_initial_foundation_mechanics(
        foundation_mechanics.verified_foundation_records()[FOUNDATION], ['tianxia.path.qi_cultivation'])


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


def test_golden_blood_root_saved_hp_survives_catalog_edit(tmp_path, monkeypatch):
    mechanics = _mechanics()
    doc = sheet([FRAME, GOLDEN], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined', 'mechanics': mechanics})
    edit_catalog(monkeypatch)
    assert_saved_hp_services(tmp_path, doc, 64)


def test_golden_blood_root_leaves_a_legacy_sheet_alone(tmp_path):
    doc = sheet([FRAME, GOLDEN], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined'})
    _, _, mid = fixture(tmp_path, [], owner_bundle=compile_character(doc, actor_id=OWNER), seed='HP-TIER-LEGACY')
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 60
