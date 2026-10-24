"""Dao-first MASTERMIND proposals from a detached, perceived decision only.

Play preconditions and goal features describe estimates, never legality. Every
legal plan remains scored; embeddings only order proposals and add a bounded
goal-fit preference. Only the native engine may execute the selected intent.
"""
from functools import lru_cache
import json
from pathlib import Path

from .ai_tactics import TurnPlan, _distance
from .relations import relation, ENEMY, ALLY
from . import embedding_rank

# Tags are generic Dao-policy levers, not sphere/character/ability identifiers.
DAO_LEVERS = {
    "pressure": ("immediate_effect", "focus_fire"),
    "finish": ("finish", "focus_fire"),
    "control": ("position", "avoidable_risk"),
    "setup": ("resource_use", "character_policy"),
    "mobility": ("position", "flight"),
    "deception": ("cover", "surround_avoid"),
    "terrain": ("position", "cover"),
    "guard": ("survival", "cover"),
    "support": ("ally_support",),
    "endurance": ("resource_use", "survival"),
}


@lru_cache(maxsize=1)
def library():
    return tuple(json.loads(Path(__file__).with_suffix(".json").read_text()))


def candidate_view(candidate, actions=None):
    """Concrete planner estimate; never changes native candidate/aim authority.

    Mastermind may supply owned action facts to reject a generic placement
    damage hint for a structured zone with no damage effect. Tricky and native
    placement/rollout identity matching retain the original view by default.
    """
    evaluation = candidate.metadata.get("placement_evaluation")
    if evaluation:
        from .gate2_runtime_models import LegalCandidate
        candidate = LegalCandidate.model_validate(evaluation)
    if actions and actions.get(candidate.source_definition_id, {}).get("non_damage_zone"):
        candidate = candidate.model_copy(update={"metadata": {**candidate.metadata, "expected_damage": 0}})
    return candidate


