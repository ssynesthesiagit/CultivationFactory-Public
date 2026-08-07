from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core import sha256_json
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD


SCHEMA = "TianxiaFoundry.TypedProjectChoiceSnapshot.v1"


def materialize_choice_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    """Freeze committed project choices without turning display text into identity."""
    content_lock = project.get("content_lock") or {}
    event_stream = project.get("event_stream") or {}
    locks = [
        {
            key: deepcopy(lock.get(key))
            for key in ("lock_id", "field", "value", "value_type", "source", "created_revision")
            if key in lock
        }
        for lock in sorted(
            (
                lock
                for lock in project.get("user_locks", [])
                if isinstance(lock, dict)
                # This is a server-derived acceptance artifact, not a new
                # owner choice.  It is materialized after the response is
                # accepted and must not make the frozen owner-choice binding
                # stale during scratch/final compilation.
                and lock.get("field") != DELEGATED_FINAL_CATALOG_GRANT_FIELD
            ),
            key=lambda lock: (str(lock.get("field") or ""), str(lock.get("lock_id") or "")),
        )
    ]
    unsigned = {
        "schema": SCHEMA,
        "canonical_project_id": project["project_id"],
        "project_revision": int(project.get("revision") or 0),
        "content_lock_hash": str(content_lock.get("lock_hash") or project.get("content_lock_hash") or ""),
        "event_stream": {
            "count": int(event_stream.get("count") or 0) if isinstance(event_stream, dict) else 0,
            "head_hash": event_stream.get("head_hash") if isinstance(event_stream, dict) else None,
        },
        "display_name_content": str(project.get("working_name") or ""),
        "typed_locks": locks,
    }
    return {**unsigned, "snapshot_sha256": sha256_json(unsigned)}


def valid_choice_snapshot(snapshot: dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        return False
    seal = snapshot.get("snapshot_sha256")
    return isinstance(seal, str) and seal == sha256_json(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    )
