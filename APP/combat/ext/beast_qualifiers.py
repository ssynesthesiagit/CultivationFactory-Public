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


def qualifies(engine: Any, actor: Any) -> bool:
    """Whether typed creature data places actor in the printed beast set.

    Missing labels/rows are nonqualifying. Ordinary Demons and Fiends do not
    imply Demon Beast, and a bare Predator label does not imply an aspect.
    """
    if actor is None:
        return False
    if matches(actor, KINDS):
        return True
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
    return any(row.get("block") == "path_rider" and row.get("kind") == "beast_aspects"
               for row in rows)
