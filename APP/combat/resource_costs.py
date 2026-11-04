"""Read shared resource-cost rows in either persisted pair or typed-dictionary form.

Decision text and extension policy hooks both consume compiled cost rows.
"""
from __future__ import annotations

from typing import Any


def parts(cost: Any) -> tuple[Any, Any]:
    """Return (resource id, amount) from a persisted pair or typed cost mapping."""
    if isinstance(cost, (tuple, list)):
        return (cost[0], cost[1]) if len(cost) >= 2 else (None, None)
    if isinstance(cost, dict):
        return cost.get("resource_id"), cost.get("amount")
    return None, None


def as_dict(cost: Any) -> dict[str, Any]:
    """Normalize a cost row for consumers whose policy hooks use typed mappings."""
    if isinstance(cost, dict):
        return cost
    resource, amount = parts(cost)
    return {"resource_id": resource, "amount": amount}
