"""Shared helper module (consumers: states.py, rider_damage_states.py, wrestling.py).
Exact source-owned condition removal used by states, links, damage riders and Choke Hold.

Unlike the engine's condition-name removal, preserve other casters and emit
the ordinary removal event for every removed instance.
"""
from typing import Any


def remove_conditions(engine: Any, holder: Any, source: str, owner: str,
                      condition_id: str | None = None, *, reason: str = "REPLACED") -> None:
    for iid, condition in list(holder.conditions.items()):
        if condition.source_definition_id != source or condition.source_actor_id != owner:
            continue
        if condition_id is not None and condition.condition_id != condition_id:
            continue
        holder.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", source, actor_id=owner,
                             target_ids=(holder.entity_id,), payload={"condition_id": condition.condition_id,
                                                                     "instance_id": iid, "reason": reason})
