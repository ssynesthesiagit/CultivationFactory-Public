"""AIUP2F1 regressions: complete fights, honest draws, whole-decision budget.

No live transport: every proposal and plan embedding uses an offline client.
"""
import pytest

import json
import shutil
from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace

from combat import ai_lookahead, ai_mastermind, menu_rank
from combat.work_budget import WorkBudget
from combat.ai_mastermind import MastermindPlan
from combat.embedding_rank import EmbeddingError
from combat.gate4_models import CandidateScore
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, context_for, fight
from tests.ai_mastermind_bench_support import BENCH_ROUNDS, bench_fight, outcome, summarize


class Offline:
    def embed(self, texts):
        raise EmbeddingError("offline regression")

    def prefetch(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)


def setup_plan(tmp_path, monkeypatch):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FLAME_LASH"], band="rival/boss")
    context = context_for(combat, session)
    plan = MastermindPlan(context)
    candidates = {c.candidate_id: c for c in context.legal_candidates}
    scores = [CandidateScore(candidate_id=c.candidate_id, option_ids=(), total=i, components=())
              for i, c in enumerate(candidates.values())]
    return context, plan, None, scores, candidates


def test_rollout_budget_is_fixed_checkpoints_not_preparation_time(tmp_path, monkeypatch):
    _, plan, _, scores, candidates = setup_plan(tmp_path, monkeypatch)
    calls = []
    def verify(context, shortlist, candidates, *, budget, cancelled=None):
        calls.append((shortlist, budget))
        return {}
    monkeypatch.setattr(ai_lookahead, "verify", verify)
    result = plan.with_self_followups(scores, candidates)
    assert calls and calls[0][1] == ai_lookahead.ROLLOUT_STEPS
    assert 1 <= ai_mastermind.LOOKAHEAD_K <= 2
    assert 1 <= len(calls[0][0]) <= ai_mastermind.LOOKAHEAD_K
    assert {s.candidate_id for s in result} == set(candidates)


def test_exhausted_budget_returns_all_best_so_far_scores(tmp_path, monkeypatch):
    _, plan, _, scores, candidates = setup_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_lookahead, "ROLLOUT_STEPS", 0)
    result = plan.with_self_followups(scores, candidates)
    assert [(s.candidate_id, s.total) for s in result] == [(s.candidate_id, s.total) for s in scores]
    assert max(result, key=lambda s: s.total) == scores[-1]


def test_context_roundtrip_preserves_the_plays(tmp_path, monkeypatch):
    from combat.gate4_models import DecisionContext
    combat, _, session = fight(tmp_path, band="rival/boss")
    base = context_for(combat, session)
    restored = DecisionContext.model_validate_json(base.model_dump_json())
    plays = [p["id"] for p in MastermindPlan(base).plays]
    assert restored == base
    assert plays and [p["id"] for p in MastermindPlan(restored).plays] == plays


def test_zero_budget_never_starts_a_rollout(tmp_path, monkeypatch):
    combat, _, session = fight(tmp_path, band="rival/boss")
    context = context_for(combat, session)
    def forbidden(*args):
        raise AssertionError("zero-budget work must not start")
    monkeypatch.setattr(ai_lookahead, "simulate", forbidden)
    assert ai_lookahead.verify(context, [], {}, budget=0) == {}


def test_facts_are_cached_only_within_this_decision(tmp_path, monkeypatch):
    context, plan, _, _, candidates = setup_plan(tmp_path, monkeypatch)
    assert plan.situation.plan is plan, "do not build a duplicate turn planner for proposals"
    candidate = next(iter(candidates.values()))
    first = plan.situation.features(candidate)
    assert plan.situation.features(candidate) is first
    again = MastermindPlan(context)
    assert again.situation.features(candidate) == first
    assert again.situation.features(candidate) is not first


def test_belief_map_shares_only_call_local_perception_facts(tmp_path, monkeypatch):
    from combat import senses, read_queries
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FLAME_LASH"], band="rival/boss")
    engine = session.engine
    actor = engine.state.actors[OWNER]
    before = engine.state.model_dump(mode="json")
    original = senses.perceives_cell
    computations = []
    def observed(engine, actor, position):
        read_queries.memo(engine, ("test:own-map-fact", actor.entity_id),
                          lambda: computations.append(actor.position))
        return original(engine, actor, position)
    monkeypatch.setattr(senses, "perceives_cell", observed)
    first = ai_lookahead.own_snapshot(engine, actor)
    assert len(computations) == 1, "reuse per-decision facts, not one fresh frame per square"
    assert ai_lookahead.own_snapshot(engine, actor) == first
    assert len(computations) == 2, "no cache may survive into the next decision"
    assert engine.state.model_dump(mode="json") == before


