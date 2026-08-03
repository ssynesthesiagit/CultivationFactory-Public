from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json, utcnow
from content_packs.identity import compute_payload_identity
from content_packs.service import ContentPackManager
from project_store.service import ProjectStore, _initial_state
from contracts.canonical import ZERO_HASH, canonical_event_from_draft, canonical_event_hash, canonical_project_document, canonical_project_hash
from contracts.registry import SchemaRegistry

PACK_ID = "TEST.TianxiaFoundry.GoldenCL13FixtureAuthority"
PACK_VERSION = "1.0.0"
CHANNEL = "fixture-reconstruction"


def _zip_deterministic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, path.read_bytes())


def _record(*, pack_hash: str, record_id: str, display_name: str, source_id: str, source_path: str, source_hash: str, anchor: str) -> dict[str, Any]:
    value = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": "source_document",
        "display_name": display_name,
        "aliases": [],
        "tags": ["TEST-ONLY", "golden-fixture-authority", "phase3a"],
        "publication": {"status": "validated", "published_version": PACK_VERSION, "replaced_by": None},
        "content_binding": {"pack_id": PACK_ID, "pack_version": PACK_VERSION, "pack_hash": pack_hash},
        "source": {
            "source_id": source_id,
            "path": source_path,
            "anchor": anchor,
            "source_hash": source_hash,
        },
        "summary": "TEST-ONLY audited authority record for reconstructing one section of the Factory GOOD_Authoritative_CL13 fixture.",
        "legality": {
            "acquisition_channels": [CHANNEL],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": 1,
            "realm_rules": {},
            "source_cl": {"basis": "fixture-authority"},
            "suppression": {"disabled_below_minimum_cl": False},
        },
        "dependencies": [],
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": "TEST-ONLY golden fixture section authority.",
            "full_description": "This record binds a canonical migration event to an exact source section. It is not selectable production content.",
            "surfaces": ["phase3a-golden-reconstruction"],
            "sort_key": record_id,
        },
        "compatibility": {
            "factory": {"producer": "HF05ZVK-R1H", "phase2_compilable": True},
            "gm_screen": {"consumer": "HF05ZUI-R2K.3", "importable": True},
        },
        "revision_history": [{"version": PACK_VERSION, "summary": "Initial audited fixture authority.", "previous_record_hash": None}],
        "regression_tests": [{"test_id": record_id + ".projection", "kind": "projection", "input": {}, "expected": {"valid": True}}],
        "record_hash": "0" * 64,
    }
    value["record_hash"] = sha256_json({k: v for k, v in value.items() if k != "record_hash"})
    return value


