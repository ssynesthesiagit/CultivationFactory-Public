from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .canonical import canonical_sha256
from .gate2_runtime_models import ActionIntent, LegalCandidate, ReactionDecision, ScriptStep
from .gate2_scripted import _matches
from .gate4_models import (
    CandidateScore, ComponentScore, ControllerChoice, DecisionContext,
    DecisionRecord, ReactionChoice, ReactionContext,
)


class ManualControllerAdapter:
    """Future UI/API seam: a chooser sees immutable context and returns IDs only."""
    controller_id = "controller:manual.adapter"
    controller_version = "1.0.0"

    def __init__(self, chooser: Callable[[DecisionContext], tuple[str, tuple[str, ...]]], reaction_chooser: Callable[[ReactionContext], ReactionDecision] | None = None):
        self.chooser = chooser
        self.reaction_chooser = reaction_chooser

    def choose_primary_action(self, context: DecisionContext) -> ControllerChoice:
        candidate_id, option_ids = self.chooser(context)
        candidate = next((c for c in context.legal_candidates if c.candidate_id == candidate_id), None)
        if candidate is None or any(o not in candidate.option_ids for o in option_ids):
            raise ValueError("GATE2_STALE_OR_ILLEGAL_CANDIDATE")
        intent = ActionIntent(
            intent_id=f"intent:manual:{canonical_sha256({'decision':context.decision_id,'candidate':candidate_id,'options':option_ids})[:24]}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination,
            option_ids=option_ids, reaction_decisions=(),
        )
        score = CandidateScore(candidate_id=candidate_id, option_ids=option_ids, total=0, components=(ComponentScore(component="manual_selection",value=0,explanation="Selected by external manual adapter."),))
        record = DecisionRecord(
            controller_id=self.controller_id,controller_version=self.controller_version,
            policy_id=context.policy.policy_id,policy_version=context.policy.policy_version,
            decision_id=context.decision_id,actor_id=candidate.actor_id,state_version=context.state_version,
            decision_kind="PRIMARY",legal_alternatives=tuple(sorted(c.candidate_id for c in context.legal_candidates)),
            scored_alternatives=(score,),selected_candidate_id=candidate_id,selected_option_ids=option_ids,
            deterministic_tie_break="manual selection",explanation="Manual adapter submitted an engine-issued candidate.",
            fallback_policy_used=context.policy.generic_fallback,
        )
        return ControllerChoice(intent=intent,record=record)

    def choose_reaction(self, context: ReactionContext) -> ReactionChoice:
        decision = self.reaction_chooser(context) if self.reaction_chooser else ReactionDecision(
            checkpoint=context.checkpoint,reactor_id=context.reactor_id,
            reaction_source_id=context.reaction_source_id,selection="DECLINE",
        )
        record = DecisionRecord(
            controller_id=self.controller_id,controller_version=self.controller_version,
            policy_id=context.policy.policy_id,policy_version=context.policy.policy_version,
            decision_id=context.decision_id,actor_id=context.reactor_id,state_version=context.state_version,
            decision_kind="REACTION",legal_alternatives=("DECLINE","USE"),scored_alternatives=(),
            selected_candidate_id=f"reaction:{decision.reaction_source_id}:{decision.selection}",
            selected_option_ids=decision.option_ids,selected_reaction=decision,
            deterministic_tie_break="manual selection",explanation="Manual reaction adapter submitted a legal checkpoint decision.",
            fallback_policy_used=context.policy.generic_fallback,
        )
        return ReactionChoice(decision=decision,record=record)


class ScriptControllerAdapter:
    """Compatibility adapter for the accepted Gate 2 scripted path."""
    controller_id = "controller:script.compatibility"
    controller_version = "1.0.0"

    def __init__(self, steps: tuple[ScriptStep, ...]):
        self.steps = steps
        self.index = 0

    def choose_primary_action(self, context: DecisionContext) -> ControllerChoice:
        if self.index >= len(self.steps):
            raise ValueError("GATE2_SCRIPT_DID_NOT_TERMINATE")
        step = self.steps[self.index]
        matches = [c for c in context.legal_candidates if _matches(c, step)]
        if len(matches) != 1:
            raise ValueError("GATE2_SCRIPT_CANDIDATE_NOT_UNIQUE")
        candidate = matches[0]
        self.index += 1
        intent = ActionIntent(
            intent_id=f"intent:script-adapter:{self.index:04d}",decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,destination=candidate.destination,option_ids=step.option_ids,
            reaction_decisions=step.reaction_decisions,
        )
        record = DecisionRecord(
            controller_id=self.controller_id,controller_version=self.controller_version,
            policy_id=context.policy.policy_id,policy_version=context.policy.policy_version,
            decision_id=context.decision_id,actor_id=candidate.actor_id,state_version=context.state_version,
            decision_kind="PRIMARY",legal_alternatives=tuple(sorted(c.candidate_id for c in context.legal_candidates)),
            scored_alternatives=(),selected_candidate_id=candidate.candidate_id,selected_option_ids=step.option_ids,
            deterministic_tie_break="script step order",explanation=step.note or "Accepted scripted compatibility step.",
            fallback_policy_used=context.policy.generic_fallback,
        )
        return ControllerChoice(intent=intent,record=record)

    def choose_reaction(self, context: ReactionContext) -> ReactionChoice:
        decision = ReactionDecision(checkpoint=context.checkpoint,reactor_id=context.reactor_id,reaction_source_id=context.reaction_source_id,selection="DECLINE")
        record = DecisionRecord(
            controller_id=self.controller_id,controller_version=self.controller_version,
            policy_id=context.policy.policy_id,policy_version=context.policy.policy_version,
            decision_id=context.decision_id,actor_id=context.reactor_id,state_version=context.state_version,
            decision_kind="REACTION",legal_alternatives=("DECLINE",),scored_alternatives=(),
            selected_candidate_id=f"reaction:{context.reaction_source_id}:DECLINE",selected_option_ids=(),selected_reaction=decision,
            deterministic_tie_break="embedded scripted reactions remain on ActionIntent",explanation="No external reaction; embedded script compatibility is unchanged.",
            fallback_policy_used=context.policy.generic_fallback,
        )
        return ReactionChoice(decision=decision,record=record)
