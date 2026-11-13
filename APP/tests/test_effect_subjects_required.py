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

    # Summon creature data is another authoring source, including copied
    # specials, hit effects, innate reactions and compile_summon additions.
    from combat import summons

    table = summons.rules()
    original_table = copy.deepcopy(table)
    monkeypatch.setattr(summons, "rules", lambda: table)

    def compile_creatures(ids, *, mechanics=None, plan=None):
        bundles, _ = summons.compile_summons(
            ids, mechanics or {}, owner_id="actor:test", short="test",
            numbers={"key_mod": 3, "attack_bonus": 5, "save_dc": 13},
            pb=4, cl=5, plan=plan,
        )
        assert bundles, ids
        for bundle in bundles:
            for row in walk_effect_containers(bundle):
                if "type" in row or row.get("applies_to") == "ally":
                    require_subjects(row, str(bundle["summon"]["source"]))
        return bundles

    checked = 0
    for source, spec in table["sources"].items():
        if "creature" not in spec:
            continue
        ids = [spec.get("ability") or source, *(spec.get("requires") or [])]
        if spec["creature"] == "corpse_servant":
            ids.append("TAL_DEATH_DEATHLESS_GUARD")
        bundles = compile_creatures(ids)
        group = spec.get("group") or spec["creature"]
        matching = [bundle for bundle in bundles if bundle["summon"]["group"] == group]
        assert matching, source
        compiled = recipients(matching[0])
        for row in recipients(table["creatures"][spec["creature"]]):
            expected = copy.deepcopy(row)
            derive_effect_subjects(expected, source)
            assert expected in compiled, (source, row)
            checked += 1
    assert checked >= 3, "the authored Chain Clone saves were not checked"

    for beast, spec in table["beasts"].items():
        bundles = compile_creatures(
            ["synthetic.tamer"], mechanics={"synthetic.tamer": {"name": "Beast Tamer"}},
            plan={"beasts": [beast]},
        )
        assert any(bundle["summon"]["group"] == f"beast0.{beast}" for bundle in bundles)
        if spec.get("mountable"):
            bundles = compile_creatures(["BEASTMASTERY_BASE_RIDER_PACKAGE"], plan={"mount": beast})
            assert any(bundle["summon"]["group"] == f"mount.{beast}" for bundle in bundles)
    assert table == original_table

    # Synthetic rows make both the on-hit path and an explicit authored value
    # observable even when the shipped data does not currently exercise them.
    synthetic = copy.deepcopy(table)
    chain = synthetic["creatures"]["chain_clone"]
    hit_save = {"type": "save", "ability": "WIS",
                "evidence": "each creature within 10 feet must make a saving throw",
                "on_fail": [{"type": "speed", "applies_to": "ally",
                             "evidence": "one ally within 10 feet"}]}
    authored_save = {"type": "save", "ability": "STR",
                     "subjects": {"area_scope": "creatures_in_area", "exclude_self": True}}
    chain["attacks"][0]["on_hit_effects"].append(hit_save)
    chain["specials"].append({"id": "synthetic", "name": "Synthetic", "effects": [authored_save]})
    original_synthetic = copy.deepcopy(synthetic)
    monkeypatch.setattr(summons, "rules", lambda: synthetic)
    bundle, = compile_creatures(["tianxia.talent.chains.chain_clone"])
    compiled = recipients(bundle)
    for row in (hit_save, authored_save):
        expected = copy.deepcopy(row)
        derive_effect_subjects(expected, "synthetic.summon")
        assert expected in compiled
    hit = next(row for row in compiled if row.get("evidence") == hit_save["evidence"])
    assert hit["subjects"] == {"area_scope": "creatures_in_area", "exclude_self": False}
    assert hit["on_fail"][0]["subjects"] == {"count": "one", "within_ft": 10, "or_self": False}
    assert authored_save in compiled
    assert synthetic == original_synthetic


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
