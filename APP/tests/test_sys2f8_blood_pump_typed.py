"""SYS2 F8 (lead review CLOUDSYS2F5R, finding 1): Blood Pump compiles from typed data.

The once-per-scene limit must come from the record's typed `use_limit`, and the record's compile must not depend on
the rider prose the branch removed from reviewed_final.d/bodya.json. The one-replacer-per-lethal-hit rule stays with the
generic zero-HP replacer prompt, so nothing here tests it."""

import copy
import json
from pathlib import Path

from combat import factory_compiler as fc

ROOT = Path(__file__).resolve().parents[1]
BLOOD_PUMP = "tianxia.path.body_refining.feature.blood_pump"


def _record() -> dict:
    data = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
    return copy.deepcopy(data["mechanics"][BLOOD_PUMP])


def _compile(record: dict):
    return fc._generic_reaction(BLOOD_PUMP, record, pb=3, numbers={"cl": 15}, primary="body", pools=(),
                                diagnostics=[], free=True)


def test_blood_pump_once_per_scene_is_typed_use_limit_and_compiles_without_rider_prose():
    record = _record()
    assert record.get("riders") == [], "the rider removal stays: Blood Pump must not depend on rider prose"
    assert record.get("use_limit") == "text:once per scene", "the once-per-scene limit must be typed data on the record"
    compiled = _compile(record)
    assert compiled is not None, "Blood Pump must compile from typed data alone (skipped.passive regression)"
    rows, _extra, _choice = compiled
    assert rows[0]["kind"] == "drop_to_zero"
    assert any(effect.get("type") == "hold_at_1hp" for effect in rows[0]["effects"])
    assert any(str(resource).startswith("resource:uses.") for resource, _amount in
               ((cost["resource_id"], cost["amount"]) for cost in rows[0]["costs"])), \
        "the typed use_limit must become the one-use-per-fight counter"


def test_blood_pump_once_per_scene_comes_only_from_the_typed_use_limit():
    record = _record()
    record.pop("use_limit", None)
    compiled = _compile(record)
    assert compiled is not None
    rows, _extra, _choice = compiled
    assert not any(str(cost["resource_id"]).startswith("resource:uses.") for cost in rows[0]["costs"]), \
        "without the typed use_limit there must be no once-per-scene counter"
