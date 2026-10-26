from __future__ import annotations

from .canonical import CANONICAL_FORMAT_VERSION, canonical_sha256
from .diagnostics import error
from .models import (
    CharacterSourceMappingDefinition,
    CombatRuntimeProjectionCore,
    CombatRuntimeProjectionEnvelope,
    Definition,
    DoctrineInputDefinition,
    FidelityDisposition,
    MechanicalDefinition,
    TacticalDoctrineCore,
    TacticalDoctrineEnvelope,
)
from .registry import TypedRegistry

from .version import PROJECTION_COMPILER_VERSION


def _project_definition(registry: TypedRegistry, stable_id: str) -> dict:
    definition = registry.require(stable_id)
    if not isinstance(definition, MechanicalDefinition):
        raise error(
            "COMBAT_PROJECTION_DEFINITION_KIND_INVALID",
            "A runtime projection list refers to a non-mechanical definition.",
            phase="PROJECTION_COMPILE",
            subsystem="combat.projection",
            entity_id=stable_id,
            recommended_action="Correct the character source mapping to reference a mechanical definition.",
        )
    return {
        "stable_id": definition.stable_id,
        "kind": definition.kind.value,
        "display_name": definition.display_name,
        "mechanics": definition.mechanics,
        "source": definition.source,
    }


def compile_projection(registry: TypedRegistry, mapping_id: str) -> CombatRuntimeProjectionEnvelope:
    mapping = registry.require(mapping_id)
    if not isinstance(mapping, CharacterSourceMappingDefinition):
        raise error(
            "COMBAT_CHARACTER_MAPPING_KIND_INVALID",
            "The requested character source mapping has the wrong definition type.",
            phase="PROJECTION_COMPILE",
            subsystem="combat.projection",
            entity_id=mapping_id,
            recommended_action="Reference a CHARACTER_SOURCE_MAPPING definition.",
        )
    required = mapping.required_definition_ids()
    fidelity = {row.definition_id: row for row in mapping.mechanic_fidelity}
    missing = sorted(required - fidelity.keys())
    extra = sorted(fidelity.keys() - required)
    if missing or extra:
        raise error(
            "COMBAT_PROJECTION_FIDELITY_COVERAGE_MISMATCH",
            "The character mechanic-fidelity review does not exactly cover the projection inputs.",
            phase="PROJECTION_COMPILE",
            subsystem="combat.projection",
            entity_id=mapping.character_id,
            source_definition=mapping_id,
            recommended_action="Add or remove fidelity rows so every projected mechanic is classified exactly once.",
            details={"missing": missing, "extra": extra},
        )
    material_deferred = [
        row.definition_id
        for row in mapping.mechanic_fidelity
        if row.disposition == FidelityDisposition.MVP_DEFERRED_UNSUPPORTED
        and any(
            (
                row.changes_tactical_choices,
                row.changes_action_sequence,
                row.changes_resource_use,
                row.changes_positioning,
                row.changes_risk_tolerance,
                row.changes_team_role,
                row.changes_dao_expression,
                row.changes_iching_expression,
            )
        )
    ]
    if material_deferred:
        raise error(
            "COMBAT_PROJECTION_MATERIAL_MECHANIC_DEFERRED",
            "A character-defining combat mechanic was deferred from the Gate 1 projection.",
            phase="PROJECTION_COMPILE",
            subsystem="combat.projection",
            entity_id=mapping.character_id,
            recommended_action="Include the mechanic or replace the character before accepting Gate 1.",
            details={"definition_ids": material_deferred},
        )
    core = CombatRuntimeProjectionCore(
        schema="TianxiaCombatRuntimeProjection.v1",
        canonical_format_version=CANONICAL_FORMAT_VERSION,
        projection_compiler_version=PROJECTION_COMPILER_VERSION,
        registry_snapshot_sha256=registry.snapshot.snapshot_sha256,
        character_id=mapping.character_id,
        display_name=mapping.display_name,
        cultivation_level=5,
        realm=mapping.realm,
        statistics=mapping.statistics,
        resources=tuple(_project_definition(registry, item) for item in mapping.resource_ids),
        actions=tuple(_project_definition(registry, item) for item in mapping.action_ids),
        reactions=tuple(_project_definition(registry, item) for item in mapping.reaction_ids),
        passives=tuple(_project_definition(registry, item) for item in mapping.passive_ids),
        condition_immunities=tuple(_project_definition(registry, item) for item in mapping.condition_immunity_ids),
        equipment_effects=tuple(_project_definition(registry, item) for item in mapping.item_ids),
        path_effects=(_project_definition(registry, mapping.primary_path_id),),
        subpath_effects=tuple(_project_definition(registry, item) for item in mapping.subpath_ids),
        foundation_effects=tuple(_project_definition(registry, item) for item in mapping.foundation_ids),
        spheres=tuple(_project_definition(registry, item) for item in mapping.sphere_ids),
        talents=tuple(_project_definition(registry, item) for item in mapping.talent_ids),
        companions=tuple(_project_definition(registry, item) for item in mapping.companion_ids),
        doctrine_source=mapping.doctrine_source,
        mechanic_fidelity=mapping.mechanic_fidelity,
        source_provenance=mapping.source_provenance,
    )
    return CombatRuntimeProjectionEnvelope(
        projection=core,
        projection_sha256=canonical_sha256(core.model_dump(mode="json")),
    )


def compile_doctrine(
    registry: TypedRegistry,
    doctrine_input_id: str,
    projection: CombatRuntimeProjectionEnvelope,
) -> TacticalDoctrineEnvelope:
    source = registry.require(doctrine_input_id)
    if not isinstance(source, DoctrineInputDefinition):
        raise error(
            "COMBAT_DOCTRINE_INPUT_KIND_INVALID",
            "The requested Tactical Doctrine input has the wrong definition type.",
            phase="DOCTRINE_COMPILE",
            subsystem="combat.projection",
            entity_id=doctrine_input_id,
            recommended_action="Reference a DOCTRINE_INPUT definition.",
        )
    if source.character_mapping_id != f"character_mapping:{projection.projection.character_id}":
        raise error(
            "COMBAT_DOCTRINE_PROJECTION_MISMATCH",
            "A Tactical Doctrine input is bound to a different character source mapping.",
            phase="DOCTRINE_COMPILE",
            subsystem="combat.projection",
            entity_id=source.doctrine_id,
            recommended_action="Compile the doctrine with its matching character projection.",
        )
    core = TacticalDoctrineCore(
        schema="TianxiaTacticalDoctrine.v1",
        canonical_format_version=CANONICAL_FORMAT_VERSION,
        doctrine_id=source.doctrine_id,
        doctrine_version=source.doctrine_version,
        doctrine_schema_version=source.doctrine_schema_version,
        source_projection_sha256=projection.projection_sha256,
        components=projection.projection.doctrine_source,
    )
    return TacticalDoctrineEnvelope(doctrine=core, doctrine_sha256=canonical_sha256(core.model_dump(mode="json")))
