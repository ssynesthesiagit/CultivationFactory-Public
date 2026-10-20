"""Phase-1 card surface: concise overviews with complete, accessible Rules."""
from html import escape
from html.parser import HTMLParser

import pytest

from factory_authoring.player_rules import (
    card_default_text, card_sha, project_player_card, render_player_card,
)
from tools.card_lint import catalogue, lint_card
from tools.card_audit import SAMPLE, shelter, check_cards


def reviewed(text, summary='Reduce damage by 1d10.', groups=None):
    return {'player_card': {'source_sha256': card_sha(text), 'rules_sha256': card_sha(text), 'summary': summary,
                            'groups': groups or {}}}


def test_sample_budget_and_full_source_retention():
    cards = catalogue()
    assert len(SAMPLE) == 41
    for key in SAMPLE:
        assert cards[key]['reviewed']
        assert lint_card(cards[key]) == [], (key, lint_card(cards[key]))
    problems, count = check_cards()
    assert count == len(cards) and problems == []


def test_facts_do_not_hoist_nested_cost_or_action():
    text = ('Test\nAction: Reaction\nRange: 30 feet\nCost: 0 cultivation points\n'
            'Reduce damage by 1d10.\nOptional burst\nAction: Action\nCost: 2 Qi\nChoose any target.')
    card = project_player_card(text, text)
    assert card['facts'] == [('Action', 'Reaction'), ('Range', '30 feet')]
    assert 'Cost: 2 Qi' in card_default_text(card)
    assert 'Cost: 0' not in card_default_text(card)
    assert card['rules'] == text


def test_overview_stales_when_clarified_rule_changes():
    text = 'Guard\nReduce damage by 1d10.'
    edit = reviewed(text)
    with pytest.raises(ValueError, match='Stale'):
        project_player_card(text.replace('1d10', '1d6'), text, edit)
    with pytest.raises(ValueError, match='Stale'):
        project_player_card(text, text.replace('1d10', '1d6'), edit)


def test_malformed_groups_fail_before_rendering_character_bullets():
    edit = reviewed('Test')
    edit['player_card']['groups'] = {'Effect': 'not a list'}
    with pytest.raises(ValueError, match='lists'):
        project_player_card('Test', 'Test', edit)


@pytest.mark.parametrize('summary,groups,expected', [
    ('', {}, 'missing-summary'),
    ('You can reduce damage.', {}, 'summary-not-verb-first'),
    ('Reduce damage. Reduce damage.', {}, 'duplicate'),
    ('Reduce damage.', {'Effect': ['Reduce damage.']}, 'duplicate'),
    ('Reduce damage.', {'Effect': ['This button picks: Guard.']}, 'filler'),
    ('Reduce damage.', {'Effect': ['Choosing this option takes no action.']}, 'filler'),
    ('Reduce damage.', {'Effect': ['x' * 330]}, 'over-budget'),
])
def test_lint_rejects_bad_default_views(summary, groups, expected):
    card = project_player_card('Test', 'Test', reviewed('Test', summary, groups))
    assert expected in lint_card(card, budget=320)


def test_over_budget_text_is_flagged_and_retained_without_truncation():
    choices = ['Option ' + str(n) + ': ' + 'x' * 80 for n in range(10)]
    text = 'Test\nChoose a target.\n' + '\n'.join(choices)
    card = project_player_card(text, text)
    assert 'over-budget' in lint_card(card, budget=320)
    for choice in choices:
        assert choice in card_default_text(card)
        assert choice in card['rules']


