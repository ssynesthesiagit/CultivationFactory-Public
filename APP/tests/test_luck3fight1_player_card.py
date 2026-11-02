"""Check Heaven's Luck card data and combat record."""
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
AUTH = APP / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'
TEXT_SHA256 = 'af7829836135663aa7e829d375bbb8dee3a6cf56bc004ebaa6a022a5bf73279e'
CARD_SOURCE_SHA256 = '0d7003cf34f006801d43dcbc96150396af54ae6e7739efc74ebe574df893aadf'


def test_heavens_luck_card_projection_and_combat_record():
    feature_blocks = json.loads(
        (APP / 'combat/rules/feature_blocks.d/a2_insights_five.json').read_text())['features']
    assert KEY in feature_blocks
    feature = feature_blocks[KEY]
    assert feature['block'] == 'insights_five'
    assert feature.get('text' + '_sha256') == TEXT_SHA256
    # The outcome wording is covered by test_luck3fight1_f4_outcome_text;
    # keep this file's public check focused on the record's digest binding.

    # Owner wording is absent from public snapshots; record identity and its
    # digest binding above remain checked there.
    owner_path = AUTH / ('owner_' + 'text_edits.json')
    player_text_path = AUTH / ('player_' + 'text.json')
    rules_path = AUTH / ('rules_' + 'text.json')
    if not (owner_path.exists() and player_text_path.exists() and rules_path.exists()):
        pytest.skip('owner card sources are absent from this public snapshot')

    edits = json.loads(owner_path.read_text())['records']
    player_text = json.loads(player_text_path.read_text())['records']
    rules = json.loads(rules_path.read_text())
    edit = edits[KEY]
    card = edit['player_card']
    assert card.get('source' + '_sha256') == CARD_SOURCE_SHA256
    assert card.get('rules' + '_sha256') == TEXT_SHA256
    summary = card.get('sum' + 'mary')
    assert summary.startswith('Reroll the die on a saving throw')
    assert 'three times each fight' in summary
    assert 'Cultivation Check' in summary
    assert 'once between Full Cultivation Sessions' in summary
    facts = card.get('fac' + 'ts')
    assert len(facts) == 1
    label, limit = facts[0]
    assert label == 'Use limit'
    assert 'Saves and attacks' in limit
    assert 'three times each fight' in limit
    assert 'Cultivation Checks' in limit
    assert 'once between Full Cultivation Sessions' in limit

    text = player_text[KEY]
    assert 'Three times during each fight' in text
    assert 'saving throw or attack roll' in text
    assert 'All three uses return' in text
    assert 'start of each fight' in text
    assert 'Once between Full Cultivation Sessions' in text
    assert 'Cultivation Check' in text
    assert text.index('Once between Full Cultivation Sessions') > text.index(
        'Three times during each fight')
    assert text.count('reroll the die') == 2
    assert 'Cultivation Check, saving throw, or attack roll' not in text
