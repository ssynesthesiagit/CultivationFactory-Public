"""World-Breaking Rampage retains both its object damage and printed exclusions."""
import json

from tests import test_auto70_berserker as B


def test_rampage_has_one_declaration_with_object_damage_and_all_exclusions():
    feature = "TAL_BERSERKER_WORLD_BREAKING_RAMPAGE"
    declarations = [json.loads(path.read_text())["features"][feature]
                    for path in (B.ROOT / "combat/rules/feature_blocks.d").glob("*.json")
                    if feature in json.loads(path.read_text()).get("features", {})]
    assert len(declarations) == 1
    spec = declarations[0]
    assert spec["block"] == "object_damage"
    assert spec["double"] and spec["double_for"] == ["unattended"]
    assert spec["covers"] == ["World-Breaking Rampage does not automatically destroy: artifacts;",
                              "Formation cores;", "Domains;", "Realm-defining structures."]
    engine = B._fight([feature])
    rows = [row for row in engine.typed_passive_rows[B.ME] if row.get("feature_id") == feature]
    assert len(rows) == 1 and rows[0]["block"] == "object_damage"
    assert rows[0]["double_for"] == spec["double_for"]
    assert any(action.parameters.get("typed", {}).get("source") == feature
               for action in engine.action_catalog.values())
