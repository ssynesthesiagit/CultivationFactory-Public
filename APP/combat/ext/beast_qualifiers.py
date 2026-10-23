"""Shared typed creature set for Ancient Desolate / Beast-Echo records.

Beast-Echo generation, spends, Predator Answer, Guard and State consumers use
`qualifies`, not names, source-id substrings or inferred predator vocabulary.
Explicit creature kinds come from the persisted creature_types field. A
Humanoid with compiled Beast Aspects path rows is beast-aspected without
changing its creature kind; no active-state/menu fallback invents ownership.
This library registers no hooks and changes no combat state.
"""
from __future__ import annotations

from typing import Any

from .creature_kinds import matches

KINDS = ("beast", "beast-aspected", "predator-aspected", "monstrosity",
         "spirit beast", "demon beast")
# Generate Pack Echo's hostile-hit clause ("hit a hostile beast-aspected,
# predator-aspected, monstrosity, spirit beast, or demon beast"). A plain
# Beast label is not on that list, so it must not trigger Echo on its own.
HOSTILE_TRIGGER_KINDS = ("beast-aspected", "predator-aspected", "monstrosity",
                         "spirit beast", "demon beast")


def qualifies(engine: Any, actor: Any, kinds: Any = KINDS) -> bool:
    """Whether typed creature data places actor in the printed beast set.

    `kinds` narrows the label set for a record that lists fewer kinds; the
    compiled Beast Aspects row only counts when "beast-aspected" is wanted.
    Missing labels/rows are nonqualifying. Ordinary Demons and Fiends do not
    imply Demon Beast, and a bare Predator label does not imply an aspect.
    """
    if actor is None:
        return False
    if matches(actor, kinds):
        return True
    if "beast-aspected" not in kinds:
        return False
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
    return any(row.get("block") == "path_rider" and row.get("kind") == "beast_aspects"
               for row in rows)
