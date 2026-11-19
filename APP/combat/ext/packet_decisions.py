"""Shared helper correlating accepted attack decisions with their native packet.

Merciful Hand records its accepted choice here for Iron Marrow's later damage
floor; the explicit attack roll id keeps separate packets independent.
"""
from __future__ import annotations

from typing import Any


def recorded_for_packet(engine: Any, source_id: str, target_id: str, roll_id: str) -> bool:
    """Whether this source accepted a choice for this exact target and attack roll."""
    return any(event.event_type == "PASSIVE_TRIGGERED"
               and event.source_definition_id == source_id
               and target_id in event.target_ids
               and (event.payload or {}).get("attack_roll_id") == roll_id
               for event in reversed(engine.events))
