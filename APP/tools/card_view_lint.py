"""Public, lexical card checks shared by card_lint and clarity_check.

Nothing here reads owner files: callers pass cards in. Kept separate so the
public test export does not follow card_lint into clarity_check's sample data.
"""
from __future__ import annotations

from collections import Counter
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

NUMBER = re.compile(r'(?:(?<![\w])[+-])?(?:\d+d\d+|d\d+|\d+)(?:\.\d+)?', re.I)
QUANTITY = re.compile(
    r'(?<!\w)(\d+(?:-\d+)?)\s*[- ]\s*'
    r'(feet|foot|hours?|minutes?|rounds?|turns?|pounds?|gp)\b', re.I)
BOUNDARY = re.compile(
    r'\buntil (?:the )?(?:start|end) of (?:the )?'
    r'(?:(?:target[’\']s|creature[’\']s|its|your|current) )?(?:next )?turn\b', re.I)
SAVE = re.compile(r'\b(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)'
                  r' (?:saving throw|save)\b', re.I)
DC = re.compile(r'\b(?:Cultivation Save DC|(?:Strength|Dexterity|Constitution|'
                r'Intelligence|Wisdom|Charisma) (?:save )?DC|DC\s+\d+)\b', re.I)
RATE = re.compile(r'\b(?:once|twice) (?:per (?:turn|round|scene)|'
                  r'between Full Cultivation Sessions)\b', re.I)
RESOURCE = re.compile(
    r'(?<!\w)[+-]?\d+ (?:cultivation points?|Qi|Stamina|Resonance|'
    r'Reagent Stock|Empty Bowl Marks?|Thunder Charges?|Black Vein Strain|Pill Impurity)\b', re.I)
CONDITIONS = (
    'Blinded', 'Charmed', 'Deafened', 'Frightened', 'Grappled', 'Incapacitated',
    'Invisible', 'Paralyzed', 'Petrified', 'Poisoned', 'Prone', 'Restrained',
    'Stunned', 'Unconscious', 'Burn', 'Burning', 'Smothered', 'Ashen Brand',
    'Dose Mark', 'Faultline Mark', 'Conductive', 'Difficult Terrain',
    'Heavily Obscured', 'Half Cover', 'Three-Quarters Cover', 'Total Cover',
    'Lightly Obscured', 'Bloodied', 'Captivated', 'Beauty Mark', 'Forge Mark',
    'Growth Mark', 'Devoured Essence', 'Remnant', 'Toxin Burden',
)
INTERNAL = re.compile(
    r'\b(?:[A-Z]+_(?:BASE|TAL)_[A-Z0-9_]+|TAL_[A-Z0-9_]+|'
    r'(?:action|condition|resource|passive):[\w.#:-]+|'
    r'tianxia\.[\w.-]+|[a-z]+_[a-z_]+)\b|'
    r'(?:APP|combat|authority|tools|tests)/[\w/.-]+')
BANNED = re.compile(
    r'\b(?:apply manually|a testament to|tapestry|palpable tension|'
    r'shivers down your spine|eyes gleaming|'
    r'let out a breath they didn[’\']t know they were holding)\b|'
    r'\b(?:No|Zero|Without)\s+[^.\n]+\.\s*(?:No|Zero|Without|Just)\s|'
    r'\bNot\s+[^.\n]+\.\s*Not\s+[^.\n]+\.\s*But\s|'
    r'\bIt[’\']s not\s+[^.\n]+,\s*it[’\']s\s', re.I)


def normalized(text: str) -> str:
    """Allow layout, typography and expanded abbreviations, never quantities."""
    text = text.replace('’', "'").replace('–', '-').replace('—', '-')
    text = re.sub(r'\bPB\b', 'Proficiency Bonus', text)
    text = re.sub(r'\bcultivation point\b', 'cultivation points', text, flags=re.I)
    text = re.sub(r'\bCL\s+(?=\d)', 'CL', text)
    text = re.sub(r'\s*\(Cultivation Level\)|\s*\(a stage of cultivation\)|'
                  r'\s*\(your Path resource\)', '', text, flags=re.I)
    return ' '.join(text.lower().split()).rstrip('.;')


