from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .canonical import canonical_sha256, sha256_file
from .character_runtime_adapter import (
    CharacterCombatRuntimeAdapter,
    CharacterRuntimeBundle,
    RuntimeResourceInitialization,
)
from .models import StrictModel
from .pre_encounter import CombatantLibraryEntry

RUNTIME_AUTHORITY_SCHEMA = "TianxiaPortableCombatRuntimeAuthority.v1"
RUNTIME_AUTHORITY_FILE = "PortableRuntimeAuthority.json"
SOURCE_PACKAGE_FILE = "SourceCharacterPackage.zip"


def runtime_actor_id(project_id: str, package_sha256: str) -> str:
    digest = canonical_sha256({"project_id": project_id, "package_sha256": package_sha256})
    return f"portable-character:{digest[:24]}"


class PortableRuntimeAuthority(StrictModel):
    schema_name: Literal[RUNTIME_AUTHORITY_SCHEMA] = Field(default=RUNTIME_AUTHORITY_SCHEMA, alias="schema")
    runtime_actor_id: str
    candidate_entry_id: str
    project_id: str
    package_sha256: str
    project_revision: int
    event_head_hash: str
    replay_state_hash: str
    content_lock_hash: str
    combat_sheet_id: str
    combat_sheet_commitment_sha256: str
    mechanics_lock_sha256: str
    primitive_registry_sha256: str
    runtime_adapter_id: str
    runtime_adapter_version: str
    runtime_engine_version: str
    actor_template_commitment_sha256: str
    source_actor_id: str
    bundle: CharacterRuntimeBundle
    source_package_relative_path: Literal[SOURCE_PACKAGE_FILE] = SOURCE_PACKAGE_FILE
    display_prose_parsed: Literal[False] = False
    package_build_state_resource_values_used: Literal[False] = False
    source_package_mutated: Literal[False] = False
    authority_sha256: str

    @model_validator(mode="after")
    def validate_authority(self) -> "PortableRuntimeAuthority":
        if self.runtime_actor_id != runtime_actor_id(self.project_id, self.package_sha256):
            raise ValueError("portable runtime actor identity mismatch")
        if self.bundle.mechanics_lock_sha256 != self.mechanics_lock_sha256:
            raise ValueError("portable mechanics lock mismatch")
        if self.bundle.primitive_registry_sha256 != self.primitive_registry_sha256:
            raise ValueError("portable primitive registry mismatch")
        if self.bundle.actor_template.entity_id != self.source_actor_id:
            raise ValueError("portable source actor identity mismatch")
        raw = self.model_dump(mode="json", by_alias=True)
        expected = raw.pop("authority_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("portable runtime authority checksum mismatch")
        return self

    def runtime_bundle(self, *, team_id: str | None = None) -> CharacterRuntimeBundle:
        actor = self.bundle.actor_template.model_copy(
            update={
                "entity_id": self.runtime_actor_id,
                "team_id": team_id or self.bundle.actor_template.team_id,
                "projection_sha256": self.actor_template_commitment_sha256,
            }
        )
        raw = self.bundle.model_dump(mode="json", by_alias=True)
        raw["actor_template"] = actor.model_dump(mode="json")
        raw.pop("bundle_sha256", None)
        raw["bundle_sha256"] = canonical_sha256(raw)
        return CharacterRuntimeBundle.model_validate(raw)


def build_runtime_authority(
    entry: CombatantLibraryEntry,
    package: Path,
    *,
    qi_current: int,
    martial_focus_current: int,
    provenance_id: str,
) -> PortableRuntimeAuthority:
    package = Path(package)
    if sha256_file(package) != entry.source_package_sha256:
        raise ValueError("C3D_SOURCE_PACKAGE_IDENTITY_CHANGED")
    adapter = CharacterCombatRuntimeAdapter(package)
    bundle = adapter.build_bundle(
        RuntimeResourceInitialization(
            qi_current=qi_current,
            martial_focus_current=martial_focus_current,
            provenance_kind="ENCOUNTER_AUTHORITY",
            provenance_id=provenance_id,
            canonical_owner_choice=False,
        )
    )
    raw: dict[str, Any] = {
        "schema": RUNTIME_AUTHORITY_SCHEMA,
        "runtime_actor_id": runtime_actor_id(entry.character_project_id, entry.source_package_sha256),
        "candidate_entry_id": entry.entry_id,
        "project_id": entry.character_project_id,
        "package_sha256": entry.source_package_sha256,
        "project_revision": entry.project_revision,
        "event_head_hash": entry.event_head_hash,
        "replay_state_hash": entry.replay_state_hash,
        "content_lock_hash": entry.content_lock_hash,
        "combat_sheet_id": entry.combat_sheet_id,
        "combat_sheet_commitment_sha256": entry.combat_sheet_commitment_sha256,
        "mechanics_lock_sha256": entry.mechanics_lock_sha256,
        "primitive_registry_sha256": entry.primitive_registry_sha256,
        "runtime_adapter_id": entry.runtime_adapter_id,
        "runtime_adapter_version": entry.runtime_adapter_version,
        "runtime_engine_version": entry.runtime_engine_version,
        "actor_template_commitment_sha256": entry.actor_template_commitment_sha256,
        "source_actor_id": entry.actor_id,
        "bundle": bundle.model_dump(mode="json", by_alias=True),
        "source_package_relative_path": SOURCE_PACKAGE_FILE,
        "display_prose_parsed": False,
        "package_build_state_resource_values_used": False,
        "source_package_mutated": False,
    }
    raw["authority_sha256"] = canonical_sha256(raw)
    return PortableRuntimeAuthority.model_validate(raw)
