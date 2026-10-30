"""Printed sight qualifiers for reaction subjects, using shared sight and senses.

Unqualified rows are inert. Hidden/Invisible creatures need a revealing sense;
ordinary line of sight alone does not reveal them. No ability ids are interpreted.

Two row fields are honored:

- ``requires_sight`` (the reaction's trigger names a creature the reactor must see): the shared
  ``reaction_subject_allowed`` hook tests the triggering creature.
- ``requires_sight_of_subject`` (an ally reaction whose printed target is "an ally you can see",
  e.g. Refined Moonspring Root's Returning-Spring Guard): the ``ally_row_allowed`` hook tests the
  protected creature instead. Shared perception already needs line of sight, so this also refuses a
  protected ally behind total cover. A row without the field is unchanged; no ability ids are read.
"""
from functools import lru_cache
from typing import Any
from . import hook


@lru_cache(maxsize=1024)
def _legacy_sight(feature: str, kind: str) -> bool:
    """Recover a dropped filter for old sealed rows, without rewriting a save.

    Only a printed Trigger clause classified for this row's checkpoint qualifies.
    Other rows keep their original unrestricted behavior.
    """
    from ..status_text import printed_rules
    from ..reaction_triggers import classify_mechanic_all

    text = printed_rules().get(feature, "")
    trigger = next((line.partition(":")[2].strip() for line in text.splitlines() if line.startswith("Trigger:")), "")
    if not trigger:
        return False
    matches = classify_mechanic_all({"mechanic_id": feature, "activation": {"trigger": trigger}})
    return any(match.requires_sight and (not kind or match.kind == kind) for match in matches)


def _perceives(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """None when the reactor perceives ``other``; False when the shared rules do not let it."""
    from .. import senses, stealth

    if other is None:
        return False
    from types import SimpleNamespace
    from ..target_knowledge import sight_bypassed

    # Reaction rows carry their own feature identity, not a primary action ID.
    action = SimpleNamespace(parameters={'typed': {'source': row.get('feature_id')}})
    if sight_bypassed(engine, reactor, other, action):
        return None
    if any(c.condition_id == "condition:typed.blinded" for c in reactor.conditions.values()) and not senses.perceives_without_sight(engine, reactor, other):
        return False
    if not stealth.sees(engine, reactor, other):
        return False
    if any(c.condition_id in {"condition:typed.invisible", stealth.HIDDEN} for c in other.conditions.values()):
        return senses.sees_hidden(engine, reactor, other)
    return None


@hook("reaction_subject_allowed")
def sight_allowed(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    requires_sight = row.get("requires_sight")
    if requires_sight is None:
        requires_sight = _legacy_sight(str(row.get("feature_id") or ""), str(row.get("kind") or ""))
    if not requires_sight:
        return None
    return _perceives(engine, reactor, other, row)


@hook("ally_row_allowed")
def ally_sight_allowed(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """An ally reaction that names the harmed/protected creature ("an ally you can see").

    The compiler sets ``requires_sight_of_subject`` from the named rider
    (combat/factory_compiler.py, _attach_reaction_modifiers). Rows without it are
    untouched, so no other ally reaction changes behavior.
    """
    if row.get("requires_sight_of_subject") is not True:
        return None
    return _perceives(engine, reactor, subject, row)
