"""Composite Playbook validator: vendor JSON schema plus data-driven legality rules.

Synthetic registry only (generic names, no game text).  The fixture-backed
test is added separately and skips when the vendor corpus is absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory_authoring.composite_playbook import (
    RULES,
    ActionRegistry,
    load_rules,
    validate_playbook,
    validate_playbook_document,
)

RES = "RES_TEST"
OPENING = "STATE_TEST_OPENING"

ACTIONS = [
    {"action_id": "ACT_TEST_STRIKE", "display_name": "Test Strike", "economy": "action",
     "resource_costs": [{"resource_id": RES, "amount": 1}], "creates_states": [OPENING]},
    {"action_id": "ACT_TEST_BURST", "display_name": "Test Burst", "economy": "action",
     "resource_costs": [{"resource_id": RES, "amount": 4}],
     "resource_requirements": [{"resource_id": RES, "minimum": 4}]},
    {"action_id": "ACT_TEST_STEP", "display_name": "Test Step", "economy": "bonus_action",
     "resource_costs": []},
    {"action_id": "ACT_TEST_GUARD", "display_name": "Test Guard", "economy": "reaction",
     "resource_costs": [{"resource_id": RES, "amount": 1}]},
    {"action_id": "ACT_TEST_RITE", "display_name": "Test Rite", "economy": "procedure",
     "resource_costs": []},
    {"action_id": "ACT_TEST_FINISH", "display_name": "Test Finish", "economy": "action",
     "resource_costs": [], "consumes_states": [OPENING]},
    {"action_id": "ACT_TEST_AURA", "display_name": "Test Aura", "economy": "passive",
     "resource_costs": []},
]
PROSE_FIELDS = ("name", "execution_role", "when_to_use", "do_not_use_when", "resource_budget",
                "temporal_feasibility", "fallback", "dao_hook", "i_ching_hook")
POOLS = {RES: {"current": 6, "maximum": 10}}


@pytest.fixture(scope="module")
def registry() -> ActionRegistry:
    return ActionRegistry.from_complete_action_surface({"actions": ACTIONS})


def _step(step, action_id, economy, round_offset=0, requires=()):
    return {"step": step, "action_id": action_id, "economy": economy, "round_offset": round_offset,
            "requires_states": list(requires), "external_preconditions": []}


def _playbook() -> dict:
    playbook = {"composite_id": "CMP_TEST_LINE", "priority": 1, "category": "test"}
    playbook.update({name: f"Synthetic {name} text." for name in PROSE_FIELDS})
    playbook["sequence"] = [
        _step(1, "ACT_TEST_STRIKE", "action", 0),
        _step(2, "ACT_TEST_STEP", "bonus_action", 0),
        _step(3, "ACT_TEST_BURST", "action", 1, requires=[OPENING]),
    ]
    return playbook


def _codes(report):
    return [(d.code, d.pointer) for d in report.diagnostics]


def _validate(registry, playbook, **kw):
    kw.setdefault("resource_pools", POOLS)
    return validate_playbook(playbook, registry=registry, **kw)


def test_valid_playbook_passes_every_enabled_rule(registry):
    report = _validate(registry, _playbook())
    assert report.ok, _codes(report)
    assert report.diagnostics == []
    assert report.rules_run == list(load_rules().enabled_rules)
    assert report.playbook_id == "CMP_TEST_LINE"
    assert set(report.rules_run) <= set(RULES)


def test_procedure_is_schema_legal_but_not_executable(registry):
    playbook = _playbook()
    playbook["sequence"][1] = _step(2, "ACT_TEST_RITE", "procedure", 0)
    codes = _codes(_validate(registry, playbook))
    assert ("ECONOMY_EXECUTABLE", "/sequence/1/economy") in codes
    assert not any(code == "SCHEMA" for code, _ in codes)


def test_procedure_passes_when_the_rules_data_allows_it(registry):
    playbook = _playbook()
    playbook["sequence"][1] = _step(2, "ACT_TEST_RITE", "procedure", 0)
    base = load_rules()
    rules = base.with_overrides(
        executable_buckets=[*base.executable_buckets, "procedure"],
        round_economy_capacity={**base.round_economy_capacity, "procedure": 1},
    )
    report = _validate(registry, playbook, rules=rules)
    assert report.ok, _codes(report)


def test_split_required_fails_schema_and_executability(registry):
    playbook = _playbook()
    playbook["sequence"][1]["economy"] = "split_required"
    codes = _codes(_validate(registry, playbook))
    assert ("SCHEMA", "/sequence/1/economy") in codes
    assert ("ECONOMY_EXECUTABLE", "/sequence/1/economy") in codes


def test_unknown_action_id(registry):
    playbook = _playbook()
    playbook["sequence"][2]["action_id"] = "ACT_TEST_MISSING"
    playbook["conditional_options"] = [{"condition": "If pressed.", "action_id": "ACT_TEST_ALSO_MISSING"}]
    codes = _codes(_validate(registry, playbook))
    assert ("ACTION_KNOWN", "/sequence/2/action_id") in codes
    assert ("ACTION_KNOWN", "/conditional_options/0/action_id") in codes


def test_economy_must_match_the_registered_action(registry):
    playbook = _playbook()
    playbook["sequence"][1]["economy"] = "reaction"  # ACT_TEST_STEP is a bonus_action
    assert ("ECONOMY_MATCHES_ACTION", "/sequence/1/economy") in _codes(_validate(registry, playbook))


def test_round_offsets_must_not_go_backwards(registry):
    playbook = _playbook()
    playbook["sequence"][1]["round_offset"] = 2
    playbook["sequence"][2]["round_offset"] = 1
    assert ("ROUND_OFFSET_MONOTONIC", "/sequence/2/round_offset") in _codes(_validate(registry, playbook))


def test_round_offset_within_max(registry):
    playbook = _playbook()
    playbook["sequence"][2]["round_offset"] = load_rules().max_round_offset + 1
    assert ("ROUND_OFFSET_MONOTONIC", "/sequence/2/round_offset") in _codes(_validate(registry, playbook))


def test_two_actions_in_one_round_exceed_capacity(registry):
    playbook = _playbook()
    playbook["sequence"][2]["round_offset"] = 0
    assert ("ROUND_ECONOMY_CAPACITY", "/sequence/2/economy") in _codes(_validate(registry, playbook))


def test_state_created_by_a_later_step_is_not_available(registry):
    playbook = _playbook()
    playbook["sequence"] = [
        _step(1, "ACT_TEST_BURST", "action", 0, requires=[OPENING]),
        _step(2, "ACT_TEST_STRIKE", "action", 1),
    ]
    assert ("STATES_AVAILABLE", "/sequence/0/requires_states") in _codes(_validate(registry, playbook))


def test_seeded_available_states_satisfy_requirements(registry):
    playbook = _playbook()
    playbook["sequence"] = [
        _step(1, "ACT_TEST_BURST", "action", 0, requires=[OPENING]),
        _step(2, "ACT_TEST_STRIKE", "action", 1),
    ]
    report = _validate(registry, playbook, available_states=[OPENING])
    assert report.ok, _codes(report)


def test_overspend_against_supplied_pool(registry):
    codes = _codes(_validate(registry, _playbook(), resource_pools={RES: {"current": 3}}))
    assert ("RESOURCE_TOTALS", "/sequence") in codes      # 1 + 4 > 3
    assert ("RESOURCE_TOTALS", "/sequence/2") in codes    # BURST requires minimum 4


def test_unknown_pool_is_a_warning_not_an_error(registry):
    report = _validate(registry, _playbook(), resource_pools=None)
    assert report.ok
    assert [(d.code, d.severity) for d in report.warnings] == [("RESOURCE_POOL_UNKNOWN", "warning")]


def test_fallback_action_id_hook_must_be_zero_cost(registry):
    playbook = _playbook()
    playbook["fallback_action_id"] = "ACT_TEST_GUARD"  # costs 1
    assert ("FALLBACK_NOT_ZERO_COST", "/fallback_action_id") in _codes(_validate(registry, playbook))
    playbook["fallback_action_id"] = "ACT_TEST_STEP"   # zero-cost
    assert _validate(registry, playbook).ok


def test_missing_required_prose_field_is_a_schema_error(registry):
    playbook = _playbook()
    del playbook["dao_hook"]
    schema_errors = [d for d in _validate(registry, playbook).diagnostics if d.code == "SCHEMA"]
    assert schema_errors and any("dao_hook" in d.message for d in schema_errors)


def test_placeholder_prose_is_rejected_by_the_vendor_schema(registry):
    playbook = _playbook()
    playbook["fallback"] = "TBD"
    assert ("SCHEMA", "/fallback") in _codes(_validate(registry, playbook))


def test_step_numbering_must_be_consecutive(registry):
    playbook = _playbook()
    playbook["sequence"][1]["step"] = 5
    assert ("STEP_NUMBERING", "/sequence/1/step") in _codes(_validate(registry, playbook))


def test_unknown_rule_code_is_rejected(registry):
    rules = load_rules().with_overrides(enabled_rules=["SCHEMA", "NOT_A_RULE"])
    with pytest.raises(ValueError, match="NOT_A_RULE"):
        validate_playbook(_playbook(), registry=registry, rules=rules)


def test_document_form_validates_each_composite(registry):
    reports = validate_playbook_document({"composites": [_playbook(), _playbook()]},
                                         registry=registry, resource_pools=POOLS)
    assert [r.ok for r in reports] == [True, True]
    assert [r.to_dict()["ok"] for r in reports] == [True, True]


# ------------------------------------------------------------- vendor fixture
FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "retained_evidence"
    / "cg1_run_8497b589d4f0436abdbcb933a474b9ef_20260829" / "post_command4_release"
    / "action13_d1038e_clean_import" / "data" / "vendor" / "extracted"
    / "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
    / "HF05ZVK_R1H_Phase2I_HF2" / "08_FIXTURES" / "GOOD_Authoritative_CL13" / "Build"
)
fixture_only = pytest.mark.skipif(not FIXTURE_DIR.exists(), reason="vendor fixture corpus not present")

# Per-step fields the vendor schema requires but the vendor's own fixture omits.
FIXTURE_MISSING_STEP_FIELDS = ("round_offset", "requires_states", "external_preconditions")


def _fixture_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture_reports():
    registry = ActionRegistry.from_complete_action_surface(_fixture_json("Complete_Action_Surface.json"))
    assert registry.warnings == []
    # Character_Master_Ledger.json resources[] carries current/max per resource_id.
    pools = {
        row["resource_id"]: {"current": row["current"], "maximum": row["max"]}
        for row in _fixture_json("Character_Master_Ledger.json")["resources"]
    }
    document = _fixture_json("Composite_Playbook.json")
    return document, validate_playbook_document(document, registry=registry, resource_pools=pools)


@fixture_only
def test_fixture_playbooks_pass_every_legality_rule(fixture_reports):
    document, reports = fixture_reports
    assert len(reports) == 3
    assert [r.playbook_id for r in reports] == [c["composite_id"] for c in document["composites"]]
    for report in reports:
        non_schema_errors = [d for d in report.errors if d.code != "SCHEMA"]
        assert non_schema_errors == [], (report.playbook_id, [d.to_dict() for d in non_schema_errors])
        assert report.warnings == [], (report.playbook_id, [d.to_dict() for d in report.warnings])
        assert report.rules_run == list(load_rules().enabled_rules)


@fixture_only
def test_fixture_playbooks_disagree_with_the_vendor_schema_only_on_three_step_fields(fixture_reports):
    """The corpus ships a schema its own fixture does not satisfy: every sequence
    step lacks round_offset / requires_states / external_preconditions.  Pin that
    exactly so a corrected fixture (or a schema change) surfaces here."""
    document, reports = fixture_reports
    for composite, report in zip(document["composites"], reports):
        schema_errors = [d for d in report.errors if d.code == "SCHEMA"]
        expected = sorted(
            (f"/sequence/{index}", f"'{name}' is a required property")
            for index in range(len(composite["sequence"]))
            for name in FIXTURE_MISSING_STEP_FIELDS
        )
        assert sorted((d.pointer, d.message) for d in schema_errors) == expected, report.playbook_id


# ----------------------------------------------------- audit follow-ups
def test_a_consumed_state_is_not_available_to_later_steps(registry):
    playbook = _playbook()
    playbook["sequence"] = [
        _step(1, "ACT_TEST_STRIKE", "action", 0),                      # creates OPENING
        _step(2, "ACT_TEST_FINISH", "action", 1, requires=[OPENING]),  # consumes OPENING
        _step(3, "ACT_TEST_BURST", "action", 2, requires=[OPENING]),   # OPENING is gone
    ]
    codes = _codes(_validate(registry, playbook))
    assert ("STATES_AVAILABLE", "/sequence/1/requires_states") not in codes
    assert ("STATES_AVAILABLE", "/sequence/2/requires_states") in codes


def test_bucket_without_a_capacity_entry_is_unlimited_per_round(registry):
    assert load_rules().capacity_for("passive") is None
    playbook = _playbook()
    playbook["sequence"] = [
        _step(1, "ACT_TEST_AURA", "passive", 0),
        _step(2, "ACT_TEST_AURA", "passive", 0),
    ]
    report = _validate(registry, playbook)
    assert report.ok, _codes(report)


def test_sequence_length_bounds_come_from_the_rules_data(registry):
    rules = load_rules().with_overrides(sequence_length={"min": 4, "max": 32})
    assert ("STEP_NUMBERING", "/sequence") in _codes(_validate(registry, _playbook(), rules=rules))


def test_max_round_offset_comes_from_the_rules_data(registry):
    playbook = _playbook()
    playbook["sequence"][2]["round_offset"] = 3
    assert _validate(registry, playbook).ok
    rules = load_rules().with_overrides(max_round_offset=2)
    assert ("ROUND_OFFSET_MONOTONIC", "/sequence/2/round_offset") in _codes(
        _validate(registry, playbook, rules=rules))


def test_malformed_action_rows_become_registry_warnings():
    registry = ActionRegistry.from_complete_action_surface(
        {"actions": ["junk", {"display_name": "no id"}, ACTIONS[0]]})
    assert len(registry) == 1
    assert len(registry.warnings) == 2
