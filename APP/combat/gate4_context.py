from __future__ import annotations

from typing import Any

from .canonical import canonical_sha256
from .gate2_engine import Gate2Engine
from .gate2_runtime_models import LegalCandidate
from .gate4_models import (
    DecisionContext, LocalControllerPolicy, ReactionContext, TeamBehavior,
    VisibleActor, VisibleZone,
)


def _visible_actor(actor) -> VisibleActor:
    return VisibleActor(
        entity_id=actor.entity_id,
        display_name=actor.display_name,
        team_id=actor.team_id,
        primary_combatant=actor.primary_combatant,
        owner_id=actor.owner_id,
        active=actor.active,
        current_hp=actor.current_hp,
        maximum_hp=actor.maximum_hp,
        temporary_hp=actor.temporary_hp,
        armor_class=actor.armor_class,
        position=actor.position,
        speed_ft=actor.speed_ft,
        movement_remaining_ft=actor.movement_remaining_ft,
        action_available=actor.action_available,
        bonus_action_available=actor.bonus_action_available,
        reaction_available=actor.reaction_available,
        resources=dict(sorted(actor.resources.items())),
        conditions=tuple(sorted(c.condition_id for c in actor.conditions.values())),
        concentration_source_id=(actor.concentration.source_definition_id if actor.concentration else None),
    )


def derive_team_behavior(engine: Gate2Engine, actor_id: str) -> TeamBehavior:
    actor = engine.state.actors[actor_id]
    hostiles = [a for a in engine.state.actors.values() if a.active and a.team_id != actor.team_id]
    primaries = [a for a in hostiles if a.primary_combatant] or hostiles
    focus = min(primaries, key=lambda a: (a.current_hp, a.entity_id), default=None)
    friendly = [a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id]
    enemy_positions = {(a.position.x, a.position.y) for a in hostiles}
    friendly_positions = {(a.position.x, a.position.y) for a in friendly}
    direction = "HOLD"
    if hostiles and friendly:
        avg_enemy_x = sum(x for x, _ in enemy_positions) / len(enemy_positions)
        avg_friend_x = sum(x for x, _ in friendly_positions) / len(friendly_positions)
        if abs(avg_enemy_x - avg_friend_x) > 5:
            direction = "CLOSE"
        elif len(friendly_positions) != len(friendly):
            direction = "SPREAD"
    pressure = bool(focus and focus.current_hp <= max(8, focus.maximum_hp // 4))
    return TeamBehavior(
        focus_target_id=focus.entity_id if focus else None,
        immediate_defeat_pressure=pressure,
        formation_direction=direction,
    )


def build_decision_context(
    engine: Gate2Engine,
    policy: LocalControllerPolicy,
    *,
    recent_event_limit: int = 12,
    no_progress_signals: tuple[str, ...] = (),
) -> DecisionContext:
    raw_candidates = tuple(engine.legal_candidates())
    filtered: list[LegalCandidate] = []
    for candidate in raw_candidates:
        actor = engine.state.actors[candidate.actor_id]
        if candidate.source_definition_id == "action:ling_qi.reflection_cut" and actor.resources.get("resource:ling_qi.mirror_trace", 0) < 1:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.command_cui" and not engine.state.actors.get("bai_cui").active:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.moon_disc_descent" and actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) < 1:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.bloodline_strike" and actor.resources.get("resource:bai_meizhen.ancestral_resonance", 0) < 1:
            continue
        filtered.append(candidate)
    candidates = tuple(filtered)
    if not candidates:
        raise ValueError("CONTROLLER_NO_LEGAL_CHOICE")
    actor_id = candidates[0].actor_id
    decision_ids = {c.decision_id for c in candidates}
    if len(decision_ids) != 1:
        raise ValueError("CONTROLLER_DECISION_CONTEXT_INVALID")
    recent = tuple(e.model_dump(mode="json") for e in engine.events[-recent_event_limit:])
    return DecisionContext(
        match_id=engine.state.match_id,
        state_version=engine.state.state_version,
        decision_id=next(iter(decision_ids)),
        active_actor_id=actor_id,
        round_number=engine.state.round_number,
        current_slot_index=engine.state.current_slot_index,
        actors=tuple(_visible_actor(a) for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)),
        zones=tuple(
            VisibleZone(
                zone_id=z.zone_id,
                source_definition_id=z.source_definition_id,
                owner_id=z.owner_id,
                center=z.center,
                radius_cells=z.radius_cells,
                active=z.active,
            )
            for z in sorted(engine.state.zones.values(), key=lambda z: z.zone_id)
        ),
        legal_candidates=candidates,
        policy=policy,
        team_behavior=derive_team_behavior(engine, actor_id),
        recent_events=recent,
        no_progress_signals=no_progress_signals,
    )


def build_reaction_context(
    engine: Gate2Engine,
    policy: LocalControllerPolicy,
    request: dict[str, Any],
) -> ReactionContext:
    reactor_id = str(request["reactor_id"])
    reactor = engine.state.actors[reactor_id]
    decision_payload = {
        "match_id": engine.state.match_id,
        "state_version": engine.state.state_version,
        "checkpoint": request["checkpoint"],
        "reactor_id": reactor_id,
        "reaction_source_id": request["reaction_source_id"],
        "event_sequence": engine.state.event_sequence,
    }
    return ReactionContext(
        match_id=engine.state.match_id,
        state_version=engine.state.state_version,
        decision_id=f"reaction-decision:{canonical_sha256(decision_payload)[:24]}",
        checkpoint=str(request["checkpoint"]),
        reactor_id=reactor_id,
        protected_target_id=request.get("protected_target_id"),
        damaged_target_id=request.get("damaged_target_id"),
        attacking_actor_id=request.get("attacking_actor_id"),
        reaction_source_id=str(request["reaction_source_id"]),
        provisional_hit=request.get("provisional_hit"),
        pending_damage=request.get("pending_damage"),
        legal_reaction_ids=tuple(request.get("legal_reaction_ids") or (request["reaction_source_id"],)),
        spend_options=tuple(int(v) for v in request.get("spend_options", ())),
        legal_option_ids=tuple(str(v) for v in request.get("legal_option_ids", ())),
        resources=dict(sorted(reactor.resources.items())),
        conditions=tuple(sorted(c.condition_id for c in reactor.conditions.values())),
        policy=policy,
        recent_events=tuple(e.model_dump(mode="json") for e in engine.events[-8:]),
    )


def reject_future_roll_access() -> None:
    from .diagnostics import error
    raise error(
        "CONTROLLER_FUTURE_ROLL_ACCESS_REJECTED",
        "Controller contexts do not expose future rolls or deterministic seed internals.",
        phase="CONTROLLER_CONTEXT", subsystem="GATE4_CONTROLLER",
        recommended_action="Choose only from visible state and legal engine candidates.",
    )
