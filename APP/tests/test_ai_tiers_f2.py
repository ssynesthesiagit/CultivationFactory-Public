"""Offline native F2 regressions; synthetic sheets, export-held combat runtime."""
from combat.ai_tactics import TurnPlan
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import fight, context_for, selected, OWNER, ROOT


def test_explanation_names_the_choice_and_purpose_not_the_integer_score(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    choice, candidate = selected(context_for(combat, session))
    assert "Dao: Fire" in choice.record.explanation
    assert candidate.display_name in choice.record.explanation
    assert "score " not in choice.record.explanation
    assert "tricky_turn_plan" not in str(choice.record.model_dump())
    assert any(word in choice.record.explanation.lower() for word in ("damage", "enemies", "range", "protect"))


def test_control_hint_does_not_outweigh_a_stronger_affordable_direct_hit(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    _, candidate = selected(context)
    assert "Fireball" in candidate.display_name
    # A printed five-CP price is soft budgeting, not permission to hoard forever.
    owner = next(a for a in context.actors if a.entity_id == OWNER)
    assert owner.resources["resource:core.qi"] >= 5


def test_search_without_a_strike_guards_instead_of_spending_the_next_attack_on_a_blind_dash(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 17, "y": 8})
    actor = session.engine.state.actors[OWNER]
    actor.movement_remaining_ft = 0  # the ordinary exploration move was spent
    context = context_for(combat, session)
    assert not TurnPlan(context).has_strike
    choice, candidate = selected(context)
    assert candidate.display_name == "Dodge"
    session.engine.execute_intent(choice.intent)
    assert any(c.condition_id == "condition:core.dodge" and c.expires_on == "START_OF_SELF_NEXT_TURN"
               for c in actor.conditions.values())
    # Negative control: without the new own-sheet defense value the legacy
    # preference spends the action on Dash even though no target is located.
    for info in context.tactics["actions"].values():
        info["defense"] = False
    assert selected(context)[1].display_name == "Dash"


def test_area_attack_spends_for_a_finishing_release_and_commits_reload(tmp_path):
    from combat.gate5_service import CombatService
    combat, mid, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"],
                                 foe_at={"x": 10, "y": 5}, foe_hp=25)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    choice, candidate = selected(context)
    assert "Fireball" in candidate.display_name and "Overheat" in candidate.display_name
    assert candidate.metadata["hostile_damage_by_id"]
    # Negative control: the old square-only estimate does not know which
    # enemy can be finished, and conserves the two extra CP instead.
    blind = context.model_copy(update={"legal_candidates": tuple(
        c.model_copy(update={"metadata": {k: v for k, v in c.metadata.items()
            if k not in {"hostile_damage_by_id", "placement_evaluation"}}})
        for c in context.legal_candidates)})
    assert "Overheat" not in selected(blind)[1].display_name
    assert combat.local_step(mid)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].resources["resource:core.qi"] == 23
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_joint_resource_comparison_is_per_ability_not_per_aim(tmp_path, monkeypatch):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    strike = next(c for c in context.legal_candidates if c.kind == "ACTION"
                  and context.tactics["actions"].get(c.source_definition_id, {}).get("damage")
                  and context.tactics["actions"][c.source_definition_id]["costs"])
    info = context.tactics["actions"][strike.source_definition_id]
    resource, cost = info["costs"][0]
    next(a for a in context.actors if a.entity_id == OWNER).resources[resource] = cost
    context.tactics["actions"]["rival"] = {**info, "economy": "BONUS_ACTION", "damage": 1}
    aims = tuple(strike.model_copy(update={"candidate_id": f"aim:{i}", "kind": "BONUS_ACTION",
                 "source_definition_id": "rival"}) for i in range(128))
    plan = TurnPlan(context.model_copy(update={"legal_candidates": (*context.legal_candidates, *aims)}))
    calls = []
    native = plan.gross_value
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(plan, "gross_value", counted)
    # Every aim remains available; equivalent resource conflicts are calculated once.
    for _ in range(128):
        assert plan.rival_conflict(strike) > 0
    assert len(calls) <= 4, f"recomputed {len(calls)} identical resource comparisons"


