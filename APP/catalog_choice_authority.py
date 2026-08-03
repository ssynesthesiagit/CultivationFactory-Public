from __future__ import annotations

from copy import deepcopy
from typing import Any


COMMITTED_CATALOG_CHOICE_FIELD = "character_creation.committed_catalog_choice_plan"
LEGACY_CATALOG_GRANT_FIELD = "character_sheet.canonical_grant_plan"


def committed_catalog_grant_plan(project: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve an immutable typed grant plan without reinterpreting priorities."""
    by_field = {
        lock.get("field"): lock.get("value")
        for lock in project.get("user_locks", [])
        if isinstance(lock, dict)
    }
    value = by_field.get(COMMITTED_CATALOG_CHOICE_FIELD)
    if value is None:
        value = by_field.get(LEGACY_CATALOG_GRANT_FIELD)
    return deepcopy(value) if isinstance(value, dict) else None
