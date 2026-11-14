"""Synthetic catalogue installation for option, status and sheet display checks.

Feeds both the shared record-card source and the printed-evidence reader; the
real compiler, table services and persistence remain unchanged.
"""
import json


def install_display_rules(tmp_path, monkeypatch, rules):
    from combat import status_text
    from factory_authoring import record_display
    from factory_authoring.player_rules import build_player_text

    data = tmp_path / "display"
    data.mkdir()
    for name, value in {
        "rules_text.json": rules,
        "player_text.json": build_player_text(rules, {}),
        "owner_text_edits.json": {"records": {}},
        "record_sections.json": {},
    }.items():
        (data / name).write_text(json.dumps(value))
    monkeypatch.setattr(record_display, "DATA", data)
    monkeypatch.setattr(record_display, "SECTIONS", data / "record_sections.json")
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", data / "rules_text.json")
