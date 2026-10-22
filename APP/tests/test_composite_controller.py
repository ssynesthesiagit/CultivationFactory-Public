from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from ai_provider.service import AIProviderService
from factory_authoring.command4_provider import canonical_command4_wire_bytes
from factory_authoring.composite_controller import (
    COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA,
    COMPOSITE_CONTROLLER_PURPOSE,
    COMPOSITE_CONTROLLER_RESOURCE_ID,
    COMPOSITE_CONTROLLER_SCHEMA,
    CompositeControllerAuthoring,
    _resource_costs,
    _resource_gains,
    _resource_requirements,
    _overlay_validation_payload,
    _workspace_sha256,
    _canonical_wire_bytes,
)
from factory_authoring.service import FactoryAuthoringWorkspaceService


PROJECT_ID = "project.composite-controller"
PROJECTION_ID = "projection.composite-controller"
CANDIDATE_SHA256 = "c" * 64


def _refresh_checksums(root: Path) -> None:
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {relative}" for relative, digest in sorted(files.items())) + "\n",
        encoding="utf-8",
    )


def _refresh_materialized_checksums(root: Path) -> None:
    build = root / "Build"
    build_files = {
        path.relative_to(build).as_posix(): sha256_file(path)
        for path in sorted(build.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    (build / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {relative}" for relative, digest in sorted(build_files.items())) + "\n",
        encoding="utf-8",
    )
    root_files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "SHA256SUMS.txt"
        and not path.relative_to(root).as_posix().startswith("Build/")
    }
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {relative}" for relative, digest in sorted(root_files.items())) + "\n",
        encoding="utf-8",
    )


def _rewrite_bound_controller_overlay(overlay: Path, source: Path, artifact: dict) -> None:
    """Rebind a synthetic overlay exactly as a tamperer could, for replay tests."""

    artifact["source_workspace_sha256"] = _workspace_sha256(source)
    artifact_sha = sha256_json(artifact)
    manifest_path = overlay / "Composite_Controller_Overlay_Manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "source_workspace_sha256": artifact["source_workspace_sha256"],
        "artifact_sha256": artifact_sha,
        "overlay_id": sha256_json({
            "source_workspace_sha256": artifact["source_workspace_sha256"],
            "base_candidate_sha256": artifact["base_candidate_sha256"],
            "artifact_sha256": artifact_sha,
        }),
    })
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact_path.write_text(canonical_json(artifact), encoding="utf-8")
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    (overlay / "Validation/Composite_Controller.validation.json").write_text(
        canonical_json(_overlay_validation_payload(artifact, artifact_sha)),
        encoding="utf-8",
    )
    _refresh_checksums(overlay)


def _replace_artifact_action_field(artifact: dict, action_id: str, field: str, value: object) -> None:
    """Update every repeated packet for one action in a rehashed replay fixture."""

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("action_id") == action_id:
                node[field] = deepcopy(value)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(artifact)


def _action(index: int, *, cost: int = 1) -> dict:
    action_id = f"action.stable.{index:02d}"
    return {
        "action_id": action_id,
        "record_id": f"record.action.{index:02d}",
        "name": "Zero Stance" if cost == 0 else f"Flame Art {index}",
        "action_type": "action",
        "bucket": "action",
        "timing": "On your turn",
        "cost": "None" if cost == 0 else f"{cost} CP",
        "range": "30 feet",
        "target": "One creature",
        "roll_save_check": "Constitution save",
        "effect": f"Apply the exact sealed effect {index}.",
        "failure": "No effect on a successful save.",
        "duration": "Until the start of your next turn",
        "limit": "Once per turn",
        "counterplay": "Succeed on the save.",
        "resource_costs": (
            []
            if cost == 0
            else [{"resource_id": "RES_CP", "amount": cost}]
        ),
        "resource_gains": [],
        "resource_requirements": [],
        "state_arrays": [],
        "execution_authority": True,
        "full_description": f"Sealed source description for action {index}.",
    }


