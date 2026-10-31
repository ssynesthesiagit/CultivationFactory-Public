from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_sha256
from .diagnostics import RecoveryDisposition, error
from .gate2_engine import Gate2Engine
from .gate2_runtime_models import ActionIntent, LegalCandidate, RuntimeExport, ScriptStep, ScriptedFight


def load_script(path: Path) -> ScriptedFight:
    return ScriptedFight.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def _matches(candidate: LegalCandidate, step: ScriptStep) -> bool:
    return (
        candidate.kind == step.kind
        and candidate.source_definition_id == step.source_definition_id
        and candidate.target_ids == step.target_ids
        and candidate.destination == step.destination
        and all(option in candidate.option_ids for option in step.option_ids)
    )


def execute_script(source_root: Path, script: ScriptedFight) -> tuple[Gate2Engine, list[dict[str, Any]]]:
    engine = Gate2Engine(source_root, match_seed=script.match_seed, maximum_rounds=script.maximum_rounds)
    decisions: list[dict[str, Any]] = []
    for index, step in enumerate(script.steps, start=1):
        if engine.state.terminal_result is not None:
            raise error(
                "GATE2_SCRIPT_HAS_POSTTERMINAL_STEP",
                f"Script step {index} occurs after the match ended.",
                phase="SCRIPT_EXECUTION", subsystem="SCRIPTED_DRIVER",
                entity_id=step.actor_id,
                recommended_action="Remove postterminal script steps.",
            )
        expected_actor_id = engine.state.pending_resolution.actor_id if engine.state.pending_resolution is not None else engine.state.current_actor_id
        if expected_actor_id != step.actor_id:
            raise error(
                "GATE2_SCRIPT_ACTOR_ORDER_MISMATCH",
                f"Script step {index} expects {step.actor_id}, but {expected_actor_id} owns the decision.",
                phase="SCRIPT_EXECUTION", subsystem="SCRIPTED_DRIVER",
                entity_id=step.actor_id,
                recommended_action="Regenerate the script from the exact deterministic initiative order.",
            )
        matches = [candidate for candidate in engine.legal_candidates() if _matches(candidate, step)]
        if len(matches) != 1:
            raise error(
                "GATE2_SCRIPT_CANDIDATE_NOT_UNIQUE",
                f"Script step {index} resolved to {len(matches)} legal candidates instead of exactly one.",
                phase="SCRIPT_EXECUTION", subsystem="SCRIPTED_DRIVER",
                entity_id=step.actor_id,
                source_definition=step.source_definition_id,
                recommended_action="Select an exact legal candidate from the current state.",
                recovery=RecoveryDisposition.STOP,
                details={
                    "step": step.model_dump(mode="json", by_alias=True),
                    "available": [candidate.model_dump(mode="json") for candidate in engine.legal_candidates()],
                },
            )
        candidate = matches[0]
        intent = ActionIntent(
            intent_id=f"intent:script:{index:04d}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            option_ids=step.option_ids,
            reaction_decisions=step.reaction_decisions,
        )
        decisions.append({
            "step_index": index,
            "note": step.note,
            "candidate": candidate.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
        })
        engine.execute_intent(intent)
    if engine.state.terminal_result is None:
        raise error(
            "GATE2_SCRIPT_DID_NOT_TERMINATE",
            "The scripted fight ended without a typed terminal result.",
            phase="SCRIPT_EXECUTION", subsystem="SCRIPTED_DRIVER",
            recommended_action="Add legal manual decisions until victory, simultaneous draw, or duration draw.",
        )
    return engine, decisions


def write_script_outputs(output_dir: Path, script: ScriptedFight, engine: Gate2Engine, decisions: list[dict[str, Any]]) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    export: RuntimeExport = engine.export()
    docs = {
        "Gate2_Scripted_Fight_Input.json": script.model_dump(mode="json", by_alias=True),
        "Gate2_Scripted_Decision_Records.json": {"schema":"TianxiaGate2DecisionRecords.v1","records":decisions},
        "Gate2_Final_State.json": export.final_state,
        "Gate2_Final_Event_Log.json": {"schema":"TianxiaGate2EventLog.v1","events":[event.model_dump(mode="json") for event in export.events]},
        "Gate2_Final_Roll_Log.json": {"schema":"TianxiaGate2RollLog.v1","rolls":[roll.model_dump(mode="json") for roll in export.rolls]},
        "Gate2_Runtime_Export.json": export.model_dump(mode="json", by_alias=True),
    }
    hashes: dict[str, str] = {}
    for name, document in docs.items():
        payload = canonical_bytes(document) + b"\n"
        (output_dir / name).write_bytes(payload)
        hashes[name] = canonical_sha256(document)
    result = {
        "schema":"TianxiaGate2ScriptExecutionResult.v1",
        "status":"PASS",
        "terminal_result": engine.state.terminal_result.model_dump(mode="json") if engine.state.terminal_result else None,
        "event_count": len(engine.events),
        "roll_count": len(engine.rolls),
        "state_version": engine.state.state_version,
        "canonical_state_sha256": export.canonical_state_sha256,
        "canonical_event_log_sha256": export.canonical_event_log_sha256,
        "artifact_hashes": hashes,
    }
    (output_dir / "Gate2_Script_Execution_Result.json").write_bytes(canonical_bytes(result) + b"\n")
    return hashes
