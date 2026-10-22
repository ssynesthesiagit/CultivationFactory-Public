from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_sha256
from .gate2_runtime_models import ActionIntent
from .gate4_models import (
    ControllerChoice,
    DecisionContext,
    DecisionRecord,
    LocalControllerPolicy,
    ReactionChoice,
    ReactionContext,
)
from .gate4_policy import FALLBACK_FILENAME, POLICY_FILENAMES, PolicyLibrary


GATE4_CONTROLLER_VERSION = "0.4.0-gate4"

_SCHEMA_MODELS = {
    "ActionIntent.schema.json": ActionIntent,
    "ControllerChoice.schema.json": ControllerChoice,
    "DecisionContext.schema.json": DecisionContext,
    "DecisionRecord.schema.json": DecisionRecord,
    "LocalControllerPolicy.schema.json": LocalControllerPolicy,
    "ReactionChoice.schema.json": ReactionChoice,
    "ReactionContext.schema.json": ReactionContext,
}

_DIAGNOSTICS = (
    (
        "CONTROLLER_POLICY_MISSING_USING_FALLBACK",
        "CONTINUE",
        "Install a bespoke typed policy or continue with the explicit generic fallback.",
    ),
    (
        "CONTROLLER_POLICY_INVALID",
        "STOP",
        "Correct the typed policy file and retry the same decision.",
    ),
    (
        "CONTROLLER_NO_LEGAL_CHOICE",
        "STOP",
        "Inspect engine candidate generation; do not fabricate an action.",
    ),
    (
        "CONTROLLER_OPTION_EXPANSION_LIMIT",
        "STOP",
        "Raise the documented option guard or simplify the content options.",
    ),
    (
        "CONTROLLER_REACTION_CONTEXT_INVALID",
        "STOP",
        "Rebuild the reaction decision from the current checkpoint context.",
    ),
    (
        "CONTROLLER_DECISION_NONDETERMINISTIC",
        "STOP",
        "Restore the exact policy and pre-state before retrying recovery.",
    ),
    (
        "CONTROLLER_FUTURE_ROLL_ACCESS_REJECTED",
        "REJECT",
        "Choose only from visible state and engine-issued legal candidates.",
    ),
    (
        "CONTROLLER_NO_PROGRESS_DETECTED",
        "CONTINUE",
        "Apply deterministic pressure to change action family or reposition.",
    ),
)


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(document) + b"\n")


def diagnostics_inventory_document() -> dict[str, Any]:
    return {
        "schema": "TianxiaGate4ControllerDiagnosticsInventory.v1",
        "diagnostic_count": len(_DIAGNOSTICS),
        "diagnostics": [
            {
                "code": code,
                "disposition": disposition,
                "recommended_action": action,
            }
            for code, disposition, action in _DIAGNOSTICS
        ],
        "scope": "ordinary local controller selection, persistence, and diagnostics",
        "certification_artifact": False,
    }


def _policy_source_row(source_root: Path, policy: LocalControllerPolicy) -> dict[str, Any]:
    if policy.generic_fallback:
        return {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "generic_fallback": True,
            "source_doctrine_id": None,
            "source_doctrine_sha256": None,
            "source_projection_sha256": None,
            "authority_status": "FALLBACK_NO_CHARACTER_AUTHORITY",
        }
    actor_id = policy.actor_id
    if actor_id is None:
        raise ValueError("CONTROLLER_POLICY_INVALID")
    doctrine_path = source_root / "combat_gate1/generated/doctrines" / f"{actor_id}.json"
    projection_path = source_root / "combat_gate1/generated/projections" / f"{actor_id}.json"
    doctrine = json.loads(doctrine_path.read_text(encoding="utf-8"))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    doctrine_document = doctrine.get("doctrine", doctrine)
    if doctrine_document.get("doctrine_id") != policy.source_doctrine_id:
        raise ValueError("CONTROLLER_POLICY_INVALID")
    if doctrine.get("doctrine_sha256") != policy.source_doctrine_sha256:
        raise ValueError("CONTROLLER_POLICY_INVALID")
    if projection.get("projection_sha256") != policy.source_projection_sha256:
        raise ValueError("CONTROLLER_POLICY_INVALID")
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "actor_id": actor_id,
        "generic_fallback": False,
        "source_doctrine_id": policy.source_doctrine_id,
        "source_doctrine_sha256": policy.source_doctrine_sha256,
        "source_projection_sha256": policy.source_projection_sha256,
        "doctrine_path": doctrine_path.relative_to(source_root).as_posix(),
        "projection_path": projection_path.relative_to(source_root).as_posix(),
        "authority_status": "PASS",
    }