def _workspace(
    tmp_path: Path,
    *,
    candidate_sha256: str = CANDIDATE_SHA256,
    resource_id: str = "RES_CP",
    resource_name: str = "Stamina",
    resource_current: int = 1,
    resource_maximum: int = 45,
    actions: list[dict] | None = None,
) -> Path:
    root = tmp_path / "workspace"
    (root / "Command_1").mkdir(parents=True)
    (root / "Command_2").mkdir()
    (root / "Command_4").mkdir()
    (root / "Validation").mkdir()
    (root / "Workspace_Manifest.json").write_text(
        canonical_json(
            {
                "schema_version": "TianxiaFoundry.FactoryCommand1To4Workspace.v1",
                "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
                "project_id": PROJECT_ID,
                "project_revision": 4,
                "projection_id": PROJECTION_ID,
                "candidate_sha256": candidate_sha256,
            }
        ),
        encoding="utf-8",
    )
    (root / "Command_1/Character_Blueprint.json").write_text(
        canonical_json(
            {
                "identity": {
                    "display_name": "Cinder Keeper",
                    "cultivation_role": "Body Refining",
                    "realm": "Body Refining",
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "Command_2/Canonical_Stats_Resource_Block.json").write_text(
        canonical_json(
            {
                "character": {"display_name": "Cinder Keeper", "role": "Body Refining"},
                "resources": [
                    {
                        "resource_id": resource_id,
                        "name": resource_name,
                        "current": {"value": resource_current},
                        "maximum": {"value": resource_maximum},
                    }
                ],
                "available_states": ["Marked"],
            }
        ),
        encoding="utf-8",
    )
    actions = actions or [_action(index, cost=0 if index == 1 else 1) for index in range(1, 17)]
    (root / "Command_4/Complete_Action_Surface.json").write_text(
        canonical_json(
            {
                "schema_version": "TianxiaFoundry.Command4CompleteActionSurface.v1",
                "status": "ACTION_SURFACE_READY",
                "actions": actions,
                "procedures": [],
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "Command_4/Composite_Playbooks.json").write_text(
        canonical_json(
            {
                "schema_version": "TianxiaFoundry.GMCompositePlaybooks.v1",
                "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                "playbooks": [
                    {
                        "playbook_id": "display.only.original",
                        "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                        "display_name": "Original GM guidance",
                        "sequence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _refresh_checksums(root)
    return root


class _FakeProvider:
    def __init__(self, response: dict | None = None, *, failure: Exception | None = None):
        self.response = response
        self.failure = failure
        self.calls: list[dict] = []

    def _settings(self) -> dict:
        return {"provider_id": "local", "model": "fake-gemma", "max_output_tokens": 1024}

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return {
            "provider_id": "local",
            "model": "fake-gemma",
            "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
            "performance": {"duration_ms": 12, "completion_tokens_per_second": 4.2},
            "response_text": canonical_json(self.response),
        }


def _prepared(tmp_path: Path) -> tuple[CompositeControllerAuthoring, dict]:
    authoring = CompositeControllerAuthoring(workspace_root=_workspace(tmp_path))
    return authoring, authoring.prepare(PROJECT_ID)


def _response(prepared: dict, *, budget: int = 2, fallback_index: int = 0) -> dict:
    tokens = prepared["action_tokens"]
    return {
        "schema": COMPOSITE_CONTROLLER_SCHEMA,
        "project_id": prepared["project_id"],
        "projection_id": prepared["projection_id"],
        "candidate_sha256": prepared["candidate_sha256"],
        "request_sha256": prepared["request_sha256"],
        "composite_controller": {
            "composite_id": "composite_controller",
            "name": "Cinder response controller",
            "execution_role": "composite_controller",
            "when_to_use": ["A legal sequence is useful."],
            "do_not_use_when": ["Stamina is unavailable."],
            "resource_budget": {"resource_id": "RES_CP", "max_spend": budget},
            "temporal_feasibility": {"same_turn_legal": True, "round_span": 0, "notes": ["Consecutive actions."]},
            "fallback": {"action_token": tokens[fallback_index], "reason": "Use the zero-cost stance."},
            "dao_hook": "Refine through controlled flame.",
            "i_ching_hook": "Li: clarity through fire.",
            "sequence": [
                {
                    "step": 1,
                    "action_token": tokens[0],
                    "round_offset": 0,
                    "economy": "action",
                    "requires_states": [],
                    "external_preconditions": [],
                },
                {
                    "step": 2,
                    "action_token": tokens[1],
                    "round_offset": 1,
                    "economy": "action",
                    "requires_states": [],
                    "external_preconditions": [],
                },
            ],
            "conditional_options": [],
        },
    }


def _multi_pool_workspace(tmp_path: Path, *, actions: list[dict] | None = None, qi_current: int = 2, stamina_current: int = 1) -> Path:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=qi_current,
        resource_maximum=40,
        actions=actions,
    )
    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"].append({
        "resource_id": "tianxia.resource.stamina",
        "name": "Stamina",
        "current": stamina_current,
        "maximum": 72,
    })
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    return root


def _explicit_two_pool_actions() -> list[dict]:
    actions = [_action(index, cost=0 if index == 1 else 1) for index in range(1, 17)]
    for index, action in enumerate(actions, start=1):
        if index == 1:
            continue
        resource_id = "tianxia.resource.qi" if index % 2 == 0 else "tianxia.resource.stamina"
        resource_name = "Qi" if resource_id.endswith("qi") else "Stamina"
        action["cost"] = f"1 {resource_name}"
        action["resource_costs"] = [{"resource_id": resource_id, "amount": 1}]
    return actions


def _multi_pool_response(prepared: dict, *, qi_budget: int = 1, stamina_budget: int = 1) -> dict:
    tokens = prepared["action_tokens"]
    return {
        "schema": COMPOSITE_CONTROLLER_SCHEMA,
        "project_id": prepared["project_id"],
        "projection_id": prepared["projection_id"],
        "candidate_sha256": prepared["candidate_sha256"],
        "request_sha256": prepared["request_sha256"],
        "composite_controller": {
            "composite_id": "composite_controller",
            "name": "Two pool response controller",
            "execution_role": "composite_controller",
            "when_to_use": ["A legal two pool sequence is useful."],
            "do_not_use_when": ["A required pool is unavailable."],
            "resource_budget": {
                "resource_budgets": [
                    {"resource_id": "tianxia.resource.qi", "max_spend": qi_budget},
                    {"resource_id": "tianxia.resource.stamina", "max_spend": stamina_budget},
                ],
            },
            "temporal_feasibility": {"same_turn_legal": True, "round_span": 0, "notes": ["Separate pools remain separate."]},
            "fallback": {"action_token": tokens[0], "reason": "Use the zero-cost stance."},
            "dao_hook": "Keep the pools distinct.",
            "i_ching_hook": "Balance without conversion.",
            "sequence": [
                {
                    "step": 1,
                    "action_token": tokens[1],
                    "round_offset": 0,
                    "economy": "action",
                    "requires_states": [],
                    "external_preconditions": [],
                },
                {
                    "step": 2,
                    "action_token": tokens[2],
                    "round_offset": 1,
                    "economy": "action",
                    "requires_states": [],
                    "external_preconditions": [],
                },
            ],
            "conditional_options": [],
        },
    }


def test_prepare_is_target_only_bounded_and_enumerates_16_opaque_action_tokens(tmp_path: Path) -> None:
    _authoring, prepared = _prepared(tmp_path)
    assert len(prepared["actions"]) == 16
    assert len(prepared["action_tokens"]) == 16
    assert len(prepared["prompt_text"].encode("utf-8")) < 20_000
    payload = json.loads(prepared["prompt_text"])
    assert payload["target"] == "composite_controller"
    assert payload["authoritative_resource"] == {
        "resource_id": COMPOSITE_CONTROLLER_RESOURCE_ID,
        "alias": "RES_CP",
        "name": "Stamina",
        "current": 1,
        "maximum": 45,
    }
    assert payload["available_states"] == ["Marked"]
    assert payload["contract"]["round_economy_capacity"]["free"] == 4
    assert "free may repeat up to four times" in payload["contract"]["round_economy_rule"]
    assert "strictly later round_offset" in payload["contract"]["round_economy_rule"]
    assert all(token.startswith("ccopt_") for token in prepared["action_tokens"])
    assert all(action["action_id"] not in prepared["prompt_text"] for action in prepared["actions"])
    assert "full_description" not in prepared["prompt_text"]
    schema_text = canonical_json(prepared["response_schema"])
    assert all(token in schema_text for token in prepared["action_tokens"])
    assert prepared["request_bytes"] <= prepared["max_request_bytes"]


@pytest.mark.parametrize("command4", [False, True])
def test_composite_authorized_wire_matches_actual_local_transport(tmp_path: Path, monkeypatch, command4) -> None:
    _authoring, prepared = _prepared(tmp_path)
    settings = {
        "enabled": True, "provider_id": "local", "model": "fixture-local-model",
        "endpoint": "http://127.0.0.1:11442/v1", "max_output_tokens": 16384,
        "timeout_seconds": 60,
    }
    provider = object.__new__(AIProviderService)
    monkeypatch.setattr(provider, "_settings", lambda: settings)
    expected = _canonical_wire_bytes(prepared["prompt_text"], prepared["system_message"], settings, prepared["response_schema"])
    if command4:
        expected = canonical_command4_wire_bytes(
            prepared["prompt_text"], system_message=prepared["system_message"], settings=settings,
            response_schema=prepared["response_schema"], response_schema_name=prepared["response_schema_name"],
            response_schema_max_output_tokens=6144,
        )

    class TransportReached(Exception):
        pass

    def capture(**kwargs):
        assert kwargs["request_bytes"] == expected
        assert json.loads(expected)["cache_prompt"] is True
        assert json.loads(expected)["max_tokens"] == 6144
        raise TransportReached

    monkeypatch.setattr(provider, "_provider_call", capture)
    with pytest.raises(TransportReached):
        provider.complete_json(
            prompt_text=prepared["prompt_text"], system_message=prepared["system_message"],
            purpose="factory_command4_action_authoring" if command4 else COMPOSITE_CONTROLLER_PURPOSE, substantive=True,
            response_schema=prepared["response_schema"], response_schema_name=prepared["response_schema_name"],
            response_schema_max_output_tokens=6144, max_request_bytes=prepared["max_request_bytes"],
            temperature=0, expected_request_sha256=sha256_bytes(expected),
        )
    if not command4:
        for purpose, limit in ((COMPOSITE_CONTROLLER_PURPOSE, 6145), ("ordinary_correction", 6144)):
            with pytest.raises(FoundryError) as error:
                provider.complete_json(
                    prompt_text=prepared["prompt_text"], system_message=prepared["system_message"],
                    purpose=purpose, substantive=True, response_schema=prepared["response_schema"],
                    response_schema_name=prepared["response_schema_name"],
                    response_schema_max_output_tokens=limit,
                )
            assert error.value.code == "AI_PROVIDER_RESPONSE_SCHEMA_INVALID"


def test_large_theme_catalog_preserves_sources_and_exact_constraints_within_wire_cap(tmp_path: Path) -> None:
    authoring, _ = _prepared(tmp_path)
    records = [
        {"section": "talents", "record": {
            "record_id": f"tianxia.fixture.teaching.{index:04d}",
            "display_name": f"Selected teaching {index}",
            "one_line_description": "A complete descriptive summary of a selected teaching.",
            "acquisition_route": "preserved in server-owned acquisition authority",
            "acquisition_cl": index % 20 + 1,
        }}
        for index in range(180)
    ]
    original = deepcopy(records)
    prepared = authoring.prepare(PROJECT_ID, theme_records=records)
    assert records == original
    prompt = json.loads(prepared["prompt_text"])
    table = prompt["actions"]
    assert [{key: value for key, value in zip(table["columns"], row) if value is not None}
            for row in table["rows"]] == prepared["action_summaries"]
    sources = prompt["descriptive_theme_sources"]
    restored = [dict(zip(sources["columns"], row)) for row in sources["rows"]]
    for row in restored:
        row["section"] = sources["sections"][row.pop("section_index")]
    assert restored == [
        {"section": row["section"], **{key: row["record"][key] for key in ("record_id", "display_name", "one_line_description")}}
        for row in records
    ]
    assert all(source["acquisition_route"] for source in prepared["theme_sources"])
    assert prepared["request_bytes"] <= prepared["max_request_bytes"] == 64 * 1024
    theme = {
        "display_name": "Bound theme", "core_theme": "A selected teaching",
        "principles": ["Observe", "Consider"], "strengths": ["Care", "Attention"],
        "risks": ["Haste", "Distraction"], "roleplay_expression": "Observe carefully.",
        "tactical_expression": "Consult the action authority.", "gm_usage_notes": "Descriptive only.",
        "relevant_record_ids": prepared["theme_record_ids"], "mechanical_effects": [],
    }
    response = _response(prepared)
    response["gm_themes"] = {"dao": deepcopy(theme), "i_ching": deepcopy(theme)}
    authoring._validate_dynamic_schema(prepared, response)
    for kind in ("dao", "i_ching"):
        for field, invalid in (("relevant_record_ids", ["unselected.record"]), ("mechanical_effects", ["free mechanic"])):
            altered = deepcopy(response)
            altered["gm_themes"][kind][field] = invalid
            with pytest.raises(FoundryError, match="sealed composite-controller response schema"):
                authoring._validate_dynamic_schema(prepared, altered)
    records[0]["record"]["one_line_description"] = "x" * (64 * 1024)
    with pytest.raises(FoundryError, match="exact wire byte cap"):
        authoring.prepare(PROJECT_ID, theme_records=records)


@pytest.mark.parametrize("wire_bytes", [52_056, 64 * 1024, 64 * 1024 + 1])
def test_composite_request_wire_cap_accepts_live_size_and_enforces_boundary(tmp_path: Path, wire_bytes: int) -> None:
    authoring, baseline = _prepared(tmp_path)
    authoring.system_message += "x" * (wire_bytes - baseline["request_bytes"])
    if wire_bytes > 64 * 1024:
        with pytest.raises(FoundryError) as error:
            authoring.prepare(PROJECT_ID)
        assert error.value.code == "COMPOSITE_CONTROLLER_REQUEST_TOO_LARGE"
        assert error.value.details == {"request_bytes": wire_bytes, "max_request_bytes": 64 * 1024}
        return
    prepared = authoring.prepare(PROJECT_ID)
    assert prepared["request_bytes"] == wire_bytes
    assert prepared["max_request_bytes"] == 64 * 1024


def test_qi_active_path_resource_flows_through_prepare_schema_response_and_overlay(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    assert prepared["resource"] == {
        "resource_id": "tianxia.resource.qi",
        "alias": "RES_CP",
        "name": "Qi",
        "current": 2,
        "maximum": 60,
        "source": "Command_2/Canonical_Stats_Resource_Block.json",
        "source_backed": True,
    }
    prompt = json.loads(prepared["prompt_text"])
    assert prompt["authoritative_resource"]["name"] == "Qi"
    assert "tianxia.resource.qi" in prompt["contract"]["resource_rule"]
    assert "maximum 60" in prompt["contract"]["resource_rule"]
    budget_schema = prepared["response_schema"]["properties"]["composite_controller"]["properties"]["resource_budget"]
    assert budget_schema["properties"]["max_spend"]["maximum"] == 60
    assert budget_schema["properties"]["resource_id"]["enum"] == ["RES_CP", "tianxia.resource.qi"]
    assert prepared["actions"][1]["resource_costs"] == [{"resource_id": "tianxia.resource.qi", "amount": 1}]

    response = _response(prepared, budget=60)
    validated = authoring._validate_response(prepared, response)
    controller = validated["composite_controller"]
    assert controller["resource_budget"]["resource_id"] == "tianxia.resource.qi"
    assert controller["sequence"][1]["resource_costs"] == [{"resource_id": "tianxia.resource.qi", "amount": 1}]

    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    artifact = result["artifact"]
    assert artifact["resource_authority"]["resource_id"] == "tianxia.resource.qi"
    assert artifact["resource_authority"]["name"] == "Qi"
    assert artifact["composite_controller"]["resource_budget"]["resource_id"] == "tianxia.resource.qi"
    assert artifact["composite_controller"]["sequence"][1]["resource_costs"] == [
        {"resource_id": "tianxia.resource.qi", "amount": 1}
    ]
    CompositeControllerAuthoring.validate_overlay(
        Path(result["overlay_path"]),
        project_id=PROJECT_ID,
        candidate_sha256=CANDIDATE_SHA256,
        projection_id=PROJECTION_ID,
        source_workspace=root,
    )


def test_qi_resource_maximum_is_not_truncated_at_historical_45(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][2]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 60}]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    prepared = CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert prepared["actions"][2]["resource_costs"] == [{"resource_id": "tianxia.resource.qi", "amount": 60}]
    assert prepared["response_schema"]["properties"]["composite_controller"]["properties"]["resource_budget"]["properties"]["max_spend"]["maximum"] == 60


def test_qi_mixed_untracked_resource_actions_are_excluded_without_conversion(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    excluded = surface["actions"][1]["action_id"]
    surface["actions"][1]["resource_costs"] = [{"resource_id": "RES_REAGENT_STOCK", "amount": 1}]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    assert excluded not in {action["action_id"] for action in prepared["actions"]}
    assert prepared["actions"][0]["name"] == "Zero Stance"
    excluded_token = "ccopt_" + sha256_json({
        "project_id": PROJECT_ID,
        "candidate_sha256": CANDIDATE_SHA256,
        "ordinal": 1,
        "action_id": excluded,
    })[:24]
    response = _response(prepared)
    response["composite_controller"]["sequence"][0]["action_token"] = excluded_token
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("field", "parser", "amount_key"),
    [
        ("resource_costs", _resource_costs, "amount"),
        ("resource_requirements", _resource_requirements, "minimum"),
        ("resource_gains", _resource_gains, "amount"),
    ],
)
@pytest.mark.parametrize("resource_id", ["RES_REAGENT_STOCK", "tianxia.resource.stamina"])
@pytest.mark.parametrize("amount", [0, 1])
def test_every_declared_non_active_resource_row_fails_closed(
    field: str,
    parser: object,
    amount_key: str,
    resource_id: str,
    amount: int,
) -> None:
    row = {field: [{"resource_id": resource_id, amount_key: amount}]}
    qi_resource = {
        "resource_id": "tianxia.resource.qi",
        "name": "Qi",
        "current": 2,
        "maximum": 60,
        "source_backed": True,
    }
    with pytest.raises(FoundryError) as error:
        parser(row, qi_resource)  # type: ignore[operator]
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("field", "amount_key"),
    [
        ("resource_costs", "amount"),
        ("resource_requirements", "minimum"),
        ("resource_gains", "amount"),
    ],
)
@pytest.mark.parametrize("amount", [0, 1])
def test_prepare_excludes_untracked_non_path_rows_without_cp_conversion(
    tmp_path: Path,
    field: str,
    amount_key: str,
    amount: int,
) -> None:
    root = _workspace(tmp_path)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    excluded = surface["actions"][2]
    excluded["resource_costs"] = excluded.get("resource_costs") or [{"resource_id": "RES_CP", "amount": 1}]
    excluded[field] = [{"resource_id": "RES_REAGENT_STOCK", amount_key: amount}]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)

    prepared = CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    excluded_id = excluded["action_id"]
    assert excluded_id not in {action["action_id"] for action in prepared["actions"]}
    assert excluded_id not in {
        action.get("action_id") for action in prepared["token_to_action"].values()
        if isinstance(action, dict)
    }
    assert all(
        row.get("resource_id") != "RES_REAGENT_STOCK"
        for action in prepared["actions"]
        for container in ("resource_costs", "resource_requirements", "resource_gains")
        for row in action.get(container, [])
        if isinstance(row, dict)
    )


@pytest.mark.parametrize(
    ("field", "amount_key"),
    [
        ("resource_costs", "amount"),
        ("resource_requirements", "minimum"),
        ("resource_gains", "amount"),
    ],
)
@pytest.mark.parametrize("amount", [0, 1])
def test_prepare_rejects_cross_path_rows_in_every_resource_container(
    tmp_path: Path,
    field: str,
    amount_key: str,
    amount: int,
) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    target = surface["actions"][2]
    target[field] = [{"resource_id": "tianxia.resource.stamina", amount_key: amount}]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED"


def test_qi_rejects_concrete_cross_path_action_resource(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][0]["resource_costs"] = [{"resource_id": "tianxia.resource.stamina", "amount": 1}]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED"


def test_resource_authority_accepts_separate_authenticated_path_pools(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
        actions=_explicit_two_pool_actions(),
    )
    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"].append({
        "resource_id": "tianxia.resource.stamina",
        "name": "Stamina",
        "current": {"value": 1},
        "maximum": {"value": 45},
    })
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    prepared = CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert [row["resource_id"] for row in prepared["resource"]["resources"]] == [
        "tianxia.resource.qi",
        "tianxia.resource.stamina",
    ]
    assert prepared["actions"][1]["resource_costs"] == [{"resource_id": "tianxia.resource.qi", "amount": 1}]
    assert prepared["actions"][2]["resource_costs"] == [{"resource_id": "tianxia.resource.stamina", "amount": 1}]
    budget = prepared["response_schema"]["properties"]["composite_controller"]["properties"]["resource_budget"]
    assert budget["required"] == ["resource_budgets"]
    assert budget["properties"]["resource_budgets"]["minItems"] == 2


def test_resource_authority_rejects_conflicting_rows_for_one_path_pool(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
        actions=_explicit_two_pool_actions(),
    )
    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"].append({
        "resource_id": "RES_QI",
        "name": "Qi",
        "current": 3,
        "maximum": 60,
    })
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID"
    assert error.value.details["resource_id"] == "tianxia.resource.qi"


