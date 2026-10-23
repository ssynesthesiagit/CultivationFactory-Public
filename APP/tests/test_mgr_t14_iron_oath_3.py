"""Native table receipts for bounded Iron Oath clauses, not whole-row closure."""
import hashlib
import json

import pytest

from combat.canonical import canonical_sha256
from combat.ext import foundation_combat as f
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import (OWNER, ALLY, FOE, fixture, candidate, settle,
                                   turn, reload, sealed_native_attack)

ROAR = 'tianxia.talent.warleader.frightful_roar'
HASHES = {
    'iron_oath_boundary': '4ba1a7e243f32bae147044c27e0d73cb4fd08345d3e5456521ff18b40692416a',
    'oath_skin_mantle': '130a3acd928b811164f0d60a2b3db6f54c2e6167d0ebc41c9790a85da63604fd',
    'scar_ledger_defense': '4750bacd4d3f3b5f8fd9b1d74f7ed533084c5770023bb114a5f07331996d3ab8',
    'shield_body_forging': '6772f50ef9e7db41159e259fd4e68b3577b529646eebede60cbbb6631dc3f9cc',
    'stand_fast_witness': 'bfb4f77d5f8fcf3b23032c3646fa1e43438701447f7847ecf674ce2ed2d209a9',
}


def use(combat, table, mid, name, target=None, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                  choices=choices or {})


def oath_table(tmp_path, *, dc=100, mode='MANUAL', stage='Awakened', damage=1, foe_talents=(), owner_talents=(), path_resource=30, followup_attack=False, pressure_economy='BONUS_ACTION'):
    doc = sheet(list(owner_talents), cl=15)
    doc['foundation'] = {'foundation_id': f.GROUPS['oath'][0], 'stage': stage,
                         'resource': {'name': 'Guarding Iron', 'resource_id': 'fixture:guarding_iron',
                                      'maximum': 1, 'current': 0}}
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = path_resource
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([ROAR, *foe_talents], cl=15, dc=dc)

    def attacks(bundles):
        # A native attack supplies DAMAGE_COMMITTED; no fabricated duty/intent
        # tag or injected resource gain is used. The bonus economy permits the
        # real Roar to follow in the same turn, before the token expires.
        sealed_native_attack(bundles[2], 'Pressure hit', modifier=damage, count=1,
                             sides=2, attack_bonus=100, range_ft=5)
        bundles[2]['action_catalog'][-1]['economy'] = pressure_economy
        if followup_attack:
            sealed_native_attack(bundles[2], 'Follow-up pressure hit', modifier=damage, count=1,
                                 sides=2, attack_bonus=100, range_ft=5)
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])

    combat, table, mid = fixture(tmp_path, list(owner_talents), owner_bundle=owner, foe_sheet=foe,
        foe_position={'x': 3, 'y': 5}, bundle_transform=attacks, seed='IRON-OATH-3',
        modes={OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'})
    from tests.iron_oath_support import duty
    duty(combat, table, mid)
    use(combat, table, mid, 'Declare Protected Subject',
        choices={f.CHOICE + 'foundation_subject': [ALLY]})
    return combat, table, mid


def test_full_decoded_controlling_sources():
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    for leaf, expected in HASHES.items():
        assert hashlib.sha256(texts[f.feature('oath', leaf)].encode()).hexdigest() == expected


@pytest.mark.parametrize('dc', [1, 100], ids=['already-succeeded', 'cannot-rescue'])
@pytest.mark.parametrize('accept', [True, False], ids=['spend', 'decline'])
def test_stand_fast_manual_keeps_legal_post_roll_choice(tmp_path, dc, accept):
    combat, table, mid = oath_table(tmp_path, dc=dc)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert not any(e.event_type == 'RESOURCE_SPENT' and
                   e.source_definition_id == f.feature('oath', 'stand_fast_witness') for e in before.events)
    prompts = use(combat, table, mid, 'Frightful Roar', choices={
        f.CHOICE + 'foundation_combat': ['use'] if accept else None})
    prompt = next(p for p in prompts if p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_combat')
    assert 'Stand' in str(prompt)
    assert 'Frightful Roar' in str(prompt)
    assert 'Guarding Iron' in str(prompt) or 'guarding iron' in str(prompt)
    after = reload(tmp_path, mid)
    owner = after.state.actors[OWNER]
    assert owner.resources[f.pool('oath')] == int(not accept)
    changes = [e for e in after.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert len(changes) == int(accept)
    if accept:
        assert changes[0].payload['bonus'] == 4
        assert changes[0].payload['result']['total'] == changes[0].payload['original']['total'] + 4
    assert any(c.condition_id == 'condition:typed.frightened' for c in owner.conditions.values()) is (dc == 100)


@pytest.mark.parametrize('dc', [1, 100])
def test_automatic_stand_fast_does_not_waste_iron(tmp_path, dc):
    combat, table, mid = oath_table(tmp_path, dc=dc)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    use(combat, table, mid, 'Pressure hit', OWNER)
    prompts = use(combat, table, mid, 'Frightful Roar')
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert not any(e.event_type == 'D20_REWRITTEN' and
                   e.source_definition_id == f.feature('oath', 'stand_fast_witness') for e in after.events)
    assert not any(p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_combat' for p in prompts)


@pytest.mark.parametrize('selected', [False, True])
def test_existing_mantle_adds_hp_without_spending_generated_iron(tmp_path, selected):
    combat, table, mid = oath_table(tmp_path, stage='Refined')
    if selected:
        use(combat, table, mid, 'Foundation expression: Oath-Skin Mantle')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[f.pool('oath')] == 1
    assert owner.temporary_hp == (4 if selected else 0)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == f.pool('oath')
                   for e in engine.events)


def test_no_token_no_stand_fast_offer_and_awakened_has_no_mantle(tmp_path):
    combat, table, mid = oath_table(tmp_path)
    engine = reload(tmp_path, mid)
    assert not any('Oath-Skin Mantle' in engine.action_catalog[c.source_definition_id].display_name
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Frightful Roar')
    assert not any(p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_combat' for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[f.pool('oath')] == 0