def _build_authority_pack_v2_legacy(*, fixture_root: Path, output_zip: Path, work_dir: Path) -> dict[str, Any]:
    # Retained only as a private compatibility name for older callers. All
    # generation is delegated to the manifest-bound v3 implementation below.
    return build_authority_pack(fixture_root=fixture_root, output_zip=output_zip, work_dir=work_dir)

    # Unreachable historical implementation retained in the Phase 3 source
    # history; do not revive its payload-only identity.
    fixture_root = fixture_root.resolve()
    ledger_path = fixture_root / "Character_Master_Ledger.json"
    packets_path = fixture_root / "Build" / "Rules_Selection_Packets.json"
    if not ledger_path.is_file() or not packets_path.is_file():
        raise FoundryError("GOLDEN_FIXTURE_INCOMPLETE", "The Factory golden fixture lacks the ledger or Rules Selection Packets.")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    if work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "records").mkdir(parents=True)
    (work_dir / "sources").mkdir()
    (work_dir / "tests").mkdir()
    source_ledger = work_dir / "sources" / "Character_Master_Ledger.json"
    source_packets = work_dir / "sources" / "Rules_Selection_Packets.json"
    source_ledger.write_text(canonical_json(ledger), encoding="utf-8", newline="\n")
    source_packets.write_text(canonical_json(packets), encoding="utf-8", newline="\n")
    smoke = work_dir / "tests" / "projection_smoke.json"
    smoke.write_text(canonical_json({"expected": "PASS", "test": "golden-fixture-reconstruction"}), encoding="utf-8", newline="\n")
    declared = []
    for rel in ["sources/Character_Master_Ledger.json", "sources/Rules_Selection_Packets.json", "tests/projection_smoke.json"]:
        p = work_dir / rel
        declared.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    pack_hash = sha256_json({"files": sorted((x["path"], x["sha256"]) for x in declared), "pack_id": PACK_ID, "version": PACK_VERSION})
    entries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    ledger_source_hash = sha256_file(source_ledger)
    packet_source_hash = sha256_file(source_packets)
    for key in sorted(ledger):
        record_id = "TEST.FIXTURE.GOOD_CL13.LEDGER." + key.upper()
        record = _record(
            pack_hash=pack_hash,
            record_id=record_id,
            display_name=f"TEST-ONLY — GOOD CL13 ledger section: {key}",
            source_path="sources/Character_Master_Ledger.json",
            source_hash=ledger_source_hash,
            anchor="/" + key.replace("~", "~0").replace("/", "~1"),
        )
        path = work_dir / "records" / f"{record_id}.json"
        path.write_text(canonical_json(record), encoding="utf-8", newline="\n")
        entries.append({"record_id": record_id, "content_type": "source_document", "path": path.relative_to(work_dir).as_posix(), "sha256": sha256_file(path)})
        records.append(record)
    packet_record_id = "TEST.FIXTURE.GOOD_CL13.RULES_SELECTION_PACKETS"
    packet_record = _record(
        pack_hash=pack_hash,
        record_id=packet_record_id,
        display_name="TEST-ONLY — GOOD CL13 Rules Selection Packets",
        source_path="sources/Rules_Selection_Packets.json",
        source_hash=packet_source_hash,
        anchor="/",
    )
    packet_record_path = work_dir / "records" / f"{packet_record_id}.json"
    packet_record_path.write_text(canonical_json(packet_record), encoding="utf-8", newline="\n")
    entries.append({"record_id": packet_record_id, "content_type": "source_document", "path": packet_record_path.relative_to(work_dir).as_posix(), "sha256": sha256_file(packet_record_path)})
    records.append(packet_record)
    manifest = {
        "schema_version": "TianxiaFoundry.ContentPackManifest.v1",
        "pack_id": PACK_ID,
        "name": "TEST-ONLY GOOD_Authoritative_CL13 Fixture Authority",
        "version": PACK_VERSION,
        "state": "validated",
        "publisher": {"name": "Tianxia Character Foundry Phase 3A", "contact": "local-only"},
        "released_at": None,
        "compatibility": {
            "foundry": ">=0.3.0",
            "project_schema": "TianxiaFoundry.CharacterProject.v1",
            "catalog_schema": "TianxiaFoundry.RulesCatalogRecord.v1",
            "factory_producers": ["HF05ZVK-R1H"],
            "gm_screen_consumers": ["HF05ZUI-R2K.3"],
        },
        "dependencies": [],
        "conflicts": [],
        "records": entries,
        "sources": [
            {"source_id": "TEST.SOURCE.GOOD_AUTHORITATIVE_CL13.LEDGER", "path": "sources/Character_Master_Ledger.json", "sha256": ledger_source_hash, "license_note": "Copied immutable regression fixture."},
            {"source_id": "TEST.SOURCE.GOOD_AUTHORITATIVE_CL13.PACKETS", "path": "sources/Rules_Selection_Packets.json", "sha256": packet_source_hash, "license_note": "Copied immutable regression fixture."},
        ],
        "tests": {"inventory": [{"test_id": "TEST.GOOD_CL13.PROJECTION", "path": "tests/projection_smoke.json"}], "verdict": "PASS", "report_path": None},
        "migrations": [],
        "files": declared,
        "content_hash": pack_hash,
        "revision_history": [{"version": PACK_VERSION, "summary": "Initial Phase 3A fixture authority pack."}],
    }
    (work_dir / "pack.json").write_text(canonical_json(manifest), encoding="utf-8", newline="\n")
    sums = []
    for p in sorted(x for x in work_dir.rglob("*") if x.is_file() and x.name != "SHA256SUMS.txt"):
        sums.append(f"{sha256_file(p)}  {p.relative_to(work_dir).as_posix()}\n")
    (work_dir / "SHA256SUMS.txt").write_text("".join(sums), encoding="utf-8", newline="\n")
    _zip_deterministic(work_dir, output_zip)
    return {"pack_id": PACK_ID, "version": PACK_VERSION, "pack_hash": pack_hash, "zip": str(output_zip), "record_count": len(records), "ledger_keys": sorted(ledger), "rules_packet_record_id": packet_record_id}


