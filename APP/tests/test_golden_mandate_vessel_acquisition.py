"""Golden Mandate: imported acquisition HP is counted once, public synthetic fixture.

The sheet is built from the repository's verified Foundation records (no private
Factory archive), and its authenticated initial mechanics carry the PB share.
The causal creation-to-HP proof through the real calculator needs the private
Factory catalog and is not part of this public suite.
"""
from copy import deepcopy

from combat.factory_compiler import compile_character
from combat.ext import foundation_combat as f
from stage2.service import _formula_value
from tests.h1_support import sheet as plain_sheet
from tests.test_golden_mandate_vessel_native import IDENTITY, POOL, source_sheet
from tests.worker2_support import OWNER, fixture, reload, settle

DEPENDENCIES = (
    'APP/authority/typed_mechanics/rules_text.json',
    'APP/authority/typed_mechanics/reviewed_final.d/a2_foundations_2.json',
    'APP/combat/rules/feature_blocks.d/a2_foundations_2.json',
    'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
    'APP/non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
)


def test_imported_acquisition_hp_counted_once_and_survives_reload(tmp_path):
    doc = source_sheet()
    first = compile_character(doc, actor_id=OWNER)
    rebuilt = compile_character(deepcopy(doc), actor_id=OWNER)
    assert first == rebuilt
    assert first['mandate_source']['foundation_id'] == IDENTITY
    assert first['mandate_source']['included_hp'] == 3
    assert first['actor_template']['maximum_hp'] == 63
    combat, table, mid = fixture(tmp_path / 'imported-fight', [], owner_bundle=first, seed='MANDATE-ACQUIRED')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    after = reload(tmp_path / 'imported-fight', mid)
    assert after.state.actors[OWNER].maximum_hp == 63
    assert after.state.actors[OWNER].current_hp == 63
    assert after.state.actors[OWNER].resources[POOL] == 0


def test_vessel_share_is_formula_derived_and_counted_once():
    """The HP share is the verified Vessel formula at PB, counted exactly once.

    Creation maximum = base sheet maximum (no Foundation) + formula share. The
    compiler must record that same share as the suppression source; a double
    count or omission breaks one of the equalities below.
    """
    doc = source_sheet()
    vessel = [m for m in doc['foundation']['mechanics']['hp_maximum_modifiers']
              if m['feature_name'] == 'Golden Mandate Vessel']
    assert len(vessel) == 1
    pb = doc['identity']['proficiency_bonus']
    share = _formula_value(vessel[0]['formula'], {'pb': pb})[0]
    base = plain_sheet([], cl=5)['ability_scores_and_statistics']['hit_points']['maximum']
    assert share == pb == 3
    assert doc['ability_scores_and_statistics']['hit_points']['maximum'] == base + share
    compiled = compile_character(doc, actor_id=OWNER)
    assert compiled['mandate_source']['included_hp'] == share
    assert compiled['actor_template']['maximum_hp'] == base + share
