"""Evented instance removal shared by Scoundrel and lane 14 Eye plugins."""
from typing import Any


def drop_condition(engine: Any, creature: Any, instance_id: str, source: str) -> None:
    """Remove precisely one condition instance and retain its replay identity."""
    condition = creature.conditions.pop(instance_id, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id,
                             target_ids=(creature.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": instance_id,
                                      **({"removed_condition": condition.model_dump(mode="json")}
                                         if condition.data.get("retain_removal_data") else {})})
