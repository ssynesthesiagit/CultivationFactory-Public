"""Sol CLARITY5 batch B13 review fixes (player_card batch on owner_text_edits).

Each guard fails when the reviewed card drifts from the printed rules:
facts (finding 1), whole-record clauses (2), hash binding (3), glossary (4),
why labels (5), lint and projection over the batch (6), and disclosure (7).
"""
import json
import re
from html import escape
from html import unescape as html_unescape
from pathlib import Path

import pytest

from factory_authoring import player_rules as pr
from tools.card_lint import lint_card

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / 'authority' / 'typed_mechanics'
KEYS = json.loads((ROOT / 'tests' / 'fixtures' / 'clarity5_b13_rules_card_keys.json').read_text())
TEXT = json.loads((ROOT / 'tests' / 'fixtures' / 'clarity5_b13_rules_clause_fixture.json').read_text())
WHY = 'CLARITY5 batch B13 player card'
ECONOMY = ('Bonus Action', 'Action', 'Reaction')


@pytest.fixture(scope='module')
def batch():
    rules = json.loads((AUTH / 'rules_text.json').read_text())
    recs = json.loads((AUTH / 'owner_text_edits.json').read_text())['records']
    clar = pr.build_player_text(rules, recs)['records']
    out = {}
    for key in KEYS:
        card = pr.project_player_card(clar[key], rules[key], recs[key])
        out[key] = (card, rules[key], clar[key], recs[key])
    return out


def test_batch_keys_are_reviewed_cards():
    recs = json.loads((AUTH / 'owner_text_edits.json').read_text())['records']
    assert len(KEYS) == 87 == len(set(KEYS))
    assert all('player_card' in recs[k] for k in KEYS)


# Finding 1: reviewed facts must agree with the printed Action/Range/Duration/Cost/Use limit.
def test_reviewed_facts_match_printed_metadata(batch):
    for key, (card, printed, _, edit) in batch.items():
        for label, value in card['facts']:
            if label == 'Action':
                assert value in ECONOMY or value.startswith(('Action or', 'Bonus Action or')), (key, value)
                continue
            if label == 'Ritual':
                amount = re.match(r'(\d+)-minute ritual$', value)
                assert amount and re.search(r'\*\*Ritual(?: Action)?:\*\* ' + amount.group(1) + ' minutes', printed), (key, value)
                continue
            for number in re.findall(r'\d+', value):
                assert re.search(r'(?<![\d.])' + number + r'(?![\d])', printed), (key, label, value)
            if label == 'Cost' and 'Resonance' in value:
                assert 'Resonance' in printed, (key, value)


# Finding 2: every printed non-zero number from metadata must remain visible on the card.
def test_whole_record_keeps_printed_numbers(batch):
    for key, (card, printed, _, _) in batch.items():
        shown = pr.card_default_text(card) + ' ' + ' '.join(sum(card['groups'].values(), []))
        for line in printed.splitlines():
            plain = line.replace('*', '').replace('`', '')
            if not re.match(r'^\s*(Action|Bonus Action|Reaction|Ritual|Cost|Range|Duration|Area|Targets?|Requirement|Required focus|Time|Ritual Time|Trigger|Concentration|Use limit)\b', plain):
                continue
            for number in re.findall(r'(?<![\w.])([1-9]\d*)(?![\d])', plain):
                assert re.search(r'(?<![\w.])' + number + r'(?![\d])', shown), (key, number, line[:120])


# Finding 3: hashes bind each reviewed card to the exact text it summarizes.
def test_hashes_bind_every_batch_card(batch):
    for key, (card, printed, clarified, edit) in batch.items():
        assert edit['player_card']['source_sha256'] == pr.card_sha(clarified), key
        assert edit['player_card']['rules_sha256'] == pr.card_sha(printed), key
        assert card['reviewed'] is True, key


# Finding 4: terms the batch uses must be defined on hover where they appear.
def test_glossary_defines_batch_terms(batch):
    for key, (card, _, _, _) in batch.items():
        html = pr.render_player_card(card)
        shown = pr.card_default_text(card)
        for term in ('Source CL', 'Trance Rhythm', 'Observed Tie'):
            if re.search(r'\b' + re.escape(term) + r'\b', shown):
                expect = '<abbr tabindex="0" title="' + escape(pr.CARD_GLOSSARY[term], quote=True) + '">' + term + '</abbr>'
                assert expect in html, (key, term)


def test_mandate_is_not_glossed_with_a_wrong_meaning():
    assert 'Mandate' not in pr.CARD_GLOSSARY


def test_observed_tie_gloss_matches_printed_object_and_location_scope():
    gloss = pr.CARD_GLOSSARY['Observed Tie']
    assert all(term in gloss for term in ('creatures', 'objects', 'Assets', 'Anchors', 'locations', 'active spiritual effects'))
    assert 'GM' not in gloss


def test_source_cl_gloss_explains_power_level_in_plain_language():
    gloss = pr.CARD_GLOSSARY['Source CL']
    assert 'power level' in gloss
    assert 'strength' in gloss and 'overcome another effect' in gloss
    assert 'Source CL of' not in gloss


