from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from .diagnostics import CombatGate1Error, RecoveryDisposition, error
from .models import StrictModel


class RollRecord(StrictModel):
    roll_id: str
    counter: int = Field(ge=0)
    expression: Literal["1d10"]
    actor_id: str
    reason: Literal["STAMINA_GUARD_REDUCTION"]
    die: int = Field(ge=1, le=10)
    total: int = Field(ge=1, le=10)


class PendingDamagePacket(StrictModel):
    transaction_id: str
    packet_id: str
    source_definition_id: str
    actor_id: str
    target_id: str
    amount: int = Field(ge=0)
    state_version: int = Field(ge=0)
    checkpoint_id: Literal["DAMAGE_APPLICATION"]
    reaction_depth: int = Field(ge=0, le=2)


class StaminaGuardDecision(StrictModel):
    decision_id: str
    packet_id: str
    state_version: int = Field(ge=0)
    selection: Literal["DECLINE", "SPEND"]
    spend: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_selection(self) -> "StaminaGuardDecision":
        if self.selection == "DECLINE" and self.spend != 0:
            raise ValueError("decline must spend zero Stamina")
        if self.selection == "SPEND" and self.spend < 1:
            raise ValueError("SPEND requires at least one Stamina")
        return self


class StaminaGuardCandidateSet(StrictModel):
    decision_id: str
    packet_id: str
    state_version: int
    spend_options: tuple[int, ...]
    decline_available: Literal[True] = True


class SpikeEvent(StrictModel):
    sequence: int = Field(ge=1)
    event_type: Literal[
        "REACTION_WINDOW_OPENED",
        "REACTION_DECLINED",
        "RESOURCE_SPENT",
        "REDUCTION_ROLLED",
        "REACTION_RESOLVED",
        "DAMAGE_COMMITTED",
    ]
    source_definition_id: str
    transaction_id: str
    actor_id: str
    target_id: str
    payload: dict


class StaminaGuardResult(StrictModel):
    decision_id: str
    packet_id: str
    original_damage: int
    stamina_before: int
    stamina_after: int
    spend: int
    reduction_rolls: tuple[RollRecord, ...]
    reduction_total: int
    committed_damage: int
    events: tuple[SpikeEvent, ...]


class DeterministicD10Authority:
    """Small platform-stable counter roller used only by the Gate 2A spike."""

    def __init__(self, seed: str, counter: int = 0):
        if not seed:
            raise ValueError("seed must not be empty")
        if counter < 0:
            raise ValueError("counter must be nonnegative")
        self.seed = seed.encode("utf-8")
        self.counter = counter

    def roll_d10(self, actor_id: str) -> RollRecord:
        counter = self.counter
        block_index = 0
        # 250 is the largest multiple-of-10 range below 256; reject 250..255.
        while True:
            material = self.seed + b"\0" + counter.to_bytes(8, "big") + block_index.to_bytes(4, "big")
            digest = hashlib.sha256(material).digest()
            accepted = next((value for value in digest if value < 250), None)
            if accepted is not None:
                die = accepted % 10 + 1
                break
            block_index += 1
        self.counter += 1
        return RollRecord(
            roll_id=f"roll:stamina_guard:{counter:08d}",
            counter=counter,
            expression="1d10",
            actor_id=actor_id,
            reason="STAMINA_GUARD_REDUCTION",
            die=die,
            total=die,
        )


