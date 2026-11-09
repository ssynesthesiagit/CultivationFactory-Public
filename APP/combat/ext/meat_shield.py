"""Compatibility access to the single Meat Shield implementation in mount_guard.

No effects, actions or redirect hooks register here: both automation lanes use
the same mounted state, edge geometry and redirection provider.
"""
from __future__ import annotations

from typing import Any

from . import mount_guard, shield_faces

ABILITY = mount_guard.KEY
COVER = mount_guard.SHIELD
END = "meat_shield.end"
held = mount_guard.held
available = mount_guard.available
raise_cover = mount_guard.activate_cover
reactive = mount_guard.meat_shield
candidates = mount_guard.offered


def stops(engine: Any, actor: Any, ray: dict[str, Any]) -> bool:
    edge = mount_guard.edge_of(engine, actor)
    return bool(edge and shield_faces.enters(ray, edge, list(engine._actor_cells(actor))))


def defensive_rider(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    return mount_guard.defensive_allowed(engine, actor, row)
