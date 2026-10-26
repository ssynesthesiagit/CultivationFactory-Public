"""Remnant Core Reserve: native compilation, table commit and cold replay.

Enemy pressure profiles below are deterministic initial scenario data using the
existing public save_categories contract. They prove the consumer, not that all
published enemy sources have already been classified by a production producer.
Dynamic inputs: authority/typed_mechanics/rules_text.json,
combat/rules/feature_blocks.d/remnant_core_reserve.json,
combat/rules/source_expressions/remnant_core_reserve.json,
authority/typed_mechanics/reviewed_final.d/remnant_core_reserve.json,
non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json.
"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.source_expressions import POLICIES, RULES_TEXT, validate_policy
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics,
    verified_foundation_records,
)
from stage2.service import _formula_value
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

FID = 'ash_born_remnant_core_v0_2B'
SOURCE = 'foundation.' + FID + '.remnant_core_reserve'
CP = 'resource:core.qi'
HASH = '6a0353becdad07541ebac96c5dde412d6098b73a9dfde75f220f99cd40464720'
SCOPES = ('remnant_possession', 'ruin_terror', 'grief_control',
          'despair_pressure', 'battlefield_horror', 'destruction_as_truth')
SOURCE_INPUTS = (
    'APP/authority/typed_mechanics/rules_text.json',
    'APP/combat/rules/feature_blocks.d/remnant_core_reserve.json',
    'APP/combat/rules/source_expressions/remnant_core_reserve.json',
    'APP/authority/typed_mechanics/reviewed_final.d/remnant_core_reserve.json',
    'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
)


def native_sheet(*, installed=True):
    doc = sheet(['ASH_TAL_ASHEN_BURIAL', 'FIRE_TAL_FIREBALL_ART'], cl=15)
    if installed:
        profile = resolve_initial_foundation_mechanics(
            verified_foundation_records()[FID], ['tianxia.path.qi_cultivation'])
        doc['foundation'] = installed_foundation_state(profile, FID, 'initial:remnant-core')
        delta = sum(_formula_value(row['formula'], {'pb': 4})[0]
                    for row in profile['resource_modifiers'])
        assert delta == 4
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] += delta
    return doc


def scenario(tmp_path, category, *, ability='WIS', installed=True, friendly=False):
    doc = native_sheet(installed=installed)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def source_profile(bundles):
        foe = bundles[2]
        source = 'action:scenario.remnant_pressure'
        foe['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Aftermath pressure',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE' if friendly else 'HOSTILE_ENTITY', 'range_ft': 60, 'costs': [],
            'parameters': {'typed': {'source': source, 'numbers': {'save_dc': 100},
                'duration': {'kind': 'instant'}, 'riders': [], 'effects': [{
                    'type': 'save', 'ability': ability, 'applies_to': 'target',
                    'save_categories': [category],
                    'on_fail': [{'type': 'damage', 'applies_to': 'target', 'flat': 7,
                                 'damage_types': ['FORCE']}], 'on_success': []}]}}})
        foe['actor_template']['action_ids'].append(source)
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner,
        bundle_transform=source_profile, seed='REMNANT-RESERVE',
        team_overrides={FOE: 'team:factory'} if friendly else None)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[OWNER].current_hp
    resources = dict(before.state.actors[OWNER].resources)
    settle(table, mid, candidate(combat, mid, 'Aftermath pressure', target=OWNER).candidate_id)
    after = reload(tmp_path, mid)
    saved_pressure = after.action_catalog['action:scenario.remnant_pressure'].parameters['typed']
    assert saved_pressure['effects'][0]['save_categories'] == [category]
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves
    # Impossible DC deliberately proves Advantage is not immunity. This row
    # generates no Cinder and never reduces the failed save's ordinary damage.
    assert after.state.actors[OWNER].current_hp == hp - 7
    assert after.state.actors[OWNER].resources == resources
    assert after.state.actors[OWNER].resource_maximums[CP] == (34 if installed else 30)
    return saves[-1].payload, after


@pytest.mark.parametrize('category', (*SCOPES, 'despair', 'grief_based_control'))
def test_all_six_owned_wisdom_scopes_commit_and_cold_replay(tmp_path, category):
    save, _ = scenario(tmp_path, category)
    assert save['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('category', (
    'ordinary_force', 'present_tense_threat', 'renewal', 'living_obligation',
    'frightened', 'possession', 'death_pressure', 'ash_contamination', 'fire_aftermath'))
def test_ordinary_and_unprinted_scope_controls(tmp_path, category):
    save, _ = scenario(tmp_path, category)
    assert save['mode'] == 'NORMAL'


@pytest.mark.parametrize('category', SCOPES)
def test_scope_requires_ownership_and_wisdom(tmp_path, category):
    save, _ = scenario(tmp_path / 'unowned', category, installed=False)
    assert save['mode'] == 'NORMAL'
    save, _ = scenario(tmp_path / 'constitution', category, ability='CON')
    assert save['mode'] == 'NORMAL'


def test_destruction_as_truth_requires_hostility(tmp_path):
    save, _ = scenario(tmp_path, 'destruction_as_truth', friendly=True)
    assert save['mode'] == 'NORMAL'


def test_native_legal_expression_receipt_commits_without_extra_benefit(tmp_path):
    doc = native_sheet()
    first = compile_character(doc, actor_id=OWNER)
    second = compile_character(json.loads(json.dumps(doc)), actor_id=OWNER)
    assert first == second
    assert sha256(json.loads(RULES_TEXT.read_text())[SOURCE].encode()).hexdigest() == HASH
    # Installation never adds sphere access or unrelated actions.
    absent = compile_character(native_sheet(installed=False), actor_id=OWNER)
    def techniques(bundle):
        return {a['parameters']['typed'].get('source'): a for a in bundle['action_catalog']
                if a.get('parameters', {}).get('typed', {}).get('source')}
    owned, unowned = techniques(first), techniques(absent)
    assert {s for s in owned if not s.startswith('foundation.')} == {
        s for s in unowned if not s.startswith('foundation.')}
    for source in ('ASH_BASE_CINDER_BRAND', 'ASH_TAL_ASHEN_BURIAL'):
        assert 'ash' in owned[source]['parameters']['typed']['foundation_alignment']
        receipt = owned[source]['parameters']['typed']['foundation_expression_sources']['ash']
        assert receipt['grant_source'] == SOURCE and receipt['grant_sha256'] == HASH
        assert receipt['source_id'] == source
        assert 'ash' not in unowned[source]['parameters']['typed'].get('foundation_alignment', [])
    assert 'ash' not in owned['FIRE_TAL_FIREBALL_ART']['parameters']['typed'].get('foundation_alignment', [])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=first, seed='REMNANT-EXPRESSION')
    action = next(a for a in first['action_catalog']
                  if a.get('parameters', {}).get('typed', {}).get('source') == 'ASH_TAL_ASHEN_BURIAL')
    before = reload(tmp_path, mid)
    maximum = before.state.actors[OWNER].resource_maximums[CP]
    current = before.state.actors[OWNER].resources[CP]
    settle(table, mid, candidate(combat, mid, action['display_name'], target=FOE).candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resource_maximums[CP] == maximum == 34
    assert after.state.actors[OWNER].resources[CP] == current - 4
    saved = after.action_catalog[action['source_definition_id']].parameters['typed']
    assert saved['foundation_expression_sources'] == action['parameters']['typed']['foundation_expression_sources']


def test_expression_input_rejects_stale_source_or_invented_quote():
    policy = json.loads((POLICIES / 'remnant_core_reserve.json').read_text())
    texts = json.loads(RULES_TEXT.read_text())
    assert set(validate_policy(policy, texts)) == {'ASH_BASE_CINDER_BRAND', 'ASH_TAL_ASHEN_BURIAL'}
    for field in ('grant_sha256', 'grant_quote'):
        stale = deepcopy(policy)
        stale[field] = 'unreviewed'
        with pytest.raises(ValueError):
            validate_policy(stale, texts)
    for field in ('text_sha256', 'quote'):
        stale = deepcopy(policy)
        stale['facts'][0][field] = 'unreviewed'
        with pytest.raises(ValueError):
            validate_policy(stale, texts)


def test_generated_reserve_keeps_native_maximum_out_of_executable_effects():
    """A main merge must not revive the old resource-gain interpretation."""
    authority = json.loads((RULES_TEXT.parents[1] /
        'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    reserve = authority['mechanics'][SOURCE]
    assert reserve['effects'] == []
    assert reserve['activation']['economy'] == 'passive'