@pytest.mark.parametrize("tier", ["MASTERMIND", "TRICKY"])
def test_forced_standing_defers_only_mastermind_flight_forecasts(tmp_path, monkeypatch, tier):
    from combat import flight_decision
    from combat.gate4_controller import LocalDeterministicController
    from combat.candidate_knowledge import query as observed
    from combat.placement_menu import query as lazy
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               flight=True, foe_at={"x": 3, "y": 7})
    engine = session.engine
    actor = engine.state.actors[OWNER]
    actor.ai_tier = tier
    engine._apply_condition(actor, "condition:typed.prone", "test:posture", OWNER, expires_on=None)
    with observed(engine), lazy():
        native = {c.candidate_id for c in engine.legal_candidates()
                  if c.kind == "MOVE" or "standing_cost_ft" in c.metadata}
    original = flight_decision.annotate
    calls = []
    def counted(*args, **kwargs):
        if args[0] is engine:
            calls.append(1)  # speculative worker engines legitimately forecast too
        return original(*args, **kwargs)
    monkeypatch.setattr(flight_decision, "annotate", counted)
    context = context_for(combat, session)
    assert native <= {c.candidate_id for c in context.legal_candidates}
    assert len(calls) == (0 if tier == "MASTERMIND" else 1)
    choice = LocalDeterministicController().choose_primary_action(context)
    chosen = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert "standing_cost_ft" in chosen.metadata
    engine.execute_intent(choice.intent)
    after = context_for(combat, session)
    assert len(calls) == (1 if tier == "MASTERMIND" else 2)
    assert any(c.metadata.get("flight_tactics") for c in after.legal_candidates if c.kind == "MOVE")


def test_expired_preview_refinement_keeps_all_roots_and_exact_aims(tmp_path, monkeypatch):
    from combat import placement_menu
    from combat.gate4_context import build_decision_context
    from combat.gate2_runtime_models import Position
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], band="rival/boss",
                               foe_at={"x": 10, "y": 5})
    engine = session.engine
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True, placement_previews=False)
    roots = [c for c in context.legal_candidates if c.metadata.get("placement_picker")]
    assert roots
    exact = placement_menu.exact
    calls = []
    def counted(engine, root, point, **kwargs):
        calls.append(point)
        return exact(engine, root, point, **kwargs)
    monkeypatch.setattr(placement_menu, "exact", counted)
    bounded = placement_menu.annotate(engine, context, budget=WorkBudget(0))
    assert [c.candidate_id for c in bounded.legal_candidates] == [c.candidate_id for c in context.legal_candidates]
    assert all(c.metadata.get("placement_evaluation") for c in bounded.legal_candidates
               if c.metadata.get("placement_picker"))
    assert len(calls) <= len(roots) * (len(context.actors) + 1), "do not refine after the work budget is spent"
    # A different, unranked square is still a legal native choice.
    foe = next(a for a in context.actors if a.entity_id != OWNER)
    aim = Position(x=foe.position.x - 1, y=foe.position.y, z=foe.position.z)
    assert exact(engine, roots[0], aim) is not None