@dataclass
class StaminaGuardSpike:
    roller: DeterministicD10Authority

    def __post_init__(self) -> None:
        self._consumed_decision_ids: set[str] = set()

    @staticmethod
    def candidates(packet: PendingDamagePacket, *, current_stamina: int, proficiency_bonus: int) -> StaminaGuardCandidateSet:
        if current_stamina < 0 or proficiency_bonus < 1:
            raise ValueError("resource and PB values are invalid")
        maximum = min(current_stamina, proficiency_bonus)
        return StaminaGuardCandidateSet(
            decision_id=f"decision:stamina_guard:{packet.packet_id}:{packet.state_version}",
            packet_id=packet.packet_id,
            state_version=packet.state_version,
            spend_options=tuple(range(1, maximum + 1)),
        )

    def resolve(
        self,
        packet: PendingDamagePacket,
        decision: StaminaGuardDecision,
        *,
        current_stamina: int,
        proficiency_bonus: int,
    ) -> StaminaGuardResult:
        candidates = self.candidates(packet, current_stamina=current_stamina, proficiency_bonus=proficiency_bonus)
        if decision.decision_id in self._consumed_decision_ids:
            raise error(
                "COMBAT_GATE2_REACTION_ALREADY_CONSUMED",
                "This Stamina Guard decision was already resolved; duplicate spending is rejected.",
                phase="GATE2A_STAMINA_GUARD",
                subsystem="REACTION_SPIKE",
                entity_id=packet.target_id,
                source_definition="reaction:core.stamina_guard",
                recommended_action="Use the current open reaction decision only once.",
                recovery=RecoveryDisposition.STOP,
            )
        if decision.decision_id != candidates.decision_id or decision.packet_id != packet.packet_id or decision.state_version != packet.state_version:
            raise error(
                "COMBAT_GATE2_STALE_REACTION_DECISION",
                "The Stamina Guard response does not bind the current pending damage packet and state version.",
                phase="GATE2A_STAMINA_GUARD",
                subsystem="REACTION_SPIKE",
                entity_id=packet.target_id,
                source_definition="reaction:core.stamina_guard",
                recommended_action="Regenerate reaction candidates from the current pending packet.",
                recovery=RecoveryDisposition.RETRY,
            )
        if packet.reaction_depth >= 2:
            raise error(
                "COMBAT_GATE2_REACTION_DEPTH_EXCEEDED",
                "The bounded reaction depth is exhausted.",
                phase="GATE2A_STAMINA_GUARD",
                subsystem="REACTION_SPIKE",
                entity_id=packet.target_id,
                source_definition="reaction:core.stamina_guard",
                recommended_action="Close the current reaction chain without opening another defensive reaction.",
                recovery=RecoveryDisposition.STOP,
            )
        if decision.selection == "SPEND" and decision.spend not in candidates.spend_options:
            raise error(
                "COMBAT_GATE2_INVALID_STAMINA_GUARD_SPEND",
                "The selected Stamina amount is not one of the legal 1..min(PB,current Stamina) options.",
                phase="GATE2A_STAMINA_GUARD",
                subsystem="REACTION_SPIKE",
                entity_id=packet.target_id,
                source_definition="reaction:core.stamina_guard",
                recommended_action="Choose one of the emitted spend options or decline.",
                recovery=RecoveryDisposition.RETRY,
                details={"legal_spend_options": list(candidates.spend_options)},
            )

        seq = 1
        events = [SpikeEvent(
            sequence=seq,
            event_type="REACTION_WINDOW_OPENED",
            source_definition_id="reaction:core.stamina_guard",
            transaction_id=packet.transaction_id,
            actor_id=packet.target_id,
            target_id=packet.target_id,
            payload={"packet_id": packet.packet_id, "spend_options": list(candidates.spend_options)},
        )]
        seq += 1
        rolls: list[RollRecord] = []
        spend = decision.spend if decision.selection == "SPEND" else 0
        if decision.selection == "DECLINE":
            events.append(SpikeEvent(
                sequence=seq,
                event_type="REACTION_DECLINED",
                source_definition_id="reaction:core.stamina_guard",
                transaction_id=packet.transaction_id,
                actor_id=packet.target_id,
                target_id=packet.target_id,
                payload={"packet_id": packet.packet_id},
            ))
            seq += 1
        else:
            events.append(SpikeEvent(
                sequence=seq,
                event_type="RESOURCE_SPENT",
                source_definition_id="reaction:core.stamina_guard",
                transaction_id=packet.transaction_id,
                actor_id=packet.target_id,
                target_id=packet.target_id,
                payload={"resource_id": "resource:an_eui.stamina", "amount": spend},
            ))
            seq += 1
            for _ in range(spend):
                roll = self.roller.roll_d10(packet.target_id)
                rolls.append(roll)
                events.append(SpikeEvent(
                    sequence=seq,
                    event_type="REDUCTION_ROLLED",
                    source_definition_id="reaction:core.stamina_guard",
                    transaction_id=packet.transaction_id,
                    actor_id=packet.target_id,
                    target_id=packet.target_id,
                    payload=roll.model_dump(mode="json"),
                ))
                seq += 1
        reduction_total = sum(roll.total for roll in rolls)
        committed_damage = max(0, packet.amount - reduction_total)
        events.append(SpikeEvent(
            sequence=seq,
            event_type="REACTION_RESOLVED",
            source_definition_id="reaction:core.stamina_guard",
            transaction_id=packet.transaction_id,
            actor_id=packet.target_id,
            target_id=packet.target_id,
            payload={"spend": spend, "reduction_total": reduction_total},
        ))
        seq += 1
        events.append(SpikeEvent(
            sequence=seq,
            event_type="DAMAGE_COMMITTED",
            source_definition_id=packet.source_definition_id,
            transaction_id=packet.transaction_id,
            actor_id=packet.actor_id,
            target_id=packet.target_id,
            payload={"original_damage": packet.amount, "committed_damage": committed_damage},
        ))
        self._consumed_decision_ids.add(decision.decision_id)
        return StaminaGuardResult(
            decision_id=decision.decision_id,
            packet_id=packet.packet_id,
            original_damage=packet.amount,
            stamina_before=current_stamina,
            stamina_after=current_stamina - spend,
            spend=spend,
            reduction_rolls=tuple(rolls),
            reduction_total=reduction_total,
            committed_damage=committed_damage,
            events=tuple(events),
        )
