from __future__ import annotations

from .relations import relation, ALLY, ENEMY

from math import ceil
from typing import Iterable

from .canonical import canonical_sha256
from .choice_authority import expand_option_selections
from .diagnostics import RecoveryDisposition, error
from .gate2_runtime_content import ACTIONS, AN, LEE, LING, BAI, CUI
from .gate2_runtime_models import (
    ActionIntent, CandidateKind, LegalCandidate, Position, ReactionDecision,
)
from .gate4_models import (
    CandidateScore, ComponentScore, ControllerChoice, DecisionContext,
    DecisionRecord, ReactionChoice, ReactionContext, VisibleActor,
)


CONTROLLER_ID = "controller:local_deterministic.gate4"
CONTROLLER_VERSION = "1.1.0"
MOVEMENT_LIMIT = 16
OPTION_EXPANSION_LIMIT = 32
COMMAND_CUI_ID = "action:bai_meizhen.command_cui"


def _actor(context: DecisionContext, actor_id: str) -> VisibleActor:
    return next(a for a in context.actors if a.entity_id == actor_id)


def _flight_facts(context: DecisionContext | None) -> dict:
    """The shared context builder annotates every candidate or none of them."""
    if context is None or not context.legal_candidates:
        return {}
    return context.legal_candidates[0].metadata.get("flight_tactics") or {}


def _distance(a, b, context: DecisionContext | None = None) -> int:
    from .gate2_grid import SquareGrid
    from .space import projection
    # Preserve the historical ground policy, including supported elevated
    # creatures without flight. Height decisions use the engine's native metric;
    # prospective movement and melee safety use the complete-volume annotations.
    if not _flight_facts(context):
        a, b = projection(a), projection(b)
    return SquareGrid.distance_cells(a, b) * 5


def _unsafe_flight_route(candidate: LegalCandidate) -> bool:
    destination = (candidate.metadata.get("flight_tactics") or {}).get("destination", {})
    # The shared builder checks every route, including endpoints outside the
    # bounded attack assessment. Missing support facts cannot earn priority.
    return any(destination.get(key, True) for key in
               ("fall_required", "path_requires_fall", "path_blocked"))


def _flight_descent(candidate: LegalCandidate) -> bool:
    facts = candidate.metadata.get("flight_tactics") or {}
    current, destination = facts.get("current", {}), facts.get("destination", {})
    return bool(candidate.kind == CandidateKind.MOVE and facts.get("flight_ending")
                and not current.get("supported") and destination
                and not _unsafe_flight_route(candidate)
                and (destination.get("supported")
                     or destination["altitude_ft"] < current["altitude_ft"]))