def test_empty_hostile_area_search_does_not_rebuild_the_menu(tmp_path, monkeypatch):
    from combat import placement_menu
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 17, "y": 8})
    context = context_for(combat, session)
    assert not TurnPlan(context).has_strike
    root = next(c for c in context.legal_candidates if c.metadata.get("placement_picker")
                and "Fireball" in c.display_name)
    calls = []
    native = placement_menu.exact
    def exact(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(placement_menu, "exact", exact)
    assert placement_menu.search(session.engine, root, context) is None
    assert not calls, "a known-empty harmful area must not probe dozens of identical misses"


def test_placement_search_shares_invariants_only_for_its_unchanged_query(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from combat import placement_menu, read_queries
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    root = next(c for c in context.legal_candidates if c.metadata.get("placement_picker")
                and "Fireball" in c.display_name)
    engine = session.engine
    native = placement_menu.exact
    probes, computations = [], []
    def compute():
        computations.append(1)
        return object()
    def exact(*args, **kwargs):
        probes.append(read_queries.invariant_memo(engine, ("aiup1:search_invariant",), compute))
        return native(*args, **kwargs)
    monkeypatch.setattr(placement_menu, "exact", exact)
    assert read_queries.enumeration_cache(engine) is None
    first = placement_menu.search(engine, root, context)
    assert first is not None and len(probes) > 1
    assert len(computations) == 1, "each sampled aim repeated the same unchanged query"
    assert read_queries.enumeration_cache(engine) is None
    # No result survives a search; a new query must read new invariant facts.
    second = placement_menu.search(engine, root, context)
    assert second.model_dump() == first.model_dump()
    assert len(computations) == 2
    assert read_queries.enumeration_cache(engine) is None
    # Native recommendations and all exact aims stay identical without caches.
    monkeypatch.setattr(read_queries, "candidate_pass", lambda _engine: nullcontext())
    uncached = placement_menu.search(engine, root, context)
    assert uncached.model_dump() == first.model_dump()
    assert len(computations) > 2
    assert read_queries.enumeration_cache(engine) is None


def test_placement_search_releases_invariant_scope_on_error(tmp_path, monkeypatch):
    from combat import placement_menu, read_queries
    import pytest
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    root = next(c for c in context.legal_candidates if c.metadata.get("placement_picker")
                and "Fireball" in c.display_name)
    def broken(*args, **kwargs):
        assert read_queries.enumeration_cache(session.engine) is not None
        raise RuntimeError("synthetic probe failure")
    monkeypatch.setattr(placement_menu, "exact", broken)
    with pytest.raises(RuntimeError, match="synthetic probe failure"):
        placement_menu.search(session.engine, root, context)
    assert read_queries.enumeration_cache(session.engine) is None


def test_native_ai_placement_context_is_compact_but_explicit_aims_stay_legal(tmp_path):
    from combat.gate4_context import build_decision_context
    from combat.placement_menu import cells, exact
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(session.engine, policy, for_ai=True)
    roots = [c for c in context.legal_candidates if c.metadata.get("placement_picker")
             and "Fireball" in c.display_name]
    assert roots, "ordinary native AI contexts must not eagerly rebuild every area aim"
    root = roots[0]
    # Compact scoring is not a legality cap: exhaustive second-stage aims and
    # native exact validation still accept an aim outside the recommendation.
    aims = list(cells(session.engine, root))
    assert len(aims) > 32
    picked = root.metadata["placement_evaluation"]["destination"]
    other = next(c for c in aims if c.destination.model_dump() != picked)
    assert exact(session.engine, root, other.destination).candidate_id == other.candidate_id
    assert root.candidate_id in {s.candidate_id for s in LocalDeterministicController()
                                 .choose_primary_action(context).record.scored_alternatives}
