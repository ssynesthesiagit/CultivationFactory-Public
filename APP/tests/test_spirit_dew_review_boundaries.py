"""Native table boundaries: unusable support and an independently rescued save."""

import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool
from tests.test_spirit_dew_maintenance import REFRAIN, WAR
from tests.test_spirit_dew_protection import AEGIS
from tests.test_spirit_dew_reduction import OWNER_ROW
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

SNARE = 'TAL_THREAD_MERIDIAN_SNARE'
SAGE = 'TAL_MONKEY_STYLE_GREAT_SAGE_EQUAL_TO_HEAVEN'
UNSHAKEN = 'insight.unshaken-rhythm'


def _supporter(talent):
    return compile_character(sheet([talent, OWNER_ROW], foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0}}), actor_id=OWNER,
        reaction_plan={'ask': True})


@pytest.mark.parametrize('stage,ally_x,reach', [('Awakened', 9, 30), ('Refined', 15, 60)])
def test_support_range_survives_cold_reload(tmp_path, stage, ally_x, reach):
    from combat.ext.foundations3 import open_channels_range
    from tests.test_a2_foundations3 import open_channels_setup, use

    combat, table, mid = open_channels_setup(tmp_path, stage=stage,
                                            ally_position={'x': ally_x, 'y': 6})
    loaded = reload(tmp_path, mid)
    assert open_channels_range(loaded, loaded.state.actors[OWNER], loaded.state.actors[ALLY]) == reach
    use(combat, table, mid, 'Support ally', ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 1


def test_unshaken_rhythm_does_not_credit_failed_calm_support(tmp_path):
    # The compiler loads ownership from a runtime directory; keep this fixture
    # contract explicit so reduced test snapshots preserve the native rescue.
    root = Path(__file__).resolve().parents[1]
    assert UNSHAKEN in json.loads((root / 'combat/rules/feature_blocks.d/music_insights.json').read_text())['features']

    def delivery(bundles):
        # Even Advantage cannot meet DC 10; Unshaken keeps the die and forces
        # success. This must not turn Calm's failed roll into support credit.
        bundles[1]['actor_template']['saving_throws']['CON'] = -100
        add_action(bundles[2], 'Concentration pressure', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])

    combat, table, mid = fixture(tmp_path, [], owner_bundle=_supporter(REFRAIN),
        ally_talents=[WAR, UNSHAKEN], bundle_transform=delivery,
        seed='DEW-UNSHAKEN-RESCUE', named=True)
    settle(table, mid, candidate(combat, mid, 'Soul-Stirring Refrain: Calm', target=ALLY).candidate_id,
           choices={})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'War Song').candidate_id)
    turn(table, mid, FOE)
    rescue_source = 'reaction:typed.' + UNSHAKEN
    prompts = settle(table, mid, candidate(combat, mid, 'Concentration pressure', target=ALLY).candidate_id,
                     picks={rescue_source: 'USE'})
    assert any(p['context']['reaction_source_id'] == rescue_source for p in prompts)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration' and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE'
    assert saved.payload['total_before_outcome'] < saved.payload['dc']
    assert saved.payload['total'] >= saved.payload['dc']
    assert saved.payload['forced_outcome'] == 'success'
    assert saved.payload['outcome_source_id'] == UNSHAKEN
    assert saved.payload['success'] is True
    assert engine.state.actors[ALLY].concentration is not None
    assert any(c.condition_id == 'condition:typed.music_calm'
               for c in engine.state.actors[ALLY].conditions.values())
    assert not getattr(engine, '_typed_roll_outcome', {})
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0


