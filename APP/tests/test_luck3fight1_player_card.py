"""Heaven's Luck's player-facing card and text state the owner's three-per-fight ruling (LUCK3FIGHT1 review fix).

Owner ruling 2026-10-22: Heaven's Luck is usable three times per fight. The table enforces that (see
tests/test_luck3fight1_heavens_luck_three.py); the player card and player text must say the same thing, not the old
"Once between Full Cultivation Sessions". The printed rules text is left as printed.
"""
import json
from pathlib import Path

from factory_authoring import player_rules as pr
from factory_authoring.owner_text_edits import player_wording

AUTH = Path(__file__).resolve().parents[1] / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'


def _edit():
    return json.loads((AUTH / 'owner_text_edits.json').read_text())['records'][KEY]


def test_player_card_use_limit_is_three_per_fight():
    card = _edit()['player_card']
    assert ['Use limit', 'Three times each fight'] in card['facts']
    assert 'Once between Full Cultivation Sessions' not in json.dumps(card, ensure_ascii=False)


def test_player_text_describes_three_uses_each_fight():
    text = _edit()['player_text']
    assert 'Three times during each fight' in text
    assert 'start of each fight' in text
    assert 'Once between Full Cultivation Sessions' not in text


def test_rendered_card_states_the_limit_and_is_bound_to_the_new_text():
    edit = _edit()
    rules = json.loads((AUTH / 'rules_text.json').read_text())
    # The same clarified text the batch build produces for this one record (no other record is touched).
    clarified = pr.format_card(player_wording(pr.display_prose(edit['player_text'], legacy_fields=True), edit))
    assert pr.card_sha(clarified) == edit['player_card']['source_sha256']
    html = pr.render_player_card(pr.project_player_card(clarified, rules[KEY], edit))
    # The card's use-limit line states the ruling. The printed rulebook block (rules_text.json) is owner-controlled
    # printed text and is not changed here, so only the card's own use-limit fact is asserted.
    assert 'Three times each fight' in html