def policy_identity_inventory(source_root: Path) -> dict[str, Any]:
    source_root = Path(source_root)
    library = PolicyLibrary(source_root)
    filenames = sorted(set(POLICY_FILENAMES.values()) | {FALLBACK_FILENAME})
    rows = []
    for filename in filenames:
        policy = library._load(filename)
        rows.append(
            {
                **_policy_source_row(source_root, policy),
                "filename": filename,
                "policy_sha256": canonical_sha256(
                    policy.model_dump(mode="json", by_alias=True)
                ),
            }
        )
    return {
        "schema": "TianxiaGate4PolicyIdentityInventory.v1",
        "status": "PASS",
        "policy_count": len(rows),
        "bespoke_policy_count": sum(not row["generic_fallback"] for row in rows),
        "fallback_policy_count": sum(row["generic_fallback"] for row in rows),
        "policies": rows,
        "runtime_doctrine_prose_interpretation": False,
    }


def controller_interface_descriptor() -> dict[str, Any]:
    return {
        "schema": "TianxiaGate4ControllerInterfaceDescriptor.v1",
        "controller_methods": {
            "choose_primary_action": {
                "input": "TianxiaDecisionContext.v1",
                "output": "ControllerChoice(ActionIntent + DecisionRecord)",
            },
            "choose_reaction": {
                "input": "TianxiaReactionContext.v1",
                "output": "ReactionChoice(ReactionDecision + DecisionRecord)",
            },
        },
        "mechanical_authority": "Gate 2 engine legal candidates and ActionIntent validation",
        "persistence_authority": "Gate 3 mechanical journal and typed reducer",
        "future_adapters": [
            "manual UI",
            "combat API",
            "manual AI bridge",
            "hosted AI provider",
            "local AI provider",
            "additional deterministic controllers",
        ],
        "arbitrary_state_mutation_supported": False,
        "future_roll_access_supported": False,
    }


def build_gate4_artifacts(source_root: Path, output_root: Path) -> dict[str, Any]:
    source_root = Path(source_root)
    output_root = Path(output_root)
    generated = output_root / "generated"
    schema_root = generated / "schemas"

    schema_hashes: dict[str, str] = {}
    for filename, model in sorted(_SCHEMA_MODELS.items()):
        schema = model.model_json_schema(by_alias=True)
        _write_json(schema_root / filename, schema)
        schema_hashes[filename] = canonical_sha256(schema)

    diagnostics = diagnostics_inventory_document()
    policies = policy_identity_inventory(source_root)
    interface = controller_interface_descriptor()
    _write_json(generated / "Gate4_Controller_Diagnostics_Inventory.json", diagnostics)
    _write_json(generated / "Gate4_Policy_Identity_Inventory.json", policies)
    _write_json(generated / "Gate4_Controller_Interface_Descriptor.json", interface)

    manifest = {
        "schema": "TianxiaGate4GeneratedArtifactManifest.v1",
        "gate4_controller_version": GATE4_CONTROLLER_VERSION,
        "runtime_schema_count": len(_SCHEMA_MODELS),
        "runtime_schema_sha256": dict(sorted(schema_hashes.items())),
        "policy_count": policies["policy_count"],
        "diagnostic_count": diagnostics["diagnostic_count"],
        "controller_interface_sha256": canonical_sha256(interface),
        "policy_inventory_sha256": canonical_sha256(policies),
        "same_action_intent_authority_for_all_controllers": True,
        "gate2_mechanical_mutation_authority_preserved": True,
        "gate3_replay_ignores_controller_reasoning": True,
        "full_ui_api_ai_integrations_implemented": False,
    }
    _write_json(generated / "Gate4_Generated_Artifact_Manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Gate 4 controller schemas and identity artifacts."
    )
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_gate4_artifacts(args.source_root, args.output)
    print(canonical_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
