"""All published Method profiles use the same causal resource calculation."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core import FoundryError, sha256_file, sha256_json
from contracts.canonical import canonical_record_hash
from contracts.registry import SchemaRegistry
from non_sphere_authority.method_mechanics import (
    INITIAL_METHOD_MECHANICS_POLICY,
    METHOD_MECHANICS_PACK_VERSION,
    compile_method_mechanics,
    uses_initial_method_mechanics,
)
from non_sphere_authority.service import NonSphereAuthorityService
from stage2.service import RulesCausalStage2Service
from projector.method_mechanics import project_initial_method_mechanics


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def authority():
    context = object.__new__(NonSphereAuthorityService)
    context.root = ROOT
    context.authority_root = ROOT / "non_sphere_authority/authority"
    context.identity = json.loads((context.authority_root / "NS1R_AUTHORITY_IDENTITIES.json").read_text())
    context._verify_authority_identity()
    path = context.authority_root / "Tianxia_Methods_Typed_Registry_v0_6.json"
    context.method_registry = json.loads(path.read_text())
    context.method_registry_commitment_sha256 = sha256_file(path)
    context.methods = {row["method_id"]: row for row in context.method_registry["methods"]}
    context.authority_snapshot_hash = sha256_json({name: meta["sha256"] for name, meta in sorted(context.identity["files"].items())})
    return context


@pytest.mark.parametrize("method_id", [f"METHOD-{i:03}" for i in range(1, 103)])
def test_every_method_uses_existing_causal_engine_with_exact_deltas_and_no_refill(authority, method_id):
    method = authority.project_locked_method_catalog_record(method_id, mechanical=True)
    assert method["content_binding"]["pack_version"] == METHOD_MECHANICS_PACK_VERSION
    assert method["record_hash"] == canonical_record_hash(method)
    assert authority.reconstruct_locked_method_catalog_record(method) == method
    registry = SchemaRegistry(ROOT)
    assert registry.report(method, "TianxiaFoundry.RulesCatalogRecord.v1")["valid"]
    causal = object.__new__(RulesCausalStage2Service)
    causal._equal_initial_path_records = lambda *_args: None
    causal._resolve_record_after_proof = lambda *_args: method
    causal._foundation_modifier_record = lambda *_args: None
    state = {
        "record_event_ids": {method_id: "method-activation", "path": "path-acquisition"},
        "method": {"record_id": method_id, "state": "active"},
        "foundation": None, "equipment": [], "ability_scores": {}, "ability_modifiers": {},
    }
    for profile in authority.methods[method_id]["per_path_resource_profiles"]:
        rid = profile["resource_id"]
        path = {
            "record_id": "path", "record_hash": "a" * 64,
            "source": {"source_id": "path-source", "anchor": "path-anchor", "source_hash": "b" * 64},
            "content_binding": {"pack_id": "test.path", "pack_version": "1.0.0", "pack_hash": "c" * 64},
            "compatibility": {"factory": {"stage2_authority": {"resources": [{
                "resource_id": rid,
                "base_formula": {"schema_version": "TianxiaFoundry.SafeFormula.v1", "formula_id": "path-base", "root": {"op": "constant", "value": 20}},
            }]}}},
        }
        for pb in range(2, 7):
            expected_delta = pb * profile["delta_proficiency_bonus_units"]
            expected_max = max(0, 20 + expected_delta)
            # A build has no spending events: the resource stays as full as it
            # was when its maximum changes, and an existing deficit carries over
            # (a Method never refills a spent resource).
            prior_max = 20
            for current in (0, 2, 20, 99):
                values, bindings, traces = causal._resource_recalculation(
                    None, "project", state, cl=20, pb=pb, path=path,
                    current_resources={rid: {"current": current, "maximum": prior_max}},
                )
                assert set(values) == {rid}
                assert values[rid]["method_delta"] == expected_delta
                assert values[rid]["maximum"] == expected_max
                assert values[rid]["current"] == max(0, expected_max - max(0, prior_max - current))
                assert any(row["role"] == "method_delta" and row["causal_event_id"] == "method-activation" for row in bindings)
                assert traces[rid][f"method_delta:{method_id}"]["root"]["value"] == expected_delta
        state["method"]["state"] = "acquired"
        values, bindings, _ = causal._resource_recalculation(None, "project", state, cl=20, pb=6, path=path)
        assert values[rid]["method_delta"] == 0
        assert not any(row["role"] == "method_delta" for row in bindings)
        state["method"]["state"] = "active"


def test_historical_acquisition_only_versions_remain_distinct(authority):
    for method_id in authority.methods:
        old = authority.project_locked_method_catalog_record(method_id)
        assert authority.reconstruct_locked_method_catalog_record(old) == old
        auth = old["compatibility"]["factory"]["stage2_authority"]
        assert auth["allowed_kinds"] == ["method_acquisition"]
        assert "method_mechanics" not in auth
        assert "resource_modifiers" not in auth
        new = authority.project_locked_method_catalog_record(method_id, mechanical=True)
        assert old["record_hash"] != new["record_hash"]


@pytest.mark.parametrize("field,value", [
    ("path_id", "OTHER_PATH"), ("resource_id", "tianxia.resource.other"),
    ("resource_name", "Other"), ("delta_proficiency_bonus_units", True),
    ("delta_proficiency_bonus_units", 50), ("applies_independently", False),
    ("conversion_permitted", True), ("conversion_rule", "convert freely"),
    ("source_text", ""),
])
def test_inconsistent_profiles_fail_before_formula_issuance(authority, field, value):
    method = deepcopy(authority.methods["METHOD-083"])
    method["per_path_resource_profiles"][0][field] = value
    with pytest.raises(FoundryError) as error:
        compile_method_mechanics(method, authority.method_registry_commitment_sha256)
    assert error.value.code == "NS1R_METHOD_MECHANICS_AUTHORITY_INVALID"


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong-grant", "unknown-version", "forged-delta"])
def test_profile_closure_and_reconstruction_reject_forgery(authority, mutation):
    method = deepcopy(authority.methods["METHOD-083"])
    if mutation == "duplicate":
        method["per_path_resource_profiles"].append(deepcopy(method["per_path_resource_profiles"][0]))
    elif mutation == "missing":
        method["per_path_resource_profiles"].pop()
    elif mutation == "wrong-grant":
        method["explicit_ap_grants"][0]["path_id"] = "QI_CULTIVATION"
    else:
        record = authority.project_locked_method_catalog_record("METHOD-083", mechanical=True)
        if mutation == "unknown-version":
            record["content_binding"]["pack_version"] = "99.0.0"
            with pytest.raises(FoundryError):
                authority.reconstruct_locked_method_catalog_record(record)
        else:
            record["compatibility"]["factory"]["stage2_authority"]["resource_modifiers"][0]["formula"]["root"]["terms"][0]["value"] = 99
            record["record_hash"] = canonical_record_hash(record)
            assert authority.reconstruct_locked_method_catalog_record(record) != record
        return
    with pytest.raises(FoundryError):
        compile_method_mechanics(method, authority.method_registry_commitment_sha256)


def _initial_events(record):
    rule = record["compatibility"]["factory"]["stage2_authority"]["rule_id"]
    return [
        {"event_id": "acquire", "sequence": 3, "subject": {"record_id": record["record_id"]}, "advancement": {"kind": "method_acquisition", "target_cl": 1}},
        {"event_id": "activate", "sequence": 4, "subject": {"record_id": record["record_id"]}, "legal_channel": "method-activation", "advancement": {"kind": "method_activation", "target_cl": 1, "details": {}, "calculation": {"rule_id": rule, "outputs": {}}}},
        {"event_id": "level", "sequence": 5, "advancement": {"kind": "level_advance", "target_cl": 1}},
    ]


def test_projection_requires_active_causal_method_and_preserves_historical_absence(authority):
    old = authority.project_locked_method_catalog_record("METHOD-083")
    assert project_initial_method_mechanics(ROOT, old, [], {}) is None
    record = authority.project_locked_method_catalog_record("METHOD-083", mechanical=True)
    projected = project_initial_method_mechanics(ROOT, record, _initial_events(record), {"acquire": "packet-acquire", "activate": "packet-activate"})
    assert projected["state"] == "active"
    assert projected["mechanical_projection"] is True
    assert projected["source_packet_ids"] == ["packet-acquire", "packet-activate"]
    assert projected["mechanics"]["per_path_resource_profiles"] == authority.methods["METHOD-083"]["per_path_resource_profiles"]


@pytest.mark.parametrize("mutation", [
    "missing-activation", "duplicate-activation", "before-acquisition", "after-level",
    "wrong-method", "wrong-channel", "wrong-cl", "refill", "calculated-output",
    "missing-packet", "forged-source",
])
def test_method_projection_rejects_missing_or_forged_activation(authority, mutation):
    record = authority.project_locked_method_catalog_record("METHOD-083", mechanical=True)
    events = _initial_events(record)
    packets = {"acquire": "packet-acquire", "activate": "packet-activate"}
    if mutation == "missing-activation":
        events.pop(1)
    elif mutation == "duplicate-activation":
        events.append(deepcopy(events[1]))
    elif mutation == "before-acquisition":
        events[1]["sequence"] = 2
    elif mutation == "after-level":
        events[1]["sequence"] = 6
    elif mutation == "wrong-method":
        events[1]["subject"]["record_id"] = "METHOD-001"
    elif mutation == "wrong-channel":
        events[1]["legal_channel"] = "method-acquisition"
    elif mutation == "wrong-cl":
        events[1]["advancement"]["target_cl"] = 2
    elif mutation == "refill":
        events[1]["advancement"]["details"] = {"refill_current": True}
    elif mutation == "calculated-output":
        events[1]["advancement"]["calculation"]["outputs"] = {"resources_after": {"stamina": 100}}
    elif mutation == "missing-packet":
        packets.pop("activate")
    else:
        record["compatibility"]["factory"]["stage2_authority"]["resource_modifiers"][0]["formula"]["root"]["terms"][0]["value"] = 99
        record["record_hash"] = canonical_record_hash(record)
    with pytest.raises(FoundryError) as error:
        project_initial_method_mechanics(ROOT, record, events, packets)
    assert error.value.code == "PROJECTION_METHOD_MECHANICS_INVALID"


def test_method_mechanics_policy_is_explicit_versioned_and_type_exact():
    assert uses_initial_method_mechanics({}) is False
    request = {"server_owned_authority": {"initial_method_mechanics_policy": deepcopy(INITIAL_METHOD_MECHANICS_POLICY)}}
    assert uses_initial_method_mechanics(request) is True
    request["server_owned_authority"]["initial_method_mechanics_policy"]["refill_current"] = 0
    with pytest.raises(FoundryError):
        uses_initial_method_mechanics(request)


def test_cached_private_proof_cannot_select_a_rehashed_changed_request(monkeypatch):
    """Isolate the post-cache check; the real private proof has separate coverage."""
    from types import SimpleNamespace
    from app.core import canonical_json
    from stage2.service import _INITIAL_CREATION_EXECUTION, _canonical_delegated_request_payload

    path_id = "tianxia.path.qi_cultivation"
    request = {
        "server_owned_authority": {"initial_method_mechanics_policy": deepcopy(INITIAL_METHOD_MECHANICS_POLICY)},
        "delegated_choice_envelope": {
            "allowed_choice_ids_by_slot": {"method_choice": ["METHOD-001"]},
            "choices_by_slot": {"method_choice": {"METHOD-001": {}}},
        },
    }
    request["request_sha256"] = sha256_json(_canonical_delegated_request_payload(request))
    context = SimpleNamespace(project_id="project", run_id="run", authorized_delegated_path_ids=(path_id,),
                              request_sha256=request["request_sha256"])
    stage2 = object.__new__(RulesCausalStage2Service)
    monkeypatch.setattr(stage2, "_validated_initial_creation_delegated_path_ids", lambda *_: frozenset({path_id}))
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: {"request_json": canonical_json(request)}))
    token = _INITIAL_CREATION_EXECUTION.set(context)
    try:
        assert stage2._validated_initial_method_version(conn, "project", "METHOD-001") == METHOD_MECHANICS_PACK_VERSION
        # A cached Path proof must not authenticate later bytes just because
        # the attacker has also recomputed the request's own digest.
        request["unbound_change"] = True
        request["request_sha256"] = sha256_json(_canonical_delegated_request_payload(request))
        assert stage2._validated_initial_method_version(conn, "project", "METHOD-001") is None
    finally:
        _INITIAL_CREATION_EXECUTION.reset(token)
