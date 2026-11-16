"""Display projections used by the authority builder and combat.player_text.

Owner prose and reviewed evidence remain verbatim. This module only turns the
authoring fields into sentences; it never changes typing, hashes or mechanics.
Explicit display wording lives in owner_text_edits.json's player_text,
player_replace and player_evidence fields.
"""
from __future__ import annotations

import re
import hashlib
from html import escape

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


# CLARITY5 is an explicit card surface. Keep full-text/log callers on their
# existing API; they must not receive HTML or lose a sentence to a summary.
CARD_FACTS = ('Action', 'Ritual', 'Range', 'Duration', 'Cost', 'Use limit')
CARD_GROUPS = ('Effect', 'Choices', 'Limits')
CARD_GLOSSARY = {
    'CP': "Cultivation points: your Path's resource (Stamina, Qi or Resonance).",
    'PB': 'Proficiency Bonus: the bonus given by your level.',
    'CL': 'Cultivation Level: your level in cultivation.',
    'Realm': 'Realm: a stage of cultivation.',
    'Source CL': "Source CL: the power level used to set an effect's strength and determine whether it can overcome another effect.",
    'Trance Rhythm': 'Trance Rhythm: a pool that starts at 0 each scene and has a maximum of your Proficiency Bonus.',
    'Observed Tie': 'Observed Tie: a recorded connection between creatures, objects, Assets, Anchors, locations, or active spiritual effects.',
    'Path key ability modifier': 'The ability modifier for your Path’s key ability (such as Strength or Wisdom).',
    'Bound': 'Bound: magically restrained; your movement or actions may be limited by the stated effect.',
    'Tether': 'Tether: a link that restricts how far the linked creature or object can move.',
    'Destruction Die': 'Destruction Die: the die rolled to determine damage to an object or structure.',
    'Formation Save DC': 'The difficulty number a creature must meet or beat on its saving throw against a Formation.',
    'Contagion Token': 'A marker tracking exposure to contagion; its rules say when it spreads or is removed.',
    'Qi': 'Qi: a cultivation resource (CP) that pays costs written in Qi.',
    'Stamina': 'Stamina: a cultivation resource (CP) that pays costs written in Stamina.',
    'Resonance': 'Resonance: a cultivation resource (CP) that pays costs written in Resonance.',
    'Momentum': 'Momentum: a Path resource that certain features gain and spend.',
    'Brood': 'Brood: a resource that certain Subpath features gain and spend.',
    'Dread': 'Dread: a Path resource that certain Subpath features gain and spend.',
    'Domain Armament': 'Domain Armament: a bound item or form that projects your Domain; features can originate from it.',
    'Blood-Moon Mark': 'Blood-Moon Mark: a mark on a creature; three marks make it Condemned.',
    'Condemned': 'Condemned: a creature bearing three Blood-Moon Marks.',
    'Golden Core': 'Golden Core: a cultivation core that Golden Core features and Forms build on.',
    'Heavenly Tone': 'Heavenly Tone: one of the named effects you choose from each turn with a Heavenly Bell field.',
    'Execution Wound': 'Execution Wound: a lasting injury chosen after a failed Final Sentence save.',
    'Source Rule': "Source Rule: the authority backing an effect; an effect whose Source Rule is equal to or higher than another effect's can restrict or respect it, and is removed only by its own printed procedure or a higher authority.",
    'Cultivation Check': 'Cultivation Check: d20 + Proficiency Bonus + the key ability modifier of the Path powering the feature; the active roll used to resist or overcome a cultivation effect.',
    'Handspan Subject': 'Handspan Subject: the creature a Last-Inch feature names as its spiritual contact within handspan reach; your Spirit-Touch unarmed strikes and spirit techniques target only this creature.',
}
# Terms are glossed only when they have an authority definition, each in plain
# language for a reader who knows basic D&D. Longest names first so a shorter
# term never shadows a longer one; a trailing "s" is allowed so plurals share a
# definition. CL is matched separately because it also abbreviates the level in
# "CL N" ranges. Mandate is deliberately absent: it names an Imbuement effect
# and a Sovereign Will resource, so a single gloss would be wrong.
_GLOSSARY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(term) for term in sorted(CARD_GLOSSARY, key=len, reverse=True)
                        if term != 'CL') + r')s?\b|\b(CL)(?=\b|\d)')

# Factory review metadata describes implementation, never a rule for players.
# Keep it in card['rules'] for source/hash audits; omit only these whole fields
# from the disclosure, preserving every other printed line verbatim.
CARD_AUTHORING_NOTE = re.compile(
    r'(?m)^(?:Split Review Decision|Recommended Factory Realization):[^\n]*\n?')


def player_safe_rules(printed: str) -> str:
    """Complete printed rules without the factory's implementation annotations."""
    return CARD_AUTHORING_NOTE.sub('', printed)


