"""On 2026-11-14 the builder dropped the owner's partial point-buy lock,
and the walk's preset menu offered arrays that ignored it.

Synthetic locks exercise the actual provider, response-package, walk and
starting-state materializer boundaries without owner data or model calls.
"""
import io
import itertools
import json
import zipfile

import pytest

from app.core import FoundryError, canonical_json
from character_creation.service import (
    CharacterCreationExecutionService,
    _owner_lock_value,
    _point_buy_lock_arrays,
    _provider_payload,
)
from character_creation.response_materialization import CanonicalSelectionIntent, RESPONSE_SCHEMA
from character_creation.creative_controller import (
    CommittedState,
    build_point_buy_assignment_menu,
    build_point_buy_preset_menu,
    commit_option,
)
from character_creation.creative_controller.linear_menus import _effective_ability_scores
from tests.test_empty_subpath_materialization import _materializer

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
EXPECTED = dict(zip(ABILITIES, (15, 10, 15, 14, 8, 8)))


def _row(fixed, *, budget=27):
    return {
        "field": "character_sheet.ability_point_buy",
        "value": {
            "fixed_scores": fixed,
            "auto_abilities": [ability for ability in ABILITIES if ability not in fixed],
            "budget": budget,
            "points_spent": sum(COSTS[value] for value in fixed.values()),
            "points_remaining": budget - sum(COSTS[value] for value in fixed.values()),
            "completion": "factory_to_complete" if len(fixed) < 6 else "owner_complete",
        },
    }


def _request(row=None):
    return {
        "request_sha256": "e" * 64,
        "content_lock_hash": "a" * 64,
        "typed_choice_snapshot": {"snapshot_sha256": "b" * 64},
        "delegated_choice_envelope": {
            "allowed_choice_ids_by_slot": {},
            "choices_by_slot": {},
            "typed_choice_authority_by_slot": {},
            "frozen_owner_target_cl": {"value": 1},
            "delegated_name_contract": {
                "state": "owner_locked", "owner_locked_value": "Synthetic Cultivator",
            },
        },
        "required_components": [],
        "forbidden_planner_fields": [],
        "server_owned_authority": {},
        "bounded_choice_contract": {
            "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
            "fields": {"ability_scores": {
                "type": "point_buy_scores",
                "abilities": list(ABILITIES),
                "allowed_values": list(COSTS),
                "budget": 27,
            }},
        },
        "stage1_prompt": {"envelope": {"user_locks": [row] if row else []}},
        "generation_route": "generated",
    }


def _schema(request):
    service = object.__new__(CharacterCreationExecutionService)
    service.owner_principal = "synthetic-owner"
    service.get = lambda _: {
        "project_id": "synthetic-project",
        "starting_revision": 1,
        "execution_mode": "STANDARD_API",
        "request": request,
    }
    service._locked_records_for_project_ids = lambda *_: {}
    package = service._complete_request_package("synthetic-run")
    with zipfile.ZipFile(io.BytesIO(package["payload"])) as archive:
        return json.loads(archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]


def _projection(request):
    payload = _provider_payload({"request": request}, cue_limit=0, display_limit=0)
    return payload, {"linear_provider_payload": payload}


@pytest.mark.parametrize("fixed", [
    {"STR": 15, "CON": 15, "INT": 14, "DEX": 10},
    EXPECTED,
])
def test_exhausted_partial_and_full_locks_are_one_owner_array(monkeypatch, fixed):
    row = _row(fixed)
    assert _point_buy_lock_arrays(row["value"]) == [EXPECTED]
    request = _request(row)
    payload, envelope = _projection(request)
    assert payload["bounded_choice_summary"]["ability_scores"]["legal_score_presets"] == [{
        "scores": list(EXPECTED.values()), "cost": 27, "permutable_across_abilities": False,
    }]
    assert "ability_scores" not in _schema(request)["properties"]["bounded_choices"]["properties"]
    assert build_point_buy_preset_menu(request, envelope) is None
    assert build_point_buy_assignment_menu(request, envelope) is None
    assert _effective_ability_scores(CommittedState.empty(), request, envelope) == EXPECTED

    service, run, project, intent = _materializer(monkeypatch, target_cl=1, select_subpath=False)
    project["user_locks"].append(row)
    document = intent.as_dict()
    document["bounded_choices"].pop("ability_scores")
    rows = service._derive_stage2_rows_from_frozen_authority(
        run, project, CanonicalSelectionIntent.from_document(document),
    )
    starting = next(item for item in rows if item["kind"] == "starting_state")
    assert starting["parameters"]["ability_scores"] == EXPECTED


