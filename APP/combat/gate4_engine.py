from __future__ import annotations

from typing import Any, Callable

from .gate2_engine import Gate2Engine
from .gate2_runtime_content import ACTIONS, AN, BAI, LING
from .gate2_runtime_models import ActionIntent, ReactionDecision

ReactionProvider = Callable[[dict[str, Any]], tuple[ReactionDecision | None, dict[str, Any] | None]]


class Gate4ControllerEngine(Gate2Engine):
    """Gate 2 mechanics with a controller-owned checkpoint reaction seam.

    No Gate 2 mutation or legality code is replaced. Scripted embedded reactions
    remain authoritative when present. A configured provider is consulted only
    when the accepted ActionIntent did not embed the exact reaction decision.
    """

    def __init__(self, *args, **kwargs):
        self._gate4_reaction_provider: ReactionProvider | None = None
        self._gate4_reaction_cache: dict[tuple[str, str, str], ReactionDecision | None] = {}
        self.gate4_reaction_decision_records: list[dict[str, Any]] = []
        self._gate4_pending_damage: int | None = None
        self._gate4_damaged_target_id: str | None = None
        super().__init__(*args, **kwargs)

    def set_reaction_provider(self, provider: ReactionProvider | None) -> None:
        self._gate4_reaction_provider = provider

    def execute_intent(self, intent: ActionIntent) -> None:
        self._gate4_reaction_cache = {}
        self.gate4_reaction_decision_records = []
        try:
            super().execute_intent(intent)
        finally:
            self._gate4_pending_damage = None
            self._gate4_damaged_target_id = None

    def _reaction_decision(
        self,
        intent: ActionIntent,
        checkpoint: str,
        reactor_id: str,
        reaction_id: str,
    ) -> ReactionDecision | None:
        embedded = super()._reaction_decision(intent, checkpoint, reactor_id, reaction_id)
        if embedded is not None or self._gate4_reaction_provider is None:
            return embedded
        key = (checkpoint, reactor_id, reaction_id)
        if key in self._gate4_reaction_cache:
            return self._gate4_reaction_cache[key]
        target_id = None
        attacker_id = None
        provisional_hit = None
        if self._active_intent is not None:
            attacker_id = self._active_intent.actor_id
            if self._active_intent.target_ids:
                target_id = self._active_intent.target_ids[0]
        if checkpoint == "DAMAGE_APPLICATION":
            target_id = self._gate4_damaged_target_id or target_id
        if checkpoint == "LEAVE_REACH":
            target_id = intent.actor_id
        if checkpoint == "ATTACK_HIT_BEFORE_DAMAGE":
            provisional_hit = True
        spend_options: list[int] = []
        if reaction_id == "reaction:core.stamina_guard":
            reactor = self.state.actors[reactor_id]
            maximum = min(
                reactor.proficiency_bonus,
                reactor.resources.get("resource:an_eui.stamina", 0),
            )
            spend_options = list(range(1, maximum + 1))
        legal_option_ids: list[str] = []
        if reaction_id == "reaction:bai_meizhen.sea_moon_interposition":
            legal_option_ids = ["DIRECT_CONTEST"]
        elif reaction_id == "reaction:bai_meizhen.spirit_intercession":
            legal_option_ids = ["SPEND_QI"]
        request = {
            "checkpoint": checkpoint,
            "reactor_id": reactor_id,
            "reaction_source_id": reaction_id,
            "protected_target_id": target_id,
            "damaged_target_id": target_id if checkpoint == "DAMAGE_APPLICATION" else None,
            "attacking_actor_id": attacker_id,
            "provisional_hit": provisional_hit,
            "pending_damage": self._gate4_pending_damage,
            "legal_reaction_ids": [reaction_id],
            "spend_options": spend_options,
            "legal_option_ids": legal_option_ids,
        }
        decision, record = self._gate4_reaction_provider(request)
        if decision is not None and (
            decision.checkpoint != checkpoint
            or decision.reactor_id != reactor_id
            or decision.reaction_source_id != reaction_id
        ):
            raise self._intent_error(
                "CONTROLLER_REACTION_CONTEXT_INVALID",
                "The controller returned a reaction for another checkpoint or reactor.",
                intent,
            )
        self._gate4_reaction_cache[key] = decision
        if record is not None:
            self.gate4_reaction_decision_records.append(record)
        return decision


    def _resolve_optional_rider(self, actor, candidate, intent: ActionIntent) -> None:
        # Gate 4 exposes Spark Step to autonomous control. The accepted Gate 2
        # implementation dereferenced a target before entering its targetless
        # Spark Step branch; handle that exact typed rider before delegating.
        if candidate.source_definition_id == "talent:lee_jia.spark_step":
            pending = self.state.pending_resolution
            if pending is None or candidate.source_definition_id not in pending.follow_up_candidates:
                raise self._intent_error(
                    "GATE2_OPTIONAL_RIDER_WINDOW_CLOSED",
                    "The optional rider trigger window is closed.", intent,
                )
            if candidate.destination is None:
                raise self._intent_error(
                    "GATE2_SPARK_STEP_DESTINATION_REQUIRED",
                    "Spark Step requires an offered destination.", intent,
                )
            ignored = intent.option_ids[0] if intent.option_ids else None
            if ignored:
                actor.turn_flags["spark_step_ignore_oa_from"] = ignored
            actor.movement_remaining_ft += candidate.movement_cost_ft
            self._resolve_movement(actor, candidate, intent)
            actor.turn_flags.pop("spark_step_ignore_oa_from", None)
            self._complete_follow_up(candidate.source_definition_id)
            return
        super()._resolve_optional_rider(actor, candidate, intent)

    def _resolve_damage_reaction(
        self,
        target,
        pending: int,
        intent: ActionIntent,
        reaction_depth: int,
    ) -> int:
        self._gate4_pending_damage = pending
        self._gate4_damaged_target_id = target.entity_id
        try:
            return super()._resolve_damage_reaction(target, pending, intent, reaction_depth)
        finally:
            self._gate4_pending_damage = None
            self._gate4_damaged_target_id = None