def test_multi_pool_response_charges_named_costs_only_from_their_pool(tmp_path: Path) -> None:
    root = _multi_pool_workspace(tmp_path, actions=_explicit_two_pool_actions(), qi_current=2, stamina_current=1)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _multi_pool_response(prepared)
    validated = authoring._validate_response(prepared, response)
    budget_rows = validated["composite_controller"]["resource_budget"]["resource_budgets"]
    assert budget_rows == [
        {"resource_id": "tianxia.resource.qi", "max_spend": 1, "total_sequence_cost": 1},
        {"resource_id": "tianxia.resource.stamina", "max_spend": 1, "total_sequence_cost": 1},
    ]
    assert validated["composite_controller"]["sequence"][0]["resource_costs"] == [
        {"resource_id": "tianxia.resource.qi", "amount": 1}
    ]
    assert validated["composite_controller"]["sequence"][1]["resource_costs"] == [
        {"resource_id": "tianxia.resource.stamina", "amount": 1}
    ]


def test_multi_pool_response_rejects_overspend_in_one_pool_without_cross_pool_substitution(tmp_path: Path) -> None:
    actions = _explicit_two_pool_actions()
    actions[2]["resource_costs"] = [{"resource_id": "tianxia.resource.stamina", "amount": 2}]
    actions[2]["cost"] = "2 Stamina"
    root = _multi_pool_workspace(tmp_path, actions=actions, qi_current=40, stamina_current=1)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _multi_pool_response(prepared, qi_budget=1, stamina_budget=2)
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_UNAVAILABLE"


