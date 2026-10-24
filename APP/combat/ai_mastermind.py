"""MASTERMIND planner adapter: Dao plays, embedding goals and bounded rollouts.

TRICKY remains TurnPlan unchanged. This adapter is inert for bystanders and
uncommanded summons, which keep the existing instinct/command gates. It never
removes menu options or grants permission to execute a hypothetical action.
"""
import time

from .ai_tactics import TurnPlan
from .ai_plays import Situation, candidate_view
from .gate4_models import ComponentScore
from . import embedding_rank


# Budget on Tabik, conservatively scaled x1.5 for Swarmlord: 1.7 seconds
# plus 0.3 seconds for constructing/sorting the complete decision record.
# Native preparation is charged too; optional search never gets a fresh budget.
DECISION_SECONDS = 1.7
# Leave most of the decision for complete scoring and useful verification;
# placement previews are optional refinements of already-legal picker roots.
PREPARATION_SECONDS = .6
# Optional native annotations share the preparation allowance with placements.
FLIGHT_SECONDS = .35
LOOKAHEAD_K = 4


class MastermindPlan(TurnPlan):
    # Final fixed-seed ablation: all components won the most decided fights.
    # Keep that configuration; the acceptance gate still diagnoses any shortfall.
    use_embeddings = True
    use_lookahead = True

    def __init__(self, context):
        self.deadline = time.monotonic() + max(0, DECISION_SECONDS - context.preparation_ns / 1e9)
        super().__init__(context)
        # A harmless zone can carry a generic placement damage hint. It is not
        # a remaining strike that can justify a burst or attack-range goal.
        self.has_strike = any(c.kind in {"ACTION", "BONUS_ACTION"}
            and (self.actions.get(c.source_definition_id, {}).get("damage") or c.metadata.get("expected_damage"))
            and not c.metadata.get("placement_ai_unavailable")
            and c.metadata.get("target_knowledge") != "LAST_OBSERVED"
            for c in (candidate_view(c, self.actions) for c in context.legal_candidates))
        self.situation = Situation(context, plan=self)
        self.plays = self.situation.proposals(rank=self.use_embeddings and not context.tactics.get("projection")
                                             and time.monotonic() < self.deadline)
        self.play = self.plays[0]
        # Die-hard is not a global stress-policy change. Only this planner
        # relinquishes Tricky's low-HP withdrawal unless its selected play says so.
        self.low = self.low and self.play["id"] == "retreat"
        self.features = {}

    def resource_price(self, info):
        # Commit affordable resources, still account for later joint actions.
        return sum(int(cost) for _, cost in info.get("costs", ())) * max(
            1, self.context.policy.weights.get("resource_use", 1)) // 4

    def score(self, candidate, legacy):
        # Resolve a lazy placement once before entering the base scorer. Its
        # recursive self.score call would otherwise add the subclass goal twice.
        view = candidate_view(candidate, self.actions)
        if self.actions.get(candidate.source_definition_id, {}).get("non_damage_zone"):
            # Keep real control/support components, but neither damage nor a
            # finishing-blow prediction can come from a harmless zone hint.
            parts = tuple(p for p in legacy.components
                          if p.component not in {"immediate_effect", "defeat_prevention_or_finish"})
            legacy = legacy.model_copy(update={"components": parts, "total": sum(p.value for p in parts)})
        score = super().score(view, legacy).model_copy(
            update={"candidate_id": candidate.candidate_id})
        # Native flight safety, free preparation and search priorities remain
        # authoritative; plays cannot promote an unsafe route over those gates.
        protected = {"flight_support", "flight_expiry", "posture",
                     "placement_admission", "free_preparation", "search_unknown_opponent"}
        features = self.situation.features(candidate)
        self.features[candidate.candidate_id] = features
        play = max(self.plays, key=lambda p: (self.situation.fit(p, features),
                                             -self.plays.index(p)))
        value = self.situation.fit(play, features) // 3
        if any(p.component in protected for p in legacy.components):
            value = 0
        # Never spend a turn merely guarding when an effective strike exists,
        # unless the explicit withdrawal strategy calls for it.
        info = self.actions.get(candidate.source_definition_id, {})
        if info.get("defense") and self.has_strike and self.play["id"] != "retreat":
            value -= 40
        why = ("No useful step remains; keep this goal for the next turn."
               if candidate.kind in {"END_TURN", "HOLD_POSITION"} else play["description"])
        receipt = ComponentScore(component="mastermind_play", value=int(value),
            explanation=f"Play: {play['name']} — {why}")
        return score.model_copy(update={"components": (*score.components, receipt),
                                        "total": score.total + value})

    def with_self_followups(self, scores, candidates):
        scores = super().with_self_followups(scores, candidates)
        ordered = sorted(scores, key=lambda s: (-s.total, s.candidate_id, s.option_ids))
        # Every legal option is scored above. Search width, not menu reachability,
        # is bounded. Seed with diverse source/target/endpoint plans, not hashes.
        shortlist, seen = [], set()
        for score in ordered:
            c = candidates[score.candidate_id]
            key = (c.source_definition_id, c.target_ids, c.destination, score.option_ids)
            if key not in seen:
                seen.add(key)
                shortlist.append(score)
            if len(shortlist) == LOOKAHEAD_K:
                break
        # Second embedding stage: fit the legal plan descriptions to the Dao
        # proposal goals. Cached/background CPU client cannot hold up a turn.
        if (not self.use_lookahead or self.context.tactics.get("projection")
                or time.monotonic() >= self.deadline):
            return scores  # complete legal-menu fallback, never a truncated menu
        from .menu_rank import default_client
        options = [(str(i), candidates[s.candidate_id].display_name + ". " +
                    str(self.features.get(s.candidate_id, {}))) for i, s in enumerate(shortlist)]
        order = (embedding_rank.rank_options(
            " ".join(p["name"] + ": " + p["description"] for p in self.plays),
            options, client=default_client()) if self.use_embeddings else [str(i) for i in range(len(shortlist))])
        ranked = [shortlist[int(i)] for i in order]
        from .ai_lookahead import verify, ROLLOUT_SECONDS
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return scores
        outcomes = verify(self.context, ranked, candidates, budget=min(ROLLOUT_SECONDS, remaining))
        if not outcomes:
            return scores
        # An unverified branch retains its prior estimate, rather than being
        # discarded or rewarded for having failed simulation.
        updated = []
        for score in scores:
            outcome = outcomes.get((score.candidate_id, score.option_ids))
            if outcome is None:
                updated.append(score)
                continue
            value = int(outcome) * max(1, self.weights.get("immediate_effect", 1))
            component = ComponentScore(component="mastermind_lookahead", value=value,
                explanation="Estimated health, resources, range and threats after your turn and a Tricky enemy reply; unknown enemy abilities are estimates.")
            updated.append(score.model_copy(update={"components": (*score.components, component),
                                                     "total": score.total + value}))
        return updated
