from __future__ import annotations

import json
import re
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterator

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json, utcnow
from contracts.canonical import ZERO_HASH, canonical_event_hash, canonical_project_document, canonical_project_hash, canonical_record_hash
from contracts.registry import SchemaRegistry
from project_store.service import ProjectStore
from catalog_choice_authority import committed_catalog_grant_plan
from security.approval_challenges import ApprovalChallengeService
from security.integrity import IntegrityService
from security.local_identity import PrincipalProvider, ProcessPrincipalProvider, reject_reserved_identity
from stage2.authority_contract import (
    RECORDED_ART_EXPRESSION_KINDS,
    allowed_content_types_for_kind,
    recorded_art_expression_issues,
)
from stage2.formulas import FormulaError, evaluate_formula
from stage2.insight_authority import insight_occurrence_index
from sphere_component_authority import attach_sphere_automatic_component_receipt, normalize_sphere_automatic_components
from stage2.legacy_service import (
    Stage2AdvancementService as LegacyStage2AdvancementService,
    _ability_modifier,
    _pb,
    _block,
    _none,
)

EVENT_V3 = "TianxiaFoundry.AdvancementEvent.v3"
PROPOSAL_V2 = "TianxiaFoundry.Stage2AdvancementProposal.v2"
LEDGER_V2 = "TianxiaFoundry.LevelingLedger.v2"
TRAINING_V2 = "TianxiaFoundry.Stage2TrainingTransaction.v2"
TERMINAL_RECEIPT_DOMAIN = "tianxia.foundry.stage2.terminal_commit.v1"
REBUILD_RECEIPT_DOMAIN = "tianxia.foundry.stage2.rebuild.v1"
PLACEHOLDER_RE = re.compile(r"(?:not recorded|not itemized|unnamed talent|unknown|tbd|placeholder)", re.I)

_COMMIT_LOCKS_GUARD = threading.Lock()
_COMMIT_LOCKS: dict[str, threading.RLock] = {}
_TRUSTED_CHARACTER_CREATION_EXECUTION = object()


@dataclass(frozen=True, slots=True)
class _InitialCreationExecutionContext:
    run_id: str
    project_id: str
    starting_revision: int
    content_lock_hash: str
    typed_choice_snapshot_sha256: str
    phase: str
    candidate_identity: str | None


_INITIAL_CREATION_EXECUTION: ContextVar[_InitialCreationExecutionContext | None] = ContextVar(
    "tianxia_stage2_initial_creation_execution", default=None,
)


def _commit_lock(proposal_id: str) -> threading.RLock:
    with _COMMIT_LOCKS_GUARD:
        return _COMMIT_LOCKS.setdefault(proposal_id, threading.RLock())

UNIQUE_COLLECTIONS = {
    "known_spheres": "sphere",
    "known_talents": "talent",
    "recorded_arts": "recorded_art",
    "equipment": "item",
}

HF1_KINDS = {
    "starting_state",
    "background_acquisition",
    "background_sphere_acquisition",
    "background_talent_acquisition",
    "origin_insight_acquisition",
    "path_acquisition",
    "sect_trial_sphere_acquisition",
    "sect_trial_talent_acquisition",
    "ai_bootstrap_sphere_acquisition",
    "ai_bootstrap_talent_acquisition",
    "level_advance",
    "ability_score_change",
    "cultivation_insight_acquisition",
    "level_talent_acquisition",
    "subpath_acquisition",
    "method_acquisition",
    "method_activation",
    "foundation_acquisition",
    "foundation_expression",
    "foundation_stage",
    "sphere_training_attempt",
    "talent_training_attempt",
    "manual_training_attempt",
    "training_source_access",
    "new_sphere_bonus_talent_acquisition",
    "equipment_acquisition",
    "printed_rule_grant",
    "forged_technique_creation",
    "typed_none",
}

# These are proposal inputs, not canonical event details.  Known calculated
# output names remain listed only so the runtime can return a precise tamper
# blocker; they are never copied into an Advancement Event.
KIND_PARAMETER_KEYS: dict[str, frozenset[str]] = {
    "starting_state": frozenset({"ability_scores"}),
    "background_acquisition": frozenset({"ability", "amount"}),
    "background_sphere_acquisition": frozenset(),
    "background_talent_acquisition": frozenset(),
    "origin_insight_acquisition": frozenset(),
    "cultivation_insight_acquisition": frozenset({"ability", "amount", "repeat_index"}),
    "path_acquisition": frozenset(),
    "sect_trial_sphere_acquisition": frozenset(),
    "sect_trial_talent_acquisition": frozenset(),
    "ai_bootstrap_sphere_acquisition": frozenset(),
    "ai_bootstrap_talent_acquisition": frozenset(),
    "level_advance": frozenset(),
    "ability_score_change": frozenset({"deltas"}),
    "level_talent_acquisition": frozenset(),
    "subpath_acquisition": frozenset(),
    "method_acquisition": frozenset(),
    "method_activation": frozenset({"refill_current"}),
    "foundation_acquisition": frozenset(),
    "foundation_expression": frozenset(),
    "foundation_stage": frozenset({"stage"}),
    "training_source_access": frozenset({"access_mode"}),
    "sphere_training_attempt": frozenset({"attempt_id", "retry_of_attempt_id", "training_source_record_id", "selected_ability", "time_die_result", "dc_die_result", "check_die_result"}),
    "talent_training_attempt": frozenset({"attempt_id", "retry_of_attempt_id", "training_source_record_id", "selected_ability", "time_die_result", "dc_die_result", "check_die_result"}),
    "manual_training_attempt": frozenset({"attempt_id", "retry_of_attempt_id", "training_source_record_id", "selected_ability", "time_die_result", "dc_die_result", "check_die_result"}),
    "new_sphere_bonus_talent_acquisition": frozenset({"entitlement_event_id", "entitlement_attempt_id"}),
    "equipment_acquisition": frozenset(),
    "printed_rule_grant": frozenset(),
    "forged_technique_creation": frozenset({"prewritten_record_id"}),
    "typed_none": frozenset({"target", "reason_code", "reason"}),
}

CREATION_KINDS = {
    "starting_state",
    "background_acquisition",
    "background_sphere_acquisition",
    "background_talent_acquisition",
    "origin_insight_acquisition",
    "path_acquisition",
    "sect_trial_sphere_acquisition",
    "sect_trial_talent_acquisition",
    "ai_bootstrap_sphere_acquisition",
    "ai_bootstrap_talent_acquisition",
}

TYPED_NONE_TARGETS = {
    "method",
    "foundation",
    "manuals",
    "equipment",
    "subpaths",
    "forged_techniques",
}


def _canonical_event_details(kind: str, details: dict[str, Any]) -> dict[str, Any]:
    """Return only replay-required, validated facts for the canonical event."""
    if kind == "foundation_expression":
        return {
            "foundation_record_id": details["foundation_record_id"],
            "path_id": details["path_id"],
        }
    if kind == "foundation_stage":
        return {"stage": details["stage"]}
    if kind == "new_sphere_bonus_talent_acquisition":
        return {"entitlement_event_id": details["entitlement_event_id"]}
    if kind == "cultivation_insight_acquisition":
        return {
            key: details[key]
            for key in ("ability", "amount", "repeat_index")
            if key in details
        }
    if kind == "typed_none":
        return {"target": details["target"]}
    return {}


def _state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.Stage2RulesCausalState.v1",
        "project_id": project_id,
        "current_cl": 0,
        "completed_levels": [],
        "pb": None,
        "ability_scores": {},
        "ability_modifiers": {},
        "ability_authority_event_id": None,
        "ability_authority_record_id": None,
        "hp": {"total": 0, "last_gain": 0, "last_formula_id": None, "components": []},
        "resources": {},
        "background": None,
        "background_sphere": None,
        "background_talent": None,
        "origin_insight": None,
        "sect_trial_sphere": None,
        "sect_trial_talent": None,
        "ai_bootstrap_sphere": None,
        "ai_bootstrap_talent": None,
        "subpath_features": [],
        "paths": [],
        "subpaths": [],
        "cultivation_insights": [],
        "cultivation_insight_occurrences": [],
        "method": _none("not_acquired", "No Method acquisition event exists."),
        "foundation": _none("not_acquired", "No Foundation acquisition event exists."),
        "known_spheres": [],
        "known_talents": [],
        "recorded_arts": [],
        "forged_techniques": {"state": "unresolved", "reason": "No causal Forged Technique or typed absence event has been applied."},
        "equipment": [],
        "training_sources": [],
        "level_talents": {},
        "training_transactions": {},
        "trained_success_cost": {},
        "new_sphere_entitlements": [],
        "event_ids": [],
        "record_event_ids": {},
        "authority_snapshots": {},
        "automatic_sphere_component_receipts": [],
        "automatic_sphere_components": [],
        "typed_none_states": {},
        "event_occurrences": {},
        "required_milestones": [],
    }