class Situation:
    """One creature's own sheet, personally projected roster and offered options."""
    def __init__(self, context, plan=None):
        self.context = context
        self.plan = plan if plan is not None else TurnPlan(context)
        self.actor = self.plan.actor
        self.foes, self.allies = self.plan.foes, self.plan.allies
        self.actions = context.tactics.get("actions", {})
        self.candidates = [candidate_view(c, self.actions) for c in context.legal_candidates]
        self.located = set(context.tactics.get("located_hostiles", ()))
        self.foes = [a for a in self.foes if a.entity_id in self.located]
        # Opponent roles must be observed in the filtered journal; never read
        # an enemy's private sheet/action catalogue to label a healer/summoner.
        self.supporters, self.summoners = set(), set()
        for event in context.recent_events:
            aid = event.get("actor_id")
            kind = event.get("event_type", "")
            if kind in {"HEALING_APPLIED", "HP_RESTORED", "HEALED"}:
                self.supporters.add(aid)
            if kind in {"SUMMON_APPEARED"}:
                self.summoners.add(aid)
        offered = {c.source_definition_id for c in self.candidates
                   if not c.metadata.get("placement_ai_unavailable")}
        available = {aid: info for aid, info in self.actions.items()
                     if aid in offered and info.get("ready", True)}
        self.facts = {
            "foes": bool(self.foes), "multiple": len(self.foes) > 1,
            "ally": bool(self.allies), "outnumbered": len(self.foes) > len(self.allies) + 1,
            "critical": self.actor.current_hp * 4 <= self.actor.maximum_hp,
            "strike": self.plan.has_strike, "ranged": self.plan.attack_range > 5,
            "moves": any(c.kind == "MOVE" for c in self.candidates),
            "control": any(i.get("control") or i.get("area_control") or i.get("reaction_denial")
                           for i in available.values()),
            "setup": any(i.get("setup") and aid not in context.tactics.get("active_sources", ())
                         for aid, i in available.items()),
            "flight": any(c.metadata.get("movement_mode") == "fly" for c in self.candidates),
            "recovery": any(c.metadata.get("useful_recovery") for c in self.candidates),
            "wounded_ally": any(a.current_hp * 2 < a.maximum_hp for a in self.allies),
            "reaction": any(a.reaction_available for a in self.foes),
            "concentrating": any(a.concentration_source_id for a in self.foes),
            "supporter": any(a.entity_id in self.supporters for a in self.foes),
            "summoner": any(a.entity_id in self.summoners for a in self.allies),
            "area": any(c.metadata.get("hostiles_in_area", 0) > 1 for c in self.candidates),
            "terrain_action": any(i.get("terrain") for i in available.values()),
            "hazard": any(c.metadata.get("hazard_exposure") or c.metadata.get("zone_hazard_exposure")
                          for c in self.candidates),
            "cover": any(c.metadata.get("cover_from_nearest_hostile") for c in self.candidates),
            "unlocated": not self.foes,
        }
        # A catalogue entry is not a remaining follow-up. A burst/setup goal
        # must still have a real attack to enable in this native decision.
        self.facts["followup"] = self.plan.has_strike
        self.facts["escape"] = self.facts["moves"] and (self.facts["ranged"] or self.facts["recovery"])
        # Immutable decision facts shared by every candidate/option. No cache
        # survives a native step, so movement, resources and knowledge stay fresh.
        self.before_range = self.plan.range_error(self.actor.position)
        self.nearest_before = min((_distance(self.actor.position, a.position) for a in self.foes), default=0)
        self._positions = {}
        self._features = {}

    def text(self):
        # No match seed, global state version, unfiltered events or hidden roster.
        actors = "; ".join(
            f"{a.display_name} at ({a.position.x}, {a.position.y}, {a.position.z}), "
            f"{'currently located' if a.entity_id in self.located else 'remembered or friendly'}"
            for a in self.context.actors if a.entity_id != self.actor.entity_id)
        facts = ", ".join(key.replace("_", " ") for key, yes in self.facts.items() if yes)
        return (f"Dao goals: {self.context.policy.goal_description}. "
                f"My health {self.actor.current_hp}/{self.actor.maximum_hp}; "
                f"my attack reach {self.plan.attack_range} feet. Perceived: {actors}. Situation: {facts}.")

    def dao_fit(self, play):
        weights = self.context.policy.weights
        return sum(sum(weights.get(key, 0) for key in DAO_LEVERS[tag]) * 10 // len(DAO_LEVERS[tag])
                   for tag in play["dao_tags"]) // len(play["dao_tags"])

    def proposals(self, client=None, *, rank=True):
        eligible = [p for p in library() if all(self.facts.get(k, False) for k in p["requires"])]
        # No-information turns still have a named, honest search play.
        if not eligible:
            # No actionable play remains, rather than falsely claiming a
            # search/control precondition on an exhausted or inactive turn.
            return [{"id": "hold", "name": "Keep the next opening",
                     "description": "No useful step remains; wait for the next turn.",
                     "requires": [], "dao_tags": ["endurance"], "goal": {}}]
        eligible.sort(key=lambda p: (-self.dao_fit(p), p["id"]))
        if not rank:
            return eligible[:3]  # deadline fallback: same Dao/precondition order
        if client is None:
            from .menu_rank import default_client
            client = default_client()
        options = [(p["id"], p["name"] + ". " + p["description"]) for p in eligible]
        # Dao fit always decides before embedding similarity. Bucketing admits
        # similar Dao priorities, never promotes an incompatible proposal.
        order = embedding_rank.rank_options(self.text(), options, client=client,
            tactical_provider=lambda _: {p["id"]: self.dao_fit(p) // 10 for p in eligible})
        by_id = {p["id"]: p for p in eligible}
        return [by_id[pid] for pid in order[:3]]

    def features(self, candidate):
        if candidate.candidate_id in self._features:
            return self._features[candidate.candidate_id]
        c = candidate_view(candidate, self.actions)
        info = self.actions.get(c.source_definition_id, {})
        target = next((a for a in self.foes if a.entity_id in c.target_ids), None)
        damage = int(c.metadata.get("expected_damage", info.get("damage", 0)) or 0)
        if c.metadata.get("target_knowledge") == "LAST_OBSERVED":
            damage = 0
        control = int(c.metadata.get("rider_utility", info.get("control", 0)) or 0)
        # A supported reaction-denial effect has value even when the generic
        # rider estimator gives it zero. This is an estimate of a possible
        # reply, never a read of the opponent\'s private reaction catalogue.
        reaction_control = bool(target and info.get("reaction_denial")
                                and c.metadata.get("target_knowledge") != "LAST_OBSERVED")
        if reaction_control:
            control = max(control, 4)
        destination = c.destination or self.actor.position
        before = self.before_range
        position_key = (destination.x, destination.y, destination.z)
        if position_key not in self._positions:
            self._positions[position_key] = (
                self.plan.range_error(destination),
                min((_distance(destination, a.position) for a in self.foes), default=0))
        after, nearest_after = self._positions[position_key]
        cost = sum(int(cost) for _, cost in info.get("costs", ()))
        recovery = sum(int(r["healing_hp"]) + int(r["temporary_hp"])
                       for r in c.metadata.get("useful_recovery", ()))
        nearest_before = self.nearest_before
        focus = target or self.plan.focus
        flank = bool(focus and _distance(destination, focus.position) <= 5 and any(
            _distance(a.position, focus.position) <= 5 and
            (a.position.x - focus.position.x) * (destination.x - focus.position.x) +
            (a.position.y - focus.position.y) * (destination.y - focus.position.y) < 0 for a in self.allies))
        hazardous = bool(c.metadata.get("hazard_exposure") or c.metadata.get("zone_hazard_exposure"))
        # Goal fit must not buy extra damage by forgetting a printed self
        # cost already charged by the base scorer (e.g. Overheat).
        own_damage = int(c.metadata.get("self_expected_damage") or 0) if c.metadata.get("self_harm") else 0
        useful_damage = max(0, damage - own_damage)
        features = {
            "damage": min(30, useful_damage), "control": min(20, control),
            "finish": (max(0, 20 - target.current_hp * 20 // max(1, target.maximum_hp))
                       if target and damage else 0),
            "spend": min(8, cost) if useful_damage and own_damage < self.actor.current_hp + self.actor.temporary_hp else 0,
            "economy": max(0, 8 - cost) if damage else 0,
            "area": max(0, int(c.metadata.get("hostiles_in_area", 0)) - 1) * 8,
            "setup": 8 if info.get("setup") and c.source_definition_id not in
                     self.context.tactics.get("active_sources", ()) else 0,
            "terrain": 8 if info.get("terrain") else 0,
            "reaction_control": max(8, min(16, control)) if reaction_control else 0,
            "supporter": 12 if target and target.entity_id in self.supporters else 0,
            "concentration": 12 if target and target.concentration_source_id and damage else 0,
            "recovery": min(20, recovery),
            "range": max(-10, min(10, (before - after) // 5)),
            "distance": max(-6, min(6, (nearest_after - nearest_before) // 5)),
            "cover": 8 if c.metadata.get("cover_from_nearest_hostile") else 0,
            "height": min(6, max(0, destination.z - self.actor.position.z))
                      if c.metadata.get("movement_mode") == "fly" and not after else 0,
            "flank": 8 if flank and c.kind == "MOVE" else 0,
            "hazard_wall": 8 if c.kind == "MOVE" and not hazardous and nearest_after > nearest_before else 0,
            "protect": sum(4 for a in self.allies if a.entity_id in self.summoners
                           and _distance(destination, a.position) <= 10) if c.kind == "MOVE" else 0,
            "rescue": sum(4 for a in self.allies if target and a.current_hp * 2 < a.maximum_hp
                          and _distance(a.position, target.position) <= 5),
            "search": 12 if c.candidate_id == self.context.search_move_candidate_id else 0,
        }

        self._features[candidate.candidate_id] = features
        return features

    def fit(self, play, features):
        return sum(features.get(key, 0) * weight for key, weight in play["goal"].items())
