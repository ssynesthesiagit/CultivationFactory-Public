"""Shared Spotlight: Adorn the Moment on yourself and one willing ally (Beauty; rider lane C10, 2026-09-30).

Owner text (tianxia.talent.beauty.shared_spotlight): "When you use Adorn the Moment, you may affect yourself and one willing ally
within 30 feet. The ally's benefit must be the same kind of presentation: graceful, radiant, tragic, terrifying, courtly, solemn,
or another shared aesthetic."

How it runs: each Adorn the Moment option the owner has (check, memory, and all eight auras) gets a
sibling "Adorn the Moment + Shared Spotlight: <option>" aimed at an ally within 30 feet (not yourself): the option's own effects
land on that ally and on you, so both get the same benefit (the same kind of presentation). Using the plain option on yourself
alone stays available ("you may"). Only owners of Shared Spotlight get the siblings.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook
from .beauty_adorn_base import aura_choices, willing_delivery

SHARED = "tianxia.talent.beauty.shared_spotlight"
ADORN = "BEAUTY_BASE_ADORN_THE_MOMENT"
KEY = "shared_spotlight"


@hook("compile_actions")
def spotlight(info: dict[str, Any]) -> list[Any] | None:
    if not {SHARED, ADORN}.issubset(info.get("owned_ids") or []):
        return None
    out = []
    for action in [*(info.get("actions") or []), *(aura_choices(info) or [])]:
        typed = (action.parameters or {}).get("typed") or {}
        if typed.get("option_of") != ADORN or typed.get("variant_of") or "+" in action.source_definition_id:
            continue
        mine = copy.deepcopy(typed.get("effects") or [])
        theirs = willing_delivery(mine, 30)
        own = {"type": "adorn_self", "effects": copy.deepcopy(mine)}
        label = str(typed.get("option_label") or "Adorn the Moment")
        benefits = {
            "Advantage on Check": "Each target gains Advantage on its next Charisma (Performance or Persuasion), Dexterity (Acrobatics), "
                                  "or Wisdom (Insight) check within 1 minute, if it depends on grace, poise, first impressions, etiquette, "
                                  "dance, beauty, or emotional presentation. A creature can benefit from this option only once per scene.",
            "Visually Memorable": "For 1 minute, each target becomes visually memorable. Creatures that see it during that minute "
                                  "have Advantage on checks to remember or identify it later.",
        }
        if label.endswith(' aura'):
            benefits[label] = (f"Both creatures gain the same {label.lower()} for 1 minute. "
                               "No direct combat effect; social possibilities depend on the actual scene.")
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}.{KEY}", "display_name": f"Adorn the Moment + Shared Spotlight: {label}",
            "target_kind": "ALLY_OR_SELF", "range_ft": 30,
            "parameters": {**action.parameters, KEY: True,
                           "typed": {**typed, "effects": [theirs, own], "range_ft": 30,
                                     "manual_inline_choice": True,
                                     "evidence": "you may affect yourself and one willing ally within 30 feet"},
                           "description": f"Spend a Bonus Action (0 CP) on Adorn the Moment ({label}) for yourself and one willing ally within 30 feet, "
                                          "with the same presentation. " + benefits.get(label, str(action.parameters.get("description") or ""))
                                          + " Each creature can benefit from only one use of Adorn the Moment at a time."}}))
    return out or None


@hook("candidate_allowed")
def an_ally(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get(KEY):
        return None
    return False if actor.entity_id in (getattr(candidate, "target_ids", ()) or ()) else None
