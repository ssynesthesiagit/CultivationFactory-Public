"""Dao-first Tricky turn scoring, without engine access or speculative legality.

Projection seam: owned_profile(engine, actor) reads ONLY the acting creature's
abilities/resources/ongoing effects. DecisionContext carries that detached data.
Planner seam: TurnPlan(context).score(candidate, legacy_score) evaluates every
legal option using only that profile and the perception-filtered context.
No engine clone, transport, hidden roster, random sampling or menu truncation.

Action, bonus-action and movement share the same focus, resource allowance and
best affordable attack range. Setup is sequenced ahead of its follow-up; every
step is re-planned after native execution, rather than issuing speculative
intents. Reactions retain the existing native trigger/extension policy; resource
allowance reserves their printed price. P2 can rank verified plans here for
MASTERMIND; until then it explicitly falls back to this same Tricky plan.
"""
from .gate4_models import ComponentScore
from .relations import relation, ENEMY, ALLY
from .gate2_grid import SquareGrid
from .ai_tiers import effective_tier


def _effects(rows):
    """Every effect row, nested ones included. A nested key holds a list of effect rows; a bare value such as the
    end_effect's own `on_success: "suppress"` is a setting, not a row, so it is not descended into."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        yield row
        for key in ("on_hit", "effects", "on_fail", "on_success"):
            nested = row.get(key)
            if isinstance(nested, list):
                yield from _effects(nested)


def _one_hostile(value):
    """Scoring-only recipient projection for one perceived hostile in an area.

    Reuses rider_value's supported semantics; never alters execution, counts
    allies as hostile, or claims an unobserved area contains a creature.
    """
    if isinstance(value, list):
        return [_one_hostile(row) for row in value]
    if isinstance(value, dict):
        return {key: ("target" if key == "applies_to" and item in
                      ("creatures_in_area", "enemies_in_area") else _one_hostile(item))
                for key, item in value.items()}
    return value


def _own_prerequisites(engine, actor, action):
    """Range-planning readiness from own state, never a legality substitute.

    Mirrors the native prerequisite gates the planner can see from its own
    creature: turn flags, disabled weapons, a taken weapon the creature still
    holds, and hand/grip possession. A stowed or lost weapon must not set the
    turn's range. Native candidate generation and execution remain the only
    legal authority.

    A declared condition requirement is read with the engine's own matcher
    (combat/condition_requirements.py), so a plain printed name such as "prone"
    matches the carried condition:typed.prone or condition:core.prone exactly as
    the table does; the two must never disagree about whether an action is ready.
    """
    from .condition_requirements import condition_present
    from .ext.hand_occupancy import weapon_allowed
    params = action.parameters
    required = params.get("requires_condition")
    absent = params.get("requires_absent_condition")
    flags = [*params.get("requires_turn_flags", ())]
    if params.get("requires_turn_flag"):
        flags.append(params["requires_turn_flag"])
    held = params.get("requires_held_weapon")
    if held and not any(c.data.get("disables_action") == held and c.data.get("held_by") == actor.entity_id
                        for other in engine.state.actors.values() for c in other.conditions.values()):
        return False
    return not (
        (required and not condition_present(actor, required)) or (absent and condition_present(actor, absent))
        or any(not actor.turn_flags.get(flag) for flag in flags)
        or (params.get("blocked_by_turn_flag") and actor.turn_flags.get(params["blocked_by_turn_flag"]))
        or any(c.data.get("disables_action") == action.source_definition_id.split("#")[0]
               for c in actor.conditions.values())
        or weapon_allowed(engine, actor, action) is False
        or any(actor.resources.get(rid, 0) < int(amount)
               for rid, amount in params.get("requires_resource", {}).items()))


# Effect rows that actually deliver damage. A compiled row may carry an
# expected_damage price for the planner without striking at all (Pick up the
# disarmed weapon is priced at the weapon's damage), so the damage number alone
# cannot decide whether a row is an attack.
STRIKE_KINDS = frozenset({"attack", "save", "damage", "conditional_damage",
                          "extra_damage", "half_damage", "arc_damage"})
# A plug-in damaging action whose handler delivers damage through its own effect
# kind (not in STRIKE_KINDS) declares that fact on its compiled parameters with
# delivers_strike=True. Recovery and utility rows never declare it, so a priced
# recovery row stays non-attack, while every custom attack keeps its real reach.


def owned_profile(engine, actor, known_actors=(), candidates=()):
    """Own-sheet and current cover receipt, using only the projected known roster."""
    from .target_knowledge import located
    from .directional_cover import tactical_cover
    foes = [a for a in known_actors if a.active and relation(engine, actor, a) == ENEMY
            and located(engine, actor, engine.state.actors[a.entity_id])]
    nearest = min(foes, key=lambda a: (_distance(actor.position, a.position), a.entity_id), default=None)
    # Cover is a geometric estimate, not knowledge of an opponent's hidden
    # weapon list. Supply a generic sight-line descriptor instead of asking
    # attack_provenance to inspect that creature's build.
    from .attack_provenance import describe
    line = describe(engine, nearest, {"range_ft": 10000, "parameters": {}},
                    "ai:perceived_line") if nearest else None
    cover = tactical_cover(engine, nearest, actor, actor.position, (line,)) if nearest else 0
    from . import loadout
    actions = {}
    offered = {c.source_definition_id for c in candidates if c.actor_id == actor.entity_id}
    # Augment variants the chosen loadout does not currently offer are not options.
    hidden = loadout.hidden(engine, actor)
    sources = dict.fromkeys((*actor.action_ids, *offered))
    for aid in sources:
        if aid in hidden and aid not in offered:
            continue
        action = engine.action_catalog.get(aid)
        if action is None or action.parameters.get("inert") or action.parameters.get("player_only"):
            continue
        typed = action.parameters.get("typed") or {}
        effects = list(_effects(typed.get("effects") or ()))
        damage = action.parameters.get("expected_damage")
        if damage is None:
            d = action.damage
            damage = (d.count * (d.sides + 1) // 2 + d.modifier) * action.attack_count if d else 0
        utility = int(action.parameters.get("rider_utility") or 0)
        kinds = {e.get("type") for e in effects}
        conditions = [e.get("condition") or e.get("condition_id") for e in effects if e.get("type") == "condition"]
        # Only source-backed effect categories, never ability-name heuristics.
        control = utility
        area_control = 0
        if damage and (typed.get("area") or action.radius_ft):
            from .rider_value import estimate_rider_utility
            area_control = estimate_rider_utility(_one_hostile(typed), target_kind="HOSTILE_ENTITY",
                                                 economy=action.economy.value)
        hit_percent = (75 if any(e.get("type") == "half_damage" for e in effects) else 50) if "save" in kinds else (65 if "attack" in kinds or action.attack_bonus is not None else 100)
        setup = bool(not damage and action.target_kind == "SELF" and
                     kinds & {"condition", "modifier", "weapon_buff", "buff"})
        # Recovery and utility rows (Pick up, Escape a grapple) keep their damage
        # price for scoring but must never become the turn's attack: their
        # nominal reach would plan the turn's movement and pull the fighter into
        # contact instead of using the strike it already has from here.
        strike = bool(damage) and (action.damage is not None or action.attack_bonus is not None
                                   or bool(kinds & STRIKE_KINDS)
                                   or bool(action.parameters.get("delivers_strike")))
        actions[aid] = {
            "damage": max(0, int(damage)), "attack": strike, "control": control,
            "area_control": area_control, "hit_percent": hit_percent,
            "ready": _own_prerequisites(engine, actor, action),
            "range": int(action.range_ft or action.reach_ft or 5),
            "attack_bonus": (action.attack_bonus if action.attack_bonus is not None else
                             ((typed.get("numbers") or {}).get("attack_bonus") if "attack" in kinds else None)),
            "costs": [list(pair) for pair in action.costs],
            "economy": action.economy.value, "setup": setup,
            "defense": action.resolution_kind == "DODGE",
            "guard": action.resolution_kind in {"DODGE", "DISENGAGE"},
            "conditions": [c for c in conditions if isinstance(c, str)],
        }
    active = {c.source_definition_id for c in actor.conditions.values()}
    active.update(m.source_definition_id for m in actor.modifiers.values() if not m.consumed)
    if actor.concentration:
        active.add(actor.concentration.source_definition_id)
    # Own reaction prices only; nothing about unseen attackers.
    reserve = {}
    if actor.reaction_available:
        for rid in actor.reaction_ids:
            action = engine.action_catalog.get(rid)
            if action:
                for resource, cost in action.costs:
                    reserve[resource] = max(reserve.get(resource, 0), cost)
    return {"tier": effective_tier(actor, getattr(engine, "ai_tier_overrides", {})),
            "actions": actions, "maximums": dict(actor.resource_maximums),
            "active_sources": sorted(active), "reaction_reserve": reserve, "current_cover": int(cover),
            "located_hostiles": sorted(a.entity_id for a in foes)}


def dao_note(context):
    dao = next((r for r in context.policy.role if r.startswith("Dao:")), None)
    return dao or "Dao: no Sphere profile; general combat tactics"


def choice_explanation(context, candidate, score):
    """Plain decision receipt; numeric accounting stays in structured scores."""
    if candidate.kind == "MOVE":
        purpose = "improve attack range, cover or safety"
    elif candidate.kind in {"END_TURN", "HOLD_POSITION"}:
        purpose = "no better attack or useful move remains"
    elif any(p.component == "tactics" for p in score.components):
        info = context.tactics.get("actions", {}).get(candidate.source_definition_id, {})
        count = int(candidate.metadata.get("hostiles_in_area") or 0)
        if count:
            purpose = f"affects {count} {'enemy' if count == 1 else 'enemies'}; best damage and useful effects for this turn"
        elif info.get("damage"):
            purpose = "best damage and useful effects for the resources left"
        elif info.get("defense"):
            purpose = "protect yourself until your next turn while no useful attack is offered"
        else:
            purpose = "prepare a useful effect or help a creature that needs it"
    else:
        purpose = "follow this creature's combat priorities"
    return f"{dao_note(context)}. Chose {candidate.display_name}: {purpose}."


def _distance(a, b):
    return SquareGrid.distance_cells(a, b) * 5


class TurnPlan:
    """One immutable decision's joint goals, reused for all candidates/options."""
    def __init__(self, context):
        self.context = context
        self.profile = context.tactics
        self.enabled = bool(self.profile) and not context.bystander
        self.actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
        p = context.policy
        resource = p.stress_resource or {}
        maximum = int(resource.get("maximum") or 0)
        current = self.actor.resources.get(resource.get("resource_id"), maximum)
        triggers = p.stress_triggers or {}
        stressed = (self.actor.current_hp * 100 <= self.actor.maximum_hp * triggers.get("hp_pct", 0)
                    or maximum and current * 100 <= maximum * triggers.get("resource_pct", 0))
        self.weights = (p.stress_weights if stressed else None) or p.weights
        self.bands = (p.stress_range_bands_ft if stressed else None) or p.preferred_range_bands_ft or ((5, 30),)
        self.foes = [a for a in context.actors if a.active and relation(context, self.actor, a) == ENEMY]
        self.allies = [a for a in context.actors if a.active and a.entity_id != self.actor.entity_id
                       and relation(context, self.actor, a) == ALLY]
        self.actions = self.profile.get("actions", {})
        self._resource_prices = {}
        self._conflicts = {}
        self.low = self.actor.current_hp * 100 <= self.actor.maximum_hp * int(p.low_hp_behavior.get("critical_defense", 20))
        self.focus = max(self.foes, key=lambda a: (self.target_value(a), a.entity_id), default=None)
        attacks = [(self.ability_value(info), aid, info) for aid, info in self.actions.items()
                   if info["damage"] and info.get("attack", True) and info.get("ready", True)
                   and self.affordable(info)
                   and ((info["economy"] == "ACTION" and self.actor.action_available)
                        or (info["economy"] == "BONUS_ACTION" and self.actor.bonus_action_available))]
        # When attacks are spent, retain the owned best range for next turn.
        if not attacks:
            attacks = [(self.ability_value(info), aid, info) for aid, info in self.actions.items()
                       if info["damage"] and info.get("attack", True) and info.get("ready", True)
                       and info["economy"] in {"ACTION", "BONUS_ACTION"} and self.affordable(info)]
        best = max(attacks, default=None, key=lambda row: (row[0], row[1]))
        self.attack_range = best[2]["range"] if best else self.bands[0][1]
        self.best_attack_value = best[0] if best else 0
        self.best_attack_id = best[1] if best else None
        # A guard should yield only when a legal move can actually put the best
        # owned strike in reach this turn. With no movement left (or a foe too
        # far away) ending the turn guarded is the right play; dashing into
        # reach without the action to strike just hands over a free attack.
        self.reaches_this_turn = bool(self.focus) and any(
            c.kind == "MOVE" and c.destination is not None and self.range_error(c.destination) == 0
            for c in context.legal_candidates)
        # Strikes offered from the current square: a move that enables an owned strike the
        # square cannot offer is the enabling follow-up, even when another strike is offered.
        self.offered_strikes = {c.source_definition_id for c in context.legal_candidates
                                if c.kind in {"ACTION", "BONUS_ACTION"}
                                and self.actions.get(c.source_definition_id, {}).get("damage")
                                and self.actions[c.source_definition_id].get("attack", True)
                                and not c.metadata.get("placement_ai_unavailable")
                                and c.metadata.get("target_knowledge") != "LAST_OBSERVED"}
        # Offered strikes, for joint action+bonus resource conflicts (targets are scored per candidate).
        # Resource conflicts depend on ability/economy, not on its many legal
        # aims. Retain every candidate in the controller; share only this fact.
        unique_offers = {}
        for c in context.legal_candidates:
            if (c.kind in {"ACTION", "BONUS_ACTION"} and c.source_definition_id in self.actions
                    and self.actions[c.source_definition_id]["damage"]
                    and self.actions[c.source_definition_id].get("attack", True)
                    and not c.metadata.get("placement_ai_unavailable")
                    and c.metadata.get("target_knowledge") != "LAST_OBSERVED"):
                unique_offers.setdefault((c.kind, c.source_definition_id), (c, self.actions[c.source_definition_id]))
        self.offers = tuple(unique_offers.values())
        self.has_strike = any(c.kind in {"ACTION", "BONUS_ACTION"} and
                              (self.actions.get(c.source_definition_id, {}).get("attack")
                               if c.source_definition_id in self.actions
                               and self.actions[c.source_definition_id].get("attack") is not None
                               else bool(c.metadata.get("expected_damage")))
                              and not c.metadata.get("placement_ai_unavailable")
                              and c.metadata.get("target_knowledge") != "LAST_OBSERVED"
                              for c in context.legal_candidates)

    def affordable(self, info):
        return all(self.actor.resources.get(rid, 0) >= cost for rid, cost in info["costs"])

    def target_value(self, target):
        # Only personally perceived/projected facts; no catalogue enemy builds.
        p = self.context.policy
        wound = (target.maximum_hp - target.current_hp) * 100 // max(1, target.maximum_hp)
        value = wound * p.target_priorities.get("LOW_HP_PRIMARY", 20) // 100
        if target.entity_id == self.context.team_behavior.focus_target_id:
            value += p.target_priorities.get("FOCUS_TARGET", 12)
        if target.concentration_source_id:
            value += self.weights.get("finish", 1)
        # A threatening foe adjacent to a wounded perceived friend merits pressure.
        value += sum(self.weights.get("ally_support", 1) for ally in self.allies
                     if ally.current_hp * 2 < ally.maximum_hp and _distance(ally.position, target.position) <= 5)
        return value - _distance(self.actor.position, target.position) // 15

    def resource_price(self, info):
        key = tuple(tuple(pair) for pair in info.get("costs", ()))
        if key in self._resource_prices:
            return self._resource_prices[key]
        penalty = 0
        for rid, cost in info.get("costs", ()):
            current = self.actor.resources.get(rid, 0)
            maximum = self.profile.get("maximums", {}).get(rid, current)
            # Four-round soft fight budget. Reaction reservation is soft too:
            # a decisive finishing attack can still spend it.
            turns = max(1, 5 - self.context.round_number)
            allowance = max(1, current // turns)
            reserve = max(self.context.policy.resource_reserves.get(rid, 0),
                          self.profile.get("reaction_reserve", {}).get(rid, 0))
            penalty += cost + max(0, cost - allowance) * 2
            if current - cost < reserve:
                penalty += min(6, maximum)
        price = penalty * self.weights.get("resource_use", 1)
        self._resource_prices[key] = price
        return price

    def rival_conflict(self, candidate):
        """Value an ACTION and a BONUS_ACTION forfeit when they share a resource pool and cannot both be paid.

        Only one of two competing strikes can be spent, so the weaker one's value is
        the opportunity cost of the stronger; the stronger keeps its margin.
        """
        key = (candidate.kind, candidate.source_definition_id)
        if key in self._conflicts:
            return self._conflicts[key]
        info = self.actions[candidate.source_definition_id]
        costs = {rid: int(cost) for rid, cost in info["costs"]}
        if not costs:
            return 0
        value = self.gross_value(info)
        worst = 0
        for other, rival_info in self.offers:
            if (other.kind == candidate.kind or other.source_definition_id == candidate.source_definition_id
                    or not {c.kind for c in (candidate, other)} == {"ACTION", "BONUS_ACTION"}):
                continue
            rival = {rid: int(cost) for rid, cost in rival_info["costs"]}
            shared = costs.keys() & rival.keys()
            if not shared or all(self.actor.resources.get(rid, 0) >= costs.get(rid, 0) + rival.get(rid, 0)
                                 for rid in shared):
                continue
            worst = max(worst, min(value, self.gross_value(rival_info)))
        self._conflicts[key] = worst
        return worst

    def ability_value(self, info, target=None):
        return self.gross_value(info, target) - self.resource_price(info)

    def gross_value(self, info, target=None):
        chance = info.get("hit_percent", 65)
        if target and target.armor_class and info.get("attack_bonus") is not None:
            chance = max(5, min(95, (21 + info["attack_bonus"] - target.armor_class) * 5))
        control_weight = self.context.policy.tactic_weights.get("control", self.weights.get("immediate_effect", 1))
        return (info.get("damage", 0) * chance * self.weights.get("immediate_effect", 1) // 100
                + info.get("control", 0) * control_weight)

    def range_error(self, position):
        if not self.focus:
            return 0
        distance = _distance(position, self.focus.position)
        # Dao positioning is authoritative, capped by the best affordable
        # attack's reach. It never buys an ideal Dao range with no attack.
        hi = min(self.attack_range, max(b[1] for b in self.bands))
        lo = min(hi, min(b[0] for b in self.bands))
        return max(0, lo - distance, distance - hi)

    def movement_value(self, candidate):
        if not candidate.destination or not self.focus:
            return -80
        before, after = self.range_error(self.actor.position), self.range_error(candidate.destination)
        value = (before - after) * max(1, self.weights.get("position", 1))
        # No reward for walking within an equally good band. Arrival can unlock
        # this turn's best action, but does not assert LoS/LoE legality.
        # Arrival into the best owned range is the enabling follow-up only when this square cannot offer that strike.
        if before and not after and self.actor.action_available and self.best_attack_id not in self.offered_strikes:
            value += max(0, self.best_attack_value)
        now = sum(_distance(self.actor.position, a.position) <= 5 for a in self.foes)
        then = sum(_distance(candidate.destination, a.position) <= 5 for a in self.foes)
        if self.low:
            value += (now - then) * self.context.policy.tactic_weights.get("withdraw", self.weights.get("survival", 1)) * 5
        value -= max(0, then - 1) * self.weights.get("surround_avoid", 1) * 4
        cover_gain = int(bool(candidate.metadata.get("cover_from_nearest_hostile"))) - int(bool(self.profile.get("current_cover")))
        value += cover_gain * self.weights.get("cover", 0) * 4
        # Flank only with a personally perceived friend on the opposite side.
        f = self.focus.position
        def flanks(dest):
            return _distance(dest, f) <= 5 and any(_distance(a.position, f) <= 5 and
                (a.position.x - f.x) * (dest.x - f.x) + (a.position.y - f.y) * (dest.y - f.y) < 0
                for a in self.allies)
        value += (int(flanks(candidate.destination)) - int(flanks(self.actor.position))) * self.weights.get("ally_support", 1)
        risk = self.weights.get("avoidable_risk", 1)
        value -= int(bool(candidate.metadata.get("hazard_exposure") or candidate.metadata.get("zone_hazard_exposure"))) * risk * 18
        value -= len(candidate.metadata.get("reaction_exposure", ())) * risk * 8
        return value - max(1, candidate.movement_cost_ft // 5)

    def with_self_followups(self, scores, candidates):
        """Compare safe move + remaining self action, not move vs action.

        Consumes the complete scored legal menu once. No future legality is
        invented: only a currently offered, position-independent self action
        is carried, and the native next decision rechecks it after the move.
        Zero-progress or hazardous moves never receive a follow-up bonus.
        """
        if not self.enabled or self.has_strike:
            return scores
        followups = {}
        for score in scores:
            c = candidates[score.candidate_id]
            # Preparation bonuses keep their existing before-movement priority.
            # Carry only an action; do not speculate that a setup bonus commutes.
            if (c.kind != "ACTION" or c.destination is not None
                    or self.actions.get(c.source_definition_id, {}).get("setup")
                    or c.metadata.get("placement_picker") or c.metadata.get("self_harm")
                    or any(t != self.actor.entity_id for t in c.target_ids)
                    or any(p.component in {"free_preparation", "posture", "placement_admission"} for p in score.components)
                    or self.actions.get(c.source_definition_id, {}).get("damage")
                    or c.metadata.get("expected_damage")):
                continue
            followups[c.kind] = max(followups.get(c.kind, 0), score.total)
        carry = sum(followups.values())
        if carry <= 0:
            return scores
        result = []
        for score in scores:
            c = candidates[score.candidate_id]
            safe = not (c.metadata.get("hazard_exposure") or c.metadata.get("zone_hazard_exposure")
                        or c.metadata.get("reaction_exposure"))
            if c.kind == "MOVE" and safe and score.total > 0:
                component = ComponentScore(component="move_then_self_action", value=carry,
                    explanation=dao_note(self.context) + ". Improve position safely, then keep the offered action for yourself.")
                score = score.model_copy(update={"total": score.total + carry,
                    "components": (*score.components, component)})
            result.append(score)
        return result

    def score(self, candidate, legacy):
        if not self.enabled:
            return legacy
        # Native safety, support expiry, search, standing and free setup remain
        # authoritative. Those short-circuit receipts must not be reweighted.
        protected = {"flight_support", "flight_expiry", "search_unknown_opponent", "posture",
                     "free_preparation", "placement_admission"}
        if any(c.component in protected for c in legacy.components):
            return legacy
        if candidate.metadata.get("placement_evaluation"):
            from .gate2_runtime_models import LegalCandidate
            preview = LegalCandidate.model_validate(candidate.metadata["placement_evaluation"])
            return self.score(preview, legacy).model_copy(update={"candidate_id": candidate.candidate_id})
        remove = set()
        value = 0
        reason = "Balance the Dao's effect, target, follow-up and remaining fight resources."
        if candidate.kind == "MOVE":
            # Native flight scoring already measures range/safety with actual
            # prospective geometry. Keep it rather than infer aerial reach.
            remove = {"position", "tactical_position", "avoidable_risk", "survival", "policy_sequence"}
            if candidate.metadata.get("flight_tactics"):
                from .gate4_controller import native_flight_position_value
                remove.remove("avoidable_risk")
                native = next((c.value for c in legacy.components if c.component == "flight_position"), 0)
                desired = native_flight_position_value(candidate, approach_melee=(
                    not self.has_strike and min(self.attack_range, max(hi for _, hi in self.bands)) <= 5
                    and (not self.low or not self.allies)))
                value = desired - native - max(1, candidate.movement_cost_ft // 5)
                if (self.actor.action_available and self.best_attack_value
                        and self.best_attack_id not in self.offered_strikes
                        and self.range_error(self.actor.position) > 0
                        and self.range_error(candidate.destination) == 0):
                    # Same enabling follow-up as movement_value: this route puts
                    # the best owned strike in reach while the current square
                    # cannot offer it, so the turn's attack rides on the move.
                    value += self.best_attack_value
                progress = (self.range_error(self.actor.position)
                            - self.range_error(candidate.destination))
                if value > 0 and progress <= 0 and not candidate.metadata.get("cover_from_nearest_hostile"):
                    # The approach reward is per candidate; without a per-turn
                    # memory it paid again for every one-square hop and
                    # altitude change, so a flier could shuffle in place for a
                    # whole turn. A positive flight value now requires closing
                    # the error to the best affordable attack (or gaining
                    # cover); otherwise it is a no-progress step.
                    value = -max(1, candidate.movement_cost_ft // 5)
                if candidate.metadata.get("zone_hazard_exposure") and not candidate.metadata.get("hazard_exposure"):
                    value -= 18 * self.weights.get("avoidable_risk", 1)
            else:
                value = self.movement_value(candidate)
            reason = "Move only to improve attack range, cover, an ally's flank, or safety."
        elif candidate.kind in {"END_TURN", "HOLD_POSITION"}:
            remove = {"policy_sequence"}
            value = -10 if candidate.kind == "HOLD_POSITION" else 0
        else:
            info = self.actions.get(candidate.source_definition_id)
            guard = bool(info and info.get("guard"))
            # No strike is offered only because the best attack is out of reach,
            # and there is no ally who could close instead. A guard then only
            # stalls the fight to the round cap (round-4 flier draws: both sides
            # at about 10 HP, ten feet apart, Dodging every turn). A creature
            # that clearly leads the HP race has no reason to force the
            # exchange, so it may keep the guard (round-4 melee seed 3: 50 vs
            # 15 HP, waiting kept the win while closing traded it away).
            ahead = bool(self.focus) and self.actor.current_hp * 4 >= self.focus.current_hp * 5
            closing = (guard and not self.has_strike and not self.allies
                       and self.range_error(self.actor.position) > 0 and not ahead
                       and self.reaches_this_turn)
            if guard and self.has_strike and not self.allies:
                # Alone on its side, guarding cannot win the fight: nobody else
                # will land the killing blow. Pressing the offered strike is the
                # only path to victory, so both the guard's policy priority and
                # the low-HP survival bonus must not outrank it. (Round-4 bench:
                # every melee/flier loss was Tricky guarding from about 40% HP
                # until it died without ever attacking again.)
                remove |= {"character_policy", "survival"}
            elif closing:
                remove |= {"character_policy", "survival"}
            elif guard and self.has_strike and not self.low:
                # The Dao's guard preference is a fallback for when nothing can
                # strike, or the creature is critical. While an attack is on
                # offer, the defensive action must not outrank it on priority.
                remove.add("character_policy")
            if info and info.get("defense") and not self.has_strike:
                # A blind Dash spends the attack before discovering whether a
                # creature is there. Explore with normal movement first (the
                # native search receipt retains priority), then protect yourself
                # until next turn instead of sprinting into an unknown attack.
                # Dao survival still determines how strongly to prefer this.
                if not closing:
                    value += 6 * self.weights.get("survival", 1)
                reason = "Protect yourself until your next turn; no useful attack is offered here."
            if info and (info["damage"] or info["control"] or info.get("area_control")
                         or info.get("setup") or candidate.metadata.get("useful_recovery") is not None):
                # Unknown native effects keep their existing estimate; a zero
                # own-sheet hint must not erase a supported control/area value.
                # Native option/placement receipts refine the owned ability's
                # estimate (e.g. number of perceived creatures in an area).
                info = {**info, "damage": int(candidate.metadata.get("expected_damage", info["damage"]) or 0),
                        "control": max(int(candidate.metadata.get("rider_utility", info["control"]) or 0),
                                       info.get("area_control", 0) if candidate.metadata.get("hostiles_in_area") else 0)}
                remove = {"immediate_effect", "resource_use", "rider_utility"}
                target = next((a for a in self.foes if a.entity_id in candidate.target_ids), None)
                if candidate.metadata.get("target_knowledge") == "LAST_OBSERVED":
                    # A remembered square is a possible aim, not a known hit,
                    # wounded foe or control target.
                    value = -self.resource_price(info)
                else:
                    value = self.ability_value(info, target)
                    if target:
                        value += self.target_value(target)
                    # Areas have a square aim, not target_ids. Price their
                    # actual known recipients as well: otherwise an affordable
                    # stronger release can never earn the Dao's finishing
                    # preference. Remembered creatures earn no HP prediction.
                    damage_by_id = candidate.metadata.get("hostile_damage_by_id", {})
                    for foe in self.foes:
                        if (foe.entity_id not in damage_by_id or
                                foe.entity_id not in self.profile.get("located_hostiles", ())):
                            continue
                        value += self.target_value(foe)
                        if damage_by_id[foe.entity_id] >= foe.current_hp + foe.temporary_hp:
                            value += 20 * self.weights.get("finish", 1) * info.get("hit_percent", 65) // 100
                    if info.get("setup"):
                        repeated = (candidate.source_definition_id in self.profile.get("active_sources", ())
                                    or any(c in self.actor.conditions for c in info.get("conditions", ())))
                        if repeated:
                            value = -1000
                            remove |= {"character_policy", "policy_sequence"}
                        elif self.actor.action_available and self.has_strike and candidate.kind == "BONUS_ACTION":
                            value += max(0, self.best_attack_value) + self.context.policy.tactic_weights.get("setup", self.weights.get("character_policy", 1))
                    support = candidate.metadata.get("useful_recovery") or ()
                    if support:
                        remove.add("ally_support")
                    value += sum((int(r["healing_hp"]) + int(r["temporary_hp"])) * (
                        self.weights.get("immediate_effect", 1) +
                        (self.weights.get("ally_support", 1) if r["target_id"] != self.actor.entity_id else 0))
                        for r in support)
        components = [c for c in legacy.components if c.component not in remove]
        components.append(ComponentScore(component="tactics", value=int(value),
                                         explanation=dao_note(self.context) + ". " + reason))
        if candidate.kind in {"ACTION", "BONUS_ACTION"} and self.actions.get(candidate.source_definition_id, {}).get("damage"):
            conflict = self.rival_conflict(candidate)
            if conflict:
                components.append(ComponentScore(component="joint_turn_conflict", value=-int(conflict),
                    explanation=dao_note(self.context) + ". A competing action or bonus strike uses the same resources this turn; only one can be paid."))
        return legacy.model_copy(update={"components": tuple(components), "total": sum(c.value for c in components)})
