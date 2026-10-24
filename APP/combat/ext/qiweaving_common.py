"""Shared readers for Qiweaving's printed reach and printed classifications, used by the Qiweaving plug-ins
(auto lane AUTO12, 2026-10-04; classification reading added by AUTO12r1f1, 2026-10-05).

Owner text (APP/authority/typed_mechanics/rules_text.json): Qi Bond is "Range: 30 feet", and three talents widen it --
Meridian Grammar ("increase the range of Unweave Pattern and Qi Bond to 60 feet"), Court of Ten Thousand Currents ("your
Unweave Pattern and Qi Bond range extends to any valid target inside the Domain") and Sovereign Qiweaver Incarnation
("your Unweave Pattern and Qi Bond range becomes 120 feet").  Meridian Grammar's typed modifier (``add_range_ft``) reaches
the compiled Qi Bond action, so reading that one action's range gives the reach every Qiweaving ability should use; a
character without it keeps the printed 30 feet.

It also holds the one reader of that printed text the plug-ins share:

* ``rules_text()`` -- the owner's printed text, by mechanic id, read once per process.
* ``source_of(action)`` -- the mechanic id one compiled action came from, with any "+variant" or "#mode" suffix removed.
* ``classifies_as_secret_inheritance(typed, text)`` / ``is_secret_inheritance(action)`` -- whether the owner classifies
  a technique's own record as a Secret Inheritance.  Circuit Lock prints "Circuit Lock does not prevent a creature from
  using a Secret Inheritance", so ``combat.ext.qiweaving_bond`` must never withhold one from a Locked creature's menu.
  This is deliberately a DIFFERENT question from the one ``combat.ext.qiweaving_unweave`` asks of the same text ("may
  this Active Qi Pattern be ended at all?", which also covers Domains, Formation projects, artifacts and campaign-scale
  magic and so fails closed); that plug-in keeps its own classifier and does not read this one.

Consumers: ``combat.ext.remote_origins`` also uses the public source and Secret
classification readers for Formation Thread Relay. ``combat.ext.qiweaving_bond`` (the Bond talents, which the printed text applies "to the target" of the bond,
and Circuit Lock's Secret Inheritance exemption) and ``combat.ext.qiweaving_unweave`` (Unweave Pattern, which the same
talents widen by the same words, and whose Pattern Rank is read off this text).  Both read only the public
``compile_actions`` payload (``info["actions"]``, a list of compiled ActionDefinition objects) and the compiled action
itself; neither calls into the other.
"""

from __future__ import annotations

import json
import re
from typing import Any

BOND = "TAL_QIWEAVING_QI_BOND"
PRINTED_FT = 30
_RULES: dict[str, str] = {}
# The owner names a talent's category in these labelled lines; "Tags:" carries the same list on some records.
_CATEGORY_LINE = re.compile(r"^(?:Source Category|Effect Category|Pattern Type|Talent Type|Tags):", re.I)
# "Secret Inheritance", and the owner's own variants of the phrase ("Secret Music Inheritance",
# "Secret Formation Inheritance", "Secret Unmaking Inheritance").
_SECRET_PHRASE = re.compile(r"\bSecret(?:\s+\w+)?\s+Inheritance\b", re.I)
_SECRET_TAG = re.compile(r"\bSecret\b", re.I)


def bond_reach(info: dict[str, Any], fallback: int = PRINTED_FT) -> int:
    """The character's current Qiweaving reach in feet, from the compiled Qi Bond action when there is one."""
    for row in info.get("actions") or []:
        typed = (getattr(row, "parameters", None) or {}).get("typed") or {}
        if typed.get("source") == BOND:
            return int(getattr(row, "range_ft", None) or fallback)
    return fallback


def rules_text() -> dict[str, str]:
    """The owner's printed text for every talent, by mechanic id, read once."""
    if not _RULES:
        from .. import factory_compiler

        _RULES.update(json.loads((factory_compiler.APP / "authority/typed_mechanics/rules_text.json").read_text(encoding="utf-8")))
    return _RULES


def source_of(action: Any) -> str:
    """The mechanic id one compiled action came from: its typed source, else the third field of its
    ``action:typed.<sheet>.<mechanic>`` id with any "+variant" or "#mode" suffix removed."""
    parameters = getattr(action, "parameters", None) or {}
    source = str(((parameters.get("typed") or {}).get("source")) or "")
    if source:
        return source
    parts = str(getattr(action, "source_definition_id", "") or "").split(".", 2)
    return parts[2].split("+")[0].split("#")[0] if len(parts) == 3 else ""


def _classifying_lines(text: str) -> list[tuple[str, bool]]:
    """(line, is_a_category_line) for the owner-authored lines that classify a talent's own power: its title, a
    labelled category or tag line, a standalone category line ("Secret Formation Inheritance", optionally bolded) and the
    Prerequisite that grants it.  Body prose is deliberately left out, so a rule that merely mentions the phrase
    ("this cannot end a Secret Inheritance") never classifies the record it lives in."""
    rows: list[tuple[str, bool]] = []
    titled = False
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if not titled:
            rows.append((line, False))
            titled = True
        elif _CATEGORY_LINE.match(line):
            rows.append((line, True))
        elif _SECRET_PHRASE.fullmatch(line.strip("*")):
            rows.append((line.strip("*"), False))  # standalone printed category, including unbolded records
        elif line.startswith("**") and line.endswith("**") and ":" not in line:
            rows.append((line.strip("*"), False))
        elif line.lower().startswith("prereq"):
            rows.append((line, False))
    return rows


def classifies_as_secret_inheritance(typed: dict[str, Any], text: str) -> bool:
    """Whether the owner classifies this talent's own printed record as a Secret Inheritance.

    The owner says so in the record's title ("Secret Inheritance - ...", "SECRET INHERITANCE - ...", "Secret Music
    Inheritance - ..."), in a labelled category or tag line, in a bolded category line, or in the Prerequisite that
    grants it.  A bare ``Secret`` counts only on an explicit category line, which is how the Equipment and Source
    scriptures declare theirs ("Tags: Armor, Guard, Secret").  An unknown record is not an inheritance, so whatever
    limit asked the question still applies to it.
    """
    rows = _classifying_lines(text)
    fields = [str(typed.get(key) or "").replace("_", " ") for key in ("source_category", "pattern_category")]
    fields.extend(line for line, _category in rows)
    if any(_SECRET_PHRASE.search(field) for field in fields):
        return True
    return any(_SECRET_TAG.search(line) for line, category in rows if category)


def is_secret_inheritance(action: Any) -> bool:
    """Whether one compiled action is a Secret Inheritance, read from its own printed record.  Default-inert: an
    action with no printed record of its own (an ordinary basic attack, a maneuver) is not one."""
    if action is None:
        return False
    parameters = getattr(action, "parameters", None) or {}
    typed = parameters.get("typed") or {}
    if not typed or parameters.get("basic"):
        return False
    return classifies_as_secret_inheritance(typed, rules_text().get(source_of(action), ""))
