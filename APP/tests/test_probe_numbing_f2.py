"""Probe (VARIANTS21F2): what the compiler emits for the Darkness owner's Shape/Numbing rows."""
import json
from combat.factory_compiler import compile_character
from tests.option_tooltip_support import OWNER, sheet


def test_probe_numbing_rows():
    bundle = compile_character(sheet(), actor_id=OWNER)
    rows = bundle["action_catalog"]
    darkness = sorted({(r["display_name"], r["source_definition_id"]) for r in rows if "Darkness" in r["display_name"] or "Shape" in r["display_name"]})
    numbing = [(r["display_name"], r["source_definition_id"], sorted((r.get("parameters") or {}).keys())) for r in rows if "Numbing" in json.dumps(r.get("parameters") or {})]
    assert False, json.dumps({"darkness": darkness, "numbing": numbing[:20]}, indent=1)
