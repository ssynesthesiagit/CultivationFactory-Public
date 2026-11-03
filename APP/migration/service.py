from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.core import Database, canonical_json, sha256_file, sha256_json, utcnow
from contracts.canonical import (
    ZERO_HASH,
    canonical_event_from_draft,
    canonical_event_hash,
    canonical_project_document,
    canonical_project_hash,
    normalize_core_catalog_record,
)
from contracts.registry import SchemaRegistry


def _initial_state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.ProjectState.v1",
        "project_id": project_id,
        "selections": {},
        "metadata": {},
        "retired_record_ids": [],
        "migration_history": [],
        "reversed_event_ids": [],
        "superseded_event_ids": [],
    }


def _add(state: dict[str, Any], ctype: str, rid: str) -> None:
    values = state["selections"].setdefault(ctype, [])
    if rid not in values:
        values.append(rid); values.sort()
    if rid in state["retired_record_ids"]:
        state["retired_record_ids"].remove(rid)


def _retire(state: dict[str, Any], rid: str) -> None:
    for values in state["selections"].values():
        if rid in values:
            values.remove(rid)
    if rid not in state["retired_record_ids"]:
        state["retired_record_ids"].append(rid); state["retired_record_ids"].sort()


def _reduce(events: list[dict[str, Any]], project_id: str, record_types: dict[str, str]) -> dict[str, Any]:
    reversed_ids: set[str] = set()
    superseded_ids: set[str] = set()
    for event in events:
        op = (event.get("migration") or {}).get("operation")
        targets = set(event.get("supersedes_event_ids") or [])
        if op == "reversal": reversed_ids |= targets
        elif op == "supersession": superseded_ids |= targets
    suppressed = reversed_ids | superseded_ids
    state = _initial_state(project_id)
    state["reversed_event_ids"] = sorted(reversed_ids)
    state["superseded_event_ids"] = sorted(superseded_ids)
    for event in events:
        if event["event_id"] in suppressed:
            continue
        op = (event.get("migration") or {}).get("operation")
        if op in {"reversal", "supersession"}:
            state["migration_history"].append({"event_id": event["event_id"], "operation": op, "targets": event.get("supersedes_event_ids", [])})
            continue
        for rid in event.get("retired_records", []): _retire(state, rid)
        for rid in event.get("created_records", []) + event.get("updated_records", []):
            _add(state, record_types.get(rid, event.get("subject", {}).get("content_type", "unclassified")), rid)
        if event["event_type"] == "migration":
            state["migration_history"].append({"event_id": event["event_id"], "migration": event.get("migration")})
    return state


