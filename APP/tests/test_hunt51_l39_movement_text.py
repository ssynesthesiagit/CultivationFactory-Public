"""Service regression for hunt 51 finding 6: movement quotes and dragged-move history."""
from tests.test_hunt51_l39 import IDS, _act, _finish, _fight, _on_turn


def test_drag_quote_and_history_report_real_movement(tmp_path):
    user, service, table, match = _fight(tmp_path, "drag-text", [
        {"material": "terrain:fire terrain", "cells": [[3, 2], [3, 4], [2, 2], [2, 4]]}])
    trace = []
    _on_turn(table, match, IDS[0], trace)
    _act(table, match, lambda option: "Grapple" in str(option.get("label")) and option.get("target_ids") == [IDS[2]], trace)
    menu = table.state(match)["menu"]
    chosen = next(option for option in menu["moves"] if option.get("destination") == {"x": 2, "y": 3})
    assert chosen["cost_ft"] == 10
    _act(table, match, lambda option: option.get("destination") == {"x": 2, "y": 3}, trace)
    engine, history = _finish(user, service, table, match)
    source_move = next(event for event in engine.events if event.event_type == "MOVEMENT_COMMITTED"
                       and event.actor_id == IDS[0] and event.payload.get("destination") == {"x": 2, "y": 3})
    assert chosen["cost_ft"] == source_move.payload["cost_ft"] == 10
    dragged = next(row for row in history["events"] if row.get("event_type") == "MOVEMENT_COMMITTED"
                   and row.get("actor_id") == IDS[2])
    assert "dragged by First Grappler" in dragged["summary"]
    assert "(0 ft)" not in dragged["summary"]


def test_forced_history_names_force_and_omits_cost_as_distance(tmp_path):
    user, service, table, match = _fight(tmp_path, "forced-history")
    trace = []
    _on_turn(table, match, IDS[0], trace)
    _act(table, match, lambda option: "Shove: Push 5 ft" in str(option.get("label")) and option.get("target_ids") == [IDS[2]], trace)
    _, history = _finish(user, service, table, match)
    dragged = next(row for row in history["events"] if row.get("event_type") == "MOVEMENT_COMMITTED"
                   and row.get("actor_id") == IDS[2])
    assert "moved by force" in dragged["summary"]
    assert "First Grappler" not in dragged["summary"]
