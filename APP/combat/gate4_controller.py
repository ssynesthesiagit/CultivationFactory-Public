from __future__ import annotations

from math import ceil
from typing import Iterable

from .canonical import canonical_sha256
from .choice_authority import expand_option_selections
from .diagnostics import RecoveryDisposition, error
from .gate2_runtime_content import ACTIONS, AN, LEE, LING, BAI, CUI
from .gate2_runtime_models import (
    ActionIntent, CandidateKind, LegalCandidate, ReactionDecision,
)
from .gate4_models import (
    CandidateScore, ComponentScore, ControllerChoice, DecisionContext,
    DecisionRecord, ReactionChoice, ReactionContext, VisibleActor,
)


CONTROLLER_ID = "controller:local_deterministic.gate4"
CONTROLLER_VERSION = "1.0.1"
MOVEMENT_LIMIT = 16
OPTION_EXPANSION_LIMIT = 32
COMMAND_CUI_ID = "action:bai_meizhen.command_cui"


def _actor(context: DecisionContext, actor_id: str) -> VisibleActor:
    return next(a for a in context.actors if a.entity_id == actor_id)


def _distance(a, b) -> int:
    return max(abs(a.x - b.x), abs(a.y - b.y)) * 5


def _average_damage(source_id: str) -> int:
    action = ACTIONS.get(source_id)
    if action is None or action.damage is None:
        return 0
    # Integer half-point approximation, deliberately not a probability simulator.
    numerator = action.damage.count * (action.damage.sides + 1) + 2 * action.damage.modifier
    return numerator // 2


def _option_sets(candidate: LegalCandidate) -> tuple[tuple[str, ...], ...]:
    try:
        return expand_option_selections(candidate, limit=OPTION_EXPANSION_LIMIT)
    except ValueError as exc:
        raise error(
            "CONTROLLER_OPTION_EXPANSION_LIMIT",
            f"Candidate {candidate.candidate_id} cannot be expanded through its typed option domains: {exc}",
            phase="CONTROLLER_CHOICE", subsystem="GATE4_CONTROLLER",
            entity_id=candidate.actor_id, source_definition=candidate.source_definition_id,
            recommended_action="Correct the typed choice-domain authority or raise the documented bounded expansion guard.",
            recovery=RecoveryDisposition.STOP,
            details={"limit": OPTION_EXPANSION_LIMIT, "choice_authority_status": candidate.choice_authority_status},
        )


def _command_mode(candidate: LegalCandidate, option_ids: tuple[str, ...]) -> str | None:
    if candidate.source_definition_id != COMMAND_CUI_ID or len(option_ids) != 1:
        return None
    return option_ids[0]


def _invalid_cui_strike(
    context: DecisionContext,
    candidate: LegalCandidate,
    option_ids: tuple[str, ...],
) -> bool:
    if _command_mode(candidate, option_ids) != "STRIKE":
        return False
    cui = next((row for row in context.actors if row.entity_id == CUI), None)
    target = next((row for row in context.actors if candidate.target_ids and row.entity_id == candidate.target_ids[0]), None)
    return bool(
        cui is None
        or target is None
        or not target.active
        or target.team_id == cui.team_id
        or target.entity_id == cui.entity_id
    )


def _hold_committed_this_turn(context: DecisionContext) -> bool:
    """Return whether the active actor already committed system Hold this turn."""
    for event in reversed(context.recent_events):
        if event.get("event_type") == "TURN_STARTED" and event.get("actor_id") == context.active_actor_id:
            return False
        if event.get("event_type") == "HOLD_POSITION_COMMITTED" and event.get("actor_id") == context.active_actor_id:
            return True
    return False


def _useful_cui_command_exists(context: DecisionContext, mode: str) -> bool:
    cui = next((row for row in context.actors if row.entity_id == CUI and row.active), None)
    if cui is None:
        return False
    for candidate in context.legal_candidates:
        if candidate.source_definition_id != COMMAND_CUI_ID or candidate.option_ids != (mode,):
            continue
        target = next((row for row in context.actors if candidate.target_ids and row.entity_id == candidate.target_ids[0]), None)
        if target is None or not target.active or target.entity_id == CUI:
            continue
        distance = _distance(cui.position, target.position)
        if mode == "STRIKE" and target.team_id != cui.team_id and distance <= cui.speed_ft + 5:
            return True
        if mode == "DASH" and distance > 5:
            return True
    return False


