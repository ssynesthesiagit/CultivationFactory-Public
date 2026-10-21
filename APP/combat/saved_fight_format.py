"""Saved-data validation, independent of engine and controller source files.

The current typed models, journal hashes and match-local input checks decide
whether a fight can continue. No code fingerprint, approval or migration is
involved. Unsupported files are left in place for explicit owner deletion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


UNSUPPORTED_CODE = "COMBAT_SAVED_FIGHT_UNSUPPORTED"
UNSUPPORTED_MESSAGE = (
    "This fight was saved with an older version and can't continue — start a new one"
)
T = TypeVar("T", bound=BaseModel)


class UnsupportedSavedFight(ValueError):
    """The saved data cannot be interpreted safely by this version."""

    code = UNSUPPORTED_CODE

    def __init__(self, reason: str):
        super().__init__(UNSUPPORTED_MESSAGE)
        self.reason = reason


def read_saved_json(path: Path) -> Any:
    """Read a regular saved JSON file without following links or changing it."""
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("required saved document is not a regular file")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise UnsupportedSavedFight(f"{path.name}: {exc}") from exc


def read_saved_model(path: Path, model: type[T]) -> tuple[dict[str, Any], T]:
    """Parse a required saved document without modifying any saved bytes."""
    document = read_saved_json(path)
    try:
        value = model.model_validate(document)
    except ValidationError as exc:
        raise UnsupportedSavedFight(f"{path.name}: {exc}") from exc
    return document, value


def saved_targeting_policy(events) -> dict[str, int]:
    """Read explicit fight settings; never infer them from old executable hashes."""
    from .targeting import POLICY_KEYS

    for event in reversed(events):
        row = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
        if not isinstance(row, dict):
            raise UnsupportedSavedFight("A saved event is not an object.")
        if row.get("event_type") != "MATCH_CREATED":
            continue
        payload = row.get("payload")
        policy = payload.get("targeting_policy") if isinstance(payload, dict) else None
        if (not isinstance(policy, dict) or set(policy) != set(POLICY_KEYS)
                or any(type(policy[key]) is not int or not 0 <= policy[key] <= 100
                       for key in POLICY_KEYS)):
            raise UnsupportedSavedFight("The saved targeting settings are missing or invalid.")
        return dict(policy)
    raise UnsupportedSavedFight("The fight has no creation event with saved targeting settings.")


def validate_saved_policies(events) -> None:
    """Use the ordinary policy readers before recovery can write saved data."""
    from . import ai_search, area_knowledge, knowledge_policy, terrain_occlusion

    saved_targeting_policy(events)
    try:
        terrain_occlusion.saved_policy(events)
        ai_search.saved_policy(events)
        knowledge_policy.saved_policy(events)
        if area_knowledge.saved_policy(events):
            area_knowledge.saved_origin_permissions(events)
    except (ValueError, KeyError, TypeError) as exc:
        raise UnsupportedSavedFight(f"The saved fight settings are invalid: {exc}") from exc
