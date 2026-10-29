"""Read-only record presentation for combat hovers, sheets and builder responses.

All three consumers use record_display; compilation, model inputs and saved
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


@lru_cache(maxsize=1)
def _catalogue(stamp):
    return tuple(json.loads((DATA / name).read_text(encoding="utf-8")) for name in
                 ("rules_text.json", "player_text.json", "owner_text_edits.json"))


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


def record_display(record, section=""):
    """One display source: reviewed card, else clarified player_text; Rules collapsed.

    A selected named subsection retains only its own reviewed choice bullets
    (including nested upgrades). No new wording or mechanical values are inferred.
    Returns None for non-records so native controls keep their own instructions.
    """
    stamp = tuple((str(DATA / n), (DATA / n).stat().st_mtime_ns,
                   (DATA / n).stat().st_size) for n in
                  ("rules_text.json", "player_text.json", "owner_text_edits.json"))
    return _record_display(stamp, str(record or ""), str(section or ""))


@lru_cache(maxsize=8192)
def _record_display(stamp, record, section):
    rules, players, edits = _catalogue(stamp)
    if record not in rules:
        return None
    printed = rules[record]
    clarified = players["records"].get(record) or display_prose(printed)
    edit = edits["records"].get(record) or {}
    card = project_player_card(clarified, printed, edit)
    # A section name is a printed heading, not an internal effect/condition id.
    section = section.split(" — ", 1)[0].strip()
    section = re.sub(r"\s*\((?:Concentration|Persistent|\d+ CP)\)$", "", section)
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
    elif not card["reviewed"]:
        # Unreviewed records show the clarified wording losslessly, not an
        # automatically invented overview. CLARITYPRO2 owns their future cards.
        card = {**card, "summary": clarified.partition("\n")[2].strip(),
                "facts": [], "groups": {}}
    return {"record_id": record, "text": card_default_text(card),
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
    if display:
        out["player_card"] = display
    return out