def _movement_representatives(context: DecisionContext, rows: list[LegalCandidate]) -> list[LegalCandidate]:
    if len(rows) <= MOVEMENT_LIMIT:
        return rows
    actor = _actor(context, context.active_actor_id)
    focus = next((a for a in context.actors if a.entity_id == context.team_behavior.focus_target_id), None)
    hostiles = [a for a in context.actors if a.active and a.team_id != actor.team_id]
    preferred = context.policy.preferred_range_bands_ft[0] if context.policy.preferred_range_bands_ft else (5, 30)

    def key(c: LegalCandidate):
        destination = c.destination or actor.position
        focus_distance = _distance(destination, focus.position) if focus else 999
        nearest = min((_distance(destination, h.position) for h in hostiles), default=999)
        range_penalty = 0 if preferred[0] <= nearest <= preferred[1] else min(abs(nearest-preferred[0]), abs(nearest-preferred[1]))
        hazard = 1 if c.metadata.get("hazard_exposure") else 0
        reactions = len(c.metadata.get("reaction_exposure", ()))
        return (range_penalty, hazard, reactions, focus_distance, c.movement_cost_ft, c.candidate_id)

    ranked = sorted(rows, key=key)
    # Preserve strategic diversity: best preferred, closest, farthest, safest, and deterministic fill.
    selected: dict[str, LegalCandidate] = {}
    for c in ranked[:8]: selected[c.candidate_id] = c
    if focus:
        for c in sorted(rows, key=lambda c: (_distance(c.destination or actor.position, focus.position), c.candidate_id))[:3]: selected[c.candidate_id] = c
        for c in sorted(rows, key=lambda c: (-_distance(c.destination or actor.position, focus.position), c.candidate_id))[:2]: selected[c.candidate_id] = c
    for c in sorted(rows, key=lambda c: (bool(c.metadata.get("hazard_exposure")), len(c.metadata.get("reaction_exposure", ())), c.movement_cost_ft, c.candidate_id))[:3]:
        selected[c.candidate_id] = c
    return sorted(selected.values(), key=lambda c: c.candidate_id)[:MOVEMENT_LIMIT]