def test_multi_pool_overlay_replay_keeps_rebound_pools_isolated(tmp_path: Path) -> None:
    root = _multi_pool_workspace(tmp_path, actions=_explicit_two_pool_actions(), qi_current=2, stamina_current=2)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    result = authoring.author(PROJECT_ID, _FakeProvider(_multi_pool_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    next(row for row in resource_block["resources"] if row["resource_id"] == "tianxia.resource.stamina")["current"] = 0
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    next(row for row in artifact["resource_authority"]["resources"] if row["resource_id"] == "tianxia.resource.stamina")["current"] = 0
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_UNAVAILABLE"


def test_multi_pool_generic_cp_requires_authenticated_powering_path_authority(tmp_path: Path) -> None:
    from factory_authoring.composite_controller import _resource_costs

    actions = _explicit_two_pool_actions()
    actions[1]["cost"] = "1 CP"
    actions[1]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    root = _multi_pool_workspace(tmp_path, actions=actions)
    prepared = CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert actions[1]["record_id"] not in {row["record_id"] for row in prepared["actions"]}
    assert len(prepared["actions"]) == len(actions) - 1
    with pytest.raises(FoundryError) as error:
        _resource_costs(actions[1], prepared["resource"])
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"
    assert error.value.details["required_authority"].startswith("authenticated producer-bound")

    insufficient = _multi_pool_workspace(tmp_path / "insufficient", actions=actions[:2])
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=insufficient).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"

    actions[1]["powering_path_id"] = "tianxia.path.qi_cultivation"
    root = _multi_pool_workspace(tmp_path / "recorded", actions=actions)
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"
    assert error.value.details["fields"] == ["powering_path_id"]


def test_single_pool_generic_cp_rejects_declared_other_path_instead_of_using_sole_pool(tmp_path: Path) -> None:
    actions = _explicit_two_pool_actions()
    actions[1]["cost"] = "1 CP"
    actions[1]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    actions[1]["required_path_id"] = "tianxia.path.body_refining"
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=40,
        actions=actions,
    )
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"
    assert error.value.details["fields"] == ["required_path_id"]


def test_conflicting_nested_powering_path_metadata_is_rejected_after_rehash(tmp_path: Path) -> None:
    actions = _explicit_two_pool_actions()
    actions[1]["cost"] = "1 CP"
    actions[1]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    actions[1]["powering_path_id"] = {
        "path_id": "tianxia.path.qi_cultivation",
        "resource_id": "tianxia.resource.stamina",
    }
    root = _multi_pool_workspace(tmp_path, actions=actions)
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"
    assert error.value.details["fields"] == ["powering_path_id"]


def test_resource_authority_accepts_agreeing_duplicate_ledger_rows(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        resource_current=2,
        resource_maximum=60,
    )
    (root / "Character_Master_Ledger.json").write_text(
        canonical_json({
            "resources": [{
                "resource_id": "RES_QI",
                "name": "Qi",
                "current": 2,
                "maximum": 60,
            }],
        }),
        encoding="utf-8",
    )
    _refresh_checksums(root)
    prepared = CompositeControllerAuthoring(workspace_root=root).prepare(PROJECT_ID)
    assert prepared["resource"]["resource_id"] == "tianxia.resource.qi"
    assert prepared["resource"]["source"] == "Command_2/Canonical_Stats_Resource_Block.json"


def test_project_id_is_validated_before_candidate_path_join(tmp_path: Path) -> None:
    calls: list[str] = []
    service = SimpleNamespace(
        db=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path / "data")),
        status=lambda project_id: calls.append(project_id),
    )
    authoring = CompositeControllerAuthoring(workspace_service=service)
    with pytest.raises(FoundryError) as error:
        authoring.prepare("../escape")
    assert error.value.code == "COMPOSITE_CONTROLLER_PROJECT_ID_INVALID"
    assert calls == []


def test_candidate_workspace_requires_pointer_hash_binding_and_rejects_sibling_substitution(tmp_path: Path) -> None:
    bundle = tmp_path / "candidate-bundle"
    bundle.mkdir()
    candidate_zip = bundle / "candidate.zip"
    candidate_zip.write_bytes(b"sealed candidate bytes")
    candidate_sha = sha256_file(candidate_zip)
    workspace = _workspace(bundle, candidate_sha256=candidate_sha)
    workspace_sha = _workspace_sha256(workspace)
    data_dir = tmp_path / "data"
    pointer_path = data_dir / "factory_candidates" / PROJECT_ID / "current.json"
    pointer_path.parent.mkdir(parents=True)
    pointer = {
        "project_id": PROJECT_ID,
        "status": "GM_MODEL_CANDIDATE_READY",
        "candidate_sha256": candidate_sha,
        "candidate_zip": str(candidate_zip),
        "workspace": str(workspace),
        "projection_id": PROJECTION_ID,
    }
    service = SimpleNamespace(
        db=SimpleNamespace(settings=SimpleNamespace(data_dir=data_dir)),
        status=lambda _project_id: {"available": True, "workspace_path": str(workspace)},
    )
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    authoring = CompositeControllerAuthoring(workspace_service=service)

    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID"

    pointer["workspace_sha256"] = workspace_sha
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    assert authoring.prepare(PROJECT_ID)["candidate_sha256"] == candidate_sha

    sibling = bundle / "sibling-workspace"
    shutil.copytree(workspace, sibling)
    sibling_manifest = sibling / "Workspace_Manifest.json"
    manifest = json.loads(sibling_manifest.read_text(encoding="utf-8"))
    manifest["project_revision"] = 999
    sibling_manifest.write_text(canonical_json(manifest), encoding="utf-8")
    _refresh_checksums(sibling)
    pointer["workspace"] = str(sibling)
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH"

    linked_member = workspace / "Command_1/linked-blueprint.json"
    linked_member.symlink_to(workspace / "Command_1/Character_Blueprint.json")
    _refresh_checksums(workspace)
    pointer["workspace"] = str(workspace)
    pointer["workspace_sha256"] = _workspace_sha256(workspace)
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID"


