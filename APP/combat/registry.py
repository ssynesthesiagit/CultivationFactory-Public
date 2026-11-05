from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .canonical import CANONICAL_FORMAT_VERSION, canonical_sha256
from .diagnostics import error
from .version import COMBAT_MODULE_VERSION
from .models import (
    CharacterSourceMappingDefinition,
    Definition,
    DoctrineInputDefinition,
    EncounterDefinition,
    LoadedPack,
    MechanicalDefinition,
    RegistryDefinitionRecord,
    RegistryPackRecord,
    RegistrySnapshotCore,
    RegistrySnapshotEnvelope,
    STABLE_ID_RE,
)


def _stable_ids_in_value(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if STABLE_ID_RE.fullmatch(value):
            found.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_stable_ids_in_value(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_stable_ids_in_value(item))
    return found


@dataclass(frozen=True)
class TypedRegistry:
    packs: dict[str, LoadedPack]
    definitions: dict[str, Definition]
    snapshot: RegistrySnapshotEnvelope

    def require(self, stable_id: str) -> Definition:
        try:
            return self.definitions[stable_id]
        except KeyError as exc:
            raise error(
                "COMBAT_REGISTRY_ID_NOT_FOUND",
                "A required stable ID is not present in the compiled combat registry.",
                phase="REGISTRY_USE",
                subsystem="combat.registry",
                entity_id=stable_id,
                recommended_action="Install the exact pack that provides this stable ID and recompile the registry.",
            ) from exc


def compile_registry(packs: Iterable[LoadedPack]) -> TypedRegistry:
    pack_map: dict[str, LoadedPack] = {}
    definition_map: dict[str, Definition] = {}
    definition_owner: dict[str, str] = {}
    for pack in packs:
        pack_id = pack.manifest.pack_id
        if pack_id in pack_map:
            raise error(
                "COMBAT_DUPLICATE_PACK_ID",
                "Two installed combat packs use the same pack ID.",
                phase="REGISTRY_COMPILE",
                subsystem="combat.registry",
                entity_id=pack_id,
                recommended_action="Keep exactly one installed artifact for each pack ID.",
            )
        pack_map[pack_id] = pack
        for definition in pack.definitions:
            if definition.stable_id in definition_map:
                raise error(
                    "COMBAT_DUPLICATE_STABLE_ID",
                    "Two combat definitions use the same permanent stable ID.",
                    phase="REGISTRY_COMPILE",
                    subsystem="combat.registry",
                    entity_id=definition.stable_id,
                    source_definition=pack_id,
                    recommended_action="Rename or remove one definition; display names may change but stable IDs must remain unique.",
                    details={"first_pack": definition_owner[definition.stable_id], "second_pack": pack_id},
                )
            definition_map[definition.stable_id] = definition
            definition_owner[definition.stable_id] = pack_id

    for pack in pack_map.values():
        for dependency in pack.manifest.dependencies:
            installed = pack_map.get(dependency.pack_id)
            if installed is None:
                raise error(
                    "COMBAT_PACK_DEPENDENCY_MISSING",
                    "A combat pack has a missing exact dependency.",
                    phase="REGISTRY_COMPILE",
                    subsystem="combat.registry",
                    entity_id=pack.manifest.pack_id,
                    source_definition=dependency.pack_id,
                    recommended_action="Install the exact required dependency before compiling the registry.",
                    details={"expected_version": dependency.exact_version},
                )
            if installed.manifest.version != dependency.exact_version:
                raise error(
                    "COMBAT_PACK_DEPENDENCY_VERSION_MISMATCH",
                    "A combat pack dependency is installed at the wrong exact version.",
                    phase="REGISTRY_COMPILE",
                    subsystem="combat.registry",
                    entity_id=pack.manifest.pack_id,
                    source_definition=dependency.pack_id,
                    recommended_action="Install the exact dependency version recorded by the pack.",
                    details={"expected": dependency.exact_version, "actual": installed.manifest.version},
                )

    for stable_id, definition in definition_map.items():
        references: set[str] = set()
        if isinstance(definition, MechanicalDefinition):
            references.update(definition.references)
            references.update(_stable_ids_in_value(definition.mechanics))
        elif isinstance(definition, CharacterSourceMappingDefinition):
            references.update(definition.required_definition_ids())
        elif isinstance(definition, DoctrineInputDefinition):
            references.add(definition.character_mapping_id)
        elif isinstance(definition, EncounterDefinition):
            references.add(definition.battlefield_id)
            for team in definition.teams:
                references.update(team.participant_ids)
            references.update(definition.companion_owner.keys())
            references.update(definition.companion_owner.values())
        else:
            dump = definition.model_dump(mode="json")
            for key, value in dump.items():
                if key.endswith("_id") and key not in {"stable_id", "character_id", "doctrine_id", "team_id", "region_id"} and isinstance(value, str):
                    if ":" in value:
                        references.add(value)
                elif key.endswith("_ids") and isinstance(value, list):
                    references.update(item for item in value if isinstance(item, str) and ":" in item)
            if hasattr(definition, "required_definition_ids"):
                references.update(definition.required_definition_ids())
        for reference in sorted(references):
            if reference not in definition_map:
                raise error(
                    "COMBAT_UNRESOLVED_STABLE_ID",
                    "A combat definition refers to a stable ID that is not installed.",
                    phase="REGISTRY_COMPILE",
                    subsystem="combat.registry",
                    entity_id=stable_id,
                    source_definition=reference,
                    recommended_action="Install or correct the definition that should provide the missing stable ID.",
                )

    pack_records = tuple(
        RegistryPackRecord(
            pack_id=pack.manifest.pack_id,
            family=pack.manifest.family,
            exact_version=pack.manifest.version,
            artifact_sha256=pack.installation.artifact_sha256,
            canonical_payload_hash=pack.manifest.canonical_payload_hash,
        )
        for pack in sorted(pack_map.values(), key=lambda item: item.manifest.pack_id)
    )
    definition_records = tuple(
        RegistryDefinitionRecord(
            stable_id=stable_id,
            kind=definition.kind,
            pack_id=definition_owner[stable_id],
            canonical_definition_sha256=canonical_sha256(definition.model_dump(mode="json")),
        )
        for stable_id, definition in sorted(definition_map.items())
    )
    core = RegistrySnapshotCore(
        schema="TianxiaCombatRegistrySnapshot.v1",
        canonical_format_version=CANONICAL_FORMAT_VERSION,
        engine_api_version="1.0",
        combat_module_version=COMBAT_MODULE_VERSION,
        packs=pack_records,
        definitions=definition_records,
    )
    envelope = RegistrySnapshotEnvelope(snapshot=core, snapshot_sha256=canonical_sha256(core.model_dump(mode="json")))
    return TypedRegistry(packs=pack_map, definitions=definition_map, snapshot=envelope)
