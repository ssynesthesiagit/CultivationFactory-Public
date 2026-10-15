"""Display projections used by the authority builder and combat.player_text.

Owner prose and reviewed evidence remain verbatim. This module only turns the
authoring fields into sentences; it never changes typing, hashes or mechanics.
Explicit display wording lives in owner_text_edits.json's player_text,
player_replace and player_evidence fields.
"""
from __future__ import annotations

import re

AUTHORING = re.compile(r"(?:\*\*)?\b(Talent Type|Prerequisite|Action Type|Trigger|Effect)\s*:(?:\*\*)?", re.I)
RAW_ID = re.compile(r"\b(?:(?:action|condition|passive|resource):typed\.[\w.#-]+|TAL_[A-Z0-9_]+)")
HEADING = re.compile(r"#{1,6}\s+")

# Card layout runs AFTER checked owner phrase replacements. Keep display_prose's
# legacy input vocabulary stable: existing player_replace pairs bind to it.
RESOURCE_DEFINITION = "Cultivation points are your Path's resource: Stamina, Qi or Resonance."
RESOURCE_GLOSS = re.compile(
    r"^Cultivation points are (?:your Path[’']s resource: Stamina, Qi or Resonance|"
    r"the resource used by your Path: Stamina, Qi, or Resonance)\.$", re.I)
FIELD_ORDER = {
    'Requires': 0, 'Action': 1, 'Timing': 2, 'Time': 3, 'Ritual Time': 3,
    'Parent Action': 4, 'Replaces Attacks': 5, 'Range': 6, 'Target': 7,
    'Targets': 7, 'Area': 8, 'Save': 9, 'Duration': 10, 'Concentration': 11,
    'Cost': 12, 'Use limit': 13,
}
FIELD = re.compile(r'^(Tags?|Type|Requires|' + '|'.join(FIELD_ORDER) + r'):\s*(.*)$')


def card_field(line: str) -> str:
    """Normalize printed field labels, without inferring missing information."""
    line = re.sub(r'^(?:To learn this, you need\s+|Prerequisites?:\s*|Requirements?:\s*)',
                  'Requires: ', line)
    line = re.sub(r'^You can use this when\s+', 'Trigger: ', line)
    line = re.sub(r'^Trigger:\s+(You|Your|A|An|The|When|If|After|Before|At|Once|While|Whenever|During|Any|Another|One|Each)\b',
                  lambda m: 'Trigger: ' + m[1].lower(), line)
    line = re.sub(r'^This ability provides\s+', 'Type: ', line)
    line = re.sub(r'^Use this as\s+', 'Action: ', line)
    line = re.sub(r'^Timing Detail:', 'Timing:', line)
    line = re.sub(r'^(?:Use )?Limit:', 'Use limit:', line)
    line = re.sub(r'^Saving Throw:', 'Save:', line)
    actions = {'Use an action.': 'Action', 'Use a bonus action.': 'Bonus Action',
               'Use a reaction.': 'Reaction', 'Action': 'Action',
               'Bonus Action': 'Bonus Action', 'Reaction': 'Reaction'}
    if line in actions:
        line = 'Action: ' + actions[line]
    if line in {'Type: Action', 'Type: Bonus Action', 'Type: Reaction', 'Type: No Action / Triggered'}:
        line = 'Action:' + line[len('Type:'):]
    # The legacy projector also expanded these words inside ordinary sentences.
    # Restore their noun meaning, e.g. "appropriate to the trigger:".
    line = line.replace('You can use this when', 'trigger:')
    line = line.replace('Use this as', 'action type:')
    return line