@pytest.mark.parametrize("prepared_mode,recovery_mode,corruption", [
    ("success", "deadline", None),
    ("timeout", "success", None),
    ("success", "busy", None),
    ("busy", "success", None),
    ("success", "busy", "score"),
    ("success", "busy", "request"),
    ("success", "busy", "missing"),
    ("success", "busy", "extra"),
])
def test_same_position_under_forced_load_gives_identical_record(
    tmp_path, monkeypatch, prepared_mode, recovery_mode, corruption,
):
    # Exercise the actual service policy and interrupted durable transaction.
    # Patch the clock the planner READS, and compare complete records, not IDs.
    from combat.gate3_storage import Gate3InjectedCrash
    from combat.gate5_service import CombatService
    from tests.ai_tiers_native_support import ROOT

    data = tmp_path / "interrupted"
    combat, mid, session = fight(data, ["FIRE_TAL_FLAME_LASH"], band="rival/boss",
                                foe_at={"x": 3, "y": 7})
    slot = Lock()
    monkeypatch.setattr(ai_mastermind, "_LOOKAHEAD_SLOT", slot)
    monkeypatch.setattr(ai_mastermind, "DECISION_BUDGET_SECONDS", 3.0)
    ranks, verifications = [], []

    def rank(text, options, **kwargs):
        ranks.append(text)
        return [key for key, _ in options]
    monkeypatch.setattr(ai_mastermind.embedding_rank, "rank_options", rank)

    @contextmanager
    def mode(which):
        entered, release = Event(), Event()
        def verify(context, shortlist, candidates, **kwargs):
            verifications.append(which)
            entered.set()
            if which in {"timeout", "busy"}:
                assert release.wait(10), "test did not release its worker"
            # A real, nonzero input changes the scores (and can change selection).
            return {(s.candidate_id, s.option_ids): -10000 for s in shortlist}
        with monkeypatch.context() as patch:
            patch.setattr(ai_lookahead, "verify", verify)
            if which in {"timeout", "busy"}:
                calls = []
                def clock():
                    calls.append(1)
                    if len(calls) < 3:
                        return 0.0
                    assert entered.wait(3), "native verification never entered"
                    return 2.95  # 50 ms wait, while the worker remains blocked
                patch.setattr(ai_mastermind, "monotonic", clock)
            elif which == "deadline":
                ticks = iter((0.0, 4.0))
                patch.setattr(ai_mastermind, "monotonic", lambda: next(ticks, 4.0))
            else:
                patch.setattr(ai_mastermind, "monotonic", lambda: 0.0)
            try:
                if which == "busy":
                    # A previous decision timed out, but its worker still owns
                    # the process-wide slot. The tested choice cannot start one.
                    combat._local_choice(session)
                    assert entered.is_set() and slot.locked()
                    patch.setattr(ai_mastermind, "monotonic", lambda: 0.0)
                yield
            finally:
                release.set()
                # Join the worker at its real ownership boundary, not a sleep.
                assert slot.acquire(timeout=3), "verification worker did not exit"
                slot.release()

    def crash(stage, context):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)

    with mode(prepared_mode):
        choice = combat._local_choice(session)[0]
        assert [row.name for row in choice.record.decision_inputs] == [
            "mastermind.proposals", "mastermind.verification"]
        verified = any(p.component == "mastermind_lookahead"
                       for s in choice.record.scored_alternatives for p in s.components)
        assert verified == (prepared_mode == "success")
        assert bool(choice.record.decision_inputs[-1].value) == verified
        assert len(choice.record.scored_alternatives) >= len(choice.record.legal_alternatives)
        # Same native save and exact prepared choice, without the interruption.
        shutil.copytree(data, tmp_path / "normal")
        normal_service = CombatService(ROOT, tmp_path / "normal")
        normal = normal_service._load_session(mid)
        normal.execute_controller_choice(choice, controller=normal_service.controller,
                                         policy_library=normal_service.policies)
        with pytest.raises(Gate3InjectedCrash):
            session.execute_controller_choice(choice, controller=combat.controller,
                policy_library=combat.policies, failure_injector=crash)

    journal = session.controller_journal_path
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    prepared = rows[-1]
    assert prepared["record_type"] == "CONTROLLER_PREPARE"
    assert prepared["primary_decision_record"] == choice.record.model_dump(mode="json", by_alias=True)
    if corruption:
        record = prepared["primary_decision_record"]
        if corruption == "score":
            record["scored_alternatives"][0]["total"] += 1
        elif corruption == "request":
            record["decision_inputs"][0]["request_sha256"] = "0" * 64
        elif corruption == "missing":
            record["decision_inputs"].pop()
        else:
            record["decision_inputs"].append(record["decision_inputs"][-1])
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))

    with mode(recovery_mode):
        # Prove these conditions would produce a different live record, so a
        # candidate-only comparison or an ineffective clock patch cannot pass.
        probe = combat._local_choice(session)[0]
        assert probe.record != choice.record
        rank_count, verify_count = len(ranks), len(verifications)
        before = {p: p.read_bytes() for p in (journal, session.store.journal_path)}
        fresh = CombatService(ROOT, data)
        if corruption:
            with pytest.raises(ValueError, match="CONTROLLER_DECISION_NONDETERMINISTIC"):
                fresh._load_session(mid)
            assert {p: p.read_bytes() for p in before} == before
        else:
            recovered = fresh._load_session(mid)
            assert recovered.verify()["controller_open_transactions"] == []
            assert recovered.mechanical.replay() == normal.mechanical.replay()
            recovered_rows = [json.loads(line) for line in journal.read_text().splitlines()]
            assert recovered_rows[-2] == prepared
            assert recovered_rows[-1]["record_type"] == "CONTROLLER_COMMIT"
            assert recovered_rows[-1]["recovered_from_incomplete_prepare"] is True
            assert fresh._load_session(mid).mechanical.replay() == normal.mechanical.replay()
        # Neither changed embedding cache order nor current verification
        # availability may be consulted when replaying the prepared inputs.
        assert (len(ranks), len(verifications)) == (rank_count, verify_count)


def test_benchmark_counts_wins_losses_and_draws_separately():
    rows = [{"outcome": outcome(SimpleNamespace(winning_team_id=winner), "boss")}
            for winner in ("boss", "boss", "boss", "foe", "foe", None)]
    report = summarize(rows)
    assert (report["WIN"], report["LOSS"], report["DRAW"]) == (3, 2, 1)
    assert report["decided"] == 5
    assert report["decided_win_rate"] == .6
    assert report["draw_rate"] == 1 / 6
    assert summarize([{"outcome": "DRAW"}])["decided_win_rate"] == 0
    with pytest.raises(AssertionError, match="did not finish"):
        outcome(None, "boss")


def test_benchmark_round_cap_survives_native_match_reload(tmp_path):
    combat, mid, session = bench_fight(tmp_path, band="rival/boss")
    assert BENCH_ROUNDS >= 20
    assert session.engine.state.maximum_rounds == BENCH_ROUNDS
    assert combat._load_session(mid).engine.state.maximum_rounds == BENCH_ROUNDS
    engine = session.engine
    # Verify that a passive fight really continues past the old round-8 cap.
    while engine.state.round_number <= 9 and engine.state.terminal_result is None:
        engine.end_turn()
    assert engine.state.round_number >= 10
    assert engine.state.terminal_result is None
    assert OWNER in engine.state.actors
