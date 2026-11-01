"""Evented instance removal shared by Scoundrel and lane 14 Eye plugins."""
from typing import Any


def drop_condition(engine: Any, creature: Any, instance_id: str, source: str) -> None:
    """Remove precisely one condition instance and retain its replay identity."""
    engine._remove_condition_instance(creature, instance_id, source)
