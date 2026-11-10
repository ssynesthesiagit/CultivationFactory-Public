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

def test_destruction_wrapper_requires_its_own_subject_seal():
    from combat.ext.destruction_blast import shape_save

    with pytest.raises(ValueError, match=r"destruction_shape_save.*synthetic.source.*subjects"):
        shape_save(SimpleNamespace(source="synthetic.source"), {"type": "destruction_shape_save"})
