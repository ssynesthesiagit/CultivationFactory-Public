"""TEMPORARY debug probe (MAINREDREACT1): print the reaction context that makes a table act ask."""
import json

import tests.test_mmx114_zone_inside_text as Z


def test_debug_mmx114_darkness_cast(tmp_path):
    combat, table, mid = Z.match(tmp_path / "zones", [Z.DARKNESS, Z.PURE])
    shape = Z._press(table, mid, "Shape Darkness: Pure Darkness")
    cast = Z._press(table, mid, "Darkness")
    assert cast["status"] == "COMMITTED", json.dumps(
        {"shape": shape["status"], "cast": cast["status"],
         "reaction": cast.get("reaction")}, indent=1, default=str)[:6000]


def test_debug_sovereign_dodge(tmp_path):
    import tests.test_r2i_sovereign_forms as F
    combat, table, mid = F.table_fixture(tmp_path / "sov")
    result = F.I.act(combat, table, mid, "Dodge")
    assert result["status"] == "COMMITTED", json.dumps(
        result.get("reaction"), indent=1, default=str)[:6000]
