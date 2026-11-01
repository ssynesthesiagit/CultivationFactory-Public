from __future__ import annotations

from pathlib import Path

from .canonical import canonical_bytes
from .models import (
    CombatRuntimeProjectionEnvelope,
    DefinitionDocument,
    EncounterDefinition,
    InstallationRecordSet,
    PackManifest,
    RegistrySnapshotEnvelope,
    TacticalDoctrineEnvelope,
    BattlefieldDefinition,
)

SCHEMAS = {
    "Pack_Manifest.schema.json": PackManifest,
    "Installation_Records.schema.json": InstallationRecordSet,
    "Definition_Document.schema.json": DefinitionDocument,
    "Registry_Snapshot.schema.json": RegistrySnapshotEnvelope,
    "Combat_Runtime_Projection.schema.json": CombatRuntimeProjectionEnvelope,
    "Tactical_Doctrine.schema.json": TacticalDoctrineEnvelope,
    "Battlefield.schema.json": BattlefieldDefinition,
    "Encounter.schema.json": EncounterDefinition,
}


def export_schemas(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        (destination / filename).write_bytes(canonical_bytes(model.model_json_schema()) + b"\n")
