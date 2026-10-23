"""Printed ability light inventory and S3 source-shape regression."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_light_source_inventory_matches_printed_authority_and_has_valid_radii():
    rows = json.loads((ROOT / "combat/rules/light_sources.json").read_text())["sources"]
    authority = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert len(rows) == 17  # the spec table enumerates 16; Radiant Fist is an additional printed entry.
    assert len({row["mechanic"] for row in rows}) == len(rows)
    for row in rows:
        text = authority[row["mechanic"]]
        assert row["name"].lower() in text.lower() or row["mechanic"] in text
        assert type(row["bright_ft"]) is int and type(row["dim_ft"]) is int
        assert 0 <= row["bright_ft"] <= row["dim_ft"]
        assert row["follows"] in {"self", "zone", "target", "targets", "summon"}
        assert f'{row["bright_ft"]}-foot' in text or f'{row["bright_ft"]} ft' in text or row["bright_ft"] == 0
        assert f'{row["dim_ft"]}-foot' in text or f'{row["dim_ft"]} ft' in text or row["dim_ft"] == row["bright_ft"]


def test_heavenly_radiance_printed_bright_radius_is_120():
    rows = {row["mechanic"]: row for row in json.loads(
        (ROOT / "combat/rules/light_sources.json").read_text())["sources"]}
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["bright_ft"] == 120
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["dim_ft"] == 240


def test_wick_body_light_has_no_dim_ring():
    import ast

    source = (ROOT / "combat/ext/wax_reactions.py").read_text()
    assert '"bright_ft": LIGHT_RADIUS_FT, "dim_ft": LIGHT_RADIUS_FT' in source