def format_card(text: str) -> str:
    """Format a whole display card, preserving rule order and all printed words.

    Only the first contiguous metadata block is ordered. Nested action headers,
    triggers, choices, tables and exceptions stay beside the rules they modify.
    Explicit semicolon lists and existing bullets share one bullet style; prose
    paragraphs are never guessed to be choices. This function is idempotent.
    """
    lines = []
    has_resource = bool(re.search(r'\bcultivation points?\b', text, re.I))
    for raw in text.replace('\\n', '\n').splitlines():
        line = re.sub(r'[ \t]+', ' ', raw).strip()
        if RESOURCE_GLOSS.fullmatch(line):
            continue
        line = re.sub(r'\s*\(your Path resource\)', '', line)
        line = card_field(line).rstrip()
        if line == 'Requires:':
            continue
        line = re.sub(r'^[•*–]\s+', '- ', line)
        lines.append(line)
    # Explain CL at its first abbreviated use, rather than on every level.
    joined = '\n'.join(lines)
    joined = re.sub(r'(?<![\w+–-])1 cultivation points\b', '1 cultivation point', joined)
    joined = re.sub(r'\s*\(Cultivation Level\)', '', joined)
    joined = re.sub(r'\bCL\s*\d+(?:\s*[-–]\s*\d+)?\+?',
                    lambda m: m[0] + ' (Cultivation Level)', joined, count=1)
    lines = joined.splitlines()
    # A standalone introductory quotation is flavour, and belongs after rules.
    quotes = []
    for index in range(min(5, len(lines))):
        if re.fullmatch(r'“[^“”]+”|"[^"\n]+"', lines[index]):
            quotes.append(lines[index])
            lines[index] = ''
    first = next((i for i, line in enumerate(lines)
                  if (FIELD.match(line) and not line.startswith(('Tag:', 'Tags:', 'Type:')))
                  or line.startswith('Trigger:')), None)
    definition_at = None
    if first is not None:
        end = first
        while end < len(lines) and (not lines[end] or FIELD.match(lines[end])
                                   or lines[end].startswith('Trigger:')):
            end += 1
        fields = [line for line in lines[first:end] if line]
        # A closing, record-level use limit belongs in the metadata block too.
        # Stop at a subheading, a nested trigger, or another action's fields;
        # never hoist an option's own limit onto its parent ability.
        body = lines[end:]
        if not any(line.startswith('Use limit:') for line in fields):
            for index, line in enumerate(body):
                if not line:
                    continue
                if line.startswith('Use limit:'):
                    fields.append(line)
                    body = body[:index] + body[index + 1:]
                    break
                if FIELD.match(line) or line.startswith('Trigger:'):
                    break
                if (not line.startswith(('-', '|')) and len(line.split()) <= 12
                        and not re.search(r'[.:;!?]', line)):
                    break
        tags = [line for line in fields if line.startswith(('Tag:', 'Tags:', 'Type:'))]
        fields = [line for line in fields if line not in tags]
        fields.sort(key=lambda line: 2 if line.startswith('Trigger:') else
                    FIELD_ORDER.get(line.split(':', 1)[0], 99))
        prefix = lines[:first]
        prefix_tags = [line for line in prefix[:5] if line.startswith(('Tag:', 'Tags:', 'Type:'))]
        prefix = [line for index, line in enumerate(prefix)
                  if not (index < 5 and line in prefix_tags)]
        tags = prefix_tags + tags
        if tags:
            title_end = 1 if prefix and prefix[0] else 0
            prefix[title_end:title_end] = tags
        # Separate title/summary, metadata and rules with paragraph spacing.
        lines = prefix + [''] + fields + [''] + body
        definition_at = len(prefix) + 1 + len(fields) + 1
    # Explicit list runs: preserve semicolons (including an "and/or" connector)
    # and make each existing item readable without altering its scope.
    in_list = False
    for index, line in enumerate(lines):
        if not line:
            continue
        if (line.endswith(';') and not FIELD.match(line)) or line.startswith('- '):
            if not line.startswith(('|', '- ')):
                lines[index] = '- ' + line
            in_list = line.endswith(';')
        elif in_list:
            if not FIELD.match(line) and not line.startswith(('Trigger:', '|')):
                lines[index] = '- ' + line
            in_list = False
    # Insert the glossary after list handling so it can never become a choice.
    if has_resource:
        if definition_at is None:
            definition_at = 1 if lines else 0
        lines[definition_at:definition_at] = ['', RESOURCE_DEFINITION, '']
    # Collapse blank lines inside a bullet run, retaining paragraph breaks.
    out = '\n'.join(lines)
    out = re.sub(r'(?m)^(- [^\n]+)\n(?:\s*\n)+(?=- )', r'\1\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out).strip()
    return out + ('\n\n' + '\n\n'.join(quotes) if quotes else '')


def display_prose(text: str, *, legacy_fields: bool = False) -> str:
    """Project labels without re-expanding labels on an already built card.

    The builder explicitly requests legacy_fields before checked phrase edits.
    Runtime fallback accepts the canonical Requires/Action/Trigger labels, so
    cleaning an existing card cannot turn its headers back into filler prose.
    Evidence retains its existing legacy projection for persisted reminders.
    """
    text = HEADING.sub("", text)
    text = text.replace("**", "").replace("`", "")
    words = {"talent type": "This ability provides", "prerequisite": "To learn this, you need",
             "action type": "Use this as", "trigger": "You can use this when",
             "effect": ""}
    if legacy_fields:
        text = AUTHORING.sub(lambda m: (words[m[1].lower()] + " ") if words[m[1].lower()] else "", text)
    else:
        labels = {'talent type': 'Type: ', 'prerequisite': 'Requires: ',
                  'action type': 'Action: ', 'trigger': 'Trigger: ', 'effect': ''}
        text = re.sub(r'(?im)^(Talent Type|Prerequisite|Action Type|Trigger|Effect)\s*:[ \t]*',
                      lambda m: labels[m[1].lower()], text)
    economies = {"action": "an action", "bonus action": "a bonus action", "reaction": "a reaction"}
    text = re.sub(r"(?im)^Use this as\s+(Action|Bonus Action|Reaction)\s*\.?\s*$",
                  lambda m: "Use " + economies[m[1].lower()] + ".", text)
    text = re.sub(r"\bCP\b", "cultivation points (your Path resource)", text)
    return text.strip()


def build_player_text(texts: dict[str, str], edits: dict) -> dict:
    """Build display text alongside, rather than over, the source authority.

    Overrides match the exact owner text and reviewed rider evidence. They never
    become effect evidence or parser input. Other records use a lossless field
    projection; no rule is inferred from a header or an internal identifier.
    """
    from factory_authoring.owner_text_edits import player_wording

    records = {}
    for key, raw in texts.items():
        edit = edits.get(key) or {}
        override = edit.get("player_text")
        records[key] = format_card(player_wording(
            display_prose(str(override), legacy_fields=True) if override else
            display_prose(raw, legacy_fields=True), edit))
    evidence = {}
    for edit in edits.values():
        for raw, text in (edit.get("player_evidence") or {}).items():
            text = display_prose(text, legacy_fields=True)
            if raw in evidence and evidence[raw] != text:
                raise ValueError(f"Conflicting player_evidence wording for {raw!r}")
            evidence[raw] = text
    return {"schema": "player_text.v1", "records": records, "evidence": evidence}
