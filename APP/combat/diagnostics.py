from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class RecoveryDisposition(StrEnum):
    CONTINUE = "CONTINUE"
    RETRY = "RETRY"
    STOP = "STOP"


class CombatDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=3)
    severity: DiagnosticSeverity
    explanation: str = Field(min_length=1)
    entity_id: str | None = None
    phase: str
    subsystem: str
    source_definition: str | None = None
    recommended_action: str
    recovery: RecoveryDisposition
    details: dict[str, Any] = Field(default_factory=dict)


class CombatGate1Error(Exception):
    def __init__(self, diagnostic: CombatDiagnostic):
        super().__init__(diagnostic.explanation)
        self.diagnostic = diagnostic

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.diagnostic.model_dump(mode="json")}


def error(
    code: str,
    explanation: str,
    *,
    phase: str,
    subsystem: str,
    entity_id: str | None = None,
    source_definition: str | None = None,
    recommended_action: str,
    recovery: RecoveryDisposition = RecoveryDisposition.STOP,
    details: dict[str, Any] | None = None,
) -> CombatGate1Error:
    return CombatGate1Error(
        CombatDiagnostic(
            code=code,
            severity=DiagnosticSeverity.ERROR,
            explanation=explanation,
            entity_id=entity_id,
            phase=phase,
            subsystem=subsystem,
            source_definition=source_definition,
            recommended_action=recommended_action,
            recovery=recovery,
            details=details or {},
        )
    )
