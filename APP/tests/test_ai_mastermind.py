"""Public, synthetic MASTERMIND regressions. All embedding requests are fake."""
import json
import time

import pytest

from combat import ai_lookahead, ai_plays
from combat.embedding_rank import EmbeddingError
from combat.gate2_runtime_models import Position
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import LocalControllerPolicy
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from factory_authoring.sphere_dao import character_dao, controller_policy
from tests.ai_tiers_native_support import ROOT, OWNER, FOE, fight, context_for, selected


class Offline:
    def embed(self, texts):
        raise EmbeddingError("offline test")

    def prefetch(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def no_live_embedding(monkeypatch):
    from combat import menu_rank
    monkeypatch.setattr(menu_rank, "default_client", lambda: Offline())
    monkeypatch.setattr(menu_rank, "_CLIENT", Offline())


def boss_context(tmp_path, **kwargs):
    combat, mid, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART", "FIRE_TAL_FLAME_LASH"],
                               band="rival/boss", **kwargs)
    return combat, mid, session, context_for(combat, session)


def test_library_has_written_preconditions_dao_tags_and_goals():
    rows = ai_plays.library()
    assert 20 <= len(rows) <= 30
    assert len({p["id"] for p in rows}) == len(rows)
    for p in rows:
        assert p["name"] and p["description"] and p["requires"] and p["goal"]
        assert set(p["dao_tags"]) <= ai_plays.DAO_LEVERS.keys()


def test_native_belief_rollout_is_not_silently_disabled(tmp_path):
    _, _, session, context = boss_context(tmp_path, foe_at={"x": 10, "y": 5})
    # Exercise the native simulator directly (inside the queued test), so a
    # caught rollout error cannot make production silently look like a pass.
    engine = ai_lookahead.projected_engine(context)
    assert engine is not None
    assert engine.state.actors[OWNER].ai_tier == "MASTERMIND"
    # Recursion is explicitly disabled for belief decisions, not by changing
    # our remaining-turn policy into Tricky\'s (which may withdraw when hurt).
    projected = build_decision_context(engine, context.policy, for_ai=True)
    assert projected.tactics["projection"] is True
    assert "simulation" not in projected.tactics
    assert projected.own_knowledge is not None
    assert set(engine.state.actors) == {OWNER, FOE}
    assert engine.state.actors[FOE].action_ids != session.engine.state.actors[FOE].action_ids
    assert all(aid.startswith("prediction:") for aid in engine.state.actors[FOE].action_ids)
    choice, _ = selected(context)
    scores = choice.record.scored_alternatives[:4]
    candidates = {c.candidate_id: c for c in context.legal_candidates}
    results = ai_lookahead.simulate(context, scores, candidates, time.monotonic() + 10)
    assert results, "at least one native candidate must execute and include a reply"
    assert any(candidates[cid].metadata.get("placement_picker") for cid, _ in results), (
        "verify the proposed area aim, not a new belief-world recommendation")
    assert any(p.component == "mastermind_lookahead" for s in choice.record.scored_alternatives
               for p in s.components), "normal turn selection must actually use lookahead"


