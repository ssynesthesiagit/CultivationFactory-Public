"""Shared helper: a Grapple or Shove attempt a feature grants "without another action" (rider lane C7, 2026-09-30).
Used by beast_aspects.py (Beast King's Technique, Ape) and hundred_hands.py (Circle of Uncounted Arms, Seizing Hand).

``attempt(engine, actor, target, intent, keys, choice_id, prompt)`` runs the attempt save of one of the fighter's own compiled
Unarmed Strike options (factory_compiler._unarmed_options: "Grapple", "Shove: Push 5 ft", "Shove: Prone" -- 2024 rules, the
target's Strength or Dexterity save against 8 + Strength + Proficiency Bonus, no more than one size larger) against ``target``,
asking which one when more than one of ``keys`` is available. It spends nothing and makes no attack. Returns the option key
used, or None (no such option, or declined). A fighter without those options (a shield in hand for Grapple) gets None.
"""

from __future__ import annotations

from typing import Any

KEYS = ("grapple", "shove_push", "shove_prone")


def options(engine: Any, actor: Any, keys: tuple[str, ...] = KEYS) -> dict[str, Any]:
    return {a.source_definition_id.rsplit(".", 1)[-1]: a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
            and ".unarmed." in a.source_definition_id and a.source_definition_id.rsplit(".", 1)[-1] in keys}


def attempt(engine: Any, actor: Any, target: Any, intent: Any, keys: tuple[str, ...] = KEYS, *, choice_id: str, prompt: str) -> str | None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    found = options(engine, actor, keys)
    if not found or target is None or not target.active:
        return None
    ordered = [key for key in keys if key in found]
    picked = ordered[:1] if len(ordered) == 1 else ask(engine, intent, checkpoint_id(engine, "grapple_attempt", target.entity_id), actor, choice_id,
                                                        ordered, labels={k: found[k].display_name for k in ordered}, target_id=target.entity_id,
                                                        prompt=prompt)
    action = found.get(picked[0]) if picked else None
    if action is None:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    save = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "save"), None)
    if save is None:
        return None
    from ..attack_reach import maximum
    # This helper grants one attempt without another action; neither its Save
    # nor a riding effect can create another attack or an Attack action.
    granted = {**typed, 'effects': [save], 'granted_attack': True, 'attack_action_parent': False}
    action = action.model_copy(update={'range_ft': maximum(engine, actor, action, base=action.range_ft or 5),
                                     'parameters': {**action.parameters, 'typed': granted}})
    te.run_effects(te.Context(engine, actor, action, intent, granted, [target], target, {}), [save])
    return picked[0]
