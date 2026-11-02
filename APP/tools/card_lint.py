#!/usr/bin/env python3
"""Audit CLARITY5 default views without clipping text or hiding legal choices.

Run from APP: python tools/card_lint.py [--reviewed-only] [--json].
Length excludes title and collapsed Rules; counts group labels, the summary,
fact row and bullets as the player reads them. Completeness takes priority over
an optional editorial budget. A full-catalogue audit is expected
to flag legacy cards until phase 2. Exit nonzero when the selected set has lint.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from factory_authoring.player_rules import (build_player_text, card_default_text,
                                           display_prose, format_card,
                                           project_player_card)

DATA = APP / 'authority/typed_mechanics'
# Length is measured, not a reason to hide a rule. Callers can request a
# separate editorial budget; completeness always applies.
BUDGET = None
FILLER = re.compile(r'This button picks:|Choosing this option takes no action|'
                    r'Cost:\s*(?:None\b|0\b)|Cultivation points are', re.I)
VERB = re.compile(r'^(?:Reduce|Deal|Gain|Choose|Make|Create|Move|Spend|Use|Grant|'
                  r'Restore|Regain|Protect|Mark|Learn|Train|Craft|Release|Apply|'
                  r'Impose|End|Become|Sense|Strike|Add|Roll|Prepare|Pull|Push|'
                  r'Change|Turn|Swap|Improve|Repeat|Resist|Recover|Prevent|'
                  r'Increase|Ignite|Heal|Shape|Summon|Inflict|Block|Store|'
                  r'Control|Command|Enter|Build|Form|Bind|Exhale|Restrain|Damage|'
                  r'Reroll|Trap|Blast|Imprison|Choke|Study|Resolve|'
                  r'Refine|Captivate|Place|Activate|Interrupt|Assign)\b')


def lint_card(card: dict, budget: int | None = BUDGET) -> list[str]:
    text = card.get('default_text', card_default_text(card))
    issues = []
    if not card['summary'].strip():
        issues.append('missing-summary')
    elif not VERB.match(card['summary']):
        issues.append('summary-not-verb-first')
    if '\n' in card['summary'] or len(card['summary']) > 180:
        issues.append('summary-too-long')
    if budget is not None and len(text) > budget:
        issues.append('over-budget')
    if FILLER.search(text):
        issues.append('filler')
    sentences = [re.sub(r'\W+', ' ', s).strip().casefold()
                 for s in re.split(r'(?<=[.!?])\s+|\n+', text)]
    if any(n > 1 for s, n in Counter(sentences).items() if s):
        issues.append('duplicate')
    # Repeated clauses across summary, facts and bullets are also duplication,
    # even when punctuation differs. Short repeated terms alone are not facts.
    units = (text.splitlines() if 'default_text' in card else
             [card['summary']] + [v for _, v in card['facts']] + [
                 item for items in card['groups'].values() for item in items])
    units = [re.sub(r'\W+', ' ', s).strip().casefold() for s in units]
    if any(len(a.split()) >= 4 and a in b for i, a in enumerate(units)
           for j, b in enumerate(units) if i != j):
        if 'duplicate' not in issues:
            issues.append('duplicate')
    if 'rules' in card:
        from tools.card_view_lint import default_view_findings
        issues.extend(default_view_findings(card))
    elif card.get('_example_family'):
        issues.append('missing-rules')
    return issues


def catalogue():
    rules = json.loads((DATA / 'rules_text.json').read_text())
    edits = json.loads((DATA / 'owner_text_edits.json').read_text())['records']
    clarified = build_player_text(rules, edits)['records']
    return {key: project_player_card(text, rules[key], edits.get(key))
            for key, text in clarified.items()}


def pro_input_catalogue(input_dir: Path, edits_path: Path | None = None) -> dict:
    """Project stored cards against every exported family source row."""
    edits_path = edits_path or DATA / 'owner_text_edits.json'
    edits = json.loads(edits_path.read_text())['records']
    rules = json.loads((DATA / 'rules_text.json').read_text())
    clarified_records = build_player_text(rules, edits)['records']
    cards = {}
    for path in sorted(input_dir.glob('*.json')):
        for row in json.loads(path.read_text()):
            edit = edits.get(row['id'])
            if edit and edit.get('player_card'):
                printed = rules.get(row['id'], row['rules_text'])
                clarified = clarified_records.get(
                    row['id'], format_card(display_prose(row['rules_text'])))
                cards[row['id']] = project_player_card(clarified, printed, edit)
    return cards


def example_catalogue(examples_path: Path) -> dict:
    """Read hand-checked cards from the phase-2 examples packet."""
    data = json.loads(examples_path.read_text())
    rows = data.get('examples', []) if isinstance(data, dict) else data
    cards = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('player_card'), dict):
            continue
        card = dict(row['player_card'])
        if row.get('player_text'):
            card.setdefault('rules', row['player_text'])
            card.setdefault('clarified', row['player_text'])
        card.setdefault('facts', [])
        card.setdefault('choice_names', [])
        card['_example_family'] = row.get('example_family', 'unclassified')
        cards[row.get('record_id', row.get('id', f'example-{index}'))] = card
    return cards


def stats(cards: dict) -> dict:
    findings = {key: lint_card(card) for key, card in cards.items()}
    lengths = sorted(len(card.get('default_text', card_default_text(card))) for card in cards.values())
    return {'records': len(cards), 'reviewed': sum(c.get('reviewed', True) for c in cards.values()),
            'clean': sum(not v for v in findings.values()),
            'findings': dict(sorted(Counter(i for v in findings.values() for i in v).items())),
            'default_chars': {'median': lengths[len(lengths)//2] if lengths else 0,
                              'max': max(lengths, default=0)},
            'flagged_records': {k: v for k, v in findings.items() if v}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-only', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--first', help='Inclusive first record ID in a batch range')
    parser.add_argument('--last', help='Inclusive last record ID in a batch range')
    parser.add_argument('--pro-input-dir', type=Path, help='Lint reviewed cards against every Astra Pro source family')
    parser.add_argument('--examples', type=Path, help='Lint hand-checked cards in an examples JSON file')
    parser.add_argument('--example-family', help='Select one example_family when linting EXAMPLES.json')
    parser.add_argument('--new-examples-only', action='store_true', help='Skip the retained 41 approved phase-1 examples')
    args = parser.parse_args()
    if sum(bool(value) for value in (args.pro_input_dir, args.examples)) > 1:
        parser.error('use only one of --pro-input-dir and --examples')
    cards = example_catalogue(args.examples) if args.examples else pro_input_catalogue(args.pro_input_dir) if args.pro_input_dir else catalogue()
    if args.example_family:
        if not args.examples:
            parser.error('--example-family requires --examples')
        cards = {key: value for key, value in cards.items() if value.get('_example_family') == args.example_family}
    if args.new_examples_only:
        if not args.examples:
            parser.error('--new-examples-only requires --examples')
        cards = {key: value for key, value in cards.items() if value.get('_example_family') != 'approved_clarity5'}
    if bool(args.first) != bool(args.last):
        parser.error('--first and --last must be supplied together')
    if args.first:
        if args.first not in cards or args.last not in cards or args.first > args.last:
            parser.error('unknown or reversed record range')
        cards = {k: c for k, c in cards.items() if args.first <= k <= args.last}
    if args.reviewed_only:
        cards = {k: c for k, c in cards.items() if c.get('reviewed', True)}
    result = stats(cards)
    print(json.dumps(result if args.json else {k: v for k, v in result.items()
                                               if k != 'flagged_records'}, indent=2))
    return int(bool(result['flagged_records']))


if __name__ == '__main__':
    raise SystemExit(main())