def _deepcopy(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _ptr(value: str) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _leaf_pointers(value: Any, pointer: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        if not value:
            out.append(pointer or "/")
        else:
            for key, child in value.items():
                out.extend(_leaf_pointers(child, f"{pointer}/{_ptr(key)}"))
    elif isinstance(value, list):
        if not value:
            out.append(pointer or "/")
        else:
            for index, child in enumerate(value):
                out.extend(_leaf_pointers(child, f"{pointer}/{index}"))
    else:
        out.append(pointer or "/")
    return out


def _point_buy_cost(score: int) -> int:
    table = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
    if score not in table:
        raise ValueError(score)
    return table[score]


def _authority(record: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {})


def _source(record: dict[str, Any]) -> dict[str, Any]:
    src = record["source"]
    return {
        "source_id": src["source_id"],
        "source_hash": src["source_hash"],
        "source_anchor": src["anchor"],
        "source_path": src.get("path", ""),
    }


def _binding(record: dict[str, Any], role: str, causal_event_id: str | None) -> dict[str, Any]:
    src = record["source"]
    bind = record["content_binding"]
    return {
        "role": role,
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "pack_id": bind["pack_id"],
        "pack_version": bind["pack_version"],
        "pack_hash": bind["pack_hash"],
        "source_id": src["source_id"],
        "source_hash": src["source_hash"],
        "source_anchor": src["anchor"],
        "source_path": src.get("path", ""),
        "causal_event_id": causal_event_id,
    }


def _formula_value(formula: dict[str, Any], context: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if formula.get("schema_version") != "TianxiaFoundry.SafeFormula.v1":
        raise FormulaError("formula does not declare TianxiaFoundry.SafeFormula.v1")
    result = evaluate_formula(formula["root"], context)
    return result.value, result.trace


def _formula_trace_text(trace: dict[str, Any]) -> str:
    """Render an evaluated SafeFormula trace as unambiguous human arithmetic."""
    node = trace.get("root", trace)

    def walk(value: dict[str, Any]) -> str:
        op = value.get("op")
        resolved = value.get("value")
        if op == "constant":
            return str(resolved)
        if op == "cl":
            return f"CL {resolved}"
        if op == "pb":
            return f"PB {resolved:+d}"
        if op == "ability_score":
            return f"{value['ability']} score {resolved}"
        if op == "ability_modifier":
            return f"{value['ability']} modifier {resolved:+d}"
        if op == "selected_path_base":
            return f"path base {value['key']} {resolved}"
        if op in {"add", "multiply", "minimum", "maximum"}:
            symbol = {"add": " + ", "multiply": " × "}.get(op)
            terms = [walk(term) for term in value.get("terms", [])]
            if symbol:
                return f"({symbol.join(terms)}) = {resolved}"
            label = "min" if op == "minimum" else "max"
            return f"{label}({', '.join(terms)}) = {resolved}"
        if op == "subtract":
            return f"({walk(value['left'])} - {walk(value['right'])}) = {resolved}"
        if op == "clamp":
            bounds = f"{value.get('minimum') if value.get('minimum') is not None else '-∞'}..{value.get('maximum') if value.get('maximum') is not None else '+∞'}"
            return f"clamp({walk(value['value_node'])}, {bounds}) = {resolved}"
        return f"{op or 'formula'} = {resolved}"

    return walk(node)


def _formula_trace_ability(trace: dict[str, Any]) -> str | None:
    """Return the first ability used by an evaluated formula trace."""
    def walk(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        if value.get("op") in {"ability_score", "ability_modifier"}:
            return value.get("ability")
        for key in ("terms",):
            for child in value.get(key, []) if isinstance(value.get(key), list) else []:
                found = walk(child)
                if found:
                    return found
        for key in ("left", "right", "value_node", "root"):
            found = walk(value.get(key))
            if found:
                return found
        return None

    return walk(trace)


def _dm_line_label(value: str) -> str:
    """Keep the em dash reserved as the Recorded-Art grammar delimiter."""
    return " ".join(str(value).replace("—", "-").replace("–", "-").split())


def _sort_unique(values: list[str]) -> list[str]:
    return sorted(set(values))


def _sphere_record_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Reconstruct the locked Sphere authority needed by replay.

    The event calculation carries the signed/static normalized packet.  The
    reducer deliberately reconstructs only this narrow record shape instead
    of re-reading a mutable catalog during replay.
    """
    outputs = event.get("advancement", {}).get("calculation", {}).get("outputs") or {}
    packet = outputs.get("automatic_component_authority")
    if not isinstance(packet, dict):
        return None
    subject = event.get("subject") or {}
    binding = event.get("content_binding") or {}
    evidence = (event.get("source_evidence") or [{}])[0]
    return {
        "record_id": subject.get("record_id"),
        "record_hash": binding.get("record_hash"),
        "source": {
            "source_id": evidence.get("source_id"),
            "source_hash": evidence.get("source_hash"),
            "anchor": evidence.get("source_anchor"),
            "path": evidence.get("source_path", ""),
        },
        "automatic_component_authority": deepcopy(packet),
    }


def _attach_sphere_components_from_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    record = _sphere_record_from_event(event)
    if record is not None:
        attach_sphere_automatic_component_receipt(state, record, event)


class RulesCausalStage2Service:
    """Phase 4A-HF1 deterministic rules-causal Stage 2 implementation."""

    def __init__(self, db: Database, *, principal_provider: PrincipalProvider | None = None, integrity: IntegrityService | None = None):
        self.db = db
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.integrity = integrity or IntegrityService.for_database(db)
        self.projects = ProjectStore(db, integrity=self.integrity)
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.challenges = ApprovalChallengeService(db, self.principal_provider, self.integrity)

    @contextmanager
    def _trusted_character_creation_scope(
        self,
        *,
        run_id: str,
        project_id: str,
        starting_revision: int,
        content_lock_hash: str,
        typed_choice_snapshot_sha256: str,
        phase: str,
        candidate_identity: str | None,
        _server_authority: object | None = None,
    ) -> Iterator[None]:
        """Bind a private server execution scope without creating provenance.

        The scope is process-local, cannot be serialized into a proposal or event,
        and is revalidated against the persisted creation run on every Stage 2
        compilation.  Only the finalization service can later issue evidence.
        """
        if _server_authority is not _TRUSTED_CHARACTER_CREATION_EXECUTION:
            raise FoundryError(
                "STAGE2_INITIAL_CREATION_SCOPE_FORBIDDEN",
                "Initial creation evaluation requires the private server execution boundary.",
                status_code=403,
            )
        if phase not in {"scratch_compile", "finalization"}:
            raise FoundryError("STAGE2_INITIAL_CREATION_SCOPE_INVALID", "The server creation phase is invalid.", status_code=409)
        context = _InitialCreationExecutionContext(
            run_id=run_id,
            project_id=project_id,
            starting_revision=int(starting_revision),
            content_lock_hash=content_lock_hash,
            typed_choice_snapshot_sha256=typed_choice_snapshot_sha256,
            phase=phase,
            candidate_identity=candidate_identity,
        )
        reset = _INITIAL_CREATION_EXECUTION.set(context)
        try:
            yield
        finally:
            _INITIAL_CREATION_EXECUTION.reset(reset)

    def _trusted_initial_talent_selection(
        self,
        conn,
        row,
        project: dict[str, Any],
        record: dict[str, Any],
        predicate_ids: list[str],
    ) -> bool:
        context = _INITIAL_CREATION_EXECUTION.get()
        if context is None or context.project_id != row["project_id"]:
            return False
        run_row = conn.execute(
            "SELECT * FROM character_creation_runs WHERE run_id=? AND project_id=?",
            (context.run_id, context.project_id),
        ).fetchone()
        if run_row is None or int(run_row["starting_revision"]) != context.starting_revision:
            return False
        request = json.loads(run_row["request_json"] or "{}")
        snapshot = request.get("typed_choice_snapshot") or {}
        if (
            request.get("project_revision") != context.starting_revision
            or request.get("content_lock_hash") != context.content_lock_hash
            or snapshot.get("canonical_project_id") != context.project_id
            or snapshot.get("project_revision") != context.starting_revision
            or snapshot.get("content_lock_hash") != context.content_lock_hash
            or snapshot.get("snapshot_sha256") != context.typed_choice_snapshot_sha256
            or project.get("content_lock", {}).get("lock_hash") != context.content_lock_hash
        ):
            return False
        if context.phase == "scratch_compile":
            if run_row["status"] not in {"WAITING_FOR_RESPONSE", "PREPARING_REQUEST"} or context.candidate_identity is not None:
                return False
        else:
            quality = json.loads(run_row["quality_json"] or "{}")
            candidate = json.loads(run_row["dry_run_json"] or "{}")
            if (
                run_row["status"] not in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
                or quality.get("status") != "CLEAN"
                or not context.candidate_identity
                or candidate.get("candidate_identity") != context.candidate_identity
            ):
                return False
        grant_plan = committed_catalog_grant_plan(project)
        if not isinstance(grant_plan, dict) or grant_plan.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1":
            return False
        disposition = next((
            item for item in grant_plan.get("selected_talent_dispositions", [])
            if isinstance(item, dict) and item.get("canonical_talent_id") == record["record_id"]
        ), None)
        provenance = (disposition or {}).get("acquisition_provenance") or {}
        return bool(
            disposition
            and disposition.get("acquisition_provenance_required") is True
            and provenance.get("source") == "pending-trusted-initial-finalization"
            and provenance.get("recorded") is False
            and sorted(provenance.get("predicate_ids") or []) == sorted(predicate_ids)
        )

    @staticmethod
    def _project_uses_ai_bootstrap(project: dict[str, Any]) -> bool:
        for lock in project.get("user_locks", []):
            if lock.get("field") == "character_sheet.generation_route":
                return lock.get("value") == "ai_bootstrap"
        return False

    # ---------- common persistence ----------
    def _project_row(self, conn, project_id: str):
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
        project = json.loads(row["project_json"])
        self.registry.validate(project)
        return row, project

    def _proposal_row(self, conn, proposal_id: str):
        row = conn.execute("SELECT * FROM stage2_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if not row:
            raise FoundryError("STAGE2_PROPOSAL_NOT_FOUND", "No Stage 2 proposal has that ID.", status_code=404)
        return row

    def _record(
        self,
        conn,
        project_id: str,
        record_id: str | None,
        pointer: str,
        *,
        require_complete: bool = True,
        record_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if not record_id:
            return None, [_block("CATALOG_RECORD_ID_REQUIRED", pointer, "A published project-locked catalog record ID is required.")]
        if record_cache is not None and record_id in record_cache:
            record = record_cache[record_id]
        else:
            record = self.projects._resolve_locked_record_after_proof(conn, project_id, record_id)
            if record_cache is not None:
                record_cache[record_id] = record
        if not record:
            return None, [_block("MISSING_OR_UNLOCKED_CATALOG_AUTHORITY", pointer, "The requested record is not present in the immutable project lock.", record_id=record_id)]
        if record.get("publication", {}).get("status") != "published":
            return None, [_block("CATALOG_RECORD_NOT_PUBLISHED", pointer, "The record is not published and cannot authorize a mechanical choice.", record_id=record_id)]
        if canonical_record_hash(record) != record.get("record_hash"):
            return None, [_block("LOCKED_RECORD_HASH_MISMATCH", pointer, "The locked catalog record bytes do not match their canonical record hash.", record_id=record_id, expected=canonical_record_hash(record), actual=record.get("record_hash"))]
        stage2 = _authority(record)
        if require_complete and not stage2.get("authority_complete"):
            return None, [_block("MISSING_STAGE2_RULE_AUTHORITY", pointer, "The catalog record is published but lacks complete typed Stage 2 authority.", record_id=record_id)]
        return record, []

    def create_proposal(self, body: dict[str, Any]) -> dict[str, Any]:
        self.registry.validate(body, PROPOSAL_V2)
        now = utcnow()
        proposal_hash = sha256_json(body)
        proposal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2-hf1:{body['project_id']}:{body['idempotency_key']}:{proposal_hash}"))
        with self.db.transaction() as conn:
            project_row, project = self._project_row(conn, body["project_id"])
            if int(project_row["revision"]) != int(body["expected_project_revision"]):
                raise FoundryError("STALE_PROJECT_REVISION", "The proposal was created for a different project revision.", details={"expected": body["expected_project_revision"], "actual": project_row["revision"]})
            if project["content_lock"]["lock_hash"] != body["expected_content_lock_hash"]:
                raise FoundryError("STALE_CONTENT_LOCK", "The proposal content-lock hash does not match the project.")
            prior = conn.execute("SELECT * FROM stage2_proposals WHERE project_id=? AND idempotency_key=?", (body["project_id"], body["idempotency_key"])).fetchone()
            if prior:
                if prior["proposal_hash"] != proposal_hash:
                    raise FoundryError("STAGE2_IDEMPOTENCY_CONFLICT", "The idempotency key is already bound to different proposal bytes.")
                return self._proposal_result(conn, prior["proposal_id"])
            conn.execute(
                "INSERT INTO stage2_proposals(proposal_id,project_id,idempotency_key,expected_project_revision,expected_content_lock_hash,target_cl,status,proposal_json,proposal_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, body["project_id"], body["idempotency_key"], body["expected_project_revision"], body["expected_content_lock_hash"], body["target_cl"], "draft", canonical_json(body), proposal_hash, now, now),
            )
            for index, choice in enumerate(body["choices"]):
                conn.execute("INSERT INTO stage2_proposal_events(proposal_id,ordinal,event_request_json,event_request_hash) VALUES(?,?,?,?)", (proposal_id, index, canonical_json(choice), sha256_json(choice)))
            return self._proposal_result(conn, proposal_id)

    def _proposal_result(self, conn, proposal_id: str) -> dict[str, Any]:
        row = self._proposal_row(conn, proposal_id)
        result = dict(row)
        for key in ("proposal_json", "validation_json"):
            if result.get(key):
                result[key] = json.loads(result[key])
        result["choices"] = [json.loads(r[0]) for r in conn.execute("SELECT event_request_json FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal", (proposal_id,))]
        return result

    # ---------- event/reducer helpers ----------
    def _v3_events(self, conn, project_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in conn.execute("SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,)):
            event = json.loads(row[0])
            if event.get("schema_version") == EVENT_V3:
                self.registry.validate(event)
                out.append(event)
        return out

    def _all_events(self, conn, project_id: str) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in conn.execute("SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,))]

    def _remember_authority(self, state: dict[str, Any], record: dict[str, Any], event_id: str) -> None:
        state["authority_snapshots"][record["record_id"]] = {
            "record": deepcopy(record),
            "event_id": event_id,
        }
        state["record_event_ids"][record["record_id"]] = event_id

    def _apply_event(self, prior: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        state = _deepcopy(prior)
        adv = event["advancement"]
        kind = adv["kind"]
        details = adv["details"]
        outputs = adv["calculation"]["outputs"]
        rid = event["subject"]["record_id"]
        eid = event["event_id"]
        state["event_ids"].append(eid)
        state["record_event_ids"][rid] = eid
        occurrence = {"event_id": eid, "record_id": rid, "cl": adv["target_cl"]}
        state["event_occurrences"].setdefault(kind, []).append(occurrence)
        if kind == "starting_state":
            state["ability_scores"] = deepcopy(outputs["ability_scores"])
            state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
            state["ability_authority_event_id"] = eid
            state["ability_authority_record_id"] = rid
        elif kind == "ability_score_change":
            state["ability_scores"] = deepcopy(outputs["ability_scores"])
            state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
            state["ability_authority_event_id"] = eid
            state["ability_authority_record_id"] = rid
            state["hp"] = deepcopy(outputs["hp_after"])
            state["resources"] = deepcopy(outputs["resources_after"])
        elif kind == "cultivation_insight_acquisition":
            state["cultivation_insights"].append(rid)
            occurrence = deepcopy(outputs.get("insight_occurrence") or {
                "record_id": rid,
                "event_id": eid,
                "acquisition_cl": adv["target_cl"],
                "repeat_index": details.get("repeat_index", 1),
                "ability": details.get("ability"),
                "amount": details.get("amount"),
                "content_binding": deepcopy(event.get("content_binding") or {}),
                "source_evidence": deepcopy(event.get("source_evidence") or []),
                "execution_authority": deepcopy(outputs.get("execution_authority") or {}),
            })
            state["cultivation_insight_occurrences"].append(occurrence)
            if outputs.get("ability_scores"):
                state["ability_scores"] = deepcopy(outputs["ability_scores"])
                state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
                state["ability_authority_event_id"] = eid
                state["ability_authority_record_id"] = rid
                state["hp"] = deepcopy(outputs.get("hp_after", state["hp"]))
                state["resources"] = deepcopy(outputs.get("resources_after", state["resources"]))
        elif kind == "path_acquisition":
            state["paths"].append(rid)
            for milestone in outputs.get("required_milestones", []):
                if milestone not in state["required_milestones"]:
                    state["required_milestones"].append(deepcopy(milestone))
        elif kind == "level_advance":
            cl = adv["target_cl"]
            state["current_cl"] = cl
            state["completed_levels"].append(cl)
            state["pb"] = outputs["pb"]
            state["hp"] = deepcopy(outputs["hp_after"])
            state["resources"] = deepcopy(outputs["resources_after"])
        elif kind == "background_acquisition":
            state["background"] = rid
            if outputs.get("ability_scores"):
                state["ability_scores"] = deepcopy(outputs["ability_scores"])
                state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
                state["ability_authority_event_id"] = eid
                state["ability_authority_record_id"] = rid
        elif kind == "background_sphere_acquisition":
            state["background_sphere"] = rid
            state["known_spheres"].append(rid)
            _attach_sphere_components_from_event(state, event)
        elif kind == "background_talent_acquisition":
            state["background_talent"] = rid
            state["known_talents"].append(rid)
        elif kind == "origin_insight_acquisition":
            state["origin_insight"] = rid
        elif kind == "sect_trial_sphere_acquisition":
            state["sect_trial_sphere"] = rid
            state["known_spheres"].append(rid)
            _attach_sphere_components_from_event(state, event)
        elif kind == "sect_trial_talent_acquisition":
            state["sect_trial_talent"] = rid
            state["known_talents"].append(rid)
            state["level_talents"].setdefault(str(adv["target_cl"]), []).append({"record_id": rid, "event_id": eid, "channel": event["legal_channel"]})
        elif kind == "ai_bootstrap_sphere_acquisition":
            state["ai_bootstrap_sphere"] = rid
            state["known_spheres"].append(rid)
            _attach_sphere_components_from_event(state, event)
        elif kind == "ai_bootstrap_talent_acquisition":
            state["ai_bootstrap_talent"] = rid
            state["known_talents"].append(rid)
        elif kind == "level_talent_acquisition":
            state["known_talents"].append(rid)
            state["level_talents"].setdefault(str(adv["target_cl"]), []).append({"record_id": rid, "event_id": eid, "channel": event["legal_channel"]})
        elif kind == "subpath_acquisition":
            state["subpaths"].append(rid)
            state["subpath_features"].extend(outputs.get("granted_feature_record_ids", []))
            state["typed_none_states"].pop("subpaths", None)
        elif kind == "training_source_access":
            state["training_sources"].append(rid)
        elif kind == "method_acquisition":
            state["method"] = {"state": "acquired", "record_id": rid, "event_id": eid}
            state["typed_none_states"].pop("method", None)
        elif kind == "method_activation":
            state["method"] = {"state": "active", "record_id": rid, "event_id": eid}
            state["resources"] = deepcopy(outputs.get("resources_after", state["resources"]))
        elif kind == "foundation_acquisition":
            state["foundation"] = {"state": "acquired", "record_id": rid, "event_id": eid, "expression_record_id": None, "path_id": None, "stage": None}
            state["typed_none_states"].pop("foundation", None)
        elif kind == "foundation_expression":
            base = state["foundation"] if isinstance(state["foundation"], dict) else {}
            state["foundation"] = {**base, "state": "expressed", "expression_record_id": rid, "path_id": details["path_id"], "event_id": eid}
        elif kind == "foundation_stage":
            base = state["foundation"] if isinstance(state["foundation"], dict) else {}
            state["foundation"] = {**base, "state": "active", "stage": details["stage"], "stage_event_id": eid}
            state["resources"] = deepcopy(outputs.get("resources_after", state["resources"]))
        elif kind in {"sphere_training_attempt", "talent_training_attempt", "manual_training_attempt"}:
            txn = deepcopy(adv["training_transaction"])
            state["training_transactions"][txn["attempt_id"]] = txn
            clkey = str(adv["target_cl"])
            if txn["result"] == "success":
                if kind != "manual_training_attempt":
                    state["trained_success_cost"][clkey] = int(state["trained_success_cost"].get(clkey, 0)) + int(txn["slot_cost"])
                if kind == "sphere_training_attempt":
                    state["known_spheres"].append(rid)
                    _attach_sphere_components_from_event(state, event)
                    state["new_sphere_entitlements"].append({"entitlement_id": eid, "sphere_record_id": rid, "sphere_event_id": eid, "character_cl": adv["target_cl"], "attempt_id": txn["attempt_id"], "consumed": False, "talent_record_id": None, "talent_event_id": None})
                elif kind == "talent_training_attempt":
                    state["known_talents"].append(rid)
                elif kind == "manual_training_attempt":
                    state["recorded_arts"].append(deepcopy(outputs["recorded_art"]))
                    state["typed_none_states"].pop("manuals", None)
        elif kind == "new_sphere_bonus_talent_acquisition":
            state["known_talents"].append(rid)
            entitlement_id = details["entitlement_event_id"]
            for entitlement in state["new_sphere_entitlements"]:
                if entitlement["entitlement_id"] == entitlement_id:
                    entitlement["consumed"] = True
                    entitlement["talent_record_id"] = rid
                    entitlement["talent_event_id"] = eid
                    break
        elif kind == "equipment_acquisition":
            state["equipment"].append(rid)
            state["resources"] = deepcopy(outputs.get("resources_after", state["resources"]))
            state["typed_none_states"].pop("equipment", None)
        elif kind == "typed_none":
            state["typed_none_states"][details["target"]] = deepcopy(adv["none_state"])
            if details["target"] == "method":
                state["method"] = deepcopy(adv["none_state"])
            elif details["target"] == "foundation":
                state["foundation"] = deepcopy(adv["none_state"])
            elif details["target"] == "forged_techniques":
                state["forged_techniques"] = deepcopy(adv["none_state"])
        state["known_spheres"] = _sort_unique(state["known_spheres"])
        state["known_talents"] = _sort_unique(state["known_talents"])
        state["paths"] = _sort_unique(state["paths"])
        state["subpaths"] = _sort_unique(state["subpaths"])
        state["cultivation_insights"] = _sort_unique(state["cultivation_insights"])
        state["equipment"] = _sort_unique(state["equipment"])
        state["training_sources"] = _sort_unique(state["training_sources"])
        return state

    def _mechanical_state(self, events: list[dict[str, Any]], project_id: str) -> dict[str, Any]:
        state = _state(project_id)
        for event in events:
            state = self._apply_event(state, event)
        return state

    def _record_in_final_state(self, state: dict[str, Any], record_id: str) -> bool:
        if record_id in state["known_spheres"] or record_id in state["known_talents"] or record_id in state["paths"] or record_id in state["subpaths"] or record_id in state["cultivation_insights"] or record_id in state["equipment"] or record_id in state["training_sources"]:
            return True
        if state.get("background") == record_id or state.get("background_sphere") == record_id or state.get("background_talent") == record_id or state.get("origin_insight") == record_id or state.get("sect_trial_sphere") == record_id or state.get("sect_trial_talent") == record_id or state.get("ai_bootstrap_sphere") == record_id or state.get("ai_bootstrap_talent") == record_id:
            return True
        if isinstance(state.get("method"), dict) and state["method"].get("record_id") == record_id:
            return True
        if isinstance(state.get("foundation"), dict) and record_id in {state["foundation"].get("record_id"), state["foundation"].get("expression_record_id")}:
            return True
        if any(x.get("record_id") == record_id for x in state["recorded_arts"]):
            return True
        return False

    def _stage2_authority(self, record: dict[str, Any], kind: str, channel: str, pointer: str) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        auth = _authority(record)
        if kind not in auth.get("allowed_kinds", []):
            blockers.append(_block("EVENT_KIND_NOT_AUTHORIZED", pointer + "/kind", "The record does not authorize this event kind.", record_id=record["record_id"], kind=kind))
        channels = auth.get("allowed_channels") or record.get("legality", {}).get("acquisition_channels", [])
        if channel not in channels:
            blockers.append(_block("INVALID_ACQUISITION_CHANNEL", pointer + "/acquisition_channel", "The acquisition channel is not published for this record.", record_id=record["record_id"], channel=channel, allowed=channels))
        return blockers

    def _legality_relation_blockers(
        self,
        conn,
        project_id: str,
        state: dict[str, Any],
        record: dict[str, Any],
        pointer: str,
        *,
        record_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Evaluate only typed prerequisite shapes; unknown shapes fail closed."""
        blockers: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        legality = record.get("legality", {})
        for index, relation in enumerate(legality.get("prerequisites", [])):
            rel_pointer = f"{pointer}/record/legality/prerequisites/{index}"
            operator = relation.get("operator")
            target_id = relation.get("target_id")
            present = isinstance(target_id, str) and self._record_in_final_state(state, target_id)
            if operator == "requires":
                if not present:
                    blockers.append(_block("PUBLISHED_PREREQUISITE_UNMET", rel_pointer, "A published prerequisite is not present in the prior causal state.", record_id=record["record_id"], prerequisite=relation))
                    continue
                prerequisite, issues = self._record(
                    conn,
                    project_id,
                    target_id,
                    rel_pointer + "/target_id",
                    record_cache=record_cache,
                )
                blockers.extend(issues)
                causal_event_id = state["record_event_ids"].get(target_id)
                if prerequisite and not causal_event_id:
                    blockers.append(_block("PREREQUISITE_CAUSAL_EVENT_MISSING", rel_pointer, "The prerequisite appears in state without its acquisition event.", target_id=target_id))
                elif prerequisite:
                    bindings.append(_binding(prerequisite, "published_prerequisite", causal_event_id))
            elif operator == "not":
                if present:
                    blockers.append(_block("PUBLISHED_NEGATIVE_PREREQUISITE_VIOLATED", rel_pointer, "A published exclusion prerequisite is present.", record_id=record["record_id"], prerequisite=relation))
            else:
                blockers.append(_block("PREREQUISITE_OPERATOR_UNSUPPORTED", rel_pointer + "/operator", "This prerequisite operator lacks a typed deterministic evaluator and therefore fails closed.", operator=operator, relation=relation))
        for index, incompatible_id in enumerate(legality.get("incompatibilities", [])):
            if self._record_in_final_state(state, incompatible_id):
                blockers.append(_block("PUBLISHED_INCOMPATIBILITY_PRESENT", f"{pointer}/record/legality/incompatibilities/{index}", "The selected record is incompatible with an element already present in the causal state.", record_id=record["record_id"], incompatible_record_id=incompatible_id, causal_event_id=state["record_event_ids"].get(incompatible_id)))
        return blockers, bindings

    def _cardinality_blockers(self, state: dict[str, Any], kind: str, record: dict[str, Any], choice: dict[str, Any], pointer: str) -> list[dict[str, Any]]:
        """Block event shapes the current reducer cannot represent without loss."""
        blockers: list[dict[str, Any]] = []
        occurrences = state.get("event_occurrences", {})
        singleton_character = {
            "starting_state",
            "background_acquisition",
            "background_sphere_acquisition",
            "background_talent_acquisition",
            "origin_insight_acquisition",
            "method_acquisition",
            "method_activation",
            "foundation_acquisition",
            "foundation_expression",
        }
        if kind == "subpath_acquisition":
            current_authority = _authority(record)
            current_parent = record.get("owning_path_id")
            prior_same_parent: list[dict[str, Any]] = []
            for prior in occurrences.get(kind, []):
                prior_record = (state.get("authority_snapshots") or {}).get(prior.get("record_id"), {}).get("record") or {}
                prior_authority = _authority(prior_record)
                prior_parent = prior_record.get("owning_path_id")
                if current_parent is None or prior_parent == current_parent:
                    prior_same_parent.append(prior)
            if prior_same_parent:
                blockers.append(_block("SINGLETON_ADVANCEMENT_EVENT_REPEATED", pointer, "Each selected Path may receive only one Subpath or Tradition acquisition.", kind=kind, parent_path_id=current_parent, prior=prior_same_parent))
        elif kind in singleton_character and occurrences.get(kind):
            blockers.append(_block("SINGLETON_ADVANCEMENT_EVENT_REPEATED", pointer, "This advancement channel is singleton in the current published character model.", kind=kind, prior=occurrences[kind]))
        cl = int(choice["effective_cl"])
        if kind in {"level_advance", "level_talent_acquisition", "ability_score_change"}:
            same_cl = [x for x in occurrences.get(kind, []) if int(x["cl"]) == cl]
            if same_cl:
                blockers.append(_block("ADVANCEMENT_SLOT_ALREADY_FILLED", pointer, "This CL-specific advancement slot already has a causal event.", kind=kind, cl=cl, prior=same_cl))
        if kind == "training_source_access":
            if any(x["record_id"] == choice.get("record_id") for x in occurrences.get(kind, [])):
                blockers.append(_block("TRAINING_SOURCE_ACCESS_ALREADY_RECORDED", pointer, "Access to this exact training source is already causal.", record_id=choice.get("record_id")))
        if kind == "typed_none":
            target = (choice.get("parameters") or {}).get("target")
            if target in state.get("typed_none_states", {}):
                blockers.append(_block("TYPED_NONE_TARGET_ALREADY_RESOLVED", pointer, "This absence target already has a causal resolution.", target=target))
        return blockers

    def _insight_occurrence_blockers(
        self,
        state: dict[str, Any],
        record: dict[str, Any],
        choice: dict[str, Any],
        pointer: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate typed Insight occurrence identity without prose parsing."""
        blockers: list[dict[str, Any]] = []
        auth = _authority(record)
        repeatability = auth.get("repeatability") or {"mode": "nonrepeatable", "maximum": 1}
        mode = repeatability.get("mode", "nonrepeatable")
        prior = [
            row for row in state.get("cultivation_insight_occurrences", [])
            if row.get("record_id") == record["record_id"]
        ]
        details = choice.get("parameters") or {}
        supplied = details.get("repeat_index")
        if isinstance(supplied, bool) or (supplied is not None and not isinstance(supplied, int)):
            blockers.append(_block("CULTIVATION_INSIGHT_REPEAT_INDEX_INVALID", pointer + "/parameters/repeat_index", "The Insight occurrence index must be a positive integer."))
        repeat_index = insight_occurrence_index(details, prior)
        if repeat_index < 1:
            blockers.append(_block("CULTIVATION_INSIGHT_REPEAT_INDEX_INVALID", pointer + "/parameters/repeat_index", "Insight occurrence indices are one-based."))
        if mode == "nonrepeatable":
            if prior:
                blockers.append(_block("CULTIVATION_INSIGHT_NOT_REPEATABLE", pointer, "The selected Insight is not repeatable and already has a causal occurrence.", record_id=record["record_id"], prior_occurrences=prior))
            if repeat_index != 1:
                blockers.append(_block("CULTIVATION_INSIGHT_REPEAT_INDEX_INVALID", pointer + "/parameters/repeat_index", "A nonrepeatable Insight can only have occurrence index 1.", repeat_index=repeat_index))
        else:
            maximum = repeatability.get("maximum")
            if isinstance(maximum, int) and repeat_index > maximum:
                blockers.append(_block("CULTIVATION_INSIGHT_REPEAT_MAXIMUM_EXCEEDED", pointer + "/parameters/repeat_index", "The Insight occurrence exceeds its exact published repeat maximum.", record_id=record["record_id"], repeat_index=repeat_index, maximum=maximum))
            expected = len(prior) + 1
            if repeat_index != expected:
                blockers.append(_block("CULTIVATION_INSIGHT_REPEAT_INDEX_NOT_CONTIGUOUS", pointer + "/parameters/repeat_index", "Repeatable Insight occurrences must use contiguous one-based indices.", expected=expected, supplied=repeat_index, prior_occurrences=prior))
        return blockers, repeat_index

    def _duplicate_blockers(self, state: dict[str, Any], record: dict[str, Any], kind: str, pointer: str) -> list[dict[str, Any]]:
        rid = record["record_id"]
        auth = _authority(record)
        if auth.get("reacquisition_rule") in {"stack", "replace", "evolve"}:
            if self._record_in_final_state(state, rid):
                return [_block("REPEATABLE_ACQUISITION_NOT_REPRESENTABLE", pointer + "/record_id", "The published record is repeatable, but this reducer does not yet model acquisition instances or ranks and must not silently deduplicate it.", record_id=rid, reacquisition_rule=auth.get("reacquisition_rule"))]
            return []
        duplicate = False
        if record["content_type"] == "sphere":
            duplicate = rid in state["known_spheres"]
        elif record["content_type"] == "talent":
            duplicate = rid in state["known_talents"]
        elif record["content_type"] == "recorded_art":
            duplicate = any(x.get("record_id") == rid for x in state["recorded_arts"])
        elif record["content_type"] == "item" and auth.get("unique", True):
            duplicate = rid in state["equipment"]
        if duplicate:
            return [_block("DUPLICATE_UNIQUE_ACQUISITION", pointer + "/record_id", "The unique record is already known or owned; silent deduplication is forbidden.", record_id=rid, kind=kind)]
        return []

    def _formula_context(self, state: dict[str, Any], cl: int, pb: int) -> dict[str, Any]:
        return {
            "cl": cl,
            "pb": pb,
            "ability_scores": state["ability_scores"],
            "ability_modifiers": state["ability_modifiers"],
            "selected_path_base": {},
        }

    def _active_record(self, conn, project_id: str, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict) or value.get("state") != "active":
            return None
        rid = value.get("record_id")
        return self.projects._resolve_locked_record_after_proof(conn, project_id, rid) if rid else None

    def _foundation_modifier_record(self, conn, project_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        f = state.get("foundation")
        if not isinstance(f, dict) or f.get("state") != "active":
            return None
        rid = f.get("expression_record_id") or f.get("record_id")
        return self.projects._resolve_locked_record_after_proof(conn, project_id, rid) if rid else None

    def _resource_recalculation(self, conn, project_id: str, state: dict[str, Any], *, cl: int, pb: int, path: dict[str, Any], current_resources: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        auth = _authority(path)
        resources_after: dict[str, Any] = {}
        bindings: list[dict[str, Any]] = [_binding(path, "path_resource_authority", state["record_event_ids"].get(path["record_id"]))]
        trace: dict[str, Any] = {}
        context = self._formula_context(state, cl, pb)
        method = self._active_record(conn, project_id, state.get("method"))
        foundation = self._foundation_modifier_record(conn, project_id, state)
        equipment_records = [self.projects._resolve_locked_record_after_proof(conn, project_id, rid) for rid in state.get("equipment", [])]
        for spec in auth.get("resources", []):
            resource_id = spec["resource_id"]
            base_value, base_trace = _formula_value(spec["base_formula"], context)
            components = [{"role": "path_base", "record_id": path["record_id"], "record_hash": path["record_hash"], "source_anchor": path["source"]["anchor"], "formula_id": spec["base_formula"]["formula_id"], "value": base_value}]
            method_delta = foundation_delta = equipment_delta = 0
            role_traces: dict[str, Any] = {"path_base": base_trace}
            for role, rec in (("method_delta", method), ("foundation_delta", foundation)):
                if not rec:
                    continue
                for modifier in _authority(rec).get("resource_modifiers", []):
                    if modifier.get("resource_id") not in {resource_id, "*"}:
                        continue
                    value, t = _formula_value(modifier["formula"], context)
                    if role == "method_delta":
                        method_delta += value
                    else:
                        foundation_delta += value
                    components.append({"role": role, "record_id": rec["record_id"], "record_hash": rec["record_hash"], "source_anchor": rec["source"]["anchor"], "formula_id": modifier["formula"]["formula_id"], "value": value})
                    bindings.append(_binding(rec, role, state["record_event_ids"].get(rec["record_id"])))
                    role_traces[f"{role}:{rec['record_id']}"] = t
            for rec in [x for x in equipment_records if x]:
                for modifier in _authority(rec).get("resource_modifiers", []):
                    if modifier.get("resource_id") not in {resource_id, "*"}:
                        continue
                    value, t = _formula_value(modifier["formula"], context)
                    equipment_delta += value
                    components.append({"role": "equipment_delta", "record_id": rec["record_id"], "record_hash": rec["record_hash"], "source_anchor": rec["source"]["anchor"], "formula_id": modifier["formula"]["formula_id"], "value": value})
                    bindings.append(_binding(rec, "equipment_resource_delta", state["record_event_ids"].get(rec["record_id"])))
                    role_traces[f"equipment:{rec['record_id']}"] = t
            maximum = max(0, base_value + method_delta + foundation_delta + equipment_delta)
            prior = (current_resources or {}).get(resource_id)
            current_before = int(prior.get("current", maximum)) if isinstance(prior, dict) else maximum
            current_after = min(current_before, maximum)
            resources_after[resource_id] = {
                "resource_id": resource_id,
                "base_value": base_value,
                "method_delta": method_delta,
                "foundation_delta": foundation_delta,
                "equipment_delta": equipment_delta,
                "maximum": maximum,
                "current": current_after,
                "current_before": current_before,
                "formula_id": spec["base_formula"]["formula_id"],
                "authority_components": components,
            }
            trace[resource_id] = role_traces
        # Deterministic de-duplication by role+record; duplicate bindings do not change evidence.
        unique: dict[tuple[str, str], dict[str, Any]] = {(b["role"], b["record_id"]): b for b in bindings}
        return resources_after, list(unique.values()), trace

    def _hp_calculation(self, state: dict[str, Any], path: dict[str, Any], cl: int, *, previous_total: int, pb: int) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        auth = _authority(path)
        formula = auth["hp_level1_formula"] if cl == 1 else auth["hp_later_formula"]
        value, trace = _formula_value(formula, self._formula_context(state, cl, pb))
        gain = max(1, value)
        result = {
            "total": previous_total + gain,
            "last_gain": gain,
            "last_formula_id": formula["formula_id"],
            "components": [{"role": "path_hp", "record_id": path["record_id"], "record_hash": path["record_hash"], "source_anchor": path["source"]["anchor"], "formula_id": formula["formula_id"], "value": gain}],
        }
        return result, [_binding(path, "path_hp_authority", state["record_event_ids"].get(path["record_id"]))], trace

    def _recalculate_after_ability(
        self,
        conn,
        project_id: str,
        state: dict[str, Any],
        old_scores: dict[str, int],
        *,
        path_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        if not state["paths"] or state["current_cl"] < 1:
            return state["hp"], state["resources"], [], {}
        selected_path_id = path_id if path_id in state["paths"] else state["paths"][0]
        path = self.projects._resolve_locked_record_after_proof(conn, project_id, selected_path_id)
        cl = state["current_cl"]
        pb = _pb(cl)
        old_con = _ability_modifier(old_scores["CON"])
        new_con = state["ability_modifiers"]["CON"]
        hp_after = deepcopy(state["hp"])
        hp_after["total"] = int(state["hp"]["total"]) + (new_con - old_con) * cl
        hp_after["last_gain"] = int(state["hp"].get("last_gain", 0)) + (new_con - old_con) * cl
        resources_after, bindings, traces = self._resource_recalculation(conn, project_id, state, cl=cl, pb=pb, path=path, current_resources=state["resources"])
        bindings.append(_binding(path, "path_hp_authority", state["record_event_ids"].get(path["record_id"])))
        return hp_after, resources_after, bindings, {"resources": traces, "hp_retroactive_con_delta": (new_con - old_con) * cl}

    def _legacy_manual_entry_unreachable(self, conn, project_id: str, manual: dict[str, Any], state: dict[str, Any], pointer: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
        auth = _authority(manual)
        fixed = auth.get("fixed_expression")
        if not isinstance(fixed, dict):
            return None, [_block("MANUAL_FIXED_EXPRESSION_AUTHORITY_MISSING", pointer, "The Recorded Art lacks a published fixed-expression authority object.")], []
        required = {"sphere_id", "technique_name", "reproduced_record_id", "dc", "timing", "cost", "range", "target", "resolution", "effect", "failure", "duration", "limits", "counterplay", "linked_action_derivation"}
        missing = sorted(required - set(fixed))
        if missing:
            return None, [_block("MANUAL_FIXED_EXPRESSION_INCOMPLETE", pointer, "The Recorded Art fixed expression is incomplete.", missing=missing)], []
        if str(fixed.get("reproduced_package_label", "")).strip().lower() in {"technique", "ability", "package", "generic"}:
            return None, [_block("MANUAL_GENERIC_REPRODUCED_PACKAGE", pointer, "A generic package label cannot authorize a Recorded Art.")], []
        sphere, issues = self._record(conn, project_id, fixed["sphere_id"], pointer + "/sphere")
        reproduced, issues2 = self._record(conn, project_id, fixed["reproduced_record_id"], pointer + "/reproduced")
        blockers = issues + issues2
        if blockers or not sphere or not reproduced:
            return None, blockers, []
        reproduced_sphere = _authority(reproduced).get("sphere_id")
        compatible = fixed["sphere_id"] == reproduced_sphere or fixed["sphere_id"] in _authority(reproduced).get("compatible_sphere_ids", [])
        if not compatible:
            blockers.append(_block("MANUAL_REPRODUCED_RECORD_WRONG_SPHERE", pointer, "The reproduced record does not belong to or declare compatibility with the named Sphere.", sphere_id=fixed["sphere_id"], reproduced_record_id=reproduced["record_id"], reproduced_sphere_id=reproduced_sphere))
            return None, blockers, []
        if fixed["sphere_id"] not in state["known_spheres"]:
            blockers.append(_block("MANUAL_SPHERE_NOT_KNOWN", pointer, "The character does not know the Recorded Art's named Sphere.", sphere_id=fixed["sphere_id"]))
            return None, blockers, []
        entry = {
            "record_id": manual["record_id"],
            "display_name": manual["display_name"],
            "dm_facing_line": f"Sphere of {sphere['display_name']} — {fixed['technique_name']} — {reproduced['display_name']} — DC {fixed['dc']}",
            "sphere_record_id": sphere["record_id"],
            "reproduced_record_id": reproduced["record_id"],
            "dc": int(fixed["dc"]),
            "execution": {key: deepcopy(fixed[key]) for key in ["timing", "cost", "range", "target", "resolution", "effect", "failure", "duration", "limits", "counterplay", "linked_action_derivation"]},
            "record_hash": manual["record_hash"],
        }
        return entry, [], [_binding(sphere, "manual_sphere_authority", state["record_event_ids"].get(sphere["record_id"])), _binding(reproduced, "manual_reproduced_package_authority", state["record_event_ids"].get(reproduced["record_id"]))]

    def _legacy_training_unreachable(self, conn, project_id: str, state: dict[str, Any], record: dict[str, Any], choice: dict[str, Any], event_id: str, pointer: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        params = choice["parameters"]
        blockers: list[dict[str, Any]] = []
        source, issues = self._record(conn, project_id, params.get("training_source_record_id"), pointer + "/parameters/training_source_record_id")
        blockers.extend(issues)
        if not source:
            return None, blockers, [], {}
        source_auth = _authority(source)
        kind_map = {"sphere_training_attempt": "new_sphere", "talent_training_attempt": "known_sphere_talent", "manual_training_attempt": "recorded_art"}
        training_type = kind_map[choice["kind"]]
        if training_type not in source_auth.get("training_types", []):
            blockers.append(_block("TRAINING_SOURCE_TYPE_NOT_AUTHORIZED", pointer, "The selected training source does not authorize this training type.", training_type=training_type, source_record_id=source["record_id"]))
        selected = params.get("selected_ability")
        if selected not in {"INT", "WIS"}:
            blockers.append(_block("TRAINING_ABILITY_INVALID", pointer + "/parameters/selected_ability", "Training must use a bounded INT or WIS choice."))
            return None, blockers, [_binding(source, "training_source", state["record_event_ids"].get(source["record_id"]))], {}
        d6 = params.get("time_die_result")
        if not isinstance(d6, int) or not 1 <= d6 <= 6:
            blockers.append(_block("TRAINING_TIME_DIE_INVALID", pointer + "/parameters/time_die_result", "Training time requires an integer d6 result from 1 through 6."))
        check_total = params.get("check_total")
        if not isinstance(check_total, int):
            blockers.append(_block("TRAINING_CHECK_TOTAL_INVALID", pointer + "/parameters/check_total", "The recorded training check total must be an integer input."))
        attempt_id = params.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            blockers.append(_block("TRAINING_ATTEMPT_ID_REQUIRED", pointer + "/parameters/attempt_id", "Every training attempt requires a stable attempt identity."))
        if attempt_id in state["training_transactions"]:
            blockers.append(_block("TRAINING_ATTEMPT_ID_DUPLICATE", pointer + "/parameters/attempt_id", "A training attempt identity cannot be reused.", attempt_id=attempt_id))
        retry_of = params.get("retry_of_attempt_id")
        if retry_of is not None:
            prior_attempt = state["training_transactions"].get(retry_of)
            if not prior_attempt or prior_attempt.get("result") != "failure" or prior_attempt.get("target_record_id") != record["record_id"]:
                blockers.append(_block("TRAINING_RETRY_IDENTITY_INVALID", pointer + "/parameters/retry_of_attempt_id", "A retry must identify a prior failed attempt for the same target.", retry_of_attempt_id=retry_of))
        if blockers:
            return None, blockers, [_binding(source, "training_source", state["record_event_ids"].get(source["record_id"]))], {}
        pb = _pb(choice["effective_cl"])
        mod = state["ability_modifiers"][selected]
        days = max(2, int(d6) + pb - mod)
        talents_in_sphere = 0
        dc_die: int | None = None
        if training_type == "new_sphere":
            dc_die = params.get("dc_die_result")
            if not isinstance(dc_die, int) or not 1 <= dc_die <= 4:
                blockers.append(_block("TRAINING_DC_DIE_INVALID", pointer + "/parameters/dc_die_result", "New-Sphere training requires an integer d4 result from 1 through 4."))
                return None, blockers, [_binding(source, "training_source", state["record_event_ids"].get(source["record_id"]))], {}
            dc = 10 + dc_die + len(state["known_spheres"])
            dc_formula_id = "TIANXIA.TRAINING.NEW_SPHERE_DC.v1"
            slot_cost = 1
        elif training_type == "known_sphere_talent":
            sphere_id = _authority(record).get("sphere_id")
            talents_in_sphere = sum(1 for rid in state["known_talents"] if (_authority(self.projects._resolve_locked_record_after_proof(conn, project_id, rid) or {}).get("sphere_id") == sphere_id))
            dc = 10 + talents_in_sphere
            dc_formula_id = "TIANXIA.TRAINING.KNOWN_SPHERE_TALENT_DC.v1"
            slot_cost = int(_authority(record).get("trained_choice_cost", 1))
        else:
            training_rule = _authority(record).get("training") or {}
            dc = int(training_rule.get("dc", _authority(record).get("fixed_expression", {}).get("dc", 0)))
            dc_formula_id = str(training_rule.get("dc_formula_id", "TIANXIA.TRAINING.RECORDED_ART_DC.v1"))
            slot_cost = int(training_rule.get("trained_choice_cost", 1))
        computed_result = "success" if int(check_total) >= int(dc) else "failure"
        tamper_fields = [("computed_training_days", days, "TRAINING_DAYS_AUTHORED_OR_TAMPERED"), ("computed_dc", dc, "TRAINING_DC_AUTHORED_OR_TAMPERED"), ("result", computed_result, "TRAINING_RESULT_AUTHORED_OR_TAMPERED"), ("slot_cost", slot_cost if computed_result == "success" else 0, "NEW_SPHERE_TRAINED_CHOICE_NOT_CONSUMED" if training_type == "new_sphere" else "TRAINING_SLOT_COST_AUTHORED_OR_TAMPERED")]
        for field, computed, code in tamper_fields:
            if field in params and params[field] != computed:
                blockers.append(_block(code, pointer + f"/parameters/{field}", "A deterministic training output was client-authored or does not match application calculation.", supplied=params[field], computed=computed))
        if blockers:
            return None, blockers, [_binding(source, "training_source", state["record_event_ids"].get(source["record_id"]))], {}
        txn = {
            "schema_version": TRAINING_V1,
            "attempt_id": attempt_id,
            "retry_of_attempt_id": params.get("retry_of_attempt_id"),
            "character_cl": choice["effective_cl"],
            "training_type": training_type,
            "target_record_id": record["record_id"],
            "target_record_hash": record["record_hash"],
            "training_source_record_id": source["record_id"],
            "training_source_record_hash": source["record_hash"],
            "selected_ability": selected,
            "time_die_result": d6,
            "pb_input": pb,
            "ability_modifier_input": mod,
            "training_days_formula_id": "TIANXIA.TRAINING.DAYS.1D6_PLUS_PB_MINUS_MOD_MIN2.v1",
            "computed_training_days": days,
            "dc_die_result": dc_die,
            "dc_formula_id": dc_formula_id,
            "dc_inputs": {"known_spheres": len(state["known_spheres"]), "known_talents_in_sphere": talents_in_sphere},
            "computed_dc": dc,
            "check_total": check_total,
            "result": computed_result,
            "slot_cost": slot_cost if computed_result == "success" else 0,
            "acquisition_event_id": event_id if computed_result == "success" else None,
        }
        self.registry.validate(txn)
        bindings = [_binding(source, "training_source", state["record_event_ids"].get(source["record_id"]))]
        return txn, [], bindings, {"days": days, "dc": dc, "result": computed_result}

    def _manual_entry(
        self,
        conn,
        project_id: str,
        manual: dict[str, Any],
        state: dict[str, Any],
        pointer: str,
        cl: int,
        event_id: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
        """Compile a Recorded Art only from published machine-readable authority."""
        auth = _authority(manual)
        art = auth.get("recorded_art")
        if not isinstance(art, dict):
            code = "MANUAL_DIFFICULTY_SEMANTICS_UNRESOLVED" if auth.get("fixed_expression") else "RECORDED_ART_AUTHORITY_MISSING"
            return None, [_block(code, pointer, "The Recorded Art lacks normalized PHB-v0.7 authority; legacy fixed-DC/manual blobs cannot compile.")], []
        required = {
            "parent_manual_record_id",
            "technique_name",
            "associated_sphere_record_ids",
            "expression_kind",
            "reproduced_component_record_ids",
            "execution_derivation",
            "learning_dc",
            "study_time",
            "allowed_study_abilities",
            "requirements",
            "fixed_expression_only",
            "grants_sphere",
            "grants_talent",
            "grants_modification_permission",
        }
        missing = sorted(required - set(art))
        if missing:
            return None, [_block("RECORDED_ART_AUTHORITY_INCOMPLETE", pointer, "The normalized Recorded Art authority is incomplete.", missing=missing)], []
        if not art.get("fixed_expression_only") or art.get("grants_sphere") or art.get("grants_talent") or art.get("grants_modification_permission"):
            return None, [_block("RECORDED_ART_FIXED_EXPRESSION_INVARIANT_VIOLATED", pointer, "A Recorded Art must remain a fixed expression and grant no flexible Sphere, talent, or modification permission.")], []
        if art.get("expression_kind") not in RECORDED_ART_EXPRESSION_KINDS:
            return None, [_block("RECORDED_ART_EXPRESSION_KIND_UNSUPPORTED", pointer, "The expression lane is not a published fail-closed Recorded Art lane.", expression_kind=art.get("expression_kind"))], []

        parent, parent_issues = self._record(conn, project_id, art.get("parent_manual_record_id"), pointer + "/parent_manual_record_id")
        blockers = list(parent_issues)
        bindings: list[dict[str, Any]] = []
        if not parent:
            return None, blockers, bindings
        parent_auth = _authority(parent).get("manual")
        if not isinstance(parent_auth, dict):
            blockers.append(_block("RECORDED_ART_PARENT_MANUAL_REQUIRED", pointer, "The parent record is not a complete published Manual authority.", parent_manual_record_id=parent["record_id"]))
        elif manual["record_id"] not in parent_auth.get("technique_record_ids", []):
            blockers.append(_block("MANUAL_GROUP_TECHNIQUE_RELATION_BROKEN", pointer, "The parent Manual does not list this exact technique.", parent_manual_record_id=parent["record_id"], technique_record_id=manual["record_id"]))
        bindings.append(_binding(parent, "recorded_art_parent_manual", state["record_event_ids"].get(parent["record_id"])))

        sphere_records: list[dict[str, Any]] = []
        sphere_ids = art.get("associated_sphere_record_ids")
        if not isinstance(sphere_ids, list) or not sphere_ids:
            blockers.append(_block("RECORDED_ART_ASSOCIATED_SPHERES_REQUIRED", pointer, "At least one associated Sphere is required for the DM-facing fixed-expression line."))
        else:
            for sphere_id in sphere_ids:
                sphere, issues = self._record(conn, project_id, sphere_id, pointer + "/associated_sphere_record_ids")
                blockers.extend(issues)
                if sphere:
                    if sphere.get("content_type") != "sphere":
                        blockers.append(_block("RECORDED_ART_ASSOCIATED_SPHERE_INVALID", pointer, "An associated Sphere reference does not resolve to a Sphere.", record_id=sphere_id, content_type=sphere.get("content_type")))
                    sphere_records.append(sphere)
                    bindings.append(_binding(sphere, "recorded_art_associated_sphere", state["record_event_ids"].get(sphere_id)))

        component_records: list[dict[str, Any]] = []
        component_ids = art.get("reproduced_component_record_ids")
        if not isinstance(component_ids, list) or not component_ids:
            blockers.append(_block("RECORDED_ART_COMPONENT_AUTHORITY_MISSING", pointer, "A Recorded Art needs at least one published reproduced component."))
        else:
            for component_id in component_ids:
                component, issues = self._record(conn, project_id, component_id, pointer + "/reproduced_component_record_ids")
                blockers.extend(issues)
                if component:
                    component_records.append(component)
                    component_sphere = _authority(component).get("sphere_id")
                    if component_sphere and component_sphere not in sphere_ids:
                        blockers.append(_block("MANUAL_REPRODUCED_RECORD_WRONG_SPHERE", pointer, "A reproduced component belongs to a Sphere omitted from the fixed expression.", component_record_id=component_id, component_sphere_id=component_sphere, associated_sphere_ids=sphere_ids))
                    bindings.append(_binding(component, "recorded_art_reproduced_component", state["record_event_ids"].get(component_id)))

        grammar_records = {
            row["record_id"]: row
            for row in [manual, parent, *sphere_records, *component_records]
            if isinstance(row, dict) and isinstance(row.get("record_id"), str)
        }
        for issue in recorded_art_expression_issues(
            record_id=manual["record_id"],
            art=art,
            record_map=grammar_records,
        ):
            details = {key: value for key, value in issue.items() if key not in {"code", "record_id", "message"}}
            blockers.append(_block(
                issue["code"],
                pointer,
                issue.get("message", "The Recorded Art fails the exact published expression grammar or executable-action contract."),
                **details,
            ))

        derivation = art.get("execution_derivation") or {}
        if derivation.get("mode") != "copy_exact_published_template":
            blockers.append(_block("RECORDED_ART_EXECUTION_DERIVATION_UNPROVEN", pointer, "Only exact published execution-template copying is implemented in this phase.", derivation=derivation))
        source_record_id = derivation.get("source_record_id")
        if source_record_id not in component_ids:
            blockers.append(_block("RECORDED_ART_COMPONENT_RELATION_INVALID", pointer, "The execution source is not one of the reproduced components.", source_record_id=source_record_id, component_record_ids=component_ids))
        source_component = next((x for x in component_records if x["record_id"] == source_record_id), None)
        template = None
        if source_component:
            template = next((x for x in source_component.get("execution_templates", []) if x.get("template_id") == derivation.get("template_id") and x.get("template_type") == "action"), None)
        if not template:
            blockers.append(_block("RECORDED_ART_EXECUTION_DERIVATION_UNPROVEN", pointer, "The exact published action template does not exist on the declared component.", source_record_id=source_record_id, template_id=derivation.get("template_id")))
        execution = deepcopy(template.get("payload")) if template else {}
        execution_required = {"action_id", "name", "timing", "cost", "range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay"}
        missing_execution = sorted(execution_required - set(execution))
        if missing_execution:
            blockers.append(_block("RECORDED_ART_EXECUTION_INCOMPLETE", pointer, "The published action template cannot produce a complete playable technique.", missing=missing_execution))

        learning = art.get("learning_dc") or {}
        mode = learning.get("mode")
        if mode == "difficulty_formula":
            difficulty = learning.get("difficulty")
            if not isinstance(difficulty, int) or difficulty < 0:
                blockers.append(_block("RECORDED_ART_DIFFICULTY_REQUIRED", pointer, "Difficulty mode requires a non-negative published Difficulty."))
            if "explicit_dc" in learning or "override_rule_record_id" in learning:
                blockers.append(_block("RECORDED_ART_FIXED_DC_FORBIDDEN", pointer + "/learning_dc", "Difficulty and a fixed/override DC cannot coexist; legacy DC text must be normalized explicitly rather than guessed."))
            dm_suffix = f"Difficulty {difficulty}" if isinstance(difficulty, int) else "Difficulty unresolved"
        elif mode == "explicit_dc_override":
            explicit_dc = learning.get("explicit_dc")
            rule_id = learning.get("override_rule_record_id")
            if not isinstance(explicit_dc, int) or explicit_dc < 0 or not rule_id:
                blockers.append(_block("RECORDED_ART_EXPLICIT_DC_AUTHORITY_MISSING", pointer, "An explicit DC override requires an exact published DC and overriding rule record."))
            if "difficulty" in learning:
                blockers.append(_block("RECORDED_ART_DIFFICULTY_DC_CONFLICT", pointer + "/learning_dc", "An explicit DC override cannot also be interpreted as Recorded Art Difficulty."))
            override, issues = self._record(conn, project_id, rule_id, pointer + "/learning_dc/override_rule_record_id") if rule_id else (None, [])
            blockers.extend(issues)
            if override:
                bindings.append(_binding(override, "recorded_art_explicit_dc_override", state["record_event_ids"].get(rule_id)))
            dm_suffix = f"DC {explicit_dc} (specific override)" if isinstance(explicit_dc, int) else "DC unresolved"
        else:
            blockers.append(_block("MANUAL_DIFFICULTY_SEMANTICS_UNRESOLVED", pointer, "Learning authority must explicitly choose difficulty_formula or explicit_dc_override.", mode=mode))
            dm_suffix = "learning rule unresolved"

        study_time = art.get("study_time") or {}
        if study_time.get("mode") not in {"printed_days", "training_scene", "lesson", "downtime_interval", "travel_rest_scenes", "named_human_adjudication"}:
            blockers.append(_block("RECORDED_ART_STUDY_TIME_UNRESOLVED", pointer, "The Manual lacks a typed PHB-v0.7 study-time basis.", study_time=study_time))
        if not isinstance(art.get("allowed_study_abilities"), list) or not art.get("allowed_study_abilities") or any(x not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} for x in art.get("allowed_study_abilities", [])):
            blockers.append(_block("RECORDED_ART_STUDY_ABILITY_AUTHORITY_INVALID", pointer, "Allowed study abilities must be a non-empty subset of the six abilities."))
        if art.get("requirements") != manual.get("legality", {}).get("prerequisites", []):
            blockers.append(_block("RECORDED_ART_REQUIREMENT_AUTHORITY_DIVERGED", pointer, "Recorded Art requirements must be identical to the catalog legality prerequisites."))
        if blockers:
            return None, blockers, bindings

        entry = {
            "record_id": manual["record_id"],
            "display_name": manual["display_name"],
            "parent_manual_record_id": parent["record_id"],
            "parent_manual_name": parent["display_name"],
            "lineage_source": parent_auth.get("lineage_source"),
            "technique_name": art["technique_name"],
            "dm_facing_line": f"Sphere of {' and '.join(_dm_line_label(x['display_name']) for x in sphere_records)} — {_dm_line_label(art['technique_name'])} — {', '.join(_dm_line_label(x['display_name']) for x in component_records)} — {dm_suffix}",
            "associated_sphere_record_ids": [x["record_id"] for x in sphere_records],
            "associated_sphere_names": [x["display_name"] for x in sphere_records],
            "reproduced_component_record_ids": [x["record_id"] for x in component_records],
            "reproduced_component_names": [x["display_name"] for x in component_records],
            "expression_kind": art["expression_kind"],
            "learning_dc": deepcopy(learning),
            "study_time": deepcopy(study_time),
            "allowed_study_abilities": deepcopy(art["allowed_study_abilities"]),
            "requirements": deepcopy(art["requirements"]),
            "execution": execution,
            "execution_derivation": {
                "derivation_kind": "published_expression",
                "source_execution_record_id": source_record_id,
                "component_record_ids": [x["record_id"] for x in component_records],
                "source_template_hash": sha256_json(template),
                "compiled_payload_hash": sha256_json(execution),
            },
            "linked_action_id": execution["action_id"],
            "fixed_expression_warning": "Learning this Recorded Art grants no source Sphere, source talent, flexible package, or modification permission.",
            "learned_at_cl": cl,
            "acquisition_event_id": event_id,
            "record_hash": manual["record_hash"],
        }
        return entry, [], bindings

    def _training(
        self,
        conn,
        project_id: str,
        state: dict[str, Any],
        record: dict[str, Any],
        choice: dict[str, Any],
        event_id: str,
        pointer: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        params = choice["parameters"]
        blockers: list[dict[str, Any]] = []
        source, issues = self._record(conn, project_id, params.get("training_source_record_id"), pointer + "/parameters/training_source_record_id")
        blockers.extend(issues)
        if not source:
            return None, blockers, [], {}
        kind_map = {"sphere_training_attempt": "new_sphere", "talent_training_attempt": "known_sphere_talent", "manual_training_attempt": "recorded_art"}
        training_type = kind_map[choice["kind"]]
        source_access = _authority(source).get("training_source_access") or {}
        if training_type not in source_access.get("training_types", []):
            blockers.append(_block("TRAINING_SOURCE_TYPE_NOT_AUTHORIZED", pointer, "The selected source does not authorize this training/study type.", training_type=training_type, source_record_id=source["record_id"]))
        targets = source_access.get("target_record_ids")
        if not isinstance(targets, list) or record["record_id"] not in targets:
            code = "RECORDED_ART_SOURCE_DOES_NOT_TEACH_TECHNIQUE" if training_type == "recorded_art" else "TRAINING_SOURCE_DOES_NOT_TEACH_TARGET"
            blockers.append(_block(code, pointer, "The selected source has no published teaching relation to this exact target.", source_record_id=source["record_id"], target_record_id=record["record_id"]))
        access_mode = source_access.get("mode")
        access_event_id: str | None = None
        if access_mode == "requires_access_event":
            if source["record_id"] not in state["training_sources"]:
                blockers.append(_block("TRAINING_SOURCE_ACCESS_EVENT_REQUIRED", pointer, "The character has no prior causal access event for this source.", source_record_id=source["record_id"]))
            access_event_id = state["record_event_ids"].get(source["record_id"])
        elif access_mode == "intrinsic_known_sphere_practice" and training_type == "known_sphere_talent":
            sphere_id = _authority(record).get("sphere_id")
            if sphere_id not in state["known_spheres"]:
                blockers.append(_block("TRAINING_INTRINSIC_SPHERE_NOT_KNOWN", pointer, "Intrinsic talent practice requires the target Sphere to be known.", sphere_id=sphere_id))
            access_event_id = state["record_event_ids"].get(sphere_id)
        else:
            blockers.append(_block("TRAINING_SOURCE_ACCESS_MODE_UNSUPPORTED", pointer, "Training-source access is missing or not deterministically supported.", mode=access_mode))
        if not access_event_id:
            blockers.append(_block("TRAINING_SOURCE_ACCESS_PROVENANCE_MISSING", pointer, "The source-access claim lacks an exact causal event.", source_record_id=source["record_id"]))

        selected = params.get("selected_ability")
        all_abilities = {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
        art_authority = _authority(record).get("recorded_art") if training_type == "recorded_art" else None
        allowed_abilities = set(art_authority.get("allowed_study_abilities", [])) if isinstance(art_authority, dict) else {"INT", "WIS"}
        if selected not in all_abilities or selected not in allowed_abilities:
            blockers.append(_block("RECORDED_ART_STUDY_ABILITY_INVALID" if training_type == "recorded_art" else "TRAINING_ABILITY_INVALID", pointer + "/parameters/selected_ability", "The selected ability is not authorized for this training/study approach.", selected=selected, allowed=sorted(allowed_abilities)))
        check_die = params.get("check_die_result")
        if not isinstance(check_die, int) or not 1 <= check_die <= 20:
            blockers.append(_block("TRAINING_CHECK_DIE_INVALID", pointer + "/parameters/check_die_result", "The recorded d20 result must be an integer from 1 through 20."))
        if "check_total" in params:
            blockers.append(_block("TRAINING_CHECK_TOTAL_AUTHORED_OR_TAMPERED", pointer + "/parameters/check_total", "The application derives the check total; clients may supply only the bounded d20 result."))
        attempt_id = params.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            blockers.append(_block("TRAINING_ATTEMPT_ID_REQUIRED", pointer + "/parameters/attempt_id", "Every attempt requires a stable identity."))
        if attempt_id in state["training_transactions"]:
            blockers.append(_block("TRAINING_ATTEMPT_ID_DUPLICATE", pointer + "/parameters/attempt_id", "A training/study attempt identity cannot be reused.", attempt_id=attempt_id))
        retry_of = params.get("retry_of_attempt_id")
        if retry_of is not None:
            prior_attempt = state["training_transactions"].get(retry_of)
            if not prior_attempt or prior_attempt.get("result") != "failure" or prior_attempt.get("target_record_id") != record["record_id"]:
                blockers.append(_block("TRAINING_RETRY_IDENTITY_INVALID", pointer + "/parameters/retry_of_attempt_id", "A retry must identify a prior failed attempt for the same target.", retry_of_attempt_id=retry_of))
        if blockers:
            binding = _binding(source, "training_source", access_event_id)
            return None, blockers, [binding], {}

        pb = _pb(choice["effective_cl"])
        selected_mod = state["ability_modifiers"][selected]
        d6: int | None = None
        dc_die: int | None = None
        difficulty: int | None = None
        same_cl_arts_before = 0
        study_time_mode = "ordinary_training_days"
        study_time_value: int | None = None
        if training_type in {"new_sphere", "known_sphere_talent"}:
            d6 = params.get("time_die_result")
            if not isinstance(d6, int) or not 1 <= d6 <= 6:
                blockers.append(_block("TRAINING_TIME_DIE_INVALID", pointer + "/parameters/time_die_result", "Ordinary Sphere/talent training requires an integer d6 result from 1 through 6."))
                days = 0
            else:
                days = max(2, int(d6) + pb - selected_mod)
            training_days_formula_id = "TIANXIA.TRAINING.DAYS.1D6_PLUS_PB_MINUS_MOD_MIN2.v1"
            study_time_value = days
        else:
            study_time = art_authority.get("study_time") or {}
            study_time_mode = study_time.get("mode")
            study_time_value = study_time.get("value") if isinstance(study_time.get("value"), int) else None
            if study_time_mode == "printed_days":
                days = int(study_time_value or 0)
                if days < 1:
                    blockers.append(_block("RECORDED_ART_STUDY_TIME_UNRESOLVED", pointer, "Printed-day study requires a positive published day count."))
            elif study_time_mode in {"training_scene", "lesson", "downtime_interval", "travel_rest_scenes", "named_human_adjudication"}:
                days = 0
            else:
                days = 0
                blockers.append(_block("RECORDED_ART_STUDY_TIME_UNRESOLVED", pointer, "Recorded Art study time is not a supported published/adjudicated basis."))
            training_days_formula_id = "TIANXIA.RECORDED_ART.STUDY_TIME.PUBLISHED_OR_ADJUDICATED.v1"

        talents_in_sphere = 0
        if training_type == "new_sphere":
            dc_die = params.get("dc_die_result")
            if not isinstance(dc_die, int) or not 1 <= dc_die <= 4:
                blockers.append(_block("TRAINING_DC_DIE_INVALID", pointer + "/parameters/dc_die_result", "New-Sphere training requires an integer d4 result from 1 through 4."))
                dc = 0
            else:
                dc = 10 + dc_die + len(state["known_spheres"])
            dc_formula_id = "TIANXIA.TRAINING.NEW_SPHERE_DC.v1"
            learning_dc_mode = "ordinary_training"
            slot_cost = 1
        elif training_type == "known_sphere_talent":
            sphere_id = _authority(record).get("sphere_id")
            talents_in_sphere = sum(1 for rid in state["known_talents"] if (_authority(self.projects._resolve_locked_record_after_proof(conn, project_id, rid) or {}).get("sphere_id") == sphere_id))
            dc = 10 + talents_in_sphere
            dc_formula_id = "TIANXIA.TRAINING.KNOWN_SPHERE_TALENT_DC.v1"
            learning_dc_mode = "ordinary_training"
            slot_cost = int(_authority(record).get("trained_choice_cost", 1))
        else:
            learning = art_authority.get("learning_dc") or {}
            learning_dc_mode = learning.get("mode")
            same_cl_arts_before = sum(1 for art in state["recorded_arts"] if int(art.get("learned_at_cl", -1)) == int(choice["effective_cl"]))
            if learning_dc_mode == "difficulty_formula":
                difficulty = learning.get("difficulty")
                if not isinstance(difficulty, int) or difficulty < 0:
                    blockers.append(_block("RECORDED_ART_DIFFICULTY_REQUIRED", pointer, "Difficulty-formula study requires a published non-negative Difficulty."))
                    dc = 0
                else:
                    dc = 10 + difficulty + 2 * same_cl_arts_before
                dc_formula_id = "TIANXIA.RECORDED_ART.DC.10_PLUS_DIFFICULTY_PLUS_2_PER_ART_THIS_CL.v1"
            elif learning_dc_mode == "explicit_dc_override":
                dc = int(learning.get("explicit_dc", -1))
                if dc < 0 or not learning.get("override_rule_record_id"):
                    blockers.append(_block("RECORDED_ART_EXPLICIT_DC_AUTHORITY_MISSING", pointer, "The specific learning-DC override is incomplete."))
                dc_formula_id = "TIANXIA.RECORDED_ART.DC.EXPLICIT_PUBLISHED_OVERRIDE.v1"
            else:
                dc = 0
                dc_formula_id = "TIANXIA.RECORDED_ART.DC.UNRESOLVED"
                blockers.append(_block("MANUAL_DIFFICULTY_SEMANTICS_UNRESOLVED", pointer, "Recorded Art learning authority is neither Difficulty nor an explicit published override."))
            slot_cost = 0

        path = self.projects._resolve_locked_record_after_proof(conn, project_id, state["paths"][0]) if state["paths"] else None
        if not path:
            blockers.append(_block("PATH_REQUIRED_FOR_CULTIVATION_CHECK", pointer, "Training/study requires a causal Path to derive PB and the check ability."))
            check_ability = selected
        else:
            check_ability = selected if training_type == "recorded_art" else _authority(path).get("key_ability")
        if check_ability not in all_abilities:
            blockers.append(_block("TRAINING_CHECK_ABILITY_AUTHORITY_INVALID", pointer, "The deterministic Cultivation Check ability is missing or invalid.", check_ability=check_ability))
            check_mod = 0
        else:
            check_mod = state["ability_modifiers"][check_ability]
        computed_check_total = int(check_die or 0) + pb + check_mod
        computed_result = "success" if computed_check_total >= int(dc) else "failure"
        tamper_fields = [
            ("computed_training_days", days, "TRAINING_DAYS_AUTHORED_OR_TAMPERED"),
            ("computed_dc", dc, "TRAINING_DC_AUTHORED_OR_TAMPERED"),
            ("computed_check_total", computed_check_total, "TRAINING_CHECK_TOTAL_AUTHORED_OR_TAMPERED"),
            ("result", computed_result, "TRAINING_RESULT_AUTHORED_OR_TAMPERED"),
            ("slot_cost", slot_cost if computed_result == "success" else 0, "NEW_SPHERE_TRAINED_CHOICE_NOT_CONSUMED" if training_type == "new_sphere" else "TRAINING_SLOT_COST_AUTHORED_OR_TAMPERED"),
        ]
        for field, computed, code in tamper_fields:
            if field in params and params[field] != computed:
                blockers.append(_block(code, pointer + f"/parameters/{field}", "A deterministic output was client-authored or does not match application calculation.", supplied=params[field], computed=computed))
        if training_type == "recorded_art" and params.get("slot_cost", 0) not in {0, None}:
            blockers.append(_block("RECORDED_ART_TRAINED_CHOICE_COST_FORBIDDEN", pointer, "Recorded Art study is separate from the three Sphere/talent trained choices."))
        if blockers:
            return None, blockers, [_binding(source, "training_source", access_event_id)], {}

        txn = {
            "schema_version": TRAINING_V2,
            "attempt_id": attempt_id,
            "retry_of_attempt_id": retry_of,
            "character_cl": choice["effective_cl"],
            "training_type": training_type,
            "target_record_id": record["record_id"],
            "target_record_hash": record["record_hash"],
            "training_source_record_id": source["record_id"],
            "training_source_record_hash": source["record_hash"],
            "training_source_access_event_id": access_event_id,
            "selected_ability": selected,
            "time_die_result": d6,
            "pb_input": pb,
            "ability_modifier_input": selected_mod,
            "training_days_formula_id": training_days_formula_id,
            "computed_training_days": days,
            "study_time_mode": study_time_mode,
            "study_time_value": study_time_value,
            "dc_die_result": dc_die,
            "dc_formula_id": dc_formula_id,
            "dc_inputs": {"known_spheres": len(state["known_spheres"]), "known_talents_in_sphere": talents_in_sphere, "recorded_art_difficulty": difficulty, "recorded_arts_learned_this_cl_before": same_cl_arts_before},
            "computed_dc": dc,
            "recorded_art_difficulty": difficulty,
            "recorded_arts_learned_this_cl_before": same_cl_arts_before,
            "learning_dc_mode": learning_dc_mode,
            "check_die_result": check_die,
            "check_formula_id": "TIANXIA.RECORDED_ART.STUDY_CHECK.D20_PLUS_PB_PLUS_RELEVANT_ABILITY.v1" if training_type == "recorded_art" else "TIANXIA.CULTIVATION_CHECK.D20_PLUS_PB_PLUS_PATH_KEY_ABILITY.v1",
            "check_ability": check_ability,
            "check_ability_modifier_input": check_mod,
            "check_pb_input": pb,
            "computed_check_total": computed_check_total,
            "result": computed_result,
            "slot_cost": slot_cost if computed_result == "success" else 0,
            "acquisition_event_id": event_id if computed_result == "success" else None,
        }
        self.registry.validate(txn)
        return txn, [], [_binding(source, "training_source_access", access_event_id)], {"days": days, "dc": dc, "check_total": computed_check_total, "result": computed_result}

    def _choice_event(
        self,
        *,
        conn,
        row,
        project: dict[str, Any],
        state: dict[str, Any],
        choice: dict[str, Any],
        index: int,
        sequence: int,
        previous_hash: str,
        generic_prefix: list[dict[str, Any]],
        record_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
        pointer = f"/choices/{index}"
        kind = choice["kind"]
        blockers: list[dict[str, Any]] = []
        if kind not in HF1_KINDS:
            return None, state, [_block("UNKNOWN_STAGE2_EVENT_KIND", pointer + "/kind", "The event kind is not part of the HF1 advancement contract.", kind=kind)]
        record, issues = self._record(
            conn,
            row["project_id"],
            choice.get("record_id"),
            pointer + "/record_id",
            record_cache=record_cache,
        )
        blockers.extend(issues)
        if not record:
            return None, state, blockers
        allowed_content_types = allowed_content_types_for_kind(kind) or frozenset()
        if record.get("content_type") not in allowed_content_types:
            blockers.append(_block(
                "EVENT_KIND_CONTENT_TYPE_MISMATCH",
                pointer + "/record_id",
                "The event kind is bound to a different catalog content type; catalog-authored allowed_kinds cannot override the reducer's runtime type contract.",
                kind=kind,
                record_id=record["record_id"],
                supplied_content_type=record.get("content_type"),
                allowed_content_types=sorted(allowed_content_types),
            ))
        parameters = choice.get("parameters") or {}
        unsupported_parameters = sorted(set(parameters) - set(KIND_PARAMETER_KEYS.get(kind, frozenset())))
        if unsupported_parameters:
            blockers.append(_block(
                "UNSUPPORTED_EVENT_PARAMETER",
                pointer + "/parameters",
                "The proposal contains parameters that are not part of this event kind's typed input contract.",
                kind=kind,
                unsupported_parameters=unsupported_parameters,
                allowed_parameters=sorted(KIND_PARAMETER_KEYS.get(kind, frozenset())),
            ))
        blockers.extend(self._stage2_authority(record, kind, choice["acquisition_channel"], pointer))
        relation_blockers, relation_bindings = self._legality_relation_blockers(
            conn,
            row["project_id"],
            state,
            record,
            pointer,
            record_cache=record_cache,
        )
        blockers.extend(relation_blockers)
        blockers.extend(self._cardinality_blockers(state, kind, record, choice, pointer))
        insight_repeat_index: int | None = None
        if kind == "cultivation_insight_acquisition":
            insight_blockers, insight_repeat_index = self._insight_occurrence_blockers(state, record, choice, pointer)
            blockers.extend(insight_blockers)
        minimum_cl = record.get("legality", {}).get("minimum_cl")
        if isinstance(minimum_cl, int) and choice["effective_cl"] < minimum_cl:
            blockers.append(_block("ACQUISITION_BEFORE_MINIMUM_CL", pointer, "The event occurs before the record's published minimum CL.", minimum_cl=minimum_cl, effective_cl=choice["effective_cl"]))
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2-hf1-event:{row['proposal_id']}:{index+1}:{sha256_json(choice)}"))
        # Legal phase ordering.
        cl = int(choice["effective_cl"])
        if state["current_cl"] > 0 and cl < state["current_cl"]:
            blockers.append(_block(
                "HISTORICAL_MECHANICAL_BACKDATING_FORBIDDEN",
                pointer + "/effective_cl",
                "An ordinary Stage 2 proposal cannot insert mechanical history behind the established current CL; legacy repair requires the explicit migration pipeline.",
                effective_cl=cl,
                current_cl=state["current_cl"],
            ))
        if cl >= 2 and kind != "level_advance" and cl > state["current_cl"]:
            blockers.append(_block("ACQUISITION_BEFORE_LEVEL_ADVANCE", pointer, "CL2+ mechanical choices require the causal level-advance event to establish that CL first.", effective_cl=cl, current_cl=state["current_cl"]))
        if kind == "level_advance" and cl != state["current_cl"] + 1:
            blockers.append(_block("LEVEL_SEQUENCE_INVALID", pointer, "Level advancement must be contiguous and occur exactly once.", expected=state["current_cl"] + 1, actual=cl))
        if kind != "level_advance" and cl > 1 and cl != state["current_cl"]:
            blockers.append(_block("EVENT_EFFECTIVE_CL_NOT_ACTIVE", pointer, "The event's CL is not the currently established CL.", effective_cl=cl, current_cl=state["current_cl"]))
        if kind in {"background_acquisition", "background_sphere_acquisition", "background_talent_acquisition", "origin_insight_acquisition", "path_acquisition", "sect_trial_sphere_acquisition", "sect_trial_talent_acquisition", "ai_bootstrap_sphere_acquisition", "ai_bootstrap_talent_acquisition"} and cl != 1:
            blockers.append(_block("CL1_CREATION_EVENT_AT_WRONG_LEVEL", pointer, "Background, Origin, Path, and sect-trial creation channels are CL1-only."))
        if kind in CREATION_KINDS and state["current_cl"] > 1:
            blockers.append(_block("CREATION_EVENT_AFTER_INITIAL_LEVEL", pointer, "Character-creation events may occur only before or during the initial CL1 build; later repair must use an explicit migration."))
        if blockers:
            return None, state, blockers

        details = deepcopy(choice.get("parameters") or {})
        if kind == "cultivation_insight_acquisition":
            details["repeat_index"] = insight_repeat_index
        calculation = {"rule_id": _authority(record).get("rule_id", f"{record['record_id']}.stage2"), "formula": None, "inputs": {}, "outputs": {}, "trace": {}}
        bindings = [_binding(record, "subject_authority", state["record_event_ids"].get(record["record_id"]))] + relation_bindings
        created_records: list[str] = []
        updated_records: list[str] = []
        event_type = "acquire"
        training_txn: dict[str, Any] | None = None
        none_state: dict[str, Any] | None = None
        next_state = _deepcopy(state)
        auth = _authority(record)
        # Keep the exact immutable authority available to later choices in
        # this same proposal. In particular, Subpath cardinality and
        # milestone checks must use explicit owning_path_id from the locked
        # record, never a parent mirror or relationship fallback.
        self._remember_authority(next_state, record, event_id)

        duplicate_kinds = {"background_sphere_acquisition", "background_talent_acquisition", "sect_trial_talent_acquisition", "level_talent_acquisition", "new_sphere_bonus_talent_acquisition", "equipment_acquisition"}
        if kind in duplicate_kinds:
            blockers.extend(self._duplicate_blockers(state, record, kind, pointer))

        if kind == "starting_state":
            generation = auth.get("ability_generation") or {}
            scores = details.get("ability_scores")
            if generation.get("method") != "point_buy" or not isinstance(scores, dict) or set(scores) != {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
                blockers.append(_block("ABILITY_GENERATION_AUTHORITY_INVALID", pointer, "Starting scores must satisfy a published generation rule and complete six-score input."))
            else:
                try:
                    cost = sum(_point_buy_cost(int(scores[a])) for a in scores)
                except Exception:
                    cost = -1
                if cost != int(generation.get("budget", 27)):
                    blockers.append(_block("ABILITY_POINT_BUY_BUDGET_INVALID", pointer, "Starting scores do not spend the exact published point-buy budget.", computed_cost=cost, required_budget=generation.get("budget", 27)))
                calculation["inputs"] = {"ability_scores": scores, "generation_rule": generation}
                calculation["outputs"] = {"ability_scores": scores, "ability_modifiers": {a: _ability_modifier(scores[a]) for a in scores}, "point_buy_cost": cost}
                created_records = [record["record_id"]]
        elif kind == "ability_score_change":
            if not state["ability_scores"]:
                blockers.append(_block("ABILITY_SCORES_NOT_ESTABLISHED", pointer, "An ability change requires a causal starting-score event."))
            deltas = details.get("deltas")
            rule = auth.get("ability_change") or {}
            if cl not in rule.get("allowed_cls", []):
                blockers.append(_block("ABILITY_CHANGE_AT_ILLEGAL_CL", pointer, "The published advancement record does not authorize an ability change at this CL.", allowed_cls=rule.get("allowed_cls", []), cl=cl))
            if not isinstance(deltas, dict) or any(k not in state["ability_scores"] or not isinstance(v, int) for k, v in (deltas or {}).items()):
                blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "Ability changes require a bounded published delta allocation."))
            else:
                positive = sum(max(0, v) for v in deltas.values())
                if positive != int(rule.get("budget", 2)) or any(v not in rule.get("allowed_deltas", [1, 2]) for v in deltas.values()):
                    blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "The supplied deltas do not match the published ASI allocation budget or allowed increments.", deltas=deltas, rule=rule))
                new_scores = {a: state["ability_scores"][a] + int(deltas.get(a, 0)) for a in state["ability_scores"]}
                cap = int(rule.get("cap", 20))
                if any(v > cap for v in new_scores.values()):
                    blockers.append(_block("ABILITY_SCORE_CAP_EXCEEDED", pointer, "A resulting ability score exceeds the published cap.", cap=cap, scores=new_scores))
                next_state["ability_scores"] = new_scores
                next_state["ability_modifiers"] = {a: _ability_modifier(v) for a, v in new_scores.items()}
                hp_after, resources_after, extra_bindings, recalc_trace = self._recalculate_after_ability(
                    conn,
                    row["project_id"],
                    next_state,
                    state["ability_scores"],
                    path_id=auth.get("path_id"),
                )
                bindings.extend(extra_bindings)
                calculation["inputs"] = {"prior_scores": state["ability_scores"], "deltas": deltas, "rule": rule}
                calculation["outputs"] = {"ability_scores": new_scores, "ability_modifiers": next_state["ability_modifiers"], "hp_after": hp_after, "resources_after": resources_after}
                calculation["trace"] = recalc_trace
                updated_records = [record["record_id"]]
        elif kind == "cultivation_insight_acquisition":
            rule = auth.get("ability_change") or auth.get("insight_ability_change")
            minimum = auth.get("minimum_cl")
            if isinstance(minimum, int) and cl < minimum:
                blockers.append(_block("CULTIVATION_INSIGHT_AT_ILLEGAL_CL", pointer, "The Cultivation Insight is not authorized before its published minimum CL.", minimum_cl=minimum, cl=cl))
            ability = details.get("ability")
            amount = details.get("amount")
            if rule:
                if not state["ability_scores"]:
                    blockers.append(_block("ABILITY_SCORES_NOT_ESTABLISHED", pointer, "A Cultivation Insight ability increase requires a causal starting-score event."))
                if ability not in rule.get("allowed_abilities", []) or amount != int(rule.get("amount", 1)):
                    blockers.append(_block("CULTIVATION_INSIGHT_ABILITY_CHANGE_INVALID", pointer, "The Insight's typed ability choice is outside its published authority.", supplied={"ability": ability, "amount": amount}, authority=rule))
                if not blockers:
                    new_scores = deepcopy(state["ability_scores"])
                    new_scores[ability] += amount
                    if new_scores[ability] > int(rule.get("cap", 20)):
                        blockers.append(_block("ABILITY_SCORE_CAP_EXCEEDED", pointer, "The Cultivation Insight would exceed the published ability cap.", cap=rule.get("cap", 20), ability=ability, score=new_scores[ability]))
                    else:
                        next_state["ability_scores"] = new_scores
                        next_state["ability_modifiers"] = {a: _ability_modifier(v) for a, v in new_scores.items()}
                        hp_after, resources_after, extra_bindings, recalc_trace = self._recalculate_after_ability(
                            conn,
                            row["project_id"],
                            next_state,
                            state["ability_scores"],
                            path_id=auth.get("path_id"),
                        )
                        bindings.extend(extra_bindings)
                        calculation["inputs"] = {"prior_scores": state["ability_scores"], "ability": ability, "amount": amount, "rule": rule}
                        calculation["outputs"] = {"ability_scores": new_scores, "ability_modifiers": next_state["ability_modifiers"], "hp_after": hp_after, "resources_after": resources_after}
                        calculation["trace"] = recalc_trace
            elif "ability" in details or "amount" in details:
                blockers.append(_block("CULTIVATION_INSIGHT_ABILITY_CHANGE_UNAUTHORIZED", pointer + "/parameters", "This Insight does not publish a typed executable ability change; ability parameters are not legal."))
            if not blockers:
                calculation.setdefault("inputs", {})
                calculation["inputs"].update({
                    "repeat_index": details["repeat_index"],
                    "execution_authority": deepcopy(auth.get("execution_authority") or {}),
                })
                calculation.setdefault("outputs", {})
                calculation["outputs"].update({
                    "ability_change_applied": bool(rule),
                    "execution_authority": deepcopy(auth.get("execution_authority") or {}),
                    "insight_occurrence": {
                        "record_id": record["record_id"],
                        "event_id": event_id,
                        "acquisition_cl": cl,
                        "repeat_index": details["repeat_index"],
                        "ability": ability if rule else None,
                        "amount": amount if rule else None,
                        "content_binding": {
                            "pack_id": record["content_binding"]["pack_id"],
                            "pack_version": record["content_binding"]["pack_version"],
                            "pack_hash": record["content_binding"]["pack_hash"],
                            "record_hash": record["record_hash"],
                        },
                        "source_evidence": [_source(record)],
                        "execution_authority": deepcopy(auth.get("execution_authority") or {}),
                    },
                })
                created_records = [record["record_id"]]
        elif kind == "path_acquisition":
            if record["record_id"] in state["paths"]:
                blockers.append(_block("PATH_ALREADY_SELECTED", pointer, "A canonical Path may be acquired only once in the same initial proposal.", path_id=record["record_id"]))
            if len(state["paths"]) >= 3:
                blockers.append(_block("TOO_MANY_PATHS_SELECTED", pointer, "A character may select at most the three canonical advancing Paths.", maximum=3, selected_path_ids=state["paths"]))
            created_records = [record["record_id"]]
            calculation["outputs"] = {"path_record_id": record["record_id"], "required_milestones": deepcopy(auth.get("required_milestones", []))}
        elif kind == "level_advance":
            forbidden_authored = sorted(set(details) & {"pb", "hp_total", "hp_gain", "resources_after", "resource_formula", "trained_choice_capacity", "level_talent_capacity"})
            if forbidden_authored:
                blockers.append(_block("CALCULATION_OUTPUT_AUTHORED_OR_TAMPERED", pointer + "/parameters", "PB, HP, resource formulas/totals, and capacities are application-calculated and cannot be authored by the proposal.", fields=forbidden_authored))
            if not state["paths"]:
                blockers.append(_block("PATH_REQUIRED_FOR_LEVEL_CALCULATION", pointer, "A Path acquisition event is required before level calculation."))
            if not state["ability_scores"]:
                blockers.append(_block("ABILITY_AUTHORITY_REQUIRED_FOR_LEVEL", pointer, "A legal starting-score event is required before level calculation."))
            if not blockers:
                feature_authority = _authority(record)
                progression_path_id = feature_authority.get("path_id")
                active_path_id = progression_path_id if progression_path_id in state["paths"] else state["paths"][0]
                path = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], active_path_id)
                path_authority = _authority(path)
                progression = (path_authority.get("progression_by_cl") or {}).get(str(cl)) or {}
                automatic_feature_ids = [
                    value for value in progression.get("feature_record_ids") or []
                    if isinstance(value, str)
                ]
                if not automatic_feature_ids:
                    blockers.append(_block(
                        "PATH_PROGRESSION_ENTRY_MISSING",
                        pointer,
                        "The selected Path does not publish an exact automatic feature set for this CL.",
                        path_id=path["record_id"],
                        cl=cl,
                    ))
                if record["record_id"] not in automatic_feature_ids:
                    blockers.append(_block(
                        "PATH_PROGRESSION_FEATURE_NOT_AT_CL",
                        pointer + "/record_id",
                        "The level event representative is not one of the exact features published for this Path at this CL.",
                        path_id=path["record_id"],
                        cl=cl,
                        record_id=record["record_id"],
                        automatic_feature_record_ids=automatic_feature_ids,
                    ))
                automatic_feature_records: list[dict[str, Any]] = []
                for feature_id in automatic_feature_ids:
                    feature_record = self.projects._resolve_locked_record_after_proof(
                        conn,
                        row["project_id"],
                        feature_id,
                    )
                    if not feature_record:
                        blockers.append(_block(
                            "PATH_PROGRESSION_FEATURE_NOT_LOCKED",
                            pointer,
                            "An automatic Path feature is absent from the immutable project snapshot.",
                            path_id=path["record_id"],
                            cl=cl,
                            feature_id=feature_id,
                        ))
                        continue
                    automatic_feature_records.append(feature_record)
                pb = _pb(cl)
                hp_after, hp_bindings, hp_trace = self._hp_calculation(state, path, cl, previous_total=int(state["hp"]["total"]), pb=pb)
                resources_after, resource_bindings, resource_trace = self._resource_recalculation(conn, row["project_id"], state, cl=cl, pb=pb, path=path, current_resources=state["resources"])
                system_rule = auth
                free_capacity = int(system_rule.get("level_talent_capacity", 1))
                trained_capacity = int(system_rule.get("trained_choice_capacity", 3))
                bindings.extend(hp_bindings + resource_bindings)
                ability_record_id = state.get("ability_authority_record_id") or system_rule.get("ability_authority_record_id")
                if ability_record_id:
                    ability_record = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], ability_record_id)
                    if ability_record:
                        bindings.append(_binding(ability_record, "ability_score_authority", state.get("ability_authority_event_id")))
                calculation["formula"] = deepcopy(_authority(path).get("hp_level1_formula" if cl == 1 else "hp_later_formula"))
                calculation["inputs"] = {"cl": cl, "pb": pb, "ability_scores": state["ability_scores"], "ability_modifiers": state["ability_modifiers"], "prior_hp_total": state["hp"]["total"], "prior_resources": state["resources"], "level_talent_capacity": free_capacity, "trained_choice_capacity": trained_capacity}
                calculation["outputs"] = {
                    "pb": pb,
                    "hp_after": hp_after,
                    "resources_after": resources_after,
                    "level_talent_capacity": free_capacity,
                    "trained_choice_capacity": trained_capacity,
                    "automatic_feature_record_ids": automatic_feature_ids,
                    "automatic_feature_display_names": [
                        feature.get("display_name") for feature in automatic_feature_records
                    ],
                    "path_progression_authority": {
                        "path_id": path["record_id"],
                        "cl": cl,
                        "source": deepcopy((path_authority.get("path_index_source") or {})),
                    },
                }
                calculation["trace"] = {"hp": hp_trace, "resources": resource_trace}
                bindings.extend(
                    _binding(feature, "path_automatic_feature_authority", state["record_event_ids"].get(feature["record_id"]))
                    for feature in automatic_feature_records
                )
                updated_records = [path["record_id"]]
        elif kind in {"background_acquisition", "background_sphere_acquisition", "background_talent_acquisition", "origin_insight_acquisition", "sect_trial_sphere_acquisition", "sect_trial_talent_acquisition", "ai_bootstrap_sphere_acquisition", "ai_bootstrap_talent_acquisition", "level_talent_acquisition", "subpath_acquisition", "method_acquisition", "foundation_acquisition", "foundation_expression", "foundation_stage", "equipment_acquisition", "new_sphere_bonus_talent_acquisition", "training_source_access"}:
            if kind == "background_acquisition" and state["background"]:
                blockers.append(_block("DUPLICATE_BACKGROUND_ACQUISITION", pointer, "A Background cannot be acquired twice."))
            if kind == "background_acquisition" and not blockers:
                adjustment = auth.get("ability_adjustment")
                if adjustment:
                    if not state["ability_scores"]:
                        blockers.append(_block("ABILITY_SCORES_NOT_ESTABLISHED", pointer, "Background ability adjustment requires legal starting scores first."))
                    else:
                        ability = details.get("ability")
                        amount = details.get("amount")
                        if ability not in adjustment.get("allowed_abilities", []) or amount != int(adjustment.get("amount", 2)):
                            blockers.append(_block("BACKGROUND_ABILITY_ADJUSTMENT_INVALID", pointer, "The Background ability adjustment does not match its published bounded authority.", authority=adjustment, supplied={"ability": ability, "amount": amount}))
                        else:
                            new_scores = deepcopy(state["ability_scores"]); new_scores[ability] += amount
                            if new_scores[ability] > int(adjustment.get("cap", 20)):
                                blockers.append(_block("ABILITY_SCORE_CAP_EXCEEDED", pointer, "The Background adjustment exceeds its published ability cap."))
                            calculation["inputs"] = {"prior_scores": state["ability_scores"], "ability": ability, "amount": amount, "authority": adjustment}
                            calculation["outputs"] = {"ability_scores": new_scores, "ability_modifiers": {a: _ability_modifier(v) for a, v in new_scores.items()}}
            if kind == "background_sphere_acquisition" and state["background_sphere"]:
                blockers.append(_block("DUPLICATE_BACKGROUND_SPHERE_ACQUISITION", pointer, "A Background Sphere cannot be acquired twice."))
            if kind == "background_sphere_acquisition" and not state.get("background"):
                blockers.append(_block("BACKGROUND_REQUIRED_BEFORE_PACKAGE_SELECTION", pointer, "A Background Sphere must be selected from the previously acquired Background package."))
            if kind == "background_sphere_acquisition" and state.get("background"):
                background = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], state["background"])
                packages = _authority(background or {}).get("background_packages", [])
                if not any(isinstance(package, dict) and package.get("sphere_record_id") == record["record_id"] for package in packages):
                    blockers.append(_block("BACKGROUND_SPHERE_NOT_IN_SELECTED_PACKAGE", pointer, "The selected Sphere is not offered by the acquired Background's published package.", background_record_id=state["background"], sphere_record_id=record["record_id"], published_packages=packages))
                elif background:
                    bindings.append(_binding(background, "background_package_authority", state["record_event_ids"].get(background["record_id"])))
            if kind == "background_talent_acquisition" and state["background_talent"]:
                blockers.append(_block("DUPLICATE_BACKGROUND_TALENT_ACQUISITION", pointer, "A Background Talent cannot be acquired twice."))
            if kind == "background_talent_acquisition" and not state.get("background"):
                blockers.append(_block("BACKGROUND_REQUIRED_BEFORE_PACKAGE_SELECTION", pointer, "A Background Talent must be selected from the previously acquired Background package."))
            if kind == "background_talent_acquisition" and state.get("background"):
                background = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], state["background"])
                packages = _authority(background or {}).get("background_packages", [])
                exact_package = any(
                    isinstance(package, dict)
                    and package.get("sphere_record_id") == state.get("background_sphere")
                    and package.get("talent_record_id") == record["record_id"]
                    for package in packages
                )
                if not exact_package:
                    blockers.append(_block("BACKGROUND_TALENT_NOT_IN_SELECTED_PACKAGE", pointer, "The selected talent is not paired with the selected Background Sphere in the acquired Background's published package.", background_record_id=state["background"], background_sphere_record_id=state.get("background_sphere"), talent_record_id=record["record_id"], published_packages=packages))
                elif background:
                    bindings.append(_binding(background, "background_package_authority", state["record_event_ids"].get(background["record_id"])))
            if kind in {"background_talent_acquisition", "sect_trial_talent_acquisition", "ai_bootstrap_talent_acquisition", "level_talent_acquisition", "new_sphere_bonus_talent_acquisition"}:
                sphere_id = auth.get("sphere_id")
                if not sphere_id or sphere_id not in state["known_spheres"]:
                    blockers.append(_block("TALENT_SPHERE_NOT_KNOWN_AT_SELECTION", pointer, "The selected talent must belong to a Sphere known at the legal selection point.", talent_record_id=record["record_id"], sphere_id=sphere_id, known_spheres=state["known_spheres"]))
            if kind == "sect_trial_talent_acquisition" and choice["acquisition_channel"] != "sect-trial-cl1-level-talent":
                blockers.append(_block("SECT_TRIAL_LEVEL_TALENT_CHANNEL_INVALID", pointer, "The CL1 sect-trial talent requires its distinct level-talent channel."))
            if kind == "sect_trial_talent_acquisition":
                sphere_id = auth.get("sphere_id")
                if not state.get("sect_trial_sphere"):
                    blockers.append(_block("SECT_TRIAL_SPHERE_REQUIRED_BEFORE_TALENT", pointer, "The sect-trial level talent requires the causal sect-trial Sphere event first."))
                elif sphere_id != state["sect_trial_sphere"]:
                    blockers.append(_block("SECT_TRIAL_TALENT_WRONG_SPHERE", pointer, "The sect-trial level talent must belong to the exact Sphere gained at the sect trial.", sect_trial_sphere_record_id=state["sect_trial_sphere"], talent_sphere_record_id=sphere_id))
                else:
                    sphere = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], sphere_id)
                    if sphere:
                        bindings.append(_binding(sphere, "sect_trial_sphere_authority", state["record_event_ids"].get(sphere_id)))
            if kind == "ai_bootstrap_sphere_acquisition":
                if choice["acquisition_channel"] != "ai-bootstrap-free-cl1-sphere":
                    blockers.append(_block("AI_BOOTSTRAP_SPHERE_CHANNEL_INVALID", pointer, "The AI-bootstrap Sphere requires its explicit free CL1 channel."))
                if not self._project_uses_ai_bootstrap(project):
                    blockers.append(_block("AI_BOOTSTRAP_NON_AI_PROJECT", pointer, "AI-bootstrap acquisition is legal only for a project explicitly locked to the AI-bootstrap route."))
            if kind == "ai_bootstrap_talent_acquisition":
                if choice["acquisition_channel"] != "ai-bootstrap-free-cl1-talent":
                    blockers.append(_block("AI_BOOTSTRAP_TALENT_CHANNEL_INVALID", pointer, "The AI-bootstrap Talent requires its explicit free CL1 channel."))
                if not self._project_uses_ai_bootstrap(project):
                    blockers.append(_block("AI_BOOTSTRAP_NON_AI_PROJECT", pointer, "AI-bootstrap acquisition is legal only for a project explicitly locked to the AI-bootstrap route."))
                sphere_id = auth.get("sphere_id")
                if not state.get("ai_bootstrap_sphere"):
                    blockers.append(_block("AI_BOOTSTRAP_SPHERE_REQUIRED_BEFORE_TALENT", pointer, "The AI-bootstrap Talent requires the causal AI-bootstrap Sphere first."))
                elif sphere_id != state.get("ai_bootstrap_sphere"):
                    blockers.append(_block("AI_BOOTSTRAP_TALENT_WRONG_SPHERE", pointer, "The AI-bootstrap free Talent must belong to the exact AI-bootstrap Sphere.", ai_bootstrap_sphere_record_id=state.get("ai_bootstrap_sphere"), talent_sphere_record_id=sphere_id))
            if kind in {"ai_bootstrap_talent_acquisition", "level_talent_acquisition"} and auth.get("access_category") != "Open":
                predicate_ids = auth.get("acquisition_provenance_predicate_ids") or []
                if not predicate_ids or not self._trusted_initial_talent_selection(
                    conn, row, project, record, predicate_ids,
                ):
                    blockers.append(_block("EXACT_ACQUISITION_PROVENANCE_REQUIRED", pointer, "Restricted post-creation acquisition requires an existing exact project-bound authority record; a Talent ID cannot satisfy this requirement.", talent_record_id=record["record_id"]))
            minimum_cl = auth.get("minimum_cl")
            if isinstance(minimum_cl, int) and cl < minimum_cl:
                blockers.append(_block("CATALOG_RECORD_ACQUIRED_TOO_EARLY", pointer, "The record cannot be acquired before its exact published minimum CL.", record_id=record["record_id"], minimum_cl=minimum_cl, cl=cl))
            if kind == "subpath_acquisition":
                owner_path_id = record.get("owning_path_id")
                parent_path_id = owner_path_id
                if not isinstance(owner_path_id, str):
                    blockers.append(_block("SUBPATH_OWNER_REQUIRED", pointer, "A Subpath or Tradition requires an explicit owning_path_id in frozen authority.", subpath_id=record["record_id"]))
                if auth.get("parent_path_id") and auth.get("parent_path_id") != owner_path_id:
                    blockers.append(_block("SUBPATH_OWNER_MISMATCH", pointer, "The Subpath Stage 2 parent mirror does not match its explicit owning_path_id.", subpath_id=record["record_id"], owning_path_id=owner_path_id, parent_path_id=auth.get("parent_path_id")))
                if parent_path_id and parent_path_id not in state.get("paths", []):
                    blockers.append(_block("SUBPATH_PARENT_PATH_REQUIRED", pointer, "The selected Subpath requires its exact parent Path.", parent_path_id=parent_path_id, active_paths=state.get("paths", [])))
                if record["record_id"] in state.get("subpaths", []):
                    blockers.append(_block("SUBPATH_ALREADY_SELECTED", pointer, "A canonical Subpath or Tradition may be acquired only once.", subpath_id=record["record_id"]))
                existing_by_parent = []
                for existing_id in state.get("subpaths", []):
                    existing = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], existing_id)
                    if parent_path_id and isinstance(existing, dict) and existing.get("owning_path_id") == parent_path_id:
                        existing_by_parent.append(existing_id)
                if existing_by_parent:
                    blockers.append(_block("MULTIPLE_SUBPATHS_FOR_ONE_PATH", pointer, "Each selected Path may have only one current Subpath or Tradition.", parent_path_id=parent_path_id, existing_subpath_ids=existing_by_parent, proposed_subpath_id=record["record_id"]))
                calculation["outputs"]["granted_feature_record_ids"] = deepcopy(auth.get("granted_feature_record_ids", []))
                calculation["outputs"]["parent_path_id"] = parent_path_id
            if kind == "level_talent_acquisition" and cl < 2 and not self._project_uses_ai_bootstrap(project):
                blockers.append(_block("CL1_LEVEL_TALENT_MUST_USE_SECT_TRIAL", pointer, "Player creation receives the CL1 level talent through the sect-trial event; only the explicit AI-bootstrap route receives a separate free pair."))
            if kind == "method_acquisition" and isinstance(state["method"], dict) and state["method"].get("state") != "none":
                blockers.append(_block("METHOD_ALREADY_ACQUIRED", pointer, "A Method is already acquired."))
            if kind == "foundation_acquisition" and isinstance(state["foundation"], dict) and state["foundation"].get("state") != "none":
                blockers.append(_block("FOUNDATION_ALREADY_ACQUIRED", pointer, "A Foundation is already acquired."))
            if kind == "foundation_expression":
                f = state.get("foundation")
                if not isinstance(f, dict) or f.get("state") == "none":
                    blockers.append(_block("FOUNDATION_NOT_ACQUIRED", pointer, "A Foundation expression requires the Foundation acquisition event."))
                if auth.get("foundation_record_id") != f.get("record_id") or auth.get("path_id") not in state["paths"]:
                    blockers.append(_block("FOUNDATION_PATH_EXPRESSION_MISMATCH", pointer, "The Foundation expression does not match the acquired Foundation and active Path.", authority=auth, foundation=f, paths=state["paths"]))
                details = {**details, "foundation_record_id": auth.get("foundation_record_id"), "path_id": auth.get("path_id")}
            if kind == "foundation_stage":
                f = state.get("foundation")
                stage = details.get("stage")
                if not isinstance(f, dict) or not f.get("expression_record_id"):
                    blockers.append(_block("FOUNDATION_EXPRESSION_REQUIRED", pointer, "Foundation stage progression requires a legal Path expression."))
                stage_order = auth.get("stage_order", [])
                current_stage = f.get("stage") if isinstance(f, dict) else None
                expected_index = 0 if current_stage is None else stage_order.index(current_stage) + 1 if current_stage in stage_order else -1
                if stage not in stage_order or stage_order.index(stage) != expected_index:
                    blockers.append(_block("FOUNDATION_STAGE_PROGRESSION_INVALID", pointer, "Foundation stages must progress exactly in published order.", current_stage=current_stage, requested_stage=stage, stage_order=stage_order))
                min_cl = int(auth.get("minimum_cl_by_stage", {}).get(stage, 99))
                if cl < min_cl:
                    blockers.append(_block("FOUNDATION_STAGE_BEFORE_MINIMUM_CL", pointer, "The requested Foundation stage occurs before its published minimum CL.", stage=stage, minimum_cl=min_cl, cl=cl))
            if kind == "new_sphere_bonus_talent_acquisition":
                entitlement_id = details.get("entitlement_event_id")
                entitlement_attempt_id = details.get("entitlement_attempt_id")
                entitlement = next((x for x in state["new_sphere_entitlements"] if (entitlement_id and x["entitlement_id"] == entitlement_id) or (entitlement_attempt_id and x.get("attempt_id") == entitlement_attempt_id)), None)
                if entitlement:
                    entitlement_id = entitlement["entitlement_id"]
                    details = {**details, "entitlement_event_id": entitlement_id}
                if not entitlement or entitlement["consumed"]:
                    blockers.append(_block("NEW_SPHERE_ENTITLEMENT_MISSING_OR_CONSUMED", pointer, "The bonus talent must consume one exact unmatched new-Sphere entitlement.", entitlement_event_id=entitlement_id))
                elif int(entitlement["character_cl"]) != cl:
                    blockers.append(_block("NEW_SPHERE_BONUS_CL_MISMATCH", pointer, "A new-Sphere bonus talent must consume its entitlement during the same CL in which the Sphere was learned.", entitlement_cl=entitlement["character_cl"], bonus_talent_cl=cl, entitlement_event_id=entitlement_id))
                elif auth.get("sphere_id") != entitlement["sphere_record_id"]:
                    blockers.append(_block("NEW_SPHERE_BONUS_WRONG_SPHERE", pointer, "The bonus talent does not belong to the same newly acquired Sphere.", expected_sphere=entitlement["sphere_record_id"], talent_sphere=auth.get("sphere_id")))
            if kind == "training_source_access":
                access_mode = details.get("access_mode")
                access_authority = auth.get("training_source_access") or {}
                manual_authority = auth.get("manual") or {}
                allowed_modes = access_authority.get("access_modes")
                if allowed_modes is None:
                    allowed_modes = manual_authority.get("access_modes")
                if not isinstance(allowed_modes, list) or not allowed_modes:
                    blockers.append(_block("TRAINING_SOURCE_ACCESS_MODES_UNPUBLISHED", pointer, "The source does not publish the access modes that can create causal training access; free-form access claims fail closed.", record_id=record["record_id"]))
                elif access_mode not in allowed_modes:
                    blockers.append(_block("TRAINING_SOURCE_ACCESS_MODE_NOT_AUTHORIZED", pointer + "/parameters/access_mode", "The requested source-access mode is not published for this source.", supplied=access_mode, allowed=allowed_modes))
                if access_authority.get("mode") != "requires_access_event":
                    blockers.append(_block("TRAINING_SOURCE_ACCESS_EVENT_NOT_AUTHORIZED", pointer, "Only a source explicitly declaring requires_access_event can receive a causal access event.", source_mode=access_authority.get("mode")))
            # Derived resource recalculation on activation, stage, and equipment.
            if kind in {"foundation_stage", "equipment_acquisition"} and state["paths"] and state["current_cl"]:
                temp = _deepcopy(state)
                if kind == "foundation_stage":
                    f = temp["foundation"]
                    temp["foundation"] = {**f, "state": "active", "stage": details.get("stage"), "stage_event_id": event_id}
                else:
                    temp["equipment"].append(record["record_id"])
                    temp["record_event_ids"][record["record_id"]] = event_id
                path = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], temp["paths"][0])
                resources_after, extra_bindings, trace = self._resource_recalculation(conn, row["project_id"], temp, cl=temp["current_cl"], pb=_pb(temp["current_cl"]), path=path, current_resources=temp["resources"])
                bindings.extend(extra_bindings)
                calculation["outputs"]["resources_after"] = resources_after
                calculation["trace"]["resources"] = trace
            created_records = [record["record_id"]]
            calculation["outputs"].update({"record_id": record["record_id"]})
        elif kind == "method_activation":
            if details.get("refill_current"):
                blockers.append(_block("METHOD_CHANGE_REFILLED_CURRENT_RESOURCE", pointer + "/parameters/refill_current", "Changing or activating a Method may recalculate maximum resource but cannot silently refill current resource."))
            if auth.get("resource_modifier_required") and not auth.get("resource_modifiers"):
                blockers.append(_block("METHOD_RESOURCE_MODIFIER_AUTHORITY_MISSING", pointer, "The Method declares a resource-shape effect but lacks its typed PB modifier authority."))
            if not isinstance(state["method"], dict) or state["method"].get("record_id") != record["record_id"] or state["method"].get("state") != "acquired":
                blockers.append(_block("METHOD_ACQUISITION_REQUIRED", pointer, "Method activation requires a prior acquisition of the same Method."))
            minimum = int(auth.get("activation_min_cl", 1))
            if cl < minimum:
                blockers.append(_block("METHOD_ACTIVATED_TOO_EARLY", pointer, "Method activation occurs before the published minimum CL.", minimum_cl=minimum, cl=cl))
            if not blockers and state["paths"] and state["current_cl"]:
                temp = _deepcopy(state)
                temp["method"] = {"state": "active", "record_id": record["record_id"], "event_id": event_id}
                temp["record_event_ids"][record["record_id"]] = event_id
                path = self.projects._resolve_locked_record_after_proof(conn, row["project_id"], temp["paths"][0])
                resources_after, extra_bindings, trace = self._resource_recalculation(conn, row["project_id"], temp, cl=temp["current_cl"], pb=_pb(temp["current_cl"]), path=path, current_resources=temp["resources"])
                bindings.extend(extra_bindings)
                calculation["outputs"] = {"resources_after": resources_after}
                calculation["trace"] = trace
                updated_records = [record["record_id"]]
                event_type = "evolve"
        elif kind in {"sphere_training_attempt", "talent_training_attempt", "manual_training_attempt"}:
            if cl != state["current_cl"] or cl < 1:
                blockers.append(_block("TRAINING_BEFORE_LEVEL_ADVANCE", pointer, "Training requires the causal level-advance event for this CL."))
            blockers.extend(self._duplicate_blockers(state, record, kind, pointer))
            manual_entry = None
            manual_bindings: list[dict[str, Any]] = []
            if kind == "manual_training_attempt":
                manual_entry, manual_blockers, manual_bindings = self._manual_entry(conn, row["project_id"], record, state, pointer, cl, event_id)
                blockers.extend(manual_blockers)
            if not blockers:
                training_txn, training_blockers, source_bindings, training_outputs = self._training(conn, row["project_id"], state, record, choice, event_id, pointer)
                blockers.extend(training_blockers)
                bindings.extend(source_bindings + manual_bindings)
                if training_txn:
                    calculation["inputs"] = {"record_id": record["record_id"], "training_source_record_id": training_txn["training_source_record_id"], "training_source_access_event_id": training_txn["training_source_access_event_id"], "time_die_result": training_txn["time_die_result"], "check_die_result": training_txn["check_die_result"], "computed_check_total": training_txn["computed_check_total"], "selected_ability": training_txn["selected_ability"]}
                    calculation["outputs"] = training_outputs
                    if kind == "manual_training_attempt" and training_txn["result"] == "success":
                        calculation["outputs"]["recorded_art"] = manual_entry
                    if training_txn["result"] == "success":
                        created_records = [record["record_id"]]
                    else:
                        event_type = "author_metadata"
        elif kind == "forged_technique_creation":
            blockers.append(_block("FORGED_TECHNIQUE_COMPILATION_DEFERRED", pointer, "Phase 4A-HF1 intentionally fails closed because the full published forging compiler is not implemented. A prewritten forged record cannot masquerade as creation.", record_id=record["record_id"]))
        elif kind == "typed_none":
            target = details.get("target")
            reason_code = choice.get("reason_code") or details.get("reason_code")
            reason = choice.get("reason") or details.get("reason")
            if target not in TYPED_NONE_TARGETS or not reason_code or not reason:
                blockers.append(_block("TYPED_NONE_INVALID", pointer, "A typed none-state requires a supported target, reason code, and source-backed reason."))
            if auth.get("none_target") != target:
                blockers.append(_block("TYPED_NONE_TARGET_NOT_AUTHORIZED", pointer + "/parameters/target", "The absence authority does not authorize this exact target.", supplied=target, authorized=auth.get("none_target")))
            allowed_reason_codes = auth.get("allowed_none_reason_codes")
            if not isinstance(allowed_reason_codes, list) or reason_code not in allowed_reason_codes:
                blockers.append(_block("TYPED_NONE_REASON_NOT_AUTHORIZED", pointer + "/reason_code", "The typed absence reason code is not published by the selected authority.", supplied=reason_code, allowed=allowed_reason_codes))
            target_is_present = {
                "method": isinstance(state.get("method"), dict) and state["method"].get("state") in {"acquired", "active"},
                "foundation": isinstance(state.get("foundation"), dict) and state["foundation"].get("state") in {"acquired", "expressed", "active"},
                "manuals": bool(state.get("recorded_arts")),
                "equipment": bool(state.get("equipment")),
                "subpaths": bool(state.get("subpaths")),
                "forged_techniques": bool(state.get("event_occurrences", {}).get("forged_technique_creation")) or isinstance(state.get("forged_techniques"), list),
            }.get(target, False)
            if target_is_present:
                blockers.append(_block("TYPED_NONE_CONTRADICTS_CURRENT_STATE", pointer, "A typed absence cannot replace a causally present current-state element.", target=target))
            none_state = {"state": "none", "reason_code": reason_code, "reason": reason, "source_backed": True}
            details = {**details, "target": target}
            calculation["outputs"] = {"none_state": none_state}
            event_type = "author_metadata"
        elif kind == "printed_rule_grant":
            blockers.append(_block("PRINTED_RULE_GRANT_NOT_FULLY_TYPED", pointer, "Printed/source-rule grants require an exact published grant relation; generic free-form grants are blocked."))

        sphere_component_kinds = {
            "background_sphere_acquisition",
            "sect_trial_sphere_acquisition",
            "ai_bootstrap_sphere_acquisition",
            "sphere_training_attempt",
        }
        sphere_components_applicable = kind in sphere_component_kinds and (
            kind != "sphere_training_attempt"
            or (training_txn is not None and training_txn.get("result") == "success")
        )
        if sphere_components_applicable and not blockers:
            try:
                calculation.setdefault("outputs", {})["automatic_component_authority"] = normalize_sphere_automatic_components(record)
            except FoundryError as exc:
                blockers.append(_block(exc.code, pointer, "The locked Sphere automatic-component authority cannot be normalized.", details=exc.details))

        if blockers:
            return None, state, blockers

        if kind == "level_advance":
            roles = {b["role"] for b in bindings}
            required_roles = {"subject_authority", "path_hp_authority", "path_resource_authority", "ability_score_authority"}
            if isinstance(state.get("method"), dict) and state["method"].get("state") == "active": required_roles.add("method_delta")
            if isinstance(state.get("foundation"), dict) and state["foundation"].get("state") == "active": required_roles.add("foundation_delta")
            if state.get("equipment"): required_roles.add("equipment_resource_delta")
            missing_roles = sorted(required_roles - roles)
            if missing_roles:
                return None, state, [_block("LEVEL_CALCULATION_AUTHORITY_BINDING_MISSING", pointer + "/authority_bindings", "The level calculation omitted one or more authorities actually used by HP/resource/capacity calculation.", missing_roles=missing_roles, present_roles=sorted(roles))]

        details = _canonical_event_details(kind, details)
        subject = {"record_id": record["record_id"], "content_type": record["content_type"], "display_name": record["display_name"]}
        bind = record["content_binding"]
        last_generic_state = self.projects._reduce_events(
            generic_prefix,
            row["project_id"],
            conn,
            lock_already_proved=True,
            record_cache=record_cache,
        )
        event = {
            "schema_version": EVENT_V3,
            "event_id": event_id,
            "project_id": row["project_id"],
            "project_revision": int(row["expected_project_revision"]) + index + 1,
            "sequence": sequence,
            "event_type": event_type,
            "effective_point": {"kind": "sect_trial" if kind.startswith("sect_trial") else ("background_creation" if kind.startswith("background") or kind.startswith("ai_bootstrap") or kind in {"starting_state", "origin_insight_acquisition", "path_acquisition"} else "manual_training" if kind == "manual_training_attempt" else "level"), "character_cl": cl, "order": index + 1, "label": kind},
            "legal_channel": choice["acquisition_channel"],
            "subject": subject,
            "content_binding": {"pack_id": bind["pack_id"], "pack_version": bind["pack_version"], "pack_hash": bind["pack_hash"], "record_hash": record["record_hash"], "catalog_build_id": project["content_lock"]["catalog_build_id"]},
            "source_evidence": [_source(record)],
            "created_records": created_records,
            "updated_records": updated_records,
            "retired_records": [],
            "idempotency_key": f"{row['idempotency_key']}:{index+1}",
            "previous_event_hash": previous_hash,
            "state_before_hash": sha256_json(last_generic_state),
            "state_after_hash": ZERO_HASH,
            "event_hash": ZERO_HASH,
            "created_at": row["created_at"],
            "advancement": {"kind": kind, "target_cl": cl, "details": details, "calculation": calculation, "authority_bindings": bindings, "training_transaction": training_txn, "none_state": none_state},
        }
        # Apply event using deterministic calculated outputs, then calculate generic state hashes.
        next_state = self._apply_event(state, event)
        generic_after = self.projects._reduce_events(
            generic_prefix + [event],
            row["project_id"],
            conn,
            lock_already_proved=True,
            record_cache=record_cache,
        )
        event["state_after_hash"] = sha256_json(generic_after)
        event["event_hash"] = canonical_event_hash(event)
        try:
            self.registry.validate(event)
        except Exception as exc:
            return None, state, [_block("ADVANCEMENT_EVENT_SCHEMA_INVALID", pointer, "The deterministic HF1 event failed its canonical v3 schema.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})())]
        return event, next_state, []

    def _completion_blockers(
        self,
        state: dict[str, Any],
        target_cl: int,
        events: list[dict[str, Any]],
        project: dict[str, Any],
        *,
        record_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        current_none = state.get("typed_none_states", {})

        def causally_none(target: str) -> bool:
            value = current_none.get(target)
            return isinstance(value, dict) and value.get("state") == "none" and value.get("source_backed") is True

        def authenticated_historical_fixture() -> bool:
            """Recognize only the sealed owner-ratified historical prefix.

            The legacy single-Subpath milestone shape is a compatibility rule
            for the authenticated C2A-R.1 proof fixture, not a generic way to
            satisfy a Path-owned milestone.  The fixture marker is installed
            only by ``ProjectStore.append_owner_fixture_locks`` after its exact
            revision/event-prefix checks, so ordinary projects cannot opt into
            this fallback by copying a display name or event count.
            """
            path = self.db.settings.root_dir / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
            try:
                fixture = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return False
            seal = fixture.get("seal_sha256")
            unsigned = {key: value for key, value in fixture.items() if key != "seal_sha256"}
            if not isinstance(seal, str) or seal != sha256_json(unsigned):
                return False
            selections = fixture.get("selections") or {}
            fixture_id = fixture.get("fixture_id")
            locks = {
                lock.get("field"): lock
                for lock in project.get("user_locks") or []
                if isinstance(lock, dict) and isinstance(lock.get("field"), str)
            }
            expected = {
                "character.identity.display_name": selections.get("display_name"),
                "character.choices.qi_cultivation_skills": selections.get("qi_cultivation_skills"),
                "character.choices.street_hardened": selections.get("street_hardened"),
                "character.choices.language": selections.get("language"),
            }
            expected_source = f"owner-ratified:{fixture_id}:{sha256_file(path)}" if isinstance(fixture_id, str) else None
            prefix = fixture.get("required_prefix") or {}
            expected_revision = prefix.get("revision")
            marker_valid = (
                isinstance(expected_revision, int)
                and project.get("revision") == expected_revision + 1
            )
            for index, (field, value) in enumerate(expected.items(), start=1):
                lock = locks.get(field)
                marker_valid = marker_valid and (
                    isinstance(lock, dict)
                    and lock.get("lock_id") == f"lock.c2ar1.{index}"
                    and lock.get("created_revision") == project.get("revision")
                    and lock.get("value") == value
                    and lock.get("source") == expected_source
                )
            if not isinstance(fixture_id, str) or not marker_valid:
                return False
            count = prefix.get("event_count")
            if not isinstance(count, int) or count <= 0 or len(events) < count:
                return False
            return events[count - 1].get("event_hash") == prefix.get("event_head")

        if state["current_cl"] != target_cl or state["completed_levels"] != list(range(1, target_cl + 1)):
            blockers.append(_block("TARGET_CL_NOT_REACHED", "/target_cl", "The event stream does not contain one contiguous completed level for every CL through the target.", target_cl=target_cl, completed_levels=state["completed_levels"]))
        if len(state.get("event_occurrences", {}).get("starting_state", [])) != 1 or not state.get("ability_scores"):
            blockers.append(_block("STARTING_STATE_REQUIRED", "/final_state/ability_scores", "A complete character requires exactly one causal starting-state event with all six ability scores."))
        if not state.get("background") or not state.get("background_sphere") or not state.get("background_talent"):
            blockers.append(_block("BACKGROUND_PACKAGE_INCOMPLETE", "/final_state/background", "A complete character requires a Background and its exact causal Sphere/Talent package."))
        if not state.get("origin_insight"):
            blockers.append(_block("ORIGIN_INSIGHT_REQUIRED", "/final_state/origin_insight", "A complete character requires one causal Origin Insight."))
        path_count = len(state.get("paths", []))
        if not 1 <= path_count <= 3:
            blockers.append(_block("PATH_SELECTION_COUNT_INVALID", "/final_state/paths", "A complete character requires one to three causal advancing Paths.", minimum=1, maximum=3, actual=path_count, paths=state.get("paths", [])))
        method_state = state.get("method") if isinstance(state.get("method"), dict) else {}
        if method_state.get("state") not in {"acquired", "active"} and not causally_none("method"):
            blockers.append(_block("METHOD_RESOLUTION_REQUIRED", "/final_state/method", "A complete character requires an acquired/active Method or a current causal typed-none Method resolution."))
        foundation_state = state.get("foundation") if isinstance(state.get("foundation"), dict) else {}
        if foundation_state.get("state") not in {"acquired", "expressed", "active"} and not causally_none("foundation"):
            blockers.append(_block("FOUNDATION_RESOLUTION_REQUIRED", "/final_state/foundation", "A complete character requires a Foundation or a current causal typed-none Foundation resolution."))
        if not state.get("recorded_arts") and not causally_none("manuals"):
            blockers.append(_block("MANUALS_RESOLUTION_REQUIRED", "/final_state/recorded_arts", "A complete character requires at least one learned Recorded Art or a current causal typed-none Manuals resolution."))
        if not state.get("equipment") and not causally_none("equipment"):
            blockers.append(_block("EQUIPMENT_RESOLUTION_REQUIRED", "/final_state/equipment", "A complete character requires equipment or a current causal typed-none Equipment resolution."))
        for cl in range(1, target_cl + 1):
            selections = state["level_talents"].get(str(cl), [])
            if not selections:
                blockers.append(_block("LEVEL_TALENT_MISSING", f"/levels/{cl}/level_talent", "Every completed CL requires exactly one causal level-talent acquisition."))
            elif len(selections) != 1:
                blockers.append(_block("LEVEL_TALENT_COUNT_INVALID", f"/levels/{cl}/level_talent", "A completed CL has more than one level-talent acquisition.", count=len(selections), selections=selections))
        if target_cl >= 1:
            sect_spheres = [e for e in events if e["advancement"]["kind"] == "sect_trial_sphere_acquisition"]
            sect_talents = [e for e in events if e["advancement"]["kind"] == "sect_trial_talent_acquisition"]
            ai_spheres = [e for e in events if e["advancement"]["kind"] == "ai_bootstrap_sphere_acquisition"]
            ai_talents = [e for e in events if e["advancement"]["kind"] == "ai_bootstrap_talent_acquisition"]
            # Creation can contain more than one exact Sphere/free-Talent pair.
            # Each pair remains represented by two causal typed events; counts
            # must match and the two creation routes remain mutually exclusive.
            sect_valid = len(sect_spheres) >= 1 and len(sect_spheres) == len(sect_talents)
            ai_valid = (
                len(ai_spheres) >= 1
                and len(ai_spheres) == len(ai_talents)
                and self._project_uses_ai_bootstrap(project)
            )
            if sect_valid == ai_valid:
                blockers.append(_block("CREATION_ROUTE_COUNT_INVALID", "/levels/1/creation_route", "Exactly one complete initial-creation route is required, with one exact free Talent event paired to every acquired Sphere event.", sect_trial_counts={"sphere": len(sect_spheres), "talent": len(sect_talents)}, ai_bootstrap_counts={"sphere": len(ai_spheres), "talent": len(ai_talents)}, project_ai_bootstrap=self._project_uses_ai_bootstrap(project)))
        subpath_parent_ids: list[str] = []
        for event in events:
            if (event.get("advancement") or {}).get("kind") != "subpath_acquisition":
                continue
            outputs = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
            parent_path_id = outputs.get("parent_path_id")
            record_id = (event.get("subject") or {}).get("record_id")
            if not isinstance(parent_path_id, str):
                snapshot = (state.get("authority_snapshots") or {}).get(record_id) or {}
                if not snapshot and isinstance(record_cache, dict):
                    snapshot = {"record": record_cache.get(record_id)}
                snapshot_record = snapshot.get("record") or {}
                parent_path_id = snapshot_record.get("owning_path_id")
            if isinstance(parent_path_id, str):
                subpath_parent_ids.append(parent_path_id)
        path_aware_subpath_milestones = bool(subpath_parent_ids)
        historical_fixture = authenticated_historical_fixture()

        for index, milestone in enumerate(state.get("required_milestones", [])):
            pointer = f"/required_milestones/{index}"
            if not isinstance(milestone, dict):
                blockers.append(_block("PATH_MILESTONE_AUTHORITY_INVALID", pointer, "A Path milestone must be a typed object."))
                continue
            milestone_cl = milestone.get("cl")
            allowed_kinds = milestone.get("allowed_kinds")
            required_count = milestone.get("count")
            if not isinstance(milestone_cl, int) or not isinstance(allowed_kinds, list) or not allowed_kinds or not isinstance(required_count, int) or required_count < 0:
                blockers.append(_block("PATH_MILESTONE_AUTHORITY_INVALID", pointer, "A Path milestone must publish CL, non-empty allowed event kinds, and a non-negative exact count.", milestone=milestone))
                continue
            if milestone_cl > target_cl:
                continue
            milestone_path_id = milestone.get("path_id")
            progression_path_by_cl: dict[int, str] = {}
            for event in events:
                advancement = event.get("advancement") or {}
                if advancement.get("kind") != "level_advance":
                    continue
                event_cl = advancement.get("target_cl")
                outputs = ((advancement.get("calculation") or {}).get("outputs") or {})
                event_path_id = ((outputs.get("path_progression_authority") or {}).get("path_id"))
                if not isinstance(event_path_id, str):
                    record_id = (event.get("subject") or {}).get("record_id")
                    event_path_id = record_id.split(".feature.", 1)[0] if isinstance(record_id, str) and ".feature." in record_id else None
                if isinstance(event_cl, int) and isinstance(event_path_id, str):
                    progression_path_by_cl[event_cl] = event_path_id
            # A selected Path can be active while only one Path progression is
            # advanced at a given CL.  Advancement-choice milestones therefore
            # apply to the Path actually advanced at that CL; Subpath milestones
            # remain independently Path-owned so two selected Paths can each
            # receive their one exact Subpath at the same legal CL.
            if (
                milestone.get("feature_kind") == "advancement_choice"
                and isinstance(milestone_path_id, str)
                and progression_path_by_cl.get(milestone_cl) not in {None, milestone_path_id}
            ):
                continue

            def matches_milestone_path(event: dict[str, Any]) -> bool:
                if not isinstance(milestone_path_id, str):
                    return True
                if (
                    milestone.get("feature_kind") == "subpath_selection"
                    and not path_aware_subpath_milestones
                ):
                    # This is the sole historical compatibility exception. A
                    # generic project with incomplete owner data must remain
                    # blocked rather than borrowing a global Subpath event.
                    return historical_fixture
                advancement = event.get("advancement") or {}
                outputs = ((advancement.get("calculation") or {}).get("outputs") or {})
                record_id = (event.get("subject") or {}).get("record_id")
                snapshot = (state.get("authority_snapshots") or {}).get(record_id) or {}
                if not snapshot and isinstance(record_cache, dict):
                    snapshot = {"record": record_cache.get(record_id)}
                snapshot_record = snapshot.get("record") or {}
                if milestone.get("feature_kind") == "subpath_selection":
                    # Subpath ownership is authoritative only in the locked
                    # record's explicit owning_path_id. Event outputs and the
                    # Stage 2 parent mirror may confirm it but may not supply
                    # one when the explicit field is absent.
                    event_path_id = snapshot_record.get("owning_path_id")
                    output_parent = outputs.get("parent_path_id")
                    if not isinstance(event_path_id, str):
                        return False
                    if output_parent is not None and output_parent != event_path_id:
                        return False
                else:
                    event_path_id = outputs.get("parent_path_id")
                    if not isinstance(event_path_id, str):
                        event_path_id = ((outputs.get("path_progression_authority") or {}).get("path_id"))
                    if not isinstance(event_path_id, str) and isinstance(record_id, str) and ".feature." in record_id:
                        event_path_id = record_id.split(".feature.", 1)[0]
                    event_path_id = event_path_id or snapshot_record.get("owning_path_id")
                if event_path_id is None and milestone.get("feature_kind") == "advancement_choice":
                    # Insight event rows intentionally carry only the Insight
                    # identity; the milestone/path binding was already fixed
                    # by the server's progression route and the non-progressed
                    # same-CL milestone was skipped above.
                    return True
                return event_path_id == milestone_path_id

            matching = [
                e for e in events
                if int(e["advancement"]["target_cl"]) == milestone_cl
                and e["advancement"]["kind"] in allowed_kinds
                and matches_milestone_path(e)
            ]
            if len(matching) != required_count:
                code = "REQUIRED_PATH_MILESTONE_MISSING" if len(matching) < required_count else "REQUIRED_PATH_MILESTONE_COUNT_INVALID"
                blockers.append(_block(
                    code,
                    f"/levels/{milestone_cl}/milestones/{milestone.get('milestone_id', index)}",
                    "The event stream does not satisfy the Path's exact published advancement milestone.",
                    milestone=milestone,
                    actual_count=len(matching),
                    matching_event_ids=[e["event_id"] for e in matching],
                ))
        for cl in range(1, target_cl + 1):
            used = int(state["trained_success_cost"].get(str(cl), 0))
            level_event = next((e for e in events if e["advancement"]["kind"] == "level_advance" and e["advancement"]["target_cl"] == cl), None)
            cap = int(level_event["advancement"]["calculation"]["outputs"].get("trained_choice_capacity", 3)) if level_event else 3
            if used > cap:
                blockers.append(_block("TRAINED_CHOICE_CAPACITY_EXCEEDED", f"/levels/{cl}/training", "Successful trained-choice costs exceed the published capacity.", used=used, capacity=cap))
        for ent in state["new_sphere_entitlements"]:
            if not ent["consumed"]:
                blockers.append(_block("NEW_SPHERE_BONUS_MISSING", f"/events/{ent['sphere_event_id']}", "A successful new-Sphere training event has an unmatched same-Sphere bonus-talent entitlement.", entitlement=ent))
        forged_none_events = [
            e for e in events
            if e["advancement"]["kind"] == "typed_none"
            and e["advancement"]["details"].get("target") == "forged_techniques"
        ]
        if not (causally_none("forged_techniques") and isinstance(state["forged_techniques"], dict) and state["forged_techniques"].get("state") == "none" and forged_none_events):
            blockers.append(_block("FORGED_TECHNIQUE_TYPED_NONE_EVENT_REQUIRED", "/final_state/forged_techniques", "HF1 requires one explicit causal typed-none event until the full forging compiler exists."))
        return blockers

    def _proposal_integrity(self, conn, row) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        mismatches: dict[str, Any] = {}
        try:
            proposal = json.loads(row["proposal_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise FoundryError(
                "STAGE2_PROPOSAL_INTEGRITY_MISMATCH",
                "The persisted proposal document cannot be parsed.",
                details={"proposal_json": "invalid_json"},
            ) from exc
        canonical_proposal = canonical_json(proposal)
        if canonical_proposal != row["proposal_json"]:
            mismatches["proposal_json"] = "noncanonical"
        actual_proposal_hash = sha256_json(proposal)
        if row["proposal_hash"] != actual_proposal_hash:
            mismatches["proposal_hash"] = {"stored": row["proposal_hash"], "actual": actual_proposal_hash}
        scalar_fields = {
            "project_id": row["project_id"],
            "idempotency_key": row["idempotency_key"],
            "expected_project_revision": row["expected_project_revision"],
            "expected_content_lock_hash": row["expected_content_lock_hash"],
            "target_cl": row["target_cl"],
        }
        for field, stored in scalar_fields.items():
            if proposal.get(field) != stored:
                mismatches.setdefault("proposal_columns", {})[field] = {"document": proposal.get(field), "column": stored}
        children = conn.execute(
            """SELECT ordinal,event_request_json,event_request_hash
               FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal""",
            (row["proposal_id"],),
        ).fetchall()
        expected_ordinals = list(range(len(children)))
        actual_ordinals = [int(child["ordinal"]) for child in children]
        if actual_ordinals != expected_ordinals:
            mismatches["child_ordinals"] = {"expected": expected_ordinals, "actual": actual_ordinals}
        parsed_children: list[dict[str, Any]] = []
        child_hashes: list[str] = []
        child_issues: list[dict[str, Any]] = []
        for child in children:
            ordinal = int(child["ordinal"])
            try:
                value = json.loads(child["event_request_json"])
            except (TypeError, json.JSONDecodeError):
                child_issues.append({"ordinal": ordinal, "issue": "invalid_json"})
                continue
            actual_hash = sha256_json(value)
            issue: dict[str, Any] = {"ordinal": ordinal}
            if canonical_json(value) != child["event_request_json"]:
                issue["canonical"] = False
            if actual_hash != child["event_request_hash"]:
                issue["hash"] = {"stored": child["event_request_hash"], "actual": actual_hash}
            if len(issue) > 1:
                child_issues.append(issue)
            parsed_children.append(value)
            child_hashes.append(actual_hash)
        expected_choices = proposal.get("choices")
        if not isinstance(expected_choices, list) or parsed_children != expected_choices:
            mismatches["child_json"] = {
                "proposal_choices_hash": sha256_json(expected_choices) if isinstance(expected_choices, list) else None,
                "persisted_children_hash": sha256_json(parsed_children),
                "proposal_choice_count": len(expected_choices) if isinstance(expected_choices, list) else None,
                "persisted_child_count": len(parsed_children),
            }
        if child_issues:
            mismatches["child_hashes"] = child_issues
        if mismatches:
            raise FoundryError(
                "STAGE2_PROPOSAL_INTEGRITY_MISMATCH",
                "The proposal document, ordered child rows, hashes, or scalar bindings diverge.",
                details=mismatches,
            )
        return proposal, parsed_children, child_hashes

    @staticmethod
    def _validation_hash(validation: dict[str, Any]) -> str:
        stable = {key: value for key, value in validation.items() if key not in {"validated_at", "validation_hash"}}
        return sha256_json(stable)

    @staticmethod
    def _approval_binding(validation: dict[str, Any]) -> dict[str, Any]:
        return {
            "proposal_hash": validation["proposal_hash"],
            "validation_hash": validation["validation_hash"],
            "child_hashes": validation["child_hashes"],
            "compiled_event_hashes": validation["compiled_event_hashes"],
            "project_lock_proof_hash": validation["project_lock_proof_hash"],
        }

    @staticmethod
    def _approval_evidence_context(validation: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "TianxiaFoundry.Stage2ApprovalContext.v1",
            "proposal_hash": validation["proposal_hash"],
            "validation_hash": validation["validation_hash"],
            "ordered_child_hashes": validation["child_hashes"],
            "compiled_event_hashes": validation["compiled_event_hashes"],
            "project_lock_proof_hash": validation["project_lock_proof_hash"],
            "mechanical_state_hash": validation["mechanical_state_hash"],
        }

    def _assert_approved_binding(self, row, validation: dict[str, Any], conn=None) -> dict[str, Any]:
        required_columns = {
            "approved_proposal_hash": row["approved_proposal_hash"],
            "approved_validation_hash": row["approved_validation_hash"],
            "approved_child_hashes_json": row["approved_child_hashes_json"],
            "approved_compiled_event_hashes_json": row["approved_compiled_event_hashes_json"],
            "approved_lock_proof_hash": row["approved_lock_proof_hash"],
            "approved_principal_id": row["approved_principal_id"],
            "approval_challenge_id": row["approval_challenge_id"],
            "approval_evidence_id": row["approval_evidence_id"],
        }
        if not all(required_columns.values()):
            raise FoundryError(
                "STAGE2_LEGACY_APPROVAL_BINDING_UNPROVEN",
                "The approved proposal lacks one or more exact R4 approval bindings and cannot be committed.",
                details={"proposal_id": row["proposal_id"], "missing": sorted(k for k, v in required_columns.items() if not v)},
                status_code=409,
            )
        expected = self._approval_binding(validation)
        actual = {
            "proposal_hash": row["approved_proposal_hash"],
            "validation_hash": row["approved_validation_hash"],
            "child_hashes": json.loads(row["approved_child_hashes_json"]),
            "compiled_event_hashes": json.loads(row["approved_compiled_event_hashes_json"]),
            "project_lock_proof_hash": row["approved_lock_proof_hash"],
        }
        if actual != expected:
            raise FoundryError(
                "STAGE2_APPROVAL_BINDING_MISMATCH",
                "Recomputed proposal, validation, child, compiled-event, or project-lock evidence differs from the approved bytes.",
                details={"proposal_id": row["proposal_id"], "approved": actual, "recomputed": expected},
                status_code=409,
            )
        if conn is None:
            raise FoundryError("STAGE2_APPROVAL_VERIFICATION_CONNECTION_REQUIRED", "R4 approval verification requires the active database transaction.", status_code=500)
        exact, binding, lock_hash = self._approval_challenge_material(conn, row, validation)
        evidence = self.challenges.verify_evidence(
            conn,
            row["approval_evidence_id"],
            operation="stage2_approve",
            subject_type="stage2_proposal",
            subject_id=row["proposal_id"],
            exact_bytes=exact,
            binding=binding,
            project_lock_hash=lock_hash,
            principal_id=row["approved_principal_id"],
            evidence_context=self._approval_evidence_context(validation),
        )
        if evidence["challenge"]["challenge_id"] != row["approval_challenge_id"]:
            raise FoundryError("STAGE2_APPROVAL_EVIDENCE_MISMATCH", "The keyed approval evidence does not match the proposal challenge ID.", status_code=409)
        return evidence

    def compile_proposal(self, conn, row) -> dict[str, Any]:
        proposal, choices, child_hashes = self._proposal_integrity(conn, row)
        lock_proof = self.projects.project_lock_proof(conn, row["project_id"])
        project_row, project = self._project_row(conn, row["project_id"])
        blockers: list[dict[str, Any]] = []
        if project_row["revision"] != row["expected_project_revision"]:
            blockers.append(_block("STALE_PROJECT_REVISION", "/expected_project_revision", "The project revision changed after proposal creation.", expected=row["expected_project_revision"], actual=project_row["revision"]))
        if project["content_lock"]["lock_hash"] != row["expected_content_lock_hash"]:
            blockers.append(_block("STALE_CONTENT_LOCK", "/expected_content_lock_hash", "The project content lock changed after proposal creation."))
        existing_v3 = self._v3_events(conn, row["project_id"])
        existing_v2 = [e for e in self._all_events(conn, row["project_id"]) if e.get("schema_version") == "TianxiaFoundry.AdvancementEvent.v2"]
        if existing_v2 and not existing_v3:
            blockers.append(_block("LEGACY_STAGE2_STREAM_REQUIRES_EXPLICIT_MIGRATION", "/events", "A legacy Stage 2 v2 stream cannot be silently mixed with HF1 v3 events."))
        state = self._mechanical_state(existing_v3, row["project_id"])
        generic_prefix = self._all_events(conn, row["project_id"])
        last = conn.execute("SELECT sequence_no,event_hash FROM events WHERE project_id=? ORDER BY sequence_no DESC LIMIT 1", (row["project_id"],)).fetchone()
        sequence = int(last[0]) + 1 if last else 1
        previous = last[1] if last else ZERO_HASH
        compiled: list[dict[str, Any]] = []
        record_cache: dict[str, dict[str, Any] | None] = {}
        for index, choice in enumerate(choices):
            event, next_state, issues = self._choice_event(
                conn=conn,
                row=row,
                project=project,
                state=state,
                choice=choice,
                index=index,
                sequence=sequence + index,
                previous_hash=previous,
                generic_prefix=generic_prefix,
                record_cache=record_cache,
            )
            blockers.extend(issues)
            if event:
                compiled.append(event)
                state = next_state
                generic_prefix.append(event)
                previous = event["event_hash"]
        blockers.extend(
            self._completion_blockers(
                state,
                int(row["target_cl"]),
                existing_v3 + compiled,
                project,
                record_cache=record_cache,
            )
        )
        report = {"schema_version": "TianxiaFoundry.Stage2BlockerReport.v1", "project_id": row["project_id"], "project_revision": project_row["revision"], "blocked": bool(blockers), "blockers": blockers}
        self.registry.validate(report)
        validation = {
            "valid": not blockers,
            "blocker_report": report,
            "compiled_events": compiled,
            "mechanical_state": state,
            "mechanical_state_hash": sha256_json(state),
            "proposal_hash": sha256_json(proposal),
            "child_hashes": child_hashes,
            "compiled_event_hashes": [event["event_hash"] for event in compiled],
            "project_lock_proof_hash": lock_proof["lock_proof_hash"],
            "validated_at": utcnow(),
        }
        validation["validation_hash"] = self._validation_hash(validation)
        return validation

    def validate_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._proposal_row(conn, proposal_id)
            validation = self.compile_proposal(conn, row)
            status = "validated" if validation["valid"] else "blocked"
            conn.execute("UPDATE stage2_proposals SET status=?,validation_json=?,updated_at=? WHERE proposal_id=?", (status, canonical_json(validation), utcnow(), proposal_id))
            conn.execute("DELETE FROM stage2_blockers WHERE proposal_id=?", (proposal_id,))
            for b in validation["blocker_report"]["blockers"]:
                conn.execute("INSERT INTO stage2_blockers(blocker_id,project_id,project_revision,proposal_id,blocker_code,severity,pointer,message,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), row["project_id"], row["expected_project_revision"], proposal_id, b["code"], b["severity"], b["pointer"], b["message"], canonical_json(b["details"]), utcnow()))
            return {"proposal_id": proposal_id, "status": status, **validation}

    def _approval_challenge_material(self, conn, row, validation: dict[str, Any] | None = None) -> tuple[bytes, dict[str, Any], str]:
        if not row["validation_json"]:
            raise FoundryError("STAGE2_VALIDATION_BINDING_MISSING", "The validated proposal has no persisted validation evidence.")
        stored = json.loads(row["validation_json"])
        if stored.get("validation_hash") != self._validation_hash(stored):
            raise FoundryError("STAGE2_VALIDATION_INTEGRITY_MISMATCH", "The persisted validation evidence does not match its deterministic hash.")
        validation = validation or self.compile_proposal(conn, row)
        if not validation["valid"]:
            raise FoundryError("STAGE2_PROPOSAL_REVALIDATION_FAILED", "The proposal became blocked before approval.", details=validation["blocker_report"])
        if self._approval_binding(stored) != self._approval_binding(validation):
            raise FoundryError("STAGE2_VALIDATION_RECOMPUTATION_MISMATCH", "Recomputed validation evidence differs from the exact validated proposal bytes.")
        children = [dict(r) for r in conn.execute(
            "SELECT ordinal,event_request_json,event_request_hash FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal",
            (row["proposal_id"],),
        )]
        exact = canonical_json({
            "proposal_json": row["proposal_json"],
            "validation_json": row["validation_json"],
            "ordered_children": children,
            "approval_binding": self._approval_binding(validation),
        }).encode("utf-8")
        binding = self._approval_binding(validation)
        return exact, binding, validation["project_lock_proof_hash"]

    def issue_approval_challenge(self, proposal_id: str, *, ttl_seconds: int = 300) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = self._proposal_row(conn, proposal_id)
            if row["status"] != "validated":
                raise FoundryError("STAGE2_PROPOSAL_NOT_VALIDATED", "Only a valid unblocked proposal may receive an approval challenge.", details={"status": row["status"]})
            exact, binding, lock_hash = self._approval_challenge_material(conn, row)
        return self.challenges.issue(operation="stage2_approve", subject_type="stage2_proposal", subject_id=proposal_id,
                                     exact_bytes=exact, binding=binding, project_lock_hash=lock_hash, ttl_seconds=ttl_seconds)

    def approve_proposal(self, proposal_id: str, approved_by: str | None = None, *, challenge_id: str | None = None, nonce: str | None = None) -> dict[str, Any]:
        # Legacy actor text is presentation-only and can never select authority.
        if approved_by is not None and str(approved_by).strip():
            reject_reserved_identity(str(approved_by), field_name="Stage 2 approval display actor")
        if not challenge_id or not nonce:
            raise FoundryError(
                "APPROVAL_CHALLENGE_REQUIRED",
                "Stage 2 approval requires an explicitly issued one-time exact-byte challenge.",
                status_code=409,
            )
        principal = self.principal_provider.current_principal()
        with self.db.connection() as conn:
            initial = self._proposal_row(conn, proposal_id)
            if initial["status"] != "validated":
                raise FoundryError("STAGE2_PROPOSAL_NOT_VALIDATED", "Only a valid unblocked proposal may be approved.", details={"status": initial["status"]})
            initial_validation = self.compile_proposal(conn, initial)
            exact, binding, lock_hash = self._approval_challenge_material(conn, initial, initial_validation)
            evidence_context = self._approval_evidence_context(initial_validation)

        def protected_approval(conn, evidence):
            row = self._proposal_row(conn, proposal_id)
            if row["status"] != "validated":
                raise FoundryError("STAGE2_PROPOSAL_NOT_VALIDATED", "Only a valid unblocked proposal may be approved.", details={"status": row["status"]})
            validation = self.compile_proposal(conn, row)
            current_exact, current_binding, current_lock = self._approval_challenge_material(conn, row, validation)
            if current_exact != exact or current_binding != binding or current_lock != lock_hash or self._approval_evidence_context(validation) != evidence_context:
                raise FoundryError("STAGE2_APPROVAL_MATERIAL_CHANGED", "The exact approval material changed before atomic challenge consumption.", status_code=409)
            now = utcnow()
            conn.execute(
                """UPDATE stage2_proposals SET
                   status='approved',approved_by=?,approved_at=?,
                   approved_proposal_hash=?,approved_validation_hash=?,approved_child_hashes_json=?,
                   approved_compiled_event_hashes_json=?,approved_lock_proof_hash=?,approved_principal_id=?,
                   approval_challenge_id=?,approval_evidence_id=?,updated_at=? WHERE proposal_id=?""",
                (principal.display_name, now, validation["proposal_hash"], validation["validation_hash"],
                 canonical_json(validation["child_hashes"]), canonical_json(validation["compiled_event_hashes"]),
                 validation["project_lock_proof_hash"], principal.principal_id, challenge_id, evidence["evidence_id"], now, proposal_id),
            )
            return self._proposal_result(conn, proposal_id)

        _evidence, result = self.challenges.consume_with_action(
            challenge_id=challenge_id,
            nonce=nonce,
            operation="stage2_approve",
            subject_type="stage2_proposal",
            subject_id=proposal_id,
            exact_bytes=exact,
            binding=binding,
            project_lock_hash=lock_hash,
            evidence_context=evidence_context,
            action=protected_approval,
        )
        assert result is not None
        return result

    def _update_project_after_batch(self, conn, project_id: str, replay: dict[str, Any], event_ids: list[str], state_hash: str, proposal_id: str, final_revision: int) -> dict[str, Any]:
        row, old = self._project_row(conn, project_id)
        commits = list(old.get("stage_commits") or [])
        commits.append({"stage": 2, "revision": final_revision, "status": "sealed", "state_hash": state_hash, "prompt_packet_ids": [], "response_ids": [proposal_id], "event_ids": event_ids})
        updated = canonical_project_document(project_id=project_id, name=old["name"], revision=final_revision, status="stage_2", created_at=old["created_at"], updated_at=utcnow(), catalog_build_id=old["content_lock"]["catalog_build_id"], pack_locks=self.projects._project_locks(conn, project_id), user_locks=old["user_locks"], source_inputs=old["source_inputs"], event_count=replay["event_count"], head_hash=replay["latest_event_hash"], active_stage=2, stage_commits=commits, generated_artifacts=old["generated_artifacts"], candidates=old["candidates"], acceptance=old["acceptance"])
        self.registry.validate(updated)
        conn.execute("UPDATE projects SET status=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?", (updated["status"], final_revision, updated["updated_at"], canonical_json(updated), canonical_project_hash(updated), updated["schema_version"], project_id))
        return updated

    @staticmethod
    def _principal_binding_hash(principal_id: str) -> str:
        return sha256_json({"principal_id": principal_id})

    @classmethod
    def _attempt_binding_set(cls, row) -> dict[str, Any]:
        principal_id = row["approved_principal_id"]
        return {
            "approved_proposal_hash": row["approved_proposal_hash"],
            "approved_validation_hash": row["approved_validation_hash"],
            "approved_child_hashes": json.loads(row["approved_child_hashes_json"]),
            "approved_compiled_event_hashes": json.loads(row["approved_compiled_event_hashes_json"]),
            "approved_lock_proof_hash": row["approved_lock_proof_hash"],
            "approved_principal_id": principal_id,
            "approved_principal_hash": cls._principal_binding_hash(principal_id),
            "approval_evidence_id": row["approval_evidence_id"],
        }

    @classmethod
    def _attempt_binding_hash(cls, row) -> str:
        return sha256_json(cls._attempt_binding_set(row))

    def _terminal_projection(
        self,
        conn,
        *,
        commit_id: str,
        row,
        attempt: dict[str, Any],
        validation: dict[str, Any],
        events: list[dict[str, Any]],
        replay: dict[str, Any],
        final_revision: int,
        completed_at: str,
    ) -> dict[str, Any]:
        evidence_row = conn.execute(
            "SELECT approval_projection_hash,integrity_key_id,integrity_domain,integrity_mac FROM exact_approval_evidence WHERE evidence_id=?",
            (row["approval_evidence_id"],),
        ).fetchone()
        if not evidence_row:
            raise FoundryError("STAGE2_APPROVAL_EVIDENCE_MISSING", "The terminal receipt cannot be created without keyed approval evidence.", status_code=409)
        return {
            "schema_version": "TianxiaFoundry.Stage2TerminalCommitReceipt.v2",
            "commit_id": commit_id,
            "proposal_id": row["proposal_id"],
            "project_id": row["project_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_no": attempt["attempt_no"],
            "binding_set": attempt["binding_set"],
            "binding_set_hash": attempt["binding_set_hash"],
            "approval_evidence": {
                "evidence_id": row["approval_evidence_id"],
                "projection_hash": evidence_row["approval_projection_hash"],
                "key_id": evidence_row["integrity_key_id"],
                "domain": evidence_row["integrity_domain"],
                "mac": evidence_row["integrity_mac"],
            },
            "base_revision": attempt["base_revision"],
            "final_revision": final_revision,
            "ordered_events": [{"event_id": event["event_id"], "event_hash": event["event_hash"]} for event in events],
            "event_chain_head": replay["latest_event_hash"],
            "event_count": replay["event_count"],
            "state_before_hash": attempt["state_before_hash"],
            "state_after_hash": replay["state_hash"],
            "terminal_mechanical_state_hash": validation["mechanical_state_hash"],
            "approved_principal_id": row["approved_principal_id"],
            "completed_at": completed_at,
        }

    def _verify_terminal_receipt(self, conn, receipt_row) -> dict[str, Any]:
        receipt = dict(receipt_row)
        required = [
            "approval_evidence_id", "terminal_projection_json", "terminal_projection_hash",
            "terminal_mechanical_state_hash", "integrity_version", "integrity_key_id",
            "integrity_domain", "integrity_mac",
        ]
        missing = [field for field in required if not receipt.get(field) or str(receipt.get(field)).startswith("LEGACY_")]
        if missing:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_LEGACY_UNPROVEN",
                "The committed result lacks an R4 external keyed terminal receipt.",
                details={"commit_id": receipt.get("commit_id"), "missing": missing}, status_code=409,
            )
        try:
            projection = json.loads(receipt["terminal_projection_json"])
        except Exception as exc:
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_CORRUPT", "The terminal receipt projection is malformed.", details={"error": type(exc).__name__}, status_code=409) from exc
        if canonical_json(projection) != receipt["terminal_projection_json"] or sha256_json(projection) != receipt["terminal_projection_hash"]:
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_CORRUPT", "The terminal receipt canonical bytes or projection hash are invalid.", status_code=409)
        envelope = {
            "integrity_version": receipt["integrity_version"], "algorithm": "HMAC-SHA-256",
            "key_id": receipt["integrity_key_id"], "domain": receipt["integrity_domain"],
            "projection_hash": receipt["terminal_projection_hash"], "mac": receipt["integrity_mac"],
        }
        self.integrity.verify(TERMINAL_RECEIPT_DOMAIN, projection, envelope)
        scalar = {
            "commit_id": receipt["commit_id"], "proposal_id": receipt["proposal_id"], "project_id": receipt["project_id"],
            "attempt_id": receipt["terminal_attempt_id"], "base_revision": receipt["base_revision"],
            "final_revision": receipt["final_revision"], "state_before_hash": receipt["state_before_hash"],
            "state_after_hash": receipt["state_after_hash"], "terminal_mechanical_state_hash": receipt["terminal_mechanical_state_hash"],
            "approved_principal_id": receipt["approved_principal_id"], "approval_evidence_id": receipt["approval_evidence_id"],
        }
        projection_scalar = {
            "commit_id": projection.get("commit_id"), "proposal_id": projection.get("proposal_id"), "project_id": projection.get("project_id"),
            "attempt_id": projection.get("attempt_id"), "base_revision": projection.get("base_revision"),
            "final_revision": projection.get("final_revision"), "state_before_hash": projection.get("state_before_hash"),
            "state_after_hash": projection.get("state_after_hash"), "terminal_mechanical_state_hash": projection.get("terminal_mechanical_state_hash"),
            "approved_principal_id": projection.get("approved_principal_id"),
            "approval_evidence_id": (projection.get("approval_evidence") or {}).get("evidence_id"),
        }
        if scalar != projection_scalar:
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_CORRUPT", "Terminal receipt columns differ from the keyed projection.", details={"stored": scalar, "projection": projection_scalar}, status_code=409)
        extra_scalar = {
            "binding_set_hash": receipt["binding_set_hash"],
            "event_chain_head": projection.get("event_chain_head"),
            "event_count": projection.get("event_count"),
            "completed_at": receipt["completed_at"],
        }
        if projection.get("binding_set_hash") != receipt["binding_set_hash"] or projection.get("completed_at") != receipt["completed_at"]:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_CORRUPT",
                "The terminal binding-set or completion fields differ from the keyed projection.",
                details=extra_scalar, status_code=409,
            )
        proposal = self._proposal_row(conn, receipt["proposal_id"])
        stored_validation = json.loads(proposal["validation_json"] or "{}")
        evidence = self._assert_approved_binding(proposal, stored_validation, conn)
        approval_projection = projection.get("approval_evidence") or {}
        if approval_projection.get("evidence_id") != evidence["evidence_id"] or approval_projection.get("projection_hash") != evidence["approval_projection_hash"] or approval_projection.get("mac") != evidence["mac"]:
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_APPROVAL_MISMATCH", "The terminal receipt is not bound to the exact keyed approval evidence.", status_code=409)
        attempt_row = conn.execute("SELECT * FROM stage2_commit_attempts WHERE attempt_id=?", (receipt["terminal_attempt_id"],)).fetchone()
        if not attempt_row or attempt_row["status"] != "committed" or attempt_row["proposal_id"] != receipt["proposal_id"] or attempt_row["binding_set_hash"] != receipt["binding_set_hash"] or attempt_row["approval_evidence_id"] != receipt["approval_evidence_id"]:
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_ATTEMPT_MISMATCH", "The terminal receipt is not backed by the exact committed attempt.", status_code=409)
        attempt_binding = self._attempt_binding_set(attempt_row)
        if (
            projection.get("attempt_no") != attempt_row["attempt_no"]
            or projection.get("binding_set") != attempt_binding
            or projection.get("binding_set_hash") != sha256_json(attempt_binding)
            or projection.get("state_before_hash") != attempt_row["state_before_hash"]
        ):
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_ATTEMPT_MISMATCH",
                "The keyed terminal projection differs from the exact committed attempt binding.",
                status_code=409,
            )
        ordered = projection.get("ordered_events") or []
        ids = [item.get("event_id") for item in ordered]
        hashes = [item.get("event_hash") for item in ordered]
        if ids != json.loads(receipt["event_ids_json"]) or hashes != json.loads(receipt["event_hashes_json"]):
            raise FoundryError("STAGE2_TERMINAL_RECEIPT_EVENT_SET_MISMATCH", "The terminal receipt event set differs from its keyed projection.", status_code=409)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            event_rows = conn.execute(
                f"SELECT event_id,event_hash FROM events WHERE project_id=? AND event_id IN ({placeholders}) ORDER BY sequence_no",
                (receipt["project_id"], *ids),
            ).fetchall()
            if [r["event_id"] for r in event_rows] != ids or [r["event_hash"] for r in event_rows] != hashes:
                raise FoundryError("STAGE2_TERMINAL_RECEIPT_EVENT_SET_MISMATCH", "Persisted events differ from the keyed terminal event set.", status_code=409)
        approved_hashes = json.loads(proposal["approved_compiled_event_hashes_json"] or "[]")
        if hashes != approved_hashes:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_EVENT_SET_MISMATCH",
                "The terminal event hashes differ from the exact approved compiled-event sequence.",
                status_code=409,
            )
        project_row, project_doc = self._project_row(conn, receipt["project_id"])
        terminal_count = int(projection.get("event_count") or 0)
        prefix_rows = conn.execute(
            "SELECT sequence_no,event_hash,event_json FROM events WHERE project_id=? ORDER BY sequence_no LIMIT ?",
            (receipt["project_id"], terminal_count),
        ).fetchall()
        if (
            project_row["revision"] < receipt["final_revision"]
            or project_doc["event_stream"]["count"] < terminal_count
            or len(prefix_rows) != terminal_count
            or (prefix_rows[-1]["event_hash"] if prefix_rows else ZERO_HASH) != projection.get("event_chain_head")
        ):
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_PROJECT_STATE_MISMATCH",
                "The project no longer contains the exact revision/event prefix bound by the keyed terminal receipt.",
                status_code=409,
            )
        try:
            prefix_events = [json.loads(item["event_json"]) for item in prefix_rows]
            prefix_state = self.projects._reduce_events(prefix_events, receipt["project_id"], conn, lock_already_proved=True)
        except Exception as exc:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_PROJECT_STATE_MISMATCH",
                "The keyed terminal event prefix cannot be mechanically replayed.",
                details={"error": str(exc)}, status_code=409,
            ) from exc
        if sha256_json(prefix_state) != receipt["state_after_hash"]:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_PROJECT_STATE_MISMATCH",
                "The replayed terminal event prefix differs from the keyed state-after hash.",
                status_code=409,
            )
        try:
            terminal_v3 = [event for event in prefix_events if event.get("schema_version") == EVENT_V3]
            mechanical_state, _terminal_rows, _terminal_entries = self._rows(terminal_v3, receipt["project_id"])
        except Exception as exc:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_MECHANICAL_STATE_MISMATCH",
                "The terminal mechanical state could not be reconstructed from the anchored event prefix.",
                details={
                    "error": str(exc),
                }, status_code=409,
            ) from exc
        if sha256_json(mechanical_state) != receipt["terminal_mechanical_state_hash"]:
            raise FoundryError(
                "STAGE2_TERMINAL_RECEIPT_MECHANICAL_STATE_MISMATCH",
                "The reconstructed mechanical state differs from the keyed terminal receipt.",
                status_code=409,
            )
        return projection

    def _committed_result(self, receipt_row, *, idempotent: bool) -> dict[str, Any]:
        receipt = dict(receipt_row)
        event_ids = json.loads(receipt["event_ids_json"])
        with self.db.connection() as conn:
            self._verify_terminal_receipt(conn, receipt_row)
            _, project = self._project_row(conn, receipt["project_id"])
            replay = self.projects._replay_events(conn, receipt["project_id"])
        stage2 = self.rebuild(receipt["project_id"])
        return {
            "committed": True,
            "idempotent": idempotent,
            "commit_id": receipt["commit_id"],
            "receipt": receipt,
            "event_count": len(event_ids),
            "event_ids": event_ids,
            "project": project,
            "replay": replay,
            "stage2": stage2,
        }

    def _prepare_commit_attempt(self, proposal_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Create one durable STARTED attempt after governing all prior states.

        The attempt row is committed before the event transaction begins. Therefore an
        abrupt process exit leaves a durable STARTED row while SQLite rolls back all
        advancement-event writes. A later caller may convert only that STARTED row to
        immutable INTERRUPTED evidence and begin the next numbered attempt.
        """
        with self.db.transaction() as conn:
            committed = conn.execute(
                "SELECT * FROM stage2_commit_receipts WHERE proposal_id=? AND status='committed'",
                (proposal_id,),
            ).fetchone()
            if committed:
                self._verify_terminal_receipt(conn, committed)
                return dict(committed), None

            row = self._proposal_row(conn, proposal_id)
            attempts = conn.execute(
                "SELECT * FROM stage2_commit_attempts WHERE proposal_id=? ORDER BY attempt_no",
                (proposal_id,),
            ).fetchall()
            latest = attempts[-1] if attempts else None
            if latest and latest["status"] == "committed":
                raise FoundryError(
                    "STAGE2_COMMIT_RECEIPT_MISSING",
                    "A committed attempt exists without its immutable proposal-level terminal receipt.",
                    details={"proposal_id": proposal_id, "attempt_id": latest["attempt_id"]},
                    status_code=409,
                )
            if latest and latest["status"] == "terminal_failed":
                raise FoundryError(
                    "STAGE2_COMMIT_TERMINAL_FAILURE",
                    "The latest commit attempt failed non-retryably; the same approved proposal cannot be retried.",
                    details={"proposal_id": proposal_id, "attempt_id": latest["attempt_id"], "error": json.loads(latest["error_json"]) if latest["error_json"] else None},
                    status_code=409,
                )

            if latest and latest["status"] == "started":
                project_row, _project = self._project_row(conn, row["project_id"])
                if int(project_row["revision"]) != int(latest["base_revision"]):
                    error = {
                        "code": "STAGE2_INTERRUPTED_ATTEMPT_STATE_DIVERGED",
                        "message": "The project revision changed while a STARTED attempt lacked a terminal result.",
                        "expected_revision": latest["base_revision"],
                        "actual_revision": project_row["revision"],
                    }
                    conn.execute(
                        "UPDATE stage2_commit_attempts SET status='terminal_failed',retryable=0,error_json=?,completed_at=? WHERE attempt_id=? AND status='started'",
                        (canonical_json(error), utcnow(), latest["attempt_id"]),
                    )
                    raise FoundryError(error["code"], error["message"], details=error, status_code=409)

                validation_for_recovery = self.compile_proposal(conn, row)
                if not validation_for_recovery["valid"]:
                    error = {
                        "code": "STAGE2_INTERRUPTED_ATTEMPT_REVALIDATION_FAILED",
                        "message": "The interrupted proposal no longer recompiles to an unblocked event set.",
                        "blocker_report": validation_for_recovery["blocker_report"],
                    }
                    conn.execute(
                        "UPDATE stage2_commit_attempts SET status='terminal_failed',retryable=0,error_json=?,completed_at=? WHERE attempt_id=? AND status='started'",
                        (canonical_json(error), utcnow(), latest["attempt_id"]),
                    )
                    raise FoundryError(error["code"], error["message"], details=error, status_code=409)
                self._assert_approved_binding(row, validation_for_recovery, conn)
                compiled_ids = [event["event_id"] for event in validation_for_recovery["compiled_events"]]
                partial = []
                if compiled_ids:
                    placeholders = ",".join("?" for _ in compiled_ids)
                    partial = [r[0] for r in conn.execute(
                        f"SELECT event_id FROM events WHERE project_id=? AND event_id IN ({placeholders}) ORDER BY sequence_no",
                        (row["project_id"], *compiled_ids),
                    )]
                if partial:
                    error = {
                        "code": "STAGE2_INTERRUPTED_ATTEMPT_PARTIAL_EVENTS",
                        "message": "A STARTED attempt has persisted event rows but no terminal receipt; automatic retry is unsafe.",
                        "event_ids": partial,
                    }
                    conn.execute(
                        "UPDATE stage2_commit_attempts SET status='terminal_failed',retryable=0,error_json=?,completed_at=? WHERE attempt_id=? AND status='started'",
                        (canonical_json(error), utcnow(), latest["attempt_id"]),
                    )
                    raise FoundryError(error["code"], error["message"], details=error, status_code=409)
                interrupted_error = {
                    "code": "STAGE2_STARTED_ATTEMPT_RECOVERED",
                    "message": "No partial events or project revision change were found; the prior STARTED attempt was closed as interrupted.",
                }
                conn.execute(
                    "UPDATE stage2_commit_attempts SET status='interrupted',retryable=1,error_json=?,completed_at=? WHERE attempt_id=? AND status='started'",
                    (canonical_json(interrupted_error), utcnow(), latest["attempt_id"]),
                )
                if row["status"] == "committing":
                    conn.execute(
                        "UPDATE stage2_proposals SET status='approved',updated_at=? WHERE proposal_id=?",
                        (utcnow(), proposal_id),
                    )
                    row = self._proposal_row(conn, proposal_id)

            if row["status"] != "approved" or not row["approved_by"]:
                raise FoundryError(
                    "STAGE2_NAMED_APPROVAL_REQUIRED",
                    "Named human approval is required before atomic commit.",
                    details={"status": row["status"]},
                )

            validation = self.compile_proposal(conn, row)
            if not validation["valid"]:
                raise FoundryError(
                    "STAGE2_PROPOSAL_REVALIDATION_FAILED",
                    "The approved proposal is now blocked.",
                    details=validation["blocker_report"],
                )
            self._assert_approved_binding(row, validation, conn)
            before = self.projects._replay_events(conn, row["project_id"])
            attempt_no = int(attempts[-1]["attempt_no"]) + 1 if attempts else 1
            binding_set = self._attempt_binding_set(row)
            binding_hash = sha256_json(binding_set)
            attempt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2-hf2-attempt:{proposal_id}:{attempt_no}:{binding_hash}"))
            conn.execute(
                """INSERT INTO stage2_commit_attempts(
                   attempt_id,proposal_id,project_id,attempt_no,status,retryable,base_revision,final_revision,
                   approved_proposal_hash,approved_validation_hash,approved_child_hashes_json,
                   approved_compiled_event_hashes_json,approved_lock_proof_hash,approved_principal_id,
                   event_ids_json,event_hashes_json,state_before_hash,state_after_hash,error_json,created_at,completed_at,
                   approved_principal_hash,binding_set_hash,approval_evidence_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id, proposal_id, row["project_id"], attempt_no, "started", 1,
                    row["expected_project_revision"], None, row["approved_proposal_hash"],
                    row["approved_validation_hash"], row["approved_child_hashes_json"],
                    row["approved_compiled_event_hashes_json"], row["approved_lock_proof_hash"],
                    row["approved_principal_id"], "[]", "[]", before["state_hash"], None, None,
                    utcnow(), None, binding_set["approved_principal_hash"], binding_hash, row["approval_evidence_id"],
                ),
            )
            return None, {
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "project_id": row["project_id"],
                "base_revision": int(row["expected_project_revision"]),
                "state_before_hash": before["state_hash"],
                "binding_set": binding_set,
                "binding_set_hash": binding_hash,
            }

    def commit_proposal(self, proposal_id: str, *, simulate_crash_after: int | None = None) -> dict[str, Any]:
        with _commit_lock(proposal_id):
            committed, attempt = self._prepare_commit_attempt(proposal_id)
            if committed is not None:
                return self._committed_result(committed, idempotent=True)
            assert attempt is not None
            attempt_id = attempt["attempt_id"]
            try:
                with self.db.transaction() as conn:
                    row = self._proposal_row(conn, proposal_id)
                    if row["status"] != "approved" or not row["approved_by"]:
                        raise FoundryError("STAGE2_NAMED_APPROVAL_REQUIRED", "Named human approval is required before atomic commit.")
                    validation = self.compile_proposal(conn, row)
                    if not validation["valid"]:
                        raise FoundryError("STAGE2_PROPOSAL_REVALIDATION_FAILED", "The approved proposal is now blocked.", details=validation["blocker_report"])
                    self._assert_approved_binding(row, validation, conn)
                    current_binding = self._attempt_binding_set(row)
                    if sha256_json(current_binding) != attempt["binding_set_hash"] or current_binding != attempt["binding_set"]:
                        raise FoundryError(
                            "STAGE2_COMMIT_ATTEMPT_BINDING_MISMATCH",
                            "The durable commit attempt is not bound to the exact current R1 approval evidence.",
                            status_code=409,
                        )
                    events = validation["compiled_events"]
                    before = self.projects._replay_events(conn, row["project_id"])
                    if int(row["expected_project_revision"]) != attempt["base_revision"] or before["state_hash"] != attempt["state_before_hash"]:
                        raise FoundryError(
                            "STAGE2_COMMIT_ATTEMPT_BASE_STATE_MISMATCH",
                            "The project revision or replay state changed after the durable attempt began.",
                            details={
                                "expected_revision": attempt["base_revision"],
                                "actual_revision": row["expected_project_revision"],
                                "expected_state_hash": attempt["state_before_hash"],
                                "actual_state_hash": before["state_hash"],
                            },
                            status_code=409,
                        )
                    conn.execute("UPDATE stage2_proposals SET status='committing',updated_at=? WHERE proposal_id=?", (utcnow(), proposal_id))
                    for index, event in enumerate(events, start=1):
                        conn.execute("INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)", (event["project_id"], event["sequence"], event["event_id"], event["event_hash"], event["previous_event_hash"], event["created_at"], canonical_json(event), None, event["schema_version"], "valid"))
                        for bind in event["advancement"]["authority_bindings"]:
                            conn.execute("INSERT OR REPLACE INTO stage2_calculation_authority_receipts(event_id,authority_role,record_id,record_hash,source_hash,binding_hash,binding_json) VALUES(?,?,?,?,?,?,?)", (event["event_id"], bind["role"], bind["record_id"], bind["record_hash"], bind["source_hash"], sha256_json(bind), canonical_json(bind)))
                            rec = self.projects._resolve_locked_record_after_proof(conn, event["project_id"], bind["record_id"])
                            if rec:
                                self.projects._assert_snapshot_record(conn, event["project_id"], rec)
                        txn = event["advancement"].get("training_transaction")
                        if txn:
                            conn.execute("INSERT INTO stage2_training_transactions(event_id,project_id,character_cl,attempt_id,retry_of_attempt_id,target_record_id,source_record_id,transaction_hash,result,slot_cost,transaction_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (event["event_id"], event["project_id"], txn["character_cl"], txn["attempt_id"], txn["retry_of_attempt_id"], txn["target_record_id"], txn["training_source_record_id"], sha256_json(txn), txn["result"], txn["slot_cost"], canonical_json(txn), utcnow()))
                        if simulate_crash_after is not None and index >= simulate_crash_after:
                            raise RuntimeError("SIMULATED_STAGE2_HF2_CRASH")
                    replay = self.projects._replay_events(conn, row["project_id"])
                    final_revision = int(row["expected_project_revision"]) + len(events)
                    project = self._update_project_after_batch(conn, row["project_id"], replay, [e["event_id"] for e in events], validation["mechanical_state_hash"], proposal_id, final_revision)
                    event_ids_json = canonical_json([e["event_id"] for e in events])
                    event_hashes_json = canonical_json([e["event_hash"] for e in events])
                    conn.execute("UPDATE stage2_proposals SET status='committed',updated_at=? WHERE proposal_id=?", (utcnow(), proposal_id))
                    conn.execute(
                        """UPDATE stage2_commit_attempts SET status='committed',retryable=0,final_revision=?,
                           event_ids_json=?,event_hashes_json=?,state_after_hash=?,error_json=NULL,completed_at=?
                           WHERE attempt_id=? AND status='started'""",
                        (final_revision, event_ids_json, event_hashes_json, replay["state_hash"], utcnow(), attempt_id),
                    )
                    commit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2-hf2-terminal:{proposal_id}"))
                    completed_at = utcnow()
                    terminal_projection = self._terminal_projection(
                        conn, commit_id=commit_id, row=row, attempt=attempt, validation=validation,
                        events=events, replay=replay, final_revision=final_revision, completed_at=completed_at,
                    )
                    terminal_projection_json = canonical_json(terminal_projection)
                    terminal_projection_hash = sha256_json(terminal_projection)
                    terminal_envelope = self.integrity.sign(TERMINAL_RECEIPT_DOMAIN, terminal_projection)
                    conn.execute(
                        """INSERT INTO stage2_commit_receipts(
                           commit_id,proposal_id,project_id,status,base_revision,final_revision,event_ids_json,event_hashes_json,
                           state_before_hash,state_after_hash,error_json,created_at,completed_at,approved_proposal_hash,
                           approved_validation_hash,approved_child_hashes_json,approved_compiled_event_hashes_json,
                           approved_lock_proof_hash,approved_principal_id,terminal_attempt_id,approved_principal_hash,binding_set_hash,
                           approval_evidence_id,terminal_projection_json,terminal_projection_hash,terminal_mechanical_state_hash,
                           integrity_version,integrity_key_id,integrity_domain,integrity_mac)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            commit_id, proposal_id, row["project_id"], "committed", attempt["base_revision"], final_revision,
                            event_ids_json, event_hashes_json, attempt["state_before_hash"], replay["state_hash"], None,
                            completed_at, completed_at, row["approved_proposal_hash"], row["approved_validation_hash"],
                            row["approved_child_hashes_json"], row["approved_compiled_event_hashes_json"],
                            row["approved_lock_proof_hash"], row["approved_principal_id"], attempt_id,
                            current_binding["approved_principal_hash"], attempt["binding_set_hash"], row["approval_evidence_id"],
                            terminal_projection_json, terminal_projection_hash, validation["mechanical_state_hash"],
                            terminal_envelope.integrity_version, terminal_envelope.key_id, terminal_envelope.domain, terminal_envelope.mac,
                        ),
                    )
                with self.db.connection() as conn:
                    receipt = conn.execute("SELECT * FROM stage2_commit_receipts WHERE proposal_id=?", (proposal_id,)).fetchone()
                return self._committed_result(receipt, idempotent=False)
            except Exception as exc:
                retryable = not isinstance(exc, FoundryError)
                terminal_status = "rolled_back" if retryable else "terminal_failed"
                error = {
                    "type": type(exc).__name__,
                    "code": exc.code if isinstance(exc, FoundryError) else "STAGE2_ATOMIC_COMMIT_ROLLED_BACK",
                    "message": exc.message if isinstance(exc, FoundryError) else str(exc),
                    "details": exc.details if isinstance(exc, FoundryError) else None,
                }
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE stage2_commit_attempts SET status=?,retryable=?,error_json=?,completed_at=? WHERE attempt_id=? AND status='started'",
                        (terminal_status, 1 if retryable else 0, canonical_json(error), utcnow(), attempt_id),
                    )
                    proposal = conn.execute("SELECT status FROM stage2_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
                    if proposal and proposal["status"] == "committing":
                        conn.execute("UPDATE stage2_proposals SET status='approved',updated_at=? WHERE proposal_id=?", (utcnow(), proposal_id))
                if isinstance(exc, FoundryError):
                    raise
                raise FoundryError(
                    "STAGE2_ATOMIC_COMMIT_ROLLED_BACK",
                    "The complete Stage 2 HF2 transaction was rolled back; immutable attempt evidence was retained and the proposal remains retryable.",
                    details={"error": str(exc), "attempt_id": attempt_id},
                )

    # ---------- projection ----------
    def _rows(self, events: list[dict[str, Any]], project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        state = _state(project_id)
        rows: list[dict[str, Any]] = []
        provenance: dict[str, Any] = {}
        by_cl: dict[int, list[dict[str, Any]]] = {}
        cumulative: list[dict[str, Any]] = []
        for event in events:
            by_cl.setdefault(int(event["advancement"]["target_cl"]), []).append(event)
        previous_hp = 0
        for cl in sorted(k for k in by_cl if k >= 0):
            current = sorted(by_cl[cl], key=lambda e: (e["effective_point"]["order"], e["sequence"]))
            for event in current:
                state = self._apply_event(state, event)
                cumulative.append(event)
            if cl < 1 or cl not in state["completed_levels"]:
                continue
            level_event = next(e for e in cumulative if e["advancement"]["kind"] == "level_advance" and e["advancement"]["target_cl"] == cl)
            level_outputs = level_event["advancement"]["calculation"]["outputs"]
            training = [deepcopy(e["advancement"]["training_transaction"]) for e in current if e["advancement"].get("training_transaction")]
            successes = sum(t["slot_cost"] for t in training if t["result"] == "success")
            failures = sum(1 for t in training if t["result"] == "failure")
            cap = int(level_outputs.get("trained_choice_capacity", 3))
            cumulative_by_id = {e["event_id"]: e for e in cumulative}

            def source_rows(event: dict[str, Any]) -> list[dict[str, Any]]:
                rows_out: list[dict[str, Any]] = []
                seen: set[tuple[str, str, str, str]] = set()
                for source in list(event.get("source_evidence", [])) + list(event["advancement"].get("authority_bindings", [])):
                    normalized = {
                        "source_id": source["source_id"],
                        "source_hash": source["source_hash"],
                        "source_anchor": source.get("source_anchor", source.get("anchor", "")),
                        "source_path": source.get("source_path", source.get("path", "")),
                    }
                    key = tuple(normalized[name] for name in ("source_id", "source_hash", "source_anchor", "source_path"))
                    if key not in seen:
                        seen.add(key)
                        rows_out.append(normalized)
                return rows_out

            def record_detail(record_id: str, preferred_event_id: str | None = None) -> dict[str, Any]:
                event = cumulative_by_id.get(preferred_event_id) if preferred_event_id else None
                if event is None:
                    event_id = state["record_event_ids"].get(record_id)
                    event = cumulative_by_id.get(event_id)
                if event is None:
                    event = next((candidate for candidate in reversed(cumulative) if candidate["subject"]["record_id"] == record_id), None)
                if event is None:
                    raise FoundryError("VISIBLE_LEDGER_RECORD_EVENT_MISSING", "A visible selected record lacks its causal event.", details={"record_id": record_id, "cl": cl})
                return {
                    "record_id": record_id,
                    "display_name": event["subject"]["display_name"],
                    "content_type": event["subject"]["content_type"],
                    "acquisition_event_id": event["event_id"],
                    "acquisition_kind": event["advancement"]["kind"],
                    "legal_channel": event["legal_channel"],
                    "source_record_ids": _sort_unique([event["subject"]["record_id"]] + [binding["record_id"] for binding in event["advancement"].get("authority_bindings", [])]),
                    "source_evidence": source_rows(event),
                }

            def selected_detail(value: Any) -> dict[str, Any]:
                return record_detail(value) if isinstance(value, str) else deepcopy(value)

            def ability_effect(event: dict[str, Any]) -> dict[str, Any]:
                abilities = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
                calculation = event["advancement"]["calculation"]
                inputs = calculation.get("inputs") or {}
                outputs = calculation.get("outputs") or {}
                before = inputs.get("prior_scores")
                after = outputs.get("ability_scores") or {}
                if isinstance(before, dict):
                    selected = {ability: int(after[ability]) - int(before[ability]) for ability in abilities if int(after.get(ability, before[ability])) != int(before[ability])}
                elif isinstance(inputs.get("deltas"), dict):
                    selected = deepcopy(inputs["deltas"])
                elif inputs.get("ability") in abilities and isinstance(inputs.get("amount"), int):
                    selected = {inputs["ability"]: inputs["amount"]}
                else:
                    selected = {}
                return {
                    "event_id": event["event_id"],
                    "kind": event["advancement"]["kind"],
                    "record_id": event["subject"]["record_id"],
                    "display_name": event["subject"]["display_name"],
                    "legal_channel": event["legal_channel"],
                    "selected_increments": selected,
                    "scores_before": deepcopy(before) if isinstance(before, dict) else None,
                    "scores_after": deepcopy(after),
                    "modifiers_after": deepcopy(outputs.get("ability_modifiers") or state["ability_modifiers"]),
                    "hp_retroactive_con_adjustment": int((calculation.get("trace") or {}).get("hp_retroactive_con_delta", 0)),
                    "source_record_ids": _sort_unique([event["subject"]["record_id"]] + [binding["record_id"] for binding in event["advancement"].get("authority_bindings", [])]),
                }

            def typed_none_event(target: str) -> dict[str, Any] | None:
                if target not in state.get("typed_none_states", {}):
                    return None
                return next(
                    (
                        event
                        for event in reversed(cumulative)
                        if event["advancement"]["kind"] == "typed_none"
                        and event["advancement"]["details"].get("target") == target
                    ),
                    None,
                )

            def absence_resolution(target: str, label: str) -> dict[str, Any]:
                typed = typed_none_event(target)
                if typed is not None:
                    value = deepcopy(state["typed_none_states"][target])
                    return {
                        **value,
                        "resolution_event_id": typed["event_id"],
                        "authority_record_id": typed["subject"]["record_id"],
                    }
                return {
                    "state": "not_yet_acquired",
                    "reason_code": "no_acquisition_event_through_level",
                    "reason": f"No {label} acquisition event exists in the canonical event prefix through CL {cl}.",
                    "source_backed": True,
                    "as_of_event_id": level_event["event_id"],
                }

            manual_entries: list[dict[str, Any]] = []
            for art in state["recorded_arts"]:
                acquisition_event = cumulative_by_id.get(art.get("acquisition_event_id"))
                transaction = (
                    acquisition_event["advancement"].get("training_transaction")
                    if acquisition_event is not None
                    else None
                )
                manual_entries.append(
                    {
                        "record_id": art["record_id"],
                        "display_name": art["display_name"],
                        "technique_name": art["technique_name"],
                        "acquisition_event_id": art["acquisition_event_id"],
                        "training_source_record_id": transaction["training_source_record_id"],
                        "training_source_access_event_id": transaction["training_source_access_event_id"],
                        "parent_manual_record_id": art["parent_manual_record_id"],
                        "parent_manual_name": art["parent_manual_name"],
                        "dm_facing_line": art["dm_facing_line"],
                        "associated_sphere_record_ids": deepcopy(art["associated_sphere_record_ids"]),
                        "associated_sphere_names": deepcopy(art["associated_sphere_names"]),
                        "reproduced_component_record_ids": deepcopy(art["reproduced_component_record_ids"]),
                        "reproduced_component_names": deepcopy(art["reproduced_component_names"]),
                        "expression_kind": art["expression_kind"],
                        "difficulty": art["learning_dc"].get("difficulty"),
                        "computed_learning_dc": transaction["computed_dc"],
                        "linked_action_id": art["linked_action_id"],
                        "fixed_expression_warning": art["fixed_expression_warning"],
                        "execution": deepcopy(art["execution"]),
                    }
                )
            manuals_resolution = (
                {
                    "state": "present",
                    "record_ids": [entry["record_id"] for entry in manual_entries],
                    "acquisition_event_ids": [entry["acquisition_event_id"] for entry in manual_entries],
                    "entries": manual_entries,
                }
                if manual_entries
                else absence_resolution("manuals", "Martial Manual / Recorded Art")
            )

            equipment_entries = [
                {
                    **record_detail(record_id),
                }
                for record_id in state["equipment"]
            ]
            equipment_resolution = (
                {
                    "state": "present",
                    "record_ids": [entry["record_id"] for entry in equipment_entries],
                    "acquisition_event_ids": [entry["acquisition_event_id"] for entry in equipment_entries],
                    "entries": equipment_entries,
                }
                if equipment_entries
                else absence_resolution("equipment", "equipment")
            )

            subpath_entries = [
                {
                    **record_detail(record_id),
                }
                for record_id in state["subpaths"]
            ]
            subpath_resolution = (
                {
                    "state": "present",
                    "record_ids": [entry["record_id"] for entry in subpath_entries],
                    "acquisition_event_ids": [entry["acquisition_event_id"] for entry in subpath_entries],
                    "entries": subpath_entries,
                }
                if subpath_entries
                else absence_resolution("subpaths", "Subpath")
            )

            forged_resolution = absence_resolution("forged_techniques", "Forged Technique")
            level_hp = level_outputs["hp_after"]
            hp_formula_trace = level_event["advancement"]["calculation"]["trace"]["hp"]
            hp_inputs = level_event["advancement"]["calculation"]["inputs"]
            hp_adjustment_events = [
                event for event in current
                if event["advancement"]["kind"] in {"ability_score_change", "cultivation_insight_acquisition", "background_acquisition"}
                and int((event["advancement"]["calculation"].get("trace") or {}).get("hp_retroactive_con_delta", 0)) != 0
            ]
            hp_retroactive_adjustment = sum(
                int((event["advancement"]["calculation"].get("trace") or {}).get("hp_retroactive_con_delta", 0))
                for event in hp_adjustment_events
            )
            hp_retroactive_details = []
            for event in hp_adjustment_events:
                calculation = event["advancement"]["calculation"]
                before_scores = calculation.get("inputs", {}).get("prior_scores") or {}
                after_scores = calculation.get("outputs", {}).get("ability_scores") or {}
                before_score = int(before_scores["CON"])
                after_score = int(after_scores["CON"])
                before_modifier = _ability_modifier(before_score)
                after_modifier = _ability_modifier(after_score)
                hp_retroactive_details.append(
                    {
                        "event_id": event["event_id"],
                        "con_score_before": before_score,
                        "con_score_after": after_score,
                        "con_modifier_before": before_modifier,
                        "con_modifier_after": after_modifier,
                        "modifier_delta": after_modifier - before_modifier,
                        "affected_levels": cl,
                        "total_adjustment": int((calculation.get("trace") or {}).get("hp_retroactive_con_delta", 0)),
                    }
                )
            hp_level_gain = int(level_hp["last_gain"])
            hp_total_change = int(state["hp"]["total"]) - previous_hp
            hp_per_level_adjustment = hp_retroactive_adjustment // cl if hp_retroactive_adjustment and hp_retroactive_adjustment % cl == 0 else 0
            hp = {
                "base": hp_level_gain,
                "contribution": hp_retroactive_adjustment,
                "gain": hp_total_change,
                "level_formula_gain": hp_level_gain,
                "retroactive_con_adjustment": hp_retroactive_adjustment,
                "retroactive_con_per_level": hp_per_level_adjustment,
                "retroactive_con_affected_levels": cl if hp_retroactive_adjustment else 0,
                "prior_total": previous_hp,
                "total": state["hp"]["total"],
                "formula_id": level_hp["last_formula_id"],
                "formula_expression": _formula_trace_text(hp_formula_trace),
                "formula_inputs": {
                    "cl": cl,
                    "pb": state["pb"],
                    "con_score": hp_inputs["ability_scores"]["CON"],
                    "con_modifier": hp_inputs["ability_modifiers"]["CON"],
                },
                "arithmetic": f"{previous_hp} + {hp_level_gain} + {hp_retroactive_adjustment} = {state['hp']['total']}",
                "adjustment_event_ids": [event["event_id"] for event in hp_adjustment_events],
                "retroactive_con_adjustment_details": hp_retroactive_details,
                "authority_components": level_hp["components"],
            }

            resources: dict[str, Any] = {}
            def resource_trace(event: dict[str, Any]) -> dict[str, Any]:
                trace = event["advancement"]["calculation"].get("trace") or {}
                # Early HF1 ability recalculation receipts used the singular
                # compatibility key.  New events use the canonical plural key;
                # both remain mechanically equivalent for replay.
                return trace.get("resources") or trace.get("resource") or {}

            for rid, value in sorted(state["resources"].items()):
                resource_event = next(
                    (
                        event
                        for event in reversed(cumulative)
                        if rid in resource_trace(event)
                    ),
                    None,
                )
                if resource_event is None:
                    raise FoundryError(
                        "STAGE2_RESOURCE_TRACE_MISSING",
                        "A visible resource lacks a causal calculation trace in the anchored event prefix.",
                        details={
                            "resource_id": rid,
                            "character_cl": cl,
                            "current_event_ids": [event["event_id"] for event in current],
                            "cumulative_event_ids": [event["event_id"] for event in cumulative],
                        },
                    )
                traces = resource_trace(resource_event)[rid]
                path_trace = traces["path_base"]
                key_ability = _formula_trace_ability(path_trace)
                modifier_details: list[dict[str, Any]] = []
                for component in value["authority_components"]:
                    if component["role"] == "path_base":
                        continue
                    trace_key = next((key for key in traces if key != "path_base" and component["record_id"] in key), None)
                    modifier_details.append({
                        "role": component["role"],
                        "value": component["value"],
                        "formula_id": component["formula_id"],
                        "formula_expression": _formula_trace_text(traces[trace_key]) if trace_key else f"published modifier = {component['value']}",
                        "authority": record_detail(component["record_id"]),
                    })
                total_terms = [value["base_value"], value["method_delta"], value["foundation_delta"], value["equipment_delta"]]
                resources[rid] = {
                    "base_value": value["base_value"], "method_delta": value["method_delta"], "foundation_delta": value["foundation_delta"], "equipment_delta": value["equipment_delta"], "maximum": value["maximum"], "current_before": value["current_before"], "current_after": value["current"], "formula_id": value["formula_id"], "formula_expression": _formula_trace_text(path_trace), "formula_inputs": {"cl": cl, "pb": state["pb"], "key_ability": key_ability, "key_ability_score": state["ability_scores"].get(key_ability) if key_ability else None, "key_ability_modifier": state["ability_modifiers"].get(key_ability) if key_ability else None}, "maximum_arithmetic": f"{' + '.join(str(term) for term in total_terms)} = {value['maximum']}", "modifier_details": modifier_details, "authority_components": value["authority_components"],
                }
            level_talent = state["level_talents"].get(str(cl), [])
            level_talent_entries = [record_detail(value["record_id"], value["event_id"]) for value in level_talent]
            level_acquisition_events = [
                {
                    "event_id": event["event_id"],
                    "kind": event["advancement"]["kind"],
                    "record_id": event["subject"]["record_id"],
                    "display_name": event["subject"]["display_name"],
                    "content_type": event["subject"]["content_type"],
                    "legal_channel": event["legal_channel"],
                    "source_record_ids": _sort_unique(
                        [event["subject"]["record_id"]]
                        + [binding["record_id"] for binding in event["advancement"].get("authority_bindings", [])]
                    ),
                }
                for event in current
            ]
            level_acquisitions: dict[str, list[str]] = {}
            for event in level_acquisition_events:
                level_acquisitions.setdefault(event["kind"], []).append(event["record_id"])

            method_value = absence_resolution("method", "Method") if isinstance(state["method"], dict) and state["method"].get("state") == "none" else deepcopy(state["method"])
            method_acquisition_event = next(
                (
                    event
                    for event in reversed(cumulative)
                    if event["advancement"]["kind"] == "method_acquisition"
                    and event["subject"]["record_id"] == method_value.get("record_id")
                ),
                None,
            )
            if method_value.get("state") == "active":
                method_detail = {
                    "state": "active",
                    "selection": record_detail(
                        method_value["record_id"],
                        method_acquisition_event["event_id"] if method_acquisition_event else None,
                    ),
                    "activation_event_id": method_value["event_id"],
                }
            elif method_value.get("state") == "acquired":
                # Acquisition establishes ownership/availability only.  Keep the
                # named selection and its causal event visible, while explicitly
                # proving that no activation event or resource modifier exists.
                method_detail = {
                    "state": "acquired",
                    "selection": record_detail(
                        method_value["record_id"],
                        method_acquisition_event["event_id"] if method_acquisition_event else method_value["event_id"],
                    ),
                    "activation_event_id": None,
                    "resource_modifier_active": False,
                }
            else:
                method_detail = deepcopy(method_value)
            foundation_value = absence_resolution("foundation", "Foundation") if isinstance(state["foundation"], dict) and state["foundation"].get("state") == "none" else deepcopy(state["foundation"])
            foundation_acquisition_event = next(
                (
                    event
                    for event in reversed(cumulative)
                    if event["advancement"]["kind"] == "foundation_acquisition"
                    and event["subject"]["record_id"] == foundation_value.get("record_id")
                ),
                None,
            )
            foundation_expression_event = next(
                (
                    event
                    for event in reversed(cumulative)
                    if event["advancement"]["kind"] == "foundation_expression"
                    and event["subject"]["record_id"] == foundation_value.get("expression_record_id")
                ),
                None,
            )
            if foundation_value.get("state") == "active":
                foundation_detail = {
                    "state": "active",
                    "selection": record_detail(foundation_value["record_id"]),
                    "expression": record_detail(foundation_value["expression_record_id"]),
                    "path": record_detail(foundation_value["path_id"]),
                    "stage": foundation_value["stage"],
                    "stage_event_id": foundation_value["stage_event_id"],
                }
            elif foundation_value.get("state") == "expressed":
                foundation_detail = {
                    "state": "expressed",
                    "selection": record_detail(
                        foundation_value["record_id"],
                        foundation_acquisition_event["event_id"] if foundation_acquisition_event else None,
                    ),
                    "expression": record_detail(
                        foundation_value["expression_record_id"],
                        foundation_expression_event["event_id"] if foundation_expression_event else foundation_value["event_id"],
                    ),
                    "path": record_detail(foundation_value["path_id"]),
                    "expression_event_id": foundation_expression_event["event_id"] if foundation_expression_event else foundation_value["event_id"],
                    "stage_event_id": None,
                    "resource_modifier_active": False,
                }
            elif foundation_value.get("state") == "acquired":
                foundation_detail = {
                    "state": "acquired",
                    "selection": record_detail(
                        foundation_value["record_id"],
                        foundation_acquisition_event["event_id"] if foundation_acquisition_event else foundation_value["event_id"],
                    ),
                    "expression_event_id": None,
                    "stage_event_id": None,
                    "resource_modifier_active": False,
                }
            else:
                foundation_detail = deepcopy(foundation_value)
            def route_absence(reason_code: str, reason: str) -> dict[str, Any]:
                return {"state": "none", "reason_code": reason_code, "reason": reason, "source_backed": True}

            sect_trial_sphere_value = state["sect_trial_sphere"] or route_absence(
                "ai_bootstrap_route_selected",
                "The project uses the source-backed AI-bootstrap creation route instead of a sect-trial Sphere event.",
            )
            sect_trial_talent_value = state["sect_trial_talent"] or route_absence(
                "ai_bootstrap_route_selected",
                "The project uses the source-backed AI-bootstrap creation route instead of a sect-trial Talent event.",
            )
            ai_bootstrap_sphere_value = state["ai_bootstrap_sphere"] or route_absence(
                "player_sect_trial_route_selected",
                "The project uses the source-backed player sect-trial creation route instead of an AI-bootstrap Sphere event.",
            )
            ai_bootstrap_talent_value = state["ai_bootstrap_talent"] or route_absence(
                "player_sect_trial_route_selected",
                "The project uses the source-backed player sect-trial creation route instead of an AI-bootstrap Talent event.",
            )

            row = {
                "cl": cl,
                "pb": state["pb"],
                "hp": hp,
                "resources": resources,
                "ability_scores": deepcopy(state["ability_scores"]),
                "ability_modifiers": deepcopy(state["ability_modifiers"]),
                "ability_score_effects": [ability_effect(e) for e in current if e["advancement"]["kind"] in {"starting_state", "background_acquisition", "ability_score_change", "cultivation_insight_acquisition"} and e["advancement"]["calculation"]["outputs"].get("ability_scores")],
                "background": state["background"] or _none("not_selected", "No Background event exists at this snapshot."),
                "background_detail": selected_detail(state["background"] or _none("not_selected", "No Background event exists at this snapshot.")),
                "background_sphere": state["background_sphere"] or _none("not_selected", "No Background Sphere event exists at this snapshot."),
                "background_sphere_detail": selected_detail(state["background_sphere"] or _none("not_selected", "No Background Sphere event exists at this snapshot.")),
                "background_talent": state["background_talent"] or _none("not_selected", "No Background Talent event exists at this snapshot."),
                "background_talent_detail": selected_detail(state["background_talent"] or _none("not_selected", "No Background Talent event exists at this snapshot.")),
                "origin_insight": state["origin_insight"] or _none("not_selected", "No Origin Insight event exists at this snapshot."),
                "origin_insight_detail": selected_detail(state["origin_insight"] or _none("not_selected", "No Origin Insight event exists at this snapshot.")),
                "sect_trial_sphere": sect_trial_sphere_value,
                "sect_trial_sphere_detail": selected_detail(state["sect_trial_sphere"] or _none("ai_bootstrap_route_selected", "The AI-bootstrap route replaces the sect-trial Sphere event.")),
                "sect_trial_talent": sect_trial_talent_value,
                "sect_trial_talent_detail": selected_detail(state["sect_trial_talent"] or _none("ai_bootstrap_route_selected", "The AI-bootstrap route replaces the sect-trial Talent event.")),
                "ai_bootstrap_sphere": ai_bootstrap_sphere_value,
                "ai_bootstrap_sphere_detail": selected_detail(state["ai_bootstrap_sphere"] or _none("player_sect_trial_route_selected", "The player sect-trial route replaces the AI-bootstrap Sphere event.")),
                "ai_bootstrap_talent": ai_bootstrap_talent_value,
                "ai_bootstrap_talent_detail": selected_detail(state["ai_bootstrap_talent"] or _none("player_sect_trial_route_selected", "The player sect-trial route replaces the AI-bootstrap Talent event.")),
                "paths": deepcopy(state["paths"]),
                "path_details": [record_detail(record_id) for record_id in state["paths"]],
                "subpaths": deepcopy(state["subpaths"]),
                "subpath_resolution": subpath_resolution,
                "method": method_value,
                "method_detail": method_detail,
                "foundation": foundation_value,
                "foundation_detail": foundation_detail,
                "level_talent": {"capacity": int(level_outputs.get("level_talent_capacity", 1)), "used": len(level_talent), "record_ids": [x["record_id"] for x in level_talent], "event_ids": [x["event_id"] for x in level_talent], "entries": level_talent_entries, "source_rule_id": level_event["subject"]["record_id"]},
                "trained_choice_capacity": {"capacity": cap, "successful_used": int(state["trained_success_cost"].get(str(cl), 0)), "failed_attempts": failures, "remaining": max(0, cap - int(state["trained_success_cost"].get(str(cl), 0))), "source_rule_id": level_event["subject"]["record_id"]},
                "training_transactions": training,
                "new_sphere_entitlements": [deepcopy(x) for x in state["new_sphere_entitlements"] if x["character_cl"] == cl],
                "cultivation_insights_after_level": deepcopy(state["cultivation_insights"]),
                "cultivation_insight_details": [record_detail(record_id) for record_id in state["cultivation_insights"]],
                "cultivation_insight_occurrences": deepcopy(state["cultivation_insight_occurrences"]),
                "automatic_sphere_component_receipts": deepcopy(state["automatic_sphere_component_receipts"]),
                "automatic_sphere_components": deepcopy(state["automatic_sphere_components"]),
                "training_sources_after_level": deepcopy(state["training_sources"]),
                "training_source_details": [record_detail(record_id) for record_id in state["training_sources"]],
                "known_spheres_after_level": deepcopy(state["known_spheres"]),
                "known_sphere_details": [record_detail(record_id) for record_id in state["known_spheres"]],
                "known_talents_after_level": deepcopy(state["known_talents"]),
                "known_talent_details": [record_detail(record_id) for record_id in state["known_talents"]],
                "recorded_arts_after_level": deepcopy(state["recorded_arts"]),
                "manuals_resolution": manuals_resolution,
                "forged_techniques_after_level": deepcopy(state["forged_techniques"]) if isinstance(state["forged_techniques"], list) else deepcopy(forged_resolution),
                "forged_techniques_resolution": forged_resolution,
                "equipment_after_level": deepcopy(state["equipment"]),
                "equipment_resolution": equipment_resolution,
                "level_acquisitions": level_acquisitions,
                "level_acquisition_events": level_acquisition_events,
                "legality": {"status": "valid", "blocker_count": 0, "event_count": len(current)},
                "row_hash": ZERO_HASH,
            }
            row["row_hash"] = sha256_json({k: v for k, v in row.items() if k != "row_hash"})
            rows.append(row)
            previous_hp = state["hp"]["total"]
            latest_by_record = {e["subject"]["record_id"]: e for e in cumulative}
            latest_ability = next((e for e in reversed(cumulative) if e["advancement"]["kind"] in {"starting_state", "background_acquisition", "ability_score_change", "cultivation_insight_acquisition"} and e["advancement"]["calculation"]["outputs"].get("ability_scores")), None)
            transaction_by_attempt = {e["advancement"]["training_transaction"]["attempt_id"]: e for e in cumulative if e["advancement"].get("training_transaction")}
            event_by_id = {e["event_id"]: e for e in cumulative}

            def _dedupe_events(candidates: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
                """Preserve event order while rejecting object-equality and fallback tricks."""
                out: list[dict[str, Any]] = []
                seen: set[str] = set()
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    event_id = candidate.get("event_id")
                    if not isinstance(event_id, str) or not event_id or event_id in seen:
                        continue
                    seen.add(event_id)
                    out.append(candidate)
                return out

            def proof(selected: list[dict[str, Any] | None]) -> dict[str, Any] | None:
                """Compile a field proof only from causal events and their bound authorities.

                There is deliberately no ``or [level_event]`` fallback.  A caller must name
                the event(s) that actually produced the field, or the field remains unproven
                and the rebuild gate blocks publication.
                """
                selected_events = _dedupe_events(selected)
                if not selected_events:
                    return None

                # Include acquisition/access events explicitly referenced by calculation
                # authority bindings and training transactions.  A dangling causal ID is a
                # broken proof, not something a nearby level event may conceal.
                expanded = list(selected_events)
                missing_causal_ids: set[str] = set()
                cursor = 0
                while cursor < len(expanded):
                    event = expanded[cursor]
                    cursor += 1
                    causal_ids = {
                        binding.get("causal_event_id")
                        for binding in event["advancement"].get("authority_bindings", [])
                        if binding.get("causal_event_id")
                    }
                    transaction = event["advancement"].get("training_transaction") or {}
                    if transaction.get("training_source_access_event_id"):
                        causal_ids.add(transaction["training_source_access_event_id"])
                    already = {item["event_id"] for item in expanded}
                    for causal_id in sorted(causal_ids):
                        causal_event = event_by_id.get(causal_id)
                        if causal_event is None:
                            missing_causal_ids.add(causal_id)
                        elif causal_id not in already:
                            expanded.append(causal_event)
                            already.add(causal_id)
                if missing_causal_ids:
                    return None
                selected_events = _dedupe_events(expanded)

                event_ids = [event["event_id"] for event in selected_events]
                event_hashes = [event["event_hash"] for event in selected_events]
                bindings = [binding for event in selected_events for binding in event["advancement"].get("authority_bindings", [])]
                record_ids = _sort_unique([event["subject"]["record_id"] for event in selected_events] + [binding["record_id"] for binding in bindings])
                record_hashes = _sort_unique([event["content_binding"]["record_hash"] for event in selected_events] + [binding["record_hash"] for binding in bindings])
                channels = _sort_unique([event["legal_channel"] for event in selected_events])
                sources: list[dict[str, Any]] = []
                seen_sources: set[tuple[str, str, str, str]] = set()

                def add_source(source: dict[str, Any]) -> None:
                    normalized = {
                        "source_id": source["source_id"],
                        "source_hash": source["source_hash"],
                        "source_anchor": source.get("source_anchor", source.get("anchor", "")),
                        "source_path": source.get("source_path", source.get("path", "")),
                    }
                    key = (normalized["source_id"], normalized["source_hash"], normalized["source_anchor"], normalized["source_path"])
                    if key not in seen_sources:
                        sources.append(normalized)
                        seen_sources.add(key)

                for event in selected_events:
                    for source in event.get("source_evidence", []):
                        add_source(source)
                    # Authority records can come from a different rule/source than the
                    # subject.  Preserve those sources instead of falsely attributing a
                    # calculation solely to the acquired record's document.
                    for binding in event["advancement"].get("authority_bindings", []):
                        add_source(binding)
                if not record_ids or not record_hashes or not channels or not sources:
                    return None
                return {
                    "event_ids": event_ids,
                    "event_hashes": event_hashes,
                    "catalog_record_ids": record_ids,
                    "catalog_record_hashes": record_hashes,
                    "acquisition_channels": channels,
                    "source_evidence": sources,
                    "calculation": {
                        "rule_id": "TIANXIA.STAGE2.HF1.FIELD_PROVENANCE.v1",
                        "inputs": {
                            "event_ids": event_ids,
                            "authority_roles": _sort_unique([binding["role"] for binding in bindings]),
                        },
                        "outputs": {"row_hash": row["row_hash"]},
                    },
                }

            def _collection_event(values: list[Any], prefix: str, relative: str) -> list[dict[str, Any] | None]:
                if relative == prefix and not values:
                    # An empty cumulative collection is a closed-world replay result.  The
                    # complete event prefix, not an arbitrary level event, proves absence.
                    return list(cumulative)
                if not relative.startswith(prefix + "/"):
                    return []
                try:
                    index = int(relative[len(prefix) + 1 :].split("/", 1)[0])
                    value = values[index]
                    record_id = value if isinstance(value, str) else value.get("record_id")
                    event_id = value.get("acquisition_event_id") if isinstance(value, dict) else None
                    return [event_by_id.get(event_id) if event_id else latest_by_record.get(record_id)]
                except (IndexError, KeyError, TypeError, ValueError):
                    return []

            def _resolution_events(resolution: dict[str, Any], prefix: str, relative: str) -> list[dict[str, Any] | None]:
                if resolution.get("state") == "present":
                    event_ids = resolution.get("acquisition_event_ids", [])
                    for collection_name in ("record_ids", "acquisition_event_ids", "entries"):
                        marker = f"{prefix}/{collection_name}/"
                        if relative.startswith(marker):
                            try:
                                index = int(relative[len(marker) :].split("/", 1)[0])
                                return [event_by_id.get(event_ids[index])]
                            except (IndexError, TypeError, ValueError):
                                return []
                    return [event_by_id.get(event_id) for event_id in event_ids]
                if resolution.get("state") == "none":
                    return [event_by_id.get(resolution.get("resolution_event_id"))]
                if resolution.get("state") == "not_yet_acquired":
                    return [event_by_id.get(resolution.get("as_of_event_id"))]
                return []

            def events_for_pointer(pointer: str) -> list[dict[str, Any] | None]:
                relative = pointer.split(f"/rows/{len(rows)-1}", 1)[-1]
                if relative == "/cl" or relative.startswith("/pb"):
                    return [level_event]
                if relative.startswith("/hp"):
                    return [event for event in current if event["advancement"]["calculation"]["outputs"].get("hp_after")]
                if relative.startswith("/resources"):
                    return [event for event in current if event["advancement"]["calculation"]["outputs"].get("resources_after")]
                if relative.startswith("/ability_score_effects/"):
                    try:
                        index = int(relative.split("/ability_score_effects/", 1)[1].split("/", 1)[0])
                        return [event_by_id.get(row["ability_score_effects"][index]["event_id"])]
                    except (IndexError, KeyError, TypeError, ValueError):
                        return []
                if relative == "/ability_score_effects" and not row["ability_score_effects"]:
                    return list(cumulative)
                if relative.startswith("/ability_scores") or relative.startswith("/ability_modifiers"):
                    return [latest_ability]

                scalar_map = {
                    "/background": state.get("background"),
                    "/background_detail": state.get("background"),
                    "/background_sphere": state.get("background_sphere"),
                    "/background_sphere_detail": state.get("background_sphere"),
                    "/background_talent": state.get("background_talent"),
                    "/background_talent_detail": state.get("background_talent"),
                    "/origin_insight": state.get("origin_insight"),
                    "/origin_insight_detail": state.get("origin_insight"),
                    "/sect_trial_sphere": state.get("sect_trial_sphere"),
                    "/sect_trial_sphere_detail": state.get("sect_trial_sphere"),
                    "/sect_trial_talent": state.get("sect_trial_talent"),
                    "/sect_trial_talent_detail": state.get("sect_trial_talent"),
                    "/ai_bootstrap_sphere": state.get("ai_bootstrap_sphere"),
                    "/ai_bootstrap_sphere_detail": state.get("ai_bootstrap_sphere"),
                    "/ai_bootstrap_talent": state.get("ai_bootstrap_talent"),
                    "/ai_bootstrap_talent_detail": state.get("ai_bootstrap_talent"),
                }
                for prefix, record_id in scalar_map.items():
                    if relative == prefix or relative.startswith(prefix + "/"):
                        return [latest_by_record.get(record_id)] if isinstance(record_id, str) else list(cumulative)

                collection_map = (
                    ("/paths", state["paths"]),
                    ("/path_details", row["path_details"]),
                    ("/subpaths", state["subpaths"]),
                    ("/cultivation_insights_after_level", state.get("cultivation_insights", [])),
                    ("/cultivation_insight_details", row["cultivation_insight_details"]),
                    ("/training_sources_after_level", state.get("training_sources", [])),
                    ("/training_source_details", row["training_source_details"]),
                    ("/known_spheres_after_level", state["known_spheres"]),
                    ("/known_sphere_details", row["known_sphere_details"]),
                    ("/known_talents_after_level", state["known_talents"]),
                    ("/known_talent_details", row["known_talent_details"]),
                    ("/recorded_arts_after_level", row["recorded_arts_after_level"]),
                    ("/equipment_after_level", state["equipment"]),
                )
                for prefix, values in collection_map:
                    if relative == prefix or relative.startswith(prefix + "/"):
                        return _collection_event(values, prefix, relative)

                resolution_map = (
                    ("/subpath_resolution", row["subpath_resolution"]),
                    ("/manuals_resolution", row["manuals_resolution"]),
                    ("/equipment_resolution", row["equipment_resolution"]),
                    ("/forged_techniques_resolution", row["forged_techniques_resolution"]),
                )
                for prefix, resolution in resolution_map:
                    if relative == prefix or relative.startswith(prefix + "/"):
                        return _resolution_events(resolution, prefix, relative)

                if relative.startswith("/method"):
                    method = row.get("method")
                    if isinstance(method, dict) and method.get("event_id"):
                        return [event_by_id.get(method["event_id"])]
                    if isinstance(method, dict) and method.get("resolution_event_id"):
                        return [event_by_id.get(method["resolution_event_id"])]
                    if isinstance(method, dict) and method.get("as_of_event_id"):
                        return [event_by_id.get(method["as_of_event_id"])]
                    return []
                if relative.startswith("/foundation"):
                    foundation = row.get("foundation")
                    if isinstance(foundation, dict) and foundation.get("resolution_event_id"):
                        return [event_by_id.get(foundation["resolution_event_id"])]
                    if isinstance(foundation, dict) and foundation.get("as_of_event_id"):
                        return [event_by_id.get(foundation["as_of_event_id"])]
                    if not isinstance(foundation, dict) or not foundation.get("record_id"):
                        return []
                    return [
                        event_by_id.get(foundation.get("stage_event_id")),
                        event_by_id.get(foundation.get("event_id")),
                        latest_by_record.get(foundation.get("expression_record_id")),
                        latest_by_record.get(foundation.get("record_id")),
                    ]
                if relative.startswith("/level_talent"):
                    # Capacity is from the level rule; selected records are from their own
                    # acquisition events. Both are directly causal to this ledger object.
                    return [level_event] + [event_by_id.get(item["event_id"]) for item in level_talent]
                if relative.startswith("/trained_choice_capacity"):
                    return [level_event] + [event for event in current if event["advancement"].get("training_transaction")]
                if relative.startswith("/training_transactions/"):
                    try:
                        index = int(relative.split("/training_transactions/", 1)[1].split("/", 1)[0])
                        return [transaction_by_attempt.get(training[index]["attempt_id"])]
                    except (IndexError, KeyError, TypeError, ValueError):
                        return []
                if relative == "/training_transactions" and not training:
                    return list(current)
                if relative.startswith("/new_sphere_entitlements/"):
                    try:
                        index = int(relative.split("/new_sphere_entitlements/", 1)[1].split("/", 1)[0])
                        entitlement = row["new_sphere_entitlements"][index]
                        return [event_by_id.get(entitlement.get("sphere_event_id")), event_by_id.get(entitlement.get("talent_event_id"))]
                    except (IndexError, KeyError, TypeError, ValueError):
                        return []
                if relative == "/new_sphere_entitlements" and not row["new_sphere_entitlements"]:
                    return list(cumulative)
                if relative.startswith("/forged_techniques_after_level"):
                    typed = next((event for event in reversed(cumulative) if event["advancement"]["kind"] == "typed_none" and event["advancement"]["details"].get("target") == "forged_techniques"), None)
                    if typed:
                        return [typed]
                    forged = state.get("forged_techniques")
                    if isinstance(forged, list):
                        return [latest_by_record.get(item if isinstance(item, str) else item.get("record_id")) for item in forged]
                    return [level_event]
                if relative.startswith("/level_acquisitions/"):
                    try:
                        kind = relative.split("/level_acquisitions/", 1)[1].split("/", 1)[0].replace("~1", "/").replace("~0", "~")
                    except (IndexError, ValueError):
                        return []
                    matching = [event for event in current if event["advancement"]["kind"] == kind]
                    return matching or list(current)
                if relative == "/level_acquisitions" and not row["level_acquisitions"]:
                    return list(current)
                if relative.startswith("/level_acquisition_events/"):
                    try:
                        index = int(relative.split("/level_acquisition_events/", 1)[1].split("/", 1)[0])
                        return [event_by_id.get(row["level_acquisition_events"][index]["event_id"])]
                    except (IndexError, KeyError, TypeError, ValueError):
                        return []
                if relative == "/level_acquisition_events":
                    return list(current)
                if relative.startswith("/legality"):
                    return list(current)
                if relative == "/row_hash":
                    return list(cumulative)
                return []

            for pointer in _leaf_pointers(row, f"/rows/{len(rows)-1}"):
                entry = proof(events_for_pointer(pointer))
                if entry is not None:
                    provenance[pointer] = entry
        return state, rows, provenance

    def _ledger(self, project: dict[str, Any], events: list[dict[str, Any]], state: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        ledger = {"schema_version": LEDGER_V2, "project_id": project["project_id"], "project_revision": project["revision"], "content_lock_hash": project["content_lock"]["lock_hash"], "event_head_hash": project["event_stream"].get("head_hash"), "target_cl": state["current_cl"], "rows": rows, "final_state_hash": sha256_json(state), "generated_at_rule": "deterministic-no-wall-clock"}
        self.registry.validate(ledger)
        return ledger

    def _markdown(self, ledger: dict[str, Any]) -> str:
        def none_resolution(value: dict[str, Any]) -> str:
            event_id = value.get("resolution_event_id") or value.get("as_of_event_id")
            event_label = f"; causal event `{event_id}`" if event_id else ""
            return f"{value.get('reason_code', 'none')} — {value.get('reason', 'No current acquisition exists.')}{event_label}"

        def state_resolution(value: dict[str, Any]) -> str:
            if value.get("state") in {"none", "not_yet_acquired"}:
                return none_resolution(value)
            fields = [f"state **{value.get('state', 'active')}**"]
            for key, label in (
                ("record_id", "record"),
                ("expression_record_id", "expression"),
                ("path_id", "Path"),
                ("stage", "stage"),
                ("event_id", "acquisition/activation event"),
                ("stage_event_id", "stage event"),
            ):
                if value.get(key) is not None:
                    fields.append(f"{label} `{value[key]}`")
            return "; ".join(fields)

        def record_resolution(value: dict[str, Any]) -> str:
            if value.get("state") in {"none", "not_yet_acquired"}:
                return none_resolution(value)
            sources = ", ".join(f"`{record_id}`" for record_id in value["source_record_ids"])
            return (
                f"**{value['display_name']}** [`{value['record_id']}`]; acquired by "
                f"`{value['acquisition_kind']}` event `{value['acquisition_event_id']}` through "
                f"`{value['legal_channel']}`; source records {sources}"
            )

        lines = [
            "# Tianxia Leveling Ledger — Rules-Causal HF1",
            "",
            f"Project: `{ledger['project_id']}`",
            f"Project revision: **{ledger['project_revision']}**",
            f"Content lock: `{ledger['content_lock_hash']}`",
            f"Canonical event head: `{ledger['event_head_hash']}`",
            f"Target CL: **{ledger['target_cl']}**",
            f"Final state hash: `{ledger['final_state_hash']}`",
            "",
        ]
        for row in ledger["rows"]:
            abilities = "; ".join(
                f"{ability} **{row['ability_scores'][ability]}** ({row['ability_modifiers'][ability]:+d})"
                for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
            )
            lines.extend(
                [
                    f"## CL {row['cl']}",
                    "",
                    "### Ability Scores & Modifiers",
                    "",
                    f"- {abilities}",
                    "",
                    "### Ability Choices Applied This CL",
                    "",
                ]
            )
            if row["ability_score_effects"]:
                for effect in row["ability_score_effects"]:
                    increments = ", ".join(f"{ability} {amount:+d}" for ability, amount in effect["selected_increments"].items()) or "starting score establishment"
                    before = ", ".join(f"{ability} {score}" for ability, score in effect["scores_before"].items()) if effect["scores_before"] else "no prior score state"
                    after = ", ".join(f"{ability} {score}" for ability, score in effect["scores_after"].items())
                    lines.append(
                        f"- **{effect['display_name']}** [`{effect['record_id']}`]: {increments}; {before} → {after}; event `{effect['event_id']}` via `{effect['legal_channel']}`; retroactive CON HP adjustment {effect['hp_retroactive_con_adjustment']:+d}"
                    )
            else:
                lines.append("- No ability-score selection or adjustment event occurs at this CL; scores carry forward unchanged.")
            lines.extend(
                [
                    "",
                    "### Proficiency Bonus",
                    "",
                    f"- PB: **+{row['pb']}**",
                    "",
                    "### HP",
                    "",
                    f"- Path level-formula gain: **{row['hp']['level_formula_gain']:+d}**",
                    f"- Retroactive CON adjustment applied this CL: **{row['hp']['retroactive_con_adjustment']:+d}** ({row['hp']['retroactive_con_per_level']:+d} across {row['hp']['retroactive_con_affected_levels']} affected levels)",
                    f"- Total maximum-HP change this CL: **{row['hp']['gain']:+d}**",
                    f"- Arithmetic: `{row['hp']['arithmetic']}`",
                    f"- Maximum after level: **{row['hp']['total']}**",
                    f"- Formula: `{row['hp']['formula_id']}` — {row['hp']['formula_expression']}",
                    f"- Inputs: CL {row['hp']['formula_inputs']['cl']}; PB +{row['hp']['formula_inputs']['pb']}; CON {row['hp']['formula_inputs']['con_score']} ({row['hp']['formula_inputs']['con_modifier']:+d})",
                    f"- Adjustment event IDs: {', '.join(f'`{event_id}`' for event_id in row['hp']['adjustment_event_ids']) or 'none; no retroactive CON adjustment'}",
                    "- Retroactive CON adjustment inputs:",
                ]
            )
            if row["hp"]["retroactive_con_adjustment_details"]:
                for detail in row["hp"]["retroactive_con_adjustment_details"]:
                    lines.append(
                        f"  - Event `{detail['event_id']}`: CON {detail['con_score_before']} ({detail['con_modifier_before']:+d}) → "
                        f"{detail['con_score_after']} ({detail['con_modifier_after']:+d}); modifier delta {detail['modifier_delta']:+d} × "
                        f"{detail['affected_levels']} affected levels = {detail['total_adjustment']:+d} HP"
                    )
            else:
                lines.append("  - None; no CON modifier change occurred at this CL.")
            lines.append("- Authority:")
            for component in row["hp"]["authority_components"]:
                lines.append(
                    f"  - {component['role']}: `{component['record_id']}`; formula `{component['formula_id']}`; value {component['value']}; source `{component['source_anchor']}`"
                )

            lines.extend(["", "### Resources", ""])
            for resource_id, resource in row["resources"].items():
                lines.extend(
                    [
                        f"#### {resource_id}",
                        "",
                        f"- Base formula: `{resource['formula_id']}` — {resource['formula_expression']}",
                        f"- Inputs: CL {resource['formula_inputs']['cl']}; PB +{resource['formula_inputs']['pb']}; key ability {resource['formula_inputs']['key_ability']} {resource['formula_inputs']['key_ability_score']} ({resource['formula_inputs']['key_ability_modifier']:+d})",
                        f"- Base: **{resource['base_value']}**",
                        f"- Method delta: **{resource['method_delta']:+d}**",
                        f"- Foundation delta: **{resource['foundation_delta']:+d}**",
                        f"- Equipment delta: **{resource['equipment_delta']:+d}**",
                        f"- Maximum: **{resource['maximum']}**",
                        f"- Maximum arithmetic: `{resource['maximum_arithmetic']}`",
                        f"- Current: **{resource['current_before']} → {resource['current_after']}**",
                        "- Modifier derivations:",
                    ]
                )
                for modifier in resource["modifier_details"]:
                    lines.append(
                        f"  - {modifier['role']}: {modifier['value']:+d} from {record_resolution(modifier['authority'])}; formula `{modifier['formula_id']}` — {modifier['formula_expression']}"
                    )
                lines.extend(
                    [
                        "- Authority:",
                    ]
                )
                for component in resource["authority_components"]:
                    lines.append(
                        f"  - {component['role']}: `{component['record_id']}`; formula `{component['formula_id']}`; value {component['value']}; source `{component['source_anchor']}`"
                    )

            level_talent = row["level_talent"]
            lines.extend(
                [
                    "",
                    "### Level Talent",
                    "",
                    f"- Capacity / used: **{level_talent['used']}/{level_talent['capacity']}**",
                    f"- Source rule: `{level_talent['source_rule_id']}`",
                    "",
                    "### Trained Choices & Attempts",
                    "",
                    f"- Successful capacity used: **{row['trained_choice_capacity']['successful_used']}/{row['trained_choice_capacity']['capacity']}**",
                    f"- Remaining successful choices: **{row['trained_choice_capacity']['remaining']}**",
                    f"- Failed attempts: **{row['trained_choice_capacity']['failed_attempts']}** (failures consume no successful-choice capacity)",
                    f"- Capacity source rule: `{row['trained_choice_capacity']['source_rule_id']}`",
                ]
            )
            for entry in level_talent["entries"]:
                lines.append(f"- Selected talent: {record_resolution(entry)}")
            if row["training_transactions"]:
                for t in row["training_transactions"]:
                    lines.append(
                        f"- `{t['attempt_id']}`: {t['training_type']} → **{t['result']}**; target `{t['target_record_id']}`; source `{t['training_source_record_id']}` via event `{t['training_source_access_event_id']}`; days {t['computed_training_days']}; DC {t['computed_dc']}; check {t['computed_check_total']}; slot cost {t['slot_cost']}; acquisition event `{t['acquisition_event_id']}`"
                    )
            else:
                lines.append("- No training-attempt event occurs at this CL; successful-choice use is zero.")

            lines.extend(["", "### New-Sphere Bonus Entitlements", ""])
            if row["new_sphere_entitlements"]:
                for entitlement in row["new_sphere_entitlements"]:
                    lines.append(
                        f"- Sphere `{entitlement['sphere_record_id']}` from event `{entitlement['sphere_event_id']}`; entitlement `{entitlement['entitlement_id']}`; consumed **{str(entitlement['consumed']).lower()}** by talent `{entitlement['talent_record_id']}` via event `{entitlement['talent_event_id']}`"
                    )
            else:
                lines.append("- None generated at this CL because no successful new-Sphere training event created an entitlement.")

            lines.extend(
                [
                    "",
                    "### Background, Origin, and Sect Trial",
                    "",
                    f"- Background: {record_resolution(row['background_detail'])}",
                    f"- Background Sphere: {record_resolution(row['background_sphere_detail'])}",
                    f"- Background Talent: {record_resolution(row['background_talent_detail'])}",
                    f"- Origin Insight: {record_resolution(row['origin_insight_detail'])}",
                    f"- Sect-trial Sphere: {record_resolution(row['sect_trial_sphere_detail'])}",
                    f"- Sect-trial level talent: {record_resolution(row['sect_trial_talent_detail'])}",
                    f"- AI-bootstrap Sphere: {record_resolution(row['ai_bootstrap_sphere_detail'])}",
                    f"- AI-bootstrap free talent: {record_resolution(row['ai_bootstrap_talent_detail'])}",
                    "",
                    "### Path & Subpath",
                    "",
                ]
            )
            for entry in row["path_details"]:
                lines.append(f"- Path: {record_resolution(entry)}")
            if row["subpath_resolution"]["state"] == "present":
                for entry in row["subpath_resolution"]["entries"]:
                    lines.append(f"- Subpath: {record_resolution(entry)}")
            else:
                lines.append(f"- Subpath: {none_resolution(row['subpath_resolution'])}")

            method_detail = row["method_detail"]
            if method_detail.get("state") == "active":
                method_text = (
                    record_resolution(method_detail["selection"])
                    + f"; active via event `{method_detail['activation_event_id']}`"
                )
            elif method_detail.get("state") == "acquired":
                method_text = (
                    record_resolution(method_detail["selection"])
                    + "; acquired but not active; no activation event exists and its resource modifier is not applied"
                )
            else:
                method_text = none_resolution(method_detail)

            foundation_detail = row["foundation_detail"]
            if foundation_detail.get("state") == "active":
                foundation_text = (
                    record_resolution(foundation_detail["selection"])
                    + f"; expression **{foundation_detail['expression']['display_name']}** "
                    + f"[`{foundation_detail['expression']['record_id']}`]; "
                    + f"stage **{foundation_detail['stage']}** via event `{foundation_detail['stage_event_id']}`"
                )
            elif foundation_detail.get("state") == "expressed":
                foundation_text = (
                    record_resolution(foundation_detail["selection"])
                    + f"; expressed as **{foundation_detail['expression']['display_name']}** "
                    + f"[`{foundation_detail['expression']['record_id']}`] via event "
                    + f"`{foundation_detail['expression_event_id']}` for path "
                    + f"**{foundation_detail['path']['display_name']}** "
                    + f"[`{foundation_detail['path']['record_id']}`]; no stage event exists and its resource modifier is not applied"
                )
            elif foundation_detail.get("state") == "acquired":
                foundation_text = (
                    record_resolution(foundation_detail["selection"])
                    + "; acquired but not expressed; no expression or stage event exists and its resource modifier is not applied"
                )
            else:
                foundation_text = none_resolution(foundation_detail)

            lines.extend(
                [
                    "",
                    "### Cultivation Method & Foundation",
                    "",
                    f"- Method: {method_text}",
                    f"- Foundation: {foundation_text}",
                    "",
                    "### Cultivation Insights",
                    "",
                ]
            )
            if row["cultivation_insight_details"]:
                lines.extend(f"- {record_resolution(entry)}" for entry in row["cultivation_insight_details"])
            else:
                lines.append("- No Cultivation Insight has been acquired through this CL; the event history proves the empty cumulative state.")
            lines.extend(
                [
                    "",
                    "### Training / Manual Access",
                    "",
                ]
            )
            if row["training_source_details"]:
                lines.extend(f"- {record_resolution(entry)}" for entry in row["training_source_details"])
            else:
                lines.append("- No training or Manual source-access event exists through this CL.")
            lines.extend(
                [
                    "",
                    "### Known Spheres",
                    "",
                ]
            )
            lines.extend(f"- {record_resolution(entry)}" for entry in row["known_sphere_details"])
            lines.extend(["", "### Known Talents", ""])
            lines.extend(f"- {record_resolution(entry)}" for entry in row["known_talent_details"])

            lines.extend(["", "### Martial Manuals / Recorded Arts", ""])
            if row["manuals_resolution"]["state"] == "present":
                for entry in row["manuals_resolution"]["entries"]:
                    execution = entry["execution"]
                    lines.extend(
                        [
                            f"#### {entry['display_name']}",
                            "",
                            f"- DM-facing line: **{entry['dm_facing_line']}**",
                            f"- Grammar fields: Sphere(s) **{', '.join(entry['associated_sphere_names'])}**; technique **{entry['technique_name']}**; reproduced component(s) **{', '.join(entry['reproduced_component_names'])}**; published Difficulty **{entry['difficulty']}**",
                            f"- Recorded Art record: `{entry['record_id']}`",
                            f"- Parent manual: **{entry['parent_manual_name']}** [`{entry['parent_manual_record_id']}`]",
                            f"- Computed learning DC for this acquisition attempt: **{entry['computed_learning_dc']}**",
                            f"- Acquisition event: `{entry['acquisition_event_id']}`",
                            f"- Training-source access: `{entry['training_source_record_id']}` via event `{entry['training_source_access_event_id']}`",
                            f"- Linked action: `{entry['linked_action_id']}`",
                            f"- Timing: {execution['timing']}",
                            f"- Cost: {execution['cost']}",
                            f"- Range: {execution['range']}",
                            f"- Target: {execution['target']}",
                            f"- Roll / Save / Check: {execution['roll_save_check']}",
                            f"- Effect: {execution['effect']}",
                            f"- Failure: {execution['failure']}",
                            f"- Duration: {execution['duration']}",
                            f"- Limit: {execution['limit']}",
                            f"- Counterplay: {execution['counterplay']}",
                            f"- Fixed-expression warning: {entry['fixed_expression_warning']}",
                            "",
                        ]
                    )
            else:
                lines.append(f"- {none_resolution(row['manuals_resolution'])}")

            lines.extend(["", "### Forged Techniques", ""])
            lines.append(f"- {none_resolution(row['forged_techniques_resolution'])}")

            lines.extend(["", "### Equipment", ""])
            if row["equipment_resolution"]["state"] == "present":
                for entry in row["equipment_resolution"]["entries"]:
                    lines.append(f"- {record_resolution(entry)}")
            else:
                lines.append(f"- {none_resolution(row['equipment_resolution'])}")

            lines.extend(["", "### Acquisitions at This CL", ""])
            for acquisition in row["level_acquisition_events"]:
                lines.append(
                    f"- `{acquisition['kind']}`: **{acquisition['display_name']}** [`{acquisition['record_id']}`] via event `{acquisition['event_id']}` and channel `{acquisition['legal_channel']}`; source records {', '.join(f'`{record_id}`' for record_id in acquisition['source_record_ids'])}"
                )

            lines.extend(
                [
                    "",
                    "### Legality / Validation",
                    "",
                    f"- Status: **{row['legality']['status']}**",
                    f"- Blockers: **{row['legality']['blocker_count']}**",
                    f"- Canonical events applied at this CL: **{row['legality']['event_count']}**",
                    f"- Row hash: `{row['row_hash']}`",
                    "",
                    "### Source / Provenance Event References",
                    "",
                ]
            )
            lines.extend(
                f"- `{acquisition['event_id']}` proves `{acquisition['kind']}` for `{acquisition['record_id']}`"
                for acquisition in row["level_acquisition_events"]
            )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _orphaned(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        ids = set(state["known_spheres"] + state["known_talents"] + state["paths"] + state["subpaths"] + state["cultivation_insights"] + state["equipment"] + state["training_sources"])
        ids |= {x["record_id"] for x in state["recorded_arts"]}
        for value in [state.get("background"), state.get("background_sphere"), state.get("background_talent"), state.get("origin_insight"), state.get("sect_trial_sphere"), state.get("sect_trial_talent"), state.get("ai_bootstrap_sphere"), state.get("ai_bootstrap_talent")]:
            if isinstance(value, str): ids.add(value)
        for value in [state.get("method"), state.get("foundation")]:
            if isinstance(value, dict):
                for key in ("record_id", "expression_record_id"):
                    if value.get(key): ids.add(value[key])
        return [{"record_id": rid, "code": "FINAL_STATE_ELEMENT_WITHOUT_CAUSAL_EVENT"} for rid in sorted(ids) if rid not in state["record_event_ids"]]

    def _persisted_event_integrity(self, conn, project_id: str) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT sequence_no,event_hash,previous_event_hash,event_json,canonical_schema_version FROM events WHERE project_id=? ORDER BY sequence_no",
            (project_id,),
        ).fetchall()
        blockers: list[dict[str, Any]] = []
        parsed: list[dict[str, Any]] = []
        previous_hash = ZERO_HASH
        expected_sequence = 1
        raw_head = ZERO_HASH
        for row in rows:
            raw_head = row["event_hash"]
            try:
                event = json.loads(row["event_json"])
            except Exception as exc:
                blockers.append(_block(
                    "PERSISTED_EVENT_JSON_MALFORMED",
                    f"/events/{row['sequence_no']}",
                    "A persisted event is not valid JSON; mechanical reduction and canonical artifact generation are forbidden.",
                    sequence=row["sequence_no"], error=str(exc),
                ))
                previous_hash = row["event_hash"]
                expected_sequence += 1
                continue
            if canonical_json(event) != row["event_json"]:
                blockers.append(_block(
                    "PERSISTED_EVENT_CANONICAL_BYTES_CORRUPT",
                    f"/events/{row['sequence_no']}",
                    "Persisted event JSON is not the exact canonical byte representation.",
                    sequence=row["sequence_no"], stored_sha256=sha256_bytes(row["event_json"].encode("utf-8")),
                    canonical_sha256=sha256_bytes(canonical_json(event).encode("utf-8")),
                ))
            report = self.registry.report(event)
            if row["canonical_schema_version"] != event.get("schema_version"):
                blockers.append(_block(
                    "PERSISTED_EVENT_SCHEMA_BINDING_MISMATCH",
                    f"/events/{row['sequence_no']}/schema_version",
                    "The persisted schema registration does not match the embedded event schema.",
                    sequence=row["sequence_no"], stored=row["canonical_schema_version"], embedded=event.get("schema_version"),
                ))
            if not report["valid"]:
                blockers.append(_block(
                    "PERSISTED_EVENT_SCHEMA_INVALID",
                    f"/events/{row['sequence_no']}",
                    "A persisted event fails its pinned schema; mechanical reduction and canonical artifact generation are forbidden.",
                    sequence=row["sequence_no"], diagnostics=report["diagnostics"],
                ))
            if int(row["sequence_no"]) != expected_sequence or event.get("sequence") != expected_sequence:
                blockers.append(_block(
                    "EVENT_SEQUENCE_INVALID",
                    f"/events/{row['sequence_no']}",
                    "The persisted event sequence is not contiguous and exact.",
                    expected=expected_sequence, stored=row["sequence_no"], embedded=event.get("sequence"),
                ))
            if row["previous_event_hash"] != previous_hash or event.get("previous_event_hash") != previous_hash:
                blockers.append(_block(
                    "EVENT_CHAIN_TAMPERED",
                    f"/events/{row['sequence_no']}",
                    "The persisted previous-event binding does not match the chain head.",
                    expected=previous_hash, stored=row["previous_event_hash"], embedded=event.get("previous_event_hash"),
                ))
            try:
                computed = canonical_event_hash(event)
            except Exception as exc:
                computed = None
                blockers.append(_block(
                    "PERSISTED_EVENT_HASH_UNCOMPUTABLE",
                    f"/events/{row['sequence_no']}",
                    "The canonical event hash cannot be recomputed from the persisted event.",
                    error=str(exc),
                ))
            if computed is not None and (computed != row["event_hash"] or computed != event.get("event_hash")):
                blockers.append(_block(
                    "EVENT_HASH_MISMATCH",
                    f"/events/{row['sequence_no']}",
                    "The persisted event bytes do not match their stored canonical hash.",
                    computed=computed, stored=row["event_hash"], embedded=event.get("event_hash"),
                ))
            parsed.append(event)
            previous_hash = row["event_hash"]
            expected_sequence += 1

        project_row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if project_row:
            try:
                project_document = json.loads(project_row["project_json"])
                stream = project_document.get("event_stream") or {}
                expected_count = int(stream.get("count", 0))
                expected_head = stream.get("head_hash") or ZERO_HASH
                if expected_count != len(rows):
                    blockers.append(_block(
                        "EVENT_CHAIN_HEAD_COUNT_MISMATCH",
                        "/project/event_stream/count",
                        "The project event-stream count does not match the persisted event set.",
                        project_event_count=expected_count, persisted_event_count=len(rows),
                    ))
                if expected_head != raw_head:
                    blockers.append(_block(
                        "EVENT_CHAIN_HEAD_MISMATCH",
                        "/project/event_stream/head_hash",
                        "The project event-stream head does not match the persisted event chain head.",
                        project_chain_head=expected_head, persisted_chain_head=raw_head,
                    ))
            except Exception as exc:
                blockers.append(_block(
                    "PROJECT_EVENT_STREAM_BINDING_INVALID",
                    "/project/event_stream",
                    "The project event-stream binding cannot be decoded for hostile audit verification.",
                    error_type=type(exc).__name__,
                ))

        # R4: SQLite self-consistency is insufficient.  Every committed Stage 2
        # event set must be covered by an external-keyed terminal receipt.
        receipts = conn.execute(
            "SELECT * FROM stage2_commit_receipts WHERE project_id=? AND status='committed' ORDER BY final_revision,completed_at",
            (project_id,),
        ).fetchall()
        anchored_event_ids: list[str] = []
        terminal_projections: list[dict[str, Any]] = []
        for receipt in receipts:
            try:
                terminal = self._verify_terminal_receipt(conn, receipt)
                terminal_projections.append(terminal)
                anchored_event_ids.extend(item["event_id"] for item in terminal.get("ordered_events", []))
            except FoundryError as exc:
                blockers.append(_block(
                    "TERMINAL_COMMIT_ANCHOR_INVALID",
                    f"/commit_receipts/{receipt['commit_id']}",
                    "A committed event set lacks a valid external keyed terminal anchor.",
                    error=exc.to_dict(),
                ))
        persisted_v3_ids = [event.get("event_id") for event in parsed if event.get("schema_version") == EVENT_V3]
        if persisted_v3_ids and not receipts:
            blockers.append(_block(
                "TERMINAL_COMMIT_ANCHOR_MISSING",
                "/commit_receipts",
                "Committed Stage 2 events have no external keyed terminal receipt.",
                event_ids=persisted_v3_ids,
            ))
        if sorted(anchored_event_ids) != sorted(persisted_v3_ids):
            blockers.append(_block(
                "TERMINAL_COMMIT_EVENT_COVERAGE_MISMATCH",
                "/commit_receipts",
                "The external keyed terminal receipts do not cover the exact persisted Stage 2 event set.",
                persisted_event_ids=persisted_v3_ids,
                anchored_event_ids=anchored_event_ids,
            ))
        if terminal_projections:
            terminal = terminal_projections[-1]
            if terminal.get("event_chain_head") != raw_head or int(terminal.get("event_count", -1)) != len(rows):
                blockers.append(_block(
                    "TERMINAL_COMMIT_CHAIN_HEAD_MISMATCH",
                    "/commit_receipts/latest",
                    "The latest external keyed terminal receipt does not bind the current complete event stream.",
                    receipt_chain_head=terminal.get("event_chain_head"), persisted_chain_head=raw_head,
                    receipt_event_count=terminal.get("event_count"), persisted_event_count=len(rows),
                ))

        if blockers:
            blocked_state_hash = sha256_json({
                "project_id": project_id,
                "trust_state": "BLOCKED_BEFORE_MECHANICAL_REDUCTION",
                "event_chain_head": raw_head,
                "blocker_hashes": [sha256_json(blocker) for blocker in blockers],
            })
            return {
                "valid": False,
                "blockers": blockers,
                "events": [],
                "v3_events": [],
                "event_chain_head": raw_head,
                "state_hash": blocked_state_hash,
                "replay": None,
            }

        replay = self.projects._replay_events(conn, project_id, verify_chain=False)
        for error in replay.get("chain_errors", []):
            blockers.append(_block(
                error.get("code", "EVENT_CHAIN_TAMPERED"),
                f"/events/{error.get('sequence', '')}",
                "Event replay integrity failed before canonical projection.",
                **error,
            ))
        if blockers:
            blocked_state_hash = sha256_json({
                "project_id": project_id,
                "trust_state": "BLOCKED_DURING_REPLAY_VERIFICATION",
                "event_chain_head": replay.get("latest_event_hash") or raw_head,
                "blocker_hashes": [sha256_json(blocker) for blocker in blockers],
            })
            return {
                "valid": False,
                "blockers": blockers,
                "events": parsed,
                "v3_events": [],
                "event_chain_head": replay.get("latest_event_hash") or raw_head,
                "state_hash": blocked_state_hash,
                "replay": replay,
            }
        return {
            "valid": True,
            "blockers": [],
            "events": parsed,
            "v3_events": [event for event in parsed if event.get("schema_version") == EVENT_V3],
            "event_chain_head": replay.get("latest_event_hash") or ZERO_HASH,
            "state_hash": replay["state_hash"],
            "replay": replay,
        }

    @staticmethod
    def _artifact_set_hash(artifacts: dict[str, bytes]) -> str:
        return sha256_json([
            {"artifact_name": name, "artifact_hash": sha256_bytes(data), "size_bytes": len(data)}
            for name, data in sorted(artifacts.items())
        ])

    def _verify_rebuild_receipt(self, conn, receipt_row) -> dict[str, Any]:
        receipt = dict(receipt_row)
        try:
            projection = json.loads(receipt["rebuild_projection_json"])
        except Exception as exc:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_CORRUPT", "The keyed rebuild receipt projection is malformed.", details={"error": type(exc).__name__}, status_code=409) from exc
        projection_json = canonical_json(projection)
        if projection_json != receipt["rebuild_projection_json"] or sha256_json(projection) != receipt["rebuild_projection_hash"]:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_CORRUPT", "The rebuild receipt canonical bytes or projection hash are invalid.", status_code=409)
        envelope = {
            "integrity_version": receipt["integrity_version"], "algorithm": "HMAC-SHA-256",
            "key_id": receipt["integrity_key_id"], "domain": receipt["integrity_domain"],
            "projection_hash": receipt["rebuild_projection_hash"], "mac": receipt["integrity_mac"],
        }
        self.integrity.verify(REBUILD_RECEIPT_DOMAIN, projection, envelope)
        fields = {
            "rebuild_receipt_id": receipt["rebuild_receipt_id"], "rebuild_id": receipt["rebuild_id"],
            "project_id": receipt["project_id"], "project_revision": receipt["project_revision"],
            "status": receipt["status"], "terminal_commit_id": receipt["terminal_commit_id"],
            "terminal_projection_hash": receipt["terminal_projection_hash"],
            "event_chain_head": receipt["event_chain_head"], "mechanical_state_hash": receipt["mechanical_state_hash"],
            "artifact_set_hash": receipt["artifact_set_hash"], "blocker_report_hash": receipt["blocker_report_hash"],
        }
        projected = {key: projection.get(key) for key in fields}
        if projected != fields:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_CORRUPT", "Rebuild receipt columns differ from the keyed projection.", details={"stored": fields, "projection": projected}, status_code=409)
        if canonical_json(projection.get("ordered_artifacts") or []) != receipt["ordered_artifacts_json"]:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_ARTIFACT_SET_MISMATCH", "The ordered artifact set differs from its keyed receipt.", status_code=409)
        return projection

    def rebuild(self, project_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            _project_row, project = self._project_row(conn, project_id)
            integrity = self._persisted_event_integrity(conn, project_id)
            events: list[dict[str, Any]] = []
            state = _state(project_id)
            rows: list[dict[str, Any]] = []
            entries: dict[str, Any] = {}
            blockers = list(integrity["blockers"])
            ledger = None
            orphaned: list[dict[str, Any]] = []

            if integrity["valid"]:
                events = integrity["v3_events"]
                if events:
                    state, rows, entries = self._rows(events, project_id)
                    blockers.extend(self._completion_blockers(state, state["current_cl"], events, project))
                else:
                    blockers.append(_block("NO_RULES_CAUSAL_STAGE2_EVENTS", "/events", "No HF1 v3 advancement events exist for this project."))
                orphaned = self._orphaned(state)
                blockers.extend(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", "/final_state", "A final-state element lacks a causal event.", **item) for item in orphaned)
                if rows and not blockers:
                    try:
                        ledger = self._ledger(project, events, state, rows)
                    except Exception as exc:
                        blockers.append(_block("LEVELING_LEDGER_SCHEMA_INVALID", "/ledger", "The deterministic ledger failed its v2 schema.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})()))

            required_provenance_pointers = sorted(
                pointer
                for row_index, row in enumerate(rows)
                for pointer in _leaf_pointers(row, f"/rows/{row_index}")
            ) if not blockers else []
            required_provenance_set = set(required_provenance_pointers)
            proven_provenance_set = set(entries) & required_provenance_set
            missing_provenance = sorted(required_provenance_set - proven_provenance_set)
            unexpected_provenance = sorted(set(entries) - required_provenance_set) if not blockers else []
            for pointer in missing_provenance:
                blockers.append(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", pointer, "A projected ledger leaf has no exact causal event/source proof; unrelated level-event fallback is forbidden.", cause="CAUSAL_EVENT_OR_RULE_SOURCE_MISSING"))
            for pointer in unexpected_provenance:
                blockers.append(_block("PROVENANCE_POINTER_NOT_IN_LEDGER", pointer, "A provenance entry does not correspond to a projected ledger leaf."))

            status_name = "BLOCKED" if blockers else "READY"
            blocker_report = {
                "schema_version": "TianxiaFoundry.Stage2BlockerReport.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "blocked": bool(blockers),
                "blockers": blockers,
            }
            self.registry.validate(blocker_report)
            blocker_report_hash = sha256_json(blocker_report)

            provenance = {
                "schema_version": "TianxiaFoundry.Stage2FieldProvenanceMap.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "entries": entries,
                "event_count": len(events),
                "coverage": {
                    "required": len(required_provenance_pointers),
                    "proven": len(proven_provenance_set),
                    "unproven": len(missing_provenance),
                },
            }
            if status_name == "READY":
                self.registry.validate(provenance)

            event_state_hash = sha256_json(state) if status_name == "READY" else integrity["state_hash"]
            ledger_state_hash = ledger["final_state_hash"] if ledger else event_state_hash
            reconciliation = None
            quarantine_diagnostics = None
            if status_name == "READY":
                reconciliation = {
                    "schema_version": "TianxiaFoundry.Stage2ReconciliationReport.v1",
                    "project_id": project_id,
                    "project_revision": project["revision"],
                    "valid": event_state_hash == ledger_state_hash,
                    "event_state_hash": event_state_hash,
                    "ledger_state_hash": ledger_state_hash,
                    "orphaned_final_elements": orphaned,
                    "mismatches": [] if event_state_hash == ledger_state_hash else [{"code": "FINAL_STATE_HASH_MISMATCH"}],
                }
                self.registry.validate(reconciliation)
            else:
                quarantine_diagnostics = {
                    "namespace": "quarantine",
                    "canonical": False,
                    "project_id": project_id,
                    "project_revision": project["revision"],
                    "event_chain_head": integrity["event_chain_head"],
                    "diagnostic_state_hash": event_state_hash,
                    "blocker_report_hash": blocker_report_hash,
                }

            if status_name == "READY":
                assert ledger is not None
                artifacts: dict[str, bytes] = {
                    "Stage2_Blocker_Report.json": canonical_json(blocker_report).encode(),
                    "Stage2_Final_State_Reconciliation.json": canonical_json(reconciliation).encode(),
                    "Stage2_Field_Provenance_Map.json": canonical_json(provenance).encode(),
                    "Leveling_Ledger.json": canonical_json(ledger).encode(),
                    "Leveling_Ledger.md": self._markdown(ledger).encode(),
                }
                trust_status = "READY"
                namespace = "canonical"
            else:
                artifacts = {"Quarantine_Stage2_Blocker_Report.json": canonical_json(blocker_report).encode()}
                trust_status = "QUARANTINED"
                namespace = "quarantine"

            artifact_set_hash = self._artifact_set_hash(artifacts)
            trust_set = {
                "schema_version": "TianxiaFoundry.Stage2ArtifactTrustSet.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "status": status_name,
                "namespace": namespace,
                "event_chain_head": integrity["event_chain_head"],
                "state_hash": event_state_hash,
                "artifact_set_hash": artifact_set_hash,
                "artifact_names": sorted(artifacts),
                "blocker_report_hash": blocker_report_hash,
            }
            trust_metadata_hash = sha256_json(trust_set)
            rebuild_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2-hf2-rebuild:{trust_metadata_hash}"))
            terminal_row = conn.execute(
                "SELECT * FROM stage2_commit_receipts WHERE project_id=? AND status='committed' ORDER BY final_revision DESC,completed_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            terminal_commit_id = terminal_row["commit_id"] if terminal_row else None
            terminal_projection_hash = terminal_row["terminal_projection_hash"] if terminal_row else None
            if status_name == "READY":
                if not terminal_row:
                    raise FoundryError("STAGE2_TERMINAL_RECEIPT_MISSING", "READY artifacts require an external keyed terminal commit receipt.", status_code=409)
                self._verify_terminal_receipt(conn, terminal_row)
            ordered_artifacts = [
                {
                    "artifact_name": name,
                    "artifact_hash": sha256_bytes(data),
                    "size_bytes": len(data),
                    "media_type": "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8",
                    "trust_status": trust_status,
                    "namespace": namespace,
                }
                for name, data in sorted(artifacts.items())
            ]
            existing_rebuild_receipt = conn.execute(
                "SELECT * FROM stage2_rebuild_receipts WHERE rebuild_id=? ORDER BY created_at LIMIT 1",
                (rebuild_id,),
            ).fetchone()
            # Rebuilding the same immutable trust basis must reuse the original
            # keyed receipt timestamp.  Generating a new timestamp would create
            # a new receipt ID while the deterministic rebuild_id uniqueness
            # constraint retains only the first receipt, leaving active status
            # pointed at a non-existent receipt.
            created_at = existing_rebuild_receipt["created_at"] if existing_rebuild_receipt else utcnow()
            preliminary_projection = {
                "schema_version": "TianxiaFoundry.Stage2RebuildReceipt.v1",
                "rebuild_receipt_id": "PENDING",
                "rebuild_id": rebuild_id,
                "project_id": project_id,
                "project_revision": project["revision"],
                "status": status_name,
                "terminal_commit_id": terminal_commit_id,
                "terminal_projection_hash": terminal_projection_hash,
                "event_chain_head": integrity["event_chain_head"],
                "mechanical_state_hash": event_state_hash,
                "artifact_set_hash": artifact_set_hash,
                "ordered_artifacts": ordered_artifacts,
                "blocker_report_hash": blocker_report_hash,
                "trust_metadata_hash": trust_metadata_hash,
                "created_at": created_at,
            }
            receipt_seed_hash = sha256_json(preliminary_projection)
            rebuild_receipt_id = "stage2.rebuild.receipt." + receipt_seed_hash
            rebuild_projection = {**preliminary_projection, "rebuild_receipt_id": rebuild_receipt_id}
            rebuild_projection_json = canonical_json(rebuild_projection)
            rebuild_projection_hash = sha256_json(rebuild_projection)
            rebuild_envelope = self.integrity.sign(REBUILD_RECEIPT_DOMAIN, rebuild_projection)
            if existing_rebuild_receipt and (
                existing_rebuild_receipt["rebuild_receipt_id"] != rebuild_receipt_id
                or existing_rebuild_receipt["rebuild_projection_hash"] != rebuild_projection_hash
            ):
                raise FoundryError(
                    "STAGE2_REBUILD_RECEIPT_REUSE_MISMATCH",
                    "An existing deterministic rebuild receipt does not match the current exact trust basis.",
                    status_code=409,
                )
            conn.execute(
                """INSERT OR IGNORE INTO stage2_rebuild_receipts(
                   rebuild_receipt_id,rebuild_id,project_id,project_revision,status,terminal_commit_id,terminal_projection_hash,
                   event_chain_head,mechanical_state_hash,artifact_set_hash,ordered_artifacts_json,blocker_report_hash,
                   rebuild_projection_json,rebuild_projection_hash,integrity_version,integrity_key_id,integrity_domain,integrity_mac,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rebuild_receipt_id,rebuild_id,project_id,project["revision"],status_name,terminal_commit_id,terminal_projection_hash,
                    integrity["event_chain_head"],event_state_hash,artifact_set_hash,canonical_json(ordered_artifacts),blocker_report_hash,
                    rebuild_projection_json,rebuild_projection_hash,rebuild_envelope.integrity_version,rebuild_envelope.key_id,
                    rebuild_envelope.domain,rebuild_envelope.mac,created_at,
                ),
            )

            conn.execute("DELETE FROM stage2_artifacts WHERE project_id=? AND project_revision=?", (project_id, project["revision"]))
            for name, data in sorted(artifacts.items()):
                media = "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8"
                artifact_hash = sha256_bytes(data)
                metadata = {
                    **trust_set,
                    "rebuild_id": rebuild_id,
                    "rebuild_receipt_id": rebuild_receipt_id,
                    "rebuild_projection_hash": rebuild_projection_hash,
                    "artifact_name": name,
                    "artifact_hash": artifact_hash,
                    "media_type": media,
                    "trust_status": trust_status,
                }
                conn.execute(
                    """INSERT INTO stage2_artifacts(
                       project_id,project_revision,artifact_name,media_type,artifact_hash,artifact_bytes,created_at,
                       trust_status,event_chain_head,state_hash,trust_metadata_json,rebuild_receipt_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        project_id, project["revision"], name, media, artifact_hash, data, created_at,
                        trust_status, integrity["event_chain_head"], event_state_hash, canonical_json(metadata), rebuild_receipt_id,
                    ),
                )

            conn.execute("DELETE FROM stage2_level_snapshots WHERE project_id=? AND project_revision=?", (project_id, project["revision"]))
            if status_name == "READY" and ledger:
                for rowdata in ledger["rows"]:
                    sequence = max([event["sequence"] for event in events if event["advancement"]["target_cl"] <= rowdata["cl"]], default=0)
                    conn.execute("INSERT INTO stage2_level_snapshots(project_id,project_revision,character_cl,event_sequence,snapshot_hash,snapshot_json,created_at) VALUES(?,?,?,?,?,?,?)", (project_id, project["revision"], rowdata["cl"], sequence, rowdata["row_hash"], canonical_json(rowdata), created_at))

            conn.execute("DELETE FROM stage2_rebuild_status WHERE project_id=? AND project_revision=?", (project_id, project["revision"]))
            conn.execute(
                """INSERT INTO stage2_rebuild_status(
                   project_id,project_revision,status,event_chain_head,state_hash,artifact_set_hash,
                   trust_metadata_hash,blocker_report_hash,updated_at,rebuild_receipt_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id, project["revision"], status_name, integrity["event_chain_head"], event_state_hash,
                    artifact_set_hash, trust_metadata_hash, blocker_report_hash, created_at, rebuild_receipt_id,
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO stage2_rebuild_history(
                   rebuild_id,project_id,project_revision,status,event_chain_head,state_hash,artifact_set_hash,
                   trust_metadata_hash,blocker_report_hash,artifact_names_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rebuild_id, project_id, project["revision"], status_name, integrity["event_chain_head"], event_state_hash,
                    artifact_set_hash, trust_metadata_hash, blocker_report_hash, canonical_json(sorted(artifacts)), created_at,
                ),
            )
            return {
                "project_id": project_id,
                "project_revision": project["revision"],
                "status": status_name,
                "canonical_artifacts_available": status_name == "READY",
                "event_count": len(events),
                "event_chain_head": integrity["event_chain_head"],
                "target_cl": state["current_cl"] if status_name == "READY" else 0,
                "final_state_hash": event_state_hash,
                "blocker_report": blocker_report,
                "reconciliation": reconciliation,
                "quarantine_diagnostics": quarantine_diagnostics,
                "provenance_coverage": provenance["coverage"] if status_name == "READY" else {"required": 0, "proven": 0, "unproven": 0},
                "artifacts": [
                    {
                        "artifact_name": name,
                        "sha256": sha256_bytes(data),
                        "media_type": "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8",
                        "size_bytes": len(data),
                        "namespace": namespace,
                        "trust_status": trust_status,
                    }
                    for name, data in sorted(artifacts.items())
                ],
            }

    def _regenerate_ready_artifacts(self, project_id: str, project: dict[str, Any], integrity: dict[str, Any]) -> dict[str, bytes]:
        """Recreate consumer-facing canonical bytes from the externally anchored event stream.

        This is deliberately independent of ``stage2_artifacts`` and
        ``stage2_rebuild_status``.  The keyed rebuild receipt authenticates the
        stored set; this second comparison proves that requested mechanics are
        also the deterministic projection of the verified event stream.
        """
        if not integrity.get("valid"):
            raise FoundryError(
                "STAGE2_ARTIFACT_REGENERATION_BLOCKED",
                "Canonical artifacts cannot be regenerated from an invalid event stream.",
                details={"blockers": integrity.get("blockers") or []},
                status_code=409,
            )
        events = list(integrity.get("v3_events") or [])
        blockers: list[dict[str, Any]] = []
        state = _state(project_id)
        rows: list[dict[str, Any]] = []
        entries: dict[str, Any] = {}
        if events:
            state, rows, entries = self._rows(events, project_id)
            blockers.extend(self._completion_blockers(state, state["current_cl"], events, project))
        else:
            blockers.append(_block("NO_RULES_CAUSAL_STAGE2_EVENTS", "/events", "No HF1 v3 advancement events exist for this project."))
        orphaned = self._orphaned(state)
        blockers.extend(
            _block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", "/final_state", "A final-state element lacks a causal event.", **item)
            for item in orphaned
        )
        ledger = None
        if rows and not blockers:
            try:
                ledger = self._ledger(project, events, state, rows)
            except Exception as exc:
                blockers.append(_block(
                    "LEVELING_LEDGER_SCHEMA_INVALID", "/ledger", "The deterministic ledger failed its v2 schema.",
                    diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})(),
                ))
        required = sorted(pointer for row_index, row in enumerate(rows) for pointer in _leaf_pointers(row, f"/rows/{row_index}")) if not blockers else []
        required_set = set(required)
        proven_set = set(entries) & required_set
        missing = sorted(required_set - proven_set)
        unexpected = sorted(set(entries) - required_set) if not blockers else []
        for pointer in missing:
            blockers.append(_block(
                "FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", pointer,
                "A projected ledger leaf has no exact causal event/source proof; unrelated level-event fallback is forbidden.",
                cause="CAUSAL_EVENT_OR_RULE_SOURCE_MISSING",
            ))
        for pointer in unexpected:
            blockers.append(_block("PROVENANCE_POINTER_NOT_IN_LEDGER", pointer, "A provenance entry does not correspond to a projected ledger leaf."))
        if blockers or ledger is None:
            raise FoundryError(
                "STAGE2_ARTIFACT_REGENERATION_BLOCKED",
                "The verified event stream no longer produces the exact READY artifact set.",
                details={"blockers": blockers},
                status_code=409,
            )
        blocker_report = {
            "schema_version": "TianxiaFoundry.Stage2BlockerReport.v1",
            "project_id": project_id,
            "project_revision": project["revision"],
            "blocked": False,
            "blockers": [],
        }
        provenance = {
            "schema_version": "TianxiaFoundry.Stage2FieldProvenanceMap.v1",
            "project_id": project_id,
            "project_revision": project["revision"],
            "entries": entries,
            "event_count": len(events),
            "coverage": {"required": len(required), "proven": len(proven_set), "unproven": len(missing)},
        }
        event_state_hash = sha256_json(state)
        reconciliation = {
            "schema_version": "TianxiaFoundry.Stage2ReconciliationReport.v1",
            "project_id": project_id,
            "project_revision": project["revision"],
            "valid": event_state_hash == ledger["final_state_hash"],
            "event_state_hash": event_state_hash,
            "ledger_state_hash": ledger["final_state_hash"],
            "orphaned_final_elements": orphaned,
            "mismatches": [] if event_state_hash == ledger["final_state_hash"] else [{"code": "FINAL_STATE_HASH_MISMATCH"}],
        }
        self.registry.validate(blocker_report)
        self.registry.validate(provenance)
        self.registry.validate(reconciliation)
        return {
            "Stage2_Blocker_Report.json": canonical_json(blocker_report).encode(),
            "Stage2_Final_State_Reconciliation.json": canonical_json(reconciliation).encode(),
            "Stage2_Field_Provenance_Map.json": canonical_json(provenance).encode(),
            "Leveling_Ledger.json": canonical_json(ledger).encode(),
            "Leveling_Ledger.md": self._markdown(ledger).encode(),
        }

    def _verified_artifact_row(self, conn, project_id: str, name: str, *, quarantine: bool = False):
        _project_row, project = self._project_row(conn, project_id)
        status = conn.execute(
            "SELECT * FROM stage2_rebuild_status WHERE project_id=? AND project_revision=?",
            (project_id, project["revision"]),
        ).fetchone()
        required_status = "BLOCKED" if quarantine else "READY"
        required_trust = "QUARANTINED" if quarantine else "READY"
        if not status or status["status"] != required_status:
            raise FoundryError(
                "STAGE2_ARTIFACT_NOT_READY",
                "No exact trusted rebuild status exists for the current project revision and requested namespace.",
                details={"project_id": project_id, "project_revision": project["revision"], "required_status": required_status},
                status_code=409,
            )
        if not status["rebuild_receipt_id"]:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_LEGACY_UNPROVEN", "The active artifact set lacks an R4 external keyed rebuild receipt.", status_code=409)
        receipt_row = conn.execute("SELECT * FROM stage2_rebuild_receipts WHERE rebuild_receipt_id=?", (status["rebuild_receipt_id"],)).fetchone()
        if not receipt_row:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_MISSING", "The active keyed rebuild receipt is missing.", status_code=409)
        rebuild_projection = self._verify_rebuild_receipt(conn, receipt_row)
        integrity = self._persisted_event_integrity(conn, project_id)
        if integrity["valid"]:
            try:
                current_state, _rows, _entries = self._rows(integrity["v3_events"], project_id)
                current_state_hash = sha256_json(current_state)
            except Exception as exc:
                raise FoundryError(
                    "STAGE2_ARTIFACT_STATE_MISMATCH",
                    "The exact current mechanical state could not be reconstructed from the verified persisted event set.",
                    details={"error": str(exc)},
                    status_code=409,
                ) from exc
        else:
            current_state_hash = integrity["state_hash"]
        if not quarantine and not integrity["valid"]:
            raise FoundryError("STAGE2_ARTIFACT_CHAIN_INVALID", "The event chain or persisted event schema is invalid; canonical artifacts are unavailable.", details={"blockers": integrity["blockers"]}, status_code=409)
        if status["event_chain_head"] != integrity["event_chain_head"]:
            raise FoundryError("STAGE2_ARTIFACT_CHAIN_INVALID", "The current event-chain head differs from the trusted rebuild binding.", status_code=409)
        if status["state_hash"] != current_state_hash:
            raise FoundryError("STAGE2_ARTIFACT_STATE_MISMATCH", "The current replay/diagnostic state hash differs from the trusted rebuild binding.", status_code=409)
        row = conn.execute(
            "SELECT * FROM stage2_artifacts WHERE project_id=? AND project_revision=? AND artifact_name=?",
            (project_id, project["revision"], name),
        ).fetchone()
        if not row:
            raise FoundryError("STAGE2_ARTIFACT_NOT_FOUND", "No Stage 2 artifact with that name exists for the current trusted rebuild.", status_code=404)
        if row["trust_status"] != required_trust:
            raise FoundryError("STAGE2_ARTIFACT_NOT_READY", "The artifact is not in the requested trusted namespace.", status_code=409)
        if quarantine and not name.startswith("Quarantine_"):
            raise FoundryError("STAGE2_ARTIFACT_NOT_READY", "Only explicitly quarantined diagnostic artifacts may be read through the quarantine namespace.", status_code=409)
        if not quarantine and name.startswith("Quarantine_"):
            raise FoundryError("STAGE2_ARTIFACT_NOT_READY", "Quarantined diagnostics are never canonical consumer artifacts.", status_code=409)
        data = bytes(row["artifact_bytes"])
        if sha256_bytes(data) != row["artifact_hash"]:
            raise FoundryError("STAGE2_ARTIFACT_TAMPERED", "The stored Stage 2 artifact hash does not match its bytes.", status_code=409)
        try:
            metadata = json.loads(row["trust_metadata_json"])
        except Exception as exc:
            raise FoundryError("STAGE2_ARTIFACT_TRUST_METADATA_INVALID", "Artifact trust metadata is missing or malformed.", details={"error": str(exc)}, status_code=409) from exc
        ready_rows = conn.execute(
            "SELECT artifact_name,artifact_hash,length(artifact_bytes) AS size_bytes FROM stage2_artifacts WHERE project_id=? AND project_revision=? AND trust_status=? ORDER BY artifact_name",
            (project_id, project["revision"], required_trust),
        ).fetchall()
        actual_set_hash = sha256_json([
            {"artifact_name": item["artifact_name"], "artifact_hash": item["artifact_hash"], "size_bytes": item["size_bytes"]}
            for item in ready_rows
        ])
        expected_set = {
            "schema_version": "TianxiaFoundry.Stage2ArtifactTrustSet.v1",
            "project_id": project_id,
            "project_revision": project["revision"],
            "status": required_status,
            "namespace": "quarantine" if quarantine else "canonical",
            "event_chain_head": integrity["event_chain_head"],
            "state_hash": current_state_hash,
            "artifact_set_hash": actual_set_hash,
            "artifact_names": [item["artifact_name"] for item in ready_rows],
            "blocker_report_hash": status["blocker_report_hash"],
        }
        if actual_set_hash != status["artifact_set_hash"] or sha256_json(expected_set) != status["trust_metadata_hash"]:
            raise FoundryError("STAGE2_ARTIFACT_TRUST_SET_MISMATCH", "The stored artifact set does not match its trusted rebuild status.", status_code=409)
        if row["rebuild_receipt_id"] != status["rebuild_receipt_id"] or rebuild_projection.get("artifact_set_hash") != actual_set_hash:
            raise FoundryError("STAGE2_REBUILD_RECEIPT_ARTIFACT_SET_MISMATCH", "The artifact/status rows differ from the external keyed rebuild receipt.", status_code=409)
        ordered_now = [
            {
                "artifact_name": item["artifact_name"], "artifact_hash": item["artifact_hash"], "size_bytes": item["size_bytes"],
                "media_type": conn.execute("SELECT media_type FROM stage2_artifacts WHERE project_id=? AND project_revision=? AND artifact_name=?", (project_id, project["revision"], item["artifact_name"])).fetchone()[0],
                "trust_status": required_trust, "namespace": "quarantine" if quarantine else "canonical",
            }
            for item in ready_rows
        ]
        if ordered_now != rebuild_projection.get("ordered_artifacts"):
            raise FoundryError("STAGE2_REBUILD_RECEIPT_ARTIFACT_SET_MISMATCH", "The current ordered artifacts differ from the keyed rebuild receipt.", status_code=409)
        for key, value in expected_set.items():
            if metadata.get(key) != value:
                raise FoundryError("STAGE2_ARTIFACT_TRUST_METADATA_MISMATCH", "The artifact trust metadata does not match the exact current rebuild basis.", details={"field": key}, status_code=409)
        if metadata.get("artifact_name") != name or metadata.get("artifact_hash") != row["artifact_hash"] or metadata.get("trust_status") != required_trust:
            raise FoundryError("STAGE2_ARTIFACT_TRUST_METADATA_MISMATCH", "The artifact-specific trust metadata is inconsistent.", status_code=409)
        if not quarantine:
            regenerated = self._regenerate_ready_artifacts(project_id, project, integrity)
            expected_bytes = regenerated.get(name)
            if expected_bytes is None or expected_bytes != data:
                raise FoundryError(
                    "STAGE2_ARTIFACT_REGENERATION_MISMATCH",
                    "The stored canonical artifact differs from deterministic regeneration of the verified event stream.",
                    details={
                        "artifact_name": name,
                        "stored_hash": sha256_bytes(data),
                        "regenerated_hash": sha256_bytes(expected_bytes) if expected_bytes is not None else None,
                    },
                    status_code=409,
                )
        return row, data

    def ledger(self, project_id: str) -> dict[str, Any]:
        try:
            return json.loads(self.artifact(project_id, "Leveling_Ledger.json")[1])
        except FoundryError as exc:
            raise FoundryError("STAGE2_LEDGER_BLOCKED", "The rules-causal Leveling Ledger is not READY under the exact current trust basis.", details=exc.to_dict(), status_code=409) from exc

    def artifact(self, project_id: str, name: str) -> tuple[str, bytes, str]:
        with self.db.connection() as conn:
            row, data = self._verified_artifact_row(conn, project_id, name, quarantine=False)
            return row["media_type"], data, row["artifact_hash"]

    def quarantine_artifact(self, project_id: str, name: str) -> tuple[str, bytes, str]:
        with self.db.connection() as conn:
            row, data = self._verified_artifact_row(conn, project_id, name, quarantine=True)
            return row["media_type"], data, row["artifact_hash"]

    def status(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            _, project = self._project_row(conn, project_id)
            rebuild = conn.execute("SELECT * FROM stage2_rebuild_status WHERE project_id=? AND project_revision=?", (project_id, project["revision"])).fetchone()
            artifacts = [dict(row) for row in conn.execute(
                "SELECT artifact_name,media_type,artifact_hash AS sha256,length(artifact_bytes) AS size_bytes,created_at,trust_status,event_chain_head,state_hash FROM stage2_artifacts WHERE project_id=? AND project_revision=? ORDER BY artifact_name",
                (project_id, project["revision"]),
            )]
            proposals = [dict(row) for row in conn.execute("SELECT proposal_id,target_cl,status,proposal_hash,approved_by,created_at,updated_at FROM stage2_proposals WHERE project_id=? ORDER BY created_at DESC", (project_id,))]
            blockers = [{"code": row["blocker_code"], "severity": row["severity"], "pointer": row["pointer"], "message": row["message"], "details": json.loads(row["details_json"])} for row in conn.execute("SELECT * FROM stage2_blockers WHERE project_id=? AND resolved_at IS NULL ORDER BY created_at", (project_id,))]
            return {
                "project_id": project_id,
                "project_revision": project["revision"],
                "content_lock_hash": project["content_lock"]["lock_hash"],
                "runtime_contract": "PHASE4A_HF2_RECOVERY_R4",
                "rebuild_status": dict(rebuild) if rebuild else None,
                "proposals": proposals,
                "artifacts": artifacts,
                "blockers": blockers,
                "stage2_ai_provider_bridge_implemented": False,
                "production_rules_authority_pack_compiled": False,
                "command5_candidate_claimed": False,
                "gm_screen_acceptance_claimed": False,
            }

    def validate_ledger_document(self, project_id: str, ledger: dict[str, Any]) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        try:
            self.registry.validate(ledger, LEDGER_V2)
        except Exception as exc:
            blockers.append(_block("LEVELING_LEDGER_SCHEMA_INVALID", "", "The supplied ledger does not match LevelingLedger.v2.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})()))
        try:
            expected = self.ledger(project_id)
        except FoundryError as exc:
            expected = None
            blockers.append(_block("DETERMINISTIC_LEDGER_UNAVAILABLE", "", "Deterministic replay cannot currently produce a READY ledger.", error=exc.to_dict()))
        if expected is not None and canonical_json(expected) != canonical_json(ledger):
            blockers.append(_block("LEVELING_LEDGER_DOES_NOT_MATCH_EVENTS", "", "The supplied ledger differs from deterministic replay.", expected_hash=sha256_json(expected), actual_hash=sha256_json(ledger)))
        for i, row in enumerate(ledger.get("rows", []) if isinstance(ledger, dict) else []):
            if i and row.get("cl") == ledger["rows"][i - 1].get("cl"):
                blockers.append(_block("COPIED_OR_REPEATED_LEVEL_ROW", f"/rows/{i}", "A level row repeats a prior CL."))
            computed = sha256_json({k: v for k, v in row.items() if k != "row_hash"})
            if row.get("row_hash") != computed:
                blockers.append(_block("CUMULATIVE_SNAPSHOT_TAMPERED", f"/rows/{i}/row_hash", "The cumulative row hash does not match its content.", expected=computed, actual=row.get("row_hash")))
        def walk(value: Any, pointer: str = "") -> None:
            if isinstance(value, str) and PLACEHOLDER_RE.search(value.strip()):
                blockers.append(_block("PLACEHOLDER_FORBIDDEN", pointer, "Forbidden placeholder text appears in the ledger.", value=value))
            elif isinstance(value, dict):
                for k, v in value.items(): walk(v, pointer + "/" + _ptr(k))
            elif isinstance(value, list):
                for i, v in enumerate(value): walk(v, pointer + f"/{i}")
        walk(ledger)
        return {"valid": not blockers, "blockers": blockers, "expected_hash": sha256_json(expected) if expected else None, "actual_hash": sha256_json(ledger) if isinstance(ledger, dict) else None}

    def validate_provenance_document(self, project_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        try:
            self.registry.validate(provenance, "TianxiaFoundry.Stage2FieldProvenanceMap.v1")
        except Exception as exc:
            blockers.append(_block("PROVENANCE_MAP_SCHEMA_INVALID", "", "The provenance map failed its schema.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})()))
        self.rebuild(project_id)
        expected = json.loads(self.artifact(project_id, "Stage2_Field_Provenance_Map.json")[1])
        if canonical_json(expected) != canonical_json(provenance):
            blockers.append(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", "/entries", "The provenance map differs from deterministic replay.", missing_pointers=sorted(set(expected.get("entries", {})) - set(provenance.get("entries", {})))))
        return {"valid": not blockers, "blockers": blockers, "expected_hash": sha256_json(expected), "actual_hash": sha256_json(provenance)}

    def audit(self, project_id: str) -> dict[str, Any]:
        """Return typed forensic evidence for hostile persistence without leaking mechanics."""
        try:
            status = self.rebuild(project_id)
            blockers = list(status["blocker_report"]["blockers"])
        except Exception as exc:
            if isinstance(exc, FoundryError):
                code = "AUDIT_" + exc.code
                details = exc.details
                message = exc.message
            else:
                code = "AUDIT_PERSISTED_CONTRACT_FAILURE"
                details = {"exception_type": type(exc).__name__}
                message = "Persisted Stage 2 evidence could not be verified under the pinned contracts."
            blocker = _block(code, "/events", message, forensic=details)
            status = {
                "project_id": project_id,
                "status": "BLOCKED",
                "canonical_artifacts_available": False,
                "ledger": None,
                "provenance": None,
                "reconciliation": None,
                "blocker_report": {
                    "schema_version": "TianxiaFoundry.Stage2BlockerReport.v1",
                    "project_id": project_id,
                    "project_revision": None,
                    "blocked": True,
                    "blockers": [blocker],
                },
            }
            blockers = [blocker]
        try:
            chain = self.projects.verify_chain(project_id)
        except Exception as exc:
            chain = {
                "project_id": project_id,
                "valid": False,
                "chain_valid": False,
                "event_count": None,
                "latest_event_hash": None,
                "errors": [{
                    "code": "PERSISTED_EVENT_UNREADABLE",
                    "pointer": "/events",
                    "message": "Persisted event evidence is unreadable.",
                    "forensic": {"exception_type": type(exc).__name__},
                }],
            }
        chain.setdefault("chain_valid", bool(chain.get("valid")))
        if not chain.get("valid") and not any(blocker.get("code") == "EVENT_CHAIN_TAMPERED" for blocker in blockers):
            blockers.append(_block("EVENT_CHAIN_TAMPERED", "/events", "The append-only event chain failed verification.", errors=chain.get("errors")))
        return {
            "schema_version": "TianxiaFoundry.Stage2HostileAudit.v1",
            "project_id": project_id,
            "valid": not blockers,
            "chain": chain,
            "stage2": status,
            "blockers": blockers,
            "canonical_artifacts_available": False if blockers else bool(status.get("canonical_artifacts_available", True)),
        }


class Stage2AdvancementService(LegacyStage2AdvancementService):
    """Compatibility facade.

    v1 proposals and v2 events retain the sealed Phase 4A behavior. New HF1 proposal
    v2 / event v3 projects use the corrected rules-causal implementation.
    """

    def __init__(self, db: Database, *, principal_provider: PrincipalProvider | None = None, integrity: IntegrityService | None = None):
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.integrity = integrity or IntegrityService.for_database(db)
        super().__init__(db, principal_provider=self.principal_provider, integrity=self.integrity)
        self.hf1 = RulesCausalStage2Service(db, principal_provider=self.principal_provider, integrity=self.integrity)

    def _proposal_version(self, proposal_id: str) -> str:
        with self.db.connection() as conn:
            row = conn.execute("SELECT proposal_json FROM stage2_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if not row:
                raise FoundryError("STAGE2_PROPOSAL_NOT_FOUND", "No Stage 2 proposal has that ID.", status_code=404)
            return json.loads(row[0]).get("schema_version", "TianxiaFoundry.Stage2AdvancementProposal.v1")

    def _has_v3(self, project_id: str) -> bool:
        with self.db.connection() as conn:
            for row in conn.execute("SELECT canonical_schema_version FROM events WHERE project_id=?", (project_id,)):
                if row[0] == EVENT_V3:
                    return True
            return False

    @staticmethod
    def _require_writable_proposal_version(version: str) -> None:
        if version != PROPOSAL_V2:
            raise FoundryError(
                "STAGE2_LEGACY_WRITE_DISABLED",
                "Legacy Stage 2 proposal streams remain readable but cannot be created, validated, approved, or committed through the current service.",
                details={"supplied": version, "required": PROPOSAL_V2},
                status_code=409,
            )

    def create_proposal(self, body: dict[str, Any]) -> dict[str, Any]:
        version = body.get("schema_version")
        self._require_writable_proposal_version(version)
        return self.hf1.create_proposal(body)

    def _trusted_character_creation_scope(self, **kwargs: Any):
        return self.hf1._trusted_character_creation_scope(**kwargs)

    def validate_proposal(self, proposal_id: str) -> dict[str, Any]:
        version = self._proposal_version(proposal_id)
        self._require_writable_proposal_version(version)
        return self.hf1.validate_proposal(proposal_id)

    def issue_approval_challenge(self, proposal_id: str, *, ttl_seconds: int = 300) -> dict[str, Any]:
        version = self._proposal_version(proposal_id)
        self._require_writable_proposal_version(version)
        return self.hf1.issue_approval_challenge(proposal_id, ttl_seconds=ttl_seconds)

    def approve_proposal(self, proposal_id: str, approved_by: str | None = None, *, challenge_id: str | None = None, nonce: str | None = None) -> dict[str, Any]:
        version = self._proposal_version(proposal_id)
        self._require_writable_proposal_version(version)
        return self.hf1.approve_proposal(proposal_id, approved_by, challenge_id=challenge_id, nonce=nonce)

    def commit_proposal(self, proposal_id: str, *, simulate_crash_after: int | None = None) -> dict[str, Any]:
        version = self._proposal_version(proposal_id)
        self._require_writable_proposal_version(version)
        return self.hf1.commit_proposal(proposal_id, simulate_crash_after=simulate_crash_after)

    def rebuild(self, project_id: str) -> dict[str, Any]:
        return self.hf1.rebuild(project_id) if self._has_v3(project_id) else super().rebuild(project_id)

    def ledger(self, project_id: str) -> dict[str, Any]:
        return self.hf1.ledger(project_id) if self._has_v3(project_id) else super().ledger(project_id)

    def status(self, project_id: str) -> dict[str, Any]:
        return self.hf1.status(project_id) if self._has_v3(project_id) else super().status(project_id)

    def artifact(self, project_id: str, name: str) -> tuple[str, bytes, str]:
        return self.hf1.artifact(project_id, name) if self._has_v3(project_id) else super().artifact(project_id, name)

    def quarantine_artifact(self, project_id: str, name: str) -> tuple[str, bytes, str]:
        if not self._has_v3(project_id):
            raise FoundryError(
                "STAGE2_ARTIFACT_NOT_READY",
                "Legacy Stage 2 artifacts have no HF2 quarantined diagnostic namespace.",
                status_code=409,
            )
        return self.hf1.quarantine_artifact(project_id, name)

    def validate_ledger_document(self, project_id: str, ledger: dict[str, Any]) -> dict[str, Any]:
        return self.hf1.validate_ledger_document(project_id, ledger) if self._has_v3(project_id) or ledger.get("schema_version") == LEDGER_V2 else super().validate_ledger_document(project_id, ledger)

    def validate_provenance_document(self, project_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
        return self.hf1.validate_provenance_document(project_id, provenance) if self._has_v3(project_id) else super().validate_provenance_document(project_id, provenance)

    def audit(self, project_id: str) -> dict[str, Any]:
        return self.hf1.audit(project_id) if self._has_v3(project_id) else super().audit(project_id)


__all__ = ["Stage2AdvancementService", "RulesCausalStage2Service", "_pb", "_ability_modifier"]