def protected(text: str, choices: list[str] = ()) -> dict[str, Counter]:
    """Extract independently checked lexical facts from either wording."""
    quantities = Counter()
    for amount, unit in QUANTITY.findall(text):
        unit = {'foot': 'feet', 'hour': 'hours', 'minute': 'minutes',
                'round': 'rounds', 'turn': 'turns', 'pound': 'pounds'}.get(unit.lower(), unit.lower())
        quantities[(amount, unit)] += 1
    costs = Counter(re.sub(r'\bcultivation point\b', 'cultivation points', normalized(m[0]))
                    for m in RESOURCE.finditer(text))
    tables = Counter(normalized(line) for line in text.splitlines()
                     if line.lstrip().startswith('|') and NUMBER.search(line))
    headers = Counter()
    for line in text.replace('\\n', '\n').splitlines():
        match = re.match(r'\s*(Range|Target|Area|Duration|Cost|(?:Use )?Limit):\s*(.*)', line, re.I)
        if match:
            label, value = match.groups()
            label = re.sub(r'^use ', '', label, flags=re.I)
            value = re.sub(r'\bcultivation point\b', 'cultivation points', value)
            headers[(label.lower(), normalized(value))] += 1
    names = Counter(name for name in CONDITIONS
                    if re.search(r'(?<!\w)' + re.escape(name) + r'(?:s)?(?!\w)', text, re.I))
    choice_names = Counter(name for name in choices if re.search(
        r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I))
    return {
        'numbers/dice': Counter(NUMBER.findall(text)), 'quantities': quantities,
        'duration boundaries': Counter(normalized(m[0]) for m in BOUNDARY.finditer(text)),
        'resource amounts': costs, 'table rows': tables,
        'headers': headers, 'conditions': names,
        'save abilities': Counter(normalized(m[1]) for m in SAVE.finditer(text)),
        'save DCs': Counter(normalized(m[0]) for m in DC.finditer(text)),
        'use rates': Counter(normalized(m[0]) for m in RATE.finditer(text)),
        'choice names': choice_names,
    }



