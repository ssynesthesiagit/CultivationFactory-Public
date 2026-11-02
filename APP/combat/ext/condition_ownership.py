"""Shared exact-instance cleanup for next-damage, next-attack and Overstrain riders.

These consumers refresh only their caster's conditions. Consumption removes the
selected instance, preserving independent instances belonging to other casters.
Events use the engine's ordinary CONDITION_REMOVED payload for replay.
"""
from typing import Any


def remove_instance(engine: Any, target: Any, instance_id: str, source: str) -> None:
    engine._remove_condition_instance(target, instance_id, source)


def refresh_owned(engine: Any, target: Any, name: str, owner_id: str, source: str) -> None:
    for iid, held in list(target.conditions.items()):
        if held.condition_id == name and held.source_actor_id == owner_id:
            remove_instance(engine, target, iid, source)
