from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.core import FoundryError, canonical_json
from character_creation.response_materialization import RESPONSE_SCHEMA
from character_creation.service import CharacterCreationExecutionService


REQUEST_SHA256 = "a" * 64


def _schema_less_preferred() -> dict[str, object]:
    return {
        "request_sha256": REQUEST_SHA256,
        "selection_intent": {"by_slot": {"path_choice": ["PATH-QI"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "Synthetic"}, "concept": "Bounded"},
    }


def test_schema_less_preferred_response_is_projected_in_memory_only() -> None:
    submitted = _schema_less_preferred()
    raw_text = canonical_json(submitted)
    receipt: dict[str, object] = {}

    parsed, raw = CharacterCreationExecutionService._parse_plan(
        raw_text,
        expected_request_sha256=REQUEST_SHA256,
        compatibility_receipt=receipt,
    )

    assert parsed["schema"] == RESPONSE_SCHEMA
    assert raw == raw_text.encode("utf-8")
    assert parsed["request_sha256"] == REQUEST_SHA256
    decoded_raw = json.loads(raw)
    assert isinstance(decoded_raw, dict)
    assert set(decoded_raw) == set(submitted)
    assert receipt == {
        "schema": "TianxiaFoundry.MissingSchemaCompatibilityProjection.v1",
        "inferred_schema": RESPONSE_SCHEMA,
        "source_schema_member": "absent",
        "top_level_shape_exact": True,
        "request_binding_exact": True,
        "exact_response_bytes_preserved": True,
    }

@pytest.mark.parametrize("schema", ["", None, "wrong-schema", "TianxiaFoundry.CharacterCreationPlan.v2"])
def test_schema_less_preferred_response_never_accepts_a_conflicting_schema(schema: object) -> None:
    submitted = _schema_less_preferred()
    submitted["schema"] = schema

    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._parse_plan(
            canonical_json(submitted),
            expected_request_sha256=REQUEST_SHA256,
        )

    assert error.value.code == "CG1_PLAN_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("bounded_choices"),
        lambda value: value.update({"unexpected": True}),
        lambda value: value["selection_intent"].pop("by_slot"),
        lambda value: value["acquisition_intent"].pop("insight_occurrences"),
        lambda value: value.update({"request_sha256": "b" * 64}),
    ],
)
def test_schema_less_preferred_response_requires_exact_shape_and_binding(mutate) -> None:
    submitted = _schema_less_preferred()
    mutate(submitted)

    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._parse_plan(
            canonical_json(submitted),
            expected_request_sha256=REQUEST_SHA256,
        )

    assert error.value.code == "CG1_PLAN_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("payload", "expected_request_sha256"),
    [
        ([], REQUEST_SHA256),
        (_schema_less_preferred(), None),
        (_schema_less_preferred(), "c" * 64),
    ],
)
def test_schema_less_preferred_response_requires_object_and_active_request_binding(
    payload: object,
    expected_request_sha256: str | None,
) -> None:
    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._parse_plan(
            canonical_json(payload),
            expected_request_sha256=expected_request_sha256,
        )

    assert error.value.code == "CG1_PLAN_SCHEMA_INVALID"


def test_schema_less_historical_plan_like_object_is_not_relabelled() -> None:
    historical = {
        "request_sha256": REQUEST_SHA256,
        "stage1_response": {"path": "PATH-QI"},
        "target_cl": 1,
        "stage2_proposal": {"choices": []},
        "owner_descriptive_fields": {"identity": {"name": "Historical"}},
        "uncertainties": [],
        "fallbacks": [],
        "output_profile": {},
    }

    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._parse_plan(
            canonical_json(deepcopy(historical)),
            expected_request_sha256=REQUEST_SHA256,
        )

    assert error.value.code == "CG1_PLAN_SCHEMA_INVALID"
