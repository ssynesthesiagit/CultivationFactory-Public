"""Clarity B08 review fixes: card terms need definitions; two facts stay short."""
import re
from html import escape

import pytest

from factory_authoring import player_rules
from tools.card_lint import catalogue

CARD_TERMS = ('Qi', 'Stamina', 'Momentum', 'Brood', 'Dread', 'Resonance',
              'Domain Armament', 'Blood-Moon Mark', 'Condemned', 'Golden Core',
              'Heavenly Tone', 'Execution Wound')
MOMENTUM = 'tianxia.subpath.body.returning_heaven_momentum_body.feature.gather_and_return'
COURT = 'tianxia.subpath.qi.cai_clan_empyreal_administrator.feature.court_of_duty'
WHITE_SUN = 'tianxia.subpath.qi.cai_clan_empyreal_administrator.feature.white_sun_judgment'


@pytest.mark.parametrize('term', CARD_TERMS)
def test_card_term_has_glossary_definition(term):
    assert term in player_rules.CARD_GLOSSARY


def test_momentum_card_defines_resource_on_every_occurrence():
    card = catalogue()[MOMENTUM]
    definition = escape(player_rules.CARD_GLOSSARY['Momentum'], quote=True)
    html = player_rules.render_player_card(card)
    assert f'<abbr tabindex="0" title="{definition}">Momentum</abbr>' in html
    assert 'Cost: 1 <abbr' in html


def test_every_visible_card_term_is_wrapped_with_its_definition():
    cards = catalogue()
    checked = 0
    for key, card in cards.items():
        if not card.get('reviewed'):
            continue
        visible = player_rules.card_default_text(card)
        html = player_rules.render_player_card(card)
        for term in CARD_TERMS:
            if re.search(r'\b' + re.escape(term) + r's?\b', visible):
                checked += 1
                definition = escape(player_rules.CARD_GLOSSARY[term], quote=True)
                assert f'title="{definition}"' in html, (key, term)
    assert checked


def test_range_fact_is_short_and_detail_stays_in_effect():
    card = catalogue()[COURT]
    assert ('Range', '30 feet') in card['facts']
    assert any("Empyreal Layer's 30 feet at activation" in item for item in card['groups']['Effect'])


def test_duration_fact_is_instantaneous_and_restriction_stays_in_effect():
    card = catalogue()[WHITE_SUN]
    assert ('Duration', 'Instantaneous') in card['facts']
    assert any("Duration: Idghkbayttglf; the oishry-sbdd vhlahpbmtmt dcou at the end of the nhcavicv ppysldyk's aalr turn." == item
               for item in card['groups']['Limits'])
