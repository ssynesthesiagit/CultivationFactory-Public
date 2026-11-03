from __future__ import annotations

import json
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .canonical import canonical_bytes, sha256_bytes, sha256_file
from .diagnostics import RecoveryDisposition, error
from .models import Definition, DefinitionDocument, InstallationRecord, InstallationRecordSet, LoadedPack, PackManifest
from .packaging import EXCLUDED_PAYLOAD_PATHS, PACK_MANIFEST

_DEFINITION_ADAPTER = TypeAdapter(DefinitionDocument)


def _safe_member_names(archive: zipfile.ZipFile, artifact: Path) -> list[str]:
    names: list[str] = []
    exact: set[str] = set()
    folded: set[str] = set()
    normalized: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if "\\" in name:
            raise error(
                "COMBAT_PACK_UNSAFE_PATH",
                "A combat pack contains a backslash member name.",
                phase="PACK_LOAD",
                subsystem="combat.pack_loader",
                source_definition=name,
                recommended_action="Rebuild the pack using forward-slash relative paths.",
                details={"artifact": artifact.name},
            )
        path = PurePosixPath(name)
        if path.is_absolute() or not name or any(part in ("", ".", "..") for part in path.parts):
            raise error(
                "COMBAT_PACK_UNSAFE_PATH",
                "A combat pack contains an unsafe or non-canonical member path.",
                phase="PACK_LOAD",
                subsystem="combat.pack_loader",
                source_definition=name,
                recommended_action="Remove absolute paths, empty segments, dot segments, and parent traversal.",
                details={"artifact": artifact.name},
            )
        canonical_name = path.as_posix()
        folded_name = canonical_name.casefold()
        normalized_name = unicodedata.normalize("NFC", canonical_name)
        if canonical_name in exact or folded_name in folded or normalized_name in normalized:
            raise error(
                "COMBAT_PACK_PATH_COLLISION",
                "A combat pack contains duplicate or case/Unicode-colliding member paths.",
                phase="PACK_LOAD",
                subsystem="combat.pack_loader",
                source_definition=canonical_name,
                recommended_action="Rename the colliding pack members so every path is unique.",
                details={"artifact": artifact.name},
            )
        exact.add(canonical_name)
        folded.add(folded_name)
        normalized.add(normalized_name)
        if info.flag_bits & 0x1:
            raise error(
                "COMBAT_PACK_ENCRYPTED_MEMBER",
                "Encrypted combat-pack members are not supported.",
                phase="PACK_LOAD",
                subsystem="combat.pack_loader",
                source_definition=canonical_name,
                recommended_action="Rebuild the pack without ZIP encryption.",
            )
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise error(
                "COMBAT_PACK_SPECIAL_FILE",
                "A combat pack contains a symbolic link or special file.",
                phase="PACK_LOAD",
                subsystem="combat.pack_loader",
                source_definition=canonical_name,
                recommended_action="Use regular files and directories only.",
            )
        if not info.is_dir():
            names.append(canonical_name)
    return sorted(names)


def _payload_hash_from_zip(archive: zipfile.ZipFile, names: list[str]) -> str:
    records = []
    for name in names:
        if name in EXCLUDED_PAYLOAD_PATHS:
            continue
        data = archive.read(name)
        records.append({"path": name, "size": len(data), "sha256": sha256_bytes(data)})
    return sha256_bytes(canonical_bytes({"payload_domain_version": "1", "files": records}))


