"""Read-only record presentation for combat hovers, sheets and builder responses.

All three consumers use record_display; compilation and saved
evidence retain their full text. File identities invalidate the small lazy cache
when the owner edits display wording during play.
"""
from functools import lru_cache
from pathlib import Path
import json
import re

from .player_rules import (card_default_text, display_prose, project_player_card,
                           render_player_card)

DATA = Path(__file__).resolve().parents[1] / "authority/typed_mechanics"
SECTIONS = DATA / "record_sections.json"


@lru_cache(maxsize=1)
def _catalogue(stamp):
    rules, players, edits = (json.loads((DATA / name).read_text(encoding="utf-8")) for name in
                             ("rules_text.json", "player_text.json", "owner_text_edits.json"))
    names = {}
    for key, text in rules.items():
        title = re.sub(r"^#+\s*|\*\*", "", text.splitlines()[0] if text else "")
        title = re.sub(r"^CL\s*\d+\s*[-—–]\s*", "", title)
        names.setdefault(_words(title), []).append(key)
    return rules, players, edits, names, json.loads(SECTIONS.read_text(encoding="utf-8"))


def _words(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def rule_section(text, name):
    """Select one uniquely named heading including upgrades, never its siblings."""
    headings = [(m.start(), len(m[1]), _words(m[2])) for m in
                re.finditer(r"(?m)^(#{1,6})\s+(.+)$", text)]
    wanted = _words(name)
    matches = [(start, depth) for start, depth, title in headings
               if wanted and (title == wanted or title.startswith(wanted + " "))]
    if len(matches) != 1:
        return text
    start, depth = matches[0]
    end = next((pos for pos, level, _ in headings if pos > start and level <= depth), len(text))
    return text[start:end].strip()


def _inline_option(text: str, option: str) -> str:
    """Scope a uniquely named rider in a printed inline Choose-one list.

    Retain the surrounding trigger, cost and limits. Ambiguous labels keep the
    original text; this never generates mechanics from prose.
    """
    match = re.search(r"(?:Then\s+)?choose one(?: rider| effect)?:\s*([^\n]+)", text, re.I)
    if not match:
        return text
    options, dot, rest = match[1].partition(". ")
    parts = re.split(r";\s*(?:or\s+)?", options)
    if len(parts) < 2:
        return text
    def words(value: str) -> set[str]:
        value = re.sub(r"\bft\b", "feet", value.casefold())
        return set(re.findall(r"[a-z]+|\d+", value)) - {"no", "the", "a", "or", "on", "off"}
    wanted = words(option)
    scores = [len(wanted & words(part)) for part in parts]
    best = max(scores)
    if not best or scores.count(best) != 1:
        return text
    selected = parts[scores.index(best)].strip().rstrip(".") + "."
    context = text[:match.start()] + (rest if dot else "") + text[match.end():]
    return selected + "\n\n" + context.strip()


def _selected_evidence(text, evidence):
    """Scope an explicitly labelled multiline choice, retaining trigger/cost/save context."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.search(r"Choose one:\s*$", line)), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if re.match(
        r"^(?:Successful Save|Success|Miss|Hit|Duration|Limit|Use limit):", lines[i])), len(lines))
    matches = [line for line in lines[start + 1:end] if _words(line) == _words(evidence)]
    if len(matches) != 1:
        return text
    selected = matches[0]
    qualifier = lines[start].rsplit("Choose one:", 1)[0].strip()
    selected = re.sub(r"^\s*[-*•]\s+", "", selected).rstrip(";")
    return "\n".join([" ".join(part for part in (qualifier, selected) if part),
                      *lines[:start], *lines[end:]])


def display_version():
    """Shared asset identity for record_display and combat.condition_text caches."""
    paths = [DATA / n for n in ("rules_text.json", "player_text.json", "owner_text_edits.json")] + [SECTIONS]
    return tuple((str(path), (stat := path.stat()).st_mtime_ns, stat.st_size) for path in paths)


def record_display(record, section="", *, fallback=""):
    """One display source: valid reviewed card, else clarified text; Rules collapsed.

    A selected named subsection retains only its own reviewed choice bullets
    (including nested upgrades). No new wording or mechanical values are inferred.
    Returns None for non-records so native controls keep their own instructions.
    """
    if not record and not fallback:
        return None
    stamp = display_version()
    display = _record_display(stamp, str(record or ""), str(section or ""))
    if display or not fallback:
        return display
    clarified = display_prose(fallback)
    title, separator, body = clarified.partition("\n")
    card = {"title": title if separator else "", "summary": body if separator else title, "facts": [], "groups": {}, "rules": fallback}
    return {"record_id": str(record or ""), "text": card_default_text(card), "facts": [], "title": card["title"], "html": render_player_card(card)}


@lru_cache(maxsize=8192)
def _record_display(stamp, record, section):
    rules, players, edits, names, sections = _catalogue(stamp)
    if record not in rules:
        matches = names.get(_words(record), []) if record else []
        if len(matches) != 1:
            return None
        record = matches[0]
    printed = rules[record]
    clarified = players["records"].get(record) or display_prose(printed)
    edit = edits["records"].get(record) or {}
    try:
        card = project_player_card(clarified, printed, edit)
    except ValueError:
        # Authoring stays strict; an invalid overview is absent for display,
        # never a reason to make the combat menu unavailable.
        card = project_player_card(clarified, printed)
    # A section name is a printed heading, not an internal effect/condition id.
    section, _, evidence = section.partition(" — ")
    section = section.strip()
    section = re.sub(r"\s*\((?:Concentration|Persistent|\d+ CP)\)$", "", section)
    # Unnamed choices use explicit label -> printed-clause provenance, never
    # word-overlap guesses. The same clause identifies its reviewed Choices bullet.
    evidence = sections.get(record, {}).get(section, evidence)
    scoped = rule_section(printed, section) if section else printed
    if scoped != printed:
        headings = [_words(m) for m in re.findall(r"(?m)^#+\s+(.+)$", scoped)]
        chosen = [item for items in card["groups"].values() for item in items
                  if _words(item.partition(":")[0]) in headings and ":" in item]
        if card["reviewed"] and chosen:
            card = {**card, "title": scoped.splitlines()[0].lstrip("# "),
                    "summary": chosen[0].partition(":")[2].strip(), "facts": [],
                    "groups": {"Effect": chosen[1:]} if len(chosen) > 1 else {},
                    "rules": scoped}
        else:
            # Clarified headings preserve the printed names even without Markdown.
            names = re.findall(r"(?m)^#+\s+(.+)$", printed)
            start_name = re.findall(r"(?m)^#+\s+(.+)$", scoped)[0]
            start = next((i for i, line in enumerate(clarified.splitlines())
                          if _words(line) == _words(start_name)), None)
            if start is not None:
                lines = clarified.splitlines()[start:]
                siblings = set(names) - set(re.findall(r"(?m)^#+\s+(.+)$", scoped))
                end = next((i for i, line in enumerate(lines[1:], 1) if line in siblings), len(lines))
                clarified = "\n".join(lines[:end]).strip()
            card = {**card, "title": start_name, "summary": clarified.partition("\n")[2].strip(),
                    "facts": [], "groups": {}, "rules": scoped}
    elif section:
        choices = card["groups"].get("Choices", [])
        chosen = [item for item in choices if _words(item.partition(":")[0]) == _words(section)
                  or (evidence and _words(item) == _words(evidence))]
        if chosen:
            siblings = [_words(item.partition(":")[0]) for item in choices if item not in chosen and ":" in item]
            printed = "\n".join(line for line in printed.splitlines() if not any(
                _words(line.replace("**", "").lstrip("- ").partition(":")[0]) == name for name in siblings))
            card = {**card, "title": f"{card['title']}: {section}",
                    "groups": {**card["groups"], "Choices": chosen},
                    "rules": _selected_evidence(printed, evidence) if evidence else printed}
        elif not card["reviewed"]:
            scoped = _selected_evidence(clarified, evidence) if evidence else _inline_option(clarified, section)
            card = {**card, "summary": scoped.replace(card["title"] + "\n", "", 1) if scoped != clarified else clarified.partition("\n")[2].strip(),
                    "facts": [], "groups": {}, "rules": _selected_evidence(printed, evidence) if evidence else _inline_option(printed, section)}
    elif not card["reviewed"]:
        # Unreviewed records show the clarified wording losslessly, not an
        # automatically invented overview. CLARITYPRO2 owns their future cards.
        card = {**card, "summary": clarified.partition("\n")[2].strip() if "\n" in clarified else clarified,
                "facts": [], "groups": {}}
    return {"record_id": record, "text": card_default_text(card), "facts": [list(pair) for pair in card["facts"]], "title": card["title"],
            "html": render_player_card(card)}


def present_records(value):
    """Decorate response copies only; builder choices and library entries share this seam."""
    if isinstance(value, list):
        return [present_records(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: present_records(item) for key, item in value.items()}
    display = next((display for key in ("record_id", "candidate_record_id", "base_ability_id",
                    "canonical_talent_id", "preserved_legacy_id", "choice_id", "id")
                    if value.get(key) and (display := record_display(value[key]))), None)
    if not display:
        text = next((value.get(key) for key in ("player_rules_text", "full_description", "short_description", "description")
                     if isinstance(value.get(key), str) and value[key]), "")
        if text:
            display = record_display("", fallback=text)
    if display:
        out["player_card"] = display
    return out
