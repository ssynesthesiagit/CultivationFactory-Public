"""The player card keeps Heaven's Luck's fight and session limits distinct.

The owner's wording is private: the owner files are read at test time and the checks skip on public snapshots, which
do not carry them. Checks that need the card renderer import it only after that skip.
"""
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
AUTH = APP / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'
TEXT_SHA256 = 'af7829836135663aa7e829d375bbb8dee3a6cf56bc004ebaa6a022a5bf73279e'
CARD_SOURCE_SHA256 = '0d7003cf34f006801d43dcbc96150396af54ae6e7739efc74ebe574df893aadf'


def _private_sources():
    owner_path = AUTH / ('owner_' + 'text_edits.json')
    player_text_path = AUTH / ('player_' + 'text.json')
    rules_path = AUTH / ('rules_' + 'text.json')
    if not (owner_path.exists() and player_text_path.exists() and rules_path.exists()):
        pytest.skip('owner card sources are absent from this public snapshot')
    edit = json.loads(owner_path.read_text())['records'][KEY]
    built = json.loads(player_text_path.read_text())['records'][KEY]
    rules = json.loads(rules_path.read_text())
    return edit, built, rules


def _limit_lines(text):
    lines = text.splitlines()
    fight_line = next(line for line in lines if line.startswith('Three times during each fight,'))
    session_line = next(line for line in lines if line.startswith('Once between Full Cultivation Sessions,'))
    return fight_line, session_line


def _in_order(text, parts):
    assert all(part in text for part in parts)
    assert [text.index(part) for part in parts] == sorted(text.index(part) for part in parts)


def test_heavens_luck_card_projection_and_combat_record():
    feature_blocks = json.loads(
        (APP / 'combat/rules/feature_blocks.d/a2_insights_five.json').read_text())['features']
    assert KEY in feature_blocks
    feature = feature_blocks[KEY]
    assert feature['block'] == 'insights_five'
    assert feature.get('text' + '_sha256') == TEXT_SHA256
    # The outcome wording is covered by test_luck3fight1_f4_outcome_text;
    # keep this file's public check focused on the record's digest binding.

    edit, built, _rules = _private_sources()
    card = edit['player_card']
    assert card.get('source' + '_sha256') == CARD_SOURCE_SHA256
    assert card.get('rules' + '_sha256') == TEXT_SHA256
    summary = card.get('sum' + 'mary')
    assert summary.startswith('Reroll the die on a saving throw')
    _in_order(summary, ('saving throw or attack roll', 'three times each fight', 'Cultivation Check',
                        'once between Full Cultivation Sessions'))
    facts = card.get('fac' + 'ts')
    assert len(facts) == 1
    label, limit = facts[0]
    assert label == 'Use limit'
    _in_order(limit, ('Saves and attacks:', 'three times each fight', 'Cultivation Checks:',
                      'once between Full Cultivation Sessions'))

    text = edit['player_text']
    assert 'Three times during each fight' in text
    assert 'saving throw or attack roll' in text
    assert 'All three uses return at the start of each fight.' in text
    assert 'Once between Full Cultivation Sessions' in text
    assert 'Cultivation Check' in text
    assert text.index('Once between Full Cultivation Sessions') > text.index('Three times during each fight')
    assert text.count('reroll the die') == 2
    # The old single sentence that put a Cultivation Check under the three-per-fight limit must be gone.
    assert 'Cultivation Check, saving throw, or attack roll' not in text


def test_built_player_text_matches_the_owner_edit():
    edit, built, _rules = _private_sources()
    fight_line, session_line = _limit_lines(edit['player_text'])
    assert fight_line in built and session_line in built
    assert 'Cultivation Check, saving throw, or attack roll' not in built


def test_rendered_card_states_the_split_limit_and_is_bound_to_the_new_text():
    edit, _built, rules = _private_sources()
    from factory_authoring import player_rules as pr
    from factory_authoring.owner_text_edits import player_wording
    # The same clarified text the batch build produces for this one record (no other record is touched).
    clarified = pr.format_card(player_wording(pr.display_prose(edit['player_text'], legacy_fields=True), edit))
    assert pr.card_sha(clarified) == edit['player_card']['source_sha256']
    html = pr.render_player_card(pr.project_player_card(clarified, rules[KEY], edit))
    # The rendered card's summary carries the split ruling; the printed rulebook block (rules_text.json) is unchanged.
    # "Cultivation Check" is wrapped in a glossary <abbr>, so assert the unwrapped pieces of the split.
    _in_order(html, ('saving throw or attack roll', 'three times each fight',
                     'once between Full Cultivation Sessions'))