def test_materialized_candidate_binds_exact_source_reviewed_overlay_and_build_receipt(tmp_path: Path) -> None:
    bundle = tmp_path / "candidate-bundle"
    bundle.mkdir()
    candidate_zip = bundle / "candidate.zip"
    candidate_zip.write_bytes(b"sealed materialized candidate")
    candidate_sha = sha256_file(candidate_zip)
    source = _workspace(tmp_path / "source", candidate_sha256=candidate_sha)
    source_sha = _workspace_sha256(source)
    workspace = bundle / "workspace"
    shutil.copytree(source, workspace)

    overlay_manifest = {
        "schema": "TianxiaFoundry.Command4ProviderOverlayManifest.v1",
        "overlay_id": "d" * 64,
        "request_sha256": "e" * 64,
        "response_sha256": "f" * 64,
        "source_workspace_sha256": source_sha,
    }
    (workspace / "Command4_Provider_Overlay_Manifest.json").write_text(
        canonical_json(overlay_manifest), encoding="utf-8"
    )
    (workspace / "Command_4/Provider_Action_Authoring_Audit.json").write_text(
        canonical_json({"valid": True}), encoding="utf-8"
    )
    (workspace / "Validation/Command4_Provider.validation.json").write_text(
        canonical_json({"valid": True}), encoding="utf-8"
    )
    (workspace / "Build").mkdir()
    build_manifest = workspace / "Build/PACKAGE_MANIFEST.json"
    build_manifest.write_text(canonical_json({"schema_version": "test-build", "files": []}), encoding="utf-8")
    overlay = {
        **overlay_manifest,
        "manifest_sha256": sha256_file(workspace / "Command4_Provider_Overlay_Manifest.json"),
        "surface_sha256": sha256_file(workspace / "Command_4/Complete_Action_Surface.json"),
        "audit_sha256": sha256_file(workspace / "Command_4/Provider_Action_Authoring_Audit.json"),
        "validation_sha256": sha256_file(workspace / "Validation/Command4_Provider.validation.json"),
    }
    _refresh_materialized_checksums(workspace)
    overlay["overlay_tree_sha256"] = sha256_json({
        path.relative_to(workspace).as_posix(): sha256_file(path)
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and not path.relative_to(workspace).as_posix().startswith("Build/")
    })

    data_dir = tmp_path / "data"
    pointer_path = data_dir / "factory_candidates" / PROJECT_ID / "current.json"
    pointer_path.parent.mkdir(parents=True)
    pointer = {
        "project_id": PROJECT_ID,
        "status": "GM_MODEL_CANDIDATE_READY",
        "candidate_sha256": candidate_sha,
        "candidate_zip": str(candidate_zip),
        "workspace": str(workspace),
        "projection_id": PROJECTION_ID,
        "build_manifest_path": str(build_manifest),
        "build_manifest_sha256": sha256_file(build_manifest),
        "reviewed_command4_overlay": overlay,
        "character_gm_command4": {
            "workspace_sha256": source_sha,
            "reviewed_command4_overlay": overlay,
        },
    }
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    service = SimpleNamespace(
        db=SimpleNamespace(settings=SimpleNamespace(data_dir=data_dir)),
        status=lambda _project_id: {
            "available": True,
            "workspace_path": str(source),
            "workspace_sha256": source_sha,
        },
    )
    authoring = CompositeControllerAuthoring(workspace_service=service)
    assert authoring.prepare(PROJECT_ID)["candidate_sha256"] == candidate_sha

    audit_path = workspace / "Command_4/Provider_Action_Authoring_Audit.json"
    original_audit = audit_path.read_bytes()
    audit_path.write_text(canonical_json({"valid": False}), encoding="utf-8")
    _refresh_materialized_checksums(workspace)
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH"
    audit_path.write_bytes(original_audit)
    _refresh_materialized_checksums(workspace)

    build_extra = workspace / "Build/extra.json"
    build_extra.write_text(canonical_json({"tampered": True}), encoding="utf-8")
    _refresh_materialized_checksums(workspace)
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH"
    build_extra.unlink()
    _refresh_materialized_checksums(workspace)

    blueprint = workspace / "Command_1/Character_Blueprint.json"
    changed = json.loads(blueprint.read_text(encoding="utf-8"))
    changed["identity"]["display_name"] = "Unbound replacement"
    blueprint.write_text(canonical_json(changed), encoding="utf-8")
    _refresh_materialized_checksums(workspace)
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH"


@pytest.mark.parametrize("symlink_kind", ["file", "directory"])
def test_overlay_validation_and_application_reject_recursive_base_symlinks(
    tmp_path: Path, symlink_kind: str,
) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    base = Path(prepared["workspace_path"])
    if symlink_kind == "file":
        link = base / "Command_1/linked-blueprint.json"
        link.symlink_to(base / "Command_1/Character_Blueprint.json")
    else:
        link = base / "linked-command-1"
        link.symlink_to(base / "Command_1", target_is_directory=True)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=base)
    assert error.value.code == "COMPOSITE_CONTROLLER_BASE_INVALID"
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.apply_overlay(base, overlay, tmp_path / "applied")
    assert error.value.code == "COMPOSITE_CONTROLLER_BASE_INVALID"


def test_author_calls_local_provider_once_maps_exact_actions_and_writes_append_only_evidence(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    provider = _FakeProvider(_response(prepared))
    result = authoring.author(PROJECT_ID, provider, tmp_path / "server-logs")
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["purpose"] == COMPOSITE_CONTROLLER_PURPOSE
    assert call["temperature"] == 0
    assert call["expected_request_sha256"] == result["provider_request_sha256"]
    artifact = result["artifact"]
    assert artifact["schema_version"] == COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA
    assert artifact["execution_authority"] is True
    assert artifact["controller_policy_registered"] is True
    assert artifact["resource_authority"]["resource_id"] == COMPOSITE_CONTROLLER_RESOURCE_ID
    assert artifact["resource_authority"]["current"] == 1
    assert artifact["resource_authority"]["maximum"] == 45
    assert [step["action_id"] for step in artifact["composite_controller"]["sequence"]] == [
        prepared["actions"][0]["action_id"], prepared["actions"][1]["action_id"]
    ]
    assert "display_only_playbooks" not in artifact
    evidence = list((tmp_path / "server-logs/composite_controller_evidence").glob("*-attempt-*"))
    assert len(evidence) == 1
    receipt = json.loads((evidence[0] / "receipt.json").read_text())
    assert receipt["retry_count"] == 0
    assert receipt["validation_verdict"] == "PASS"
    assert receipt["candidate_sha256"] == CANDIDATE_SHA256
    assert receipt["resolution_mode"] == "local_provider"
    assert receipt["provider_call_count"] == 1
    assert artifact["provenance"]["resolution_mode"] == "local_provider"
    assert artifact["provenance"]["provider_call_count"] == 1
    assert (evidence[0] / "request_wire.json").read_bytes()

    authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "server-logs")
    evidence_after = list((tmp_path / "server-logs/composite_controller_evidence").glob("*-attempt-*"))
    assert len(evidence_after) == 2
    assert {path.name for path in evidence_after} == {f"{path.name.split('-attempt-')[0]}-attempt-{index:03d}" for index, path in enumerate(sorted(evidence_after), start=1)}


