from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from app.core import FoundryError, canonical_json, sha256_json, utcnow
from security.integrity import IntegrityService
from content_packs.identity import normalized_record_bytes
from contracts.canonical import canonical_record_hash


@dataclass(frozen=True)
class PackSeal:
    pack_id: str
    version: str
    pack_hash: str
    record_set_hash: str
    payload_files_hash: str
    install_receipt_hash: str
    membership_snapshot_hash: str
    records: tuple[dict[str, Any], ...]

    def lock_row(self) -> dict[str, str]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "pack_hash": self.pack_hash,
            "record_set_hash": self.record_set_hash,
            "payload_files_hash": self.payload_files_hash,
            "install_receipt_hash": self.install_receipt_hash,
            "membership_snapshot_hash": self.membership_snapshot_hash,
        }


def semantic_hash(record: dict[str, Any]) -> str:
    raw = canonical_json(record).encode("utf-8")
    _normalized, _record_id, digest = normalized_record_bytes(raw)
    return digest


def canonical_membership_rows(
    records: Iterable[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str, str]:
    """Return immutable membership rows and deterministic record/payload hashes.

    This helper is used for canonical core and explicitly isolated TEST-only
    authorities that are installed directly by test/catalog tooling rather than
    through a portable Content Pack archive.  Portable Content Packs retain the
    exact hashes computed by ``compute_payload_identity``.
    """
    rows: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    record_set: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, record in sorted(records, key=lambda item: (item[1]["record_id"], item[0])):
        rid = record["record_id"]
        if rid in seen:
            raise FoundryError(
                "PACK_MEMBERSHIP_DUPLICATE_RECORD_ID",
                "A sealed pack membership may contain only one exact record per stable ID.",
                details={"record_id": rid},
            )
        seen.add(rid)
        body = json.loads(canonical_json(record))
        expected_hash = canonical_record_hash(body)
        if body.get("record_hash") != expected_hash:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_HASH_INVALID",
                "A record cannot enter immutable membership with a mismatched canonical hash.",
                details={"record_id": rid, "stored": body.get("record_hash"), "expected": expected_hash},
            )
        sem = semantic_hash(body)
        semantic_bytes, _, _ = normalized_record_bytes(canonical_json(body).encode("utf-8"))
        row = {
            "record_id": rid,
            "record_hash": body["record_hash"],
            "record_path": path,
            "semantic_hash": sem,
            "record_json": canonical_json(body),
        }
        rows.append(row)
        entries.append({
            "path": path,
            "kind": "rules_catalog_record",
            "semantic_bytes": len(semantic_bytes),
            "semantic_sha256": sem,
        })
        record_set.append({"record_id": rid, "path": path, "semantic_sha256": sem})
    return rows, sha256_json(entries), sha256_json(record_set)


