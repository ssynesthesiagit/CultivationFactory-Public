from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z0-9][a-z0-9_.-]*$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True)


class PackFamily(StrEnum):
    CORE_RULES = "CORE_RULES"
    CHARACTER_CONTENT = "CHARACTER_CONTENT"
    CREATURE_CONTENT = "CREATURE_CONTENT"
    BATTLEFIELD = "BATTLEFIELD"
    ENCOUNTER = "ENCOUNTER"


class DefinitionKind(StrEnum):
    PRIMITIVE = "PRIMITIVE"
    RESOURCE = "RESOURCE"
    ACTION = "ACTION"
    REACTION = "REACTION"
    PASSIVE = "PASSIVE"
    CONDITION = "CONDITION"
    PATH = "PATH"
    SUBPATH = "SUBPATH"
    FOUNDATION = "FOUNDATION"
    SPHERE = "SPHERE"
    TALENT = "TALENT"
    ITEM = "ITEM"
    CREATURE = "CREATURE"
    CHARACTER_SOURCE_MAPPING = "CHARACTER_SOURCE_MAPPING"
    DOCTRINE_INPUT = "DOCTRINE_INPUT"
    BATTLEFIELD = "BATTLEFIELD"
    ENCOUNTER = "ENCOUNTER"


class FidelityDisposition(StrEnum):
    MVP_INCLUDED = "MVP_INCLUDED"
    MVP_REDUNDANT_PRESENTATION_ONLY = "MVP_REDUNDANT_PRESENTATION_ONLY"
    MVP_DEFERRED_UNSUPPORTED = "MVP_DEFERRED_UNSUPPORTED"


class Dependency(StrictModel):
    pack_id: str = Field(min_length=3)
    exact_version: str

    @model_validator(mode="after")
    def validate_version(self) -> "Dependency":
        if not SEMVER_RE.fullmatch(self.exact_version):
            raise ValueError("exact_version must be x.y.z")
        return self


class PackManifest(StrictModel):
    pack_id: str = Field(min_length=3)
    family: PackFamily
    version: str
    schema_version: Literal["1.0"]
    engine_api_version: Literal["1.0"]
    dependencies: tuple[Dependency, ...] = ()
    provided_ids: tuple[str, ...]
    payload_domain_version: Literal["1"]
    canonical_payload_hash: str

    @model_validator(mode="after")
    def validate_manifest(self) -> "PackManifest":
        if not SEMVER_RE.fullmatch(self.version):
            raise ValueError("version must be x.y.z")
        if not SHA256_RE.fullmatch(self.canonical_payload_hash):
            raise ValueError("canonical_payload_hash must be lowercase SHA-256")
        if tuple(sorted(self.provided_ids)) != self.provided_ids:
            raise ValueError("provided_ids must be sorted")
        if len(set(self.provided_ids)) != len(self.provided_ids):
            raise ValueError("provided_ids must be unique")
        for stable_id in self.provided_ids:
            if not STABLE_ID_RE.fullmatch(stable_id):
                raise ValueError(f"invalid stable ID: {stable_id}")
        dep_keys = [(d.pack_id, d.exact_version) for d in self.dependencies]
        if tuple(sorted(dep_keys)) != tuple(dep_keys) or len(set(dep_keys)) != len(dep_keys):
            raise ValueError("dependencies must be unique and sorted")
        return self


class InstallationRecord(StrictModel):
    pack_id: str
    exact_version: str
    artifact_filename: str
    artifact_size: int = Field(ge=1)
    artifact_sha256: str

    @model_validator(mode="after")
    def validate_record(self) -> "InstallationRecord":
        if not SEMVER_RE.fullmatch(self.exact_version):
            raise ValueError("exact_version must be x.y.z")
        if not SHA256_RE.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256 must be lowercase SHA-256")
        if "/" in self.artifact_filename or "\\" in self.artifact_filename:
            raise ValueError("artifact_filename must be a basename")
        return self


class InstallationRecordSet(StrictModel):
    artifact_schema: Literal["TianxiaCombatInstallationRecords.v1"] = Field(alias="schema")
    installations: tuple[InstallationRecord, ...]

    @model_validator(mode="after")
    def validate_records(self) -> "InstallationRecordSet":
        keys = [(record.pack_id, record.exact_version) for record in self.installations]
        if tuple(sorted(keys)) != tuple(keys) or len(set(keys)) != len(keys):
            raise ValueError("installations must be unique and sorted")
        return self


