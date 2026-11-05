"""Sect Check's automated after-roll decision must not be presented as a GM rider."""
import json
from pathlib import Path


def test_sect_check_has_no_obsolete_after_roll_rider():
    authority = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    record = json.loads(authority.read_text())["mechanics"]["SECT_STEWARDSHIP_BASE_SECT_CHECK"]
    assert record["riders"] == []
    assert any(effect["type"] == "sect_check" for effect in record["effects"])
