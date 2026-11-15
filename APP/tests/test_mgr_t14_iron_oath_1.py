"""Iron Oath inventory evidence via native actions, table commits and cold replay.

These tests certify the named mechanical clauses only, not the absent GM duty
adjudication/scene producer or the complete source rows.
"""
import hashlib
import json

import pytest

from combat.ext import foundation_combat as f
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, turn, settle, reload, candidate, OWNER, ALLY, FOE

CURSE = 'tianxia.tradition.spirit.dream_eater.feature.sleeping_curse'
SPIKE = 'tianxia.path.spirit_awakening.feature.mind_spike'
TOUCH = 'tianxia.tradition.spirit.dream_eater.feature.nightmare_touch'


def oath_table(tmp_path, *, stage='Awakened', foundation='iron_oath_skin_v0_2B'):
    document = sheet([], cl=15, name='Oath bearer')
    document['foundation'] = {
        'foundation_id': foundation, 'stage': stage,
        'resource': {'name': 'Guarding Iron', 'resource_id': 'tianxia.resource.foundation.guarding_iron',
                     'maximum': 1, 'current': 0},
    }
    stats = document['ability_scores_and_statistics']
    stats['hit_points']['maximum'] = 500
    stats['armor_class']['base_value'] = 1
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([CURSE, SPIKE, TOUCH], cl=15, dc=100, primary='Resonance', key='WIS', name='Dream eater')
    foe['identity']['path'] = 'Spirit Awakening'
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe,
                   foe_position={'x': 3, 'y': 5}, seed='IRON-OATH-CONSCIOUS')


def use(combat, table, mid, name, target=None, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                  choices=choices or {})


@pytest.mark.parametrize('sleeping', [False, True], ids=['conscious', 'native-cursed-sleep'])
def test_guarding_iron_requires_consciousness_after_native_damage(tmp_path, sleeping):
    combat, table, mid = oath_table(tmp_path)
    use(combat, table, mid, 'Declare Protected Subject',
        choices={f.CHOICE + 'foundation_subject': [ALLY]})
    turn(table, mid, FOE)
    use(combat, table, mid, 'Nightmare Touch', OWNER)
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    # Mind Spike supplies the actual Resonance Mark prerequisite for Sleeping
    # Curse. No test writes a mark, condition, resource or turn flag.
    use(combat, table, mid, 'Mind Spike', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 1
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[f.pool('oath')] == 0
    use(combat, table, mid, 'Sleeping Curse' if sleeping else 'Dodge', OWNER if sleeping else None)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.unconscious'
               for c in engine.state.actors[OWNER].conditions.values()) is sleeping
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    prompts = use(combat, table, mid, 'Unarmed Strike', OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert 0 < owner.current_hp < before
    assert owner.active
    assert any(c.condition_id == 'condition:typed.unconscious'
               for c in owner.conditions.values()) is sleeping
    assert owner.resources[f.pool('oath')] == int(not sleeping)
    assert not any(p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_combat'
                   for p in prompts)  # no token may pay for its generating hit


@pytest.mark.parametrize('stage,foundation,available', [
    ('Awakened', 'iron_oath_skin_v0_2B', True),
    ('Common Expression', 'iron_oath_skin_v0_2B', False),
    ('Latent', 'iron_oath_skin_v0_2B', False),
    ('Awakened', 'heaven_tyrant_body_v0_2D', False),
])
def test_native_declaration_stage_and_wrong_foundation_controls(tmp_path, stage, foundation, available):
    combat, table, mid = oath_table(tmp_path, stage=stage, foundation=foundation)
    engine = reload(tmp_path, mid)
    declarations = [c for c in engine.legal_candidates()
                    if engine.action_catalog.get(c.source_definition_id)
                    and engine.action_catalog[c.source_definition_id].display_name == 'Declare Protected Subject']
    assert bool(declarations) is available
    if available:
        prompts = use(combat, table, mid, 'Declare Protected Subject',
                      choices={f.CHOICE + 'foundation_subject': [ALLY]})
        assert any(p['context'].get('reaction_source_id') == f.CHOICE + 'foundation_subject'
                   for p in prompts)
        owner = reload(tmp_path, mid).state.actors[OWNER]
        assert f.held(owner, 'protected_subject').data['subject'] == ALLY
        assert owner.action_available and owner.bonus_action_available
        assert owner.resources[f.pool('oath')] == 0


def test_exact_controlling_source_hashes():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    expected = {
        'declare_protected_subject': '5b6c8e259bec0768c374d9b37d2ed0d528990128f445de3235ecd6e929326231',
        'generate_guarding_iron': '740597f6cd45f1fc477c2491b603c286ff0cef2b86ca875d4d4df96d62c0000a',
        'oath_skin_frame': '77f358d41a5453c702cf0bc2045cc856f356c79723e17aa4183e481aecbd2098',
    }
    for leaf, digest in expected.items():
        assert hashlib.sha256(text[f.feature('oath', leaf)].encode()).hexdigest() == digest