def build_authority_pack(*, fixture_root: Path, output_zip: Path, work_dir: Path) -> dict[str, Any]:
    """Build the golden fixture authority with the v3 manifest-bound identity."""
    fixture_root = fixture_root.resolve()
    ledger_path = fixture_root / "Character_Master_Ledger.json"
    packets_path = fixture_root / "Build" / "Rules_Selection_Packets.json"
    if not ledger_path.is_file() or not packets_path.is_file():
        raise FoundryError("GOLDEN_FIXTURE_INCOMPLETE", "The Factory golden fixture lacks the ledger or Rules Selection Packets.")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    source_payload = {
        "sources/Character_Master_Ledger.json": canonical_json(ledger).encode("utf-8"),
        "sources/Rules_Selection_Packets.json": canonical_json(packets).encode("utf-8"),
        "tests/projection_smoke.json": canonical_json({"expected": "PASS", "test": "golden-fixture-reconstruction"}).encode("utf-8"),
    }
    ledger_source_hash = sha256_bytes(source_payload["sources/Character_Master_Ledger.json"])
    packet_source_hash = sha256_bytes(source_payload["sources/Rules_Selection_Packets.json"])
    ledger_source_id = "TEST.SOURCE.GOOD_AUTHORITATIVE_CL13.LEDGER"
    packet_source_id = "TEST.SOURCE.GOOD_AUTHORITATIVE_CL13.PACKETS"
    record_specs: list[dict[str, str]] = []
    for key in sorted(ledger):
        record_specs.append({
            "record_id": "TEST.FIXTURE.GOOD_CL13.LEDGER." + key.upper(),
            "display_name": f"TEST-ONLY - GOOD CL13 ledger section: {key}",
            "source_id": ledger_source_id,
            "source_path": "sources/Character_Master_Ledger.json",
            "source_hash": ledger_source_hash,
            "anchor": "/" + key.replace("~", "~0").replace("/", "~1"),
        })
    packet_record_id = "TEST.FIXTURE.GOOD_CL13.RULES_SELECTION_PACKETS"
    record_specs.append({
        "record_id": packet_record_id,
        "display_name": "TEST-ONLY - GOOD CL13 Rules Selection Packets",
        "source_id": packet_source_id,
        "source_path": "sources/Rules_Selection_Packets.json",
        "source_hash": packet_source_hash,
        "anchor": "/",
    })

    def records_for(pack_hash: str) -> list[dict[str, Any]]:
        return [_record(pack_hash=pack_hash, **spec) for spec in record_specs]

    def record_payload(records: list[dict[str, Any]]) -> dict[str, bytes]:
        return {f"records/{record['record_id']}.json": canonical_json(record).encode("utf-8") for record in records}

    def manifest_for(records: list[dict[str, Any]], payload: dict[str, bytes], identity: dict[str, Any] | None) -> dict[str, Any]:
        records_payload = record_payload(records)
        return {
            "schema_version": "TianxiaFoundry.ContentPackManifest.v1",
            "pack_id": PACK_ID,
            "name": "TEST-ONLY GOOD_Authoritative_CL13 Fixture Authority",
            "version": PACK_VERSION,
            "state": "validated",
            "publisher": {"name": "Tianxia Character Foundry Phase 3A", "contact": "local-only"},
            "released_at": None,
            "compatibility": {
                "foundry": ">=0.3.0",
                "project_schema": "TianxiaFoundry.CharacterProject.v1",
                "catalog_schema": "TianxiaFoundry.RulesCatalogRecord.v1",
                "factory_producers": ["HF05ZVK-R1H"],
                "gm_screen_consumers": ["HF05ZUI-R2K.3"],
            },
            "dependencies": [],
            "conflicts": [],
            "records": [{
                "record_id": record["record_id"],
                "content_type": "source_document",
                "path": f"records/{record['record_id']}.json",
                "sha256": sha256_bytes(records_payload[f"records/{record['record_id']}.json"]),
            } for record in records],
            "sources": [
                {"source_id": ledger_source_id, "path": "sources/Character_Master_Ledger.json", "sha256": ledger_source_hash, "license_note": "Copied immutable regression fixture."},
                {"source_id": packet_source_id, "path": "sources/Rules_Selection_Packets.json", "sha256": packet_source_hash, "license_note": "Copied immutable regression fixture."},
            ],
            "tests": {"inventory": [{"test_id": "TEST.GOOD_CL13.PROJECTION", "path": "tests/projection_smoke.json"}], "verdict": "PASS", "report_path": None},
            "migrations": [],
            "replacement_maps": [],
            "files": [{"path": rel, "bytes": len(raw), "sha256": sha256_bytes(raw)} for rel, raw in sorted(payload.items())],
            "manifest_contract_hash": identity["manifest_contract_hash"] if identity else "0" * 64,
            "content_hash": identity["content_hash"] if identity else "0" * 64,
            "revision_history": [{"version": PACK_VERSION, "summary": "Initial Phase 3A fixture authority pack."}],
        }

    initial_records = records_for("0" * 64)
    payload = {**source_payload, **record_payload(initial_records)}
    record_paths = set(record_payload(initial_records))
    seed = manifest_for(initial_records, payload, None)
    identity = compute_payload_identity(pack_id=PACK_ID, version=PACK_VERSION, payload=payload, record_paths=record_paths, manifest=seed)
    records = records_for(identity["content_hash"])
    payload.update(record_payload(records))
    manifest = manifest_for(records, payload, identity)
    verified = compute_payload_identity(pack_id=PACK_ID, version=PACK_VERSION, payload=payload, record_paths=record_paths, manifest=manifest)
    if verified != identity:
        raise FoundryError("GOLDEN_AUTHORITY_IDENTITY_NONDETERMINISTIC", "Derived record bindings changed the normalized authority-pack identity.")

    for rel, raw in payload.items():
        path = work_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (work_dir / "pack.json").write_text(canonical_json(manifest), encoding="utf-8", newline="\n")
    _zip_deterministic(work_dir, output_zip)
    return {
        "pack_id": PACK_ID,
        "version": PACK_VERSION,
        "pack_hash": identity["content_hash"],
        "manifest_contract_hash": identity["manifest_contract_hash"],
        "zip": str(output_zip),
        "record_count": len(records),
        "ledger_keys": sorted(ledger),
        "rules_packet_record_id": packet_record_id,
    }


