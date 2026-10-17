"""Display projections used by the authority builder and combat.player_text.

Owner prose and reviewed evidence remain verbatim. This module only turns the
authoring fields into sentences; it never changes typing, hashes or mechanics.
Explicit display wording lives in owner_text_edits.json's player_text field.
"""
from __future__ import annotations

import re

AUTHORING = re.compile(r"(?:\*\*)?\b(Talent Type|Prerequisite|Action Type|Trigger|Effect)\s*:(?:\*\*)?", re.I)
RAW_ID = re.compile(r"\b(?:(?:action|condition|passive|resource):typed\.[\w.#-]+|TAL_[A-Z0-9_]+)")
HEADING = re.compile(r"#{1,6}\s+")


def display_prose(text: str) -> str:
    """Keep every rule clause, replacing authoring labels with player wording."""
    text = HEADING.sub("", text)
    text = text.replace("**", "").replace("`", "")
    words = {"talent type": "This ability provides", "prerequisite": "To learn this, you need",
             "action type": "Use this as", "trigger": "You can use this when",
             "effect": ""}
    text = AUTHORING.sub(lambda m: (words[m[1].lower()] + " ") if words[m[1].lower()] else "", text)
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
    records = {}
    for key, raw in texts.items():
        override = (edits.get(key) or {}).get("player_text")
        records[key] = str(override) if override else display_prose(raw)
    evidence = {raw: text for edit in edits.values() for raw, text in (edit.get("player_evidence") or {}).items()}
    return {"schema": "player_text.v1", "records": records, "evidence": evidence}
