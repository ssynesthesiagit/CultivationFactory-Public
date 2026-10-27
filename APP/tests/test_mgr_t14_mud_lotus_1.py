"""Mud Lotus consciousness admission through table commits and cold replay.

The condition and hostile save are executed by the ordinary typed dispatcher;
no Foundation hook is called directly and no saved state is edited.
"""
import hashlib
import json

import pytest

from tests.h1_support import ROOT
from tests.test_a2_foundations3 import add_action, setup, use, pool, BOON
from tests.worker2_support import OWNER, ALLY, FOE, turn, reload


@pytest.mark.parametrize('condition,expected', [
    ('unconscious', 0),
    ('life_unconscious', 0),
    ('dream_sleep', 0),
    ('stunned', 1),
    ('paralyzed', 1),
])
def test_dew_requires_consciousness_not_just_positive_hp(tmp_path, condition, expected):
    def delivery(bundles):
        add_action(bundles[2], 'Condition before recovery', [
            {'type': 'condition', 'condition': condition, 'applies_to': 'target',
             'duration': {'kind': 'minute'}}], economy='NONE')

    combat, table, mid = setup(tmp_path, 'lotus', initial=0, extra=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Condition before recovery', OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.current_hp > 0 and owner.active
    assert any(c.condition_id == 'condition:typed.' + condition for c in owner.conditions.values())
    use(combat, table, mid, 'Successful poison save', ALLY)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert save.actor_id == ALLY and save.payload['success'] is True
    assert engine.state.actors[OWNER].resources[pool('lotus')] == expected
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.actor_id == OWNER and e.payload.get('resource_id') == pool('lotus')]
    assert len(gains) == expected
    assert engine.state.actors[ALLY].resources.get(pool('lotus'), 0) == 0


def test_latent_foundation_does_not_own_awakened_generation(tmp_path):
    combat, table, mid = setup(tmp_path, 'lotus', initial=0, stage='Latent')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Successful poison save', ALLY)
    engine = reload(tmp_path, mid)
    assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['success']
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0


def test_real_generated_dew_pays_recovery_on_a_later_turn(tmp_path):
    combat, table, mid = setup(tmp_path, 'lotus', initial=0)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Successful poison save', ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('lotus')] == 1
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Lotus-Root Recovery', ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    assert engine.state.actors[ALLY].temporary_hp == 6
    assert any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())
    gained = next(i for i, e in enumerate(engine.events) if e.event_type == 'RESOURCE_GAINED'
                  and e.actor_id == OWNER and e.payload.get('resource_id') == pool('lotus'))
    spent = next(i for i, e in enumerate(engine.events) if e.event_type == 'RESOURCE_SPENT'
                 and e.actor_id == OWNER and e.payload.get('resource_id') == pool('lotus'))
    grant = next(i for i, e in enumerate(engine.events) if e.event_type == 'TEMP_HP_GRANTED')
    assert gained < spent < grant


def test_controlling_decoded_source_matches_manifest_and_pinned_builder_source():
    """Decoded rule hashes and catalogue-section hashes have different scopes."""
    from character_creation.foundation_corpus_release import verified_sections
    from non_sphere_authority.foundation_features import features_for_stage

    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    expected = {
        'generate_lotus_dew': '2131ad4a049c7992f5cfb3ad9d55bc9359499e56bb898a51f954eebc813016f6',
        'mud_lotus_reserve': 'a40624d6fbcfd45eff7769250b7dd82155b2faa5077d9640561f81208a7e35de',
        'lotus_root_recovery': '565d8241caeebb75ea91408566a044482560b5a0b92d2239f47e59bb9d4918a4',
    }
    # This production reader authenticates both whole catalogue and registry.
    sections = verified_sections()
    assert any(b'# 29. Mud Lotus Dantian' in value for value in sections.values())
    features = {r['id']: r for r in features_for_stage('mud_lotus_dantian_v0_2A', 'Awakened')}
    for slug, digest in expected.items():
        mid = 'foundation.mud_lotus_dantian_v0_2A.' + slug
        assert hashlib.sha256(texts[mid].encode()).hexdigest() == digest
        feature = features[mid]
        builder_text = '#### ' + feature['name'] + '\n\n' + '\n'.join(
            f'**{key}:** {value}' for key, value in feature['fields'].items()) + '\n'
        assert builder_text.strip() == texts[mid].strip()
