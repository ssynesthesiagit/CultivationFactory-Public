"""Public card previews and full-source retention checks; no repository history or owner fixtures.

Used by clarity_check's CLI, clarity5_sample's artifact CLI and their public tests.
"""
import json
from pathlib import Path

from factory_authoring.player_rules import card_default_text, project_player_card
from factory_authoring.verdant_evidence import SHELTER_EVIDENCE
from tools.card_view_lint import NUMBER, default_view_findings

DATA = Path(__file__).resolve().parents[1] / 'authority/typed_mechanics'
# These are display overviews. Rules remains the entire source, including every
# choice, scaling table and exception. The lead judges these before batch work.
SAMPLE = (
    'AIR_BASE_GATHER_CURRENT',
    'AIR_BASE_WIND_HAND_TRAINING',
    'AIR_BASE_WIND_LASH',
    'ALCHEMY_BASE_ALCHEMY_CHECK',
    'ALCHEMY_BASE_ALCHEMY_TRAINING',
    'ALCHEMY_BASE_FIELD_FORMULA',
    'ALCHEMY_BASE_PILL_FORGING',
    'ALCHEMY_BASE_REAGENT_STOCK',
    'ASH_BASE_ASHFALL',
    'ASH_BASE_CINDER_BRAND',
    'ASH_TAL_ASHEN_BURIAL',
    'ASH_TAL_CINDER_BURST',
    'ASH_TAL_CREMATION_PRISON',
    'ASH_TAL_DEEP_CINDER_BRAND',
    'ASH_TAL_RUINOUS_ASH',
    'ASH_TAL_SMOTHERING_CLOUD',
    'ASH_TAL_SOOT_IN_LUNGS',
    'ATHLETICS_BASE_ATHLETIC_TRAINING',
    'ATHLETICS_BASE_COORDINATED_MOVEMENT',
    'BEASTMASTERY_BASE_BEASTMASTERY_TRAINING',
    'BEASTMASTERY_BASE_RIDER_PACKAGE',
    'TAL_ALCHEMY_ANTIDOTE_PILL',
    'BEAUTY_BASE_ADORN_THE_MOMENT',
    'BEAUTY_BASE_CATCH_THE_EYE',
    'BEAUTY_BASE_TURN_THE_BLADE_ASIDE',
    'BLACKSMITH_BASE_BLACKSMITH_TRAINING',
    'BLACKSMITH_BASE_HAMMER_THE_MARK',
    'BLACKSMITH_BASE_QUENCH_THE_MARK',
    'BLACKSMITH_BASE_READ_THE_FLAW',
    'BLACKSMITH_BASE_SET_THE_WORKPIECE',
    'BLOOD_BASE_BLOODSENSE',
    'tianxia.path.body_refining.feature.stamina_guard',
    'TAL_DAEMONIC_CULTIVATION_DEMON_MARK',
    'TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH',
    'FLOWERS_BASE_FRAGRANCE',
    'FORMATIONS_BASE_PULSE_ARRAY',
    'insight.exorcist-s-calling',
    'tianxia.talent.spirit_companions.spirit_pact_technique',
    'tianxia.talent.thread.stitch_the_broken_technique',
    'insight.armor-is-not-a-cage',
    'POISON_BASE_INGRAIN_THE_TOXIN',
)


def shelter():
    """Use public evidence shared with combat, without engine dependencies."""
    raw = 'Verdant Response: Shelter\n' + SHELTER_EVIDENCE
    edit = {'player_card': json.loads((DATA / 'owner_text_edits.json').read_text())[
        'player_card_examples']['verdant_shelter']}
    return raw, project_player_card(raw, raw, edit)


def check_cards() -> tuple[list[str], int]:
    """Keep every printed fact in Rules and every reviewed mechanic visible.

    Canonical source byte equality retains all audit evidence. The rendered
    disclosure retains every rule verbatim, omitting only factory review fields;
    it must never expose those authoring annotations. This also checks
    default-view omissions and unsupported facts. It cannot prove
    summary scope; the lead must review the comparison. --all
    continues to check the clarified full text against its frozen baseline.
    """
    from tools.card_lint import catalogue
    from html.parser import HTMLParser
    from factory_authoring.player_rules import (
        CARD_AUTHORING_NOTE, card_default_text, player_safe_rules, render_player_card,
    )

    class PrintedRules(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_pre = False
            self.text = []

        def handle_starttag(self, tag, attrs):
            if tag == 'pre':
                self.in_pre = True

        def handle_endtag(self, tag):
            if tag == 'pre':
                self.in_pre = False

        def handle_data(self, data):
            if self.in_pre:
                self.text.append(data)
    rules = json.loads((DATA / 'rules_text.json').read_text())
    cards = catalogue()
    problems = []
    for key, card in cards.items():
        rendered = PrintedRules()
        rendered.feed(render_player_card(card))
        disclosed = ''.join(rendered.text)
        if card['rules'] != rules[key] or disclosed != player_safe_rules(rules[key]):
            problems.append(f'{key}: complete printed Rules changed')
        if CARD_AUTHORING_NOTE.search(disclosed):
            problems.append(f'{key}: internal authoring annotation in player Rules')
        if card['reviewed']:
            problems.extend(f'{key}: {issue}' for issue in default_view_findings(card))
            available = set(NUMBER.findall(card['rules'] + '\n' + card['clarified']))
            for number in set(NUMBER.findall(card_default_text(card))) - available:
                problems.append(f'{key}: overview invents numeric token {number}')
    return problems, len(cards)