def test_boss_play_is_saved_and_reloaded_in_decision_record(tmp_path):
    combat, mid, session, context = boss_context(tmp_path, foe_at={"x": 10, "y": 5})
    before = session.engine.state.model_dump(mode="json")
    choice, candidate = selected(context)
    assert session.engine.state.model_dump(mode="json") == before, "rollouts never mutate the real fight"
    assert "Play: " in choice.record.explanation
    assert "Dao: " in choice.record.explanation
    assert all(sum(p.component == "mastermind_play" for p in s.components) == 1
               for s in choice.record.scored_alternatives), "lazy placements must not double-score their play"
    assert candidate.kind in {"ACTION", "BONUS_ACTION", "MOVE", "OPTIONAL_RIDER"}
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result = combat.local_step(mid)
    assert result["status"] == "COMMITTED"
    assert "Play: " in result["record"]["explanation"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    journal = [json.loads(line) for line in loaded.controller_journal_path.read_text().splitlines()]
    assert any("Play: " in (r.get("primary_decision_record") or {}).get("explanation", "") for r in journal)
    # The public service returns the exact persisted record; native replay must
    # still validate the speculative planner's real selected intent.
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_two_daos_visibly_prefer_different_plays_without_embeddings(tmp_path):
    _, _, _, context = boss_context(tmp_path, foe_at={"x": 10, "y": 5})
    proposals, decisions = [], []
    for spheres in ({"tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12},
                    {"tianxia.sphere.dark": 8, "tianxia.sphere.scoundrel": 5}):
        policy = LocalControllerPolicy.model_validate(controller_policy(character_dao(spheres), OWNER))
        situation = ai_plays.Situation(context.model_copy(update={"policy": policy}))
        proposals.append(situation.proposals(client=Offline())[0]["id"])
        choice, _ = selected(situation.context)
        decisions.append(choice.record.explanation.split(" — ", 1)[0])
    assert proposals[0] != proposals[1], proposals
    assert decisions[0] != decisions[1], decisions


def test_embedding_payload_uses_only_perceived_context_and_dao_still_first(tmp_path):
    _, _, _, context = boss_context(tmp_path)
    calls = []
    class Fake:
        def embed(self, texts):
            calls.append(texts)
            return [[1.0, float(i % 2)] for i in range(len(texts))]
    situation = ai_plays.Situation(context)
    proposals = situation.proposals(client=Fake())
    assert calls and proposals
    payload = json.dumps(calls)
    assert "AIUP1" not in payload
    assert "simulation" not in payload and "actor_template" not in payload
    assert all(all(situation.facts.get(k) for k in p["requires"]) for p in proposals)


def test_hidden_changes_do_not_change_mastermind_snapshot_goal_or_choice(tmp_path):
    combat, _, session, _ = boss_context(tmp_path)
    engine = session.engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test:concealment", FOE, expires_on=None)
    first = context_for(combat, session)
    assert first.own_knowledge is not None, "Mastermind must use personal knowledge even when analytic slices are off"
    choice, _ = selected(first)
    foe.position = Position(x=15, y=5)
    foe.current_hp, foe.armor_class = 1, 99
    foe.resources["resource:core.qi"] = 999
    second = context_for(combat, session)
    assert first.actors == second.actors
    assert first.tactics == second.tactics
    assert ai_plays.Situation(first).text() == ai_plays.Situation(second).text()
    again, _ = selected(second)
    assert choice.intent.candidate_id == again.intent.candidate_id


def test_unprojected_human_context_never_starts_mastermind_transport(tmp_path, monkeypatch):
    from combat.ai_tactics import make_plan, TurnPlan
    combat, _, session = fight(tmp_path, band="rival/boss")
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(session.engine, policy)
    assert context.own_knowledge is None
    def forbidden(*args, **kwargs):
        raise AssertionError("Unprojected human contexts cannot enter proposal ranking")
    monkeypatch.setattr(ai_plays.embedding_rank, "rank_options", forbidden)
    assert type(make_plan(context)) is TurnPlan


def test_team_only_telemetry_is_not_personal_knowledge(tmp_path, monkeypatch):
    monkeypatch.delenv("CF_COMBAT_AI_SLICES_1_2", raising=False)
    combat, _, session, _ = boss_context(tmp_path)
    engine = session.engine
    viewer, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test:concealment", FOE, expires_on=None)
    engine.events = [e.model_copy(update={"payload": {k: v for k, v in e.payload.items()
                     if k != "personal_observations"}}) for e in engine.events]
    engine.state.observations[viewer.team_id] = {FOE: Position(x=14, y=4)}
    first = context_for(combat, session)
    engine.state.observations[viewer.team_id][FOE] = Position(x=17, y=8)
    second = context_for(combat, session)
    assert first.own_knowledge is not None and not first.own_knowledge.creatures
    assert first.own_knowledge == second.own_knowledge
    assert first.actors == second.actors
    assert ai_plays.Situation(first).text() == ai_plays.Situation(second).text()
    assert selected(first)[0].intent.candidate_id == selected(second)[0].intent.candidate_id


def test_full_movement_menu_remains_scored_and_tricky_is_not_changed(tmp_path):
    _, _, _, context = boss_context(tmp_path)
    tricky = context.model_copy(update={"tactics": {k: v for k, v in context.tactics.items()
                                                  if k != "simulation"}})
    tricky.tactics["tier"] = "TRICKY"
    choice = LocalDeterministicController().choose_primary_action(tricky)
    assert not any(p.component.startswith("mastermind") for s in choice.record.scored_alternatives for p in s.components)
    boss, _ = selected(context)
    moves = {c.candidate_id for c in context.legal_candidates if c.kind == "MOVE"
             and c.destination not in context.movement_endpoints}
    assert moves <= {s.candidate_id for s in boss.record.scored_alternatives}


def test_hard_worker_wait_bound_and_no_parallel_rollout_flood(tmp_path, monkeypatch):
    import threading
    _, _, _, context = boss_context(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        release.wait(2)
        return {}
    monkeypatch.setattr(ai_lookahead, "simulate", slow)
    start = time.monotonic()
    try:
        assert ai_lookahead.verify(context, [], {}, budget=.03) == {}
        assert entered.is_set()
        assert ai_lookahead.verify(context, [], {}, budget=.03) == {}
        assert time.monotonic() - start < .3
    finally:
        release.set()
        # Join by the owned lock, never by process names.
        assert ai_lookahead._WORKER.acquire(timeout=2)
        ai_lookahead._WORKER.release()


def test_deadline_keeps_completed_replies_while_later_branch_is_slow(tmp_path, monkeypatch):
    import threading
    _, _, _, context = boss_context(tmp_path)
    release = threading.Event()
    key = ("finished-plan", ())
    def partial(_context, _shortlist, _candidates, _deadline, publish):
        publish(key, 17)
        release.wait(2)
        return {key: 17}
    monkeypatch.setattr(ai_lookahead, "simulate", partial)
    try:
        assert ai_lookahead.verify(context, [], {}, budget=.03) == {key: 17}
    finally:
        release.set()
        assert ai_lookahead._WORKER.acquire(timeout=2)
        ai_lookahead._WORKER.release()


def test_reaction_bait_uses_printed_condition_semantics_not_name_guesses(tmp_path):
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    from combat.ai_tactics import _effects
    cut = [aid for aid in context.tactics["actions"] if any(e.get("type") == "reaction_denied"
           for e in _effects(session.engine.action_catalog[aid].parameters.get("typed", {}).get("effects", ())))]
    assert cut and all(context.tactics["actions"][aid]["reaction_denial"] for aid in cut)


def test_die_hard_does_not_hoard_and_no_snapshot_for_tricky_or_summons(tmp_path):
    from combat.ai_mastermind import MastermindPlan
    from combat.ai_tactics import TurnPlan
    combat, _, session, context = boss_context(tmp_path)
    plan = MastermindPlan(context)
    expensive = {"costs": [["resource:core.qi", 20]]}
    assert plan.resource_price(expensive) < TurnPlan(context).resource_price(expensive)
    actor = session.engine.state.actors[OWNER]
    actor.ai_tier = "TRICKY"
    assert "simulation" not in context_for(combat, session).tactics
    actor.ai_tier = "MASTERMIND"
    actor.summon = {"owner_id": FOE}
    assert "simulation" not in context_for(combat, session).tactics