class ParsedCard(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_rules = False
        self.rules = []
        self.details = []
        self.visible = []

    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            self.details.append(dict(attrs))
            self.in_rules = True

    def handle_endtag(self, tag):
        if tag == 'details':
            self.in_rules = False

    def handle_data(self, data):
        (self.rules if self.in_rules else self.visible).append(data)


def test_html_escapes_rules_and_uses_collapsed_disclosure_and_glossary():
    raw = '<script>alert("x")</script>\nChoose one: A or B; only an ally within 30 feet.'
    text = 'Guard\nAction: Reaction\nCost: 2 cultivation points\nReduce damage by 1d10.'
    edit = reviewed(text, groups={'Choices': ['Choose one: A or B; only an ally within 30 feet.']})
    edit['player_card']['rules_sha256'] = card_sha(raw)
    card = project_player_card(text, raw, edit)
    html = render_player_card(card)
    assert '<script>' not in html
    assert '<abbr tabindex="0" title=' in html
    parsed = ParsedCard()
    parsed.feed(html)
    assert len(parsed.details) == 1 and 'open' not in parsed.details[0]
    assert raw in ''.join(parsed.rules)
    assert 'Choose one: A or B; only an ally within 30 feet.' in ''.join(parsed.visible)
    assert ''.join(parsed.visible).count('Reduce damage by 1d10.') == 1
    assert '2 CP' in ''.join(parsed.visible)


def test_all_card_glossary_terms_are_explained_in_rendered_cards():
    from factory_authoring.player_rules import CARD_GLOSSARY
    card = project_player_card('Test', 'Test', reviewed('Test', ' '.join(CARD_GLOSSARY)))
    html = render_player_card(card)
    for term, definition in CARD_GLOSSARY.items():
        # The renderer writes the title through html.escape(quote=True), so a
        # definition holding an apostrophe (CP: "your Path's resource") is
        # stored as &#x27;. Compare the escaped form: this still demands the
        # full definition of every term, and would still fail if the renderer
        # dropped, truncated or mistyped one.
        assert (f'<abbr tabindex="0" title="{escape(definition, quote=True)}">'
                f'{escape(term)}</abbr>') in html


def test_shelter_example_keeps_all_choices_in_default_view_and_rules():
    raw, card = shelter()
    assert lint_card(card) == []
    for choice in ('Half Cover', 'Temporary HP', 'Lightly Obscured'):
        assert choice in raw and choice in card_default_text(card)
    assert card['rules'] == raw


@pytest.mark.parametrize('source,visible', [
    ('Move 15 feet.', 'Move 10 feet.'),
    ('Cost: 0 CP\nAt 0 HP, gain a benefit.', 'Gain a benefit.'),
    ('Deal 2d6 damage.', 'Deal 1d6 damage.'),
    ('Roll d20.', 'Roll 20.'),
    ('Range: 30 feet', 'Choose a target.'),
    ('Duration: 1 minute', 'Lasts 1 round.'),
    ('Cost: Up to your Proficiency Bonus in Stamina', 'Spend Stamina.'),
    ('Target: One willing creature', 'Choose one creature.'),
    ('Until the start of its next turn.', 'Until the start of your next turn.'),
    ('The first hostile Tiny unattended object moves 5 feet.', 'Move an object 5 feet.'),
    ('Become Poisoned.', 'Become slowed.'),
    ('Choose one:\nLift: Move 5 feet.\nPress: Slow a creature.', 'Lift: Move 5 feet.'),
    ('Choose one:\nLift: Move a willing ally.\nPress: Slow a foe.', 'Choose Lift or Press.'),
    ('Choose one:\nLift: Move 5 feet.\nPress: Slow 10 feet.', 'Lift: Move 10 feet.\nPress: Slow 5 feet.'),
    ('Choose one:\nLift: Move the first willing creature.', 'Lift: Move a willing creature.'),
    ('Choose one:\nCarry: Move a Tiny unattended object weighing no more than 1 pound.',
     'Carry: Move a Tiny unattended object weighing 1 pound.'),
    ('Choose one:\nCut: The target cannot take Reactions until the start of your next turn.',
     'Cut: The target can take Reactions until the start of your next turn.'),
    ('Choose one:\nBitter Breath. Hinder a save.\nNumb Channels. Slow it.', 'Choose Bitter Breath.'),
    ('| CL | Damage |\n| 5-10 | 2d6 |\n| 11-16 | 3d6 |',
     'CL 5-10: 3d6; CL 11-16: 2d6.'),
])
def test_lint_rejects_details_hidden_only_in_rules(source, visible):
    text = 'Test\n' + source
    edit = reviewed(text, 'Choose an effect.', {'Effect': [visible]})
    # Hide the metadata too: inherited fact rows would otherwise correctly
    # keep Range, Duration and Cost visible despite the incomplete prose.
    edit['player_card']['facts'] = []
    card = project_player_card(text, text, edit)
    assert any(issue.startswith('incomplete-') for issue in lint_card(card))


def test_complete_cards_can_exceed_old_length_target_without_dropping_effects():
    card = catalogue()['AIR_BASE_GATHER_CURRENT']
    assert len(card_default_text(card)) > 320
    assert not lint_card(card)
    assert '15-foot cube at Foundation Realm' in card_default_text(card)
    assert '20-foot cube at Core Formation' in card_default_text(card)
    for name in ('Lift', 'Press', 'Scatter', 'Carry', 'Turn'):
        assert any(line.startswith(name + ':') for line in card['groups']['Choices'])


def test_ingrain_default_view_has_every_effect_payment_save_and_treatment():
    card = catalogue()['POISON_BASE_INGRAIN_THE_TOXIN']
    shown = card_default_text(card)
    assert not lint_card(card)
    assert 'Cost: 2 CP' in shown and 'Spend 2 of those marks' in shown
    for name in ('Bitter Breath', 'Numb Channels', 'Sour Blood', 'Clouded Senses', 'Heavy Pulse'):
        assert any(line.startswith(name + ':') for line in card['groups']['Choices'])
    assert 'Success: the marks are still spent' in shown
    assert 'treatment DC equals your Cultivation Save DC' in shown
    assert 'Dash on its next turn' in shown and '5 feet' in shown
    assert 'Until the target finishes a long rest or receives treatment' in shown


def test_reviewed_facts_are_validated_and_do_not_invent_parent_metadata():
    text = 'Test\nChoose an effect.\nOptional:\nCost: 2 Qi'
    edit = reviewed(text, 'Choose an effect.')
    edit['player_card']['facts'] = [['Action', 'Reaction']]
    assert project_player_card(text, text, edit)['facts'] == [('Action', 'Reaction')]
    edit['player_card']['facts'] = [['Internal', 'invalid']]
    with pytest.raises(ValueError, match='label/value'):
        project_player_card(text, text, edit)


def test_reviewed_inline_choices_are_bound_to_source_and_default_view():
    text = 'Test\nChoose Rider or Tamer.'
    edit = reviewed(text, 'Choose Rider.')
    edit['player_card']['choice_names'] = ['Rider', 'Tamer']
    card = project_player_card(text, text, edit)
    assert 'incomplete-choice: Tamer' in lint_card(card)
    edit['player_card']['choice_names'] = ['Archer']
    assert 'unsupported-choice: Archer' in lint_card(project_player_card(text, text, edit))


@pytest.mark.parametrize('source,visible', [
    ('Become Poisoned.', 'Become Poisoned and Frightened.'),
    ('Until the start of its next turn.', 'Until the start of its next turn. Until the end of your next turn.'),
    ('Move 5 feet.', 'Move 5 feet for 5 minutes.'),
])
def test_lint_rejects_invented_conditions_durations_and_units(source, visible):
    text = 'Test\n' + source
    card = project_player_card(text, text, reviewed(text, 'Choose an effect.', {'Effect': [visible]}))
    assert any(issue.startswith('unsupported-') for issue in lint_card(card))


def test_phase_one_overviews_preserve_all_existing_full_text_and_mechanics():
    """Cards preserve source bytes and every non-card field, without private Git history.

    SUMMONAI1 intentionally supersedes the four printed Dodge defaults in the
    original CLARITY5 baseline (Corpse Servant stat block, Rouse Lesser Dead,
    Grave Formation and Bone Guard). Pin that approved projection, not the old
    behavior. The original rules_text byte pin is unchanged.
    """
    import hashlib
    import json
    from tools.card_audit import DATA

    expected = {
        'rules_text.json': 'a78d75c6b9f5396ea576fa91ce2495fc37a884932e4ffbd231e9f98d5b2b13b0',
        'player_text.json': '282ee237368a82d95c7c60679c36ef698a76ee3ce12b239dbb7eff67945412e6',
    }
    for name, digest in expected.items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name
    current = json.loads((DATA / 'owner_text_edits.json').read_text())
    without_cards = {key: {field: value for field, value in row.items() if field != 'player_card'}
                     for key, row in current['records'].items()}
    encoded = json.dumps(without_cards, ensure_ascii=False, sort_keys=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == 'c53afb0994c19d60b2c95175dfd2072722d01b38af5e5b8fc18e0d674f78c430'


def test_browser_preview_optin(tmp_path):
    """Lead runs outside sandbox with CLARITY5_BROWSER=1; never auto-launch."""
    import os
    if os.environ.get('CLARITY5_BROWSER') != '1':
        pytest.skip('Lead must run browser review outside the sandbox')
    from playwright.sync_api import sync_playwright
    path = tmp_path / 'card.html'
    card = catalogue()[SAMPLE[0]]
    path.write_text(render_player_card(card))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        page.goto(path.as_uri())
        assert not page.locator('details').evaluate('(e) => e.open')
        page.locator('summary').click()
        assert page.locator('details').evaluate('(e) => e.open')
        assert page.locator('pre').text_content() == card['rules']
        browser.close()
