from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical import canonical_sha256
from .gate4_context import build_decision_context
from .gate4_controller import LocalDeterministicController
from .gate4_persistence import Gate4Persistence, Gate4PersistentSession
from .gate4_policy import PolicyLibrary


MEANINGFUL_EVENTS = {
    "MOVEMENT_COMMITTED", "RESOURCE_SPENT", "RESOURCE_GAINED", "DAMAGE_COMMITTED",
    "TEMP_HP_GRANTED", "CONDITION_APPLIED", "CONDITION_REMOVED", "MODIFIER_APPLIED",
    "MODIFIER_REMOVED", "ZONE_CREATED", "ZONE_REMOVED", "CONCENTRATION_STARTED",
    "CONCENTRATION_ENDED", "ENTITY_DEFEATED", "MATCH_ENDED",
}


@dataclass
class NoProgressTracker:
    last_meaningful_sequence: int = 0
    recent_sources: list[str] = field(default_factory=list)
    round_at_last_change: int = 1

    def update(self, session: Gate4PersistentSession, selected_source: str) -> None:
        self.recent_sources.append(selected_source)
        self.recent_sources = self.recent_sources[-8:]
        meaningful = [e for e in session.engine.events if e.event_type in MEANINGFUL_EVENTS]
        if meaningful and meaningful[-1].sequence > self.last_meaningful_sequence:
            self.last_meaningful_sequence = meaningful[-1].sequence
            self.round_at_last_change = session.engine.state.round_number

    def signals(self, session: Gate4PersistentSession) -> tuple[str, ...]:
        rows = []
        if len(self.recent_sources) >= 4 and all(s in {"system:combat.turn", "system:combat.hold_position"} for s in self.recent_sources[-4:]):
            rows.append("REPEATED_HOLD_OR_END")
        if session.engine.state.round_number - self.round_at_last_change >= 3:
            rows.append("THREE_ROUNDS_NO_MECHANICAL_PROGRESS")
        return tuple(rows)


class Gate4AutonomousRunner:
    def __init__(self, source_root: Path, userdata_root: Path):
        self.source_root = Path(source_root)
        self.userdata_root = Path(userdata_root)
        self.persistence = Gate4Persistence(source_root, userdata_root)
        self.controller = LocalDeterministicController()
        self.policies = PolicyLibrary(source_root)

    def run(self, *, match_seed: str, maximum_rounds: int = 20, max_decisions: int = 1000) -> tuple[Gate4PersistentSession, list[dict[str, Any]]]:
        session = self.persistence.create_match(match_seed=match_seed, maximum_rounds=maximum_rounds)
        tracker = NoProgressTracker(round_at_last_change=session.engine.state.round_number)
        decisions: list[dict[str, Any]] = []
        for index in range(1, max_decisions + 1):
            if session.engine.state.terminal_result is not None:
                break
            candidates = session.engine.legal_candidates()
            if not candidates:
                raise RuntimeError("CONTROLLER_NO_LEGAL_CHOICE")
            actor_id = candidates[0].actor_id
            policy, fallback = self.policies.for_actor(actor_id)
            context = build_decision_context(
                session.engine, policy,
                no_progress_signals=tracker.signals(session),
            )
            choice = self.controller.choose_primary_action(context)
            session.execute_controller_choice(
                choice, controller=self.controller, policy_library=self.policies
            )
            decisions.append({
                "decision_index": index,
                "context_sha256": canonical_sha256(context.model_dump(mode="json", by_alias=True)),
                "record": choice.record.model_dump(mode="json", by_alias=True),
                "intent": choice.intent.model_dump(mode="json"),
            })
            selected = next(c for c in candidates if c.candidate_id == choice.intent.candidate_id)
            tracker.update(session, selected.source_definition_id)
        if session.engine.state.terminal_result is None:
            raise RuntimeError("CONTROLLER_NO_PROGRESS_DETECTED")
        return session, decisions
