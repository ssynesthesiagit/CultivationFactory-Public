"""Scratch diagnostic for the Pure Darkness candidate; deleted before commit."""
import json
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")


def test_diag_e11_candidates(tmp_path):
    doc = sheet(["DARK_BASE_DARKNESS", "TAL_DARK_PURE_DARKNESS"], cl=15, name="x")
    bundle = compile_character(doc, actor_id="actor:factory.x")
    shapes = [r["display_name"] for r in bundle["action_catalog"] if "Shape" in r["display_name"] or "Darkness" in r["display_name"]]
    raise AssertionError("DIAG " + json.dumps({"sphere": doc.get("spheres_and_talents"), "rows": shapes})[:2400])