def test_suppression_keeps_independent_numeric_concentration_support():
    from combat import concentration
    from combat.ext.music import OPENING_CONCENTRATION
    from combat.gate2_engine import SYSTEM_CONCENTRATION
    from tests.h1_support import duel, ME, FOE as OPPONENT

    engine = duel([])
    subject = engine.state.actors[OPPONENT]
    engine._apply_condition(subject, concentration.MODE, 'test:calm', ME,
        expires_on='UNTIL_REMOVED', data={'rule': {'concentration_mode': 'ADVANTAGE'}})
    engine._apply_condition(subject, OPENING_CONCENTRATION, 'test:opening', ME,
        expires_on='UNTIL_REMOVED', data={'bonus': 4})
    assert concentration.support_sources(engine, subject) == [
        {'actor_id': ME, 'source_id': 'test:calm'}, {'actor_id': ME, 'source_id': 'test:opening'}]
    engine._apply_condition(subject, 'condition:typed.cannot_advantage_con_saves',
                            'test:breath_line', ME, expires_on='UNTIL_REMOVED')
    assert concentration.support_sources(engine, subject) == [{'actor_id': ME, 'source_id': 'test:opening'}]
    roll = engine._roll_save(subject, 'CON', 10, SYSTEM_CONCENTRATION,
                            roll_context={'save_modes': sorted(concentration.save_modes(engine, subject))})
    assert roll.mode == 'NORMAL'
    assert roll.modifier == subject.saving_throws.get('CON', 0) + 4


def test_breath_line_suppresses_calm_credit_on_successful_concentration(tmp_path):
    def delivery(bundles):
        doc = sheet([SNARE], cl=15, dc=99)
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        bundles[2] = compile_character(doc, actor_id=FOE, reaction_plan={'ask': True})
        add_action(bundles[2], 'Concentration pressure', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])

    combat, table, mid = fixture(tmp_path, [], owner_bundle=_supporter(REFRAIN),
        ally_talents=[WAR], ally_score=30, bundle_transform=delivery,
        seed='DEW-CALM-MAINTENANCE', named=True)
    settle(table, mid, candidate(combat, mid, 'Soul-Stirring Refrain: Calm', target=ALLY).candidate_id,
           choices={})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'War Song').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Meridian Snare: Breath Line', target=ALLY).candidate_id)
    snared = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.cannot_advantage_con_saves'
               for c in snared.state.actors[ALLY].conditions.values())
    assert snared.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    # Breath Line lasts through the snare creator's next turn. Keep the paid
    # Calm grant alive while the same enemy delivers the actual damage check.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Concentration pressure', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration' and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'NORMAL'
    assert saved.payload['success'] is True
    assert engine.state.actors[ALLY].concentration is not None
    assert any(c.condition_id == 'condition:typed.music_calm'
               for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0


def test_laugh_at_heaven_does_not_credit_failed_aegis_protection(tmp_path):
    def delivery(bundles):
        bundles[2] = compile_character(sheet([REFRAIN], cl=15, dc=99), actor_id=FOE,
                                       reaction_plan={'ask': True})

    combat, table, mid = fixture(tmp_path, [], owner_bundle=_supporter(AEGIS),
        ally_talents=[SAGE], bundle_transform=delivery, seed='DEW-FEAR-RESCUE', named=True)
    settle(table, mid, candidate(combat, mid, 'Radiant Aegis of the Heart', target=ALLY).candidate_id,
           choices={})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Great Sage Equal to Heaven').candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid,
        candidate(combat, mid, 'Soul-Stirring Refrain: Fear (any creature)', target=ALLY).candidate_id,
        picks={'choice:willing.consent': ['refuse'],
               'choice:needle.monkey_laugh_at_heaven': ['succeed']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.monkey_laugh_at_heaven'
               for p in prompts)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and REFRAIN in e.source_definition_id and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE'
    assert saved.payload['total'] < saved.payload['dc']
    assert any(c.condition_id == 'condition:typed.monkey_laughed'
               for c in engine.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id == 'condition:typed.frightened'
                   for c in engine.state.actors[ALLY].conditions.values())
    assert not getattr(engine, '_typed_roll_outcome', {})
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
