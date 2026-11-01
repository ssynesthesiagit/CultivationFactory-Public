from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .canonical import canonical_bytes
from .diagnostics import CombatDiagnostic, DiagnosticSeverity, RecoveryDisposition
from .models import (
    BattlefieldDefinition,
    CombatRuntimeProjectionEnvelope,
    DoctrineInputDefinition,
    EncounterDefinition,
    TacticalDoctrineEnvelope,
)
from .pack_loader import load_installation_records, load_pack
from .projection import compile_doctrine, compile_projection
from .registry import TypedRegistry, compile_registry


class Gate1BuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    registry: TypedRegistry
    projections: dict[str, CombatRuntimeProjectionEnvelope]
    doctrines: dict[str, TacticalDoctrineEnvelope]
    battlefield: BattlefieldDefinition
    encounter: EncounterDefinition
    diagnostics: tuple[CombatDiagnostic, ...]


def build_gate1(gate1_root: Path, output_dir: Path | None = None) -> Gate1BuildResult:
    records = load_installation_records(gate1_root / "installation_records.json")
    loaded = tuple(load_pack(gate1_root / "packs" / record.artifact_filename, record) for record in records)
    registry = compile_registry(loaded)

    mapping_ids = sorted(
        stable_id for stable_id, definition in registry.definitions.items() if stable_id.startswith("character_mapping:")
    )
    projections = {mapping_id: compile_projection(registry, mapping_id) for mapping_id in mapping_ids}

    doctrine_inputs = sorted(
        (definition for definition in registry.definitions.values() if isinstance(definition, DoctrineInputDefinition)),
        key=lambda definition: definition.stable_id,
    )
    doctrines = {
        source.stable_id: compile_doctrine(registry, source.stable_id, projections[source.character_mapping_id])
        for source in doctrine_inputs
    }

    battlefields = [definition for definition in registry.definitions.values() if isinstance(definition, BattlefieldDefinition)]
    encounters = [definition for definition in registry.definitions.values() if isinstance(definition, EncounterDefinition)]
    if len(battlefields) != 1 or len(encounters) != 1:
        from .diagnostics import error

        raise error(
            "COMBAT_GATE1_VERTICAL_SLICE_CARDINALITY",
            "Gate 1 must compile exactly one battlefield and one encounter.",
            phase="GATE1_BUILD",
            subsystem="combat.gate1",
            recommended_action="Remove extra vertical-slice battlefield or encounter definitions.",
            details={"battlefield_count": len(battlefields), "encounter_count": len(encounters)},
        )

    result = Gate1BuildResult(
        registry=registry,
        projections=projections,
        doctrines=doctrines,
        battlefield=battlefields[0],
        encounter=encounters[0],
        diagnostics=(
            CombatDiagnostic(
                code="COMBAT_GATE1_BUILD_COMPLETE",
                severity=DiagnosticSeverity.INFO,
                explanation="Exact packs loaded, references resolved, and deterministic Gate 1 artifacts compiled.",
                phase="GATE1_BUILD",
                subsystem="combat.gate1",
                recommended_action="Review Gate 1 artifacts before authorizing combat resolution.",
                recovery=RecoveryDisposition.CONTINUE,
                details={
                    "pack_count": len(registry.packs),
                    "definition_count": len(registry.definitions),
                    "projection_count": len(projections),
                    "doctrine_count": len(doctrines),
                },
            ),
        ),
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "Registry_Snapshot.json").write_bytes(canonical_bytes(registry.snapshot.model_dump(mode="json")) + b"\n")
        projection_dir = output_dir / "projections"
        doctrine_dir = output_dir / "doctrines"
        projection_dir.mkdir(exist_ok=True)
        doctrine_dir.mkdir(exist_ok=True)
        for mapping_id, projection in projections.items():
            filename = mapping_id.split(":", 1)[1] + ".json"
            (projection_dir / filename).write_bytes(canonical_bytes(projection.model_dump(mode="json")) + b"\n")
        for input_id, doctrine in doctrines.items():
            filename = input_id.split(":", 1)[1] + ".json"
            (doctrine_dir / filename).write_bytes(canonical_bytes(doctrine.model_dump(mode="json")) + b"\n")
        (output_dir / "Battlefield.json").write_bytes(canonical_bytes(result.battlefield.model_dump(mode="json")) + b"\n")
        (output_dir / "Encounter.json").write_bytes(canonical_bytes(result.encounter.model_dump(mode="json")) + b"\n")
        (output_dir / "Diagnostics.json").write_bytes(
            canonical_bytes({"diagnostics": [item.model_dump(mode="json") for item in result.diagnostics]}) + b"\n"
        )
    return result