def default_view_findings(card: dict) -> list[str]:
    """Check visible facts independently of the collapsed, complete Rules.

    Presence is set based: an editorial summary need not repeat a fact merely
    because the source repeats it. Numbers remain paired with units, resources,
    table rows and timing boundaries. This lexical gate does not prove scope or
    prose equivalence; clause-by-clause human review is still required.
    """
    from factory_authoring.player_rules import card_default_text

    def canonical(text):
        text = re.sub(r'[*`#]', '', text)
        text = re.sub(r'(?m)^\s*\d+\.\s+', '', text)
        text = re.sub(r'\bCP\b', 'cultivation points', text)
        text = re.sub(r'\bCL\s*(\d)', r'CL \1', text)
        text = re.sub(r'\bft\b', 'feet', text)
        text = re.sub(r'\bfoot\b', 'feet', text)
        return normalized(text)

    source = card['rules']
    visible = card.get('default_text', card_default_text(card))
    # Omit only the free-cost FIELD, never every occurrence of its number.
    # A second 0 in "at 0 HP" still has to appear in the default view.
    mechanics_source = re.sub(r'[*`#]', '', source)
    mechanics_source = re.sub(
        r'(?im)^[ \t]*Cost:[ \t]*(?:None|0(?: (?:CP|cultivation points?))?)\.?[ \t]*$',
        '', mechanics_source)
    before, after = protected(canonical(mechanics_source)), protected(canonical(visible))
    problems = []
    for field in ('numbers/dice', 'quantities', 'duration boundaries',
                  'resource amounts', 'conditions', 'save abilities',
                  'save DCs', 'use rates'):
        missing = set(before[field]) - set(after[field])
        if missing:
            problems.append(f'incomplete-{field}: {sorted(missing, key=str)}')
    # Reviewed owner wording can add a rule (for example an instinctive
    # servant's 30-foot follow distance) without changing archived Rules.
    # Support additions from either hash-bound text, just as for numbers;
    # missing printed facts above must still fail.
    supported = protected(canonical(source + '\n' + card.get('clarified', '')))
    invented = set(after['numbers/dice']) - set(supported['numbers/dice'])
    if invented:
        problems.append(f'unsupported-numbers/dice: {sorted(invented)}')
    for field in ('quantities', 'resource amounts', 'conditions', 'save abilities',
                  'save DCs', 'duration boundaries', 'use rates'):
        added = set(after[field]) - set(supported[field])
        if added:
            problems.append(f'unsupported-{field}: {sorted(added, key=str)}')
    plain_visible = canonical(visible)
    # Header values bind nonnumeric costs, targets and requirements too.
    for line in source.splitlines():
        line = re.sub(r'[*`]', '', line).strip()
        match = re.match(r'^(Range|Target|Area|Duration|Cost|Prerequisite|Trigger):\s*(.+)', line, re.I)
        if match:
            label, value = match.groups()
            if label.lower() == 'cost' and re.fullmatch(r'None\.?|0 CP\.?', value, re.I):
                continue
            # Compound duration fields may be unpacked into separate outcome
            # bullets. Their words, quantities and turn boundaries still bind.
            present = canonical(value).rstrip('.') in plain_visible
            if label.lower() == 'duration':
                present = set(re.findall(r'\w+', canonical(value))) <= set(
                    re.findall(r'\w+', plain_visible))
            if not present:
                problems.append(f'incomplete-{label.lower()}: {value}')
        if line.startswith('|') and NUMBER.search(line):
            row = ' '.join(part.strip() for part in line.strip('|').split('|'))
            words = lambda s: re.sub(r'[^\w+\-]+', ' ', canonical(s)).strip()
            if words(row) not in words(visible):
                problems.append(f'incomplete-scaling: {row}')
    # Named choice labels in printed prose (Lift:, Bitter Breath., etc.) and
    # subordinate option headings must each carry their effect in plain view.
    excluded = {'action type', 'timing detail', 'split review decision',
                'recommended factory realization', 'range', 'target', 'area',
                'duration', 'cost', 'prerequisite', 'requirement', 'save', 'trigger', 'effect',
                'limits', 'talent type', 'rarity', 'consumption', 'source cl',
                'failed save', 'successful save', 'hit', 'hit or unattended object',
                'tag', 'tags', 'type'}  # card metadata lines, read like player_rules (Tag:/Tags:/Type:)
    names, labeled_choices = [], []
    for line in source.splitlines()[1:]:
        m = re.match(r'^([A-Z][A-Za-z -]{1,40}):\s+\S', line) or re.match(
            r'^([A-Z][A-Za-z-]*(?: [A-Z][A-Za-z-]*){0,5})\.\s+\S', line)
        if m and m[1].lower() not in excluded:
            names.append(m[1])
            labeled_choices.append((m[1], line[m.end() - 1:]))
        m = re.match(r'^#{4,}\s+([A-Za-z][A-Za-z -]+)$', line)
        if m:
            names.append(m[1])
    for name in card.get('choice_names', []):
        if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', source, re.I):
            problems.append(f'unsupported-choice: {name}')
        names.append(name)
    for name in names:
        if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', visible, re.I):
            problems.append(f'incomplete-choice: {name}')
    for name, source_effect in labeled_choices:
        effect = re.search(r'(?m)^\s*(?:- )?' + re.escape(name) + r':\s+(\S[^\n]*)', visible)
        if not effect:
            problems.append(f'incomplete-choice-effect: {name}')
            continue
        # Bind facts to their choice, so retaining 5 feet in Press cannot mask
        # losing 5 feet from Lift. Qualifiers likewise belong to that effect.
        expected, actual = protected(canonical(source_effect)), protected(canonical(effect[1]))
        for field in ('numbers/dice', 'quantities', 'conditions', 'save abilities',
                      'duration boundaries', 'resource amounts'):
            missing = set(expected[field]) - set(actual[field])
            if missing:
                problems.append(f'incomplete-choice-effect: {name}: {field}: {sorted(missing, key=str)}')
        for qualifier in ('first', 'willing', 'hostile', 'unattended', 'Tiny',
                          'size larger than you', 'no more than', 'at least',
                          'up to', 'may', 'cannot', 'Disadvantage', 'Advantage',
                          'Dash', 'next', 'Long Rest', 'Proficiency Bonus'):
            pattern = r'(?<!\w)' + re.escape(qualifier) + r'(?!\w)'
            if re.search(pattern, canonical(source_effect), re.I) and not re.search(
                    pattern, canonical(effect[1]), re.I):
                problems.append(f'incomplete-choice-effect: {name}: {qualifier}')
    # These qualifiers are easy to lose while retaining every numeric token.
    for qualifier in ('willing', 'hostile', 'unattended', 'Tiny', 'Invisible',
                      'Concentration', 'Short Rest', 'Long Rest', 'Instantaneous',
                      'once per scene', 'once per recipe attempt'):
        pattern = r'(?<!\w)' + re.escape(qualifier) + r'(?!\w)'
        if re.search(pattern, source, re.I) and not re.search(pattern, visible, re.I):
            problems.append(f'incomplete-restriction: {qualifier}')
    if BANNED.search(visible):
        problems.append('banned phrase in default view')
    return problems
