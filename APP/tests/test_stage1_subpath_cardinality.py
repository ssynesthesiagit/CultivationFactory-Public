from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import stage1.service as stage1_service
from contracts.registry import SchemaRegistry
from stage1.service import SLOT_SPECS, Stage1ClipboardService


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, *_args):
        return self

    def fetchone(self):
        return {"pack_hash": "pack-hash"}


class _Database:
    def connection(self):
        return _Connection()


class _Coverage:
    def build(self, *, project_id):
        return {
            "report_hash": "coverage-hash",
            "categories": [
                {
                    "slot_id": spec["slot_id"],
                    "selectable_record_ids": [],
                    "intent_selectable_record_ids": [],
                    "blocked_reasons": [],
                }
                for spec in SLOT_SPECS
            ],
        }


class _Catalog:
    def effective_catalog(self, project_id):
        return {"records": []}


class _Authority:
    method_registry_commitment_sha256 = "method-registry-hash"

    def __init__(self, _db):
        pass

    def method_catalog(self, *, initial_creation):
        return {"records": []}


def _service(monkeypatch, target_cl: int) -> Stage1ClipboardService:
    project = {
        "project_id": "stage1-subpath-test",
        "revision": 4,
        "content_lock": {"catalog_build_id": "catalog", "lock_hash": "content-lock"},
        "user_locks": [{"field": "target_cl", "value": target_cl}],
    }
    service = object.__new__(Stage1ClipboardService)
    service.db = _Database()
    service.coverage = _Coverage()
    service.catalog = _Catalog()
    service.projects = SimpleNamespace(project_lock_proof=lambda _conn, _project_id: {})
    service._project = lambda _project_id: deepcopy(project)
    service._validate_contract = lambda *_args: None
    # 283e3174 freezes Background package talents under the project lock
    # proof; this catalog has no Background records, so only the proof runs.
    service.projects = SimpleNamespace(
        project_lock_proof=lambda _conn, _project_id: None,
        _resolve_project_locked_background_after_proof=lambda *_args: None,
    )
    monkeypatch.setattr(stage1_service, "NonSphereAuthorityService", _Authority)
    return service


def test_stage1_subpath_minimum_is_zero_before_authenticated_selection_level(monkeypatch):
    for target_cl, expected_minimum in ((1, 0), (3, 1)):
        envelope = _service(monkeypatch, target_cl).build_envelope("stage1-subpath-test")
        slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "subpath_choice")
        assert slot["min_selections"] == expected_minimum
        assert slot["max_selections"] == 3
        assert slot["allow_none"] is True


def test_stage1_v2_schema_accepts_zero_but_rejects_negative_minimum():
    envelope = {
        "schema_version": "TianxiaFoundry.Stage1PromptEnvelope.v2",
        "prompt_id": "stage1.prompt.subpath-test",
        "project_id": "stage1-subpath-test",
        "project_revision": 4,
        "catalog_build_id": "catalog",
        "content_lock_hash": "0" * 64,
        "stage_id": "stage_1_source_blueprint",
        "user_locks": [{"field": "target_cl", "value": 1}],
        "decision_slots": [{
            "slot_id": "subpath_choice",
            "label": "Subpaths or Traditions",
            "min_selections": 0,
            "max_selections": 3,
            "allow_none": True,
            "coverage_state": "offered",
            "choices": [],
        }],
        "decision_state_contract": [
            "selected",
            "explicit_none",
            "blocked_missing_authority",
            "deferred_with_reason",
        ],
        "authored_fields": [],
        "forbidden_authority_rules": [],
        "response_schema_version": "TianxiaFoundry.AIClipboard.Stage1.v2",
    }
    registry = SchemaRegistry(Path(__file__).resolve().parents[1])
    valid = registry.report(envelope, "TianxiaFoundry.Stage1PromptEnvelope.v2")
    assert valid["valid"] is True

    negative = deepcopy(envelope)
    negative["decision_slots"][0]["min_selections"] = -1
    invalid = registry.report(negative, "TianxiaFoundry.Stage1PromptEnvelope.v2")
    assert invalid["valid"] is False
    assert any(
        diagnostic["validator"] == "minimum"
        and diagnostic["pointer"].endswith("/min_selections")
        for diagnostic in invalid["diagnostics"]
    )