def test_materialize_delegated_seals_without_provider_and_records_selector_provenance(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    source = Path(prepared["workspace_path"])
    source_before = _workspace_sha256(source)
    response = _response(prepared)
    output_root = tmp_path / "delegated-logs"

    result = authoring.materialize_delegated(
        PROJECT_ID,
        response,
        output_root,
        selector_id="gpt-5.6-luna",
    )

    assert _workspace_sha256(source) == source_before
    assert result["resolution_mode"] == "delegated_response"
    assert result["selector_id"] == "gpt-5.6-luna"
    assert result["provider_call_count"] == 0
    provenance = result["artifact"]["provenance"]
    assert provenance["resolution_mode"] == "delegated_response"
    assert provenance["selector_id"] == "gpt-5.6-luna"
    assert provenance["provider_call_count"] == 0
    assert provenance["response_sha256"] == result["response_sha256"]
    CompositeControllerAuthoring.validate_overlay(
        Path(result["overlay_path"]),
        project_id=PROJECT_ID,
        candidate_sha256=CANDIDATE_SHA256,
        projection_id=PROJECTION_ID,
        source_workspace=source,
    )
    evidence = list((output_root / "composite_controller_evidence").glob("*-attempt-*"))
    assert len(evidence) == 1
    receipt = json.loads((evidence[0] / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["provider_id"] == "delegated_response"
    assert receipt["model"] is None
    assert receipt["resolution_mode"] == "delegated_response"
    assert receipt["selector_id"] == "gpt-5.6-luna"
    assert receipt["provider_call_count"] == 0
    assert receipt["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert receipt["completion_sha256"] is None


def test_materialize_delegated_rejects_response_and_appends_fail_without_overlay(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    response["composite_controller"]["sequence"][0]["action_token"] = "not-a-request-token"
    output_root = tmp_path / "delegated-failure-logs"

    with pytest.raises(FoundryError) as error:
        authoring.materialize_delegated(
            PROJECT_ID,
            response,
            output_root,
            selector_id="gpt-5.6-luna",
        )
    assert error.value.code == "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID"
    assert not (output_root / "composite_controller_overlays").exists()
    evidence = list((output_root / "composite_controller_evidence").glob("*-attempt-*"))
    assert len(evidence) == 1
    receipt = json.loads((evidence[0] / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["validation_verdict"] == "FAIL"
    assert receipt["resolution_mode"] == "delegated_response"
    assert receipt["provider_call_count"] == 0
    assert receipt["provider_id"] == "delegated_response"
    assert receipt["completion_sha256"] is None


def test_materialize_delegated_reuses_overlay_and_appends_each_evidence_attempt(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    output_root = tmp_path / "delegated-repeat-logs"

    first = authoring.materialize_delegated(PROJECT_ID, response, output_root, selector_id="gpt-5.6-luna")
    second = authoring.materialize_delegated(PROJECT_ID, response, output_root, selector_id="gpt-5.6-luna")

    assert second["overlay_path"] == first["overlay_path"]
    evidence = sorted((output_root / "composite_controller_evidence").glob("*-attempt-*"))
    assert [path.name.rsplit("-", 1)[-1] for path in evidence] == ["001", "002"]
    assert all(
        json.loads((path / "receipt.json").read_text(encoding="utf-8"))["provider_call_count"] == 0
        for path in evidence
    )


def test_new_delegated_overlay_keeps_legacy_provider_provenance_accepted(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "legacy-logs")
    overlay = Path(result["overlay_path"])
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["provenance"].pop("resolution_mode")
    artifact["provenance"].pop("provider_call_count")
    _rewrite_bound_controller_overlay(overlay, Path(prepared["workspace_path"]), artifact)

    validated = CompositeControllerAuthoring.validate_overlay(
        overlay,
        project_id=PROJECT_ID,
        candidate_sha256=CANDIDATE_SHA256,
        projection_id=PROJECTION_ID,
        source_workspace=Path(prepared["workspace_path"]),
    )
    assert "resolution_mode" not in validated["artifact"]["provenance"]


@pytest.mark.parametrize(
    "mutation",
    [
        "local_count_zero",
        "local_selector",
        "delegated_count_one",
        "delegated_missing_selector",
        "delegated_unsafe_selector",
        "unsupported_mode",
        "extra_field",
    ],
)
def test_overlay_rejects_invalid_explicit_provenance(tmp_path: Path, mutation: str) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    provenance = artifact["provenance"]
    if mutation == "local_count_zero":
        provenance["provider_call_count"] = 0
    elif mutation == "local_selector":
        provenance["selector_id"] = "gpt-5.6-luna"
    elif mutation == "delegated_count_one":
        provenance.update({
            "resolution_mode": "delegated_response",
            "selector_id": "gpt-5.6-luna",
            "provider_call_count": 1,
        })
    elif mutation == "delegated_missing_selector":
        provenance.update({"resolution_mode": "delegated_response", "provider_call_count": 0})
    elif mutation == "delegated_unsafe_selector":
        provenance.update({
            "resolution_mode": "delegated_response",
            "selector_id": "../escape",
            "provider_call_count": 0,
        })
    elif mutation == "unsupported_mode":
        provenance["resolution_mode"] = "unsupported"
    else:
        provenance["unexpected"] = True
    _rewrite_bound_controller_overlay(overlay, Path(prepared["workspace_path"]), artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(
            overlay,
            project_id=PROJECT_ID,
            candidate_sha256=CANDIDATE_SHA256,
            projection_id=PROJECTION_ID,
            source_workspace=Path(prepared["workspace_path"]),
        )
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID"


def test_delegated_primary_response_error_survives_bad_evidence_root(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    response["composite_controller"]["sequence"][0]["action_token"] = "not-a-request-token"
    bad_root = tmp_path / "evidence-file"
    bad_root.write_text("occupied", encoding="utf-8")

    with pytest.raises(FoundryError) as error:
        authoring.materialize_delegated(
            PROJECT_ID,
            response,
            bad_root,
            selector_id="gpt-5.6-luna",
        )

    assert error.value.code == "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID"
    assert error.value.status_code == 400
    assert isinstance(error.value.details, dict)
    assert error.value.details["cause"]
    assert error.value.details["evidence_error"]["code"] == "COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID"
    assert error.value.details["evidence_error"]["exception_type"] == "FoundryError"
    assert bad_root.read_text(encoding="utf-8") == "occupied"


def test_author_rejects_structurally_invalid_output_before_local_provider_call(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    provider = _FakeProvider(_response(prepared))
    bad_root = tmp_path / "output-file"
    bad_root.write_text("occupied", encoding="utf-8")

    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, provider, bad_root)

    assert error.value.code == "COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID"
    assert provider.calls == []
    assert bad_root.read_text(encoding="utf-8") == "occupied"


def test_author_rejects_symlinked_output_root_before_local_provider_call(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    provider = _FakeProvider(_response(prepared))
    outside = tmp_path / "outside"
    outside.mkdir()
    bad_root = tmp_path / "output-link"
    bad_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, provider, bad_root)

    assert error.value.code == "COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID"
    assert provider.calls == []
    assert not (outside / "composite_controller_overlays").exists()


def test_local_provider_error_survives_output_root_occupancy_during_call(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    output_root = tmp_path / "logs"
    output_root.mkdir()

    class _FailingProviderThatOccupiesRoot(_FakeProvider):
        def complete_json(self, **kwargs):
            self.calls.append(kwargs)
            output_root.rmdir()
            output_root.write_text("occupied", encoding="utf-8")
            raise RuntimeError("provider unavailable")

    provider = _FailingProviderThatOccupiesRoot(_response(prepared))
    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, provider, output_root)

    assert error.value.code == "COMPOSITE_CONTROLLER_PROVIDER_FAILED"
    assert error.value.status_code == 502
    assert isinstance(error.value.details, dict)
    assert error.value.details["cause"]
    assert error.value.details["evidence_error"]["code"] == "COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID"
    assert error.value.details["evidence_error"]["exception_type"] == "FoundryError"
    assert len(provider.calls) == 1
    assert output_root.read_text(encoding="utf-8") == "occupied"


def test_success_evidence_path_failure_is_typed_and_not_misreported(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    output_root = tmp_path / "logs"
    output_root.mkdir()
    (output_root / "composite_controller_evidence").write_text("occupied", encoding="utf-8")

    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), output_root)

    assert error.value.code == "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID"
    assert error.value.status_code == 400
    assert (output_root / "composite_controller_evidence").read_text(encoding="utf-8") == "occupied"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("candidate_sha256", "COMPOSITE_CONTROLLER_LINEAGE_MISMATCH"),
        ("raw_action_token", "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID"),
        ("step", "COMPOSITE_CONTROLLER_SEQUENCE_NUMBER_INVALID"),
        ("extra", "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID"),
        ("fallback", "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE"),
    ],
)
def test_response_contract_rejects_lineage_economy_sequence_state_extra_and_fallback_errors(
    tmp_path: Path, mutation: str, code: str,
) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    controller = response["composite_controller"]
    if mutation == "candidate_sha256":
        response["candidate_sha256"] = "d" * 64
    elif mutation == "raw_action_token":
        controller["sequence"][0]["action_token"] = prepared["actions"][0]["action_id"]
    elif mutation == "economy":
        controller["sequence"][0]["economy"] = "reaction"
    elif mutation == "step":
        controller["sequence"][1]["step"] = 3
    elif mutation == "state":
        controller["sequence"][0]["requires_states"] = ["Not sealed"]
    elif mutation == "extra":
        response["unexpected"] = True
    elif mutation == "fallback":
        controller["fallback"]["action_token"] = prepared["action_tokens"][1]
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == code


def test_step_economy_and_unknown_states_are_derived_not_trusted(tmp_path: Path) -> None:
    # A step's economy is its action's, and a state the character lacks is
    # not a precondition; the server derives both (MiMo builds 5 and 12).
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    step = response["composite_controller"]["sequence"][0]
    expected = authoring._validate_response(prepared, deepcopy(response))["composite_controller"]["sequence"][0]
    step["economy"] = "reaction"
    step["requires_states"] = ["Not sealed"]
    repaired = authoring._validate_response(prepared, response)["composite_controller"]["sequence"][0]
    assert repaired["economy"] == expected["economy"]
    assert repaired.get("requires_states", []) == expected.get("requires_states", [])


def test_response_rejects_overspend_and_requires_zero_cost_fallback_at_current_one(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared, budget=0)
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_BUDGET_EXCEEDED"

    response = _response(prepared, fallback_index=1)
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE"


def test_response_rejects_duplicate_economy_in_one_round_and_unaffordable_intrinsic_action(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    response = _response(prepared)
    response["composite_controller"]["sequence"][1]["round_offset"] = 0
    # A second step overfilling its economy in a round moves to the next
    # round with room (LFM CPU build 16) rather than failing authoring.
    repaired = authoring._validate_response(prepared, response)["composite_controller"]["sequence"]
    assert repaired[1]["round_offset"] > repaired[0]["round_offset"]

    response = _response(prepared)
    sequence = response["composite_controller"]["sequence"]
    sequence[0]["action_token"] = prepared["action_tokens"][2]
    sequence[0]["round_offset"] = 0
    sequence[1]["action_token"] = prepared["action_tokens"][3]
    sequence[1]["round_offset"] = 1
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_RESOURCE_UNAVAILABLE"


def test_fallback_checks_action_intrinsic_state_and_resource_requirements(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    token = prepared["action_tokens"][0]
    prepared["token_to_action"][token]["requires_states"] = ["Unsealed state"]
    response = _response(prepared)
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, response)
    assert error.value.code == "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE"

    prepared["token_to_action"][token]["requires_states"] = []
    prepared["token_to_action"][token]["resource_requirements"] = [{"resource_id": "RES_CP", "minimum": 2}]
    with pytest.raises(FoundryError) as error:
        authoring._validate_response(prepared, _response(prepared))
    assert error.value.code == "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE"


def test_provider_is_local_only_and_failure_is_one_call_with_append_only_failed_receipt(tmp_path: Path) -> None:
    authoring, _prepared_value = _prepared(tmp_path)

    class NonLocal(_FakeProvider):
        def _settings(self) -> dict:
            return {"provider_id": "deepseek", "model": "not-used"}

    nonlocal_provider = NonLocal()
    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, nonlocal_provider, tmp_path / "nonlocal-logs")
    assert error.value.code == "COMPOSITE_CONTROLLER_LOCAL_PROVIDER_REQUIRED"
    assert nonlocal_provider.calls == []

    failing = _FakeProvider(failure=RuntimeError("provider unavailable"))
    with pytest.raises(FoundryError) as error:
        authoring.author(PROJECT_ID, failing, tmp_path / "failure-logs")
    assert error.value.code == "COMPOSITE_CONTROLLER_PROVIDER_FAILED"
    assert len(failing.calls) == 1
    evidence = list((tmp_path / "failure-logs/composite_controller_evidence").glob("*-attempt-*"))
    assert len(evidence) == 1
    receipt = json.loads((evidence[0] / "receipt.json").read_text())
    assert receipt["retry_count"] == 0
    assert receipt["validation_verdict"] == "FAIL"
    assert receipt["error_code"] == "COMPOSITE_CONTROLLER_PROVIDER_FAILED"


def test_overlay_validation_and_application_are_deterministic_and_preserve_legacy_playbook(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_SOURCE_REQUIRED"
    validated = CompositeControllerAuthoring.validate_overlay(
        overlay,
        project_id=PROJECT_ID,
        candidate_sha256=CANDIDATE_SHA256,
        projection_id=PROJECTION_ID,
        source_workspace=Path(prepared["workspace_path"]),
    )
    assert "display_only_playbooks" not in validated["artifact"]
    base_before = (Path(prepared["workspace_path"]) / "Command_4/Composite_Playbooks.json").read_bytes()
    applied = CompositeControllerAuthoring.apply_overlay(Path(prepared["workspace_path"]), overlay, tmp_path / "applied")
    assert applied.is_dir()
    assert json.loads((applied / "Command_4/Composite_Controller_Artifact.json").read_text())["execution_authority"] is True
    assert (applied / "Command_4/Composite_Playbooks.json").read_bytes() == base_before
    assert (Path(prepared["workspace_path"]) / "Command_4/Composite_Playbooks.json").read_bytes() == base_before


def test_pre_removal_saved_overlay_with_playbook_fields_still_applies(tmp_path: Path) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    source = Path(prepared["workspace_path"])
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    playbooks = json.loads((source / "Command_4/Composite_Playbooks.json").read_text(encoding="utf-8"))["playbooks"]
    artifact["display_only_playbooks"] = playbooks
    artifact["provenance"]["legacy_playbook_preserved"] = True
    _rewrite_bound_controller_overlay(overlay, source, artifact)

    applied = CompositeControllerAuthoring.apply_overlay(source, overlay, tmp_path / "legacy-applied")
    assert applied.is_dir()
    saved = json.loads((applied / "Command_4/Composite_Controller_Artifact.json").read_text(encoding="utf-8"))
    assert saved["display_only_playbooks"] == playbooks
    assert (applied / "Command_4/Composite_Playbooks.json").is_file()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requires_states", ["Unavailable state"]),
        ("resource_requirements", [{"resource_id": COMPOSITE_CONTROLLER_RESOURCE_ID, "minimum": 2}]),
    ],
)
def test_overlay_revalidation_rederives_fallback_intrinsic_legality_from_bound_workspace(
    tmp_path: Path, field: str, value: list[dict[str, object]] | list[str],
) -> None:
    authoring, prepared = _prepared(tmp_path)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])
    base = Path(prepared["workspace_path"])

    source_path = base / "Command_4/Complete_Action_Surface.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    target_action_id = prepared["actions"][0]["action_id"]
    source_action = next(row for row in source["actions"] if row["action_id"] == target_action_id)
    source_action[field] = value
    source_path.write_text(canonical_json(source), encoding="utf-8")
    _refresh_checksums(base)

    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    for action in artifact["linked_actions"]:
        if action["action_id"] == target_action_id:
            action[field] = value
    controller = artifact["composite_controller"]
    for action in controller["linked_actions"]:
        if action["action_id"] == target_action_id:
            action[field] = value
    for step in controller["sequence"]:
        if step["action_id"] == target_action_id:
            step["action"][field] = value
    controller["fallback"]["action"][field] = value
    from factory_authoring.composite_controller import _overlay_validation_payload

    artifact["source_workspace_sha256"] = _workspace_sha256(base)
    artifact_sha = sha256_json(artifact)
    manifest_path = overlay / "Composite_Controller_Overlay_Manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "source_workspace_sha256": artifact["source_workspace_sha256"],
        "artifact_sha256": artifact_sha,
        "overlay_id": sha256_json({
            "source_workspace_sha256": artifact["source_workspace_sha256"],
            "base_candidate_sha256": artifact["base_candidate_sha256"],
            "artifact_sha256": artifact_sha,
        }),
    })
    _write = lambda path, payload: path.write_text(canonical_json(payload), encoding="utf-8")
    _write(artifact_path, artifact)
    _write(manifest_path, manifest)
    _write(overlay / "Validation/Composite_Controller.validation.json", _overlay_validation_payload(artifact, artifact_sha))
    _refresh_checksums(overlay)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=base)
    assert error.value.code == "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE"


def test_overlay_replay_rejects_two_cp_steps_after_self_consistent_current_rebind(tmp_path: Path) -> None:
    root = _workspace(tmp_path, resource_current=2)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][0]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][2]["resource_costs"] = []
    surface["actions"][2]["cost"] = "None"
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _response(prepared, budget=2, fallback_index=2)
    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"][0]["current"]["value"] = 1
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["resource_authority"]["current"] = 1
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_UNAVAILABLE"


