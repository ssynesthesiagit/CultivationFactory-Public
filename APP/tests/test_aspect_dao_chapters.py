"""Numbered Dao catalogue profiles retain their Aspect IDs across heading changes."""
from tools import build_sphere_dao_authority as builder
from tools.aspect_terms import aspect_terms


def test_renamed_dao_markers_keep_profiles_and_retired_entries(tmp_path, monkeypatch):
    original = builder.build()
    renamed_markers = tmp_path / builder.MARKERS.name
    renamed_markers.write_text(aspect_terms(builder.MARKERS.read_text(encoding="utf-8")), encoding="utf-8")
    assert "Way of Fire" in renamed_markers.read_text(encoding="utf-8")
    monkeypatch.setattr(builder, "MARKERS", renamed_markers)
    changed = builder.build()

    assert changed["spheres"].keys() == original["spheres"].keys()
    assert changed["spheres"]["tianxia.sphere.fire"]["source_names"]["marker_catalogue"] == "Way of Fire"
    assert changed["retired_owner_profiles"].keys() == original["retired_owner_profiles"].keys()
    assert "Fencing" in changed["retired_owner_profiles"]
    for sphere_id, before in original["spheres"].items():
        after = changed["spheres"][sphere_id]
        assert after["status"] == before["status"]
        for key in ("natural_trigrams", "testing_trigrams", "shadow_trigrams"):
            assert after[key] == before[key]
