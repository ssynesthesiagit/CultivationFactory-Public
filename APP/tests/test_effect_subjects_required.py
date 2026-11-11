"""Recipient data must be derived before an effect reaches execution."""
from types import SimpleNamespace

import pytest

from combat import typed_executor as te
from factory_authoring.effect_subjects import derive_effect_subjects


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
