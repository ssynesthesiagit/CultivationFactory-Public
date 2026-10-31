"""The player card keeps Heaven's Luck's fight and session limits distinct."""
import json
from pathlib import Path

from factory_authoring import player_rules as pr
from factory_authoring.owner_text_edits import player_wording

AUTH = Path(__file__).resolve().parents[1] / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'


def _edit():
    return json.loads((AUTH / 'owner_text_edits.json').read_text())['records'][KEY]


def _limit_lines():
    lines = _edit()['player_text'].splitlines()
    fight_line = next(line for line in lines if line.startswith('Three times during each fight,'))
    session_line = next(line for line in lines if line.startswith('Once between Full Cultivation Sessions,'))
    return fight_line, session_line


def test_player_card_use_limit_splits_fight_rolls_from_cultivation_checks():
    card = _edit()['player_card']
    fact = next(value for label, value in card['facts'] if label == 'Use limit')
    fact_parts = ('Saves and attacks:', 'three times each fight', 'Cultivation Checks:',
                  'once between Full Cultivation Sessions')
    assert all(part in fact for part in fact_parts)
    assert [fact.index(part) for part in fact_parts] == sorted(fact.index(part) for part in fact_parts)
    summary_parts = ('saving throw or attack roll', 'three times each fight', 'Cultivation Check',
                     'once between Full Cultivation Sessions')
    assert all(part in card['summary'] for part in summary_parts)
    assert [card['summary'].index(part) for part in summary_parts] == sorted(
        card['summary'].index(part) for part in summary_parts)


def test_player_text_describes_three_fight_uses_and_a_session_limit_for_cultivation_checks():
    text = _edit()['player_text']
    fight_line, session_line = _limit_lines()
    assert fight_line.startswith('Three times during each fight,') and 'saving throw or attack roll' in fight_line
    assert 'All three uses return at the start of each fight.' in text
    assert session_line.startswith('Once between Full Cultivation Sessions,') and 'Cultivation Check' in session_line
    # The old single sentence that put a Cultivation Check under the three-per-fight limit must be gone.
    assert 'Cultivation Check, saving throw, or attack roll' not in text


def test_built_player_text_matches_the_owner_edit():
    built = json.loads((AUTH / 'player_text.json').read_text())['records'][KEY]
    fight_line, session_line = _limit_lines()
    assert fight_line in built and session_line in built
    assert 'Cultivation Check, saving throw, or attack roll' not in built


def test_rendered_card_states_the_split_limit_and_is_bound_to_the_new_text():
    edit = _edit()
    rules = json.loads((AUTH / 'rules_text.json').read_text())
    # The same clarified text the batch build produces for this one record (no other record is touched).
    clarified = pr.format_card(player_wording(pr.display_prose(edit['player_text'], legacy_fields=True), edit))
    assert pr.card_sha(clarified) == edit['player_card']['source_sha256']
    html = pr.render_player_card(pr.project_player_card(clarified, rules[KEY], edit))
    # The rendered card's summary carries the split ruling; the printed rulebook block (rules_text.json) is unchanged.
    # "Cultivation Check" is wrapped in a glossary <abbr>, so assert the unwrapped pieces of the split.
    rendered_parts = ('saving throw or attack roll', 'three times each fight',
                      'once between Full Cultivation Sessions')
    assert all(part in html for part in rendered_parts)
    assert [html.index(part) for part in rendered_parts] == sorted(html.index(part) for part in rendered_parts)
