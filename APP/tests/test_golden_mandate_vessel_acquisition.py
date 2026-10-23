"""Golden Mandate: imported acquisition HP is counted once, public synthetic fixture.

The sheet is built from the repository's verified Foundation records (no private
Factory archive), and its authenticated initial mechanics carry the PB share.
The causal creation-to-HP proof through the real calculator needs the private
Factory catalog and is not part of this public suite.
"""
from copy import deepcopy

from combat.factory_compiler import compile_character
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