class MechanicalDefinition(StrictModel):
    stable_id: str
    kind: Literal[
        DefinitionKind.PRIMITIVE,
        DefinitionKind.RESOURCE,
        DefinitionKind.ACTION,
        DefinitionKind.REACTION,
        DefinitionKind.PASSIVE,
        DefinitionKind.CONDITION,
        DefinitionKind.PATH,
        DefinitionKind.SUBPATH,
        DefinitionKind.FOUNDATION,
        DefinitionKind.SPHERE,
        DefinitionKind.TALENT,
        DefinitionKind.ITEM,
        DefinitionKind.CREATURE,
    ]
    display_name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    references: tuple[str, ...] = ()
    mechanics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_definition(self) -> "MechanicalDefinition":
        if self.kind in {
            DefinitionKind.CHARACTER_SOURCE_MAPPING,
            DefinitionKind.DOCTRINE_INPUT,
            DefinitionKind.BATTLEFIELD,
            DefinitionKind.ENCOUNTER,
        }:
            raise ValueError(f"{self.kind} requires its dedicated typed schema")
        if not STABLE_ID_RE.fullmatch(self.stable_id):
            raise ValueError(f"invalid stable ID: {self.stable_id}")
        if tuple(sorted(self.references)) != self.references or len(set(self.references)) != len(self.references):
            raise ValueError("references must be unique and sorted")
        return self


class AbilityScores(StrictModel):
    strength: int = Field(ge=1, le=30)
    dexterity: int = Field(ge=1, le=30)
    constitution: int = Field(ge=1, le=30)
    intelligence: int = Field(ge=1, le=30)
    wisdom: int = Field(ge=1, le=30)
    charisma: int = Field(ge=1, le=30)


class CombatStatistics(StrictModel):
    armor_class: int = Field(ge=1)
    hit_points: int = Field(ge=1)
    speed_ft: int = Field(ge=0)
    proficiency_bonus: int = Field(ge=1)
    cultivation_attack_bonus: int
    cultivation_save_dc: int = Field(ge=1)
    ability_scores: AbilityScores


class MechanicFidelityRow(StrictModel):
    source_mechanic_id: str
    definition_id: str
    disposition: FidelityDisposition
    rationale: str = Field(min_length=1)
    changes_tactical_choices: bool = False
    changes_action_sequence: bool = False
    changes_resource_use: bool = False
    changes_positioning: bool = False
    changes_risk_tolerance: bool = False
    changes_team_role: bool = False
    changes_dao_expression: bool = False
    changes_iching_expression: bool = False

    @model_validator(mode="after")
    def validate_material_deferment(self) -> "MechanicFidelityRow":
        if not STABLE_ID_RE.fullmatch(self.definition_id):
            raise ValueError(f"invalid definition_id: {self.definition_id}")
        if self.disposition == FidelityDisposition.MVP_DEFERRED_UNSUPPORTED and any(
            (
                self.changes_tactical_choices,
                self.changes_action_sequence,
                self.changes_resource_use,
                self.changes_positioning,
                self.changes_risk_tolerance,
                self.changes_team_role,
                self.changes_dao_expression,
                self.changes_iching_expression,
            )
        ):
            raise ValueError("A materially identity-changing mechanic cannot be deferred in Gate 1")
        return self


class DoctrineSource(StrictModel):
    role: tuple[str, ...]
    resource_policy: tuple[str, ...]
    relationships: tuple[str, ...]
    risk_profile: tuple[str, ...]
    dao: tuple[str, ...]
    iching: tuple[str, ...]
    phase_behavior: tuple[str, ...]
    prohibitions_and_exceptions: tuple[str, ...]


