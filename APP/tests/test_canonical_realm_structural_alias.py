from copy import deepcopy
import json
from pathlib import Path

import pytest

from canonical_catalog import CanonicalCatalogAuthorityService
from canonical_catalog.service import REALM_ENTRY_CL, _structural_realm_requirement
from test_cat3_p1r_r2_r1_prerequisite_scope import _project

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = json.loads((ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
CASES = [(talent, predicate) for talent in DOCUMENT["talents"]
         for predicate in talent["typed_prerequisites"]
         if predicate["kind"] == "structural_authority" and predicate.get("display_name", "").endswith(" Realm")]


@pytest.fixture(scope="module")
def service():
    return CanonicalCatalogAuthorityService(ROOT)


@pytest.mark.parametrize("talent,predicate", CASES)
def test_every_duplicate_realm_requires_the_actual_entry_level(service, talent, predicate):
    required = REALM_ENTRY_CL[predicate["display_name"].removesuffix(" Realm")]
    assert _structural_realm_requirement(predicate, talent) == required
    for target, expected in [(required - 1, False), (required, True)]:
        result = service._evaluate_predicate(predicate, {"target_cl": target, "structural_authority_ids": set()}, talent)
        assert result["passed"] is expected


@pytest.mark.parametrize("field,value", [
    ("target_id", "tianxia.structural.other.foundation_realm"),
    ("display_name", "Foundation Realm Technique"),
    ("raw_text", "Foundation Realm or special permission"),
    ("clause_id", "other-clause"),
    ("alternative_id", "other-alternative"),
    ("source_provenance", {}),
])
def test_a_name_or_cross_clause_reference_does_not_grant_realm_authority(service, field, value):
    talent, original = CASES[0]
    predicate = deepcopy(original)
    predicate[field] = value
    assert _structural_realm_requirement(predicate, talent) is None
    result = service._evaluate_predicate(predicate, {"target_cl": 20, "structural_authority_ids": set()}, talent)
    assert result["passed"] is False


def test_missing_companion_does_not_grant_realm_authority():
    original, predicate = CASES[0]
    talent = deepcopy(original)
    talent["typed_prerequisites"] = [row for row in talent["typed_prerequisites"] if row["kind"] != "realm"]
    assert _structural_realm_requirement(predicate, talent) is None


@pytest.mark.parametrize("talent_id,entry,prerequisites", [
    ("tianxia.talent.sabers.battleline_shove_cut", 5, []),
    ("tianxia.talent.sabers.ten_step_pursuit_doctrine", 10, ["tianxia.talent.sabers.red_trail_pursuit"]),
])
def test_owner_training_choices_pass_at_their_recorded_levels(service, talent_id, entry, prerequisites):
    assert _project(service, talent_id, target_cl=entry - 1, existing_talent_ids=prerequisites)["selectable_now"] is False
    assert _project(service, talent_id, target_cl=entry, existing_talent_ids=prerequisites)["selectable_now"] is True
    if prerequisites:
        assert _project(service, talent_id, target_cl=entry)["selectable_now"] is False