def test_overlay_replay_revalidates_conditional_affordability_after_resource_change(tmp_path: Path) -> None:
    root = _workspace(tmp_path, resource_current=1)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    for index in (0, 1):
        surface["actions"][index]["resource_costs"] = []
        surface["actions"][index]["cost"] = "None"
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _response(prepared, budget=1)
    response["composite_controller"]["conditional_options"] = [{
        "action_token": prepared["action_tokens"][2],
        "when": "The current stance is unavailable.",
        "priority": 1,
    }]
    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"][0]["current"]["value"] = 0
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["resource_authority"]["current"] = 0
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_UNAVAILABLE"


def test_overlay_replay_applies_source_bound_gain_before_next_step_after_rebind(tmp_path: Path) -> None:
    root = _workspace(tmp_path, resource_current=2, resource_maximum=2)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][0]["cost"] = "1 CP"
    surface["actions"][0]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][0]["resource_gains"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][2]["cost"] = "None"
    surface["actions"][2]["resource_costs"] = []
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _response(prepared, budget=2, fallback_index=2)
    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"][0]["current"]["value"] = 1
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["resource_authority"]["current"] = 1
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    validated = CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert validated["artifact"]["resource_authority"]["current"] == 1


def test_overlay_replay_rejects_ordered_requirement_after_prior_cost_rebind(tmp_path: Path) -> None:
    root = _workspace(tmp_path, resource_current=2)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][0]["cost"] = "1 CP"
    surface["actions"][0]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][1]["cost"] = "None"
    surface["actions"][1]["resource_costs"] = []
    surface["actions"][1]["resource_requirements"] = [{"resource_id": "RES_CP", "minimum": 1}]
    surface["actions"][2]["cost"] = "None"
    surface["actions"][2]["resource_costs"] = []
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _response(prepared, budget=1, fallback_index=2)
    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"][0]["current"]["value"] = 1
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["resource_authority"]["current"] = 1
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_ACTION_PREREQUISITE_UNAVAILABLE"


