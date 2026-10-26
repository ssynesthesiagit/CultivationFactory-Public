"""Review-page preview groups compiled Talents by their catalog Sphere."""

from __future__ import annotations

from app.api import _bounded_owner_scratch_sheet


def test_preview_talents_carry_the_sheet_supplied_sphere_name() -> None:
    compiled = {
        "owner_character_sheet": {
            "identity": {"name": "Test"},
            "selected_record_sections": {
                "Talents": [
                    {"record_id": "talent.swift_movement", "display_name": "Swift Movement", "acquisition_cl": 1},
                    {"record_id": "talent.unmapped", "display_name": "Unmapped Talent", "acquisition_cl": 2},
                ],
            },
        },
        "talent_sphere_names": {"talent.swift_movement": "Athletics"},
    }
    sheet = _bounded_owner_scratch_sheet(compiled)
    by_name = {row["name"]: row for row in sheet["talents"]}
    assert by_name["Swift Movement"]["sphere"] == "Athletics"
    assert "sphere" not in by_name["Unmapped Talent"]
