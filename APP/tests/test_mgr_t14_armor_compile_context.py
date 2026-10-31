"""Compile-bundle context for the armor_subject hook (Sol F14R blocker).

Every character passes through compile_bundle; the armor hook reads the
effective owned talent ids and spheres from that context. Before the fix the
hook raised KeyError for every character, including those without Equipment.
Synthetic fixtures only (public CI).
"""
from copy import deepcopy
from importlib import import_module

from combat.factory_compiler import compile_character

support = import_module("tests.test_review_sw-equipment")
ACTOR = "actor:factory.00000000-0000-4000-8000-000000000015"
EQUIPMENT_SPHERE = "tianxia.sphere.equipment"
DESIGNATION = "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION"


def _sheet_with_spheres(spheres):
    doc = deepcopy(support._sheet([]))
    block = dict(doc.get("spheres_and_talents") or {})
    block["sphere_record_ids"] = list(spheres)
    doc["spheres_and_talents"] = block
    return doc


def test_character_without_equipment_compiles_and_is_not_granted_designation():
    bundle = compile_character(_sheet_with_spheres([]), actor_id=ACTOR)
    subject = bundle["armor_subject"]
    assert DESIGNATION not in subject["owned"]
    assert subject["ready"] == 0 and subject["fitted_key"] == ""


def test_equipment_sphere_reaches_armor_subject_through_compile_context():
    bundle = compile_character(_sheet_with_spheres([EQUIPMENT_SPHERE]), actor_id=ACTOR)
    assert DESIGNATION in bundle["armor_subject"]["owned"]
