"""Reviewed creature-type targets for any owned typed action.

The same data contract serves Soul Hook, Soul Funeral and Command the Unquiet.
Alternatives contain conjunctions of exact, case-insensitive printed labels;
no name, condition, race, immunity or ability implies a creature type. Missing
classification cannot prove eligibility. Unrestricted actions stay unchanged.
"""
from __future__ import annotations

import copy
from typing import Any

from . import hook
from ..creature_types import has_type


@hook("compile_action")
def compile_target_types(action: Any, info: dict[str, Any]) -> Any | None:
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('source')
    if source not in info['owned_ids']:
        return None
    target = ((info.get('mechanics') or {}).get(source) or {}).get('target') or {}
    if not isinstance(target, dict) or not target.get('creature_types_any'):
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters['typed']['target'] = copy.deepcopy(target)
    return action.model_copy(update={'parameters': parameters})


@hook('candidate_allowed')
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or action.owner_id != actor.entity_id:
        return None
    groups = (((action.parameters or {}).get('typed') or {}).get('target') or {}).get('creature_types_any')
    if not groups:
        return None
    for identity in candidate.target_ids:
        target = engine.state.actors.get(identity)
        if target is None or not any(group and all(has_type(target, label) for label in group) for group in groups):
            return False
    return None