def create_direct_install_receipt(
    conn: sqlite3.Connection,
    *,
    pack_id: str,
    version: str,
    pack_hash: str,
    authority: str,
    trust_state: str,
    records: Iterable[tuple[str, dict[str, Any]]],
    installed_at: str | None = None,
    integrity: IntegrityService,
) -> PackSeal:
    """Seal a canonical-core or TEST-only direct installation.

    This is not a compatibility bypass: it creates the same immutable receipt
    and member relation required of archive-installed packs before any project
    may lock the authority.
    """
    created_at = installed_at or utcnow()
    rows, payload_files_hash, record_set_hash = canonical_membership_rows(records)
    receipt_core = {
        "schema_version": "TianxiaFoundry.ContentPackInstallReceipt.v1",
        "pack_id": pack_id,
        "version": version,
        "canonical_content_hash": pack_hash,
        "payload_files_hash": payload_files_hash,
        "record_set_hash": record_set_hash,
        "archive_sha256": None,
        "package_identity_sha256": sha256_json({
            "mode": "direct_sealed_authority",
            "pack_id": pack_id,
            "version": version,
            "pack_hash": pack_hash,
            "payload_files_hash": payload_files_hash,
            "record_set_hash": record_set_hash,
        }),
        "package_bytes": sum(len(row["record_json"].encode("utf-8")) for row in rows),
        "trust_state": trust_state,
        "authority": authority,
        "signer_key_id": None,
        "signature_sidecar_sha256": None,
        "human_approved_by": None,
        "human_approval_hash": None,
        "human_principal_id": None,
        "human_principal_hash": None,
        "human_challenge_id": None,
        "human_evidence_id": None,
        "authority_disposition": "canonical_direct" if authority == "canonical" else "test_only",
        "installed_at": created_at,
    }
    receipt = {**receipt_core, "receipt_hash": sha256_json(receipt_core)}
    install_projection = {
        "schema_version": "TianxiaFoundry.ContentPackInstallIntegrity.v1",
        "receipt": receipt,
        "authority_disposition": receipt_core["authority_disposition"],
        "approval_projection_hash": None,
        "record_membership": [
            {"record_id": row["record_id"], "path": row["record_path"], "semantic_sha256": row["semantic_hash"]}
            for row in rows
        ],
    }
    install_projection_json = canonical_json(install_projection)
    install_projection_hash = sha256_json(install_projection)
    envelope = integrity.sign("tianxia.foundry.content_pack.install.v1", install_projection)
    conn.execute(
        """INSERT INTO content_pack_install_receipts(
           pack_id,version,canonical_content_hash,payload_files_hash,record_set_hash,
           archive_sha256,package_identity_sha256,package_bytes,trust_state,signer_key_id,
           signature_sidecar_sha256,human_approved_by,human_approval_hash,receipt_json,
           receipt_hash,installed_at,authority_disposition,install_projection_json,install_projection_hash,
           integrity_version,integrity_key_id,integrity_domain,integrity_mac)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pack_id, version, pack_hash, payload_files_hash, record_set_hash,
            None, receipt_core["package_identity_sha256"], receipt_core["package_bytes"],
            trust_state, None, None, None, None, canonical_json(receipt), receipt["receipt_hash"], created_at,
            receipt_core["authority_disposition"],install_projection_json,install_projection_hash,
            envelope.integrity_version,envelope.key_id,envelope.domain,envelope.mac,
        ),
    )
    for row in rows:
        conn.execute(
            """INSERT INTO content_pack_record_membership(
               pack_hash,pack_id,pack_version,record_set_hash,payload_files_hash,install_receipt_hash,
               record_id,record_hash,record_path,semantic_hash,record_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pack_hash, pack_id, version, record_set_hash, payload_files_hash, receipt["receipt_hash"],
                row["record_id"], row["record_hash"], row["record_path"], row["semantic_hash"],
                row["record_json"], created_at,
            ),
        )
    return verify_pack_seal(conn, pack_id=pack_id, version=version, expected_pack_hash=pack_hash, integrity=integrity)


def _receipt_core(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "receipt_hash"}


