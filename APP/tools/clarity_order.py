"""Audit sentence moves against the pre-CLARITY3 display, retaining edited words.

This is an offline review aid, never a runtime rule. Sequence alignment matches
sentences after glossary/abbreviation normalization. Conservative restoration
keeps all matched sentences in printed order, including triggers and exceptions;
new summaries and explanations travel with their preceding matched sentence.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Keep labelled fields/options whole, including their qualifying clauses."""
    spans = []
    for line in re.finditer(r'[^\n]+', text):
        value = line[0].strip()
        start = line.start() + len(line[0]) - len(line[0].lstrip())
        if not value:
            continue
        if re.match(r'[^:.!?]{1,90}:|You can use this when\b', value):
            spans.append((start, start + len(value)))
        else:
            for part in re.finditer(r'\S.*?(?:(?<=[.!?])(?=\s+[A-Z“])|$)', value):
                spans.append((start + part.start(), start + part.end()))
    return spans


def sentences(text: str) -> list[str]:
    return [text[start:end] for start, end in sentence_spans(text)]


def words(text: str) -> list[str]:
    text = re.sub(r'\((?:Cultivation Level|a stage of cultivation|your Path resource)\)', '', text)
    text = re.sub(r'\bCultivation Level\s*(?=\d)', 'CL', text)
    text = re.sub(r'\bPB\b', 'Proficiency Bonus', text)
    text = re.sub(r'^(?:To learn this, you need|Requirements?):?\s*', 'Requires ', text)
    return re.findall(r"[\w+-]+", text.lower().replace('’', "'"))


def align(old: str, new: str) -> tuple[list[str], dict[int, int]]:
    """One-to-one sentence alignment, exact blocks first, then edited sentences.

    Fuzzy matches require >= 65% sequence similarity and at least four shared
    words. Short headings only match exactly. Ambiguous ties keep source order.
    """
    before, after = sentences(old), sentences(new)
    a, b = [words(s) for s in before], [words(s) for s in after]
    mapping = {}
    for block in SequenceMatcher(None, [tuple(s) for s in a], [tuple(s) for s in b], autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.b + offset] = block.a + offset
    used = set(mapping.values())
    candidates = []
    for j, right in enumerate(b):
        if j in mapping or not right:
            continue
        for i, left in enumerate(a):
            if i in used or not left:
                continue
            if left == right:
                score = 1.0
            elif len(set(left) & set(right)) >= 4:
                score = SequenceMatcher(None, left, right, autojunk=False).ratio()
            else:
                continue
            if score >= .65:
                candidates.append((-score, abs(i - j), i, j))
    for _, _, i, j in sorted(candidates):
        if i not in used and j not in mapping:
            mapping[j] = i
            used.add(i)
    return after, mapping


def restore_order(old: str, new: str) -> tuple[str, dict]:
    parts, mapping = align(old, new)
    source = sentences(old)
    def kind(text: str, index: int) -> str:
        if text.startswith('Cultivation points are') or text.startswith(('“', '"', '---')):
            return 'layout'
        if re.match(r'(?:You can use this when|Trigger:|Timing(?: Detail)?:)', text):
            return 'trigger'
        if re.match(r'(?:To learn this, you need|Requirements?:|Prerequisites?:|Use (?:an action|a bonus action|a reaction)|'
                    r'Use this as|Action(?: Type)?:|Range:|Target:|Area:|Save:|Duration:|Concentration:|'
                    r'Cost:|(?:Use )?Limits?:|Tags:|Type:|Time:|Saving Throw:|Parent Action:|Replaces Attacks:|'
                    r'This ability provides|(?:Action|Bonus Action|Reaction)$)', text):
            return 'field'
        return 'layout' if index == 0 else 'rule'
    inversions = [(j, k) for j in sorted(mapping) for k in sorted(mapping)
                  if j < k and mapping[j] > mapping[k]]
    if not inversions:
        return new, {}
    risky = [(j, k) for j, k in inversions
             if kind(source[mapping[j]], mapping[j]) == 'rule'
             and kind(source[mapping[k]], mapping[k]) in {'rule', 'trigger'}]
    audit = {'matched': len(mapping), 'inversions': len(inversions), 'rejected': len(risky),
             'moves': [[parts[j], parts[k]] for j, k in risky]}
    if not risky:
        return new, audit
    # Preserve every sentence exactly, including additions. A new title before
    # the first match stays first; an added explanation follows its anchor.
    groups = {-1: []}
    anchor = -1
    for j, part in enumerate(parts):
        if j in mapping:
            anchor = mapping[j]
        groups.setdefault(anchor, []).append(j)
    ordered = [j for i in sorted(groups) for j in groups[i]]
    spans = sentence_spans(new)
    restored = ''
    previous = None
    for j in ordered:
        separator = '' if previous is None else (
            new[spans[previous][1]:spans[j][0]] if j == previous + 1 else '\n\n')
        restored += separator + parts[j]
        previous = j
    return restored, audit
