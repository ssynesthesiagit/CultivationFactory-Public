from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

from app.core import (
    APP_VERSION,
    FACTORY_VERSION,
    GM_SCREEN_VERSION,
    Database,
    FoundryError,
    canonical_json,
    resolve_inside,
    sha256_bytes,
    sha256_file,
    sha256_json,
    utcnow,
)
from catalog.service import (
    CATALOG_SCHEMA_VERSION,
    PROJECT_SCHEMA_VERSION,
    CatalogService,
    _foundry_version_matches,
)
from content_packs.identity import compute_payload_identity, normalize_payload_path
from content_packs.membership import verify_pack_seal
from security.approval_challenges import ApprovalChallengeService
from security.integrity import IntegrityService
from security.local_identity import PrincipalProvider, ProcessPrincipalProvider, reject_reserved_identity
from contracts.registry import SchemaRegistry
from stage2.authority_contract import (
    MANUAL_CONTENT_TYPES,
    RECORDED_ART_EXPRESSION_KINDS,
    allowed_content_types_for_kind,
    recorded_art_expression_issues,
)

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 192 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_DEPTH = 10
EXECUTABLE_SUFFIXES = {
    ".exe", ".dll", ".com", ".scr", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".py", ".pyc", ".pyd", ".so"
}
KNOWN_CONTENT_TYPES = {
    "path",
    "path_feature",
    "path_feature_component",
    "subpath",
    "subpath_feature",
    "tradition",
    "tradition_feature",
    "sphere",
    "talent",
    "foundation",
    "foundation_family",
    "foundation_expression",
    "cultivation_method",
    "cultivation_insight",
    "item",
    "treasure_set",
    "background",
    "origin_insight",
    "manual",
    "martial_manual",
    "manual_expression",
    "recorded_art",
    "forged_technique_component",
    "companion",
    "source_document",
}

TRUSTED_PUBLISHERS_PATH = Path(__file__).with_name("trusted_publishers.json")
SIGNATURE_SCHEMA = "TianxiaFoundry.ContentPackSignature.v1"
HUMAN_TRUST_CONFIRMATION_PREFIX = "TRUST_LOCAL_CONTENT_PACK:"
LIFECYCLE_TRANSITIONS = {
    "draft": {"draft", "validated", "published", "retired"},
    "validated": {"validated", "published", "retired"},
    "published": {"published", "superseded", "retired"},
    "superseded": {"superseded", "retired"},
    "retired": {"retired"},
    "quarantined": {"quarantined"},
}