def verify_pack_seal(
    conn: sqlite3.Connection,
    *,
    pack_id: str,
    version: str,
    expected_pack_hash: str | None = None,
    integrity: IntegrityService,
) -> PackSeal:
    pack = conn.execute(
        "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
        (pack_id, version),
    ).fetchone()
    if not pack:
        raise FoundryError(
            "PACK_LOCK_NOT_INSTALLED",
            "A requested Content Pack version is not installed.",
            details={"pack_id": pack_id, "version": version},
        )
    pack_hash = pack["pack_hash"]
    if expected_pack_hash is not None and pack_hash != expected_pack_hash:
        raise FoundryError(
            "PACK_LOCK_HASH_MISMATCH",
            "The installed Content Pack bytes differ from the requested exact lock.",
            details={"pack_id": pack_id, "version": version, "expected": expected_pack_hash, "actual": pack_hash},
        )
    receipt_row = conn.execute(
        "SELECT * FROM content_pack_install_receipts WHERE pack_id=? AND version=?",
        (pack_id, version),
    ).fetchone()
    if not receipt_row:
        raise FoundryError(
            "LEGACY_PROJECT_LOCK_MEMBERSHIP_UNPROVEN",
            "The installed pack has no immutable HF2 install receipt and cannot be used for a new or writable project lock.",
            details={"pack_id": pack_id, "version": version, "pack_hash": pack_hash},
            status_code=409,
        )
    if receipt_row["canonical_content_hash"] != pack_hash:
        raise FoundryError(
            "PACK_INSTALL_RECEIPT_HASH_MISMATCH",
            "The immutable install receipt is not bound to the installed pack hash.",
            details={"pack_id": pack_id, "version": version},
        )
    try:
        receipt = json.loads(receipt_row["receipt_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise FoundryError(
            "PACK_INSTALL_RECEIPT_INVALID",
            "The immutable install receipt cannot be parsed.",
            details={"pack_id": pack_id, "version": version},
        ) from exc
    expected_receipt_hash = sha256_json(_receipt_core(receipt))
    if receipt.get("receipt_hash") != expected_receipt_hash or receipt_row["receipt_hash"] != expected_receipt_hash:
        raise FoundryError(
            "PACK_INSTALL_RECEIPT_INTEGRITY_MISMATCH",
            "The immutable install receipt hash does not match its exact canonical bytes.",
            details={"pack_id": pack_id, "version": version},
        )
    exact_fields = {
        "pack_id": pack_id,
        "version": version,
        "canonical_content_hash": pack_hash,
        "payload_files_hash": receipt_row["payload_files_hash"],
        "record_set_hash": receipt_row["record_set_hash"],
    }
    mismatched = {
        key: {"receipt": receipt.get(key), "column": value}
        for key, value in exact_fields.items()
        if receipt.get(key) != value
    }
    if mismatched:
        raise FoundryError(
            "PACK_INSTALL_RECEIPT_INTEGRITY_MISMATCH",
            "The immutable install receipt columns and canonical document diverge.",
            details={"pack_id": pack_id, "version": version, "mismatched": mismatched},
        )
    required_integrity = {
        "authority_disposition": receipt_row["authority_disposition"],
        "install_projection_json": receipt_row["install_projection_json"],
        "install_projection_hash": receipt_row["install_projection_hash"],
        "integrity_version": receipt_row["integrity_version"],
        "integrity_key_id": receipt_row["integrity_key_id"],
        "integrity_domain": receipt_row["integrity_domain"],
        "integrity_mac": receipt_row["integrity_mac"],
    }
    missing_r4 = sorted(key for key, value in required_integrity.items() if not value or str(value) == "legacy_unproven")
    if missing_r4:
        raise FoundryError(
            "LEGACY_TRUST_UNPROVEN",
            "The Content Pack receipt lacks an R4 external keyed trust anchor.",
            details={"pack_id": pack_id, "version": version, "missing": missing_r4}, status_code=409,
        )
    try:
        install_projection = json.loads(receipt_row["install_projection_json"])
    except Exception as exc:
        raise FoundryError("PACK_INSTALL_INTEGRITY_PROJECTION_INVALID", "The keyed install projection is malformed.", status_code=409) from exc
    if canonical_json(install_projection) != receipt_row["install_projection_json"] or sha256_json(install_projection) != receipt_row["install_projection_hash"]:
        raise FoundryError("PACK_INSTALL_INTEGRITY_PROJECTION_INVALID", "The keyed install projection canonical bytes are invalid.", status_code=409)
    integrity.verify(
        "tianxia.foundry.content_pack.install.v1",
        install_projection,
        {
            "integrity_version": receipt_row["integrity_version"], "algorithm": "HMAC-SHA-256",
            "key_id": receipt_row["integrity_key_id"], "domain": receipt_row["integrity_domain"],
            "projection_hash": receipt_row["install_projection_hash"], "mac": receipt_row["integrity_mac"],
        },
    )
    if install_projection.get("receipt") != receipt or install_projection.get("authority_disposition") != receipt_row["authority_disposition"]:
        raise FoundryError("PACK_INSTALL_INTEGRITY_PROJECTION_MISMATCH", "The keyed install projection differs from the exact receipt.", status_code=409)
    if receipt_row["trust_state"] == "human_trusted_exact_archive":
        if receipt_row["authority_disposition"] != "r4_keyed_human_trust" or not receipt_row["human_evidence_id"]:
            raise FoundryError("LEGACY_TRUST_UNPROVEN", "Exact human trust lacks an R4 keyed approval disposition.", status_code=409)
        evidence = conn.execute("SELECT * FROM exact_approval_evidence WHERE evidence_id=?", (receipt_row["human_evidence_id"],)).fetchone()
        if not evidence or evidence["operation"] != "content_pack_exact_trust" or evidence["subject_id"] != receipt_row["package_identity_sha256"]:
            raise FoundryError("PACK_HUMAN_TRUST_EVIDENCE_INVALID", "The exact human trust evidence is missing or bound to another archive.", status_code=409)
        try:
            approval_projection = json.loads(evidence["approval_projection_json"])
        except Exception as exc:
            raise FoundryError("PACK_HUMAN_TRUST_EVIDENCE_INVALID", "The human trust approval projection is malformed.", status_code=409) from exc
        integrity.verify(
            "tianxia.foundry.approval_evidence.v2",
            approval_projection,
            {
                "integrity_version": evidence["integrity_version"], "algorithm": "HMAC-SHA-256",
                "key_id": evidence["integrity_key_id"], "domain": evidence["integrity_domain"],
                "projection_hash": evidence["approval_projection_hash"], "mac": evidence["integrity_mac"],
            },
        )
        if install_projection.get("approval_projection_hash") != evidence["approval_projection_hash"]:
            raise FoundryError("PACK_HUMAN_TRUST_EVIDENCE_INVALID", "The install receipt is not bound to the exact keyed human approval.", status_code=409)

    members = [
        dict(row)
        for row in conn.execute(
            """SELECT record_id,record_hash,record_path,semantic_hash,record_json,
                      record_set_hash,payload_files_hash,install_receipt_hash,pack_id,pack_version,pack_hash
               FROM content_pack_record_membership WHERE pack_hash=? ORDER BY record_id,record_path""",
            (pack_hash,),
        )
    ]
    if not members:
        raise FoundryError(
            "LEGACY_PROJECT_LOCK_MEMBERSHIP_UNPROVEN",
            "The installed pack has no immutable HF2 record membership.",
            details={"pack_id": pack_id, "version": version, "pack_hash": pack_hash},
            status_code=409,
        )
    record_set: list[dict[str, str]] = []
    snapshot: list[dict[str, str]] = []
    for member in members:
        if (
            member["pack_id"] != pack_id
            or member["pack_version"] != version
            or member["pack_hash"] != pack_hash
            or member["record_set_hash"] != receipt_row["record_set_hash"]
            or member["payload_files_hash"] != receipt_row["payload_files_hash"]
            or member["install_receipt_hash"] != expected_receipt_hash
        ):
            raise FoundryError(
                "PACK_MEMBERSHIP_BINDING_MISMATCH",
                "An immutable membership row is not bound to the exact pack receipt.",
                details={"pack_id": pack_id, "version": version, "record_id": member["record_id"]},
            )
        try:
            record = json.loads(member["record_json"])
        except json.JSONDecodeError as exc:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_INVALID",
                "An immutable membership record cannot be parsed.",
                details={"record_id": member["record_id"]},
            ) from exc
        if canonical_json(record) != member["record_json"]:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_NONCANONICAL",
                "An immutable membership record is not stored in canonical JSON.",
                details={"record_id": member["record_id"]},
            )
        if record.get("record_id") != member["record_id"] or canonical_record_hash(record) != member["record_hash"] or record.get("record_hash") != member["record_hash"]:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_HASH_INVALID",
                "An immutable membership record hash does not match its exact canonical bytes.",
                details={"record_id": member["record_id"]},
            )
        binding = record.get("content_binding") or {}
        if binding.get("pack_id") != pack_id or binding.get("pack_version") != version or binding.get("pack_hash") != pack_hash:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_BINDING_INVALID",
                "An immutable membership record is not bound to the exact pack identity.",
                details={"record_id": member["record_id"]},
            )
        if semantic_hash(record) != member["semantic_hash"]:
            raise FoundryError(
                "PACK_MEMBERSHIP_SEMANTIC_HASH_INVALID",
                "An immutable membership semantic hash does not match the record bytes.",
                details={"record_id": member["record_id"]},
            )
        record_set.append({
            "record_id": member["record_id"],
            "path": member["record_path"],
            "semantic_sha256": member["semantic_hash"],
        })
        snapshot.append({
            "record_id": member["record_id"],
            "record_hash": member["record_hash"],
            "record_path": member["record_path"],
            "semantic_hash": member["semantic_hash"],
        })
    derived_record_set_hash = sha256_json(record_set)
    if derived_record_set_hash != receipt_row["record_set_hash"]:
        raise FoundryError(
            "PACK_RECORD_SET_HASH_MISMATCH",
            "Immutable membership does not reproduce the install receipt record-set hash.",
            details={
                "pack_id": pack_id,
                "version": version,
                "expected": receipt_row["record_set_hash"],
                "actual": derived_record_set_hash,
            },
        )
    projected_members = install_projection.get("record_membership") or []
    if projected_members != record_set:
        raise FoundryError("PACK_INSTALL_INTEGRITY_MEMBERSHIP_MISMATCH", "The immutable membership differs from the external keyed install projection.", status_code=409)
    return PackSeal(
        pack_id=pack_id,
        version=version,
        pack_hash=pack_hash,
        record_set_hash=receipt_row["record_set_hash"],
        payload_files_hash=receipt_row["payload_files_hash"],
        install_receipt_hash=expected_receipt_hash,
        membership_snapshot_hash=sha256_json(snapshot),
        records=tuple(members),
    )
