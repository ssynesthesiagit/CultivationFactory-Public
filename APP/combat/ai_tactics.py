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
    for row in rows:
        yield row
        for key in ("on_hit", "effects", "on_fail", "on_success"):
            yield from _effects(row.get(key) or ())


def owned_profile(engine, actor, known_actors=()):
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
    actions = {}
    for aid in actor.action_ids:
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
        setup = bool(not damage and action.target_kind == "SELF" and
                     kinds & {"condition", "modifier", "weapon_buff", "buff"})
        actions[aid] = {
            "damage": max(0, int(damage)), "control": control,
            "range": int(action.range_ft or action.reach_ft or 5),
            "attack_bonus": (action.attack_bonus if action.attack_bonus is not None else
                             ((typed.get("numbers") or {}).get("attack_bonus") if "attack" in kinds else None)),
            "costs": [list(pair) for pair in action.costs],
            "economy": action.economy.value, "setup": setup,
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
            "active_sources": sorted(active), "reaction_reserve": reserve, "current_cover": int(cover)}


def dao_note(context):
    dao = next((r for r in context.policy.role if r.startswith("Dao:")), None)
    return dao or "Dao: no Sphere profile; general combat tactics"


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
        self.low = self.actor.current_hp * 100 <= self.actor.maximum_hp * int(p.low_hp_behavior.get("critical_defense", 20))
        self.focus = max(self.foes, key=lambda a: (self.target_value(a), a.entity_id), default=None)
        attacks = [(self.ability_value(info), aid, info) for aid, info in self.actions.items()
                   if info["damage"] and self.affordable(info)
                   and ((info["economy"] == "ACTION" and self.actor.action_available)
                        or (info["economy"] == "BONUS_ACTION" and self.actor.bonus_action_available))]
        # When attacks are spent, retain the owned best range for next turn.
        if not attacks:
            attacks = [(self.ability_value(info), aid, info) for aid, info in self.actions.items()
                       if info["damage"] and self.affordable(info)]
        best = max(attacks, default=None, key=lambda row: (row[0], row[1]))
        self.attack_range = best[2]["range"] if best else self.bands[0][1]
        self.best_attack_value = best[0] if best else 0
        self.has_strike = any(c.kind in {"ACTION", "BONUS_ACTION"} and
                              (self.actions.get(c.source_definition_id, {}).get("damage") or c.metadata.get("expected_damage"))
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
        return penalty * self.weights.get("resource_use", 1)

    def ability_value(self, info, target=None):
        chance = 65
        if target and target.armor_class and info.get("attack_bonus") is not None:
            chance = max(5, min(95, (21 + info["attack_bonus"] - target.armor_class) * 5))
        control_weight = self.context.policy.tactic_weights.get("control", self.weights.get("immediate_effect", 1))
        return (info.get("damage", 0) * chance * self.weights.get("immediate_effect", 1) // 100
                + info.get("control", 0) * control_weight - self.resource_price(info))

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
        if before and not after and self.actor.action_available and not self.has_strike:
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
        value -= int(bool(candidate.metadata.get("hazard_exposure"))) * risk * 18
        value -= len(candidate.metadata.get("reaction_exposure", ())) * risk * 8
        return value - max(1, candidate.movement_cost_ft // 5)

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
                    not self.has_strike and self.attack_range <= 5 and not self.low))
                value = desired - native - max(1, candidate.movement_cost_ft // 5)
            else:
                value = self.movement_value(candidate)
            reason = "Move only to improve attack range, cover, an ally's flank, or safety."
        elif candidate.kind in {"END_TURN", "HOLD_POSITION"}:
            remove = {"policy_sequence"}
            value = -10 if candidate.kind == "HOLD_POSITION" else 0
        else:
            info = self.actions.get(candidate.source_definition_id)
            if info:
                # Native option/placement receipts refine the owned ability's
                # estimate (e.g. number of perceived creatures in an area).
                info = {**info, "damage": int(candidate.metadata.get("expected_damage", info["damage"]) or 0),
                        "control": int(candidate.metadata.get("rider_utility", info["control"]) or 0)}
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
                    value += sum(int(r["healing_hp"]) + int(r["temporary_hp"]) for r in support) * self.weights.get("ally_support", 1)
        components = [c for c in legacy.components if c.component not in remove]
        components.append(ComponentScore(component="tricky_turn_plan", value=int(value),
                                         explanation=dao_note(self.context) + ". " + reason))
        return legacy.model_copy(update={"components": tuple(components), "total": sum(c.value for c in components)})