class ContentPackManager:
    def __init__(self, db: Database, *, trusted_publishers: dict[str, Any] | None = None, principal_provider: PrincipalProvider | None = None, integrity: IntegrityService | None = None):
        self.db = db
        self.integrity = integrity or IntegrityService.for_database(db)
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.challenges = ApprovalChallengeService(db, self.principal_provider, self.integrity)
        self.catalog = CatalogService(db, integrity=self.integrity)
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.manifest_schema = self.registry.schema("TianxiaFoundry.ContentPackManifest.v1")
        self.record_schema = self.registry.schema("TianxiaFoundry.RulesCatalogRecord.v1")
        self.manifest_validator = Draft202012Validator(self.manifest_schema, format_checker=FormatChecker())
        self.record_validator = Draft202012Validator(self.record_schema, format_checker=FormatChecker())
        self.signature_schema = self.registry.schema(SIGNATURE_SCHEMA)
        self.signature_validator = Draft202012Validator(self.signature_schema, format_checker=FormatChecker())
        self.replacement_schema = self.registry.schema("TianxiaFoundry.FoundationReplacementMap.v1")
        self.replacement_validator = Draft202012Validator(self.replacement_schema, format_checker=FormatChecker())
        self.trusted_publishers = trusted_publishers or self._load_trusted_publishers()

    @staticmethod
    def _load_trusted_publishers() -> dict[str, Any]:
        value = json.loads(TRUSTED_PUBLISHERS_PATH.read_text(encoding="utf-8"))
        if value.get("schema_version") != "TianxiaFoundry.TrustedContentPublishers.v1":
            raise RuntimeError("The built-in Content Pack publisher registry has an unsupported schema.")
        result: dict[str, Any] = {}
        for row in value.get("publishers", []):
            key_id = row.get("key_id")
            if not isinstance(key_id, str) or key_id in result:
                raise RuntimeError("The built-in Content Pack publisher registry contains a duplicate or invalid key ID.")
            raw = base64.b64decode(row["public_key_base64"], validate=True)
            if len(raw) != 32 or sha256_bytes(raw) != row.get("public_key_sha256"):
                raise RuntimeError(f"Trusted publisher key material failed its pinned fingerprint: {key_id}")
            result[key_id] = dict(row)
        return result

    @staticmethod
    def _authority_for(pack_id: str, trust_state: str) -> str:
        if pack_id.upper().startswith("TEST"):
            return "test-only"
        if trust_state in {"trusted_signed", "human_trusted_exact_archive"}:
            return "published-extension"
        return "quarantined"

    @staticmethod
    def _named_lifecycle_actor(actor: str | None, *, allow_reserved_machine: bool = False) -> str:
        value = str(actor or "").strip()
        if not value:
            raise FoundryError(
                "PACK_LIFECYCLE_ACTOR_REQUIRED",
                "Content Pack lifecycle actions require a named actor for retained audit evidence.",
            )
        if len(value) > 200:
            raise FoundryError(
                "PACK_LIFECYCLE_ACTOR_INVALID",
                "The lifecycle actor name exceeds the supported length.",
            )
        if not allow_reserved_machine:
            reject_reserved_identity(value, field_name="Content Pack lifecycle actor")
        return value

    def _append_lifecycle_audit_event(
        self,
        conn: sqlite3.Connection,
        *,
        pack_id: str,
        version: str,
        pack_hash: str,
        from_state: str | None,
        to_state: str,
        transition_kind: str,
        actor: str,
        occurred_at: str,
        superseded_by_version: str | None = None,
        evidence: dict[str, Any] | None = None,
        authoritative_principal_id: str | None = None,
        approval_challenge_id: str | None = None,
        approval_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        actor = ContentPackManager._named_lifecycle_actor(
            actor, allow_reserved_machine=authoritative_principal_id is None
        )
        evidence_core = {
            "schema_version": "TianxiaFoundry.ContentPackLifecycleTransition.v2",
            "pack_id": pack_id,
            "version": version,
            "canonical_content_hash": pack_hash,
            "from_state": from_state,
            "to_state": to_state,
            "superseded_by_version": superseded_by_version,
            "transition_kind": transition_kind,
            "actor": actor,
            "authoritative_principal_id": authoritative_principal_id,
            "approval_challenge_id": approval_challenge_id,
            "approval_evidence_id": approval_evidence_id,
            "occurred_at": occurred_at,
            **(evidence or {}),
        }
        evidence_hash = sha256_json(evidence_core)
        event_id = "pack.lifecycle." + evidence_hash
        transition_projection = {
            "schema_version": "TianxiaFoundry.ContentPackLifecycleIntegrity.v1",
            "event_id": event_id,
            "evidence": evidence_core,
            "evidence_hash": evidence_hash,
        }
        transition_projection_json = canonical_json(transition_projection)
        transition_projection_hash = sha256_json(transition_projection)
        envelope = self.integrity.sign("tianxia.foundry.content_pack.lifecycle.v1", transition_projection)
        conn.execute(
            """INSERT INTO content_pack_lifecycle_audit_events(
               event_id,pack_id,version,canonical_content_hash,from_state,to_state,
               superseded_by_version,transition_kind,evidence_json,evidence_hash,occurred_at,
               authoritative_principal_id,approval_challenge_id,approval_evidence_id,
               transition_projection_json,transition_projection_hash,integrity_version,integrity_key_id,integrity_domain,integrity_mac)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id, pack_id, version, pack_hash, from_state, to_state,
                superseded_by_version, transition_kind, canonical_json(evidence_core),
                evidence_hash, occurred_at, authoritative_principal_id, approval_challenge_id,
                approval_evidence_id,transition_projection_json,transition_projection_hash,
                envelope.integrity_version,envelope.key_id,envelope.domain,envelope.mac,
            ),
        )
        return {**evidence_core, "event_id": event_id, "evidence_hash": evidence_hash, "transition_projection_hash": transition_projection_hash, **envelope.as_dict()}

    def _verify_lifecycle_event(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        try:
            evidence = json.loads(row["evidence_json"])
            projection = json.loads(row["transition_projection_json"])
        except Exception as exc:
            raise FoundryError(
                "PACK_LIFECYCLE_EVIDENCE_INVALID",
                "A Content Pack lifecycle event contains malformed canonical evidence.",
                details={"event_id": row["event_id"], "error": type(exc).__name__},
                status_code=409,
            ) from exc
        if canonical_json(evidence) != row["evidence_json"] or sha256_json(evidence) != row["evidence_hash"]:
            raise FoundryError("PACK_LIFECYCLE_EVIDENCE_INVALID", "Lifecycle evidence bytes or hash are invalid.", details={"event_id": row["event_id"]}, status_code=409)
        expected_id = "pack.lifecycle." + row["evidence_hash"]
        if row["event_id"] != expected_id:
            raise FoundryError("PACK_LIFECYCLE_EVIDENCE_INVALID", "Lifecycle event ID is not derived from its exact evidence.", details={"event_id": row["event_id"]}, status_code=409)
        exact_fields = {
            "pack_id": row["pack_id"], "version": row["version"], "canonical_content_hash": row["canonical_content_hash"],
            "from_state": row["from_state"], "to_state": row["to_state"], "superseded_by_version": row["superseded_by_version"],
            "transition_kind": row["transition_kind"], "authoritative_principal_id": row["authoritative_principal_id"],
            "approval_challenge_id": row["approval_challenge_id"], "approval_evidence_id": row["approval_evidence_id"],
            "occurred_at": row["occurred_at"],
        }
        for field, value in exact_fields.items():
            if evidence.get(field) != value:
                raise FoundryError("PACK_LIFECYCLE_EVIDENCE_INVALID", "Lifecycle evidence differs from its immutable columns.", details={"event_id": row["event_id"], "field": field}, status_code=409)
        if canonical_json(projection) != row["transition_projection_json"] or sha256_json(projection) != row["transition_projection_hash"]:
            raise FoundryError("PACK_LIFECYCLE_EVIDENCE_INVALID", "Lifecycle integrity projection bytes or hash are invalid.", details={"event_id": row["event_id"]}, status_code=409)
        if projection != {
            "schema_version": "TianxiaFoundry.ContentPackLifecycleIntegrity.v1",
            "event_id": row["event_id"], "evidence": evidence, "evidence_hash": row["evidence_hash"],
        }:
            raise FoundryError("PACK_LIFECYCLE_EVIDENCE_INVALID", "Lifecycle integrity projection differs from the exact transition evidence.", details={"event_id": row["event_id"]}, status_code=409)
        self.integrity.verify(
            "tianxia.foundry.content_pack.lifecycle.v1", projection,
            {"integrity_version": row["integrity_version"], "algorithm": "HMAC-SHA-256", "key_id": row["integrity_key_id"],
             "domain": row["integrity_domain"], "projection_hash": row["transition_projection_hash"], "mac": row["integrity_mac"]},
        )
        evidence_id = row["approval_evidence_id"]
        if evidence_id:
            approval = conn.execute("SELECT * FROM exact_approval_evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
            if not approval:
                raise FoundryError("PACK_LIFECYCLE_APPROVAL_EVIDENCE_MISSING", "Lifecycle transition approval evidence is missing.", details={"event_id": row["event_id"]}, status_code=409)
            try:
                approval_projection = json.loads(approval["approval_projection_json"])
            except Exception as exc:
                raise FoundryError("PACK_LIFECYCLE_APPROVAL_EVIDENCE_INVALID", "Lifecycle transition approval evidence is malformed.", details={"event_id": row["event_id"]}, status_code=409) from exc
            self.integrity.verify(
                "tianxia.foundry.approval_evidence.v2", approval_projection,
                {"integrity_version": approval["integrity_version"], "algorithm": "HMAC-SHA-256", "key_id": approval["integrity_key_id"],
                 "domain": approval["integrity_domain"], "projection_hash": approval["approval_projection_hash"], "mac": approval["integrity_mac"]},
            )
            if approval["challenge_id"] != row["approval_challenge_id"] or approval["principal_id"] != row["authoritative_principal_id"]:
                raise FoundryError("PACK_LIFECYCLE_APPROVAL_EVIDENCE_INVALID", "Lifecycle transition identity differs from its exact approval evidence.", details={"event_id": row["event_id"]}, status_code=409)
        return projection

    def _verify_lifecycle_history(self, conn: sqlite3.Connection, pack_id: str, version: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM content_pack_lifecycle_audit_events WHERE pack_id=? AND version=? ORDER BY sequence_no",
            (pack_id, version),
        ).fetchall()
        projections: list[dict[str, Any]] = []
        prior_state: str | None = None
        prior_global_sequence = 0
        for row in rows:
            sequence_no = int(row["sequence_no"])
            # sequence_no is the append-only global lifecycle audit ordinal, not
            # a per-pack counter. Other pack/version transitions may interleave,
            # so this history requires strict monotonicity plus an exact state
            # chain rather than artificial adjacency.
            if sequence_no <= prior_global_sequence or row["from_state"] != prior_state:
                raise FoundryError(
                    "PACK_LIFECYCLE_SEQUENCE_INVALID",
                    "Content Pack lifecycle history is not a monotonic immutable state transition chain.",
                    details={
                        "pack_id": pack_id, "version": version,
                        "sequence_no": sequence_no, "prior_sequence_no": prior_global_sequence,
                        "expected_from_state": prior_state, "actual_from_state": row["from_state"],
                    }, status_code=409,
                )
            projections.append(self._verify_lifecycle_event(conn, row))
            prior_global_sequence = sequence_no
            prior_state = row["to_state"]
        return projections

    def _successor_proof(
        self,
        conn: sqlite3.Connection,
        *,
        pack_id: str,
        current_version: str,
        successor_version: str,
    ) -> dict[str, Any]:
        if successor_version == current_version:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INVALID",
                "A Content Pack version cannot supersede itself.",
            )
        successor = conn.execute(
            """SELECT p.pack_hash,p.lifecycle_state,p.authority,p.installed_path,p.manifest_json,
                      receipt.trust_state,receipt.receipt_hash,
                      (SELECT COUNT(*) FROM catalog_records r
                       WHERE r.pack_id=p.pack_id AND r.pack_version=p.version
                         AND r.publication_state<>'published') AS nonpublished_record_count
               FROM content_packs p
               LEFT JOIN content_pack_install_receipts receipt
                 ON receipt.pack_id=p.pack_id AND receipt.version=p.version
                AND receipt.canonical_content_hash=p.pack_hash
               WHERE p.pack_id=? AND p.version=?""",
            (pack_id, successor_version),
        ).fetchone()
        if not successor:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_NOT_INSTALLED",
                "The named successor version is not installed under the same Content Pack ID.",
                details={"pack_id": pack_id, "successor_version": successor_version},
            )
        # R4: lifecycle authority must be rooted in the externally keyed install seal,
        # not only in mutually writable lifecycle/trust columns.
        successor_seal = verify_pack_seal(
            conn,
            pack_id=pack_id,
            version=successor_version,
            expected_pack_hash=successor["pack_hash"],
            integrity=self.integrity,
        )
        if successor["lifecycle_state"] != "published":
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_NOT_PUBLISHED",
                "The named successor must already be published.",
                details={"pack_id": pack_id, "successor_version": successor_version, "lifecycle_state": successor["lifecycle_state"]},
            )
        explicit_test = successor["authority"] == "test-only" and pack_id.upper().startswith("TEST")
        trusted = (
            successor["authority"] == "canonical"
            or explicit_test
            or (
                successor["authority"] == "published-extension"
                and successor["trust_state"] in {"trusted_signed", "human_trusted_exact_archive"}
            )
        )
        if not trusted:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_UNTRUSTED",
                "The named successor lacks published canonical or immutable trusted extension authority.",
                details={
                    "pack_id": pack_id,
                    "successor_version": successor_version,
                    "authority": successor["authority"],
                    "trust_state": successor["trust_state"],
                },
            )
        if successor["nonpublished_record_count"]:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_RECORDS_NOT_PUBLISHED",
                "The named successor contains records that are not published.",
                details={"pack_id": pack_id, "successor_version": successor_version},
            )
        try:
            manifest = json.loads(successor["manifest_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_MANIFEST_INVALID",
                "The named successor manifest cannot be audited.",
            ) from exc
        compatibility = manifest.get("compatibility")
        if not isinstance(compatibility, dict):
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                "The named successor has no usable compatibility declaration.",
            )
        expected = {
            "project_schema": PROJECT_SCHEMA_VERSION,
            "catalog_schema": CATALOG_SCHEMA_VERSION,
        }
        for field, current in expected.items():
            if compatibility.get(field) != current:
                raise FoundryError(
                    "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                    "The named successor does not support the active runtime contracts.",
                    details={"field": field, "required": current, "declared": compatibility.get(field)},
                )
        producers = compatibility.get("factory_producers") or []
        consumers = compatibility.get("gm_screen_consumers") or []
        if producers and FACTORY_VERSION not in producers:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                "The named successor does not support the active Factory producer.",
                details={"required": FACTORY_VERSION, "declared": producers},
            )
        if consumers and GM_SCREEN_VERSION not in consumers:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                "The named successor does not support the active GM Screen consumer.",
                details={"required": GM_SCREEN_VERSION, "declared": consumers},
            )
        foundry_range = compatibility.get("foundry")
        try:
            foundry_compatible = isinstance(foundry_range, str) and _foundry_version_matches(APP_VERSION, foundry_range)
        except ValueError as exc:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                "The named successor uses an unsupported Foundry compatibility range.",
                details={"required": APP_VERSION, "declared": foundry_range},
            ) from exc
        if not foundry_compatible:
            raise FoundryError(
                "PACK_SUPERSEDED_SUCCESSOR_INCOMPATIBLE",
                "The named successor does not support this Foundry version.",
                details={"required": APP_VERSION, "declared": foundry_range},
            )
        migration = next(
            (
                item for item in manifest.get("migrations") or []
                if isinstance(item, dict) and item.get("from_version") == current_version
            ),
            None,
        )
        if migration is None:
            raise FoundryError(
                "PACK_SUPERSESSION_MIGRATION_REQUIRED",
                "The named successor must retain a hash-bound migration map from the superseded version.",
                details={"pack_id": pack_id, "from_version": current_version, "to_version": successor_version},
            )
        try:
            migration_rel = normalize_payload_path(migration["map_path"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FoundryError(
                "PACK_SUPERSESSION_MIGRATION_INVALID",
                "The successor migration map path is invalid.",
                details={"migration": migration},
            ) from exc
        root = Path(successor["installed_path"] or "").resolve()
        migration_path = (root / PurePosixPath(migration_rel)).resolve()
        if root not in migration_path.parents or not migration_path.is_file():
            raise FoundryError(
                "PACK_SUPERSESSION_MIGRATION_MISSING",
                "The successor's declared migration map is not present in its immutable installed payload.",
                details={"map_path": migration_rel},
            )
        actual_migration_hash = sha256_file(migration_path)
        if migration.get("sha256") != actual_migration_hash:
            raise FoundryError(
                "PACK_SUPERSESSION_MIGRATION_HASH_MISMATCH",
                "The successor migration map no longer matches its manifest hash.",
                details={"map_path": migration_rel, "expected": migration.get("sha256"), "actual": actual_migration_hash},
            )
        return {
            "successor_pack_hash": successor["pack_hash"],
            "successor_lifecycle_state": successor["lifecycle_state"],
            "successor_authority": successor["authority"],
            "successor_trust_state": successor["trust_state"] or ("canonical" if successor["authority"] == "canonical" else None),
            "successor_receipt_hash": successor["receipt_hash"],
            "successor_manifest_hash": sha256_json(manifest),
            "successor_compatibility_hash": sha256_json(compatibility),
            "migration_map_path": migration_rel,
            "migration_map_sha256": actual_migration_hash,
        }

    def _safe_extract_zip(self, package: Path, destination: Path) -> None:
        if package.stat().st_size > MAX_ARCHIVE_BYTES:
            raise FoundryError("ARCHIVE_TOO_LARGE", "Content Pack archive exceeds the size limit.")
        with zipfile.ZipFile(package) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise FoundryError("ARCHIVE_ENTRY_LIMIT", "Content Pack archive has too many entries.")
            total = 0
            member_keys: dict[str, str] = {}
            for info in infos:
                portable_name = info.filename[:-1] if info.is_dir() and info.filename.endswith("/") else info.filename
                posix = PurePosixPath(portable_name)
                if posix.is_absolute() or ".." in posix.parts:
                    raise FoundryError("ZIP_TRAVERSAL", "Content Pack contains an unsafe path.", details={"entry": info.filename})
                if len(posix.parts) > MAX_DEPTH:
                    raise FoundryError("ARCHIVE_NESTING_LIMIT", "Content Pack nesting exceeds the limit.", details={"entry": info.filename})
                unix_type = (info.external_attr >> 16) & 0o170000
                if unix_type == 0o120000:
                    raise FoundryError("ARCHIVE_SYMLINK_REJECTED", "Content Packs may not contain symbolic links.", details={"entry": info.filename})
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise FoundryError("ARCHIVE_EXPANSION_LIMIT", "Content Pack expands beyond the configured limit.")
                try:
                    normalized = normalize_payload_path(portable_name)
                except ValueError as exc:
                    raise FoundryError("UNSAFE_ARCHIVE_PATH", str(exc), details={"entry": info.filename}) from exc
                if Path(normalized).suffix.lower() in EXECUTABLE_SUFFIXES:
                    raise FoundryError("EXECUTABLE_CONTENT_REJECTED", "Content Packs may not contain executable files.", details={"entry": info.filename})
                key = normalized.casefold()
                if key in member_keys:
                    raise FoundryError(
                        "ARCHIVE_DUPLICATE_PATH",
                        "Content Pack ZIP members collide exactly or by case-folding.",
                        details={"entry": normalized, "existing": member_keys[key]},
                    )
                member_keys[key] = normalized
            zf.extractall(destination)

    def _materialize(self, package: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
        package = package.resolve()
        if not package.exists():
            raise FoundryError("PACK_NOT_FOUND", "The Content Pack package does not exist.", details={"path": str(package)}, status_code=404)
        if package.is_dir():
            for p in package.rglob("*"):
                rel = p.relative_to(package).as_posix()
                try:
                    normalize_payload_path(rel)
                except ValueError as exc:
                    raise FoundryError("UNSAFE_PAYLOAD_PATH", str(exc), details={"entry": rel}) from exc
                if p.is_symlink():
                    raise FoundryError("ARCHIVE_SYMLINK_REJECTED", "Content Packs may not contain symbolic links.", details={"entry": str(p.relative_to(package))})
                if p.is_file() and p.suffix.lower() in EXECUTABLE_SUFFIXES:
                    raise FoundryError("EXECUTABLE_CONTENT_REJECTED", "Content Packs may not contain executable files.", details={"entry": str(p.relative_to(package))})
                if len(p.relative_to(package).parts) > MAX_DEPTH:
                    raise FoundryError("ARCHIVE_NESTING_LIMIT", "Content Pack nesting exceeds the limit.")
            return package, None
        if package.suffix.lower() != ".zip":
            raise FoundryError("PACK_FORMAT_UNSUPPORTED", "Content Packs must be directories or ZIP files.")
        tmp = tempfile.TemporaryDirectory(prefix="tianxia_pack_")
        root = Path(tmp.name)
        self._safe_extract_zip(package, root)
        children = [p for p in root.iterdir() if p.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir() and not (root / "pack.json").exists():
            root = children[0]
        return root, tmp

    @staticmethod
    def _schema_errors(validator: Draft202012Validator, value: Any) -> list[dict[str, Any]]:
        errors = []
        for error in sorted(validator.iter_errors(value), key=lambda e: list(e.path)):
            errors.append({
                "path": "/" + "/".join(str(x) for x in error.path),
                "message": error.message,
                "validator": error.validator,
            })
        return errors

    @staticmethod
    def _package_identity(package: Path) -> dict[str, Any]:
        package = package.resolve()
        if package.is_file():
            return {
                "kind": "zip",
                "archive_sha256": sha256_file(package),
                "package_identity_sha256": sha256_file(package),
                "package_bytes": package.stat().st_size,
            }
        rows: list[dict[str, Any]] = []
        total = 0
        for path in sorted(p for p in package.rglob("*") if p.is_file()):
            rel = path.relative_to(package).as_posix()
            rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
            total += path.stat().st_size
        return {
            "kind": "directory",
            "archive_sha256": None,
            "package_identity_sha256": sha256_json(rows),
            "package_bytes": total,
        }

    @staticmethod
    def _physical_payload(root: Path) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
        payload: dict[str, bytes] = {}
        issues: list[dict[str, Any]] = []
        casefolded: dict[str, str] = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if rel == "pack.json":
                continue
            try:
                normalized = normalize_payload_path(rel)
            except ValueError as exc:
                issues.append({"code": "UNSAFE_PAYLOAD_PATH", "path": rel, "message": str(exc)})
                continue
            key = normalized.casefold()
            if key in casefolded:
                issues.append({"code": "PAYLOAD_CASEFOLD_PATH_COLLISION", "path": normalized, "existing": casefolded[key]})
                continue
            casefolded[key] = normalized
            payload[normalized] = path.read_bytes()
        return payload, issues

    @staticmethod
    def _manifest_payload_paths(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        declared: dict[str, dict[str, Any]] = {}
        folded: dict[str, str] = {}
        issues: list[dict[str, Any]] = []
        for index, item in enumerate(manifest.get("files", [])):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            raw = item["path"]
            try:
                path = normalize_payload_path(raw)
            except ValueError as exc:
                issues.append({"code": "UNSAFE_DECLARED_PATH", "path": raw, "message": str(exc)})
                continue
            key = path.casefold()
            if path in declared:
                issues.append({"code": "DUPLICATE_DECLARED_PATH", "path": path, "index": index})
                continue
            if key in folded:
                issues.append({"code": "DECLARED_CASEFOLD_PATH_COLLISION", "path": path, "existing": folded[key]})
                continue
            folded[key] = path
            declared[path] = item
        return declared, issues

    @staticmethod
    def _semantic_reference_paths(manifest: dict[str, Any]) -> tuple[set[str], set[str], list[dict[str, Any]]]:
        referenced: set[str] = set()
        record_paths: set[str] = set()
        folded: dict[str, str] = {}
        issues: list[dict[str, Any]] = []

        def add(raw: object, *, code: str, record: bool = False) -> None:
            if not isinstance(raw, str):
                return
            try:
                path = normalize_payload_path(raw)
            except ValueError as exc:
                issues.append({"code": "UNSAFE_REFERENCED_PATH", "path": raw, "reference": code, "message": str(exc)})
                return
            key = path.casefold()
            if key in folded and folded[key] != path:
                issues.append({"code": "REFERENCED_CASEFOLD_PATH_COLLISION", "path": path, "existing": folded[key], "reference": code})
            folded[key] = path
            referenced.add(path)
            if record:
                record_paths.add(path)

        for item in manifest.get("records", []):
            if isinstance(item, dict):
                add(item.get("path"), code="records", record=True)
        for item in manifest.get("sources", []):
            if isinstance(item, dict):
                add(item.get("path"), code="sources")
        tests = manifest.get("tests") if isinstance(manifest.get("tests"), dict) else {}
        for item in tests.get("inventory", []):
            if isinstance(item, dict):
                add(item.get("path"), code="tests")
        add(tests.get("report_path"), code="test_report")
        for item in manifest.get("migrations", []):
            if isinstance(item, dict):
                add(item.get("map_path"), code="migrations")
        for item in manifest.get("replacement_maps", []):
            if isinstance(item, dict):
                add(item.get("path") or item.get("map_path"), code="replacement_maps")
        return referenced, record_paths, issues

    def _signature_report(self, package: Path, manifest: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        archive_hash = identity.get("archive_sha256")
        sidecar = package.with_name(package.name + ".sig.json")
        if not sidecar.is_file():
            return {"state": "unsigned", "trusted": False, "sidecar_path": None}
        if not archive_hash:
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": [{"code": "SIGNATURE_REQUIRES_ZIP_ARCHIVE"}]}
        try:
            value = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": [{"code": "SIGNATURE_SIDECAR_INVALID", "message": str(exc)}]}
        schema_issues = [{"code": "SIGNATURE_SCHEMA", **row} for row in self._schema_errors(self.signature_validator, value)]
        if schema_issues:
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": schema_issues}
        expected = {
            "pack_id": manifest.get("pack_id"),
            "version": manifest.get("version"),
            "content_hash": manifest.get("content_hash"),
            "archive_sha256": archive_hash,
        }
        mismatches = {key: {"expected": wanted, "actual": value.get(key)} for key, wanted in expected.items() if value.get(key) != wanted}
        if mismatches:
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": [{"code": "SIGNATURE_IDENTITY_MISMATCH", "mismatches": mismatches}]}
        publisher = self.trusted_publishers.get(value["key_id"])
        if publisher is None:
            return {
                "state": "untrusted_signer",
                "trusted": False,
                "key_id": value["key_id"],
                "sidecar_path": str(sidecar),
                "sidecar_sha256": sha256_file(sidecar),
            }
        if not any(str(value["pack_id"]).startswith(prefix) for prefix in publisher.get("pack_id_prefixes", [])):
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": [{"code": "SIGNER_NAMESPACE_MISMATCH", "key_id": value["key_id"], "pack_id": value["pack_id"]}]}
        signed = {key: item for key, item in value.items() if key != "signature_base64"}
        try:
            signature = base64.b64decode(value["signature_base64"], validate=True)
            public = base64.b64decode(publisher["public_key_base64"], validate=True)
            Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_json(signed).encode("utf-8"))
        except (ValueError, binascii.Error, InvalidSignature) as exc:
            return {"state": "invalid", "trusted": False, "sidecar_path": str(sidecar), "issues": [{"code": "SIGNATURE_INVALID", "key_id": value["key_id"], "message": str(exc)}]}
        return {
            "state": "trusted_signed",
            "trusted": True,
            "key_id": value["key_id"],
            "sidecar_path": str(sidecar),
            "sidecar_sha256": sha256_file(sidecar),
            "public_key_sha256": publisher["public_key_sha256"],
        }

    @staticmethod
    def _human_trust_report(approval: dict[str, Any] | None, identity: dict[str, Any]) -> dict[str, Any] | None:
        if approval is None:
            return None
        archive_hash = identity.get("archive_sha256")
        actor = str(approval.get("approved_by") or "").strip()
        submitted_hash = approval.get("archive_sha256")
        confirmation = approval.get("confirmation")
        if not archive_hash:
            raise FoundryError("HUMAN_TRUST_REQUIRES_ZIP", "Exact human trust is available only for immutable ZIP bytes.")
        if submitted_hash != archive_hash:
            raise FoundryError("HUMAN_TRUST_ARCHIVE_HASH_MISMATCH", "Human trust approval does not name the exact archive digest.", details={"expected": archive_hash, "actual": submitted_hash})
        if not actor:
            raise FoundryError("HUMAN_TRUST_ACTOR_REQUIRED", "A named human approver is required.")
        reject_reserved_identity(actor, field_name="Content Pack trust approver")
        if confirmation != HUMAN_TRUST_CONFIRMATION_PREFIX + archive_hash:
            raise FoundryError("HUMAN_TRUST_CONFIRMATION_REQUIRED", "The exact digest confirmation string is required.")
        canonical = {"approved_by": actor, "archive_sha256": archive_hash, "confirmation": confirmation}
        return {**canonical, "approval_hash": sha256_json(canonical)}

    @staticmethod
    def _validate_execution(record: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        templates = record.get("execution_templates", [])
        for idx, template in enumerate(templates):
            if not isinstance(template, dict):
                issues.append({"code": "EXECUTION_TEMPLATE_NOT_OBJECT", "path": f"/execution_templates/{idx}"})
                continue
            ttype = str(template.get("kind") or template.get("template_type") or "").lower()
            payload = template.get("payload") if isinstance(template.get("payload"), dict) else template
            if "action" in ttype or record.get("content_type") in {"recorded_art", "forged_technique_component"}:
                required = ["timing", "cost", "range", "target", "effect", "failure", "duration", "counterplay"]
                missing = [key for key in required if key not in payload or payload[key] in (None, "", [])]
                if not payload.get("roll_save_check") and not payload.get("resolution"):
                    missing.append("roll_save_check|resolution")
                if not payload.get("limit") and not payload.get("limits"):
                    missing.append("limit|limits")
                if missing:
                    issues.append({
                        "code": "INCOMPLETE_EXECUTABLE_ACTION",
                        "path": f"/execution_templates/{idx}",
                        "missing": missing,
                    })
        return issues

    @staticmethod
    def _validate_stage2_authority(record: dict[str, Any]) -> list[dict[str, Any]]:
        """Reject records that claim complete Stage 2 authority without a typed contract.

        Older/reference-only records remain installable.  This gate applies only
        when a publisher sets ``authority_complete`` and thereby asks the
        advancement compiler to trust the record as mechanical authority.
        """
        stage2 = record.get("compatibility", {}).get("factory", {}).get("stage2_authority")
        if not isinstance(stage2, dict) or not stage2.get("authority_complete"):
            return []
        issues: list[dict[str, Any]] = []
        rid = record.get("record_id")
        ctype = record.get("content_type")
        allowed = stage2.get("allowed_kinds")
        reference_only = set(record.get("legality", {}).get("acquisition_channels") or []) <= {"reference-only"}
        if not isinstance(allowed, list) or (not allowed and not reference_only) or any(not isinstance(x, str) or not x for x in allowed):
            issues.append({"code": "STAGE2_ALLOWED_KINDS_INCOMPLETE", "path": "/compatibility/factory/stage2_authority/allowed_kinds"})
            allowed = []
        for index, kind in enumerate(allowed):
            expected_types = allowed_content_types_for_kind(kind)
            if expected_types is None:
                issues.append({
                    "code": "STAGE2_ALLOWED_KIND_UNSUPPORTED",
                    "path": f"/compatibility/factory/stage2_authority/allowed_kinds/{index}",
                    "kind": kind,
                })
            elif ctype not in expected_types:
                issues.append({
                    "code": "STAGE2_EVENT_KIND_CONTENT_TYPE_MISMATCH",
                    "path": f"/compatibility/factory/stage2_authority/allowed_kinds/{index}",
                    "kind": kind,
                    "content_type": ctype,
                    "expected_content_types": sorted(expected_types),
                })
        if not isinstance(stage2.get("rule_id"), str) or not stage2.get("rule_id"):
            issues.append({"code": "STAGE2_RULE_ID_REQUIRED", "path": "/compatibility/factory/stage2_authority/rule_id"})

        talent_kinds = {
            "background_talent_acquisition", "sect_trial_talent_acquisition",
            "ai_bootstrap_talent_acquisition", "level_talent_acquisition", "talent_training_attempt",
            "new_sphere_bonus_talent_acquisition",
        }
        if ctype == "talent" and talent_kinds.intersection(allowed):
            if not isinstance(stage2.get("sphere_id"), str) or not stage2.get("sphere_id"):
                issues.append({"code": "STAGE2_TALENT_SPHERE_ID_REQUIRED", "path": "/compatibility/factory/stage2_authority/sphere_id"})

        if ctype == "background" and "background_acquisition" in allowed:
            packages = stage2.get("background_packages")
            if not isinstance(packages, list) or not packages:
                issues.append({"code": "STAGE2_BACKGROUND_PACKAGES_REQUIRED", "path": "/compatibility/factory/stage2_authority/background_packages"})
            else:
                for index, package in enumerate(packages):
                    if not isinstance(package, dict) or not isinstance(package.get("sphere_record_id"), str) or not isinstance(package.get("talent_record_id"), str):
                        issues.append({"code": "STAGE2_BACKGROUND_PACKAGE_INVALID", "path": f"/compatibility/factory/stage2_authority/background_packages/{index}"})

        if ctype == "path" and "path_acquisition" in allowed:
            for key in ("key_ability", "hp_level1_formula", "hp_later_formula", "resources", "required_milestones"):
                if stage2.get(key) in (None, "", []):
                    issues.append({"code": "STAGE2_PATH_AUTHORITY_INCOMPLETE", "path": f"/compatibility/factory/stage2_authority/{key}", "missing": key})

        source_access = stage2.get("training_source_access")
        if source_access is not None:
            if not isinstance(source_access, dict):
                issues.append({"code": "STAGE2_TRAINING_SOURCE_AUTHORITY_INVALID", "path": "/compatibility/factory/stage2_authority/training_source_access"})
            else:
                if source_access.get("mode") not in {"requires_access_event", "intrinsic_known_sphere_practice"}:
                    issues.append({"code": "STAGE2_TRAINING_SOURCE_MODE_UNSUPPORTED", "path": "/compatibility/factory/stage2_authority/training_source_access/mode"})
                if not isinstance(source_access.get("training_types"), list) or not source_access.get("training_types"):
                    issues.append({"code": "STAGE2_TRAINING_SOURCE_TYPES_REQUIRED", "path": "/compatibility/factory/stage2_authority/training_source_access/training_types"})
                if not isinstance(source_access.get("target_record_ids"), list) or not source_access.get("target_record_ids"):
                    issues.append({"code": "STAGE2_TRAINING_SOURCE_TARGETS_REQUIRED", "path": "/compatibility/factory/stage2_authority/training_source_access/target_record_ids"})
                if source_access.get("mode") == "requires_access_event":
                    manual_modes = (stage2.get("manual") or {}).get("access_modes") if isinstance(stage2.get("manual"), dict) else None
                    access_modes = source_access.get("access_modes", manual_modes)
                    if not isinstance(access_modes, list) or not access_modes:
                        issues.append({"code": "STAGE2_TRAINING_SOURCE_ACCESS_MODES_REQUIRED", "path": "/compatibility/factory/stage2_authority/training_source_access/access_modes"})

        if ctype in MANUAL_CONTENT_TYPES:
            manual = stage2.get("manual")
            if not isinstance(manual, dict):
                issues.append({"code": "STAGE2_MANUAL_AUTHORITY_REQUIRED", "path": "/compatibility/factory/stage2_authority/manual"})
            else:
                for key in ("lineage_source", "access_modes", "technique_record_ids", "reliability", "status"):
                    if manual.get(key) in (None, "", []):
                        issues.append({"code": "STAGE2_MANUAL_AUTHORITY_INCOMPLETE", "path": f"/compatibility/factory/stage2_authority/manual/{key}", "missing": key})

        if ctype == "recorded_art":
            art = stage2.get("recorded_art")
            required = {
                "parent_manual_record_id", "technique_name", "associated_sphere_record_ids",
                "expression_kind", "reproduced_component_record_ids", "execution_derivation",
                "learning_dc", "study_time", "allowed_study_abilities", "requirements",
                "fixed_expression_only", "grants_sphere", "grants_talent",
                "grants_modification_permission",
            }
            if not isinstance(art, dict):
                issues.append({"code": "STAGE2_RECORDED_ART_AUTHORITY_REQUIRED", "path": "/compatibility/factory/stage2_authority/recorded_art"})
            else:
                missing = sorted(required - set(art))
                if missing:
                    issues.append({"code": "STAGE2_RECORDED_ART_AUTHORITY_INCOMPLETE", "path": "/compatibility/factory/stage2_authority/recorded_art", "missing": missing})
                if art.get("fixed_expression_only") is not True or any(art.get(key) is not False for key in ("grants_sphere", "grants_talent", "grants_modification_permission")):
                    issues.append({"code": "STAGE2_RECORDED_ART_FIXED_EXPRESSION_REQUIRED", "path": "/compatibility/factory/stage2_authority/recorded_art"})
                if art.get("expression_kind") not in RECORDED_ART_EXPRESSION_KINDS:
                    issues.append({"code": "STAGE2_RECORDED_ART_EXPRESSION_KIND_UNSUPPORTED", "path": "/compatibility/factory/stage2_authority/recorded_art/expression_kind"})
                learning = art.get("learning_dc") if isinstance(art.get("learning_dc"), dict) else {}
                if learning.get("mode") == "difficulty_formula":
                    if not isinstance(learning.get("difficulty"), int) or learning.get("difficulty") < 0 or "explicit_dc" in learning or "override_rule_record_id" in learning:
                        issues.append({"code": "STAGE2_RECORDED_ART_DIFFICULTY_INVALID", "path": "/compatibility/factory/stage2_authority/recorded_art/learning_dc"})
                elif learning.get("mode") == "explicit_dc_override":
                    if not isinstance(learning.get("explicit_dc"), int) or not isinstance(learning.get("override_rule_record_id"), str) or "difficulty" in learning:
                        issues.append({"code": "STAGE2_RECORDED_ART_DC_OVERRIDE_INCOMPLETE", "path": "/compatibility/factory/stage2_authority/recorded_art/learning_dc"})
                else:
                    issues.append({"code": "STAGE2_RECORDED_ART_LEARNING_MODE_UNRESOLVED", "path": "/compatibility/factory/stage2_authority/recorded_art/learning_dc/mode"})
        return [{"record_id": rid, **issue} for issue in issues]

    @staticmethod
    def _validate_stage2_authority_relations(
        record_map: dict[str, dict[str, Any]],
        subject_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-check every complete Stage 2 authority reference within a pack."""
        issues: list[dict[str, Any]] = []
        selected = subject_ids if subject_ids is not None else set(record_map)
        for rid in sorted(selected):
            record = record_map.get(rid)
            if not isinstance(record, dict):
                continue
            stage2 = record.get("compatibility", {}).get("factory", {}).get("stage2_authority")
            if not isinstance(stage2, dict) or not stage2.get("authority_complete"):
                continue
            referenced: list[tuple[str, str, str | frozenset[str] | None]] = []
            if isinstance(stage2.get("sphere_id"), str):
                referenced.append(("talent_sphere", stage2["sphere_id"], "sphere"))
            for package in stage2.get("background_packages", []) if isinstance(stage2.get("background_packages"), list) else []:
                if isinstance(package, dict):
                    referenced.extend([
                        ("background_sphere", package.get("sphere_record_id"), "sphere"),
                        ("background_talent", package.get("talent_record_id"), "talent"),
                    ])
            access = stage2.get("training_source_access") if isinstance(stage2.get("training_source_access"), dict) else {}
            for target in access.get("target_record_ids", []) if isinstance(access.get("target_record_ids"), list) else []:
                referenced.append(("training_target", target, None))
            manual = stage2.get("manual") if isinstance(stage2.get("manual"), dict) else {}
            for technique in manual.get("technique_record_ids", []) if isinstance(manual.get("technique_record_ids"), list) else []:
                referenced.append(("manual_technique", technique, "recorded_art"))
            art = stage2.get("recorded_art") if isinstance(stage2.get("recorded_art"), dict) else {}
            if art:
                referenced.append(("parent_manual", art.get("parent_manual_record_id"), MANUAL_CONTENT_TYPES))
                for sphere in art.get("associated_sphere_record_ids", []) if isinstance(art.get("associated_sphere_record_ids"), list) else []:
                    referenced.append(("associated_sphere", sphere, "sphere"))
                for component in art.get("reproduced_component_record_ids", []) if isinstance(art.get("reproduced_component_record_ids"), list) else []:
                    referenced.append(("reproduced_component", component, None))
                derivation = art.get("execution_derivation") if isinstance(art.get("execution_derivation"), dict) else {}
                source_id = derivation.get("source_record_id")
                if isinstance(source_id, str):
                    referenced.append(("execution_source", source_id, None))
            for role, target_id, expected_type in referenced:
                target = record_map.get(target_id) if isinstance(target_id, str) else None
                if target is None:
                    issues.append({"code": "STAGE2_AUTHORITY_REFERENCE_MISSING", "record_id": rid, "role": role, "target_record_id": target_id})
                elif expected_type:
                    expected_types = {expected_type} if isinstance(expected_type, str) else set(expected_type)
                    if target.get("content_type") not in expected_types:
                        issues.append({"code": "STAGE2_AUTHORITY_REFERENCE_TYPE_MISMATCH", "record_id": rid, "role": role, "target_record_id": target_id, "expected_type": sorted(expected_types), "actual_type": target.get("content_type")})
            if art:
                # The expression kind determines the exact number, order, and
                # published content types of its components.  Merely resolving
                # IDs is not sufficient: that was the loophole that allowed an
                # arbitrary JSON action to masquerade as a Martial Art.
                issues.extend(recorded_art_expression_issues(
                    record_id=rid,
                    art=art,
                    record_map=record_map,
                ))
                parent = record_map.get(art.get("parent_manual_record_id"))
                parent_manual = parent.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("manual", {}) if parent else {}
                if rid not in parent_manual.get("technique_record_ids", []):
                    issues.append({"code": "STAGE2_MANUAL_TECHNIQUE_BACKLINK_MISSING", "record_id": rid, "parent_manual_record_id": art.get("parent_manual_record_id")})
                derivation = art.get("execution_derivation") if isinstance(art.get("execution_derivation"), dict) else {}
                source = record_map.get(derivation.get("source_record_id"))
                template_id = derivation.get("template_id")
                template = next((x for x in source.get("execution_templates", []) if x.get("template_id") == template_id and x.get("template_type") == "action"), None) if source else None
                if derivation.get("mode") != "copy_exact_published_template" or template is None:
                    issues.append({"code": "STAGE2_RECORDED_ART_EXECUTION_DERIVATION_UNPROVEN", "record_id": rid, "source_record_id": derivation.get("source_record_id"), "template_id": template_id})
                elif isinstance(template.get("payload"), dict):
                    canonical_action_fields = {
                        "action_id", "name", "timing", "cost", "range", "target",
                        "roll_save_check", "effect", "failure", "duration", "limit", "counterplay",
                    }
                    missing_fields = sorted(canonical_action_fields - set(template["payload"]))
                    if missing_fields:
                        issues.append({"code": "STAGE2_RECORDED_ART_EXECUTION_TEMPLATE_INCOMPLETE", "record_id": rid, "source_record_id": derivation.get("source_record_id"), "template_id": template_id, "missing": missing_fields})
                component_ids = art.get("reproduced_component_record_ids", [])
                if derivation.get("source_record_id") not in component_ids:
                    issues.append({"code": "STAGE2_RECORDED_ART_EXECUTION_SOURCE_NOT_COMPONENT", "record_id": rid})
                associated = set(art.get("associated_sphere_record_ids", []))
                for component_id in component_ids:
                    component = record_map.get(component_id)
                    component_sphere = component.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("sphere_id") if component else None
                    if component_sphere and component_sphere not in associated:
                        issues.append({"code": "STAGE2_RECORDED_ART_COMPONENT_SPHERE_OMITTED", "record_id": rid, "component_record_id": component_id, "component_sphere_id": component_sphere})
        return issues

    @staticmethod
    def _record_dependencies(record: dict[str, Any]) -> list[str]:
        deps: list[str] = []
        for dep in record.get("dependencies", []):
            if isinstance(dep, str):
                deps.append(dep)
            elif isinstance(dep, dict):
                for key in ("record_id", "target_id", "dependency_id"):
                    if isinstance(dep.get(key), str):
                        deps.append(dep[key])
                        break
        for prereq in record.get("legality", {}).get("prerequisites", []):
            if isinstance(prereq, dict) and isinstance(prereq.get("target_id"), str):
                deps.append(prereq["target_id"])
        return list(dict.fromkeys(deps))

    @staticmethod
    def _detect_cycles(graph: dict[str, list[str]], local_ids: set[str]) -> list[list[str]]:
        indegree = {n: 0 for n in local_ids}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for node, deps in graph.items():
            for dep in deps:
                if dep in local_ids:
                    outgoing[dep].append(node)
                    indegree[node] += 1
        queue = deque(n for n, d in indegree.items() if d == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for nxt in outgoing[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if visited == len(local_ids):
            return []
        return [[n for n, d in indegree.items() if d > 0]]

    def validate(self, package: Path) -> dict[str, Any]:
        root, temp = self._materialize(package)
        try:
            manifest_path = root / "pack.json"
            if not manifest_path.exists():
                raise FoundryError("PACK_MANIFEST_MISSING", "pack.json is required at the Content Pack root.")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise FoundryError("MALFORMED_JSON", "pack.json is not valid JSON.", details={"line": exc.lineno, "column": exc.colno}) from exc
            issues: list[dict[str, Any]] = []
            manifest_report = self.registry.report(manifest, "TianxiaFoundry.ContentPackManifest.v1")
            issues.extend({"code": "MANIFEST_SCHEMA", **e} for e in manifest_report["diagnostics"])
            pack_id = str(manifest.get("pack_id", ""))
            version = str(manifest.get("version", ""))
            package_identity = self._package_identity(package)
            payload, payload_issues = self._physical_payload(root)
            issues.extend(payload_issues)
            declared_files, declared_issues = self._manifest_payload_paths(manifest)
            issues.extend(declared_issues)
            referenced_paths, identity_record_paths, reference_issues = self._semantic_reference_paths(manifest)
            issues.extend(reference_issues)
            actual_paths = set(payload)
            declared_paths = set(declared_files)
            for path in sorted(actual_paths - declared_paths):
                issues.append({"code": "UNDECLARED_PAYLOAD_FILE", "path": path})
            for path in sorted(declared_paths - actual_paths):
                issues.append({"code": "DECLARED_FILE_MISSING", "path": path})
            for path in sorted(referenced_paths - declared_paths):
                issues.append({"code": "SEMANTIC_FILE_NOT_DECLARED", "path": path})
            for rel in sorted(actual_paths & declared_paths):
                item = declared_files[rel]
                raw = payload[rel]
                actual_hash = sha256_bytes(raw)
                if Path(rel).suffix.lower() in EXECUTABLE_SUFFIXES:
                    issues.append({"code": "EXECUTABLE_CONTENT_REJECTED", "path": rel})
                if item.get("sha256") != actual_hash:
                    issues.append({"code": "FILE_HASH_MISMATCH", "path": rel, "declared": item.get("sha256"), "actual": actual_hash})
                if item.get("bytes") != len(raw):
                    issues.append({"code": "FILE_SIZE_MISMATCH", "path": rel, "declared": item.get("bytes"), "actual": len(raw)})
            try:
                payload_identity = compute_payload_identity(
                    pack_id=pack_id,
                    version=version,
                    payload=payload,
                    record_paths=identity_record_paths,
                    manifest=manifest,
                )
            except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                payload_identity = {
                    "schema_version": "TianxiaFoundry.ContentPackPayloadIdentity.v3",
                    "content_hash": None,
                    "payload_files_hash": None,
                    "record_set_hash": None,
                    "manifest_contract_hash": None,
                    "entries": [],
                    "records": [],
                }
                issues.append({"code": "PAYLOAD_IDENTITY_INVALID", "message": str(exc)})
            if manifest.get("content_hash") != payload_identity["content_hash"]:
                issues.append({"code": "CONTENT_HASH_MISMATCH", "declared": manifest.get("content_hash"), "actual": payload_identity["content_hash"]})
            if manifest.get("manifest_contract_hash") != payload_identity["manifest_contract_hash"]:
                issues.append({
                    "code": "MANIFEST_CONTRACT_HASH_MISMATCH",
                    "declared": manifest.get("manifest_contract_hash"),
                    "actual": payload_identity["manifest_contract_hash"],
                })
            record_map: dict[str, dict[str, Any]] = {}
            record_paths: dict[str, str] = {}
            record_ids_folded: dict[str, str] = {}
            for entry in manifest.get("records", []):
                if not isinstance(entry, dict):
                    continue
                rid = entry.get("record_id")
                rel = entry.get("path")
                if not isinstance(rid, str) or not isinstance(rel, str):
                    continue
                folded_id = rid.casefold()
                if rid in record_map:
                    issues.append({"code": "DUPLICATE_STABLE_ID_IN_PACK", "record_id": rid})
                    continue
                if folded_id in record_ids_folded:
                    issues.append({"code": "CASEFOLD_STABLE_ID_COLLISION_IN_PACK", "record_id": rid, "existing": record_ids_folded[folded_id]})
                    continue
                record_ids_folded[folded_id] = rid
                try:
                    safe_rel = normalize_payload_path(rel)
                except (TypeError, ValueError) as exc:
                    issues.append({"code": "RECORD_PATH_UNSAFE", "record_id": rid, "path": rel, "message": str(exc)})
                    continue
                p = root / Path(*PurePosixPath(safe_rel).parts)
                if not p.exists():
                    issues.append({"code": "RECORD_FILE_MISSING", "record_id": rid, "path": safe_rel})
                    continue
                actual_record_file_hash = sha256_file(p)
                if entry.get("sha256") != actual_record_file_hash:
                    issues.append({"code": "RECORD_FILE_HASH_MISMATCH", "record_id": rid, "declared": entry.get("sha256"), "actual": actual_record_file_hash})
                declared_item = declared_files.get(safe_rel)
                if declared_item and declared_item.get("sha256") != actual_record_file_hash:
                    issues.append({"code": "RECORD_DECLARATION_HASH_MISMATCH", "record_id": rid, "record_sha256": entry.get("sha256"), "file_sha256": declared_item.get("sha256")})
                try:
                    record = json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    issues.append({"code": "MALFORMED_RECORD_JSON", "record_id": rid, "path": safe_rel, "line": exc.lineno})
                    continue
                record_map[rid] = record
                record_paths[rid] = safe_rel
                record_report = self.registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
                issues.extend({"code": "RECORD_SCHEMA", "record_id": rid, **e} for e in record_report["diagnostics"])
                if record.get("record_id") != rid:
                    issues.append({"code": "RECORD_ID_MISMATCH", "declared": rid, "actual": record.get("record_id")})
                if record.get("content_type") != entry.get("content_type"):
                    issues.append({
                        "code": "MANIFEST_RECORD_CONTENT_TYPE_MISMATCH",
                        "record_id": rid,
                        "declared": entry.get("content_type"),
                        "actual": record.get("content_type"),
                    })
                if record.get("content_type") not in KNOWN_CONTENT_TYPES:
                    issues.append({"code": "UNKNOWN_CONTENT_TYPE", "record_id": rid, "content_type": record.get("content_type")})
                if record.get("content_binding", {}).get("pack_id") != pack_id or record.get("content_binding", {}).get("pack_version") != version:
                    issues.append({"code": "CONTENT_BINDING_MISMATCH", "record_id": rid})
                if record.get("content_binding", {}).get("pack_hash") != manifest.get("content_hash"):
                    issues.append({"code": "PACK_HASH_BINDING_MISMATCH", "record_id": rid})
                computed_record_hash = sha256_json({k: v for k, v in record.items() if k != "record_hash"})
                if record.get("record_hash") != computed_record_hash:
                    issues.append({"code": "RECORD_HASH_MISMATCH", "record_id": rid, "declared": record.get("record_hash"), "actual": computed_record_hash})
                source = record.get("source", {})
                if record.get("publication", {}).get("status") == "published":
                    if not source.get("source_text") and not source.get("path"):
                        issues.append({"code": "PUBLISHED_SOURCE_MISSING", "record_id": rid})
                    if not record.get("regression_tests"):
                        issues.append({"code": "PUBLISHED_REGRESSION_TEST_MISSING", "record_id": rid})
                issues.extend({"record_id": rid, **e} for e in self._validate_execution(record))
                issues.extend(self._validate_stage2_authority(record))
            authority_scope: dict[str, dict[str, Any]] = {}
            with self.db.connection() as conn:
                for installed in conn.execute("SELECT record_id,data_json FROM catalog_records ORDER BY record_id"):
                    try:
                        authority_scope.setdefault(installed["record_id"], json.loads(installed["data_json"]))
                    except (TypeError, json.JSONDecodeError):
                        continue
            authority_scope.update(record_map)
            issues.extend(self._validate_stage2_authority_relations(authority_scope, set(record_map)))
            source_by_id: dict[str, dict[str, Any]] = {}
            for source_entry in manifest.get("sources", []):
                if not isinstance(source_entry, dict):
                    continue
                source_id = source_entry.get("source_id")
                path = source_entry.get("path")
                if not isinstance(source_id, str) or not isinstance(path, str):
                    continue
                if source_id in source_by_id:
                    issues.append({"code": "DUPLICATE_SOURCE_ID", "source_id": source_id})
                    continue
                source_by_id[source_id] = source_entry
                raw = payload.get(path)
                if raw is not None and source_entry.get("sha256") != sha256_bytes(raw):
                    issues.append({"code": "SOURCE_FILE_HASH_MISMATCH", "source_id": source_id, "path": path})
            for rid, record in record_map.items():
                source = record.get("source") if isinstance(record.get("source"), dict) else {}
                source_id = source.get("source_id")
                declared_source = source_by_id.get(source_id)
                if source.get("source_text"):
                    if source.get("source_hash") != sha256_bytes(str(source["source_text"]).encode("utf-8")):
                        issues.append({"code": "INLINE_SOURCE_HASH_MISMATCH", "record_id": rid, "source_id": source_id})
                elif declared_source is None:
                    issues.append({"code": "RECORD_SOURCE_NOT_DECLARED", "record_id": rid, "source_id": source_id})
                else:
                    if source.get("path") != declared_source.get("path") or source.get("source_hash") != declared_source.get("sha256"):
                        issues.append({
                            "code": "RECORD_SOURCE_BINDING_MISMATCH",
                            "record_id": rid,
                            "source_id": source_id,
                            "expected": {"path": declared_source.get("path"), "source_hash": declared_source.get("sha256")},
                            "actual": {"path": source.get("path"), "source_hash": source.get("source_hash")},
                        })
            if manifest.get("state") == "published":
                not_published = sorted(
                    rid
                    for rid, record in record_map.items()
                    if record.get("publication", {}).get("status") != "published"
                )
                if not_published:
                    issues.append({
                        "code": "PACK_PUBLISHED_WITH_UNPUBLISHED_RECORDS",
                        "record_ids": not_published,
                        "message": "A published Content Pack must contain only published catalog records.",
                    })
            for migration in manifest.get("migrations", []):
                if not isinstance(migration, dict) or not isinstance(migration.get("map_path"), str):
                    continue
                raw = payload.get(migration["map_path"])
                if raw is not None and migration.get("sha256") != sha256_bytes(raw):
                    issues.append({"code": "MIGRATION_FILE_HASH_MISMATCH", "path": migration["map_path"]})
            replacement_rows: list[dict[str, Any]] = []
            replacement_ids: set[str] = set()
            for map_entry in manifest.get("replacement_maps", []):
                if not isinstance(map_entry, dict) or not isinstance(map_entry.get("path"), str):
                    continue
                map_path = map_entry["path"]
                raw = payload.get(map_path)
                if raw is None:
                    continue
                map_hash = sha256_bytes(raw)
                if map_entry.get("sha256") != map_hash:
                    issues.append({"code": "REPLACEMENT_MAP_FILE_HASH_MISMATCH", "path": map_path})
                try:
                    replacement_map = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    issues.append({"code": "REPLACEMENT_MAP_INVALID_JSON", "path": map_path, "message": str(exc)})
                    continue
                issues.extend({"code": "REPLACEMENT_MAP_SCHEMA", "path": map_path, **row} for row in self._schema_errors(self.replacement_validator, replacement_map))
                if replacement_map.get("replacement_pack_id") != pack_id or replacement_map.get("replacement_pack_version") != version:
                    issues.append({"code": "REPLACEMENT_MAP_PACK_BINDING_MISMATCH", "path": map_path})
                for replacement in replacement_map.get("replacements", []):
                    if not isinstance(replacement, dict):
                        continue
                    replacement_id = replacement.get("replacement_id")
                    if not isinstance(replacement_id, str):
                        continue
                    folded_replacement = replacement_id.casefold()
                    if folded_replacement in replacement_ids:
                        issues.append({"code": "DUPLICATE_REPLACEMENT_ID", "replacement_id": replacement_id})
                        continue
                    replacement_ids.add(folded_replacement)
                    target = record_map.get(replacement.get("target_record_id"))
                    if not target or target.get("content_type") != "foundation_expression" or target.get("publication", {}).get("status") != "published":
                        issues.append({"code": "REPLACEMENT_TARGET_NOT_LOCAL_PUBLISHED_FOUNDATION_EXPRESSION", "replacement_id": replacement_id, "target_record_id": replacement.get("target_record_id")})
                        continue
                    source = replacement.get("source") if isinstance(replacement.get("source"), dict) else {}
                    with self.db.connection() as conn:
                        source_row = conn.execute(
                            """SELECT data_json FROM catalog_records WHERE record_id=? AND record_hash=? AND pack_id=? AND pack_version=? LIMIT 1""",
                            (source.get("record_id"), source.get("record_hash"), source.get("pack_id"), source.get("pack_version")),
                        ).fetchone()
                    source_record = json.loads(source_row["data_json"]) if source_row else None
                    if (
                        not source_record
                        or source_record.get("content_type") != "foundation"
                        or source_record.get("content_binding", {}).get("pack_hash") != source.get("pack_hash")
                    ):
                        issues.append({"code": "REPLACEMENT_SOURCE_EXACT_FOUNDATION_NOT_FOUND", "replacement_id": replacement_id, "source": source})
                        continue
                    replacement_rows.append({
                        "replacement_id": replacement_id,
                        "source": source,
                        "target_record_id": target["record_id"],
                        "target_record_hash": target["record_hash"],
                        "mode": replacement.get("mode"),
                        "reason": replacement.get("reason"),
                        "map_path": map_path,
                        "map_hash": map_hash,
                    })
            local_ids = set(record_map)
            graph = {rid: self._record_dependencies(record) for rid, record in record_map.items()}
            available_external: set[str] = set()
            with self.db.connection() as conn:
                for row in conn.execute("SELECT DISTINCT record_id FROM catalog_records"):
                    available_external.add(row[0])
                if pack_id and version:
                    existing = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?", (pack_id, version)).fetchone()
                    if existing and existing[0] != manifest.get("content_hash"):
                        issues.append({"code": "PACK_VERSION_HASH_CONFLICT", "pack_id": pack_id, "version": version, "installed_hash": existing[0], "incoming_hash": manifest.get("content_hash")})
                        locked = conn.execute("SELECT project_id FROM project_content_locks WHERE pack_id=? AND version=? LIMIT 1", (pack_id, version)).fetchone()
                        if locked:
                            issues.append({"code": "PACK_VERSION_IN_USE_OVERWRITE", "pack_id": pack_id, "version": version, "project_id": locked[0]})
                for rid in local_ids:
                    collision = conn.execute(
                        "SELECT pack_id,pack_version FROM catalog_records WHERE record_id=? AND pack_id<>? LIMIT 1",
                        (rid, pack_id),
                    ).fetchone()
                    if collision:
                        issues.append({"code": "STABLE_ID_COLLISION", "record_id": rid, "existing_pack_id": collision[0], "existing_version": collision[1]})
                    folded_collision = conn.execute(
                        "SELECT record_id,pack_id,pack_version FROM catalog_records WHERE lower(record_id)=lower(?) AND record_id<>? LIMIT 1",
                        (rid, rid),
                    ).fetchone()
                    if folded_collision:
                        issues.append({"code": "CASEFOLD_STABLE_ID_COLLISION", "record_id": rid, "existing_record_id": folded_collision[0], "existing_pack_id": folded_collision[1], "existing_version": folded_collision[2]})
            for rid, deps in graph.items():
                for dep in deps:
                    if dep not in local_ids and dep not in available_external:
                        issues.append({"code": "MISSING_REFERENCE", "record_id": rid, "dependency": dep})
            for cycle in self._detect_cycles(graph, local_ids):
                issues.append({"code": "DEPENDENCY_CYCLE", "records": cycle})
            for dependency in manifest.get("dependencies", []):
                if not isinstance(dependency, dict) or dependency.get("optional"):
                    continue
                dep_id = dependency.get("pack_id")
                with self.db.connection() as conn:
                    exists = conn.execute("SELECT 1 FROM content_packs WHERE pack_id=? LIMIT 1", (dep_id,)).fetchone()
                if not exists:
                    issues.append({"code": "PACK_DEPENDENCY_MISSING", "pack_id": dep_id})
            signature = self._signature_report(package.resolve(), manifest, package_identity)
            issues.extend(signature.get("issues") or [])
            if pack_id.upper().startswith("TEST"):
                trust_state = "test_only"
            else:
                trust_state = signature["state"] if signature.get("trusted") else "quarantined"
            authority = self._authority_for(pack_id, trust_state)
            valid = not issues
            return {
                "valid": valid,
                "pack_id": pack_id,
                "version": version,
                "authority": authority,
                "lifecycle_state": manifest.get("state"),
                "content_hash": manifest.get("content_hash"),
                "payload_identity": payload_identity,
                "package_identity": package_identity,
                "signature": signature,
                "trust_state": trust_state,
                "selectable": bool(
                    authority == "published-extension"
                    and manifest.get("state") == "published"
                    and all(record.get("publication", {}).get("status") == "published" for record in record_map.values())
                ),
                "record_count": len(record_map),
                "issues": issues,
                "manifest": manifest,
                "records": record_map,
                "record_paths": record_paths,
                "replacement_rows": replacement_rows,
                "source_root": str(root),
            }
        finally:
            if temp is not None:
                temp.cleanup()

    @staticmethod
    def _exact_trust_binding(validation: dict[str, Any]) -> dict[str, Any]:
        identity = validation["package_identity"]
        payload = validation["payload_identity"]
        return {
            "archive_sha256": identity["archive_sha256"],
            "package_identity_sha256": identity["package_identity_sha256"],
            "package_bytes": identity["package_bytes"],
            "payload_files_hash": payload["payload_files_hash"],
            "record_set_hash": payload["record_set_hash"],
            "manifest_content_hash": validation["manifest"]["content_hash"],
        }

    def issue_exact_trust_challenge(self, package: Path, *, ttl_seconds: int = 300) -> dict[str, Any]:
        package = package.resolve()
        validation = self.validate(package)
        if not validation["valid"]:
            raise FoundryError("PACK_VALIDATION_FAILED", "Content Pack validation failed.", details=validation["issues"])
        if not package.is_file() or package.suffix.casefold() != ".zip":
            raise FoundryError("HUMAN_TRUST_REQUIRES_ZIP", "Exact human trust is available only for immutable ZIP bytes.")
        identity = validation["package_identity"]
        challenge = self.challenges.issue(
            operation="content_pack_exact_trust", subject_type="content_pack_archive",
            subject_id=identity["package_identity_sha256"], exact_bytes=package.read_bytes(),
            binding=self._exact_trust_binding(validation), project_lock_hash=validation["manifest"]["content_hash"],
            ttl_seconds=ttl_seconds,
        )
        return {"validation": {"valid": True, "package_identity": identity}, **challenge}

    def _transition_material(self, conn, pack_id: str, version: str, state: str, superseded_by: str | None) -> tuple[bytes, dict[str, Any], str, Any]:
        row = conn.execute(
            """SELECT p.authority,p.lifecycle_state,p.pack_hash,r.trust_state,r.receipt_hash
               FROM content_packs p LEFT JOIN content_pack_install_receipts r
               ON r.pack_id=p.pack_id AND r.version=p.version
               WHERE p.pack_id=? AND p.version=?""", (pack_id, version),
        ).fetchone()
        if not row:
            raise FoundryError("PACK_NOT_INSTALLED", "The requested Content Pack version is not installed.", status_code=404)
        successor_proof = None
        if state == "superseded":
            successor_version = str(superseded_by or "").strip()
            if not successor_version:
                raise FoundryError("PACK_SUPERSEDED_VERSION_REQUIRED", "A superseded Content Pack must name its replacement version.")
            successor_proof = self._successor_proof(
                conn, pack_id=pack_id, current_version=version, successor_version=successor_version
            )
        transition = {
            "schema_version": "TianxiaFoundry.ContentPackExactTransition.v1",
            "pack_id": pack_id, "version": version, "pack_hash": row["pack_hash"],
            "from_state": row["lifecycle_state"], "to_state": state,
            "superseded_by_version": superseded_by,
            "install_receipt_hash": row["receipt_hash"],
            "successor_proof": successor_proof,
        }
        binding = {"authority": row["authority"], "trust_state": row["trust_state"], **transition}
        return canonical_json(transition).encode("utf-8"), binding, row["receipt_hash"] or row["pack_hash"], row

    def issue_lifecycle_challenge(self, pack_id: str, version: str, state: str, *, superseded_by: str | None = None, ttl_seconds: int = 300) -> dict[str, Any]:
        with self.db.connection() as conn:
            exact, binding, lock_hash, _row = self._transition_material(conn, pack_id, version, state, superseded_by)
        return self.challenges.issue(
            operation=f"content_pack_{state}", subject_type="content_pack_transition",
            subject_id=f"{pack_id}@{version}", exact_bytes=exact, binding=binding,
            project_lock_hash=lock_hash, ttl_seconds=ttl_seconds,
        )

    def install(self, package: Path, *, human_trust: dict[str, Any] | None = None, challenge_id: str | None = None, nonce: str | None = None) -> dict[str, Any]:
        """Install exactly the bytes captured at the start of this call.

        Validation and publication must never re-open a caller-controlled path
        independently.  A private snapshot closes the validate/materialize
        swap window while preserving detached-signature discovery.
        """

        source = package.resolve()
        if not source.exists():
            raise FoundryError("PACK_NOT_FOUND", "The Content Pack package does not exist.", details={"path": str(source)}, status_code=404)
        if source.is_file() and source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise FoundryError("ARCHIVE_TOO_LARGE", "Content Pack archive exceeds the size limit.")
        with tempfile.TemporaryDirectory(prefix="tianxia_pack_snapshot_") as snapshot_temp:
            snapshot_root = Path(snapshot_temp)
            snapshot = snapshot_root / source.name
            if source.is_dir():
                # Preserve links as links so the normal materialization guard
                # rejects them; never follow a directory-pack link while taking
                # the private snapshot.
                shutil.copytree(source, snapshot, symlinks=True)
            else:
                shutil.copyfile(source, snapshot)
                sidecar = source.with_name(source.name + ".sig.json")
                if sidecar.is_file():
                    shutil.copyfile(sidecar, snapshot.with_name(snapshot.name + ".sig.json"))
            return self._install_snapshot(snapshot, human_trust=human_trust, challenge_id=challenge_id, nonce=nonce)

    def _install_snapshot(self, package: Path, *, human_trust: dict[str, Any] | None = None, challenge_id: str | None = None, nonce: str | None = None) -> dict[str, Any]:
        validation = self.validate(package)
        if not validation["valid"]:
            raise FoundryError("PACK_VALIDATION_FAILED", "Content Pack validation failed.", details=validation["issues"])
        human_approval = self._human_trust_report(human_trust, validation["package_identity"])
        human_evidence = None
        human_principal = None
        if human_approval is not None:
            if not package.is_file() or package.suffix.casefold() != ".zip":
                raise FoundryError("HUMAN_TRUST_REQUIRES_ZIP", "Exact human trust is available only for immutable ZIP bytes.")
            if not challenge_id or not nonce:
                raise FoundryError("APPROVAL_CHALLENGE_REQUIRED", "Exact human Content Pack trust requires an explicitly issued one-time challenge.", status_code=409)
            human_principal = self.principal_provider.current_principal()
        root, temp = self._materialize(package)
        try:
            manifest = json.loads((root / "pack.json").read_text(encoding="utf-8"))
            pack_id = manifest["pack_id"]
            version = manifest["version"]
            pack_hash = manifest["content_hash"]
            if pack_id.upper().startswith("TEST"):
                trust_state = "test_only"
            elif validation["signature"].get("trusted"):
                trust_state = "trusted_signed"
            elif human_approval is not None:
                trust_state = "human_trusted_exact_archive"
            else:
                trust_state = "quarantined"
            authority = self._authority_for(pack_id, trust_state)
            lifecycle_state = manifest["state"] if authority != "quarantined" else "quarantined"
            all_records_published = all(
                record.get("publication", {}).get("status") == "published"
                for record in validation["records"].values()
            )
            pack_selectable = bool(
                authority in {"published-extension", "test-only"}
                and manifest["state"] == "published"
                and all_records_published
            )
            package_identity = validation["package_identity"]
            payload_identity = validation["payload_identity"]
            installed_at = utcnow()
            receipt: dict[str, Any] | None = None
            receipt_holder: dict[str, Any] = {}
            # User-controlled identifiers are logical catalog keys, not safe
            # Windows path segments.  Store them under deterministic digest
            # directories so reserved names, trailing characters, and aliases
            # can never collide in the local filesystem.
            target = (
                self.db.settings.packs_dir
                / ("pack-" + sha256_bytes(pack_id.encode("utf-8")))
                / ("version-" + sha256_bytes(version.encode("utf-8")))
                / pack_hash
            )
            staging = target.with_name(target.name + ".staging")
            if target.exists():
                with self.db.connection() as conn:
                    row = conn.execute(
                        """SELECT p.pack_hash,p.lifecycle_state,p.authority,
                                  r.trust_state,r.package_identity_sha256,r.archive_sha256,r.receipt_json,
                                  COALESCE(MAX(c.selected_authority),0) AS any_selected_authority
                           FROM content_packs p LEFT JOIN content_pack_install_receipts r
                           ON r.pack_id=p.pack_id AND r.version=p.version
                           LEFT JOIN catalog_records c
                           ON c.pack_id=p.pack_id AND c.pack_version=p.version
                           WHERE p.pack_id=? AND p.version=?""",
                        (pack_id, version),
                    ).fetchone()
                if row and row["pack_hash"] == pack_hash:
                    if not row["receipt_json"]:
                        raise FoundryError("PACK_INSTALL_RECEIPT_MISSING", "An existing pack version has no immutable trust/identity receipt.")
                    if row["package_identity_sha256"] != package_identity["package_identity_sha256"] or row["archive_sha256"] != package_identity["archive_sha256"]:
                        raise FoundryError("PACK_ARCHIVE_IDENTITY_CONFLICT", "The same pack ID/version/content hash arrived in different package bytes.")
                    with self.db.connection() as conn:
                        verify_pack_seal(conn, pack_id=pack_id, version=version, expected_pack_hash=pack_hash, integrity=self.integrity)
                    existing_receipt = json.loads(row["receipt_json"])
                    return {
                        "installed": True,
                        "idempotent": True,
                        "pack_id": pack_id,
                        "version": version,
                        "pack_hash": pack_hash,
                        "path": str(target),
                        "trust_state": existing_receipt["trust_state"],
                        # Idempotent installs report the immutable installed state.  They must
                        # not recompute selectability from the trust evidence supplied on a
                        # later request (which may intentionally omit the original sidecar or
                        # explicit human approval).
                        "selectable": bool(
                            row["any_selected_authority"]
                            and row["lifecycle_state"] == "published"
                            and (
                                row["authority"] == "test-only"
                                or (
                                    row["authority"] == "published-extension"
                                    and row["trust_state"] in {"trusted_signed", "human_trusted_exact_archive"}
                                )
                            )
                        ),
                        "receipt": existing_receipt,
                    }
            if staging.exists():
                shutil.rmtree(staging)
            staging.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, staging)
            target_preexisted = target.exists()
            moved_target = False
            try:
                def install_body(conn, approval_evidence):
                    nonlocal human_approval, receipt, moved_target
                    if human_approval is not None:
                        if approval_evidence is None or human_principal is None:
                            raise FoundryError("CONTENT_PACK_APPROVAL_EVIDENCE_MISSING", "Exact human trust requires keyed approval evidence.", status_code=409)
                        human_approval = {
                            **human_approval,
                            "presentation_approved_by": human_approval.get("approved_by"),
                            "approved_by": human_principal.display_name,
                            "principal_id": human_principal.principal_id,
                            "principal_hash": human_principal.principal_hash,
                            "challenge_id": challenge_id,
                            "evidence_id": approval_evidence["evidence_id"],
                        }
                    authority_disposition = (
                        "r4_keyed_human_trust" if trust_state == "human_trusted_exact_archive"
                        else "trusted_signature" if trust_state == "trusted_signed"
                        else "test_only" if trust_state == "test_only"
                        else "untrusted_quarantine"
                    )
                    receipt_core = {
                        "schema_version": "TianxiaFoundry.ContentPackInstallReceipt.v1",
                        "pack_id": pack_id,
                        "version": version,
                        "canonical_content_hash": pack_hash,
                        "payload_files_hash": payload_identity["payload_files_hash"],
                        "record_set_hash": payload_identity["record_set_hash"],
                        "archive_sha256": package_identity["archive_sha256"],
                        "package_identity_sha256": package_identity["package_identity_sha256"],
                        "package_bytes": package_identity["package_bytes"],
                        "trust_state": trust_state,
                        "authority": authority,
                        "signer_key_id": validation["signature"].get("key_id"),
                        "signature_sidecar_sha256": validation["signature"].get("sidecar_sha256"),
                        "human_approved_by": human_approval.get("approved_by") if human_approval else None,
                        "human_approval_hash": human_approval.get("approval_hash") if human_approval else None,
                        "human_principal_id": human_approval.get("principal_id") if human_approval else None,
                        "human_principal_hash": human_approval.get("principal_hash") if human_approval else None,
                        "human_challenge_id": human_approval.get("challenge_id") if human_approval else None,
                        "human_evidence_id": human_approval.get("evidence_id") if human_approval else None,
                        "authority_disposition": authority_disposition,
                        "installed_at": installed_at,
                    }
                    receipt = {**receipt_core, "receipt_hash": sha256_json(receipt_core)}
                    install_projection = {
                        "schema_version": "TianxiaFoundry.ContentPackInstallIntegrity.v1",
                        "receipt": receipt,
                        "authority_disposition": authority_disposition,
                        "approval_projection_hash": approval_evidence.get("approval_projection_hash") if approval_evidence else None,
                        "record_membership": [
                            {"record_id": item["record_id"], "path": item["path"], "semantic_sha256": item["semantic_sha256"]}
                            for item in sorted(payload_identity["records"], key=lambda item: (item["record_id"], item["path"]))
                        ],
                    }
                    install_projection_json = canonical_json(install_projection)
                    install_projection_hash = sha256_json(install_projection)
                    install_envelope = self.integrity.sign("tianxia.foundry.content_pack.install.v1", install_projection)
                    receipt_holder.update({"receipt": receipt, "projection_hash": install_projection_hash})
                    existing = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?", (pack_id, version)).fetchone()
                    if existing and existing[0] != pack_hash:
                        raise FoundryError("PACK_VERSION_HASH_CONFLICT", "The same pack ID/version is already installed with different bytes.")
                    if existing:
                        # An exact existing installation was handled before the
                        # transaction.  Reaching this branch means the database
                        # contains legacy/incomplete identity state and must not
                        # be silently rebuilt around immutable HF2 receipts.
                        raise FoundryError(
                            "LEGACY_PACK_INSTALLATION_UNPROVEN",
                            "An existing pack version cannot be upgraded in place without a provable immutable HF2 receipt.",
                            details={"pack_id": pack_id, "version": version, "pack_hash": pack_hash},
                            status_code=409,
                        )
                    conn.execute(
                        "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?,?)",
                        (pack_id, version, pack_hash, lifecycle_state, authority, str(target), canonical_json(manifest), installed_at),
                    )
                    conn.execute(
                        """INSERT INTO content_pack_install_receipts(
                           pack_id,version,canonical_content_hash,payload_files_hash,record_set_hash,
                           archive_sha256,package_identity_sha256,package_bytes,trust_state,signer_key_id,
                           signature_sidecar_sha256,human_approved_by,human_approval_hash,receipt_json,receipt_hash,installed_at,
                           human_principal_id,human_principal_hash,human_challenge_id,human_evidence_id,
                           authority_disposition,install_projection_json,install_projection_hash,
                           integrity_version,integrity_key_id,integrity_domain,integrity_mac)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            pack_id, version, pack_hash, payload_identity["payload_files_hash"], payload_identity["record_set_hash"],
                            package_identity["archive_sha256"], package_identity["package_identity_sha256"], package_identity["package_bytes"],
                            trust_state, validation["signature"].get("key_id"), validation["signature"].get("sidecar_sha256"),
                            human_approval.get("approved_by") if human_approval else None,
                            human_approval.get("approval_hash") if human_approval else None,
                            canonical_json(receipt), receipt["receipt_hash"], installed_at,
                            human_approval.get("principal_id") if human_approval else None,
                            human_approval.get("principal_hash") if human_approval else None,
                            human_approval.get("challenge_id") if human_approval else None,
                            human_approval.get("evidence_id") if human_approval else None,
                            authority_disposition,install_projection_json,install_projection_hash,
                            install_envelope.integrity_version,install_envelope.key_id,install_envelope.domain,install_envelope.mac,
                        ),
                    )
                    identity_by_id = {row["record_id"]: row for row in payload_identity["records"]}
                    for rid, record in sorted(validation["records"].items()):
                        identity = identity_by_id.get(rid)
                        if not identity:
                            raise FoundryError(
                                "PACK_MEMBERSHIP_IDENTITY_MISSING",
                                "The payload identity omitted a catalog record required by the immutable membership seal.",
                                details={"record_id": rid},
                            )
                        record_path = validation["record_paths"][rid]
                        if identity["path"] != record_path:
                            raise FoundryError(
                                "PACK_MEMBERSHIP_PATH_MISMATCH",
                                "The payload identity and validated record path diverge.",
                                details={"record_id": rid, "identity_path": identity["path"], "record_path": record_path},
                            )
                        conn.execute(
                            """INSERT INTO content_pack_record_membership(
                               pack_hash,pack_id,pack_version,record_set_hash,payload_files_hash,install_receipt_hash,
                               record_id,record_hash,record_path,semantic_hash,record_json,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                pack_hash, pack_id, version, payload_identity["record_set_hash"],
                                payload_identity["payload_files_hash"], receipt["receipt_hash"], rid,
                                record["record_hash"], record_path, identity["semantic_sha256"],
                                canonical_json(record), installed_at,
                            ),
                        )
                    install_actor = (
                        human_approval.get("presentation_approved_by") or human_approval.get("approved_by")
                        if human_approval
                        else validation["signature"].get("key_id")
                        or ("system:test-pack-installer" if trust_state == "test_only" else "system:local-pack-installer")
                    )
                    self._append_lifecycle_audit_event(
                        conn,
                        pack_id=pack_id,
                        version=version,
                        pack_hash=pack_hash,
                        from_state=None,
                        to_state=lifecycle_state,
                        transition_kind="pack_installation",
                        actor=install_actor,
                        occurred_at=installed_at,
                        evidence={
                            "install_receipt_hash": receipt["receipt_hash"],
                            "archive_sha256": package_identity["archive_sha256"],
                            "trust_state": trust_state,
                            "authority": authority,
                        },
                        authoritative_principal_id=human_approval.get("principal_id") if human_approval else None,
                        approval_challenge_id=human_approval.get("challenge_id") if human_approval else None,
                        approval_evidence_id=human_approval.get("evidence_id") if human_approval else None,
                    )
                    conn.execute("DELETE FROM catalog_records WHERE pack_id=? AND pack_version=?", (pack_id, version))
                    for rid, record in validation["records"].items():
                        source = record["source"]
                        pub = record["publication"]
                        legality = record["legality"]
                        unresolved = []
                        # Variant selection belongs to the immutable record itself.  Pack
                        # lifecycle and trust decide whether the variant may be offered to a
                        # *new* project; they must never rewrite this metadata because exact
                        # project locks remain reproducible after supersession/retirement.
                        record_selected_authority = int(bool(
                            record.get("compatibility", {}).get("factory", {}).get("selected_authority", True)
                        ))
                        row = conn.execute(
                            """INSERT INTO catalog_records(record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,
                            source_path,source_anchor,source_hash,record_hash,minimum_cl,realm,selected_authority,data_json,unresolved_notes_json,
                            raw_projection_json,canonical_schema_version,contract_status)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                rid,
                                record["content_type"],
                                record["display_name"],
                                pack_id,
                                version,
                                authority,
                                pub.get("status"),
                                source.get("path") or validation["record_paths"][rid],
                                source["anchor"],
                                source["source_hash"],
                                record["record_hash"],
                                legality.get("minimum_cl"),
                                None,
                                record_selected_authority,
                                canonical_json(record),
                                canonical_json(unresolved),
                                None,
                                record["schema_version"],
                                "valid",
                            ),
                        )
                        row_id = row.lastrowid
                        for dep in self._record_dependencies(record):
                            conn.execute("INSERT INTO catalog_dependencies(source_row_id,dependency_record_id,relation) VALUES(?,?,?)", (row_id, dep, "depends_on"))
                        conn.execute(
                            "INSERT INTO canonical_object_validations(object_family,object_key,schema_version,boundary,valid,diagnostics_json,object_hash,validated_at) VALUES(?,?,?,?,?,?,?,?)",
                            ("rules_catalog_record", rid, record["schema_version"], "content_pack_install", 1, "[]", record["record_hash"], utcnow()),
                        )
                    conn.execute("DELETE FROM catalog_record_replacements WHERE replacement_pack_id=? AND replacement_pack_version=?", (pack_id, version))
                    for replacement in validation.get("replacement_rows", []):
                        source = replacement["source"]
                        conn.execute(
                            """INSERT INTO catalog_record_replacements(
                               replacement_id,replacement_pack_id,replacement_pack_version,replacement_pack_hash,
                               source_record_id,source_record_hash,source_pack_id,source_pack_version,source_pack_hash,
                               target_record_id,target_record_hash,mode,reason,map_path,map_hash)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                replacement["replacement_id"], pack_id, version, pack_hash,
                                source["record_id"], source["record_hash"], source["pack_id"], source["pack_version"], source["pack_hash"],
                                replacement["target_record_id"], replacement["target_record_hash"], replacement["mode"], replacement["reason"],
                                replacement["map_path"], replacement["map_hash"],
                            ),
                        )
                    CatalogService._rebuild_fts(conn)
                    if target.exists():
                        shutil.rmtree(target)
                    os.replace(staging, target)
                    moved_target = True
                if human_approval is not None:
                    exact_trust_context = {
                        "schema_version": "TianxiaFoundry.ContentPackExactTrustContext.v1",
                        "exact_trust_binding": self._exact_trust_binding(validation),
                        "manifest_content_hash": validation["manifest"]["content_hash"],
                    }
                    human_evidence, _ = self.challenges.consume_with_action(
                        challenge_id=challenge_id,
                        nonce=nonce,
                        operation="content_pack_exact_trust",
                        subject_type="content_pack_archive",
                        subject_id=validation["package_identity"]["package_identity_sha256"],
                        exact_bytes=package.read_bytes(),
                        binding=self._exact_trust_binding(validation),
                        project_lock_hash=validation["manifest"]["content_hash"],
                        evidence_context=exact_trust_context,
                        action=install_body,
                    )
                else:
                    with self.db.transaction() as conn:
                        install_body(conn, None)
                receipt = receipt_holder["receipt"]
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                if moved_target and not target_preexisted and target.exists():
                    shutil.rmtree(target)
                raise
            return {
                "installed": True,
                "idempotent": False,
                "pack_id": pack_id,
                "version": version,
                "pack_hash": pack_hash,
                "path": str(target),
                "record_count": validation["record_count"],
                "trust_state": trust_state,
                "selectable": pack_selectable,
                "receipt": receipt,
            }
        finally:
            if temp is not None:
                temp.cleanup()

    def validate_installed_records(self) -> dict[str, Any]:
        total = valid = invalid = 0
        diagnostics: list[dict[str, Any]] = []
        with self.db.connection() as conn:
            for row in conn.execute("SELECT record_id,pack_id,pack_version,data_json FROM catalog_records WHERE pack_id<>? ORDER BY pack_id,pack_version,record_id", ("tianxia.core.factory.hf05zvk.r1h.phase2i.hf2",)):
                total += 1
                record = json.loads(row["data_json"])
                report = self.registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
                if report["valid"]:
                    valid += 1
                else:
                    invalid += 1
                    diagnostics.append({"record_id": row["record_id"], "pack_id": row["pack_id"], "version": row["pack_version"], "diagnostics": report["diagnostics"]})
        return {"total": total, "valid": valid, "invalid": invalid, "diagnostics": diagnostics}

    def list(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM catalog_records r WHERE r.pack_id=p.pack_id AND r.pack_version=p.version) AS record_count,
                   (SELECT COUNT(*) FROM catalog_records r WHERE r.pack_id=p.pack_id AND r.pack_version=p.version AND r.publication_state<>'published') AS nonpublished_record_count,
                   (SELECT COUNT(*) FROM project_content_locks l WHERE l.pack_id=p.pack_id AND l.version=p.version) AS dependent_projects
                   FROM content_packs p ORDER BY p.pack_id,p.version"""
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["manifest"] = json.loads(item.pop("manifest_json"))
                receipt = conn.execute(
                    "SELECT receipt_json FROM content_pack_install_receipts WHERE pack_id=? AND version=?",
                    (item["pack_id"], item["version"]),
                ).fetchone()
                item["install_receipt"] = json.loads(receipt[0]) if receipt else None
                item["trust_state"] = (
                    item["install_receipt"].get("trust_state")
                    if item["install_receipt"]
                    else ("canonical" if item["authority"] == "canonical" else "unverified")
                )
                item["selectable"] = bool(
                    item["lifecycle_state"] == "published"
                    and item["nonpublished_record_count"] == 0
                    and (
                        item["authority"] in {"canonical", "test-only"}
                        or (
                            item["authority"] == "published-extension"
                            and item["trust_state"] in {"trusted_signed", "human_trusted_exact_archive"}
                        )
                    )
                )
                result.append(item)
            return result

    def inspect(self, pack_id: str, version: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM content_packs WHERE pack_id=? AND version=?", (pack_id, version)).fetchone()
            if not row:
                raise FoundryError("PACK_NOT_INSTALLED", "The requested Content Pack version is not installed.", status_code=404)
            records = [dict(r) for r in conn.execute("SELECT record_id,content_type,display_name,record_hash,publication_state FROM catalog_records WHERE pack_id=? AND pack_version=? ORDER BY display_name", (pack_id, version))]
            dependents = [dict(r) for r in conn.execute("SELECT project_id FROM project_content_locks WHERE pack_id=? AND version=?", (pack_id, version))]
            self._verify_lifecycle_history(conn, pack_id, version)
            data = dict(row)
            data["manifest"] = json.loads(data.pop("manifest_json"))
            receipt = conn.execute(
                "SELECT receipt_json FROM content_pack_install_receipts WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
            data["install_receipt"] = json.loads(receipt[0]) if receipt else None
            data["lifecycle_events"] = [
                {
                    **dict(event),
                    "evidence": json.loads(event["evidence_json"]),
                }
                for event in conn.execute(
                    """SELECT sequence_no,event_id,from_state,to_state,superseded_by_version,
                              transition_kind,evidence_json,evidence_hash,occurred_at
                       FROM content_pack_lifecycle_audit_events
                       WHERE pack_id=? AND version=? ORDER BY sequence_no""",
                    (pack_id, version),
                )
            ]
            for event in data["lifecycle_events"]:
                event.pop("evidence_json", None)
            data["records"] = records
            data["dependent_projects"] = dependents
            return data

    def set_state(
        self,
        pack_id: str,
        version: str,
        state: str,
        *,
        actor: str | None,
        superseded_by: str | None = None,
        challenge_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        if state not in {"draft", "validated", "published", "superseded", "retired"}:
            raise FoundryError("PACK_STATE_INVALID", "Unsupported Content Pack lifecycle state.")
        lifecycle_actor = self._named_lifecycle_actor(actor)
        if not challenge_id or not nonce:
            raise FoundryError(
                "APPROVAL_CHALLENGE_REQUIRED",
                "Content Pack lifecycle changes require an explicitly issued one-time exact-byte challenge.",
                status_code=409,
            )
        principal = self.principal_provider.current_principal()
        with self.db.connection() as conn:
            self._verify_lifecycle_history(conn, pack_id, version)
            exact_bytes, transition_binding, transition_lock_hash, initial_row = self._transition_material(
                conn, pack_id, version, state, superseded_by
            )
            verify_pack_seal(
                conn, pack_id=pack_id, version=version, expected_pack_hash=initial_row["pack_hash"], integrity=self.integrity
            )
        evidence_context = {
            "schema_version": "TianxiaFoundry.ContentPackLifecycleApprovalContext.v1",
            "transition_binding": transition_binding,
            "transition_lock_hash": transition_lock_hash,
        }

        def protected_transition(conn, approval_evidence):
            self._verify_lifecycle_history(conn, pack_id, version)
            row = conn.execute(
                """SELECT p.authority,p.lifecycle_state,p.pack_hash,r.trust_state FROM content_packs p
                   LEFT JOIN content_pack_install_receipts r ON r.pack_id=p.pack_id AND r.version=p.version
                   WHERE p.pack_id=? AND p.version=?""",
                (pack_id, version),
            ).fetchone()
            if not row:
                raise FoundryError("PACK_NOT_INSTALLED", "The requested Content Pack version is not installed.", status_code=404)
            verify_pack_seal(
                conn, pack_id=pack_id, version=version, expected_pack_hash=row["pack_hash"], integrity=self.integrity
            )
            current_exact, current_binding, current_lock, transition_row = self._transition_material(
                conn, pack_id, version, state, superseded_by
            )
            if current_exact != exact_bytes or current_binding != transition_binding or current_lock != transition_lock_hash:
                raise FoundryError(
                    "PACK_TRANSITION_BINDING_CHANGED",
                    "The Content Pack transition basis changed before atomic approval.",
                    status_code=409,
                )
            if state == "published" and row["authority"] == "test-only":
                pass
            elif state == "published" and row["trust_state"] not in {"trusted_signed", "human_trusted_exact_archive"}:
                raise FoundryError(
                    "PACK_TRUST_REQUIRED",
                    "Unsigned or untrusted Content Packs remain quarantined and cannot become selectable published extensions.",
                    details={"pack_id": pack_id, "version": version, "trust_state": row["trust_state"] or "missing_receipt"},
                )
            current_state = row["lifecycle_state"]
            allowed = LIFECYCLE_TRANSITIONS.get(current_state, {current_state})
            if state not in allowed:
                raise FoundryError(
                    "PACK_LIFECYCLE_TRANSITION_INVALID",
                    "Content Pack lifecycle transitions are monotonic and cannot reactivate or move backward.",
                    details={"pack_id": pack_id, "version": version, "from_state": current_state, "to_state": state, "allowed": sorted(allowed)},
                )
            if state == "superseded" and not str(superseded_by or "").strip():
                raise FoundryError("PACK_SUPERSEDED_VERSION_REQUIRED", "A superseded Content Pack must name its replacement version.")
            if state != "superseded" and superseded_by is not None:
                raise FoundryError("PACK_SUPERSEDED_VERSION_UNEXPECTED", "superseded_by is valid only for a superseded transition.")
            successor_proof = (
                self._successor_proof(
                    conn, pack_id=pack_id, current_version=version, successor_version=str(superseded_by).strip()
                )
                if state == "superseded" and state != current_state
                else None
            )
            records = conn.execute(
                "SELECT row_id,record_id,record_hash,data_json FROM catalog_records WHERE pack_id=? AND pack_version=?",
                (pack_id, version),
            ).fetchall()
            if state == "published":
                not_ready = [
                    rec["record_id"] for rec in records
                    if json.loads(rec["data_json"]).get("publication", {}).get("status") != "published"
                ]
                if not_ready:
                    raise FoundryError(
                        "PACK_RECORDS_NOT_RELEASE_READY",
                        "Publishing cannot mutate immutable record bytes; release-ready records must already declare published status.",
                        details={"record_ids": not_ready},
                    )
            before = {rec["row_id"]: (rec["record_hash"], rec["data_json"]) for rec in records}
            if state != current_state:
                occurred_at = utcnow()
                conn.execute(
                    """UPDATE content_packs
                       SET lifecycle_state=?,
                           superseded_by_version=COALESCE(?,superseded_by_version),
                           retired_at=CASE WHEN ?='retired' THEN COALESCE(retired_at,?) ELSE retired_at END
                       WHERE pack_id=? AND version=?""",
                    (state, superseded_by, state, occurred_at, pack_id, version),
                )
                self._append_lifecycle_audit_event(
                    conn, pack_id=pack_id, version=version, pack_hash=row["pack_hash"],
                    from_state=current_state, to_state=state, superseded_by_version=superseded_by,
                    transition_kind="human_local_lifecycle_action", actor=lifecycle_actor, occurred_at=occurred_at,
                    evidence={"successor_proof": successor_proof} if successor_proof else None,
                    authoritative_principal_id=principal.principal_id, approval_challenge_id=challenge_id,
                    approval_evidence_id=approval_evidence["evidence_id"],
                )
            after = {
                rec["row_id"]: (rec["record_hash"], rec["data_json"])
                for rec in conn.execute(
                    "SELECT row_id,record_hash,data_json FROM catalog_records WHERE pack_id=? AND pack_version=?",
                    (pack_id, version),
                )
            }
            if before != after:
                raise FoundryError("PACK_IMMUTABLE_RECORD_MUTATION", "A lifecycle transition attempted to alter immutable record bytes or hashes.")
            CatalogService._rebuild_fts(conn)
            return {"changed": state != current_state}

        self.challenges.consume_with_action(
            challenge_id=challenge_id, nonce=nonce, operation=f"content_pack_{state}",
            subject_type="content_pack_transition", subject_id=f"{pack_id}@{version}", exact_bytes=exact_bytes,
            binding=transition_binding, project_lock_hash=transition_lock_hash, evidence_context=evidence_context,
            action=protected_transition,
        )
        return self.inspect(pack_id, version)

    def uninstall(self, pack_id: str, version: str, *, actor: str | None, challenge_id: str | None = None, nonce: str | None = None) -> dict[str, Any]:
        lifecycle_actor = self._named_lifecycle_actor(actor)
        if not challenge_id or not nonce:
            raise FoundryError(
                "APPROVAL_CHALLENGE_REQUIRED",
                "Content Pack uninstall requires an explicitly issued one-time exact-byte challenge.",
                status_code=409,
            )
        principal = self.principal_provider.current_principal()
        with self.db.connection() as conn:
            self._verify_lifecycle_history(conn, pack_id, version)
            exact_bytes, transition_binding, transition_lock_hash, initial_row = self._transition_material(
                conn, pack_id, version, "uninstalled", None
            )
            verify_pack_seal(
                conn, pack_id=pack_id, version=version, expected_pack_hash=initial_row["pack_hash"], integrity=self.integrity
            )
        evidence_context = {
            "schema_version": "TianxiaFoundry.ContentPackLifecycleApprovalContext.v1",
            "transition_binding": transition_binding,
            "transition_lock_hash": transition_lock_hash,
        }
        result_holder: dict[str, Any] = {}

        def protected_uninstall(conn, approval_evidence):
            self._verify_lifecycle_history(conn, pack_id, version)
            row = conn.execute(
                "SELECT installed_path,pack_hash,lifecycle_state FROM content_packs WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
            if not row:
                raise FoundryError("PACK_NOT_INSTALLED", "The requested Content Pack version is not installed.", status_code=404)
            verify_pack_seal(
                conn, pack_id=pack_id, version=version, expected_pack_hash=row["pack_hash"], integrity=self.integrity
            )
            current_exact, current_binding, current_lock, _ = self._transition_material(conn, pack_id, version, "uninstalled", None)
            if current_exact != exact_bytes or current_binding != transition_binding or current_lock != transition_lock_hash:
                raise FoundryError("PACK_TRANSITION_BINDING_CHANGED", "The Content Pack uninstall basis changed before atomic approval.", status_code=409)
            dependent = conn.execute(
                "SELECT project_id FROM project_content_locks WHERE pack_id=? AND version=? LIMIT 1", (pack_id, version)
            ).fetchone()
            if dependent:
                raise FoundryError("PACK_IN_USE", "A locked project depends on this Content Pack version.", details={"project_id": dependent[0]})
            installed_path = Path(row["installed_path"]) if row["installed_path"] else None
            uninstalled_at = utcnow()
            self._append_lifecycle_audit_event(
                conn, pack_id=pack_id, version=version, pack_hash=row["pack_hash"],
                from_state=row["lifecycle_state"], to_state="uninstalled", transition_kind="human_local_uninstall",
                actor=lifecycle_actor, occurred_at=uninstalled_at, authoritative_principal_id=principal.principal_id,
                approval_challenge_id=challenge_id, approval_evidence_id=approval_evidence["evidence_id"],
            )
            receipt = conn.execute(
                "SELECT receipt_hash,receipt_json FROM content_pack_install_receipts WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
            if not receipt:
                raise FoundryError(
                    "LEGACY_PACK_INSTALLATION_UNPROVEN",
                    "A pack without an immutable keyed HF2 receipt cannot use the HF2 uninstall path.",
                    details={"pack_id": pack_id, "version": version}, status_code=409,
                )
            conn.execute(
                """INSERT INTO uninstalled_content_pack_receipts(
                   pack_id,version,pack_hash,receipt_hash,receipt_json,uninstalled_at)
                   VALUES(?,?,?,?,?,?)""",
                (pack_id, version, row["pack_hash"], receipt["receipt_hash"], receipt["receipt_json"], uninstalled_at),
            )
            conn.execute(
                """INSERT INTO uninstalled_content_pack_record_membership(
                   pack_hash,record_id,record_hash,record_json,receipt_hash,uninstalled_at)
                   SELECT pack_hash,record_id,record_hash,record_json,install_receipt_hash,?
                   FROM content_pack_record_membership WHERE pack_hash=?""",
                (uninstalled_at, row["pack_hash"]),
            )
            conn.execute("DELETE FROM content_pack_record_membership WHERE pack_hash=?", (row["pack_hash"],))
            conn.execute("DELETE FROM content_pack_install_receipts WHERE pack_id=? AND version=?", (pack_id, version))
            conn.execute("DELETE FROM content_packs WHERE pack_id=? AND version=?", (pack_id, version))
            CatalogService._rebuild_fts(conn)
            result_holder["installed_path"] = installed_path
            return {"uninstalled": True}

        self.challenges.consume_with_action(
            challenge_id=challenge_id, nonce=nonce, operation="content_pack_uninstalled",
            subject_type="content_pack_transition", subject_id=f"{pack_id}@{version}", exact_bytes=exact_bytes,
            binding=transition_binding, project_lock_hash=transition_lock_hash, evidence_context=evidence_context,
            action=protected_uninstall,
        )
        installed_path = result_holder.get("installed_path")
        if installed_path and installed_path.exists() and self.db.settings.packs_dir in installed_path.parents:
            shutil.rmtree(installed_path)
        return {"uninstalled": True, "pack_id": pack_id, "version": version}

    def preview_migration(self, project_id: str, pack_id: str, target_version: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            current = conn.execute("SELECT version,pack_hash FROM project_content_locks WHERE project_id=? AND pack_id=?", (project_id, pack_id)).fetchone()
            if not current:
                raise FoundryError("PROJECT_PACK_NOT_LOCKED", "The project is not locked to that Content Pack.")
            target = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?", (pack_id, target_version)).fetchone()
            if not target:
                raise FoundryError("TARGET_PACK_NOT_INSTALLED", "The target Content Pack version is not installed.")
            old_records = {r["record_id"]: r["record_hash"] for r in conn.execute("SELECT record_id,record_hash FROM catalog_records WHERE pack_id=? AND pack_version=?", (pack_id, current[0]))}
            new_records = {r["record_id"]: r["record_hash"] for r in conn.execute("SELECT record_id,record_hash FROM catalog_records WHERE pack_id=? AND pack_version=?", (pack_id, target_version))}
            referenced = {r[0] for r in conn.execute("SELECT record_id FROM project_locked_records WHERE project_id=? AND pack_id=?", (project_id, pack_id))}
            added = sorted(set(new_records) - set(old_records))
            removed = sorted(set(old_records) - set(new_records))
            changed = sorted(rid for rid in set(old_records) & set(new_records) if old_records[rid] != new_records[rid])
            affected = sorted(referenced & set(removed + changed))
            return {
                "applied": False,
                "project_id": project_id,
                "pack_id": pack_id,
                "from_version": current[0],
                "to_version": target_version,
                "from_hash": current[1],
                "to_hash": target[0],
                "added": added,
                "removed": removed,
                "changed": changed,
                "affected_referenced_records": affected,
                "blockers": [f"Referenced record changed or removed: {rid}" for rid in affected],
            }