def card_sha(text: str) -> str:
    """Bind a reviewed overview to the exact clarified text it summarizes."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def project_player_card(clarified: str, printed: str, edit: dict | None = None) -> dict:
    """Project a presentation-only card; never infer mechanics or truncate choices.

    player_card in owner_text_edits contains a reviewed summary and optional
    Effect/Choices/Limits lists. Unreviewed cards use a lossless fallback and
    remain lintable for batch editing. Only the first metadata block becomes
    facts: a nested option's price/range must never become its parent's price.
    Rules retains the entire printed source; clarified wording is retained for
    independent preservation checks. No combat state or source data is changed.
    """
    lines = [line.strip() for line in clarified.splitlines() if line.strip()]
    title = lines.pop(0) if lines else ''
    facts, body = [], []
    metadata_started = metadata_ended = False
    for line in lines:
        if RESOURCE_GLOSS.fullmatch(line):
            continue
        if line.startswith('Use this when '):
            line = 'Trigger: ' + line[len('Use this when '):]
        match = FIELD.match(line) or re.match(r'^(Trigger|Consumption):\s*(.*)$', line)
        if match and not metadata_ended:
            metadata_started = True
            label, value = match.groups()
            if label == 'Consumption':
                label = 'Action'
            if label in CARD_FACTS:
                if label != 'Cost' or not re.fullmatch(
                        r'None\.?|0(?: cultivation points?| CP)?\.?', value, re.I):
                    facts.append((label, value))
            else:
                body.append(line)
        else:
            if metadata_started:
                metadata_ended = True
            body.append(line.removeprefix('- '))
    facts.sort(key=lambda pair: CARD_FACTS.index(pair[0]))
    overview = (edit or {}).get('player_card')
    if overview is not None:
        if overview.get('source_sha256') != card_sha(clarified):
            raise ValueError(f'Stale player_card overview: {title}')
        if overview.get('rules_sha256') != card_sha(printed):
            raise ValueError(f'Stale player_card printed Rules: {title}')
        summary = overview['summary']
        groups = overview.get('groups', {})
        choices = overview.get('choice_names', [])
        if not isinstance(choices, list) or not all(isinstance(v, str) and v for v in choices):
            raise ValueError('player_card choice_names requires nonempty text names')
        if (not isinstance(summary, str) or not isinstance(groups, dict)
                or set(groups) - set(CARD_GROUPS)
                or any(not isinstance(items, list) or not all(isinstance(v, str) for v in items)
                       for items in groups.values())):
            raise ValueError('player_card requires a text summary and Effect/Choices/Limits lists')
        # Reviewed cards can lay out nested metadata explicitly. Hash binding
        # above prevents these display fields from outliving their source.
        if 'facts' in overview:
            facts = overview['facts']
            if (not isinstance(facts, list) or any(
                    not isinstance(pair, list) or len(pair) != 2
                    or pair[0] not in CARD_FACTS
                    or not isinstance(pair[1], str) for pair in facts)):
                raise ValueError('player_card facts require supported label/value pairs')
            facts = [tuple(pair) for pair in facts]
        reviewed = True
    else:
        choices = []
        summary_at = next((i for i, line in enumerate(body)
                           if not re.match(r'^[\w /-]+:', line)
                           and not line.startswith(('|', '“', '"'))), None)
        summary = body.pop(summary_at) if summary_at is not None else ''
        groups = {'Effect': body} if body else {}
        reviewed = False
    return {'title': title, 'summary': summary, 'facts': facts,
            'groups': {name: list(groups[name]) for name in CARD_GROUPS if groups.get(name)},
            'rules': printed, 'clarified': clarified, 'reviewed': reviewed,
            'choice_names': list(choices)}


def card_default_text(card: dict) -> str:
    """Exactly the visible text, excluding the title and collapsed Rules."""
    facts = ' · '.join(value if label in ('Action', 'Ritual') else
                       f'{"Uses" if label == "Use limit" else label}: {value}'
                       for label, value in card['facts'])
    parts = [card['summary'], facts]
    for name, items in card['groups'].items():
        parts.append(name + '\n' + '\n'.join('- ' + item for item in items))
    text = '\n\n'.join(part for part in parts if part)
    text = re.sub(r'\bcultivation points?\b', 'CP', text, flags=re.I)
    text = re.sub(r'\bProficiency Bonus\b', 'PB', text)
    return text


def render_player_card(card: dict) -> str:
    """Standalone accessible HTML; Rules starts collapsed, all content escaped.

    Shared glossary abbreviations use native hover/focus definitions rather
    than repeating definitions in the default text. No scripts or GUI needed.
    """
    def glossary(text):
        def wrap(m):
            term = m.group(1) or m.group(2)
            return ('<abbr tabindex="0" title="' + escape(CARD_GLOSSARY[term], quote=True)
                    + '">' + m.group(0) + '</abbr>')
        return _GLOSSARY_RE.sub(wrap, escape(text))
    def prose(text):
        text = re.sub(r'\bcultivation points?\b', 'CP', text, flags=re.I)
        text = re.sub(r'\bProficiency Bonus\b', 'PB', text)
        return glossary(text)
    out = ['<article class="player-card">', '<h3>' + escape(card['title']) + '</h3>',
           '<p>' + prose(card['summary']) + '</p>']
    facts = card_default_text({**card, 'summary': '', 'groups': {}})
    if facts:
        out.append('<p class="card-facts">' + prose(facts) + '</p>')
    for name, items in card['groups'].items():
        out.append('<section><h4>' + name + '</h4><ul>' + ''.join(
            '<li>' + prose(item) + '</li>' for item in items) + '</ul></section>')
    out.append('<details><summary>Rules</summary><pre style="white-space:pre-wrap">'
               + glossary(player_safe_rules(card['rules'])) + '</pre></details></article>')
    return '\n'.join(out)
