"""Mud-Lotus conversion settings: Lotus wording, Severance defaults, unselected expression, Blackblood category match."""
from types import SimpleNamespace

from combat.ext import foundation_conversion_bonus as fcb
from combat.ext import foundations4_rolls as rolls
from combat.typed_reactions import rules

LOTUS = 'foundation.mud_lotus_dantian_v0_2A.refined_lotus_recovery'


def _info(owned):
    return {'owned_ids': [owned], 'actor_id': 'actor:test.lotus', 'short': 'mud_lotus',
            'numbers': {'pb': 3, 'key_mod': 2, 'save_dc': 14, 'attack_bonus': 6},
            'mechanics': {owned: {'name': 'Refined Lotus Recovery'}}}


def _texts(actions):
    return ' '.join([a.display_name + ' ' + str(a.parameters.get('setting_description', ''))
                     + ' ' + str((a.parameters.get('typed') or {}).get('effects')) for a in actions or []])


def test_lotus_owner_settings_do_not_name_severance_edge():
    # Before the fix the expression and source-status actions were hardcoded to Severance Edge.
    texts = _texts(fcb.expression_actions(_info(LOTUS))) + ' ' + _texts(fcb.source_status_actions(_info(LOTUS)))
    assert 'Lotus Dew' in texts
    assert 'Refined Lotus Recovery bonuses' in texts
    assert 'Severance' not in texts


def test_severance_rows_keep_their_printed_wording_by_default():
    # Defaults stay Severance Edge for rows that name no pool or phrase.
    spec = {'block': 'foundation_conversion_bonus', 'conversions': ['cut'], 'selected': False}
    assert spec.get('pool_label') is None
    assert fcb.SEVERANCE_POOL_LABEL == 'Severance Edge'
    assert fcb.SEVERANCE_BONUS_PHRASE == 'Severance Edge evolution bonuses'
    row = fcb.compile_bonus(fcb.BLOCK, spec, {'feature_id': 'x'}, {'pb': 2})[0]
    assert row['pool_label'] == 'Severance Edge'
    assert row['bonus_phrase'] == 'Severance Edge evolution bonuses'


def test_refined_lotus_record_states_only_guard_as_needs_system():
    # The Witness is now paid through the shared provider, so only Guard remains unwired.
    assert rules()['features'][LOTUS]['needs_system'] == ['mud_lotus_guard']


def test_unselected_expression_leaves_the_witness_roll_at_base_pb(monkeypatch):
    # With no Refined expression the shared provider quotes nothing, so the Witness keeps its own +PB.
    monkeypatch.setattr(fcb, 'conversion_bonus', lambda engine, actor, conversion, receipt_id=None: 0)
    holder = SimpleNamespace(feature_id='foundation.mud_lotus_dantian_v0_2A.humble_medicine_witness',
                             numbers={'pb': 3}, actor=SimpleNamespace())
    assert rolls.roll_bonus(None, holder, SimpleNamespace(roll=SimpleNamespace(roll_id='r'))) == 3


def test_blackblood_refusal_keeps_main_matching_for_a_category_save(monkeypatch):
    # Finding 1: a WIS typed 'category:poisoned' save stays outside Blackblood on main. Before the fix it matched.
    monkeypatch.setattr(rolls, 'pool_id', lambda actor, name: 'resource:test.pool')
    monkeypatch.setattr(rolls, '_holds', lambda engine, actor, resource, amount: True)
    holder = SimpleNamespace(actor=SimpleNamespace())
    save = SimpleNamespace(kind='save', ability='WIS', named=['category:poisoned'])
    assert rolls.guard('blackblood_refusal')(None, holder, save) is False


def test_refined_lotus_expression_states_the_unautomated_guard_bonus():
    # Regression for finding 3: the Refined expression must tell the player Guard's +PB is not automated.
    # Before the fix the expression text said nothing about Guard and this asserted False.
    text = _texts(fcb.expression_actions(_info(LOTUS)))
    assert 'Guard' in text and 'not automated' in text