def test_remaining_points_only_offer_exact_fixed_assignments(monkeypatch):
    row = _row({"STR": 15, "CON": 15})
    allowed = _point_buy_lock_arrays(row["value"])
    assert allowed is not None and len(allowed) > 1
    request = _request(row)
    payload, envelope = _projection(request)
    presets = payload["bounded_choice_summary"]["ability_scores"]["legal_score_presets"]
    alternatives = _schema(request)["properties"]["bounded_choices"]["properties"]["ability_scores"]["oneOf"]
    schema_scores = [
        {ability: alternative["properties"][ability]["const"] for ability in ABILITIES}
        for alternative in alternatives
    ]
    assert schema_scores == allowed
    assert [dict(zip(ABILITIES, preset["scores"])) for preset in presets] == allowed
    for scores, preset in zip(allowed, presets):
        assert scores["STR"] == scores["CON"] == 15
        assert sum(COSTS[value] for value in scores.values()) == 27
        assert preset["permutable_across_abilities"] is False

    # INT cannot be highest here, but generated Qi builds must still offer
    # every owner-authorized completion, including pages beyond the old cap.
    state = CommittedState.empty().with_slot("path_choice", ["tianxia.path.qi_cultivation"])
    seen = []
    page = 1
    while True:
        menu = build_point_buy_preset_menu(request, envelope, state, page=page)
        assert menu is not None
        for option in menu.options:
            if not option.is_continuation:
                committed = commit_option(menu, option.option_id, state)
                seen.append(committed.bounded["ability_scores"])
                assert build_point_buy_assignment_menu(request, envelope, committed) is None
        if menu.next_page_id is None:
            break
        page += 1
    assert page > 3
    assert {tuple(scores[ability] for ability in ABILITIES) for scores in seen} == {
        tuple(scores[ability] for ability in ABILITIES) for scores in allowed
    }

    plan = {"schema": RESPONSE_SCHEMA, "bounded_choices": {"ability_scores": dict.fromkeys(ABILITIES, 15)}}
    decision = CharacterCreationExecutionService._point_buy_budget_owner_decision({"request": request}, plan)
    assert decision["repaired_scores"] in allowed

    service, run, project, intent = _materializer(monkeypatch, target_cl=1, select_subpath=False)
    project["user_locks"].append(row)
    document = intent.as_dict()
    for scores in (allowed[0], dict(zip(ABILITIES, (8, 8, 15, 8, 15, 15)))):
        document["bounded_choices"]["ability_scores"] = scores
        candidate = CanonicalSelectionIntent.from_document(document)
        if scores in allowed:
            rows = service._derive_stage2_rows_from_frozen_authority(run, project, candidate)
            assert rows[0]["parameters"]["ability_scores"] == scores
        else:
            with pytest.raises(FoundryError) as error:
                service._derive_stage2_rows_from_frozen_authority(run, project, candidate)
            assert error.value.code == "CG1_BOUNDED_DECISION_REQUIRED"

    # The reader uses the lock's budget, not an inline 27-point table.
    assert _point_buy_lock_arrays(_row({"STR": 15, "CON": 15}, budget=18)["value"]) == [
        dict(zip(ABILITIES, (15, 8, 15, 8, 8, 8))),
    ]


def test_no_lock_and_builder_defaults_keep_main_contract_bytes():
    # Literal presets and exhaustive alternatives mirror the pre-fix main
    # contract without repository-history reads or private fixture data.
    expected_presets = [
        {"scores": list(scores), "cost": 27, "permutable_across_abilities": True}
        for scores in ((15, 15, 15, 8, 8, 8), (15, 14, 13, 10, 12, 8),
                       (15, 14, 14, 10, 10, 8), (15, 13, 13, 12, 12, 8))
    ]
    expected_alternatives = [
        {
            "type": "object", "additionalProperties": False, "required": list(ABILITIES),
            "properties": {ability: {"const": values[index]} for index, ability in enumerate(ABILITIES)},
        }
        for values in itertools.product(sorted(COSTS), repeat=6)
        if sum(COSTS[value] for value in values) == 27
    ]
    default = {**_row(EXPECTED), "source": "builder-default"}
    for row in (None, default):
        request = _request(row)
        assert _point_buy_lock_arrays(_owner_lock_value(
            request["stage1_prompt"]["envelope"]["user_locks"], "character_sheet.ability_point_buy",
        )) is None
        payload, _ = _projection(request)
        assert canonical_json(payload["bounded_choice_summary"]["ability_scores"]["legal_score_presets"]) == canonical_json(expected_presets)
        schema = _schema(request)["properties"]["bounded_choices"]["properties"]["ability_scores"]
        assert canonical_json(schema) == canonical_json({
            "oneOf": expected_alternatives, "x-point-buy-budget": 27,
        })


def test_impossible_lock_fails_closed_at_reader_and_provider_boundaries(monkeypatch):
    row = _row(dict.fromkeys(ABILITIES, 15))
    request = _request(row)
    service, run, project, intent = _materializer(monkeypatch, target_cl=1, select_subpath=False)
    project["user_locks"].append(row)
    plan = {"schema": RESPONSE_SCHEMA, "bounded_choices": {"ability_scores": EXPECTED}}
    for operation in (
        lambda: _point_buy_lock_arrays(row["value"]),
        lambda: _projection(request),
        lambda: _schema(request),
        lambda: CharacterCreationExecutionService._point_buy_budget_owner_decision({"request": request}, plan),
        lambda: service._derive_stage2_rows_from_frozen_authority(run, project, intent),
    ):
        with pytest.raises(FoundryError) as error:
            operation()
        assert error.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
