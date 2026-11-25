"""A wounded native patient receives support, without restored Hit Points."""
from combat.factory_compiler import compile_character
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool, use
from tests.test_mgr_t15_lotus_root_recovery import FOUNDATION, NAME, support
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, turn, reload

# Literal dynamic source dependencies for the supported safe export.
INPUTS = ('APP/non_sphere_authority/authority/qi_cultivation.path_index.p2a.json',
          'APP/non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
          'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
          'APP/authority/typed_mechanics/rules_text.json',
          'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json',
          'APP/combat/rules/feature_blocks.d/foundations3.json',
          'APP/authority/typed_mechanics/reviewed_final.d/foundations3.json')


def test_wounded_patient_receives_temp_hp_without_any_healing(tmp_path):
    mechanics = resolve_initial_foundation_mechanics(verified_foundation_records()[FOUNDATION],
        ['tianxia.path.qi_cultivation'], stage='Awakened')
    doc = sheet([], cl=9, key='INT', score=14)
    doc['identity']['proficiency_bonus'] = 4
    doc['foundation'] = installed_foundation_state(mechanics, FOUNDATION, 'event:scenario.initial-foundation')
    assert doc['foundation']['resource']['current'] == 0
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        add_action(bundles[2], 'Direct damage', [{'type': 'damage', 'flat': 8,
            'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
        add_action(bundles[2], 'Poison exposure', [{'type': 'save', 'ability': 'CON',
            'save_categories': ['poison'], 'on_fail': [{'type': 'damage', 'flat': 1,
            'damage_types': ['poison'], 'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=6)

    combat, table, mid = fixture(tmp_path, [], cl=9, owner_bundle=bundle,
        seed='LOTUS-ROOT-NATIVE', bundle_transform=delivery)
    initial = reload(tmp_path, mid).state.actors[ALLY].current_hp
    turn(table, mid, FOE)
    use(combat, table, mid, 'Direct damage', ALLY)
    wounded = reload(tmp_path, mid)
    assert wounded.state.actors[ALLY].current_hp == initial - 8
    assert wounded.state.actors[OWNER].resources[pool('lotus')] == 0
    assert 1 + wounded.state.actors[ALLY].saving_throws.get('CON', 0) < 6
    use(combat, table, mid, 'Poison exposure', ALLY)
    earned = reload(tmp_path, mid)
    assert [e for e in earned.events if e.event_type == 'SAVE_ROLLED'][-1].payload['success'] is True
    assert earned.state.actors[OWNER].resources[pool('lotus')] == 1
    injured_hp = earned.state.actors[ALLY].current_hp
    assert injured_hp < initial
    turn(table, mid, OWNER)
    accepted_source = candidate(combat, mid, NAME, target=ALLY).source_definition_id
    support(combat, table, mid, ALLY, method='medicine')
    after = reload(tmp_path, mid)
    assert after.state.actors[ALLY].current_hp == injured_hp
    assert after.state.actors[ALLY].temporary_hp == 6
    assert after.state.actors[OWNER].resources[pool('lotus')] == 0
    assert any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == accepted_source
               for e in after.events)