class LocalDeterministicController:
    controller_id = CONTROLLER_ID
    controller_version = CONTROLLER_VERSION

    def _score_candidate(self, context: DecisionContext, candidate: LegalCandidate, option_ids: tuple[str, ...]) -> CandidateScore:
        actor = _actor(context, candidate.actor_id)
        target = next((a for a in context.actors if candidate.target_ids and a.entity_id == candidate.target_ids[0]), None)
        command_mode = _command_mode(candidate, option_ids)
        components: list[ComponentScore] = []
        weights = context.policy.weights

        immediate = _average_damage(candidate.source_definition_id)
        if candidate.source_definition_id in {"action:ling_qi.forgotten_vale_nocturne", "action:bai_meizhen.blackwater_serpent_court"} and candidate.destination:
            action = ACTIONS[candidate.source_definition_id]
            count = sum(1 for a in context.actors if a.active and a.team_id != actor.team_id and _distance(candidate.destination, a.position) <= int(action.radius_ft or 0))
            immediate += count * 7
        if candidate.source_definition_id == "action:ling_qi.keep_the_measure": immediate += 8
        if candidate.source_definition_id == COMMAND_CUI_ID:
            cui = next((a for a in context.actors if a.entity_id == CUI), None)
            if command_mode == "STRIKE" and cui and target and target.team_id != cui.team_id:
                if _distance(cui.position, target.position) <= cui.speed_ft + 5:
                    immediate += _average_damage("action:bai_cui.companion_strike")
                else:
                    immediate += 2  # bounded approach value; no assumed attack damage
            elif command_mode == "DODGE":
                immediate += 5
            elif command_mode == "DASH" and cui and target and _distance(cui.position, target.position) > 5:
                immediate += 4
            elif command_mode == "HOLD":
                immediate -= 4
        if candidate.kind == CandidateKind.OPTIONAL_RIDER: immediate += 8
        components.append(ComponentScore(component="immediate_effect", value=immediate * weights.get("immediate_effect", 1), explanation=f"Visible average or typed effect estimate {immediate}."))

        policy_value = context.policy.action_priorities.get(candidate.source_definition_id, 0)
        for option in option_ids:
            policy_value += {
                "DEEPEN": 7,
                "PAIRED_WEAPONS": 8, "PRIMARY_WEAPON": 2, "DASH": 4, "DISENGAGE": 6,
                "STRIKE": 12, "DODGE": 8, "HOLD": -12,
                "CHARGE": 7, "JOLT": 10, "FLASH": 6, "ARC": 8,
                "AC_MINUS_1": 8, "NEXT_ATTACK_ADVANTAGE": 10, "NO_HALF_COVER": 5,
            }.get(option, 0)
        components.append(ComponentScore(component="character_policy", value=policy_value * weights.get("character_policy", 1), explanation="Typed policy action and option priority."))

        target_value = 0
        finish = 0
        if target and command_mode != "DODGE":
            if target.primary_combatant: target_value += 4
            if target.entity_id == context.team_behavior.focus_target_id: target_value += context.policy.target_priorities.get("FOCUS_TARGET", 0)
            if target.current_hp * 4 <= target.maximum_hp: target_value += context.policy.target_priorities.get("LOW_HP_PRIMARY", 0)
            if command_mode != "DASH" and immediate >= target.current_hp + target.temporary_hp: finish += 20
        components.append(ComponentScore(component="target", value=target_value, explanation="Visible focus and low-HP target priority."))
        components.append(ComponentScore(component="defeat_prevention_or_finish", value=finish * weights.get("finish", 1), explanation="Visible defeat pressure without future-roll inspection."))

        resource = 0
        action = ACTIONS.get(candidate.source_definition_id)
        if action:
            for rid, cost in action.costs:
                after = actor.resources.get(rid, 0) - cost
                reserve = context.policy.resource_reserves.get(rid, 0)
                resource -= cost * 4
                if after < reserve: resource -= 18
        components.append(ComponentScore(component="resource_use", value=resource * weights.get("resource_use", 1), explanation="Cost and typed reserve policy."))

        position = 0
        risk = 0
        if candidate.kind == CandidateKind.MOVE and candidate.destination:
            hostiles = [a for a in context.actors if a.active and a.team_id != actor.team_id]
            nearest = min((_distance(candidate.destination, h.position) for h in hostiles), default=999)
            bands = context.policy.preferred_range_bands_ft or ((5,30),)
            if any(lo <= nearest <= hi for lo,hi in bands): position += 18
            else: position -= min(20, min(min(abs(nearest-lo),abs(nearest-hi)) for lo,hi in bands))
            if candidate.metadata.get("hazard_exposure"): risk -= 18
            risk -= 8 * len(candidate.metadata.get("reaction_exposure", ()))
            hp_pct = actor.current_hp * 100 // actor.maximum_hp
            if hp_pct <= 20: position += nearest // 5
            elif context.team_behavior.formation_direction == "CLOSE": position -= nearest // 10
        components.append(ComponentScore(component="position", value=position * weights.get("position", 1), explanation="Preferred range, formation direction, and visible geometry."))
        components.append(ComponentScore(component="avoidable_risk", value=risk * weights.get("avoidable_risk", 1), explanation="Visible hazard and opportunity-reaction exposure."))

        survival = 0
        hp_pct = actor.current_hp * 100 // actor.maximum_hp
        if hp_pct <= 20:
            if candidate.source_definition_id in {"system:combat.dodge","system:combat.disengage"}: survival += 28
            if candidate.kind == CandidateKind.MOVE: survival += 12
        elif hp_pct <= 40:
            if candidate.source_definition_id in {"system:combat.dodge","system:combat.disengage"}: survival += 12
        components.append(ComponentScore(component="survival", value=survival * weights.get("survival", 1), explanation=f"Visible HP band {hp_pct}%."))

        ally = 0
        if candidate.source_definition_id == "action:ling_qi.keep_the_measure":
            ally += 16
        elif candidate.source_definition_id == COMMAND_CUI_ID:
            ally += 16
            if command_mode == "DODGE":
                ally += 8
            elif command_mode == "HOLD":
                ally += 2
            elif command_mode == "DASH" and target and target.team_id == actor.team_id:
                ally += min(8, context.policy.ally_companion_priorities.get(target.entity_id, 0))
        elif target and target.team_id == actor.team_id:
            ally += context.policy.ally_companion_priorities.get(target.entity_id, 0)
        components.append(ComponentScore(component="ally_support", value=ally * weights.get("ally_support", 1), explanation="Typed ally and companion priority."))

        # Bespoke bounded guards and sequencing.
        condition_ids = set(actor.conditions)
        special = 0
        if actor.entity_id == AN:
            has_ruin = "condition:an_eui.ruin_tempered" in condition_ids
            if candidate.source_definition_id == "action:an_eui.ruin_tempered_armament_quick": special += 26 if not has_ruin else -35
            if candidate.source_definition_id == "action:an_eui.first_arm": special += 32 if has_ruin else -10000
        elif actor.entity_id == LEE:
            charge = actor.resources.get("resource:lee_jia.lightning_charge", 0)
            if candidate.source_definition_id == "action:lee_jia.gather_charge": special += 20 if charge < 2 else -12
            if candidate.source_definition_id == "action:lee_jia.lightning_lash": special += charge * 14
        elif actor.entity_id == LING:
            if candidate.source_definition_id == "action:ling_qi.forgotten_vale_nocturne":
                special += 22 if actor.concentration_source_id is None else -12
            if candidate.source_definition_id == "action:ling_qi.keep_the_measure":
                allies = [a for a in context.actors if a.active and a.team_id == actor.team_id and a.current_hp * 2 < a.maximum_hp]
                special += 8 * len(allies)
        elif actor.entity_id == BAI:
            cui = next((a for a in context.actors if a.entity_id == CUI), None)
            if candidate.source_definition_id == "action:bai_meizhen.blackwater_serpent_court": special += 20 if actor.concentration_source_id is None else -10
            if candidate.source_definition_id == COMMAND_CUI_ID and cui and cui.active:
                if command_mode == "STRIKE":
                    special += 18 if target and target.team_id != cui.team_id and _distance(cui.position, target.position) <= cui.speed_ft + 5 else -12
                elif command_mode == "DASH":
                    special += 8 if target and _distance(cui.position, target.position) > 5 else -10
                elif command_mode == "DODGE":
                    no_better_command = not _useful_cui_command_exists(context, "STRIKE") and not _useful_cui_command_exists(context, "DASH")
                    special += 18 if no_better_command else 2
                elif command_mode == "HOLD":
                    special -= 18
        if candidate.kind in {CandidateKind.END_TURN, CandidateKind.HOLD_POSITION}:
            useful = any(c.kind in {CandidateKind.ACTION,CandidateKind.BONUS_ACTION,CandidateKind.OPTIONAL_RIDER} for c in context.legal_candidates)
            special += -1000 if useful else 0
            if candidate.kind == CandidateKind.HOLD_POSITION:
                special -= 20
                if _hold_committed_this_turn(context):
                    special -= 10000
        if context.no_progress_signals and candidate.kind == CandidateKind.MOVE: special += 20
        if context.no_progress_signals and candidate.kind in {CandidateKind.HOLD_POSITION,CandidateKind.END_TURN}: special -= 30
        components.append(ComponentScore(component="policy_sequence", value=special, explanation="Small typed character sequencing and no-progress rules."))

        total = sum(c.value for c in components)
        return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=total, components=tuple(components))

    def choose_primary_action(self, decision_context: DecisionContext) -> ControllerChoice:
        candidates = list(decision_context.legal_candidates)
        if _hold_committed_this_turn(decision_context):
            candidates = [candidate for candidate in candidates if candidate.kind != CandidateKind.HOLD_POSITION]
        movement = _movement_representatives(decision_context, [c for c in candidates if c.kind == CandidateKind.MOVE])
        candidates = [c for c in candidates if c.kind != CandidateKind.MOVE] + movement
        scored: list[CandidateScore] = []
        candidate_map = {c.candidate_id: c for c in candidates}
        for candidate in candidates:
            for options in _option_sets(candidate):
                if candidate.source_definition_id == COMMAND_CUI_ID and candidate.option_ids != options:
                    continue
                if _invalid_cui_strike(decision_context, candidate, options):
                    continue
                scored.append(self._score_candidate(decision_context, candidate, options))
        if not scored:
            raise error(
                "CONTROLLER_NO_LEGAL_CHOICE", "The local controller received no legal expanded choice.",
                phase="CONTROLLER_CHOICE", subsystem="GATE4_CONTROLLER",
                entity_id=decision_context.active_actor_id,
                recommended_action="Preserve the match and inspect candidate-generation diagnostics.",
            )
        scored.sort(key=lambda s: (-s.total, s.candidate_id, s.option_ids))
        selected = scored[0]
        candidate = candidate_map[selected.candidate_id]
        intent = ActionIntent(
            intent_id=f"intent:local:{canonical_sha256({'decision':decision_context.decision_id,'candidate':candidate.candidate_id,'options':selected.option_ids})[:24]}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            option_ids=selected.option_ids,
            reaction_decisions=(),
        )
        record = DecisionRecord(
            controller_id=self.controller_id, controller_version=self.controller_version,
            policy_id=decision_context.policy.policy_id, policy_version=decision_context.policy.policy_version,
            decision_id=decision_context.decision_id, actor_id=candidate.actor_id,
            state_version=decision_context.state_version, decision_kind="PRIMARY",
            legal_alternatives=tuple(sorted(c.candidate_id for c in candidates)),
            scored_alternatives=tuple(scored), selected_candidate_id=candidate.candidate_id,
            selected_option_ids=selected.option_ids, selected_reaction=None,
            deterministic_tie_break="highest integer total, then candidate_id, then option_ids",
            explanation=f"Selected {candidate.display_name} at score {selected.total}.",
            fallback_policy_used=decision_context.policy.generic_fallback,
            diagnostics=tuple(
                ([{"code":"CONTROLLER_POLICY_MISSING_USING_FALLBACK","actor_id":candidate.actor_id,"policy":decision_context.policy.policy_id,"safe_next_action":"Continue with the generic policy or install a bespoke typed policy."}] if decision_context.policy.generic_fallback else [])
                + ([{"code":"CONTROLLER_NO_PROGRESS_DETECTED","actor_id":candidate.actor_id,"signals":list(decision_context.no_progress_signals),"safe_next_action":"Change action family or reposition through current legal candidates."}] if decision_context.no_progress_signals else [])
            ),
        )
        return ControllerChoice(intent=intent, record=record)

    def choose_reaction(self, reaction_context: ReactionContext) -> ReactionChoice:
        rid = reaction_context.reaction_source_id
        rule = reaction_context.policy.reaction_rules.get(rid, {})
        pending = int(reaction_context.pending_damage or 0)
        minimum = int(rule.get("minimum_packet", 8))
        use = False
        spend = 0
        if rid == "reaction:ling_qi.qi_armor":
            use = bool(reaction_context.provisional_hit and reaction_context.resources.get("resource:ling_qi.qi",0) >= 2)
        elif rid == "reaction:bai_meizhen.spirit_intercession":
            use = True
        elif pending >= minimum:
            use = True
        if reaction_context.spend_options and use:
            spend = min(max(1, ceil(pending / 6)), max(reaction_context.spend_options))
            spend = min(reaction_context.spend_options, key=lambda x: (abs(x-spend), x))
        selected_reaction_options: tuple[str, ...] = ()
        if use and reaction_context.legal_option_ids:
            # Current reactions expose bounded exact option IDs. The policy uses
            # every offered exact modifier; the validator remains authoritative.
            selected_reaction_options = tuple(reaction_context.legal_option_ids)
        decision = ReactionDecision(
            checkpoint=reaction_context.checkpoint,
            reactor_id=reaction_context.reactor_id,
            reaction_source_id=rid,
            selection="USE" if use else "DECLINE",
            spend=spend,
            option_ids=selected_reaction_options,
        )
        use_score = pending * 10 + (1000 if use and pending else 0)
        decline_score = 0 if pending < minimum else -pending * 3
        scored = (
            CandidateScore(candidate_id=f"reaction:{rid}:DECLINE", option_ids=(), total=decline_score, components=(ComponentScore(component="packet_materiality",value=decline_score,explanation="Decline value for visible packet."),)),
            CandidateScore(candidate_id=f"reaction:{rid}:USE", option_ids=((str(spend),) if spend else ()), total=use_score, components=(ComponentScore(component="damage_prevention",value=use_score,explanation="Visible prevention and typed reaction policy."),)),
        )
        selected_id = f"reaction:{rid}:{decision.selection}"
        record = DecisionRecord(
            controller_id=self.controller_id, controller_version=self.controller_version,
            policy_id=reaction_context.policy.policy_id, policy_version=reaction_context.policy.policy_version,
            decision_id=reaction_context.decision_id, actor_id=reaction_context.reactor_id,
            state_version=reaction_context.state_version, decision_kind="REACTION",
            legal_alternatives=(f"reaction:{rid}:DECLINE", f"reaction:{rid}:USE"),
            scored_alternatives=scored, selected_candidate_id=selected_id,
            selected_option_ids=selected_reaction_options or ((str(spend),) if spend else ()), selected_reaction=decision,
            deterministic_tie_break="typed policy threshold, then minimum sufficient legal spend",
            explanation=f"{decision.selection} {rid} for visible pending damage {pending}.",
            fallback_policy_used=reaction_context.policy.generic_fallback,
            diagnostics=(),
        )
        return ReactionChoice(decision=decision, record=record)