def _flight_move_value(candidate: LegalCandidate, *, approach_melee: bool = False) -> int:
    """Relative, integer value of native prospective facts, never permission.

    No bonus is given for height itself. A move must gain an attack, reduce
    perceived melee exposure, or make useful progress toward an attack. Known
    flight loss makes support/descents urgent; unevaluated geometry earns no
    attack or safety credit. A price for movement breaks equivalent-height ties.
    When a melee policy has spent its attacks, a flight route that passes
    native support and expiry checks
    may still close on a perceived foe; that gains only geometric progress,
    never credit for an unavailable attack or for altitude itself.
    """
    facts = candidate.metadata["flight_tactics"]
    current, destination = facts["current"], facts.get("destination", {})
    if not destination:
        return -40
    cost = max(1, candidate.movement_cost_ft // 5)
    climb = max(0, (destination["altitude_ft"] - current["altitude_ft"]) // 5)
    if _unsafe_flight_route(candidate):
        return -3000 - cost
    if facts.get("flight_ending"):
        if _flight_descent(candidate):
            drop = max(0, (current["altitude_ft"] - destination["altitude_ft"]) // 5)
            # Keep support above every partial descent, even on tall maps.
            return (30000 if destination["supported"] else 20000 + min(5000, drop * 100)) - min(999, cost)
        if not destination.get("supported"):
            return -2000 - climb * 10 - cost
    if destination.get("expiry_risk"):
        return -2000 - climb * 10 - cost
    before_attack = bool(current.get("attack_target_ids"))
    after_attack = bool(destination.get("attack_target_ids"))
    before = current.get("nearest_hostile_ft")
    after = destination.get("nearest_hostile_ft")
    # Every route already has native support/expiry checks and exact observed
    # distance. Closing needs no speculative attack or safe-attack assessment.
    if (approach_melee and not before_attack and not after_attack
            and before is not None and after is not None and before > after):
        return (before - after) // 5 * 6 - cost
    if not destination.get("evaluated"):
        return -40 - climb * 6 - cost
    before_threats = len(current.get("melee_threat_ids", ()))
    after_threats = len(destination.get("melee_threat_ids", ()))
    threat_reduction = before_threats - after_threats
    value = 80 * (int(after_attack) - int(before_attack))
    # Losing an available attack must carry a cost as well as any safety gain.
    if before_attack and not after_attack:
        value -= 60
    value += 40 * threat_reduction
    if destination.get("safe_attack") and not current.get("safe_attack"):
        value += 50
    if not before_attack and not after_attack:
        before = current.get("nearest_hostile_ft")
        after = destination.get("nearest_hostile_ft")
        if before is not None and after is not None:
            value += (before - after) // 5 * 6
    if climb and not (after_attack and not before_attack) and threat_reduction <= 0:
        value -= climb * 6
    if value <= 0:
        value -= 40  # no-progress/low-HP bonuses must not buy pointless flight
    return value - cost


def _average_damage(source_id: str) -> int:
    action = ACTIONS.get(source_id)
    if action is None or action.damage is None:
        return 0
    # Integer half-point approximation, deliberately not a probability simulator.
    numerator = action.damage.count * (action.damage.sides + 1) + 2 * action.damage.modifier
    return numerator // 2


_GUARD_ACTIONS = frozenset({"system:combat.dodge", "system:combat.disengage"})


def _deals_damage(candidate: LegalCandidate) -> bool:
    if candidate.metadata.get('placement_ai_unavailable'):
        return False
    if candidate.kind not in {CandidateKind.ACTION, CandidateKind.BONUS_ACTION}:
        return False
    return bool(_average_damage(candidate.source_definition_id) or int(candidate.metadata.get("expected_damage", 0) or 0))


def _outmatched(context: DecisionContext, actor: VisibleActor) -> bool:
    """The nearest enemy has more of its HP left than this actor does."""
    hostiles = [a for a in context.actors if a.active and relation(context, a, actor) == ENEMY]
    if not hostiles or not actor.maximum_hp:
        return False
    foe = min(hostiles, key=lambda h: (_distance(actor.position, h.position, context), h.entity_id))
    return foe.current_hp * actor.maximum_hp > actor.current_hp * max(1, foe.maximum_hp)


def _stress_reason(context: DecisionContext) -> str | None:
    """The I Ching change trigger met by the active actor, if its policy has one."""
    triggers = context.policy.stress_triggers or {}
    if not triggers:
        return None
    actor = next((a for a in context.actors if a.entity_id == context.active_actor_id), None)
    if actor is None:
        return None
    if actor.maximum_hp and actor.current_hp * 100 <= int(triggers.get("hp_pct", 0)) * actor.maximum_hp:
        return "wounded"
    resource = context.policy.stress_resource or {}
    maximum = int(resource.get("maximum") or 0)
    current = actor.resources.get(str(resource.get("resource_id") or ""))
    if maximum and current is not None and current * 100 <= int(triggers.get("resource_pct", 0)) * maximum:
        return f"{resource.get('label') or 'resource'} low"
    return None


def _posture_note(context: DecisionContext) -> str:
    reason = _stress_reason(context)
    labels = context.policy.posture_labels or {}
    if reason and labels.get("stress"):
        return f" I Ching change ({reason}): fighting as {labels['stress']}, not {labels.get('default', 'the default posture')}."
    return ""


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
        or relation(context, target, cui) != ENEMY
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
        distance = _distance(cui.position, target.position, context)
        if mode == "STRIKE" and relation(context, target, cui) == ENEMY and distance <= cui.speed_ft + 5:
            return True
        if mode == "DASH" and distance > 5:
            return True
    return False


def _movement_representatives(context: DecisionContext, rows: list[LegalCandidate], *, score_move=None) -> list[LegalCandidate]:
    from . import ext
    ordered = ext.run_strict('ai_movement_order', context, tuple(rows))
    if ordered:
        # A ranked prefix is presentation/expansion order, never legality.
        # Require a permutation so every legal destination stays reachable.
        ids = ordered[0]
        if len(ids) != len(rows) or set(ids) != {c.candidate_id for c in rows}:
            raise ValueError('ai_movement_order must retain every destination')
        by_id = {c.candidate_id: c for c in rows}
        return [by_id[cid] for cid in ids]
    if _flight_facts(context):
        # Score before truncating: hash ordering must never evict the only safe
        # attacking height or the route back to support before flight expires.
        return sorted(rows, key=lambda c: (-score_move(c), c.candidate_id))[:MOVEMENT_LIMIT]
    if context.bystander:
        from .bystander_policy import score
        actor = _actor(context, context.active_actor_id)
        return sorted(rows, key=lambda c: (-score(context, actor, c), c.candidate_id))[:MOVEMENT_LIMIT]
    if len(rows) <= MOVEMENT_LIMIT:
        return rows
    actor = _actor(context, context.active_actor_id)
    focus = next((a for a in context.actors if a.entity_id == context.team_behavior.focus_target_id), None)
    hostiles = [a for a in context.actors if a.active and relation(context, a, actor) == ENEMY]
    preferred = context.policy.preferred_range_bands_ft[0] if context.policy.preferred_range_bands_ft else (5, 30)

    def key(c: LegalCandidate):
        destination = c.destination or actor.position
        focus_distance = _distance(destination, focus.position, context) if focus else 999
        nearest = min((_distance(destination, h.position, context) for h in hostiles), default=999)
        range_penalty = 0 if preferred[0] <= nearest <= preferred[1] else min(abs(nearest-preferred[0]), abs(nearest-preferred[1]))
        hazard = 1 if c.metadata.get("hazard_exposure") else 0
        reactions = len(c.metadata.get("reaction_exposure", ()))
        return (range_penalty, hazard, reactions, focus_distance, c.movement_cost_ft, c.candidate_id)

    ranked = sorted(rows, key=key)
    # Preserve strategic diversity: best preferred, closest, farthest, safest, and deterministic fill.
    selected: dict[str, LegalCandidate] = {}
    for c in ranked[:8]: selected[c.candidate_id] = c
    if focus:
        for c in sorted(rows, key=lambda c: (_distance(c.destination or actor.position, focus.position, context), c.candidate_id))[:3]: selected[c.candidate_id] = c
        for c in sorted(rows, key=lambda c: (-_distance(c.destination or actor.position, focus.position, context), c.candidate_id))[:2]: selected[c.candidate_id] = c
    for c in sorted(rows, key=lambda c: (bool(c.metadata.get("hazard_exposure")), len(c.metadata.get("reaction_exposure", ())), c.movement_cost_ft, c.candidate_id))[:3]:
        selected[c.candidate_id] = c
    result = sorted(selected.values(), key=lambda c: c.candidate_id)[:MOVEMENT_LIMIT]
    search = next((c for c in rows if c.candidate_id == context.search_move_candidate_id), None)
    if search is not None and search not in result:
        result = result[:MOVEMENT_LIMIT - 1] + [search]
    # Flight is an engine-granted movement mode, never an ability-id heuristic.
    # Preserve a scored route for each vertical purpose before ordinary fill.
    flight = {}
    for c in ranked:
        if c.metadata.get("movement_mode") != "fly" or c.destination is None:
            continue
        z = c.destination.z
        purpose = "up" if z > actor.position.z else "down" if z < actor.position.z else "across"
        flight.setdefault(purpose, c)
    protected = list(flight.values())
    if not protected:
        return result
    if search is not None and search not in protected:
        protected.append(search)
    result = protected + [c for c in result if c not in protected][:MOVEMENT_LIMIT - len(protected)]
    return result


def native_flight_position_value(candidate: LegalCandidate, *, approach_melee: bool = False) -> int:
    """Shared native flight value for destination ranking and menu adapters.

    Consumes the existing perception-projected flight_tactics receipt. Does not
    copy an engine or grant movement legality; height alone earns no bonus.
    The controller already includes this value, so additive hooks must not add
    it a second time. Used by ext.ai_movement's destination ordering.
    approach_melee permits geometric progress toward a perceived foe after
    attacks are spent; it grants no attack or safety credit on unassessed routes.
    """
    return _flight_move_value(candidate, approach_melee=approach_melee) if candidate.metadata.get('flight_tactics') else 0


class LocalDeterministicController:
    controller_id = CONTROLLER_ID
    controller_version = CONTROLLER_VERSION

    def _score_candidate(self, context: DecisionContext, candidate: LegalCandidate, option_ids: tuple[str, ...], *,
                         strike_available: bool | None = None) -> CandidateScore:
        if candidate.metadata.get('placement_ai_unavailable'):
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=-10000,
                components=(ComponentScore(component='placement_admission', value=-10000,
                    explanation='No placement passes the automatic controller’s checks using known creatures.'),))
        evaluation = candidate.metadata.get('placement_evaluation')
        if evaluation:
            preview = LegalCandidate.model_validate(evaluation)
            score = self._score_candidate(context, preview, option_ids, strike_available=strike_available)
            return score.model_copy(update={'candidate_id': candidate.candidate_id})
        # One immutable decision's damage availability is shared by all scores.
        # Direct scoring callers retain the same result without a supplied value.
        if strike_available is None:
            strike_available = any(_deals_damage(row) for row in context.legal_candidates)
        actor = _actor(context, candidate.actor_id)
        flight_facts = candidate.metadata.get("flight_tactics") or {}
        stressed = _stress_reason(context)
        flight_bands = (context.policy.stress_range_bands_ft if stressed and context.policy.stress_range_bands_ft else None) or context.policy.preferred_range_bands_ft
        approach_melee = bool(not strike_available and context.policy.position_relative
            and flight_bands and all(hi <= 5 for _, hi in flight_bands)
            and candidate.metadata.get("movement_mode") == "fly"
            and not flight_facts.get("flight_ending")
            and not (stressed and _outmatched(context, actor)))
        flight_value = _flight_move_value(candidate, approach_melee=approach_melee) if flight_facts and candidate.kind == CandidateKind.MOVE else 0
        if flight_facts and candidate.kind == CandidateKind.MOVE and _unsafe_flight_route(candidate):
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=flight_value,
                components=(ComponentScore(component="flight_support", value=flight_value,
                    explanation="Avoid an unchecked route or one where native flight and support rules block movement or require a fall."),))
        if _flight_descent(candidate):
            value = flight_value - min(999, 18 * bool(candidate.metadata.get("hazard_exposure")) + 8 * len(candidate.metadata.get("reaction_exposure", ())))
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=value,
                components=(ComponentScore(component="flight_expiry", value=value,
                    explanation="Reach support or descend before known flight support ends, using a legal native route."),))
        if flight_facts.get("destination", {}).get("expiry_risk"):
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=flight_value,
                components=(ComponentScore(component="flight_expiry", value=flight_value,
                    explanation="Avoid a height whose known route to support exceeds the remaining flight movement before expiry."),))
        if (candidate.kind == CandidateKind.MOVE and candidate.candidate_id == context.search_move_candidate_id
                and not flight_facts.get("flight_ending")):
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=10000,
                components=(ComponentScore(component='search_unknown_opponent', value=10000,
                    explanation='Use available walking movement to look for an opponent, following remembered places and unexplored routes.'),))
        if 'standing_cost_ft' in candidate.metadata:
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=10000,
                components=(ComponentScore(component='posture', value=10000,
                    explanation='Stand up to end Prone and move normally; spend half Speed or the available reduced standing cost.'),))
        if candidate.metadata.get('ai_free_preparation') is True:
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=10000,
                components=(ComponentScore(component='free_preparation', value=10000,
                    explanation='Complete a legal free preparation before spending actions.'),))
        from .relations import ordinary_turn
        if context.bystander and ordinary_turn(context.legal_candidates):
            from .bystander_policy import score
            value = score(context, actor, candidate)
            return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=value,
                components=(ComponentScore(component='bystander', value=value,
                    explanation='Move away from danger, then Dodge to make attacks against you less likely to hit until your next turn.'),))
        target = next((a for a in context.actors if candidate.target_ids and a.entity_id == candidate.target_ids[0]), None)
        command_mode = _command_mode(candidate, option_ids)
        components: list[ComponentScore] = []
        weights = context.policy.stress_weights if stressed and context.policy.stress_weights else context.policy.weights

        immediate = _average_damage(candidate.source_definition_id) or int(candidate.metadata.get("expected_damage", 0) or 0)
        support = candidate.metadata.get('useful_recovery')
        if support is not None:
            immediate += sum(int(row['healing_hp']) + int(row['temporary_hp']) for row in support)
        if candidate.metadata.get('target_knowledge') == 'LAST_OBSERVED':
            immediate = 0
            target = None  # no predicted damage or defeat pressure against an unobserved creature
        if candidate.source_definition_id in {"action:ling_qi.forgotten_vale_nocturne", "action:bai_meizhen.blackwater_serpent_court"} and candidate.destination:
            action = ACTIONS[candidate.source_definition_id]
            count = sum(1 for a in context.actors if a.active and relation(context, a, actor) == ENEMY and _distance(candidate.destination, a.position, context) <= int(action.radius_ft or 0))
            immediate += count * 7
        if candidate.source_definition_id == "action:ling_qi.keep_the_measure": immediate += 8
        if candidate.source_definition_id == COMMAND_CUI_ID:
            cui = next((a for a in context.actors if a.entity_id == CUI), None)
            if command_mode == "STRIKE" and cui and target and relation(context, target, cui) == ENEMY:
                if _distance(cui.position, target.position, context) <= cui.speed_ft + 5:
                    immediate += _average_damage("action:bai_cui.companion_strike")
                else:
                    immediate += 2  # bounded approach value; no assumed attack damage
            elif command_mode == "DODGE":
                immediate += 5
            elif command_mode == "DASH" and cui and target and _distance(cui.position, target.position, context) > 5:
                immediate += 4
            elif command_mode == "HOLD":
                immediate -= 4
        if candidate.kind == CandidateKind.OPTIONAL_RIDER: immediate += 8
        components.append(ComponentScore(component="immediate_effect", value=immediate * weights.get("immediate_effect", 1), explanation=f"Visible average or typed effect estimate {immediate}."))
        allied_damage = int(candidate.metadata.get('ally_expected_damage') or 0)
        allied_count = int(candidate.metadata.get('unavoidable_allies_in_area') or 0)
        if allied_count:
            penalty = max(allied_damage, allied_count) * max(1, weights.get('immediate_effect', 1))
            components.append(ComponentScore(component='friendly_fire', value=-penalty,
                explanation=f'This area affects {allied_count} allies; estimated damage to them is {allied_damage}.'))
        if candidate.metadata.get('self_harm'):
            own_damage = int(candidate.metadata.get('self_expected_damage') or 0)
            components.append(ComponentScore(component='self_harm',
                value=-max(1, own_damage) * max(1, weights.get('immediate_effect', 1)),
                explanation=f'This technique harms its user; estimated damage is {own_damage}.'))

        utility = candidate.metadata.get('rider_utility', 0)
        if type(utility) is int and utility and candidate.metadata.get('target_knowledge') != 'LAST_OBSERVED':
            components.append(ComponentScore(component='rider_utility',
                value=utility * weights.get('rider_utility', weights.get('immediate_effect', 1)),
                explanation='Value of the additional effect, separate from damage; it cannot count as a finishing blow.'))

        policy_value = context.policy.action_priorities.get(candidate.source_definition_id, 0)
        if (context.policy.guard_only_when_no_strike and policy_value > 0
                and candidate.source_definition_id in _GUARD_ACTIONS
                and strike_available
                and not (stressed and _outmatched(context, actor))):
            # A Dao fighter that can strike guards or slips away only when the I Ching
            # change has it wounded AND losing the exchange; otherwise it presses.
            policy_value = 0
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
        if target and command_mode != "DODGE" and not (support is not None and target.team_id == actor.team_id):
            if target.primary_combatant: target_value += 4
            if target.entity_id == context.team_behavior.focus_target_id: target_value += context.policy.target_priorities.get("FOCUS_TARGET", 0)
            if target.current_hp * 4 <= target.maximum_hp: target_value += context.policy.target_priorities.get("LOW_HP_PRIMARY", 0)
            if command_mode != "DASH" and immediate >= target.current_hp + target.temporary_hp: finish += 20
        components.append(ComponentScore(component="target", value=target_value, explanation="Visible focus and low-HP target priority."))
        components.append(ComponentScore(component="defeat_prevention_or_finish", value=finish * weights.get("finish", 1), explanation="Visible defeat pressure without future-roll inspection."))

        resource = 0
        action = ACTIONS.get(candidate.source_definition_id)
        costs = action.costs if action is not None else candidate.metadata.get('compiled_costs', ())
        for rid, cost in costs:
            after = actor.resources.get(rid, 0) - cost
            reserve = context.policy.resource_reserves.get(rid, 0)
            resource -= cost * 4
            if after < reserve: resource -= 18
        explanation = ("Resource spending and the amounts this fighter tries to keep in reserve."
                       if action is None and costs else "Cost and typed reserve policy.")
        components.append(ComponentScore(component="resource_use", value=resource * weights.get("resource_use", 1), explanation=explanation))

        position = 0
        risk = 0
        if candidate.metadata.get('cell_placement') and candidate.destination:
            hostiles = [a for a in context.actors if a.active and a.team_id != actor.team_id]
            distance = min((_distance(candidate.destination, h.position, context) for h in hostiles), default=0)
            position = max(0, 20 - distance // 5)
        teleport = bool(candidate.metadata.get('teleport'))
        if (candidate.kind == CandidateKind.MOVE or teleport) and candidate.destination:
            hostiles = [a for a in context.actors if a.active and relation(context, a, actor) == ENEMY]
            bands = (context.policy.stress_range_bands_ft if stressed and context.policy.stress_range_bands_ft else None) or context.policy.preferred_range_bands_ft or ((5,30),)
            hp_pct = actor.current_hp * 100 // actor.maximum_hp

            def place_score(cell) -> int:
                nearest = min((_distance(cell, h.position, context) for h in hostiles), default=999)
                score = 18 if any(lo <= nearest <= hi for lo,hi in bands) else -min(20, min(min(abs(nearest-lo),abs(nearest-hi)) for lo,hi in bands))
                if hp_pct <= 20: score += nearest // 5
                elif context.team_behavior.formation_direction == "CLOSE": score -= nearest // 10
                return score

            position = place_score(candidate.destination)
            if context.policy.position_relative or teleport:
                position -= place_score(actor.position)
                if not strike_available and not (stressed and _outmatched(context, actor)):
                    # Nothing can strike from here (a sword does not reach from 10 ft): close on the nearest enemy.
                    nearest_now = min((_distance(actor.position, h.position, context) for h in hostiles), default=0)
                    nearest_then = min((_distance(candidate.destination, h.position, context) for h in hostiles), default=0)
                    position = (nearest_now - nearest_then) // 5 * 6
            if candidate.metadata.get("hazard_exposure"): risk -= 18
            if (not flight_facts and candidate.metadata.get("movement_mode") == "fly"
                    and hostiles and all(lo > 5 for lo, _ in bands)):
                # Ranged fighters can use altitude to leave melee reach while
                # keeping their preferred range. Native flight_tactics already
                # scores actual reach and support, so use this fallback only
                # when those facts are absent. Consider only perceived foes.
                adjacent_now = sum(_distance(actor.position, h.position, context) <= 5 for h in hostiles)
                adjacent_then = sum(_distance(candidate.destination, h.position, context) <= 5 for h in hostiles)
                position += 6 * (adjacent_now - adjacent_then)
            if not teleport:
                risk -= 8 * len(candidate.metadata.get("reaction_exposure", ()))
            if teleport:
                # Pay for a hop only when its range/safety improves on staying.
                # Ordinary walking scores and all nonteleport contexts retain
                # their existing representation and deterministic tie breaks.
                adjacent_now = sum(_distance(actor.position, h.position, context) <= 5 for h in hostiles)
                adjacent_then = sum(_distance(candidate.destination, h.position, context) <= 5 for h in hostiles)
                if hp_pct <= 20:
                    position += 12 * (adjacent_now - adjacent_then)
                if not hostiles or position <= 0:
                    position = -40
        if flight_facts and candidate.kind == CandidateKind.MOVE:
            position = 0  # flight is relative to standing still, for every policy
            components.append(ComponentScore(component="flight_position", value=flight_value,
                explanation="Native prospective attack geometry, perceived melee reach, support, and useful movement without excess altitude."))
        components.append(ComponentScore(component="position", value=position * weights.get("position", 1), explanation="Preferred range, formation direction, and visible geometry."))
        if candidate.kind == CandidateKind.MOVE and ("cover_from_nearest_hostile" in candidate.metadata or "adjacent_hostiles" in candidate.metadata):
            # Cheap tactics for Dao-driven fighters: value cover from the nearest enemy, avoid being surrounded.
            tactical = (4 if candidate.metadata.get("cover_from_nearest_hostile") else 0) * weights.get("cover", 0)
            # One adjacent enemy is simply engaging; each enemy beyond the first is being surrounded.
            tactical -= 4 * max(0, int(candidate.metadata.get("adjacent_hostiles", 0)) - 1) * weights.get("surround_avoid", 0)
            components.append(ComponentScore(component="tactical_position", value=tactical, explanation="Cover from the nearest enemy and enemies adjacent to the destination."))
        components.append(ComponentScore(component="avoidable_risk", value=risk * weights.get("avoidable_risk", 1), explanation="Visible hazard and opportunity-reaction exposure."))

        survival = 0
        hp_pct = actor.current_hp * 100 // actor.maximum_hp
        guarding = candidate.source_definition_id in _GUARD_ACTIONS
        if (guarding and context.policy.guard_only_when_no_strike
                and strike_available
                and not any(a.active and relation(context, a, actor) == ALLY and a.entity_id != actor.entity_id for a in context.actors)):
            # Owner 2026-09-26 (step 12): a Dao fighter alone on its side gains nothing by Dodging while it can
            # still strike -- nobody else will win the fight for it -- so low HP alone no longer favours it
            # (losing fighters Dodged dozens of times into the round limit). Its Dao's own guard preference
            # (policy_value above) still applies.
            guarding = False
        if hp_pct <= 20:
            if guarding: survival += 28
            if candidate.kind == CandidateKind.MOVE and (not flight_facts or flight_value > 0): survival += 12
        elif hp_pct <= 40:
            if guarding: survival += 12
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
            elif command_mode == "DASH" and target and relation(context, target, actor) == ALLY:
                ally += min(8, context.policy.ally_companion_priorities.get(target.entity_id, 0))
        elif target and relation(context, target, actor) == ALLY:
            ally += context.policy.ally_companion_priorities.get(target.entity_id, 0)
        recovery_help = 0
        if context.policy.support_wounded_allies:
            for row in support or ():
                recipient = next((a for a in context.actors if a.entity_id == row['target_id']), None)
                if (recipient and recipient.active and recipient.entity_id != actor.entity_id
                        and relation(context, recipient, actor) == ALLY
                        and recipient.current_hp < recipient.maximum_hp):
                    recovery_help += max(0, int(row['healing_hp'])) + max(0, int(row['temporary_hp']))
        ally += recovery_help
        explanation = ("Healing or added Temporary HP that helps a wounded teammate."
                       if recovery_help else "Typed ally and companion priority.")
        components.append(ComponentScore(component="ally_support", value=ally * weights.get("ally_support", 1), explanation=explanation))

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
                allies = [a for a in context.actors if a.active and relation(context, a, actor) == ALLY and a.current_hp * 2 < a.maximum_hp]
                special += 8 * len(allies)
        elif actor.entity_id == BAI:
            cui = next((a for a in context.actors if a.entity_id == CUI), None)
            if candidate.source_definition_id == "action:bai_meizhen.blackwater_serpent_court": special += 20 if actor.concentration_source_id is None else -10
            if candidate.source_definition_id == COMMAND_CUI_ID and cui and cui.active:
                if command_mode == "STRIKE":
                    special += 18 if target and relation(context, target, cui) == ENEMY and _distance(cui.position, target.position, context) <= cui.speed_ft + 5 else -12
                elif command_mode == "DASH":
                    special += 8 if target and _distance(cui.position, target.position, context) > 5 else -10
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
        if context.no_progress_signals and candidate.kind == CandidateKind.MOVE and (not flight_facts or flight_value > 0): special += 20
        if context.no_progress_signals and candidate.kind in {CandidateKind.HOLD_POSITION,CandidateKind.END_TURN}: special -= 30
        components.append(ComponentScore(component="policy_sequence", value=special, explanation="Small typed character sequencing and no-progress rules."))

        from . import ext
        for extra in ext.run_strict('ai_score_components', context, candidate, option_ids):
            components.extend(extra)
        total = sum(c.value for c in components)
        if candidate.metadata.get('nonenemy_area_count'):
            penalty = -40 * int(candidate.metadata['nonenemy_area_count'])
            components.append(ComponentScore(component='bystander_safety', value=penalty,
                explanation='Avoid catching allies or neutral creatures in a harmful area.'))
            total += penalty
        return CandidateScore(candidate_id=candidate.candidate_id, option_ids=option_ids, total=total, components=tuple(components))

    def choose_primary_action(self, decision_context: DecisionContext) -> ControllerChoice:
        return self._primary_choice(decision_context)

    def score_primary_projection(self, decision_context: DecisionContext, candidate_ids) -> ControllerChoice:
        """Read-only table score projection; separate from the choice adapter API."""
        return self._primary_choice(decision_context, score_candidate_ids=candidate_ids)

    def _primary_choice(self, decision_context: DecisionContext, *, score_candidate_ids=None) -> ControllerChoice:
        """Optional presentation projection scores only requested native IDs.

        The complete context still supplies damage availability, collateral
        admission and movement representatives. None retains ordinary AI choice
        and replay exactly. A projection is for display, never turn execution.
        """
        # Explicit human/model/API choices retain these roots in the context;
        # local automatic selection requires an admitted concrete placement.
        candidates = [c for c in decision_context.legal_candidates
                      if not c.metadata.get('placement_ai_unavailable')]
        actor = _actor(decision_context, decision_context.active_actor_id)
        from .relations import ordinary_turn
        ordinary = ordinary_turn(candidates)
        if ordinary:
            candidates = [c for c in candidates if not any(
                relation(decision_context, actor, a) == 'NEUTRAL'
                for a in decision_context.actors if a.entity_id in c.target_ids)]
        if decision_context.bystander and ordinary:
            candidates = [c for c in candidates if c.kind in {CandidateKind.MOVE, CandidateKind.END_TURN}
                          or c.source_definition_id == 'system:combat.dodge']
        if _hold_committed_this_turn(decision_context):
            candidates = [candidate for candidate in candidates if candidate.kind != CandidateKind.HOLD_POSITION]
        if (ordinary and decision_context.movement_endpoints
                and any(c.kind != CandidateKind.MOVE for c in candidates)):
            candidates = [candidate for candidate in candidates
                          if candidate.kind != CandidateKind.MOVE
                          or candidate.destination not in decision_context.movement_endpoints
                          or _flight_descent(candidate)]
        # Placement risk is authoritative even when an extension's damage cannot
        # be estimated. Prefer a hostile-hitting placement of the same ability
        # that spares friends (including the caster). Explicit activation self
        # costs are not collateral; optional recipient selectors already spare
        # allies. Keep unavoidable placements if this ability has no safe one.
        def area_family(candidate):
            return candidate.metadata.get('ai_area_family') or candidate.source_definition_id
        safe_areas = {area_family(c) for c in candidates
                      if c.metadata.get('hostiles_in_area')
                      and not c.metadata.get('unavoidable_allies_in_area')}
        candidates = [c for c in candidates
                      if not (c.metadata.get('unavoidable_allies_in_area')
                              and area_family(c) in safe_areas)]
        strike_available = any(_deals_damage(row) for row in decision_context.legal_candidates)
        # Documented joint-planner seam: ai_tactics consumes only this immutable
        # knowledge context, scores every legal option, and cannot issue intents.
        # A tier adapter may refine complete scores and verify bounded plans;
        # the adapter receives only the detached knowledge context, not engine.
        from .ai_tactics import make_plan, choice_explanation
        plan = make_plan(decision_context)
        movement = ([c for c in candidates if c.kind == CandidateKind.MOVE] if plan.enabled else
                    _movement_representatives(decision_context, [c for c in candidates if c.kind == CandidateKind.MOVE],
            score_move=lambda candidate: max(self._score_candidate(decision_context, candidate, options,
                strike_available=strike_available).total for options in _option_sets(candidate))))
        candidates = [c for c in candidates if c.kind != CandidateKind.MOVE] + movement
        if score_candidate_ids is not None:
            candidates = [c for c in candidates if c.candidate_id in score_candidate_ids]
        scored: list[CandidateScore] = []
        candidate_map = {c.candidate_id: c for c in candidates}
        for candidate in candidates:
            for options in _option_sets(candidate):
                if candidate.source_definition_id == COMMAND_CUI_ID and candidate.option_ids != options:
                    continue
                if _invalid_cui_strike(decision_context, candidate, options):
                    continue
                scored.append(plan.score(candidate, self._score_candidate(decision_context, candidate, options,
                                                    strike_available=strike_available)))
        if not scored:
            raise error(
                "CONTROLLER_NO_LEGAL_CHOICE", "The local controller received no legal expanded choice.",
                phase="CONTROLLER_CHOICE", subsystem="GATE4_CONTROLLER",
                entity_id=decision_context.active_actor_id,
                recommended_action="Preserve the match and inspect candidate-generation diagnostics.",
            )
        scored = plan.with_self_followups(scored, candidate_map)
        # Spending movement must improve on a non-move choice. Keep the existing
        # stable hash/option tie-break within each group; positive-value moves win.
        scored.sort(key=lambda s: (-s.total, candidate_map[s.candidate_id].kind == CandidateKind.MOVE,
                                   s.candidate_id, s.option_ids))
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
            placement_destination=(Position.model_validate(candidate.metadata['placement_evaluation']['destination'])
                if candidate.metadata.get('placement_evaluation') else None),
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
            deterministic_tie_break="highest integer total, then non-movement choices, then candidate_id, then option_ids",
            explanation=choice_explanation(decision_context, candidate, selected) + _posture_note(decision_context),
            fallback_policy_used=decision_context.policy.generic_fallback,
            diagnostics=tuple(
                ([{"code":"CONTROLLER_POLICY_MISSING_USING_FALLBACK","actor_id":candidate.actor_id,"policy":decision_context.policy.policy_id,"safe_next_action":"Continue with the generic policy or install a bespoke typed policy."}] if decision_context.policy.generic_fallback else [])
                + ([{"code":"CONTROLLER_NO_PROGRESS_DETECTED","actor_id":candidate.actor_id,"signals":list(decision_context.no_progress_signals),"safe_next_action":"Change action family or reposition through current legal candidates."}] if decision_context.no_progress_signals else [])
            ),
        )
        return ControllerChoice(intent=intent, record=record)

    def choose_reaction(self, reaction_context: ReactionContext) -> ReactionChoice:
        from .ai_tactics import dao_note
        rid = reaction_context.reaction_source_id
        rule = reaction_context.policy.reaction_rules.get(rid, {})
        pending = int(reaction_context.pending_damage or 0)
        # No printed generic reaction has an eight-damage minimum. An explicit
        # character policy may reserve a reaction; otherwise score every legal
        # trigger, including non-damage reactions such as opportunity attacks.
        minimum = int(rule.get("minimum_packet", 0))
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
        if reaction_context.extension_choice is not None:
            spec = reaction_context.extension_choice
            use = spec.automatic_use or not spec.allow_decline
            ordered = (*spec.preferred_option_ids, *(o for o in spec.option_ids if o not in spec.preferred_option_ids))
            selected_reaction_options = tuple(ordered[:spec.maximum_selections]) if use else ()
            spend = 0
        use_score = pending * 10 + (1000 if use and pending else 0)
        decline_score = 0 if pending < minimum else -pending * 3
        if not use:
            # Explicit reservations, resource requirements and extension vetoes
            # belong in the recorded score too, never a hidden final override.
            use_score = min(use_score, decline_score - 1)
        if reaction_context.extension_choice is None:
            use = use_score >= decline_score
        if not use:
            spend = 0
            selected_reaction_options = ()
        decision = ReactionDecision(
            checkpoint=reaction_context.checkpoint,
            reactor_id=reaction_context.reactor_id,
            reaction_source_id=rid,
            selection="USE" if use else "DECLINE",
            spend=spend,
            option_ids=selected_reaction_options,
        )
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
            deterministic_tie_break="highest integer score with typed policy constraints, USE on ties, then minimum sufficient legal spend",
            explanation=dao_note(reaction_context) + f". {decision.selection} reaction for visible pending damage {pending}.",
            fallback_policy_used=reaction_context.policy.generic_fallback,
            diagnostics=(),
        )
        return ReactionChoice(decision=decision, record=record)