def _resolve_record(conn, project_id: str, record_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT record_json FROM project_locked_records WHERE project_id=? AND record_id=?", (project_id, record_id)).fetchone()
    if row:
        return json.loads(row[0])
    row = conn.execute(
        """SELECT r.data_json FROM catalog_records r JOIN project_content_locks l
           ON l.project_id=? AND l.pack_id=r.pack_id AND l.version=r.pack_version
           WHERE r.record_id=? ORDER BY r.selected_authority DESC LIMIT 1""", (project_id, record_id)
    ).fetchone()
    return json.loads(row[0]) if row else None


def _quarantine(conn, family: str, key: str, obj: dict[str, Any], reason: str, diagnostics: list[dict[str, Any]]) -> None:
    conn.execute(
        "INSERT INTO contract_quarantine(object_family,object_key,declared_schema_version,reason_code,diagnostics_json,original_json,quarantined_at) VALUES(?,?,?,?,?,?,?)",
        (family, key, obj.get("schema_version") or obj.get("protocol_version"), reason, canonical_json(diagnostics), canonical_json(obj), utcnow()),
    )


def _canonicalize_catalog(conn, registry: SchemaRegistry, inventory: dict[str, Any]) -> None:
    rows = conn.execute("SELECT * FROM catalog_records WHERE contract_status!='valid' OR canonical_schema_version IS NULL").fetchall()
    inventory["catalog_legacy_rows"] = len(rows)
    inventory["catalog_converted"] = 0
    inventory["catalog_already_canonical"] = 0
    inventory["catalog_quarantined"] = 0
    for row in rows:
        obj = json.loads(row["data_json"])
        report = registry.report(obj, "TianxiaFoundry.RulesCatalogRecord.v1")
        if report["valid"]:
            canonical = obj
            raw = None
            inventory["catalog_already_canonical"] += 1
        elif obj.get("schema_version") == "TianxiaFoundry.CatalogProjection.v1":
            pack = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?", (row["pack_id"], row["pack_version"])).fetchone()
            if not pack:
                _quarantine(conn, "rules_catalog_record", row["record_id"], obj, "PACK_BINDING_NOT_FOUND", report["diagnostics"])
                conn.execute("UPDATE catalog_records SET contract_status='quarantined' WHERE row_id=?", (row["row_id"],))
                inventory["catalog_quarantined"] += 1
                continue
            canonical = normalize_core_catalog_record(obj, pack_hash=pack[0])
            canonical_report = registry.report(canonical)
            if not canonical_report["valid"]:
                _quarantine(conn, "rules_catalog_record", row["record_id"], obj, "CANONICALIZATION_FAILED", canonical_report["diagnostics"])
                conn.execute("UPDATE catalog_records SET contract_status='quarantined' WHERE row_id=?", (row["row_id"],))
                inventory["catalog_quarantined"] += 1
                continue
            raw = obj
            inventory["catalog_converted"] += 1
        else:
            _quarantine(conn, "rules_catalog_record", row["record_id"], obj, "UNKNOWN_LEGACY_CATALOG_SHAPE", report["diagnostics"])
            conn.execute("UPDATE catalog_records SET contract_status='quarantined' WHERE row_id=?", (row["row_id"],))
            inventory["catalog_quarantined"] += 1
            continue
        authority = canonical["compatibility"]["factory"].get("authority_classification", row["authority"])
        notes = canonical["compatibility"]["factory"].get("unresolved_normalization_notes", [])
        conn.execute(
            """UPDATE catalog_records SET content_type=?,display_name=?,pack_id=?,pack_version=?,authority=?,publication_state=?,
            source_path=?,source_anchor=?,source_hash=?,record_hash=?,minimum_cl=?,realm=?,selected_authority=?,data_json=?,
            unresolved_notes_json=?,raw_projection_json=?,canonical_schema_version=?,contract_status='valid' WHERE row_id=?""",
            (canonical["content_type"], canonical["display_name"], canonical["content_binding"]["pack_id"], canonical["content_binding"]["pack_version"],
             authority, canonical["publication"]["status"], canonical["source"].get("path", ""), canonical["source"]["anchor"], canonical["source"]["source_hash"],
             canonical["record_hash"], canonical["legality"].get("minimum_cl"), canonical["legality"].get("realm_rules", {}).get("realm"),
             1 if canonical["compatibility"]["factory"].get("selected_authority", row["selected_authority"]) else 0,
             canonical_json(canonical), canonical_json(notes), canonical_json(raw) if raw is not None else row["raw_projection_json"],
             canonical["schema_version"], row["row_id"]),
        )


def _canonicalize_locked_records(conn, registry: SchemaRegistry, inventory: dict[str, Any]) -> None:
    rows = conn.execute("SELECT * FROM project_locked_records").fetchall()
    converted = quarantined = 0
    for row in rows:
        obj = json.loads(row["record_json"])
        if registry.report(obj, "TianxiaFoundry.RulesCatalogRecord.v1")["valid"]:
            continue
        if obj.get("schema_version") == "TianxiaFoundry.CatalogProjection.v1":
            pack = conn.execute("SELECT pack_hash FROM project_content_locks WHERE project_id=? AND pack_id=? AND version=?", (row["project_id"], row["pack_id"], row["pack_version"])).fetchone()
            if pack:
                canonical = normalize_core_catalog_record(obj, pack_hash=pack[0])
                if registry.report(canonical)["valid"]:
                    conn.execute("UPDATE project_locked_records SET record_hash=?,record_json=? WHERE project_id=? AND record_id=?", (canonical["record_hash"], canonical_json(canonical), row["project_id"], row["record_id"]))
                    converted += 1
                    continue
        _quarantine(conn, "project_locked_record", f"{row['project_id']}:{row['record_id']}", obj, "LOCKED_RECORD_CANONICALIZATION_FAILED", registry.report(obj, "TianxiaFoundry.RulesCatalogRecord.v1")["diagnostics"])
        quarantined += 1
    inventory["locked_records_converted"] = converted
    inventory["locked_records_quarantined"] = quarantined


def _canonicalize_events(conn, registry: SchemaRegistry, inventory: dict[str, Any], mapping: list[dict[str, Any]]) -> None:
    projects = [r[0] for r in conn.execute("SELECT DISTINCT project_id FROM events ORDER BY project_id")]
    converted = already = quarantined = 0
    for project_id in projects:
        rows = conn.execute("SELECT * FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,)).fetchall()
        canonical_events: list[dict[str, Any]] = []
        event_by_id: dict[str, dict[str, Any]] = {}
        record_types: dict[str, str] = {}
        previous = ZERO_HASH
        for row in rows:
            old = json.loads(row["event_json"])
            report = registry.report(old, "TianxiaFoundry.AdvancementEvent.v1")
            if report["valid"]:
                event = old
                already += 1
            else:
                legacy_type = old.get("event_type")
                stable_ids = old.get("stable_rule_ids") or []
                target_id = (old.get("payload") or {}).get("target_event_id") or old.get("superseded_event_reference")
                target_event = event_by_id.get(target_id) if target_id else None
                if legacy_type in {"reversal", "supersede"} and target_event:
                    stable_ids = [target_event["subject"]["record_id"]]
                rid = stable_ids[0] if stable_ids else None
                record = _resolve_record(conn, project_id, rid) if rid else None
                if not record or not registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")["valid"]:
                    _quarantine(conn, "advancement_event", old.get("event_id", str(row["sequence_no"])), old, "EVENT_SUBJECT_RECORD_UNRESOLVED", report["diagnostics"])
                    conn.execute("UPDATE events SET contract_status='quarantined',legacy_event_hash=? WHERE project_id=? AND sequence_no=?", (row["event_hash"], project_id, row["sequence_no"]))
                    quarantined += 1
                    continue
                record_types[rid] = record["content_type"]
                canonical_type = legacy_type
                supersedes: list[str] = []
                legacy_audit = {
                    "legacy_schema_version": old.get("schema_version"),
                    "legacy_event_hash": row["event_hash"],
                    "legacy_runtime_fields": {
                        key: old.get(key)
                        for key in (
                            "actor_type", "actor_identifier", "content_pack_references", "stable_rule_ids",
                            "acquisition_channel", "prerequisite_evidence", "payload", "validation_result",
                            "approval_state", "approved_by", "superseded_event_reference", "rationale",
                        )
                        if key in old
                    },
                }
                migration: dict[str, Any] | None = {
                    "operation": "phase2_runtime_contract_reconciliation",
                    "contract_reconciliation": legacy_audit,
                }
                if legacy_type == "reversal":
                    canonical_type = "retire"; supersedes = [target_id]; migration = {"operation": "reversal", "legacy_event_type": "reversal", "target_event_id": target_id, "contract_reconciliation": legacy_audit}
                elif legacy_type == "supersede":
                    canonical_type = "replace"; supersedes = [target_id]; migration = {"operation": "supersession", "legacy_event_type": "supersede", "target_event_id": target_id, "contract_reconciliation": legacy_audit}
                elif legacy_type not in {"acquire", "evolve", "replace", "retire", "author_metadata", "lock_change", "migration"}:
                    _quarantine(conn, "advancement_event", old.get("event_id", str(row["sequence_no"])), old, "EVENT_TYPE_UNMAPPABLE", report["diagnostics"])
                    conn.execute("UPDATE events SET contract_status='quarantined',legacy_event_hash=? WHERE project_id=? AND sequence_no=?", (row["event_hash"], project_id, row["sequence_no"]))
                    quarantined += 1
                    continue
                before = _reduce(canonical_events, project_id, record_types)
                draft = {
                    "event_type": legacy_type,
                    "effective_point": old.get("effective_point"),
                    "acquisition_channel": old.get("acquisition_channel") or old.get("legal_channel") or "administrative",
                    "payload": old.get("payload") or {},
                    "planner_response_id": old.get("planner_response_id"),
                }
                project_row = conn.execute("SELECT revision,catalog_build_hash FROM projects WHERE project_id=?", (project_id,)).fetchone()
                event = canonical_event_from_draft(
                    event_id=old.get("event_id") or str(uuid.uuid4()), project_id=project_id,
                    project_revision=min(int(project_row["revision"]), int(row["sequence_no"])), sequence=int(row["sequence_no"]),
                    draft=draft, subject_record=record, catalog_build_id=project_row["catalog_build_hash"] or "catalog.unbuilt",
                    previous_event_hash=previous, state_before_hash=sha256_json(before), state_after_hash=ZERO_HASH,
                    created_at=old.get("created_at") or utcnow(), idempotency_key=old.get("event_id") or f"migration.{project_id}.{row['sequence_no']}",
                    supersedes_event_ids=supersedes, canonical_event_type=canonical_type, migration=migration,
                )
                after = _reduce(canonical_events + [event], project_id, record_types)
                event["state_after_hash"] = sha256_json(after)
                event["event_hash"] = canonical_event_hash(event)
                canonical_report = registry.report(event)
                if not canonical_report["valid"]:
                    _quarantine(conn, "advancement_event", event["event_id"], old, "EVENT_CANONICALIZATION_FAILED", canonical_report["diagnostics"])
                    conn.execute("UPDATE events SET contract_status='quarantined',legacy_event_hash=? WHERE project_id=? AND sequence_no=?", (row["event_hash"], project_id, row["sequence_no"]))
                    quarantined += 1
                    continue
                converted += 1
                mapping_row = {
                    "project_id": project_id, "sequence": int(row["sequence_no"]), "event_id": event["event_id"],
                    "old_event_hash": row["event_hash"], "new_event_hash": event["event_hash"],
                    "old_previous_event_hash": row["previous_event_hash"], "new_previous_event_hash": previous,
                    "reason": "Phase2 legacy runtime envelope canonicalized to AdvancementEvent.v1",
                }
                mapping.append(mapping_row)
                conn.execute(
                    "INSERT OR REPLACE INTO event_hash_mappings(project_id,sequence_no,event_id,old_event_hash,new_event_hash,old_previous_event_hash,new_previous_event_hash,mapping_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (project_id, row["sequence_no"], event["event_id"], row["event_hash"], event["event_hash"], row["previous_event_hash"], previous, mapping_row["reason"], utcnow()),
                )
            # Even already-canonical events are rebound to the canonical previous hash if needed.
            if event.get("previous_event_hash") != previous:
                event["previous_event_hash"] = previous
                before = _reduce(canonical_events, project_id, record_types)
                event["state_before_hash"] = sha256_json(before)
                after = _reduce(canonical_events + [event], project_id, record_types)
                event["state_after_hash"] = sha256_json(after)
                event["event_hash"] = canonical_event_hash(event)
            conn.execute(
                "UPDATE events SET event_id=?,event_hash=?,previous_event_hash=?,created_at=?,event_json=?,legacy_event_json=?,legacy_event_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=? AND sequence_no=?",
                (event["event_id"], event["event_hash"], event["previous_event_hash"], event["created_at"], canonical_json(event), canonical_json(old) if not report["valid"] else row["legacy_event_json"], row["event_hash"] if not report["valid"] else row["legacy_event_hash"], event["schema_version"], project_id, row["sequence_no"]),
            )
            canonical_events.append(event); event_by_id[event["event_id"]] = event; previous = event["event_hash"]
    inventory["events_converted"] = converted
    inventory["events_already_canonical"] = already
    inventory["events_quarantined"] = quarantined


def _canonicalize_projects(conn, registry: SchemaRegistry, inventory: dict[str, Any]) -> None:
    rows = conn.execute("SELECT * FROM projects").fetchall()
    converted = already = quarantined = 0
    dropped_unhashed_source_inputs = 0
    for row in rows:
        old = json.loads(row["project_json"])
        report = registry.report(old, "TianxiaFoundry.CharacterProject.v1")
        if report["valid"]:
            project = old; already += 1
        else:
            locks = [dict(r) for r in conn.execute("SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id", (row["project_id"],))]
            events = conn.execute("SELECT event_hash FROM events WHERE project_id=? AND contract_status='valid' ORDER BY sequence_no", (row["project_id"],)).fetchall()
            legacy_sources = old.get("source_evidence_records") or []
            project = canonical_project_document(
                project_id=row["project_id"], name=old.get("working_name") or row["working_name"], revision=len(events), status="draft",
                created_at=old.get("created_at") or row["created_at"], updated_at=old.get("updated_at") or row["updated_at"],
                catalog_build_id=old.get("rules_catalog_snapshot_hash") or row["catalog_build_hash"] or "catalog.unbuilt",
                pack_locks=locks, user_locks=old.get("user_locks") or [], source_inputs=legacy_sources,
                event_count=len(events), head_hash=events[-1][0] if events else None,
            )
            dropped_unhashed_source_inputs += max(0, len(legacy_sources) - len(project["source_inputs"]))
            canonical_report = registry.report(project)
            if not canonical_report["valid"]:
                _quarantine(conn, "character_project", row["project_id"], old, "PROJECT_CANONICALIZATION_FAILED", canonical_report["diagnostics"])
                conn.execute("UPDATE projects SET contract_status='quarantined' WHERE project_id=?", (row["project_id"],))
                quarantined += 1
                continue
            converted += 1
        conn.execute(
            """UPDATE projects SET working_name=?,status=?,revision=?,created_at=?,updated_at=?,target_factory_version=?,
            target_candidate_schema_version=?,target_gm_screen_version=?,catalog_build_hash=?,project_json=?,canonical_project_hash=?,
            canonical_schema_version=?,contract_status='valid',legacy_project_json=? WHERE project_id=?""",
            (project["name"], project["status"], project["revision"], project["created_at"], project["updated_at"],
             project["factory_target"]["producer"], project["factory_target"]["candidate_schema"], project["gm_screen_target"]["consumer"],
             project["content_lock"]["catalog_build_id"], canonical_json(project), canonical_project_hash(project), project["schema_version"], canonical_json(old) if not report["valid"] else row["legacy_project_json"], row["project_id"]),
        )
    inventory["projects_converted"] = converted
    inventory["projects_already_canonical"] = already
    inventory["projects_quarantined"] = quarantined
    inventory["project_source_inputs_excluded_unhashed"] = dropped_unhashed_source_inputs
    inventory["project_field_mapping"] = {
        "working_name": "name",
        "target_factory_version": "factory_target.producer",
        "target_candidate_schema_version": "factory_target.candidate_schema",
        "target_gm_screen_version": "gm_screen_target.consumer",
        "rules_catalog_snapshot_hash": "content_lock.catalog_build_id",
        "content_pack_locks": "content_lock.packs (from project_content_locks)",
        "source_evidence_records": "source_inputs when source hash is valid; original preserved in legacy_project_json",
        "compatibility_projection_status": "internal projects read-model column",
        "compile_status": "internal projects read-model column",
        "consumer_verification_status": "internal projects read-model column",
    }


def reconcile_database(db: Database) -> dict[str, Any]:
    """Idempotently reconcile legacy Phase 2 runtime rows after migration 002.

    New/empty databases return immediately. Existing Phase 2 rows are inventoried,
    canonicalized, validated, and accompanied by an explicit hash mapping.
    """
    with db.connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "contract_migration_runs" not in tables:
            return {"status": "002_NOT_APPLIED"}
        legacy_counts = {
            "catalog": conn.execute("SELECT COUNT(*) FROM catalog_records WHERE contract_status!='valid'").fetchone()[0],
            "projects": conn.execute("SELECT COUNT(*) FROM projects WHERE contract_status!='valid'").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events WHERE contract_status!='valid'").fetchone()[0],
        }
        if not any(legacy_counts.values()):
            return {"status": "NO_LEGACY_OBJECTS", "counts": legacy_counts}
    registry = SchemaRegistry(db.settings.root_dir)
    run_id = str(uuid.uuid4())
    inventory: dict[str, Any] = {"legacy_counts": legacy_counts, "started_at": utcnow()}
    mapping: list[dict[str, Any]] = []
    db_hash = sha256_file(db.settings.db_path) if db.settings.db_path.exists() else None
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO contract_migration_runs(run_id,started_at,source_database_hash,status,inventory_json,mapping_json,quarantine_count) VALUES(?,?,?,?,?,?,?)",
            (run_id, inventory["started_at"], db_hash, "running", canonical_json(inventory), "[]", 0),
        )
        _canonicalize_catalog(conn, registry, inventory)
        _canonicalize_locked_records(conn, registry, inventory)
        _canonicalize_events(conn, registry, inventory, mapping)
        _canonicalize_projects(conn, registry, inventory)
        quarantine_count = conn.execute("SELECT COUNT(*) FROM contract_quarantine").fetchone()[0]
        inventory["completed_at"] = utcnow()
        inventory["quarantine_count"] = quarantine_count
        conn.execute(
            "UPDATE contract_migration_runs SET completed_at=?,status=?,inventory_json=?,mapping_json=?,quarantine_count=? WHERE run_id=?",
            (inventory["completed_at"], "pass" if quarantine_count == 0 else "pass_with_quarantine", canonical_json(inventory), canonical_json(mapping), quarantine_count, run_id),
        )
    return {"status": "PASS" if inventory["quarantine_count"] == 0 else "PASS_WITH_QUARANTINE", "run_id": run_id, "inventory": inventory, "mapping": mapping}