class CharacterSourceMappingDefinition(StrictModel):
    stable_id: str
    kind: Literal[DefinitionKind.CHARACTER_SOURCE_MAPPING]
    display_name: str
    source: str
    character_id: str
    cultivation_level: Literal[5]
    realm: str
    primary_path_id: str
    statistics: CombatStatistics
    resource_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    passive_ids: tuple[str, ...]
    condition_immunity_ids: tuple[str, ...] = ()
    item_ids: tuple[str, ...] = ()
    subpath_ids: tuple[str, ...] = ()
    foundation_ids: tuple[str, ...] = ()
    sphere_ids: tuple[str, ...] = ()
    talent_ids: tuple[str, ...] = ()
    companion_ids: tuple[str, ...] = ()
    doctrine_source: DoctrineSource
    mechanic_fidelity: tuple[MechanicFidelityRow, ...]
    source_provenance: tuple[str, ...]

    @model_validator(mode="after")
    def validate_mapping(self) -> "CharacterSourceMappingDefinition":
        if not STABLE_ID_RE.fullmatch(self.stable_id):
            raise ValueError(f"invalid stable ID: {self.stable_id}")
        if self.stable_id != f"character_mapping:{self.character_id}":
            raise ValueError("mapping stable_id must be character_mapping:<character_id>")
        for field_name in (
            "resource_ids", "action_ids", "reaction_ids", "passive_ids", "condition_immunity_ids",
            "item_ids", "subpath_ids", "foundation_ids", "sphere_ids", "talent_ids", "companion_ids",
        ):
            values = getattr(self, field_name)
            if tuple(sorted(values)) != values or len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be unique and sorted")
        fidelity_ids = [row.definition_id for row in self.mechanic_fidelity]
        if len(set(fidelity_ids)) != len(fidelity_ids):
            raise ValueError("mechanic_fidelity definition IDs must be unique")
        return self

    def required_definition_ids(self) -> set[str]:
        values = {self.primary_path_id}
        for field_name in (
            "resource_ids", "action_ids", "reaction_ids", "passive_ids", "condition_immunity_ids",
            "item_ids", "subpath_ids", "foundation_ids", "sphere_ids", "talent_ids", "companion_ids",
        ):
            values.update(getattr(self, field_name))
        return values


class DoctrineInputDefinition(StrictModel):
    stable_id: str
    kind: Literal[DefinitionKind.DOCTRINE_INPUT]
    display_name: str
    source: str
    doctrine_id: str
    doctrine_version: str
    doctrine_schema_version: Literal["1.0"]
    character_mapping_id: str

    @model_validator(mode="after")
    def validate_doctrine(self) -> "DoctrineInputDefinition":
        for value in (self.stable_id, self.doctrine_id, self.character_mapping_id):
            if not STABLE_ID_RE.fullmatch(value):
                raise ValueError(f"invalid stable ID: {value}")
        if not SEMVER_RE.fullmatch(self.doctrine_version):
            raise ValueError("doctrine_version must be x.y.z")
        return self


