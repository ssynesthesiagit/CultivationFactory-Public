from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_json, utcnow
from contracts.canonical import ZERO_HASH, canonical_event_hash, canonical_project_document, canonical_project_hash
from contracts.registry import SchemaRegistry
from project_store.service import ProjectStore
from security.approval_challenges import ApprovalChallengeService
from security.integrity import IntegrityService
from security.local_identity import PrincipalProvider, ProcessPrincipalProvider

PLACEHOLDER_RE = re.compile(r"^(?:not recorded|not itemized|unnamed talent|unknown|tbd|placeholder)$", re.I)
EVENT_VERSION = "TianxiaFoundry.AdvancementEvent.v2"
PROPOSAL_VERSION = "TianxiaFoundry.Stage2AdvancementProposal.v1"
LEDGER_VERSION = "TianxiaFoundry.LevelingLedger.v1"
BLOCKER_VERSION = "TianxiaFoundry.Stage2BlockerReport.v1"
RECON_VERSION = "TianxiaFoundry.Stage2ReconciliationReport.v1"

SELECTION_KINDS = {
    "background_acquisition": "background",
    "background_sphere_acquisition": "sphere",
    "background_talent_acquisition": "talent",
    "origin_insight_acquisition": "cultivation_insight",
    "path_acquisition": "path",
    "subpath_acquisition": "subpath",
    "method_acquisition": "cultivation_method",
    "foundation_acquisition": "foundation",
    "foundation_expression": "foundation_expression",
    "sphere_acquisition": "sphere",
    "talent_acquisition": "talent",
    "manual_acquisition": "recorded_art",
    "forged_technique_acquisition": "forged_technique",
    "equipment_acquisition": "item",
}


def _ability_modifier(score: int) -> int:
    return (int(score) - 10) // 2


