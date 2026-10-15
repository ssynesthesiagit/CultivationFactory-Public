"""A finished character's name at the table and in fights (owner 2026-09-27: "Lingfeng Xi isnt an option on the table"
-- the rename was saved while the character was being finalized and never reached it)."""

import json
import zipfile
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore

APP = Path(__file__).resolve().parents[1]
PID = "93be0568-e62d-45ee-8ab8-74a3aa22e8a7"


def test_the_table_name_replaces_the_sheet_name_everywhere_combat_reads_it(tmp_path):
    package = tmp_path / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps({"identity": {"display_name": "Lingfeng Ironroot"}}))
    service = CombatService(APP, tmp_path)
    assert service._factory_owner_sheet(PID)["identity"]["display_name"] == "Lingfeng Ironroot"
    assert [row["display_name"] for row in service.factory_characters()] == ["Lingfeng Ironroot"]
    ButtonStore(tmp_path / "tabletop_buttons").save_display_name(PID, "  Lingfeng   Xi ")
    assert service._factory_owner_sheet(PID)["identity"]["display_name"] == "Lingfeng Xi"
    assert [row["display_name"] for row in service.factory_characters()] == ["Lingfeng Xi"]  # the cached row follows
    ButtonStore(tmp_path / "tabletop_buttons").save_display_name(PID, "")
    assert service._factory_owner_sheet(PID)["identity"]["display_name"] == "Lingfeng Ironroot"