class GridPosition(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class TerrainRegion(StrictModel):
    region_id: str
    terrain_type: Literal["OPEN", "BLOCKED", "SIMPLE_COVER", "QI_HAZARD"]
    cells: tuple[GridPosition, ...]
    movement_cost: int = Field(ge=0)
    description: str


class BattlefieldDefinition(StrictModel):
    stable_id: str
    kind: Literal[DefinitionKind.BATTLEFIELD]
    display_name: str
    source: str
    battlefield_version: str
    width_squares: Literal[20]
    height_squares: Literal[14]
    square_size_ft: Literal[5]
    information_model: Literal["FULLY_VISIBLE"]
    terrain_regions: tuple[TerrainRegion, ...]
    starting_positions: dict[str, GridPosition]
    victory_boundary: Literal["NONLETHAL_WARDED_COURT"]

    @model_validator(mode="after")
    def validate_battlefield(self) -> "BattlefieldDefinition":
        if not STABLE_ID_RE.fullmatch(self.stable_id):
            raise ValueError(f"invalid stable ID: {self.stable_id}")
        if not SEMVER_RE.fullmatch(self.battlefield_version):
            raise ValueError("battlefield_version must be x.y.z")
        hazard_count = sum(region.terrain_type == "QI_HAZARD" for region in self.terrain_regions)
        if hazard_count != 1:
            raise ValueError("Gate 1 battlefield must contain exactly one Qi hazard")
        seen: set[tuple[int, int]] = set()
        for region in self.terrain_regions:
            for cell in region.cells:
                if cell.x >= self.width_squares or cell.y >= self.height_squares:
                    raise ValueError(f"terrain cell outside grid: {cell}")
                key = (cell.x, cell.y)
                if key in seen:
                    raise ValueError(f"terrain cell appears in multiple regions: {key}")
                seen.add(key)
        for actor, position in self.starting_positions.items():
            if position.x >= self.width_squares or position.y >= self.height_squares:
                raise ValueError(f"starting position outside grid for {actor}")
        return self


class EncounterTeam(StrictModel):
    team_id: str
    participant_ids: tuple[str, ...]


class EncounterDefinition(StrictModel):
    stable_id: str
    kind: Literal[DefinitionKind.ENCOUNTER]
    display_name: str
    source: str
    encounter_version: str
    battlefield_id: str
    teams: tuple[EncounterTeam, ...]
    companion_owner: dict[str, str]
    victory_condition: Literal["OPPOSING_PRIMARY_COMBATANTS_INACTIVE"]
    history_model: Literal["LINEAR_COMMITTED_WITH_SNAPSHOTS"]
    control_progression: tuple[Literal["MANUAL", "LOCAL_DETERMINISTIC", "MANUAL_AI_BRIDGE"], ...]

    @model_validator(mode="after")
    def validate_encounter(self) -> "EncounterDefinition":
        if not STABLE_ID_RE.fullmatch(self.stable_id) or not STABLE_ID_RE.fullmatch(self.battlefield_id):
            raise ValueError("encounter and battlefield IDs must be stable IDs")
        if not SEMVER_RE.fullmatch(self.encounter_version):
            raise ValueError("encounter_version must be x.y.z")
        if len(self.teams) != 2:
            raise ValueError("Gate 1 encounter requires exactly two teams")
        primary = [member for team in self.teams for member in team.participant_ids]
        if len(primary) != 4 or len(set(primary)) != 4:
            raise ValueError("Gate 1 encounter requires four unique primary participants")
        if self.control_progression != ("MANUAL", "LOCAL_DETERMINISTIC", "MANUAL_AI_BRIDGE"):
            raise ValueError("control progression must match the frozen vertical slice")
        return self


Definition = Annotated[
    Union[
        MechanicalDefinition,
        CharacterSourceMappingDefinition,
        DoctrineInputDefinition,
        BattlefieldDefinition,
        EncounterDefinition,
    ],
    Field(discriminator="kind"),
]


class DefinitionDocument(StrictModel):
    definitions: tuple[Definition, ...]


class LoadedPack(StrictModel):
    manifest: PackManifest
    installation: InstallationRecord
    definitions: tuple[Definition, ...]


class RegistryPackRecord(StrictModel):
    pack_id: str
    family: PackFamily
    exact_version: str
    artifact_sha256: str
    canonical_payload_hash: str


class RegistryDefinitionRecord(StrictModel):
    stable_id: str
    kind: DefinitionKind
    pack_id: str
    canonical_definition_sha256: str


class RegistrySnapshotCore(StrictModel):
    artifact_schema: Literal["TianxiaCombatRegistrySnapshot.v1"] = Field(alias="schema")
    canonical_format_version: Literal["tianxia.canonical-json.v1"]
    engine_api_version: Literal["1.0"]
    combat_module_version: Literal["0.1.0-gate1"]
    packs: tuple[RegistryPackRecord, ...]
    definitions: tuple[RegistryDefinitionRecord, ...]


class RegistrySnapshotEnvelope(StrictModel):
    snapshot: RegistrySnapshotCore
    snapshot_sha256: str


class CombatRuntimeProjectionCore(StrictModel):
    artifact_schema: Literal["TianxiaCombatRuntimeProjection.v1"] = Field(alias="schema")
    canonical_format_version: Literal["tianxia.canonical-json.v1"]
    projection_compiler_version: Literal["1.0.0"]
    registry_snapshot_sha256: str
    character_id: str
    display_name: str
    cultivation_level: Literal[5]
    realm: str
    statistics: CombatStatistics
    resources: tuple[dict[str, Any], ...]
    actions: tuple[dict[str, Any], ...]
    reactions: tuple[dict[str, Any], ...]
    passives: tuple[dict[str, Any], ...]
    condition_immunities: tuple[dict[str, Any], ...]
    equipment_effects: tuple[dict[str, Any], ...]
    path_effects: tuple[dict[str, Any], ...]
    subpath_effects: tuple[dict[str, Any], ...]
    foundation_effects: tuple[dict[str, Any], ...]
    spheres: tuple[dict[str, Any], ...]
    talents: tuple[dict[str, Any], ...]
    companions: tuple[dict[str, Any], ...]
    doctrine_source: DoctrineSource
    mechanic_fidelity: tuple[MechanicFidelityRow, ...]
    source_provenance: tuple[str, ...]


class CombatRuntimeProjectionEnvelope(StrictModel):
    projection: CombatRuntimeProjectionCore
    projection_sha256: str


class TacticalDoctrineCore(StrictModel):
    artifact_schema: Literal["TianxiaTacticalDoctrine.v1"] = Field(alias="schema")
    canonical_format_version: Literal["tianxia.canonical-json.v1"]
    doctrine_id: str
    doctrine_version: str
    doctrine_schema_version: Literal["1.0"]
    source_projection_sha256: str
    components: DoctrineSource


class TacticalDoctrineEnvelope(StrictModel):
    doctrine: TacticalDoctrineCore
    doctrine_sha256: str