def reconstruct_project(*, db: Database, fixture_root: Path, authority_pack_zip: Path, working_name: str = "GOOD Authoritative CL13 Reconstruction", exclude_ledger_keys: set[str] | None = None, ledger_overrides: dict[str, Any] | None = None, additional_pack_locks: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Create the audited golden project in one transaction.

    This is an explicit fixture migration, not an ordinary user-event endpoint. Each
    generated event is the same canonical AdvancementEvent.v1 shape used elsewhere,
    validates before insertion, and receives a deterministic chain/state hash. Batch
    insertion avoids the quadratic replay/validation cost of submitting 48 migration
    events through the interactive draft workflow.
    """
    packs = ContentPackManager(db)
    projects = ProjectStore(db)
    registry = SchemaRegistry(db.settings.root_dir)
    validation = packs.validate(authority_pack_zip)
    if not validation["valid"]:
        raise FoundryError("GOLDEN_AUTHORITY_PACK_INVALID", "The generated golden fixture authority pack failed validation.", details=validation)
    try:
        packs.install(authority_pack_zip)
    except FoundryError as exc:
        if exc.code not in {"PACK_ALREADY_INSTALLED", "PACK_IDEMPOTENT", "PACK_SAME_VERSION_INSTALLED"}:
            raise
    ledger = json.loads((fixture_root / "Character_Master_Ledger.json").read_text(encoding="utf-8"))
    for key, value in (ledger_overrides or {}).items():
        ledger[key] = value
    excluded = set(exclude_ledger_keys or set())
    packets = json.loads((fixture_root / "Build" / "Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    requested_locks = [{"pack_id": PACK_ID, "version": PACK_VERSION}] + list(additional_pack_locks or [])
    wrapper = projects.create_project(working_name=working_name, pack_locks=requested_locks, quality_target="golden-fixture")
    project = wrapper["project"]
    project_id = project["project_id"]
    now = utcnow()
    namespace = uuid.UUID("65f5ceab-933b-4c75-9ba1-89de86d02f89")
    with db.transaction() as conn:
        pack_hash = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?", (PACK_ID, PACK_VERSION)).fetchone()[0]
        record_rows = {
            row["record_id"]: json.loads(row["data_json"])
            for row in conn.execute("SELECT record_id,data_json FROM catalog_records WHERE pack_id=? AND pack_version=?", (PACK_ID, PACK_VERSION))
        }
        state = _initial_state(project_id)
        previous_hash = ZERO_HASH
        committed: list[dict[str, Any]] = []
        operations: list[tuple[str, str, Any, str]] = []
        for key in sorted(ledger):
            if key in excluded:
                continue
            operations.append(("ledger", "/" + key.replace("~", "~0").replace("/", "~1"), ledger[key], "TEST.FIXTURE.GOOD_CL13.LEDGER." + key.upper()))
        operations.append(("rules_selection_packets", "", packets, "TEST.FIXTURE.GOOD_CL13.RULES_SELECTION_PACKETS"))
        target_cl = int(ledger.get("character", {}).get("character_level", 13))
        for sequence, (target, pointer, value, record_id) in enumerate(operations, start=1):
            record = record_rows[record_id]
            event_id = str(uuid.uuid5(namespace, f"{project_id}:{sequence}:{record_id}"))
            migration = {
                "operation": "golden_fixture_reconstruction",
                "projection_operations": [{
                    "target": target,
                    "op": "set",
                    "path": pointer,
                    "value": value,
                    "source_kind": "audited_factory_fixture_section" if target == "ledger" else "audited_factory_fixture_rules_packets",
                }],
                "fixture_authority": {
                    "fixture": "GOOD_Authoritative_CL13",
                    "source_pointer": pointer if target == "ledger" else "/Build/Rules_Selection_Packets.json",
                },
            }
            draft = {
                "event_type": "migration",
                "effective_point": {"kind": "other", "character_cl": target_cl, "order": sequence, "label": f"golden fixture {target}{pointer}"[:200]},
                "actor_type": "migration",
                "actor_identifier": "phase3a-golden-fixture-migrator",
                "acquisition_channel": CHANNEL,
                "planner_response_id": None,
            }
            before_hash = sha256_json(state)
            event = canonical_event_from_draft(
                event_id=event_id,
                project_id=project_id,
                project_revision=sequence,
                sequence=sequence,
                draft=draft,
                subject_record=record,
                catalog_build_id=project["content_lock"]["catalog_build_id"],
                previous_event_hash=previous_hash,
                state_before_hash=before_hash,
                state_after_hash=ZERO_HASH,
                created_at=now,
                idempotency_key=event_id,
                migration=migration,
                canonical_event_type="migration",
            )
            state["migration_history"].append({"event_id": event_id, "migration": migration})
            event["state_after_hash"] = sha256_json(state)
            event["event_hash"] = canonical_event_hash(event)
            report = registry.report(event, "TianxiaFoundry.AdvancementEvent.v1")
            if not report["valid"]:
                raise FoundryError("GOLDEN_EVENT_INVALID", "A generated golden fixture event failed canonical validation.", details={"record_id": record_id, "diagnostics": report["diagnostics"]})
            conn.execute(
                """INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,
                legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (project_id, sequence, event_id, event["event_hash"], previous_hash, now, canonical_json(event), None, event["schema_version"], "valid"),
            )
            binding = record["content_binding"]
            conn.execute(
                "INSERT OR REPLACE INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                (project_id, record_id, binding["pack_id"], binding["pack_version"], record["record_hash"], canonical_json(record)),
            )
            conn.execute(
                """INSERT INTO canonical_object_validations(object_family,object_key,schema_version,boundary,valid,diagnostics_json,object_hash,validated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("advancement_event", event_id, event["schema_version"], "golden_fixture_batch_insert", 1, "[]", event["event_hash"], now),
            )
            previous_hash = event["event_hash"]
            committed.append(event)
        final_project = canonical_project_document(
            project_id=project_id,
            name=project["name"],
            revision=len(committed),
            status=project["status"],
            created_at=project["created_at"],
            updated_at=now,
            catalog_build_id=project["content_lock"]["catalog_build_id"],
            pack_locks=[dict(row) for row in conn.execute("SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version", (project_id,))],
            user_locks=project["user_locks"],
            source_inputs=project["source_inputs"],
            event_count=len(committed),
            head_hash=previous_hash,
            active_stage=project["active_stage"],
            stage_commits=project["stage_commits"],
            generated_artifacts=project["generated_artifacts"],
            candidates=project["candidates"],
            acceptance=project["acceptance"],
        )
        project_report = registry.report(final_project, "TianxiaFoundry.CharacterProject.v1")
        if not project_report["valid"]:
            raise FoundryError("GOLDEN_PROJECT_INVALID", "The reconstructed golden project failed canonical validation.", details=project_report["diagnostics"])
        conn.execute(
            "UPDATE projects SET revision=?,updated_at=?,project_json=?,canonical_project_hash=?,contract_status='valid' WHERE project_id=?",
            (len(committed), now, canonical_json(final_project), canonical_project_hash(final_project), project_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)",
            (project_id, len(committed), sha256_json(state), canonical_json(state), now),
        )
    replay = projects.replay(project_id)
    if replay["latest_event_hash"] != previous_hash or replay["state_hash"] != sha256_json(state):
        raise FoundryError("GOLDEN_REPLAY_MISMATCH", "Post-commit replay did not reproduce the batch migration hashes.", details={"expected_head": previous_hash, "actual_head": replay["latest_event_hash"], "expected_state": sha256_json(state), "actual_state": replay["state_hash"]})
    return {"project_id": project_id, "event_count": len(committed), "head_hash": previous_hash, "state_hash": replay["state_hash"], "pack_hash": pack_hash}
