"""Sol CLARITY5F1R findings: safe Rules, shared evidence and attached levels."""
from html import escape
from pathlib import Path

import pytest

from factory_authoring import player_rules
from factory_authoring.verdant_evidence import SHELTER_EVIDENCE
from tests.test_clarity5_cards import ParsedCard
from tools.card_lint import catalogue
from tools.card_audit import shelter, check_cards


@pytest.mark.parametrize('metadata', [
    'Range: 30 feet', 'Duration: 1 minute',
    'Cost: Up to your Proficiency Bonus in Stamina',
])
def test_visible_fact_rows_satisfy_completeness(metadata):
    from tests.test_clarity5_cards import reviewed
    from tools.card_lint import lint_card

    text = 'Test\n' + metadata
    card = player_rules.project_player_card(text, text, reviewed(text, 'Choose an effect.'))
    assert not lint_card(card)
    assert card['facts']


def test_read_the_flaw_discloses_all_rules_without_factory_annotations():
    card = catalogue()['BLACKSMITH_BASE_READ_THE_FLAW']
    # The exact source remains available to hash/retention audits.
    assert 'single_combat_action_plus_procedure_variant' in card['rules']
    assert 'procedures=ONE_MINUTE_EXAMINATION' in card['rules']
    html = player_rules.render_player_card(card)
    assert 'single_combat_action_plus_procedure_variant' not in html
    assert 'procedures=ONE_MINUTE_EXAMINATION' not in html
    parsed = ParsedCard()
    parsed.feed(html)
    expected = '\n'.join(line for line in card['rules'].splitlines()
                         if not line.startswith(('Split Review Decision:',
                                                 'Recommended Factory Realization:')))
    assert ''.join(parsed.rules) == 'Rules' + expected
    for fact in ('learn two', 'whichever is higher', '1 minute', '1 Forge Mark',
                 'at least 10 minutes', 'whether the object is resisting your work'):
        assert fact in ''.join(parsed.rules)


@pytest.mark.parametrize('printed,expected', [
    ('Guard\nSplit Review Decision: internal_code\nReduce damage by 1d10.',
     'Guard\nReduce damage by 1d10.'),
    ('Guard\nRecommended Factory Realization: procedures=INTERNAL', 'Guard\n'),
    ('Guard\nCost: 2 CP\nChoose one: A or B.\nUntil the start of its next turn.',
     'Guard\nCost: 2 CP\nChoose one: A or B.\nUntil the start of its next turn.'),
    ('A sentence mentioning Recommended Factory Realization: stays a sentence.',
     'A sentence mentioning Recommended Factory Realization: stays a sentence.'),
])
def test_only_whole_authoring_fields_are_removed(printed, expected):
    assert player_rules.player_safe_rules(printed) == expected


def test_card_audit_rejects_raw_authoring_annotations_in_rules(monkeypatch):
    render = player_rules.render_player_card

    def leaking_renderer(card):
        if card['title'] == 'Read the Flaw':
            return '<pre>' + escape(card['rules']) + '</pre>'
        return render(card)

    monkeypatch.setattr(player_rules, 'render_player_card', leaking_renderer)
    problems, _ = check_cards()
    assert ('BLACKSMITH_BASE_READ_THE_FLAW: internal authoring annotation '
            'in player Rules') in problems


def test_shelter_preview_does_not_read_private_plugin_source(monkeypatch):
    read_text = Path.read_text

    def public_data_only(path, *args, **kwargs):
        assert path.name != 'verdant_chassis.py', 'preview must use public evidence'
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', public_data_only)
    raw, card = shelter()
    assert raw == 'Verdant Response: Shelter\n' + SHELTER_EVIDENCE
    assert card['rules'] == raw


def test_compiled_shelter_and_preview_share_public_evidence():
    from combat.ext.verdant_chassis import SOW, verdant_buttons

    actions = verdant_buttons({'owned_ids': [SOW], 'short': 'clarity',
                              'actor_id': 'gardener', 'numbers': {'pb': 2}})
    action = next(a for a in actions if a.display_name == 'Verdant Response: Shelter')
    assert action.parameters['typed']['effects'][0]['evidence'] == SHELTER_EVIDENCE
    assert shelter()[0].endswith(SHELTER_EVIDENCE)


@pytest.mark.parametrize('key,levels', [
    ('tianxia.path.body_refining.feature.stamina_guard', ('CL2',)),
    ('insight.exorcist-s-calling', ('CL4+', 'CL13')),
])
def test_actual_attached_levels_have_focusable_glossary_definitions(key, levels):
    html = player_rules.render_player_card(catalogue()[key])
    for level in levels:
        defined = ('<abbr tabindex="0" title="Cultivation Level: your level in cultivation.">'
                   'CL</abbr>' + level[2:])
        # Every occurrence, including the collapsed Rules, must be defined.
        assert html.count(defined) == (
            player_rules.card_default_text(catalogue()[key]).count(level)
            + catalogue()[key]['rules'].count(level))
        assert defined in html
    parsed = ParsedCard()
    parsed.feed(html)
    for level in levels:
        assert level in ''.join(parsed.visible + parsed.rules)