# Finding 5: the why label must stay the owner-approved text, and the batch provenance must be explicit.
def test_why_labels_trace_to_batch():
    recs = json.loads((AUTH / 'owner_text_edits.json').read_text())['records']
    for key in KEYS:
        assert recs[key]['why'].startswith(tuple(TEXT['why_prefixes'])), (key, recs[key]['why'])
        assert recs[key]['player_card']['batch'].startswith(TEXT['batch_prefix']), key


# Public-export regression: the lint must not reach the owner-sample module
# (the owner-sample module is an excluded dependency group in the export).
def test_lint_closure_avoids_owner_sample_module():
    src = (ROOT / 'tools' / 'card_lint.py').read_text()
    # No dotted module literal: the export reads it as a dependency edge.
    assert 'clarity_check' not in src and 'card_view_lint' in src


# Finding 6: projection and lint run over every batch record (this is the CI guard).
def test_batch_projects_and_lints_clean(batch):
    for key, (card, _, _, _) in batch.items():
        assert lint_card(card) == [], (key, lint_card(card))


# Finding 7: factory-only implementation fields never reach the player disclosure.
def test_disclosure_has_no_factory_annotations(batch):
    markers = ('Split Review Decision', 'Recommended Factory Realization', 'procedures=', '_INTERNAL')
    for key, (card, printed, _, _) in batch.items():
        html = pr.render_player_card(card)
        assert not any(marker in html for marker in markers), key
        assert pr.player_safe_rules(printed) == printed or not any(
            marker in pr.player_safe_rules(printed) for marker in markers), key


# Sol review (MERGE AFTER FIXES): number checks alone let a card drop a
# restriction, trigger, target qualifier or outcome. Each printed sentence that
# carries one of these words must have its content words on the visible card;
# paraphrase is allowed, a dropped clause is not. Lead-ins ending in ':' only
# introduce a list whose items are checked on their own.
RESTRICTION = frozenset(
    'not no none never cannot nor neither without unless except only half once each every '
    'until instead before after during while if when must may all any'.split())
CLAUSE_STOP = frozenset(
    'the and for with that this from into onto your you are any can its their they them '
    'while when each once until than then also such who whom which what where there here been '
    'being have has had will would should could shall upon over under about after before during '
    'within without only not'.split())


def _stem(word):
    for suffix in ('ings', 'ing', 'ed', 'es', 's'):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _content_stems(text):
    words = re.findall(r'[a-z0-9]+', text.lower().replace('\u2019', "'"))
    return {_stem(w) for w in words if w.isdigit() or (len(w) >= 3 and w not in CLAUSE_STOP)}


def _printed_clauses(printed):
    text = pr.player_safe_rules(printed).replace('**', '').replace('`', '')
    clauses = []
    for line in text.splitlines():
        line = re.sub(r'^\s*(#+\s*|[-*\u2022]\s*)', '', line).strip()
        for part in re.split(r'(?<=[.;!?])\s+(?=[A-Z(\u201c"])', line):
            part = part.strip()
            if len(part.split()) >= 3:
                clauses.append(part)
    return clauses


def _visible_text(card):
    return card['title'] + ' ' + pr.card_default_text(card)


def _dropped_clauses(printed, card):
    visible = _content_stems(_visible_text(card))
    dropped = []
    for clause in _printed_clauses(printed):
        if clause.endswith(':'):
            continue
        if not set(re.findall(r'[a-z]+', clause.lower())) & RESTRICTION:
            continue
        need = _content_stems(clause)
        if need and len(need & visible) / len(need) < 0.5:
            dropped.append(clause)
    return dropped


def test_restricted_printed_clauses_are_visible_on_card(batch):
    gaps = [(key, clause[:160]) for key, (card, printed, _, _) in batch.items()
            for clause in _dropped_clauses(printed, card)]
    assert not gaps, gaps[:20]


def test_clause_check_flags_dropped_restriction_and_accepts_paraphrase():
    printed = TEXT['printed']
    base = {'title': 'Test Feature', 'facts': [], 'groups': {}}
    dropped = dict(base, summary=TEXT['dropped_summary'])
    paraphrased = dict(base, summary=TEXT['paraphrased_summary'])
    assert len(_dropped_clauses(printed, dropped)) == 2
    assert _dropped_clauses(printed, paraphrased) == []


# Sol review: the full printed Rules must be what the player's disclosure exposes.
def _plain(text):
    return ' '.join(text.replace('**', '').replace('`', '').split())


def test_rules_disclosure_exposes_every_printed_line(batch):
    for key, (card, printed, _, _) in batch.items():
        html = pr.render_player_card(card)
        pre = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.S)
        assert pre, key
        shown = _plain(html_unescape(re.sub(r'<[^>]+>', '', pre.group(1))))
        for line in pr.player_safe_rules(printed).splitlines():
            plain = _plain(line)
            if plain:
                assert plain in shown, (key, plain[:120])