def _pb(cl: int) -> int:
    return min(6, 2 + (int(cl) - 1) // 4)


def _copy_state(state: dict[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_json(state))


def _initial_mechanical_state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.Stage2MechanicalState.v1",
        "project_id": project_id,
        "current_cl": 0,
        "pb": None,
        "ability_scores": {},
        "ability_modifiers": {},
        "hp_total": 0,
        "resources": {},
        "background": None,
        "background_sphere": None,
        "background_talent": None,
        "origin_insight": None,
        "paths": [],
        "subpaths": [],
        "method": {"state": "none", "reason_code": "not_acquired", "reason": "No Method acquisition event exists."},
        "foundation": {"state": "none", "reason_code": "not_acquired", "reason": "No Foundation acquisition event exists."},
        "known_spheres": [],
        "known_talents": [],
        "manuals": [],
        "forged_techniques": [],
        "equipment": [],
        "free_level_talents": {},
        "trained_choices": {},
        "new_sphere_bonus": {},
        "event_ids": [],
        "record_event_ids": {},
    }


def _block(code: str, pointer: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "pointer": pointer, "message": message, "details": details}


def _source_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    source = record["source"]
    row = {
        "source_id": source["source_id"],
        "source_hash": source["source_hash"],
        "source_anchor": source["anchor"],
        "source_path": source.get("path", ""),
    }
    return [row]


def _none(reason_code: str, reason: str) -> dict[str, Any]:
    return {"state": "none", "reason_code": reason_code, "reason": reason}


class Stage2AdvancementService:
    """Deterministic Stage 2 advancement engine.

    Proposal payloads contain bounded IDs and declared starting inputs. They are not
    authority. Every committed mechanical change is emitted as a canonical v2
    Advancement Event bound to a published, project-locked catalog record.
    """

    def __init__(self, db: Database, *, principal_provider: PrincipalProvider | None = None, integrity: IntegrityService | None = None):
        self.db = db
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.integrity = integrity or IntegrityService.for_database(db)
        self.projects = ProjectStore(db, integrity=self.integrity)
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.challenges = ApprovalChallengeService(
            db,
            principal_provider=self.principal_provider,
            integrity=self.integrity,
        )

    # ---------- persistence and authority ----------
    def _project_row(self, conn, project_id: str):
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
        project = json.loads(row["project_json"])
        self.registry.validate(project)
        return row, project

    def _record(self, conn, project_id: str, record_id: str, pointer: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        record = self.projects._resolve_locked_record(conn, project_id, record_id)
        if not record:
            return None, [_block("MISSING_OR_UNLOCKED_CATALOG_AUTHORITY", pointer, "The requested ID is not present in the immutable project content lock.", record_id=record_id)]
        publication = record.get("publication", {}).get("status")
        if publication != "published":
            return None, [_block("CATALOG_RECORD_NOT_PUBLISHED", pointer, "Only published locked content may create mechanical events.", record_id=record_id, publication_status=publication)]
        authority = record.get("compatibility", {}).get("factory", {}).get("stage2_authority")
        if not isinstance(authority, dict):
            return None, [_block("MISSING_STAGE2_MECHANICAL_AUTHORITY", pointer, "The published record has no structured Stage 2 mechanical authority.", record_id=record_id)]
        return record, []

    def _proposal_row(self, conn, proposal_id: str):
        row = conn.execute("SELECT * FROM stage2_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if not row:
            raise FoundryError("STAGE2_PROPOSAL_NOT_FOUND", "No Stage 2 proposal has that ID.", status_code=404)
        return row

    def create_proposal(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self.registry.validate(body, PROPOSAL_VERSION)
        except Exception as exc:
            details = getattr(exc, "to_dict", lambda: {"message": str(exc)})()
            raise FoundryError("STAGE2_PROPOSAL_SCHEMA_INVALID", "The Stage 2 proposal does not match the bounded contract.", details=details)
        proposal_hash = sha256_json(body)
        now = utcnow()
        with self.db.transaction() as conn:
            row, project = self._project_row(conn, body["project_id"])
            if int(row["revision"]) != int(body["expected_project_revision"]):
                raise FoundryError("STALE_PROJECT_REVISION", "The proposal targets a stale project revision.", details={"expected": body["expected_project_revision"], "actual": row["revision"]})
            if project["content_lock"]["lock_hash"] != body["expected_content_lock_hash"]:
                raise FoundryError("STALE_CONTENT_LOCK", "The proposal targets a different immutable content lock.", details={"expected": body["expected_content_lock_hash"], "actual": project["content_lock"]["lock_hash"]})
            existing = conn.execute("SELECT * FROM stage2_proposals WHERE project_id=? AND idempotency_key=?", (body["project_id"], body["idempotency_key"])).fetchone()
            if existing:
                if existing["proposal_hash"] != proposal_hash:
                    raise FoundryError("STAGE2_IDEMPOTENCY_CONFLICT", "The idempotency key is already bound to different proposal bytes.")
                return self.get_proposal(existing["proposal_id"])
            proposal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tianxia-stage2:{body['project_id']}:{body['idempotency_key']}:{proposal_hash}"))
            conn.execute(
                """INSERT INTO stage2_proposals(proposal_id,project_id,idempotency_key,expected_project_revision,
                expected_content_lock_hash,target_cl,status,proposal_json,proposal_hash,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (proposal_id, body["project_id"], body["idempotency_key"], body["expected_project_revision"], body["expected_content_lock_hash"], body["target_cl"], "draft", canonical_json(body), proposal_hash, now, now),
            )
            for ordinal, choice in enumerate(body["choices"], start=1):
                conn.execute("INSERT INTO stage2_proposal_events(proposal_id,ordinal,event_request_json,event_request_hash) VALUES(?,?,?,?)", (proposal_id, ordinal, canonical_json(choice), sha256_json(choice)))
        return self.get_proposal(proposal_id)

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = self._proposal_row(conn, proposal_id)
            result = dict(row)
            for key in ("proposal_json", "validation_json"):
                if result.get(key):
                    result[key.removesuffix("_json")] = json.loads(result.pop(key))
                else:
                    result.pop(key, None)
            result["choices"] = [json.loads(r[0]) for r in conn.execute("SELECT event_request_json FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal", (proposal_id,))]
            return result

    def list_proposals(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT proposal_id,project_id,target_cl,status,proposal_hash,approved_by,created_at,updated_at FROM stage2_proposals WHERE project_id=? ORDER BY created_at DESC", (project_id,))]

    # ---------- deterministic reducer ----------
    def _existing_v2_events(self, conn, project_id: str) -> list[dict[str, Any]]:
        out=[]
        for row in conn.execute("SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,)):
            event=json.loads(row[0])
            if event.get("schema_version") == EVENT_VERSION:
                self.registry.validate(event)
                out.append(event)
        return out

    def _state_from_events(self, events: list[dict[str, Any]], project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        state=_initial_mechanical_state(project_id)
        rows=[]
        provenance={}
        by_cl: dict[int,list[dict[str,Any]]]={}
        for event in events:
            by_cl.setdefault(event["advancement"]["target_cl"], []).append(event)
        cumulative_events: list[dict[str, Any]] = []
        for cl in sorted(k for k in by_cl if k >= 0):
            current_events = sorted(by_cl[cl], key=lambda e: (e["effective_point"]["order"], e["sequence"]))
            for event in current_events:
                state=self._apply_event(state,event)
                cumulative_events.append(event)
            if cl >= 1 and state["current_cl"] >= cl:
                row=self._level_row(state, cl, current_events, cumulative_events)
                rows.append(row)
                self._row_provenance(provenance,row,event_list=current_events,cumulative_events=cumulative_events,row_index=len(rows)-1)
        return state, rows, provenance

    def _apply_event(self, prior: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        state=_copy_state(prior)
        adv=event["advancement"]
        kind=adv["kind"]
        details=adv["details"]
        outputs=adv["calculation"]["outputs"]
        rid=event["subject"]["record_id"]
        eid=event["event_id"]
        state["event_ids"].append(eid)
        state["record_event_ids"][rid]=eid
        if kind == "starting_state":
            state["ability_scores"] = deepcopy(outputs["ability_scores"])
            state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
        elif kind == "ability_score_change":
            state["ability_scores"] = deepcopy(outputs["ability_scores"])
            state["ability_modifiers"] = deepcopy(outputs["ability_modifiers"])
        elif kind == "path_acquisition":
            if rid not in state["paths"]: state["paths"].append(rid)
        elif kind == "level_advance":
            state["current_cl"] = adv["target_cl"]
            state["pb"] = outputs["pb"]
            state["hp_total"] = outputs["hp_total"]
            state["resources"] = deepcopy(outputs["resources_after"])
        elif kind == "background_acquisition": state["background"] = rid
        elif kind == "background_sphere_acquisition":
            state["background_sphere"] = rid
            if rid not in state["known_spheres"]: state["known_spheres"].append(rid)
        elif kind == "background_talent_acquisition":
            state["background_talent"] = rid
            if rid not in state["known_talents"]: state["known_talents"].append(rid)
        elif kind == "origin_insight_acquisition": state["origin_insight"] = rid
        elif kind == "subpath_acquisition":
            if not isinstance(state["subpaths"], list):
                state["subpaths"] = []
            if rid not in state["subpaths"]:
                state["subpaths"].append(rid)
        elif kind == "method_acquisition": state["method"] = {"record_id":rid,"status":"acquired","event_id":eid}
        elif kind == "method_activation": state["method"] = {"record_id":rid,"status":"active","event_id":eid}
        elif kind == "foundation_acquisition": state["foundation"] = {"record_id":rid,"status":"acquired","event_id":eid,"path_expression":None,"stage":None}
        elif kind == "foundation_expression":
            base=state["foundation"] if isinstance(state["foundation"],dict) else {}
            state["foundation"]={**base,"record_id":details["foundation_record_id"],"path_expression":rid,"path_id":details["path_id"],"status":"expressed","event_id":eid}
        elif kind == "foundation_stage":
            base=state["foundation"] if isinstance(state["foundation"],dict) else {}
            state["foundation"]={**base,"stage":details["stage"],"status":"active","event_id":eid}
        elif kind == "sphere_acquisition":
            if rid not in state["known_spheres"]: state["known_spheres"].append(rid)
            if event["legal_channel"] == "new-sphere-acquisition": state["new_sphere_bonus"].setdefault(str(adv["target_cl"]),{"sphere_event_id":eid,"talent_event_id":None})
        elif kind == "talent_acquisition":
            if rid not in state["known_talents"]: state["known_talents"].append(rid)
            clkey=str(adv["target_cl"])
            if event["legal_channel"] == "free-level-talent": state["free_level_talents"].setdefault(clkey,[]).append(rid)
            if event["legal_channel"] == "trained-choice": state["trained_choices"].setdefault(clkey,[]).append(rid)
            if event["legal_channel"] == "new-sphere-bonus-talent": state["new_sphere_bonus"].setdefault(clkey,{"sphere_event_id":None,"talent_event_id":None})["talent_event_id"]=eid
        elif kind == "manual_acquisition":
            if rid not in state["manuals"]: state["manuals"].append(rid)
        elif kind == "forged_technique_acquisition":
            if rid not in state["forged_techniques"]: state["forged_techniques"].append(rid)
        elif kind == "equipment_acquisition":
            if rid not in state["equipment"]: state["equipment"].append(rid)
        elif kind == "typed_none":
            target=details["target"]
            state[target]=deepcopy(adv["none_state"])
        state["known_spheres"].sort(); state["known_talents"].sort(); state["manuals"].sort(); state["forged_techniques"].sort(); state["equipment"].sort()
        return state

    def _level_row(self, state: dict[str, Any], cl: int, event_list: list[dict[str, Any]], cumulative_events: list[dict[str, Any]]) -> dict[str, Any]:
        level_event = next((e for e in event_list if e["advancement"]["kind"] == "level_advance"), None)
        hp_outputs = level_event["advancement"]["calculation"]["outputs"] if level_event else {}
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for event in event_list:
            by_kind.setdefault(event["advancement"]["kind"], []).append(event)
        all_by_kind: dict[str, list[dict[str, Any]]] = {}
        for event in cumulative_events:
            all_by_kind.setdefault(event["advancement"]["kind"], []).append(event)

        def record_ids(kind: str) -> list[str]:
            return [e["subject"]["record_id"] for e in by_kind.get(kind, [])]

        ability_events = by_kind.get("ability_score_change", [])
        if cl == 1 and not ability_events:
            ability_events = all_by_kind.get("starting_state", [])[-1:]
        ability_effects = [
            {
                "event_id": e["event_id"],
                "kind": e["advancement"]["kind"],
                "calculation_rule_id": e["advancement"]["calculation"]["rule_id"],
                "outputs": deepcopy(e["advancement"]["calculation"]["outputs"]),
            }
            for e in ability_events
        ]

        resource_changes: dict[str, Any] = {}
        for resource_id, total in sorted(state["resources"].items()):
            resource_changes[resource_id] = {
                "gain": int(hp_outputs.get("resource_gains", {}).get(resource_id, 0)),
                "formula": deepcopy(hp_outputs.get("resource_formulas", {}).get(resource_id)),
                "total": int(total),
            }

        new_sphere_events = [e for e in by_kind.get("sphere_acquisition", []) if e["legal_channel"] == "new-sphere-acquisition"]
        bonus_events = [e for e in by_kind.get("talent_acquisition", []) if e["legal_channel"] == "new-sphere-bonus-talent"]
        if new_sphere_events or bonus_events:
            new_sphere = {
                "state": "acquired",
                "sphere_record_ids": [e["subject"]["record_id"] for e in new_sphere_events],
                "bonus_talent_record_ids": [e["subject"]["record_id"] for e in bonus_events],
                "sphere_event_ids": [e["event_id"] for e in new_sphere_events],
                "bonus_talent_event_ids": [e["event_id"] for e in bonus_events],
            }
        else:
            new_sphere = {
                "state": "none",
                "reason_code": "no_new_sphere_acquisition_at_cl",
                "reason": f"No new-Sphere acquisition event exists at CL {cl}.",
                "source_backed": True,
            }

        path_acquisitions = record_ids("path_acquisition")
        subpath_acquisitions = record_ids("subpath_acquisition")
        manual_acquisitions = record_ids("manual_acquisition")
        forged_acquisitions = record_ids("forged_technique_acquisition")
        equipment_acquisitions = record_ids("equipment_acquisition")
        free_ids = list(state["free_level_talents"].get(str(cl), []))
        trained_ids = list(state["trained_choices"].get(str(cl), []))
        free_capacity = hp_outputs.get("free_level_talent_capacity")
        trained_capacity = hp_outputs.get("trained_choice_capacity")
        row = {
            "cl": cl,
            "pb": state["pb"],
            "hp": {"gain": hp_outputs.get("hp_gain", 0), "formula": hp_outputs.get("hp_formula"), "total": state["hp_total"]},
            "resource_changes": resource_changes,
            "resources_after_level": deepcopy(state["resources"]),
            "ability_score_effects": ability_effects,
            "ability_scores_after_level": deepcopy(state["ability_scores"]),
            "background": deepcopy(state["background"] if state["background"] is not None else _none("not_acquired_by_cl", "No Background acquisition event exists at or before this CL.")),
            "background_sphere": deepcopy(state["background_sphere"] if state["background_sphere"] is not None else _none("not_acquired_by_cl", "No Background Sphere acquisition event exists at or before this CL.")),
            "background_talent": deepcopy(state["background_talent"] if state["background_talent"] is not None else _none("not_acquired_by_cl", "No Background Talent acquisition event exists at or before this CL.")),
            "origin_insight": deepcopy(state["origin_insight"] if state["origin_insight"] is not None else _none("not_acquired_by_cl", "No Origin Insight acquisition event exists at or before this CL.")),
            "path_acquisitions": path_acquisitions,
            "paths_after_level": list(state["paths"]),
            "subpath_acquisitions": subpath_acquisitions,
            "subpaths_after_level": deepcopy(state["subpaths"]),
            "method": deepcopy(state["method"]),
            "foundation": deepcopy(state["foundation"]),
            "free_level_talents": {"capacity": free_capacity, "used": len(free_ids), "record_ids": free_ids},
            "trained_choices": {"capacity": trained_capacity, "used": len(trained_ids), "record_ids": trained_ids},
            "new_sphere_acquisition": new_sphere,
            "known_spheres_after_level": list(state["known_spheres"]),
            "known_talents_after_level": list(state["known_talents"]),
            "manual_acquisitions": manual_acquisitions,
            "manuals_after_level": list(state["manuals"]),
            "forged_technique_acquisitions": forged_acquisitions,
            "forged_techniques_after_level": list(state["forged_techniques"]),
            "equipment_acquisitions": equipment_acquisitions,
            "equipment_after_level": list(state["equipment"]),
            "legality": {"status": "valid", "blocker_count": 0, "event_count": len(event_list)},
            "event_ids": [e["event_id"] for e in event_list],
        }
        row["row_hash"] = sha256_json(row)
        return row

    def _row_provenance(self, target: dict[str, Any], row: dict[str, Any], event_list: list[dict[str, Any]], cumulative_events: list[dict[str, Any]], row_index: int) -> None:
        by_id = {e["subject"]["record_id"]: e for e in cumulative_events}
        by_event_id = {e["event_id"]: e for e in cumulative_events}
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for event in cumulative_events:
            by_kind.setdefault(event["advancement"]["kind"], []).append(event)
        current_by_kind: dict[str, list[dict[str, Any]]] = {}
        for event in event_list:
            current_by_kind.setdefault(event["advancement"]["kind"], []).append(event)
        level = next((e for e in event_list if e["advancement"]["kind"] == "level_advance"), None)
        fallback = level or (event_list[-1] if event_list else cumulative_events[-1])

        def composite(events: list[dict[str, Any]], rule_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
            chosen = events or [fallback]
            chosen = [e for e in chosen if e is not None]
            return {
                "event_ids": [e["event_id"] for e in chosen],
                "event_hashes": [e["event_hash"] for e in chosen],
                "catalog_record_ids": [e["subject"]["record_id"] for e in chosen],
                "catalog_record_hashes": [e["content_binding"]["record_hash"] for e in chosen],
                "acquisition_channels": [e["legal_channel"] for e in chosen],
                "source_evidence": [source for e in chosen for source in e["source_evidence"]],
                "calculation": {"rule_id": rule_id, "inputs": inputs, "outputs": {}},
            }

        def provider_for(pointer: str, value: Any) -> dict[str, Any]:
            top = pointer.split("/")[3] if pointer.startswith(f"/rows/{row_index}/") else "row"
            if top in {"cl", "pb", "hp", "resource_changes", "resources_after_level", "free_level_talents", "trained_choices", "legality"}:
                return composite([fallback], f"stage2.ledger.{top}.v1", {"cl": row["cl"]})
            if top in {"ability_score_effects", "ability_scores_after_level"}:
                events = current_by_kind.get("ability_score_change", []) or (by_kind.get("starting_state", [])[-1:] if row["cl"] == 1 else [])
                return composite(events, "stage2.ability-score-replay.v1", {"cl": row["cl"]})
            scalar_kinds = {
                "background": ["background_acquisition"],
                "background_sphere": ["background_sphere_acquisition"],
                "background_talent": ["background_talent_acquisition"],
                "origin_insight": ["origin_insight_acquisition"],
                "method": ["method_activation", "method_acquisition"],
                "foundation": ["foundation_stage", "foundation_expression", "foundation_acquisition"],
                "subpaths_after_level": ["subpath_acquisition", "typed_none"],
            }
            if top in scalar_kinds:
                events: list[dict[str, Any]] = []
                for kind in scalar_kinds[top]:
                    events.extend(by_kind.get(kind, []))
                return composite(events[-1:], f"stage2.ledger.{top}.v1", {"cl": row["cl"]})
            event_kind_fields = {
                "path_acquisitions": "path_acquisition",
                "subpath_acquisitions": "subpath_acquisition",
                "manual_acquisitions": "manual_acquisition",
                "forged_technique_acquisitions": "forged_technique_acquisition",
                "equipment_acquisitions": "equipment_acquisition",
                "new_sphere_acquisition": "sphere_acquisition",
            }
            if top in event_kind_fields:
                events = current_by_kind.get(event_kind_fields[top], [])
                if top == "new_sphere_acquisition":
                    events = events + [e for e in current_by_kind.get("talent_acquisition", []) if e["legal_channel"] == "new-sphere-bonus-talent"]
                return composite(events, f"stage2.ledger.{top}.v1", {"cl": row["cl"]})
            cumulative_fields = {
                "paths_after_level": "paths",
                "known_spheres_after_level": "known_spheres",
                "known_talents_after_level": "known_talents",
                "manuals_after_level": "manuals",
                "forged_techniques_after_level": "forged_techniques",
                "equipment_after_level": "equipment",
            }
            if top in cumulative_fields:
                ids: list[str] = []
                if isinstance(value, str) and value in by_id:
                    ids = [value]
                events = [by_id[x] for x in ids if x in by_id]
                return composite(events, f"stage2.cumulative-{cumulative_fields[top]}.v1", {"cl": row["cl"]})
            if top == "event_ids" and isinstance(value, str):
                return composite([by_event_id.get(value)], "stage2.event-membership.v1", {"cl": row["cl"]})
            return composite([fallback], "stage2.level-row-field.v1", {"cl": row["cl"], "pointer": pointer})

        def walk(pointer: str, value: Any) -> None:
            if isinstance(value, dict):
                if not value:
                    target[pointer] = provider_for(pointer, value)
                for key, child in value.items():
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    walk(f"{pointer}/{escaped}", child)
            elif isinstance(value, list):
                if not value:
                    target[pointer] = provider_for(pointer, value)
                for index, child in enumerate(value):
                    walk(f"{pointer}/{index}", child)
            else:
                target[pointer] = provider_for(pointer, value)

        prefix = f"/rows/{row_index}"
        for key, value in row.items():
            if key == "row_hash":
                continue
            walk(f"{prefix}/{key}", value)
        target[f"{prefix}/row_hash"] = composite(event_list, "stage2.level-row-hash.v1", {"row_without_hash_sha256": sha256_json({k: v for k, v in row.items() if k != "row_hash"})})

    @staticmethod
    def _provenance(event:dict[str,Any])->dict[str,Any]:
        return {"event_id":event["event_id"],"event_hash":event["event_hash"],"catalog_record_id":event["subject"]["record_id"],"catalog_record_hash":event["content_binding"]["record_hash"],"acquisition_channel":event["legal_channel"],"source_evidence":event["source_evidence"],"calculation":event["advancement"]["calculation"]}

    @staticmethod
    def _composite_provenance(events: list[dict[str, Any]], rule_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_ids": [e["event_id"] for e in events],
            "event_hashes": [e["event_hash"] for e in events],
            "catalog_record_ids": [e["subject"]["record_id"] for e in events],
            "catalog_record_hashes": [e["content_binding"]["record_hash"] for e in events],
            "acquisition_channels": [e["legal_channel"] for e in events],
            "source_evidence": [source for e in events for source in e["source_evidence"]],
            "calculation": {"rule_id": rule_id, "inputs": inputs, "outputs": {}},
        }

    @staticmethod
    def _leaf_pointers(value: Any, pointer: str = "") -> set[str]:
        pointers: set[str] = set()
        if isinstance(value, dict):
            if not value:
                pointers.add(pointer or "/")
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                pointers |= Stage2AdvancementService._leaf_pointers(child, f"{pointer}/{escaped}")
        elif isinstance(value, list):
            if not value:
                pointers.add(pointer or "/")
            for index, child in enumerate(value):
                pointers |= Stage2AdvancementService._leaf_pointers(child, f"{pointer}/{index}")
        else:
            pointers.add(pointer or "/")
        return pointers

    @staticmethod
    def _orphaned_final_elements(state: dict[str, Any]) -> list[dict[str, Any]]:
        record_events = state.get("record_event_ids", {})
        candidates: list[tuple[str, str]] = []
        scalar = {
            "/background": state.get("background"),
            "/background_sphere": state.get("background_sphere"),
            "/background_talent": state.get("background_talent"),
            "/origin_insight": state.get("origin_insight"),
        }
        for pointer, record_id in scalar.items():
            if isinstance(record_id, str):
                candidates.append((pointer, record_id))
        for field in ("paths", "known_spheres", "known_talents", "manuals", "forged_techniques", "equipment"):
            for index, record_id in enumerate(state.get(field, []) if isinstance(state.get(field), list) else []):
                candidates.append((f"/{field}/{index}", record_id))
        if isinstance(state.get("subpaths"), list):
            for index, record_id in enumerate(state["subpaths"]):
                candidates.append((f"/subpaths/{index}", record_id))
        for field in ("method", "foundation"):
            value = state.get(field)
            if isinstance(value, dict):
                for key in ("record_id", "path_expression"):
                    record_id = value.get(key)
                    if isinstance(record_id, str):
                        candidates.append((f"/{field}/{key}", record_id))
        return [
            {"pointer": pointer, "record_id": record_id, "reason": "No causal Advancement Event exists for this final-state record."}
            for pointer, record_id in candidates
            if record_id not in record_events
        ]

    def _current_state(self, conn, project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        events=self._existing_v2_events(conn,project_id)
        state,rows,prov=self._state_from_events(events,project_id)
        return state,rows,prov,events

    def _authority(self, record:dict[str,Any])->dict[str,Any]:
        return record["compatibility"]["factory"]["stage2_authority"]

    def _prerequisite_blockers(self, record:dict[str,Any], state:dict[str,Any], pointer:str)->list[dict[str,Any]]:
        selected=set(state["record_event_ids"])
        out=[]
        for prereq in record.get("legality",{}).get("prerequisites",[]):
            target=prereq.get("target_id")
            if prereq.get("operator")=="requires" and target not in selected:
                out.append(_block("PREREQUISITE_NOT_ACQUIRED",pointer,"A required published record has no earlier causal event.",record_id=record["record_id"],required_record_id=target))
        return out

    def _choice_to_event(self, *, conn, project_id:str, choice:dict[str,Any], pointer:str, state:dict[str,Any], sequence:int, project_revision:int, previous_event_hash:str, generic_before_hash:str, created_at:str, event_id:str) -> tuple[dict[str,Any]|None,dict[str,Any],list[dict[str,Any]]]:
        kind=choice["kind"]; rid=choice.get("record_id")
        if not rid:
            return None,state,[_block("CATALOG_RECORD_ID_REQUIRED",pointer+"/record_id","Every mechanical Stage 2 choice requires a published project-locked authority record.",kind=kind)]
        record, blockers=self._record(conn,project_id,rid,pointer+"/record_id")
        if blockers or record is None: return None,state,blockers
        auth=self._authority(record)
        if kind not in auth.get("allowed_kinds",[]):
            return None,state,[_block("AUTHORITY_KIND_MISMATCH",pointer,"The record does not authorize this Advancement Event kind.",record_id=rid,kind=kind,allowed=auth.get("allowed_kinds",[]))]
        cl=int(choice["effective_cl"])
        if cl < int(record.get("legality",{}).get("minimum_cl") or 0):
            blockers.append(_block("ACQUISITION_BEFORE_MINIMUM_CL",pointer+"/effective_cl","The record is not legal at the requested CL.",record_id=rid,minimum_cl=record["legality"]["minimum_cl"],effective_cl=cl))
        channel=choice["acquisition_channel"]
        allowed=record.get("legality",{}).get("acquisition_channels",[])
        if channel not in allowed:
            blockers.append(_block("INVALID_ACQUISITION_CHANNEL",pointer+"/acquisition_channel","The requested channel is not published for this record.",record_id=rid,channel=channel,allowed=allowed))
        blockers += self._prerequisite_blockers(record,state,pointer)
        params=choice.get("parameters") or {}
        details={"parameters":deepcopy(params)}
        calc_rule=auth.get("rule_id")
        if not calc_rule:
            blockers.append(_block("MISSING_CALCULATION_RULE",pointer,"The authority does not name a deterministic calculation rule.",record_id=rid))
            calc_rule="missing"
        inputs={"effective_cl":cl,"parameters":deepcopy(params),"state_before_hash":sha256_json(state)}
        outputs={}
        next_state=_copy_state(state)
        none_state=None
        prereq_event_ids=[state["record_event_ids"][x] for x in record.get("dependencies",[]) if x in state["record_event_ids"]]

        if kind == "starting_state":
            scores=params.get("ability_scores")
            if not isinstance(scores,dict) or set(scores)!={"STR","DEX","CON","INT","WIS","CHA"} or any(not isinstance(v,int) or v<1 or v>30 for v in scores.values()):
                blockers.append(_block("ABILITY_SCORE_START_STATE_INVALID",pointer+"/parameters/ability_scores","Starting state requires all six integer ability scores from 1 to 30."))
            else:
                outputs={"ability_scores":scores,"ability_modifiers":{k:_ability_modifier(v) for k,v in scores.items()}}
        elif kind == "ability_score_change":
            if not state["ability_scores"]: blockers.append(_block("ABILITY_SCORES_NOT_INITIALIZED",pointer,"Ability scores require an earlier starting-state event."))
            deltas=params.get("deltas")
            if not isinstance(deltas,dict) or any(k not in state["ability_scores"] or not isinstance(v,int) for k,v in (deltas or {}).items()):
                blockers.append(_block("ABILITY_SCORE_DELTA_INVALID",pointer+"/parameters/deltas","Ability-score change requires integer deltas for known abilities."))
            else:
                scores={k:v+deltas.get(k,0) for k,v in state["ability_scores"].items()}
                outputs={"ability_scores":scores,"ability_modifiers":{k:_ability_modifier(v) for k,v in scores.items()}}
        elif kind == "path_acquisition":
            if state["current_cl"]>cl: blockers.append(_block("PATH_ACQUISITION_RETROACTIVE",pointer,"Path acquisition cannot be inserted before the current committed CL."))
            outputs={"path_id":rid}
        elif kind == "level_advance":
            if cl != state["current_cl"]+1: blockers.append(_block("LEVEL_SEQUENCE_INVALID",pointer+"/effective_cl","Level-advance events must form an exact CL1-current sequence.",expected_cl=state["current_cl"]+1,requested_cl=cl))
            if not state["paths"]: blockers.append(_block("PATH_REQUIRED_FOR_LEVEL_CALCULATION",pointer,"A Path acquisition event is required before HP and resource calculations."))
            if not state["ability_scores"]: blockers.append(_block("STARTING_ABILITY_SCORES_REQUIRED",pointer,"A starting-state event is required before HP calculation."))
            path_record=None; path_auth=None
            if state["paths"]:
                path_record=self.projects._resolve_locked_record(conn,project_id,state["paths"][0])
                path_auth=(path_record or {}).get("compatibility",{}).get("factory",{}).get("stage2_authority",{})
            hp=(path_auth or {}).get("hp")
            resources=(path_auth or {}).get("resources")
            if not isinstance(hp,dict): blockers.append(_block("PATH_HP_AUTHORITY_MISSING",pointer,"The active Path lacks structured HP authority."))
            if not isinstance(resources,list): blockers.append(_block("PATH_RESOURCE_AUTHORITY_MISSING",pointer,"The active Path lacks structured resource authority."))
            if not blockers:
                ability=hp.get("ability","CON"); mod=state["ability_modifiers"].get(ability)
                if mod is None: blockers.append(_block("HP_ABILITY_MODIFIER_MISSING",pointer,"The HP rule names an unavailable ability modifier.",ability=ability))
                else:
                    base=hp.get("level1_base") if cl==1 else hp.get("later_base")
                    if not isinstance(base,int): blockers.append(_block("HP_FORMULA_AUTHORITY_INCOMPLETE",pointer,"The Path HP rule lacks an integer level base."))
                    else:
                        gain=max(1,base+mod); res_after=deepcopy(state["resources"]); res_gains={}
                        for rr in resources:
                            res_id=rr.get("resource_id"); amount=rr.get("level1") if cl==1 else rr.get("per_level")
                            if not isinstance(res_id,str) or not isinstance(amount,int): blockers.append(_block("RESOURCE_FORMULA_AUTHORITY_INCOMPLETE",pointer,"A Path resource rule is incomplete.",rule=rr)); continue
                            res_gains[res_id]=amount; res_after[res_id]=int(res_after.get(res_id,0))+amount
                        outputs={
                            "pb":_pb(cl),
                            "hp_gain":gain,
                            "hp_total":state["hp_total"]+gain,
                            "hp_formula":{"rule_id":hp.get("rule_id"),"base":base,"ability":ability,"modifier":mod,"minimum":1},
                            "resource_gains":res_gains,
                            "resource_formulas":{rr["resource_id"]:{"rule_id":rr.get("rule_id", f"{path_record['record_id']}.resource.v1"),"amount":rr.get("level1") if cl==1 else rr.get("per_level"),"level_kind":"level1" if cl==1 else "later_level"} for rr in resources if isinstance(rr,dict) and isinstance(rr.get("resource_id"),str)},
                            "resources_after":res_after,
                            "free_level_talent_capacity":path_auth.get("free_level_talents_per_cl"),
                            "trained_choice_capacity":path_auth.get("trained_choice_capacity_per_cl"),
                        }
        elif kind == "method_activation":
            acquired=state.get("method",{}).get("record_id") == rid
            if not acquired: blockers.append(_block("METHOD_NOT_ACQUIRED",pointer,"Method activation requires an earlier acquisition event for the same record.",record_id=rid))
            min_active=int(auth.get("activation_min_cl",record["legality"].get("minimum_cl") or 0))
            if cl<min_active: blockers.append(_block("METHOD_ACTIVATED_TOO_EARLY",pointer,"Method activation precedes its published activation CL.",minimum_cl=min_active,effective_cl=cl))
            outputs={"method_id":rid,"status":"active"}
        elif kind == "foundation_expression":
            foundation_id=auth.get("foundation_record_id"); path_id=auth.get("path_id")
            if not foundation_id or not path_id: blockers.append(_block("FOUNDATION_EXPRESSION_AUTHORITY_INCOMPLETE",pointer,"Foundation expression requires exact foundation and Path IDs."))
            if state.get("foundation",{}).get("record_id") != foundation_id: blockers.append(_block("FOUNDATION_NOT_ACQUIRED",pointer,"The expression does not match the acquired Foundation.",required_foundation_id=foundation_id))
            if path_id not in state["paths"]: blockers.append(_block("FOUNDATION_PATH_EXPRESSION_MISMATCH",pointer,"The Foundation expression does not match an acquired Path.",required_path_id=path_id,active_paths=state["paths"]))
            details.update({"foundation_record_id":foundation_id,"path_id":path_id}); outputs={"foundation_expression_id":rid}
        elif kind == "foundation_stage":
            stages=auth.get("stage_order") or ["awakened","refined","perfected"]
            requested=params.get("stage")
            current=state.get("foundation",{}).get("stage")
            expected=stages[0] if current is None else (stages[stages.index(current)+1] if current in stages and stages.index(current)+1<len(stages) else None)
            if requested != expected: blockers.append(_block("FOUNDATION_STAGE_PROGRESSION_INVALID",pointer+"/parameters/stage","Foundation stages must advance exactly one published step.",current=current,expected=expected,requested=requested))
            min_by_stage=auth.get("minimum_cl_by_stage",{})
            if requested in min_by_stage and cl<int(min_by_stage[requested]): blockers.append(_block("FOUNDATION_STAGE_TOO_EARLY",pointer,"Foundation stage precedes its published CL.",stage=requested,minimum_cl=min_by_stage[requested]))
            details["stage"]=requested; outputs={"stage":requested}
        elif kind == "talent_acquisition":
            if channel == "free-level-talent":
                path_record=self.projects._resolve_locked_record(conn,project_id,state["paths"][0]) if state["paths"] else None
                cap=((path_record or {}).get("compatibility",{}).get("factory",{}).get("stage2_authority",{}).get("free_level_talents_per_cl"))
                used=len(state["free_level_talents"].get(str(cl),[]))
                if not isinstance(cap,int): blockers.append(_block("FREE_LEVEL_TALENT_AUTHORITY_MISSING",pointer,"The active Path does not publish free-level-talent capacity."))
                elif used+1>cap: blockers.append(_block("FREE_LEVEL_TALENT_CAPACITY_EXCEEDED",pointer,"The free level talent capacity is exceeded.",capacity=cap,used=used))
            if channel == "trained-choice":
                path_record=self.projects._resolve_locked_record(conn,project_id,state["paths"][0]) if state["paths"] else None
                cap=((path_record or {}).get("compatibility",{}).get("factory",{}).get("stage2_authority",{}).get("trained_choice_capacity_per_cl"))
                used=len(state["trained_choices"].get(str(cl),[])); cost=int(auth.get("trained_choice_cost",1))
                if not isinstance(cap,int): blockers.append(_block("TRAINED_CHOICE_AUTHORITY_MISSING",pointer,"The active Path does not publish trained-choice capacity."))
                elif used+cost>cap: blockers.append(_block("TRAINED_CHOICE_CAPACITY_EXCEEDED",pointer,"Trained-choice capacity is exceeded.",capacity=cap,used=used,cost=cost))
            if channel == "new-sphere-bonus-talent":
                bonus=state["new_sphere_bonus"].get(str(cl))
                required_sphere=auth.get("sphere_id")
                if not bonus or not bonus.get("sphere_event_id") or bonus.get("talent_event_id"):
                    blockers.append(_block("ILLEGAL_NEW_SPHERE_BONUS",pointer,"A bonus talent requires one unmatched new-Sphere acquisition at the same CL."))
                if required_sphere and required_sphere not in state["known_spheres"]:
                    blockers.append(_block("NEW_SPHERE_BONUS_SPHERE_MISMATCH",pointer,"The bonus talent does not belong to the newly acquired Sphere.",required_sphere_id=required_sphere))
            outputs={"talent_id":rid,"channel":channel}
        elif kind == "manual_acquisition":
            fixed=auth.get("fixed_expression")
            required_keys={"sphere_id","technique_name","reproduced_record_id","dc","timing","cost","range","target","resolution","effect","failure","duration","limits","counterplay"}
            if not isinstance(fixed,dict) or not required_keys.issubset(fixed): blockers.append(_block("MANUAL_FIXED_EXPRESSION_AUTHORITY_MISSING",pointer,"Recorded Art acquisition requires a complete published fixed-expression source.",required=sorted(required_keys)))
            outputs={"manual_id":rid,"fixed_expression":deepcopy(fixed)}
        elif kind == "forged_technique_acquisition":
            if channel != "forged_technique_creation": blockers.append(_block("FORGED_TECHNIQUE_EVENT_REQUIRED",pointer,"Forged Techniques require the published forging acquisition channel."))
            min_forge=int(auth.get("minimum_forging_cl",record["legality"].get("minimum_cl") or 0))
            if cl<min_forge: blockers.append(_block("FORGED_TECHNIQUE_BEFORE_LEGAL_LEVEL",pointer,"The Forged Technique precedes its published legal CL.",minimum_cl=min_forge,effective_cl=cl))
            if not auth.get("forging_recipe_id"): blockers.append(_block("FORGING_AUTHORITY_INCOMPLETE",pointer,"The published record lacks a deterministic forging recipe ID."))
            outputs={"forged_technique_id":rid,"forging_recipe_id":auth.get("forging_recipe_id")}
        elif kind == "typed_none":
            reason_code=choice.get("reason_code"); reason=choice.get("reason")
            target=auth.get("none_target")
            if not reason_code or not reason or not target: blockers.append(_block("TYPED_NONE_INCOMPLETE",pointer,"Typed absence requires a published target plus explicit reason code and reason."))
            elif PLACEHOLDER_RE.match(reason.strip()): blockers.append(_block("PLACEHOLDER_FORBIDDEN",pointer+"/reason","Typed absence cannot use placeholder text."))
            none_state={"state":"none","reason_code":reason_code,"reason":reason,"source_backed":True}; details["target"]=target; outputs={"target":target,"none_state":none_state}
        else:
            outputs={"record_id":rid,"kind":kind}

        if blockers: return None,state,blockers
        # Create a provisional event, apply it mechanically, then bind both mechanical and generic hashes.
        event_type="evolve" if kind in {"level_advance","ability_score_change","method_activation","foundation_stage"} else "author_metadata" if kind=="starting_state" else "acquire"
        created=[rid] if event_type=="acquire" else []
        updated=[rid] if event_type=="evolve" else []
        adv={"kind":kind,"target_cl":cl,"calculation":{"rule_id":calc_rule,"inputs":inputs,"outputs":outputs},"prerequisite_record_ids":[x.get("target_id") for x in record.get("legality",{}).get("prerequisites",[]) if x.get("operator")=="requires"],"prerequisite_event_ids":prereq_event_ids,"details":details,"none_state":none_state}
        binding=record["content_binding"]
        event={
            "schema_version":EVENT_VERSION,"event_id":event_id,"project_id":project_id,"project_revision":project_revision,"sequence":sequence,"event_type":event_type,
            "effective_point":{"kind":"level" if cl>=1 else "background_creation","character_cl":cl,"order":sequence},"legal_channel":channel,
            "subject":{"record_id":rid,"content_type":record["content_type"],"display_name":record["display_name"]},
            "content_binding":{"pack_id":binding["pack_id"],"pack_version":binding["pack_version"],"pack_hash":binding["pack_hash"],"record_hash":record["record_hash"],"catalog_build_id":self._catalog_build_id(conn)},
            "source_evidence":_source_evidence(record),"training":None,"created_records":created,"updated_records":updated,"retired_records":[],"planner_response_id":None,"supersedes_event_ids":[],"migration":None,
            "idempotency_key":event_id,"previous_event_hash":previous_event_hash,"state_before_hash":generic_before_hash,"state_after_hash":ZERO_HASH,"event_hash":ZERO_HASH,"created_at":created_at,"advancement":adv,
        }
        # Mechanical next state and hashes are deterministic calculations, not authored inputs.
        next_state=self._apply_event(state,event)
        event["advancement"]["calculation"]["outputs"]["mechanical_state_before_hash"]=sha256_json(state)
        event["advancement"]["calculation"]["outputs"]["mechanical_state_after_hash"]=sha256_json(next_state)
        return event,next_state,[]

    def _catalog_build_id(self, conn)->str:
        row=conn.execute("SELECT build_id FROM catalog_builds ORDER BY created_at DESC LIMIT 1").fetchone()
        return row[0] if row else "catalog.unbuilt"

    def _compile_proposal(self, conn, row) -> dict[str,Any]:
        proposal=json.loads(row["proposal_json"]); project_row,project=self._project_row(conn,row["project_id"])
        blockers=[]
        if project_row["revision"] != row["expected_project_revision"]: blockers.append(_block("STALE_PROJECT_REVISION","/expected_project_revision","The project revision changed after proposal creation.",expected=row["expected_project_revision"],actual=project_row["revision"]))
        if project["content_lock"]["lock_hash"] != row["expected_content_lock_hash"]: blockers.append(_block("STALE_CONTENT_LOCK","/expected_content_lock_hash","The content lock changed after proposal creation."))
        state,_,_,existing_v2=self._current_state(conn,row["project_id"])
        all_events=self.projects._event_rows(conn,row["project_id"])
        generic_prefix=list(all_events)
        last=conn.execute("SELECT sequence_no,event_hash FROM events WHERE project_id=? ORDER BY sequence_no DESC LIMIT 1",(row["project_id"],)).fetchone()
        sequence=(last[0]+1) if last else 1; previous=(last[1] if last else ZERO_HASH)
        base_revision=int(project_row["revision"])
        compiled=[]
        choices=[json.loads(r[0]) for r in conn.execute("SELECT event_request_json FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal",(row["proposal_id"],))]
        for index,choice in enumerate(choices):
            pointer=f"/choices/{index}"
            generic_before=sha256_json(self.projects._reduce_events(generic_prefix,row["project_id"],conn))
            event_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"tianxia-stage2-event:{row['proposal_id']}:{index+1}:{sha256_json(choice)}"))
            event,next_state,issues=self._choice_to_event(conn=conn,project_id=row["project_id"],choice=choice,pointer=pointer,state=state,sequence=sequence+index,project_revision=base_revision+index+1,previous_event_hash=previous,generic_before_hash=generic_before,created_at=row["created_at"],event_id=event_id)
            blockers.extend(issues)
            if event is None: continue
            generic_after=self.projects._reduce_events(generic_prefix+[event],row["project_id"],conn)
            event["state_after_hash"]=sha256_json(generic_after)
            event["event_hash"]=canonical_event_hash(event)
            try: self.registry.validate(event)
            except Exception as exc: blockers.append(_block("ADVANCEMENT_EVENT_SCHEMA_INVALID",pointer,"The deterministic event failed the canonical v2 schema.",diagnostics=getattr(exc,"to_dict",lambda:{"message":str(exc)})()))
            compiled.append(event); generic_prefix.append(event); previous=event["event_hash"]; state=next_state
        # Required exact CL sequence and target.
        if state["current_cl"] != int(row["target_cl"]): blockers.append(_block("TARGET_CL_NOT_REACHED","/target_cl","The proposed event set does not deterministically reach the requested target CL.",target_cl=row["target_cl"],replayed_cl=state["current_cl"]))
        # New-Sphere bonus pairs must close at each CL.
        for clkey,pair in state["new_sphere_bonus"].items():
            if pair.get("sphere_event_id") and not pair.get("talent_event_id"): blockers.append(_block("NEW_SPHERE_BONUS_MISSING",f"/level/{clkey}","A new-Sphere acquisition requires its causal bonus-talent event at the same CL."))
        report={"schema_version":BLOCKER_VERSION,"project_id":row["project_id"],"project_revision":project_row["revision"],"blocked":bool(blockers),"blockers":blockers}
        self.registry.validate(report)
        return {"valid":not blockers,"blocker_report":report,"compiled_events":compiled,"mechanical_state":state,"mechanical_state_hash":sha256_json(state),"validated_at":utcnow()}

    def validate_proposal(self, proposal_id:str)->dict[str,Any]:
        with self.db.transaction() as conn:
            row=self._proposal_row(conn,proposal_id)
            validation=self._compile_proposal(conn,row)
            status="validated" if validation["valid"] else "blocked"
            conn.execute("UPDATE stage2_proposals SET status=?,validation_json=?,updated_at=? WHERE proposal_id=?",(status,canonical_json(validation),utcnow(),proposal_id))
            conn.execute("DELETE FROM stage2_blockers WHERE proposal_id=?",(proposal_id,))
            for b in validation["blocker_report"]["blockers"]:
                conn.execute("INSERT INTO stage2_blockers(blocker_id,project_id,project_revision,proposal_id,blocker_code,severity,pointer,message,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),row["project_id"],row["expected_project_revision"],proposal_id,b["code"],b["severity"],b["pointer"],b["message"],canonical_json(b["details"]),utcnow()))
            return {"proposal_id":proposal_id,"status":status,**validation}

    @staticmethod
    def _legacy_approval_projection(validation: dict[str, Any]) -> dict[str, Any]:
        projected = deepcopy(validation)
        projected.pop("validated_at", None)
        return projected

    def _legacy_approval_material(self, conn, row) -> tuple[bytes, dict[str, Any], str]:
        if not row["validation_json"]:
            raise FoundryError("STAGE2_PROPOSAL_NOT_VALIDATED", "The proposal has no persisted validation evidence.")
        validation = json.loads(row["validation_json"])
        children = [
            {
                "ordinal": int(child["ordinal"]),
                "event_request_json": child["event_request_json"],
                "event_request_hash": child["event_request_hash"],
            }
            for child in conn.execute(
                "SELECT ordinal,event_request_json,event_request_hash FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal",
                (row["proposal_id"],),
            )
        ]
        _project_row, project = self._project_row(conn, row["project_id"])
        lock_hash = project["content_lock"]["lock_hash"]
        projection = {
            "schema_version": "TianxiaFoundry.LegacyStage2ApprovalMaterial.v1",
            "proposal_id": row["proposal_id"],
            "project_id": row["project_id"],
            "proposal_json": row["proposal_json"],
            "validation": self._legacy_approval_projection(validation),
            "children": children,
            "project_lock_hash": lock_hash,
        }
        binding = {
            "proposal_hash": sha256_bytes(row["proposal_json"].encode("utf-8")),
            "validation_hash": sha256_json(self._legacy_approval_projection(validation)),
            "child_hashes": [child["event_request_hash"] for child in children],
            "project_lock_hash": lock_hash,
        }
        return canonical_json(projection).encode("utf-8"), binding, lock_hash

    def issue_approval_challenge(self, proposal_id: str, *, ttl_seconds: int = 300) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = self._proposal_row(conn, proposal_id)
            if row["status"] != "validated":
                raise FoundryError(
                    "STAGE2_PROPOSAL_NOT_VALIDATED",
                    "Only an unblocked validated proposal may receive an approval challenge.",
                    details={"status": row["status"]},
                )
            exact, binding, lock_hash = self._legacy_approval_material(conn, row)
        return self.challenges.issue(
            operation="legacy_stage2_approve",
            subject_type="stage2_proposal_v1",
            subject_id=proposal_id,
            exact_bytes=exact,
            binding=binding,
            project_lock_hash=lock_hash,
            ttl_seconds=ttl_seconds,
        )

    def approve_proposal(
        self,
        proposal_id: str,
        approved_by: str | None = None,
        *,
        challenge_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        if not challenge_id or not nonce:
            raise FoundryError(
                "APPROVAL_CHALLENGE_REQUIRED",
                "Legacy Stage 2 approval requires a server-issued one-time exact-byte challenge.",
                status_code=409,
            )
        with self.db.connection() as conn:
            initial = self._proposal_row(conn, proposal_id)
            if initial["status"] != "validated":
                raise FoundryError(
                    "STAGE2_PROPOSAL_NOT_VALIDATED",
                    "Only an unblocked validated proposal may be approved.",
                    details={"status": initial["status"]},
                )
            exact, binding, lock_hash = self._legacy_approval_material(conn, initial)
        principal = self.challenges.principal()

        def protected_approval(conn, evidence):
            row = self._proposal_row(conn, proposal_id)
            if row["status"] != "validated":
                raise FoundryError(
                    "STAGE2_PROPOSAL_NOT_VALIDATED",
                    "Only an unblocked validated proposal may be approved.",
                    details={"status": row["status"]},
                )
            current_exact, current_binding, current_lock = self._legacy_approval_material(conn, row)
            if current_exact != exact or current_binding != binding or current_lock != lock_hash:
                raise FoundryError(
                    "STAGE2_APPROVAL_MATERIAL_CHANGED",
                    "The exact legacy approval material changed before challenge consumption.",
                    status_code=409,
                )
            validation = self._compile_proposal(conn, row)
            if not validation["valid"]:
                raise FoundryError(
                    "STAGE2_PROPOSAL_REVALIDATION_FAILED",
                    "The proposal became blocked before approval.",
                    details=validation["blocker_report"],
                )
            persisted = json.loads(row["validation_json"])
            if self._legacy_approval_projection(validation) != self._legacy_approval_projection(persisted):
                raise FoundryError(
                    "STAGE2_APPROVAL_MATERIAL_CHANGED",
                    "The deterministic legacy validation changed before challenge consumption.",
                    status_code=409,
                )
            now = utcnow()
            conn.execute(
                """UPDATE stage2_proposals SET status='approved',approved_by=?,approved_at=?,
                   approved_principal_id=?,approval_challenge_id=?,approval_evidence_id=?,updated_at=?
                   WHERE proposal_id=?""",
                (
                    principal.display_name,
                    now,
                    principal.principal_id,
                    challenge_id,
                    evidence["evidence_id"],
                    now,
                    proposal_id,
                ),
            )
            return {"proposal_id": proposal_id}

        _evidence, result = self.challenges.consume_with_action(
            challenge_id=challenge_id,
            nonce=nonce,
            operation="legacy_stage2_approve",
            subject_type="stage2_proposal_v1",
            subject_id=proposal_id,
            exact_bytes=exact,
            binding=binding,
            project_lock_hash=lock_hash,
            evidence_context={"proposal_id": proposal_id, "legacy_schema_version": PROPOSAL_VERSION},
            action=protected_approval,
        )
        assert result is not None
        return self.get_proposal(proposal_id)

    def _update_project_after_batch(self,conn,project_id:str,replay:dict[str,Any],event_ids:list[str],state_hash:str,proposal_id:str,final_revision:int)->dict[str,Any]:
        row,old=self._project_row(conn,project_id)
        commits=list(old.get("stage_commits") or [])
        commits.append({"stage":2,"revision":final_revision,"status":"sealed","state_hash":state_hash,"prompt_packet_ids":[],"response_ids":[proposal_id],"event_ids":event_ids})
        updated=canonical_project_document(project_id=project_id,name=old["name"],revision=final_revision,status="stage_2",created_at=old["created_at"],updated_at=utcnow(),catalog_build_id=old["content_lock"]["catalog_build_id"],pack_locks=self.projects._project_locks(conn,project_id),user_locks=old["user_locks"],source_inputs=old["source_inputs"],event_count=replay["event_count"],head_hash=replay["latest_event_hash"],active_stage=2,stage_commits=commits,generated_artifacts=old["generated_artifacts"],candidates=old["candidates"],acceptance=old["acceptance"])
        self.registry.validate(updated)
        conn.execute("UPDATE projects SET status=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?",(updated["status"],final_revision,updated["updated_at"],canonical_json(updated),canonical_project_hash(updated),updated["schema_version"],project_id))
        return updated

    def commit_proposal(self,proposal_id:str,*,simulate_crash_after:int|None=None)->dict[str,Any]:
        # Existing committed receipt is the idempotency authority.
        with self.db.connection() as conn:
            existing=conn.execute("SELECT * FROM stage2_commit_receipts WHERE proposal_id=? AND status='committed'",(proposal_id,)).fetchone()
            if existing:
                return {"committed":True,"idempotent":True,"receipt":dict(existing),"ledger":self.ledger(existing["project_id"])}
        commit_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"tianxia-stage2-commit:{proposal_id}"))
        try:
            with self.db.transaction() as conn:
                row=self._proposal_row(conn,proposal_id)
                if row["status"] != "approved" or not row["approved_by"]: raise FoundryError("STAGE2_NAMED_APPROVAL_REQUIRED","The proposal requires named human approval before commit.")
                validation=self._compile_proposal(conn,row)
                if not validation["valid"]: raise FoundryError("STAGE2_PROPOSAL_REVALIDATION_FAILED","The approved proposal is now blocked.",details=validation["blocker_report"])
                events=validation["compiled_events"]
                before=self.projects._replay_events(conn,row["project_id"])
                conn.execute("INSERT INTO stage2_commit_receipts(commit_id,proposal_id,project_id,status,base_revision,event_ids_json,event_hashes_json,state_before_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(commit_id,proposal_id,row["project_id"],"started",row["expected_project_revision"],"[]","[]",before["state_hash"],utcnow()))
                conn.execute("UPDATE stage2_proposals SET status='committing',updated_at=? WHERE proposal_id=?",(utcnow(),proposal_id))
                for index,event in enumerate(events,start=1):
                    conn.execute("INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)",(event["project_id"],event["sequence"],event["event_id"],event["event_hash"],event["previous_event_hash"],event["created_at"],canonical_json(event),None,event["schema_version"],"valid"))
                    record=self.projects._resolve_locked_record(conn,event["project_id"],event["subject"]["record_id"])
                    binding=record["content_binding"]
                    conn.execute("INSERT OR REPLACE INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",(event["project_id"],record["record_id"],binding["pack_id"],binding["pack_version"],record["record_hash"],canonical_json(record)))
                    if simulate_crash_after is not None and index>=simulate_crash_after: raise RuntimeError("SIMULATED_STAGE2_CRASH")
                replay=self.projects._replay_events(conn,row["project_id"])
                final_revision=int(row["expected_project_revision"])+len(events)
                project=self._update_project_after_batch(conn,row["project_id"],replay,[e["event_id"] for e in events],validation["mechanical_state_hash"],proposal_id,final_revision)
                conn.execute("UPDATE stage2_proposals SET status='committed',updated_at=? WHERE proposal_id=?",(utcnow(),proposal_id))
                conn.execute("UPDATE stage2_commit_receipts SET status='committed',final_revision=?,event_ids_json=?,event_hashes_json=?,state_after_hash=?,completed_at=? WHERE commit_id=?",(final_revision,canonical_json([e["event_id"] for e in events]),canonical_json([e["event_hash"] for e in events]),replay["state_hash"],utcnow(),commit_id))
            artifacts=self.rebuild(row["project_id"])
            return {"committed":True,"idempotent":False,"commit_id":commit_id,"event_count":len(events),"event_ids":[e["event_id"] for e in events],"project":project,"replay":replay,"stage2":artifacts}
        except Exception as exc:
            # The event transaction has rolled back. Persist a crash/failure receipt separately.
            with self.db.transaction() as conn:
                row=conn.execute("SELECT project_id,expected_project_revision FROM stage2_proposals WHERE proposal_id=?",(proposal_id,)).fetchone()
                if row:
                    conn.execute("INSERT OR REPLACE INTO stage2_commit_receipts(commit_id,proposal_id,project_id,status,base_revision,event_ids_json,event_hashes_json,state_before_hash,error_json,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(commit_id,proposal_id,row["project_id"],"rolled_back",row["expected_project_revision"],"[]","[]",ZERO_HASH,canonical_json({"type":type(exc).__name__,"message":str(exc)}),utcnow(),utcnow()))
                    conn.execute("UPDATE stage2_proposals SET status='approved',updated_at=? WHERE proposal_id=?",(utcnow(),proposal_id))
            if isinstance(exc,FoundryError): raise
            raise FoundryError("STAGE2_ATOMIC_COMMIT_ROLLED_BACK","The Stage 2 batch failed and the complete transaction was rolled back.",details={"error":str(exc)})

    # ---------- projections and reconciliation ----------
    def _ledger_document(self, project: dict[str, Any], events: list[dict[str, Any]], state: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        ledger = {
            "schema_version": LEDGER_VERSION,
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "content_lock_hash": project["content_lock"]["lock_hash"],
            "event_head_hash": project["event_stream"].get("head_hash"),
            "target_cl": state["current_cl"],
            "rows": rows,
            "final_state_hash": sha256_json(state),
            "generated_at_rule": "deterministic-no-wall-clock",
        }
        self.registry.validate(ledger)
        return ledger

    def _markdown(self, ledger: dict[str, Any]) -> str:
        lines = [
            "# Tianxia Leveling Ledger",
            f"Project: `{ledger['project_id']}`",
            f"Revision: **{ledger['project_revision']}**",
            f"Target CL: **{ledger['target_cl']}**",
            "",
        ]
        for row in ledger["rows"]:
            resources = "; ".join(
                f"{resource_id}: +{data['gain']} → {data['total']}"
                for resource_id, data in sorted(row["resource_changes"].items())
            ) or "None (typed empty collection)"
            new_sphere = row["new_sphere_acquisition"]
            if new_sphere.get("state") == "acquired":
                new_sphere_text = f"{', '.join(new_sphere['sphere_record_ids'])} + bonus {', '.join(new_sphere['bonus_talent_record_ids'])}"
            else:
                new_sphere_text = f"None — {new_sphere['reason_code']}"
            lines += [
                f"## CL {row['cl']}",
                f"- PB: **+{row['pb']}**",
                f"- HP: +{row['hp']['gain']} → **{row['hp']['total']}**",
                f"- Resources: {resources}",
                f"- Ability scores after level: `{canonical_json(row['ability_scores_after_level'])}`",
                f"- Background: `{canonical_json(row['background'])}`",
                f"- Background Sphere: `{canonical_json(row['background_sphere'])}`",
                f"- Background Talent: `{canonical_json(row['background_talent'])}`",
                f"- Origin Insight: `{canonical_json(row['origin_insight'])}`",
                f"- Paths after level: {', '.join(row['paths_after_level'])}",
                f"- Subpaths after level: `{canonical_json(row['subpaths_after_level'])}`",
                f"- Method: `{canonical_json(row['method'])}`",
                f"- Foundation: `{canonical_json(row['foundation'])}`",
                f"- Free level talents: {row['free_level_talents']['used']}/{row['free_level_talents']['capacity']} — {', '.join(row['free_level_talents']['record_ids']) or 'None (typed empty collection)'}",
                f"- Trained choices: {row['trained_choices']['used']}/{row['trained_choices']['capacity']} — {', '.join(row['trained_choices']['record_ids']) or 'None (typed empty collection)'}",
                f"- New Sphere acquisition: {new_sphere_text}",
                f"- Known Spheres after level: {', '.join(row['known_spheres_after_level'])}",
                f"- Known talents after level: {', '.join(row['known_talents_after_level'])}",
                f"- Manual acquisitions: {', '.join(row['manual_acquisitions']) or 'None (typed empty collection)'}",
                f"- Forged Technique acquisitions: {', '.join(row['forged_technique_acquisitions']) or 'None (typed empty collection)'}",
                f"- Equipment acquisitions: {', '.join(row['equipment_acquisitions']) or 'None (typed empty collection)'}",
                f"- Legality: **{row['legality']['status']}** ({row['legality']['event_count']} causal events)",
                f"- Event IDs: {', '.join(row['event_ids'])}",
                "",
            ]
        text = "\n".join(lines).rstrip() + "\n"
        if any(PLACEHOLDER_RE.search(line.strip()) for line in text.splitlines()):
            raise FoundryError("STAGE2_PLACEHOLDER_FORBIDDEN", "A forbidden placeholder entered the human-readable ledger.")
        return text

    def rebuild(self, project_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            _row, project = self._project_row(conn, project_id)
            events = self._existing_v2_events(conn, project_id)
            state, rows, provenance_entries = self._state_from_events(events, project_id)
            blockers: list[dict[str, Any]] = []
            if not events:
                blockers.append(_block("NO_STAGE2_ADVANCEMENT_EVENTS", "/events", "No canonical Stage 2 Advancement Events have been committed."))
            if state["current_cl"] < 1:
                blockers.append(_block("LEVEL_SEQUENCE_EMPTY", "/rows", "No complete CL1-current-level sequence exists."))

            ledger_candidate = self._ledger_document(project, events, state, rows) if not blockers else None
            if ledger_candidate and events:
                head = events[-1]
                for pointer in ("/schema_version", "/project_id", "/project_revision", "/content_lock_hash", "/event_head_hash", "/target_cl", "/generated_at_rule"):
                    provenance_entries[pointer] = self._composite_provenance([head], "stage2.ledger-metadata.v1", {"pointer": pointer, "project_revision": project["revision"]})
                provenance_entries["/final_state_hash"] = self._composite_provenance(events, "stage2.final-state-replay-hash.v1", {"event_count": len(events)})
                required_pointers = self._leaf_pointers(ledger_candidate)
                proven_pointers = set(provenance_entries)
                unproven = sorted(required_pointers - proven_pointers)
                if unproven:
                    blockers.append(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", "/provenance", "One or more Leveling Ledger fields lack event/catalog/calculation provenance.", unproven_pointers=unproven))
            else:
                required_pointers = set()
                unproven = []

            orphaned = self._orphaned_final_elements(state)
            if orphaned:
                blockers.append(_block("FINAL_STATE_ELEMENT_WITHOUT_CAUSAL_EVENT", "/final_state", "One or more final-state records have no causal Advancement Event.", orphaned=orphaned))

            blocker_report = {
                "schema_version": BLOCKER_VERSION,
                "project_id": project_id,
                "project_revision": project["revision"],
                "blocked": bool(blockers),
                "blockers": blockers,
            }
            self.registry.validate(blocker_report)
            ledger = ledger_candidate if not blockers else None
            provenance = {
                "schema_version": "TianxiaFoundry.Stage2FieldProvenanceMap.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "entries": provenance_entries,
                "event_count": len(events),
                "coverage": {
                    "required": len(required_pointers) if required_pointers else max(1, len(provenance_entries)),
                    "proven": len(required_pointers & set(provenance_entries)) if required_pointers else max(1, len(provenance_entries)),
                    "unproven": len(unproven),
                },
            }
            if events and provenance_entries:
                self.registry.validate(provenance)
            event_state_hash = sha256_json(state)
            ledger_state_hash = ledger_candidate["final_state_hash"] if ledger_candidate else event_state_hash
            mismatches = []
            if event_state_hash != ledger_state_hash:
                mismatches.append({"code": "FINAL_STATE_HASH_MISMATCH"})
            reconciliation = {
                "schema_version": RECON_VERSION,
                "project_id": project_id,
                "project_revision": project["revision"],
                "valid": not blockers and not mismatches and not orphaned,
                "event_state_hash": event_state_hash,
                "ledger_state_hash": ledger_state_hash,
                "orphaned_final_elements": orphaned,
                "mismatches": mismatches,
            }
            self.registry.validate(reconciliation)
            artifacts = {
                "Stage2_Blocker_Report.json": canonical_json(blocker_report).encode(),
                "Stage2_Field_Provenance_Map.json": canonical_json(provenance).encode(),
                "Stage2_Final_State_Reconciliation.json": canonical_json(reconciliation).encode(),
            }
            if ledger:
                artifacts["Leveling_Ledger.json"] = canonical_json(ledger).encode()
                artifacts["Leveling_Ledger.md"] = self._markdown(ledger).encode()
            conn.execute("DELETE FROM stage2_artifacts WHERE project_id=? AND project_revision=?", (project_id, project["revision"]))
            for name, data in artifacts.items():
                media = "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8"
                conn.execute(
                    "INSERT INTO stage2_artifacts(project_id,project_revision,artifact_name,media_type,artifact_hash,artifact_bytes,created_at) VALUES(?,?,?,?,?,?,?)",
                    (project_id, project["revision"], name, media, sha256_bytes(data), data, utcnow()),
                )
            conn.execute("DELETE FROM stage2_level_snapshots WHERE project_id=? AND project_revision=?", (project_id, project["revision"]))
            if ledger:
                for rowdata in ledger["rows"]:
                    conn.execute(
                        "INSERT INTO stage2_level_snapshots(project_id,project_revision,character_cl,event_sequence,snapshot_hash,snapshot_json,created_at) VALUES(?,?,?,?,?,?,?)",
                        (project_id, project["revision"], rowdata["cl"], max([e["sequence"] for e in events if e["advancement"]["target_cl"] <= rowdata["cl"]] or [0]), rowdata["row_hash"], canonical_json(rowdata), utcnow()),
                    )
            return {
                "project_id": project_id,
                "project_revision": project["revision"],
                "status": "BLOCKED" if blockers else "READY",
                "event_count": len(events),
                "target_cl": state["current_cl"],
                "final_state_hash": event_state_hash,
                "blocker_report": blocker_report,
                "reconciliation": reconciliation,
                "provenance_coverage": provenance["coverage"],
                "artifacts": [
                    {
                        "artifact_name": name,
                        "sha256": sha256_bytes(data),
                        "media_type": "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8",
                        "size_bytes": len(data),
                    }
                    for name, data in sorted(artifacts.items())
                ],
            }

    def status(self,project_id:str)->dict[str,Any]:
        with self.db.connection() as conn:
            row,project=self._project_row(conn,project_id)
            arts=[dict(r) for r in conn.execute("SELECT artifact_name,media_type,artifact_hash AS sha256,length(artifact_bytes) AS size_bytes,created_at FROM stage2_artifacts WHERE project_id=? AND project_revision=? ORDER BY artifact_name",(project_id,project["revision"]))]
            proposals=[dict(r) for r in conn.execute("SELECT proposal_id,target_cl,status,proposal_hash,approved_by,created_at,updated_at FROM stage2_proposals WHERE project_id=? ORDER BY created_at DESC",(project_id,))]
            blockers=[{"code":r["blocker_code"],"severity":r["severity"],"pointer":r["pointer"],"message":r["message"],"details":json.loads(r["details_json"])} for r in conn.execute("SELECT * FROM stage2_blockers WHERE project_id=? AND resolved_at IS NULL ORDER BY created_at",(project_id,))]
            return {"project_id":project_id,"project_revision":project["revision"],"content_lock_hash":project["content_lock"]["lock_hash"],"proposals":proposals,"artifacts":arts,"blockers":blockers,"stage2_ai_provider_bridge_implemented":False,"command5_candidate_claimed":False,"gm_screen_acceptance_claimed":False}

    def ledger(self,project_id:str)->dict[str,Any]:
        status=self.rebuild(project_id)
        if status["status"]!="READY": raise FoundryError("STAGE2_LEDGER_BLOCKED","The Leveling Ledger is blocked.",details=status["blocker_report"])
        return json.loads(self.artifact(project_id,"Leveling_Ledger.json")[1])

    def validate_ledger_document(self, project_id: str, ledger: dict[str, Any]) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        try:
            self.registry.validate(ledger, LEDGER_VERSION)
        except Exception as exc:
            blockers.append(_block("LEVELING_LEDGER_SCHEMA_INVALID", "", "The supplied Leveling Ledger does not match the canonical schema.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})()))
        try:
            expected = self.ledger(project_id)
        except FoundryError as exc:
            blockers.append(_block("DETERMINISTIC_LEDGER_UNAVAILABLE", "", "The authoritative event stream cannot currently produce a complete ledger.", error=exc.to_dict()))
            expected = None
        if expected is not None and canonical_json(ledger) != canonical_json(expected):
            blockers.append(_block("LEVELING_LEDGER_DOES_NOT_MATCH_EVENTS", "", "The supplied ledger differs from deterministic replay of the complete event stream.", expected_hash=sha256_json(expected), actual_hash=sha256_json(ledger)))
        for i,row in enumerate(ledger.get("rows",[]) if isinstance(ledger,dict) else []):
            if i and row.get("cl") == ledger["rows"][i-1].get("cl"):
                blockers.append(_block("COPIED_OR_REPEATED_LEVEL_ROW",f"/rows/{i}","A level row repeats a prior CL."))
            computed=sha256_json({k:v for k,v in row.items() if k!="row_hash"})
            if row.get("row_hash") != computed:
                blockers.append(_block("CUMULATIVE_SNAPSHOT_TAMPERED",f"/rows/{i}/row_hash","The level snapshot hash does not match its fields.",expected=computed,actual=row.get("row_hash")))
        def walk(value:Any,pointer:str=""):
            if isinstance(value,str) and PLACEHOLDER_RE.match(value.strip()): blockers.append(_block("PLACEHOLDER_FORBIDDEN",pointer,"Forbidden placeholder text appears in the ledger projection.",value=value))
            elif isinstance(value,dict):
                for k,v in value.items(): walk(v,pointer+"/"+str(k).replace("~","~0").replace("/","~1"))
            elif isinstance(value,list):
                for i,v in enumerate(value): walk(v,pointer+f"/{i}")
        walk(ledger)
        return {"valid":not blockers,"blockers":blockers,"expected_hash":sha256_json(expected) if expected else None,"actual_hash":sha256_json(ledger) if isinstance(ledger,dict) else None}

    def validate_provenance_document(self, project_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        try:
            self.registry.validate(provenance, "TianxiaFoundry.Stage2FieldProvenanceMap.v1")
        except Exception as exc:
            blockers.append(_block("PROVENANCE_MAP_SCHEMA_INVALID", "", "The provenance document does not match the canonical schema.", diagnostics=getattr(exc, "to_dict", lambda: {"message": str(exc)})()))
        status = self.rebuild(project_id)
        _, expected_bytes, _ = self.artifact(project_id, "Stage2_Field_Provenance_Map.json")
        expected = json.loads(expected_bytes)
        if canonical_json(provenance) != canonical_json(expected):
            missing = sorted(set(expected.get("entries", {})) - set(provenance.get("entries", {}))) if isinstance(provenance, dict) else []
            blockers.append(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE", "/entries", "The supplied field-provenance map differs from deterministic replay.", missing_pointers=missing, expected_hash=sha256_json(expected), actual_hash=sha256_json(provenance)))
        return {"valid": not blockers, "blockers": blockers, "stage2_status": status["status"], "expected_hash": sha256_json(expected), "actual_hash": sha256_json(provenance)}

    def audit(self, project_id: str) -> dict[str, Any]:
        chain=self.projects.verify_chain(project_id)
        status=self.rebuild(project_id)
        blockers=list(status["blocker_report"]["blockers"])
        if not chain.get("valid"): blockers.append(_block("EVENT_CHAIN_TAMPERED","/events","The append-only event hash chain failed verification.",errors=chain.get("errors")))
        if status["status"]=="READY":
            ledger=self.ledger(project_id); validation=self.validate_ledger_document(project_id,ledger); blockers.extend(validation["blockers"])
            _,prov_bytes,_=self.artifact(project_id,"Stage2_Field_Provenance_Map.json"); prov=json.loads(prov_bytes)
            if prov.get("coverage",{}).get("unproven"):
                blockers.append(_block("FINAL_STATE_WITHOUT_CAUSAL_PROVENANCE","/provenance","One or more projected fields lack causal event provenance.",coverage=prov.get("coverage")))
        return {"project_id":project_id,"valid":not blockers,"chain":chain,"stage2":status,"blockers":blockers}

    def artifact(self,project_id:str,name:str)->tuple[str,bytes,str]:
        with self.db.connection() as conn:
            row,project=self._project_row(conn,project_id)
            art=conn.execute("SELECT media_type,artifact_hash,artifact_bytes FROM stage2_artifacts WHERE project_id=? AND project_revision=? AND artifact_name=?",(project_id,project["revision"],name)).fetchone()
            if not art: raise FoundryError("STAGE2_ARTIFACT_NOT_FOUND","No Stage 2 artifact with that name exists for the current project revision.",status_code=404)
            data=bytes(art["artifact_bytes"])
            if sha256_bytes(data)!=art["artifact_hash"]: raise FoundryError("STAGE2_ARTIFACT_TAMPERED","The stored Stage 2 artifact hash does not match its bytes.")
            return art["media_type"],data,art["artifact_hash"]
