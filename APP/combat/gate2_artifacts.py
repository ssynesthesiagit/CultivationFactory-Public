from __future__ import annotations

import argparse
from pathlib import Path

from .canonical import canonical_bytes
from .gate2_profile_coverage import write_runtime_profile_coverage
from .gate2_runtime_models import (
    ActionIntent,
    ActorState,
    CombatEvent,
    LegalCandidate,
    MatchState,
    PendingResolution,
    ReactionDecision,
    RollRecord,
    RuntimeExport,
    ScriptedFight,
    TerminalResult,
    ZoneState,
)
from .gate2a_cli import build_outputs as build_gate2a_outputs


GATE2_RUNTIME_VERSION = "0.2.0-gate2"

_SCHEMA_MODELS = {
    "Gate2_ActionIntent.schema.json": ActionIntent,
    "Gate2_ActorState.schema.json": ActorState,
    "Gate2_CombatEvent.schema.json": CombatEvent,
    "Gate2_LegalCandidate.schema.json": LegalCandidate,
    "Gate2_MatchState.schema.json": MatchState,
    "Gate2_PendingResolution.schema.json": PendingResolution,
    "Gate2_ReactionDecision.schema.json": ReactionDecision,
    "Gate2_RollRecord.schema.json": RollRecord,
    "Gate2_RuntimeExport.schema.json": RuntimeExport,
    "Gate2_ScriptedFight.schema.json": ScriptedFight,
    "Gate2_TerminalResult.schema.json": TerminalResult,
    "Gate2_ZoneState.schema.json": ZoneState,
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def build_gate2_artifacts(output_root: Path) -> dict[str, object]:
    output_root = Path(output_root)
    lock = build_gate2a_outputs(output_root)
    coverage = write_runtime_profile_coverage(
        output_root / "generated" / "Gate2_Executable_Mechanics_Lock.json",
        output_root / "generated" / "Gate2_Runtime_Profile_Coverage.json",
    )
    schema_root = output_root / "generated" / "schemas"
    for filename, model in sorted(_SCHEMA_MODELS.items()):
        _write_json(schema_root / filename, model.model_json_schema(by_alias=True))
    manifest = {
        "schema": "TianxiaGate2GeneratedArtifactManifest.v1",
        "gate2_runtime_version": GATE2_RUNTIME_VERSION,
        "mechanics_lock_sha256": lock.lock_sha256,
        "profile_coverage_status": coverage["status"],
        "profile_count": coverage["profile_count"],
        "runtime_schema_count": len(_SCHEMA_MODELS),
    }
    _write_json(output_root / "generated" / "Gate2_Generated_Artifact_Manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Gate 2 locks, coverage, and runtime schemas.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_gate2_artifacts(args.output)
    print(canonical_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
