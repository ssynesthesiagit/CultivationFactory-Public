"""Recipient data must be derived before an effect reaches execution."""
import copy
import json
from types import SimpleNamespace

import pytest

from combat import typed_executor as te
from factory_authoring.effect_subjects import derive_effect_subjects, require_subjects


@pytest.mark.parametrize(
    ("reader", "effect", "missing"),
    [
        (te.save_subjects, {"type": "save"}, "area_scope"),
        (te.save_subjects, {"type": "save", "subjects": {}}, "exclude_self"),
        (te.save_subjects, {"type": "save", "subjects": {"area_scope": None}}, "exclude_self"),
        (te._allies_near, {"type": "healing", "applies_to": "ally"}, "count"),
        (te._allies_near, {"type": "healing", "applies_to": "ally", "subjects": {}}, "within_ft"),
        (te._allies_near, {"type": "healing", "applies_to": "ally", "subjects": {"count": "all", "within_ft": None}}, "or_self"),
    ],
)
def test_missing_subject_fields_fail_with_effect_and_source(reader, effect, missing):
    ctx = SimpleNamespace(source="synthetic.source")
    with pytest.raises(ValueError, match=rf"{effect['type']}.*synthetic.source.*{missing}"):
        reader(ctx, effect)


def test_derivation_marks_nonrecipient_and_rejects_incomplete_authored_subjects():
    effect = {"type": "damage", "damage_types": ["fire"]}
    authored = {"type": "damage", "subjects": {}}
    derive_effect_subjects([effect, authored])
    assert "subjects" in effect and effect["subjects"] is None
    assert authored["subjects"] == {}
    for row in ({"type": "save", "subjects": {}},
                {"type": "speed", "applies_to": "ally", "subjects": {"count": "one"}}):
        with pytest.raises(ValueError, match=rf"{row['type']}.*synthetic.source.*subjects"):
            derive_effect_subjects({"mechanic_id": "synthetic.source", "effects": [row]})
    complete = {"type": "save", "subjects": {"area_scope": None, "exclude_self": False}}
    derive_effect_subjects(complete)
    assert complete["subjects"] == {"area_scope": None, "exclude_self": False}

def test_feature_block_recipients_are_sealed_at_compile(monkeypatch):
    from combat import typed_reactions
    from combat.on_hit_data import walk_effect_containers

    def recipients(value):
        return [row for row in walk_effect_containers(value)
                if row.get("type") == "save" or row.get("applies_to") == "ally"]

    def compile_feature(source):
        return typed_reactions.compile_blocks(
            [source], pb=2, key_mod=3, saves={}, resource_ids={}, mechanics={},
        )

    root = typed_reactions.RULES_PATH
    paths = [root, *sorted((root.parent / "feature_blocks.d").glob("*.json"))]
    checked = 0
    for path in paths:
        for source, spec in json.loads(path.read_text(encoding="utf-8"))["features"].items():
            authored = recipients(spec)
            if not authored:
                continue
            cached = copy.deepcopy(typed_reactions.rules()["features"][source])
            compiled = recipients(compile_feature(source))
            assert len(compiled) >= len(authored), (path, source)
            for row in compiled:
                require_subjects(row, source)
            for row in authored:
                expected = copy.deepcopy(row)
                derive_effect_subjects(expected, source)
                assert expected in compiled, (path, source, row)
                checked += 1
            assert typed_reactions.rules()["features"][source] == cached
    assert checked, "no feature-block save or ally effects were checked"

    # Future blocks can author recipients explicitly or provide text for an ally;
    # compilation must not mutate the cached rules or replace authored values.
    source = "synthetic.feature"
    spec = {"block": "granted_action", "action": {"effects": [
        {"type": "save", "subjects": {"area_scope": "creatures_in_area", "exclude_self": True}},
        {"type": "speed", "applies_to": "ally", "evidence": "one ally within 10 feet"},
    ]}}
    original = copy.deepcopy(spec)
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": {source: spec}})
    rows = recipients(compile_feature(source))
    assert rows[0]["subjects"] == {"area_scope": "creatures_in_area", "exclude_self": True}
    assert rows[1]["subjects"] == {"count": "one", "within_ft": 10, "or_self": False}
    assert spec == original
    spec["action"]["effects"][0]["subjects"] = {}
    with pytest.raises(ValueError, match=r"save.*synthetic.feature.*subjects"):
        compile_feature(source)


def test_jester_passes_ally_selector_through_table_commit_and_reload(tmp_path, monkeypatch):
    from tests.cw2_service_support import add_action
    from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

    observed = []
    original = te._default_subject

    def record(ctx, effect, *, harmful):
        observed.append(dict(effect))
        return original(ctx, effect, harmful=harmful)

    monkeypatch.setattr(te, "_default_subject", record)

    def setup(bundles):
        add_action(bundles[0], "Synthetic Fluster", [{
            "type": "flustered", "applies_to": "ally",
            "evidence": "one ally within 10 feet",
        }], target="ALLY_OR_SELF")

    combat, table, mid = fixture(tmp_path, [], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, "Synthetic Fluster", target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(condition.condition_id == "condition:typed.flustered"
               for condition in engine.state.actors[ALLY].conditions.values())
    assert all(not any(condition.condition_id == "condition:typed.flustered"
                       for condition in engine.state.actors[actor].conditions.values())
               for actor in (OWNER, FOE))
    assert any(row.get("type") == "flustered" and row.get("subjects") == {
        "count": "one", "within_ft": 10, "or_self": False,
    } for row in observed)


def test_destruction_wrapper_requires_its_own_subject_seal():
    from combat.ext.destruction_blast import shape_save

    with pytest.raises(ValueError, match=r"destruction_shape_save.*synthetic.source.*subjects"):
        shape_save(SimpleNamespace(source="synthetic.source"), {"type": "destruction_shape_save"})
