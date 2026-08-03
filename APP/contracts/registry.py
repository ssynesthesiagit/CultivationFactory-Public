from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


@dataclass(frozen=True)
class ContractDiagnostic:
    pointer: str
    schema_pointer: str
    validator: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "pointer": self.pointer,
            "schema_pointer": self.schema_pointer,
            "validator": self.validator,
            "message": self.message,
        }


class ContractValidationError(ValueError):
    def __init__(self, schema_version: str, diagnostics: list[ContractDiagnostic]):
        super().__init__(f"Object does not validate against {schema_version}")
        self.schema_version = schema_version
        self.diagnostics = diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "CANONICAL_SCHEMA_VALIDATION_FAILED",
            "schema_version": self.schema_version,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def _pointer(parts: list[Any]) -> str:
    if not parts:
        return ""
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class SchemaRegistry:
    """Pinned, local-only runtime JSON Schema registry.

    The registry never resolves network references. Every canonical runtime object is
    selected by its explicit schema/protocol version and validated at the application
    boundary that reads or writes it.
    """

    VERSION_TO_FILE = {
        "TianxiaFoundry.CharacterProject.v1": "Character_Project.schema.json",
        "TianxiaFoundry.AdvancementEvent.v1": "Advancement_Event.schema.json",
        "TianxiaFoundry.AdvancementEvent.v2": "Advancement_Event_v2.schema.json",
        "TianxiaFoundry.AdvancementEvent.v3": "Advancement_Event_v3.schema.json",
        "TianxiaFoundry.RulesCatalogRecord.v1": "Rules_Catalog_Record.schema.json",
        "TianxiaFoundry.ContentPackManifest.v1": "Content_Pack_Manifest.schema.json",
        "TianxiaFoundry.ContentPackSignature.v1": "Content_Pack_Signature.schema.json",
        "TianxiaFoundry.FoundationReplacementMap.v1": "Foundation_Replacement_Map.schema.json",
        "TianxiaFoundry.AIClipboard.v1": "AI_Stage_Response.schema.json",
        "TianxiaFoundry.ServiceContracts.v1": "Service_API_Contracts.schema.json",
        "TianxiaFoundry.ServiceError.v1": "Service_Error.schema.json",
        "TianxiaFoundry.Stage1PromptEnvelope.v1": "Stage1_Prompt_Envelope.schema.json",
        "TianxiaFoundry.AIClipboard.Stage1.v1": "Stage1_Clipboard_Response.schema.json",
        "TianxiaFoundry.Stage1ClipboardExchange.v1": "Stage1_Clipboard_Exchange.schema.json",
        "TianxiaFoundry.Stage1PromptEnvelope.v2": "Stage1_Prompt_Envelope_v2.schema.json",
        "TianxiaFoundry.AIClipboard.Stage1.v2": "Stage1_Clipboard_Response_v2.schema.json",
        "TianxiaFoundry.Stage1ClipboardExchange.v2": "Stage1_Clipboard_Exchange_v2.schema.json",
        "TianxiaFoundry.BlueprintDecision.v1": "Blueprint_Decision.schema.json",
        "TianxiaFoundry.BlueprintDecisionBatch.v1": "Blueprint_Decision_Batch.schema.json",
        "TianxiaFoundry.BlueprintIntentState.v1": "Blueprint_Intent_State.schema.json",
        "TianxiaFoundry.Stage2AdvancementProposal.v1": "Stage2_Advancement_Proposal.schema.json",
        "TianxiaFoundry.Stage2AdvancementProposal.v2": "Stage2_Advancement_Proposal_v2.schema.json",
        "TianxiaFoundry.LevelingLedger.v1": "Leveling_Ledger_v1.schema.json",
        "TianxiaFoundry.LevelingLedger.v2": "Leveling_Ledger_v2.schema.json",
        "TianxiaFoundry.Stage2TrainingTransaction.v1": "Stage2_Training_Transaction_v1.schema.json",
        "TianxiaFoundry.Stage2TrainingTransaction.v2": "Stage2_Training_Transaction.schema.json",
        "TianxiaFoundry.SafeFormula.v1": "Stage2_Safe_Formula.schema.json",
        "TianxiaFoundry.ProjectForgedTechnique.v1": "Project_Scoped_Forged_Technique.schema.json",
        "TianxiaFoundry.Stage2BlockerReport.v1": "Stage2_Blocker_Report.schema.json",
        "TianxiaFoundry.Stage2ReconciliationReport.v1": "Stage2_Reconciliation_Report.schema.json",
        "TianxiaFoundry.Stage2FieldProvenanceMap.v1": "Stage2_Field_Provenance_Map.schema.json",
    }

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self.schema_dir = self.root_dir / "schemas"
        self._schemas: dict[str, dict[str, Any]] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        for version, filename in self.VERSION_TO_FILE.items():
            path = self.schema_dir / filename
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self._schemas[version] = schema
            self._validators[version] = Draft202012Validator(schema, format_checker=FormatChecker())

    def versions(self) -> list[str]:
        return sorted(self._schemas)

    def status(self) -> dict[str, Any]:
        return {
            "registry_version": "TianxiaFoundry.SchemaRegistry.v1",
            "network_resolution": False,
            "schema_count": len(self._schemas),
            "schemas": [
                {
                    "schema_version": version,
                    "file": self.VERSION_TO_FILE[version],
                    "$id": self._schemas[version].get("$id"),
                    "title": self._schemas[version].get("title"),
                }
                for version in self.versions()
            ],
        }

    def schema(self, version: str) -> dict[str, Any]:
        if version not in self._schemas:
            raise KeyError(version)
        return self._schemas[version]

    @staticmethod
    def object_version(obj: dict[str, Any]) -> str:
        value = obj.get("schema_version") or obj.get("protocol_version")
        if not isinstance(value, str) or not value:
            raise ContractValidationError(
                "UNKNOWN",
                [ContractDiagnostic("", "", "schema_version", "No schema_version or protocol_version is declared.")],
            )
        return value

    def diagnostics(self, obj: dict[str, Any], version: str | None = None) -> list[ContractDiagnostic]:
        chosen = version or self.object_version(obj)
        validator = self._validators.get(chosen)
        if validator is None:
            return [
                ContractDiagnostic(
                    "/schema_version" if "schema_version" in obj else "/protocol_version",
                    "",
                    "known-schema-version",
                    f"Unknown schema version: {chosen}",
                )
            ]
        errors = sorted(validator.iter_errors(obj), key=lambda e: (list(e.absolute_path), e.message))
        return [
            ContractDiagnostic(
                _pointer(list(error.absolute_path)),
                _pointer(list(error.absolute_schema_path)),
                str(error.validator),
                error.message,
            )
            for error in errors
        ]

    def validate(self, obj: dict[str, Any], version: str | None = None) -> dict[str, Any]:
        chosen = version or self.object_version(obj)
        diagnostics = self.diagnostics(obj, chosen)
        if diagnostics:
            raise ContractValidationError(chosen, diagnostics)
        return obj

    def report(self, obj: dict[str, Any], version: str | None = None) -> dict[str, Any]:
        chosen = version or self.object_version(obj)
        diagnostics = self.diagnostics(obj, chosen)
        return {
            "schema_version": chosen,
            "valid": not diagnostics,
            "diagnostics": [d.to_dict() for d in diagnostics],
        }
