"""A manual given at the table is listed on the owner sheet beside the sealed ones (owner 2026-09-29: Tabik's Clearsight
manual was in his fights but on no sheet). combat/tabletop_service.py table_manuals; static/app.js ownerManualRows."""

import json

from combat.tabletop_service import TabletopService

PID = "0badc0de-0000-4000-8000-000000000002"
MANUAL = {"id": "table.manual.dark_gate_clearsight", "name": "Dark Gate School — Clearsight",
          "talents": ["TAL_DARK_CLEARSIGHT", "TAL_DARK_LOOMING_DARKNESS", "TAL_DARK_SNAGGING_DARKNESS"], "cl": 10,
          "at": "2026-09-28T00:50:13+00:00", "gm": False}


def test_a_table_manual_is_listed_with_its_recorded_arts(tmp_path):
    service = TabletopService(None, tmp_path)
    (tmp_path / "tabletop_buttons").mkdir()
    (tmp_path / "tabletop_buttons" / f"{PID}.json").write_text(json.dumps(
        {"schema": "TianxiaSheetButtons.v1", "buttons": [], "advancement": {"manuals": [MANUAL]}}), encoding="utf-8")
    [row] = service.table_manuals(PID)
    assert row["display_name"] == "Dark Gate School — Clearsight" and row["status"] == "Given at the table"
    assert [art["display_name"] for art in row["recorded_arts"]] == ["Clearsight", "Looming Darkness", "Snagging Darkness"]
    assert all(art["parent_manual_record_id"] == row["record_id"] for art in row["recorded_arts"])
    assert "immune to negative effects created by your Darkness talents" in row["recorded_arts"][0]["full_description"]
    assert len(row["summary"]) <= 160  # the sheet shows it as the card's one-line summary


def test_no_table_manuals_is_an_empty_list(tmp_path):
    assert TabletopService(None, tmp_path).table_manuals(PID) == []
