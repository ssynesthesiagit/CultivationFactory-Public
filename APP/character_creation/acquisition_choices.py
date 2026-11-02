"""Source-defined acquisition choices, shared by builder and combat compilation.

Choices are owner input, not grants. A sealed project snapshot transports them;
the consumer must independently verify that the character acquired the feature.
"""
import json
from pathlib import Path

from app.core import FoundryError
from character_creation.choice_snapshot import valid_choice_snapshot

FIELD = "character.choices.acquisition"
DEFINITIONS = Path(__file__).resolve().parents[1] / "combat/rules/acquisition_choices.json"


def definitions():
    return json.loads(DEFINITIONS.read_text())


def validate(selected_record_ids, selections, *, require_complete=True):
    """Validate exact options for selected parents; never choose for an owner."""
    offered = {key: row for key, row in definitions().items()
               if row["parent_id"] in selected_record_ids}
    supplied = selections or {}
    if not isinstance(supplied, dict) or set(supplied) - set(offered):
        raise FoundryError("ACQUISITION_CHOICE_UNOWNED", "Choose only for a selected feature.")
    missing = [row for key, row in offered.items() if key not in supplied]
    if require_complete and missing:
        raise FoundryError("ACQUISITION_CHOICE_REQUIRED", "Choose the feature's starting option before acquiring it.",
                           details={"choices": missing})
    for key, value in supplied.items():
        if not isinstance(value, str) or value not in offered[key]["options"]:
            raise FoundryError("ACQUISITION_CHOICE_INVALID", "Choose one of the printed options.", details={"choice": offered[key]})
    return dict(supplied)


def from_sheet(sheet):
    """Read choices only from a valid sealed builder snapshot, not loose metadata."""
    snapshot = (sheet.get("advancement_history") or {}).get("typed_choice_snapshot") or {}
    if not valid_choice_snapshot(snapshot):
        return {}
    rows = [row.get("value") for row in snapshot.get("typed_locks", []) if row.get("field") == FIELD]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return {}
    parents = [row["parent_id"] for row in definitions().values()]
    return validate(parents, rows[0], require_complete=False)


def for_acquisition(project, parent_id):
    """Bind a native acquisition event to its already recorded owner choices.

    Also covers a parent proposed after blueprint creation: missing input blocks
    the grant and presents the exact choices instead of inventing a default.
    Other parents' choices are neither granted nor copied into this event.
    """
    wanted = {key for key, row in definitions().items() if row["parent_id"] == parent_id}
    if not wanted:
        return {}
    rows = [row.get("value") for row in project.get("user_locks", []) if row.get("field") == FIELD]
    values = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    return validate([parent_id], {key: values[key] for key in wanted if key in values})
