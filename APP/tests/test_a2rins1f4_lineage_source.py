"""Demon-Blood source permissions through table commits, presets and cold replay."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat.ext import ancestral_bloodline as lineage
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatServiceError
from tests.cw2_service_support import add_action
from tests.h1_support import sheet
from tests.test_r9i_karma_persistence import act
from tests.test_a2r_ancestral_bloodline import setup, pick, qi_bolt, by_name
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, turn


SOURCE = {
    'source_id': 'source:test.ember_ancestor',
    'rules_text': 'Ember ancestor lineage: Fire is a lineage damage type.',
    'damage_types': ['Fire'],
}


def owner_bundle(source=SOURCE, *, owns=True):
    document = sheet([], cl=15)
    document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    document.setdefault('path_and_subpath', {})['ancestral_lineage_source'] = dict(source)
    document.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = (
        [lineage.INSIGHT] if owns else [])
    return compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})


@pytest.mark.parametrize('relative,feature', [
    ('combat/rules/feature_blocks.d/a2_group_insights_1_residual.json', 'insight.borrowed-golden-form'),
    ('combat/rules/feature_blocks.d/insights7.json', 'insight.reservoir-core-refinement'),
    ('combat/rules/feature_blocks.d/tabik.json', 'tianxia.path.qi_cultivation.feature.golden_core_form'),
    ('combat/rules/feature_blocks.d/auto8-athletics.json', 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'),
])
def test_real_service_inputs_are_exported(relative, feature):
    # These are dynamic loader inputs used by the real character compiler.
    # Explicit source paths keep the public export's test closure complete.
    from combat.typed_reactions import rules
    path = Path(__file__).resolve().parents[1] / relative
    rows = json.loads(path.read_text())['features']
    assert rules()['features'][feature]['block'] == rows[feature]['block']


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
def test_source_authorized_fire_is_selectable_and_persists_with_its_rider(tmp_path, monkeypatch, mode):
    from combat import settings_service
    bundle = owner_bundle()
    gifts = {a['display_name']: a for a in bundle['action_catalog'] if '.lineage_gift.demon.' in a['source_definition_id']}
    assert set(gifts) == {'Ancestral Bloodline: Demon-Blood -- ' + kind
                          for kind in ('Necrotic', 'Psychic', 'Poison', 'Fire')}
    title = 'Ancestral Bloodline: Demon-Blood -- Fire'
    if mode != 'MANUAL':
        # Real roster preset admission must happen before the automatic default.
        monkeypatch.setattr(settings_service, 'presets_for_roster',
                            lambda service, ids: {OWNER: [gifts[title]['source_definition_id']]})
    combat, table, mid = setup(tmp_path, owner_bundle=bundle, bundle_transform=qi_bolt,
                              modes={OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'})
    if mode == 'MANUAL':
        pick(combat, table, mid, title)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert lineage.gift_of(actor) == 'demon'
    assert lineage.chosen_damage(actor) == 'FIRE'
    passive = next(r for r in engine.typed_passive_rows[OWNER] if r.get('kind') == 'lineage_gift')
    assert passive['lineage_source'] == {**SOURCE, 'damage_types': ['fire']}
    assert not any('.lineage_gift.' in c.source_definition_id for c in engine.legal_candidates())
    if mode != 'MANUAL':
        # Preset admission uses the real automatic/model seat setup; no model
        # service is called. The manual case below also checks actual damage.
        return
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Qi Bolt', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    rider = [ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
             and ev.source_definition_id == lineage.INSIGHT]
    assert len(rider) == 1 and rider[0].payload['damage_type'] == 'FIRE'
    assert 1 <= int(rider[0].payload['hp_damage']) <= 6


def test_source_cannot_authorize_unprinted_types_or_another_gifts_types(tmp_path):
    bundle = owner_bundle()
    assert not any(a['display_name'] == 'Ancestral Bloodline: Demon-Blood -- Cold'
                   for a in bundle['action_catalog'])
    # A stale/supplied row cannot bypass execution validation after cold reload.
    def unprinted_pick(bundles):
        add_action(bundles[0], 'Try unprinted Cold',
                   [{'type': 'lineage_gift_pick', 'gift': 'demon', 'damage_type': 'cold'}],
                   target='SELF', typed={'source': lineage.INSIGHT})
    combat, table, mid = setup(tmp_path, owner_bundle=bundle, bundle_transform=unprinted_pick)
    with pytest.raises(CombatServiceError) as rejected:
        act(table, mid, candidate(combat, mid, 'Try unprinted Cold').candidate_id)
    assert rejected.value.diagnostic.code == 'COMBAT_AI_INTENT_INVALID'
    assert 'printed ancestral gift' in rejected.value.diagnostic.details['reason']
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    with pytest.raises(ValueError, match='printed ancestral gift'):
        lineage.record_gift(SimpleNamespace(engine=engine, actor=actor),
                            {'gift': 'demon', 'damage_type': 'cold'})
    assert lineage.gift_of(reload(tmp_path, mid).state.actors[OWNER]) == ''
    pick(combat, table, mid, 'Ancestral Bloodline: Demon-Blood -- Fire')
    assert lineage.chosen_damage(reload(tmp_path, mid).state.actors[OWNER]) == 'FIRE'
    # A Fire/Force source adds Force only to Demon-Blood, never Dragon/Phoenix.
    extra = owner_bundle({**SOURCE, 'rules_text': 'Lineage damage types: Fire and Force.',
                          'damage_types': ['fire', 'Force', 'FIRE']})
    names = [a['display_name'] for a in extra['action_catalog']]
    assert names.count('Ancestral Bloodline: Demon-Blood -- Fire') == 1
    assert 'Ancestral Bloodline: Demon-Blood -- Force' in names
    assert 'Ancestral Bloodline: Azure Dragon -- Force' not in names
    assert 'Ancestral Bloodline: Vermilion Phoenix -- Force' not in names


@pytest.mark.parametrize('source', [
    {**SOURCE, 'damage_types': ['cold']},
    {**SOURCE, 'damage_types': ['wildfire'], 'rules_text': 'Wildfire damage.'},
    {**SOURCE, 'source_id': ''},
    {**SOURCE, 'rules_text': ''},
    {**SOURCE, 'damage_types': 'Fire'},
])
def test_unbacked_source_types_are_rejected(source):
    with pytest.raises(ValueError, match='ancestral lineage'):
        lineage.lineage_source({'path_and_subpath': {'ancestral_lineage_source': source}})


def test_source_is_inert_without_insight_and_legacy_standard_choices_stay(tmp_path):
    plain = owner_bundle(owns=False)
    assert not any('.lineage_gift' in a['source_definition_id'] for a in plain['action_catalog'])
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    assert {kind for kind in ('Necrotic', 'Psychic', 'Poison')
            if by_name(engine, 'Ancestral Bloodline: Demon-Blood -- ' + kind)} == {'Necrotic', 'Psychic', 'Poison'}
    assert not by_name(engine, 'Ancestral Bloodline: Demon-Blood -- Fire')