def test_overlay_replay_rejects_rebound_intrinsic_state_not_in_source_authority(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    target_action_id = surface["actions"][1]["action_id"]
    surface["actions"][1]["requires_states"] = ["Marked"]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    result = authoring.author(PROJECT_ID, _FakeProvider(_response(prepared)), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    source = json.loads(surface_path.read_text(encoding="utf-8"))
    source["actions"][1]["requires_states"] = ["Not sealed"]
    surface_path.write_text(canonical_json(source), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    _replace_artifact_action_field(artifact, target_action_id, "requires_states", ["Not sealed"])
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID"


def test_overlay_replay_rejects_rebound_maximum_and_budget_mismatch(tmp_path: Path) -> None:
    root = _workspace(tmp_path, resource_current=2, resource_maximum=3)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"][0]["cost"] = "1 CP"
    surface["actions"][0]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][1]["cost"] = "1 CP"
    surface["actions"][1]["resource_costs"] = [{"resource_id": "RES_CP", "amount": 1}]
    surface["actions"][2]["cost"] = "None"
    surface["actions"][2]["resource_costs"] = []
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    prepared = authoring.prepare(PROJECT_ID)
    response = _response(prepared, budget=2, fallback_index=2)
    result = authoring.author(PROJECT_ID, _FakeProvider(response), tmp_path / "logs")
    overlay = Path(result["overlay_path"])

    resource_path = root / "Command_2/Canonical_Stats_Resource_Block.json"
    resource_block = json.loads(resource_path.read_text(encoding="utf-8"))
    resource_block["resources"][0]["current"]["value"] = 1
    resource_block["resources"][0]["maximum"]["value"] = 1
    resource_path.write_text(canonical_json(resource_block), encoding="utf-8")
    _refresh_checksums(root)
    artifact_path = overlay / "Command_4/Composite_Controller_Artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["resource_authority"]["current"] = 1
    artifact["resource_authority"]["maximum"] = 1
    artifact["composite_controller"]["resource_budget"]["max_spend"] = 1
    _rewrite_bound_controller_overlay(overlay, root, artifact)

    with pytest.raises(FoundryError) as error:
        CompositeControllerAuthoring.validate_overlay(overlay, source_workspace=root)
    assert error.value.code == "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID"


def test_service_exposes_explicit_composite_endpoint_method_without_implicit_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = SimpleNamespace(settings=SimpleNamespace(logs_dir=tmp_path / "logs"))
    seen: dict[str, object] = {}

    def fake_author(self, project_id, provider, output_root):
        seen.update({"project_id": project_id, "provider": provider, "output_root": output_root})
        return {"valid": True}

    monkeypatch.setattr(CompositeControllerAuthoring, "author", fake_author)
    provider = object()
    assert service.author_composite_controller(PROJECT_ID, provider) == {"valid": True}
    assert seen == {
        "project_id": PROJECT_ID,
        "provider": provider,
        "output_root": (tmp_path / "logs/factory_composite_controller").resolve(),
    }


def test_composite_controller_endpoint_is_explicit_and_has_no_client_output_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    app = create_app(Settings.from_env(root, tmp_path / "data"))
    calls: list[tuple[str, object]] = []

    def fake_author(project_id, provider):
        calls.append((project_id, provider))
        return {"valid": True, "target": "composite_controller"}

    app.state.factory_authoring.author_composite_controller = fake_author
    headers = {"x-foundry-token": app.state.session_token}
    with TestClient(app) as client:
        response = client.post(
            "/api/characters/project.endpoint/factory-workspace/composite-controller-author?output_root=/tmp/ignored",
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json() == {"valid": True, "target": "composite_controller"}
    assert calls == [("project.endpoint", app.state.ai_provider)]


def test_too_few_actions_can_still_author_themes_when_the_caller_opts_in(tmp_path: Path) -> None:
    # A Death/Athletics character had one executable action (build 22): the
    # combat plan is impossible, but its Dao and I Ching are still authored.
    root = _workspace(tmp_path)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["actions"] = surface["actions"][:1]
    surface_path.write_text(canonical_json(surface), encoding="utf-8")
    _refresh_checksums(root)
    authoring = CompositeControllerAuthoring(workspace_root=root)
    with pytest.raises(FoundryError) as error:
        authoring.prepare(PROJECT_ID)
    assert error.value.code == "COMPOSITE_CONTROLLER_ACTIONS_INCOMPLETE"
    records = [{"record": {"record_id": "TAL_TEST", "display_name": "Test Talent", "one_line_description": "A test."}}]
    prepared = authoring.prepare(PROJECT_ID, theme_records=records, allow_theme_only=True)
    assert prepared["theme_only"] is True and prepared["action_tokens"] == []
    assert "composite_controller" not in prepared["response_schema"]["properties"]
    theme = {
        "display_name": "Grave Dao", "core_theme": "Graves remember", "principles": ["a", "b"],
        "strengths": ["c", "d"], "risks": ["e", "f"], "roleplay_expression": "g",
        "tactical_expression": "h", "gm_usage_notes": "i", "relevant_record_ids": ["TAL_TEST"],
        "mechanical_effects": [],
    }
    response = {
        "schema": COMPOSITE_CONTROLLER_SCHEMA, "project_id": prepared["project_id"],
        "projection_id": prepared["projection_id"], "candidate_sha256": prepared["candidate_sha256"],
        "request_sha256": prepared["request_sha256"], "gm_themes": {"dao": theme, "i_ching": dict(theme, display_name="Hexagram 2")},
    }
    validated = authoring._validate_response(prepared, response)
    assert "composite_controller" not in validated and validated["gm_themes"]["dao"]["display_name"] == "Grave Dao"
