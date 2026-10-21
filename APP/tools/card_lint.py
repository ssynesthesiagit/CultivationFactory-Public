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
    from tools.card_view_lint import default_view_findings
    issues.extend(default_view_findings(card))
    return issues


def catalogue(keys=None):
    """Project all cards, or only requested records for a focused review.

    A subset still validates its own exact replacements and card hashes; it does
    not depend on unrelated records (including fields filtered by public export).
    The default full-catalogue audit remains strict.
    """
    rules = json.loads((DATA / 'rules_text.json').read_text())
    edits = json.loads((DATA / 'owner_text_edits.json').read_text())['records']
    if keys is not None:
        rules = {key: rules[key] for key in keys}
        edits = {key: edits[key] for key in rules if key in edits}
    clarified = build_player_text(rules, edits)['records']
    return {key: project_player_card(text, rules[key], edits.get(key))
            for key, text in clarified.items()}


def stats(cards: dict) -> dict:
    findings = {key: lint_card(card) for key, card in cards.items()}
    lengths = sorted(len(card.get('default_text', card_default_text(card))) for card in cards.values())
    return {'records': len(cards), 'reviewed': sum(c['reviewed'] for c in cards.values()),
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
    args = parser.parse_args()
    cards = catalogue()
    if bool(args.first) != bool(args.last):
        parser.error('--first and --last must be supplied together')
    if args.first:
        if args.first not in cards or args.last not in cards or args.first > args.last:
            parser.error('unknown or reversed record range')
        cards = {k: c for k, c in cards.items() if args.first <= k <= args.last}
    if args.reviewed_only:
        cards = {k: c for k, c in cards.items() if c['reviewed']}
    result = stats(cards)
    print(json.dumps(result if args.json else {k: v for k, v in result.items()
                                               if k != 'flagged_records'}, indent=2))
    return int(bool(result['flagged_records']))


if __name__ == '__main__':
    raise SystemExit(main())