def load_pack(artifact: Path, installation: InstallationRecord) -> LoadedPack:
    if not artifact.is_file():
        raise error(
            "COMBAT_PACK_MISSING",
            "An installed combat pack artifact is missing.",
            phase="PACK_LOAD",
            subsystem="combat.pack_loader",
            entity_id=installation.pack_id,
            source_definition=str(artifact),
            recommended_action="Restore the exact pack artifact recorded by the installation record.",
            details={"expected_version": installation.exact_version},
        )
    actual_size = artifact.stat().st_size
    actual_hash = sha256_file(artifact)
    if actual_size != installation.artifact_size or actual_hash != installation.artifact_sha256:
        raise error(
            "COMBAT_PACK_ARTIFACT_IDENTITY_MISMATCH",
            "The installed combat pack does not match its external installation identity.",
            phase="PACK_LOAD",
            subsystem="combat.pack_loader",
            entity_id=installation.pack_id,
            source_definition=artifact.name,
            recommended_action="Reinstall the exact expected pack version or update the installation record deliberately.",
            details={
                "expected_size": installation.artifact_size,
                "actual_size": actual_size,
                "expected_sha256": installation.artifact_sha256,
                "actual_sha256": actual_hash,
            },
        )
    try:
        with zipfile.ZipFile(artifact) as archive:
            names = _safe_member_names(archive, artifact)
            bad_member = archive.testzip()
            if bad_member is not None:
                raise error(
                    "COMBAT_PACK_ZIP_INTEGRITY_FAILURE",
                    "A combat pack failed its ZIP CRC check.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=installation.pack_id,
                    source_definition=bad_member,
                    recommended_action="Replace the damaged pack artifact.",
                )
            if PACK_MANIFEST not in names:
                raise error(
                    "COMBAT_PACK_MANIFEST_MISSING",
                    "A combat pack is missing pack.json.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=installation.pack_id,
                    recommended_action="Add the required minimal pack manifest and rebuild the pack.",
                )
            try:
                manifest = PackManifest.model_validate_json(archive.read(PACK_MANIFEST))
            except ValidationError as exc:
                raise error(
                    "COMBAT_PACK_MANIFEST_INVALID",
                    "A combat pack manifest does not match the Gate 1 schema.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=installation.pack_id,
                    source_definition=PACK_MANIFEST,
                    recommended_action="Correct the manifest fields and rebuild the pack.",
                    details={"validation_errors": exc.errors(include_url=False)},
                ) from exc
            if manifest.pack_id != installation.pack_id or manifest.version != installation.exact_version:
                raise error(
                    "COMBAT_PACK_INSTALLATION_RECORD_MISMATCH",
                    "The pack manifest identity differs from the external installation record.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=installation.pack_id,
                    source_definition=PACK_MANIFEST,
                    recommended_action="Install the exact recorded pack version.",
                    details={"manifest_pack_id": manifest.pack_id, "manifest_version": manifest.version},
                )
            payload_hash = _payload_hash_from_zip(archive, names)
            if payload_hash != manifest.canonical_payload_hash:
                raise error(
                    "COMBAT_PACK_PAYLOAD_HASH_MISMATCH",
                    "The combat pack payload does not match its non-self canonical payload hash.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=manifest.pack_id,
                    source_definition=PACK_MANIFEST,
                    recommended_action="Rebuild or restore the pack; do not silently accept changed payload bytes.",
                    details={"expected": manifest.canonical_payload_hash, "actual": payload_hash},
                )
            definitions: list[Definition] = []
            definition_files = [name for name in names if name.startswith("definitions/") and name.endswith(".json")]
            for name in definition_files:
                try:
                    document = _DEFINITION_ADAPTER.validate_json(archive.read(name))
                except ValidationError as exc:
                    raise error(
                        "COMBAT_DEFINITION_SCHEMA_INVALID",
                        "A combat content definition file is malformed.",
                        phase="PACK_LOAD",
                        subsystem="combat.pack_loader",
                        entity_id=manifest.pack_id,
                        source_definition=name,
                        recommended_action="Correct the typed definition and rebuild the pack.",
                        details={"validation_errors": exc.errors(include_url=False)},
                    ) from exc
                definitions.extend(document.definitions)
            actual_ids = tuple(sorted(definition.stable_id for definition in definitions))
            if actual_ids != manifest.provided_ids:
                raise error(
                    "COMBAT_PACK_PROVIDED_IDS_MISMATCH",
                    "The manifest provided_ids list does not exactly match the definitions in the pack.",
                    phase="PACK_LOAD",
                    subsystem="combat.pack_loader",
                    entity_id=manifest.pack_id,
                    recommended_action="Regenerate provided_ids from the pack definitions.",
                    details={"manifest_ids": manifest.provided_ids, "actual_ids": actual_ids},
                )
            return LoadedPack(manifest=manifest, installation=installation, definitions=tuple(definitions))
    except zipfile.BadZipFile as exc:
        raise error(
            "COMBAT_PACK_NOT_A_ZIP",
            "The installed combat pack is not a readable ZIP archive.",
            phase="PACK_LOAD",
            subsystem="combat.pack_loader",
            entity_id=installation.pack_id,
            source_definition=artifact.name,
            recommended_action="Replace the damaged or incorrectly named pack artifact.",
        ) from exc


def load_installation_records(path: Path) -> tuple[InstallationRecord, ...]:
    try:
        document = InstallationRecordSet.model_validate_json(path.read_bytes())
        records = document.installations
    except (OSError, ValidationError) as exc:
        raise error(
            "COMBAT_INSTALLATION_RECORDS_INVALID",
            "The combat installation record is missing or malformed.",
            phase="PACK_LOAD",
            subsystem="combat.pack_loader",
            source_definition=str(path),
            recommended_action="Restore or regenerate the exact installation record.",
            details={"exception": str(exc)},
        ) from exc
    keys = [(record.pack_id, record.exact_version) for record in records]
    if tuple(sorted(keys)) != tuple(keys) or len(set(keys)) != len(keys):
        raise error(
            "COMBAT_INSTALLATION_RECORDS_NOT_CANONICAL",
            "Combat installation records must be unique and sorted by pack ID/version.",
            phase="PACK_LOAD",
            subsystem="combat.pack_loader",
            source_definition=str(path),
            recommended_action="Sort and deduplicate the installation records.",
        )
    return records
