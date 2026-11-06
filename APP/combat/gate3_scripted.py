from __future__ import annotations

from pathlib import Path
from typing import Any

from .gate2_runtime_models import ActionIntent
from .gate2_scripted import _matches, load_script
from .gate3_storage import Gate3Persistence, PersistentMatchSession


def execute_persistent_script(
    source_root: Path,
    userdata_root: Path,
    script_path: Path,
) -> tuple[PersistentMatchSession, list[dict[str, Any]]]:
    script = load_script(script_path)
    persistence = Gate3Persistence(source_root, userdata_root)
    session = persistence.create_match(
        match_seed=script.match_seed, maximum_rounds=script.maximum_rounds
    )
    decisions: list[dict[str, Any]] = []
    for index, step in enumerate(script.steps, start=1):
        matches = [
            candidate
            for candidate in session.engine.legal_candidates()
            if _matches(candidate, step)
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"persistent script step {index} resolved to {len(matches)} candidates"
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
        decisions.append(
            {
                "step_index": index,
                "note": step.note,
                "candidate": candidate.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
            }
        )
        session.execute_intent(intent)
    if session.engine.state.terminal_result is None:
        raise RuntimeError("persistent script did not reach a terminal result")
    return session, decisions
