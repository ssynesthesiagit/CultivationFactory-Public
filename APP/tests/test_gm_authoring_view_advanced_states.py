"""The GM-authoring sheet view always exposes a ``state`` for each advanced system.

The Command 4 audits carry acquired rows as a list; the view must not hand
that list to the renderer, which would fall back to "not acquired" while the
Forged Techniques and Immortal Arts tabs list the rows.
"""
from __future__ import annotations

from factory_authoring.service import _advanced_system_state


def test_acquired_rows_project_to_a_present_state_with_names():
    rows = [
        {"record_id": "forged.1", "name": "Unbroken Downburst"},
        {"record_id": "immortal.2", "display_name": "Iron Voice — Binding Immortal Art"},
    ]
    state = _advanced_system_state(rows, present_state="projected", system="immortal arts")
    assert state["state"] == "projected" and state["count"] == 2 and state["source_backed"] is True
    assert state["display_names"] == ["Unbroken Downburst", "Iron Voice — Binding Immortal Art"]
    assert state["note"] == "2 immortal arts: Unbroken Downburst · Iron Voice — Binding Immortal Art"


def test_typed_absence_passes_through_and_missing_value_is_none():
    absence = {"state": "none", "source_backed": True, "reason": "No manuals were selected."}
    assert _advanced_system_state(absence, present_state="acquired", system="recorded arts") == absence
    legacy = {"state": "not_projected", "source_backed": False, "note": "legacy workspace"}
    assert _advanced_system_state(legacy, present_state="projected", system="immortal arts") == legacy
    for empty in (None, [], {}):
        state = _advanced_system_state(empty, present_state="acquired", system="forged techniques")
        assert state["state"] == "none" and state["source_backed"] is False
