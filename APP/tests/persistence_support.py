"""Small test helpers for current saved-data integrity and committed turns."""
from hashlib import sha256
from pathlib import Path

from combat.gate2_runtime_models import ActionIntent


def inventory(root: Path) -> dict[str, str]:
    """Snapshot saved file bytes so a read-only test can detect an accidental write."""
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def end_turn(session) -> None:
    """Commit an offered END_TURN through the ordinary persistent-session path."""
    candidate = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
    intent = ActionIntent(
        intent_id=f"test:{session.engine.state.state_version}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids,
    )
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
