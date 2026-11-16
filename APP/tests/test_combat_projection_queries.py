"""Prospective attack enumeration keeps complete results and local query scopes."""
from types import SimpleNamespace

import pytest

from combat import ext, flight_decision, read_queries, target_knowledge
from combat.gate2_runtime_models import Position


def _view(position=0):
    actor = SimpleNamespace(entity_id="actor", position=Position(x=position, y=0))
    action = SimpleNamespace(source_definition_id="action")
    candidates = (SimpleNamespace(candidate_id="one", target_ids=("foe",)),
                  SimpleNamespace(candidate_id="two", target_ids=("foe",)))
    view = SimpleNamespace(
        state=SimpleNamespace(state_version=1, event_sequence=1), action_catalog={"action": action},
        _action_candidates=lambda holder, source: candidates)
    return view, actor, action


def _query_hooks(monkeypatch, gate, *, present=None, key=None):
    ext.load_plug_ins()
    monkeypatch.setitem(ext._HOOKS, "candidate_allowed", [gate])
    monkeypatch.setitem(ext._HOOKS, "ai_candidate_allowed", [])
    if present is not None:
        monkeypatch.setitem(ext._HOOK_PRESENT, ("candidate_allowed", gate), present)
        monkeypatch.setattr(ext, "_FILTERED_POINTS", ext._FILTERED_POINTS | {"candidate_allowed"})
    if key is not None:
        monkeypatch.setitem(ext._HOOK_QUERY_KEYS, ("candidate_allowed", gate), key)
    monkeypatch.setattr(target_knowledge, "can_see", lambda engine, actor, foe: True)


def _ask(view, actor, action):
    foes = (SimpleNamespace(entity_id="foe"),)
    return flight_decision.native_attack_candidates(view, actor, foes, (action,))


def test_projection_uses_declared_pure_queries_without_changing_results(monkeypatch):
    calls = []

    def gate(engine, actor, candidate, action):
        calls.append(actor.position.x)
        return False if actor.position.x else None

    _query_hooks(monkeypatch, gate, key=lambda engine, actor, candidate, action: actor.position.x)
    view, actor, action = _view()
    shared = _ask(view, actor, action)
    assert [row.candidate_id for _, row in shared] == ["one", "two"]
    assert calls == [0]
    with read_queries.sharing_off():
        assert _ask(view, actor, action) == shared
    assert calls == [0, 0, 0]
    # Same recorded revision, different projected inputs: no cached permission.
    view, actor, action = _view(1)
    assert _ask(view, actor, action) == ()
    assert calls == [0, 0, 0, 1]
    assert read_queries.enumeration_cache(view) is None


def test_projection_obeys_existing_inert_provider_declarations(monkeypatch):
    calls = []
    def neutral(engine, actor, candidate, action):
        calls.append(candidate.candidate_id)

    _query_hooks(monkeypatch, neutral, present=lambda engine: False)
    view, actor, action = _view()
    assert len(_ask(view, actor, action)) == 2
    assert calls == []
    with read_queries.sharing_off():
        assert len(_ask(view, actor, action)) == 2
    assert calls == ["one", "two"]


def test_unannotated_hooks_still_see_every_candidate(monkeypatch):
    calls = []
    def gate(engine, actor, candidate, action):
        calls.append(candidate.candidate_id)
        return False if candidate.candidate_id == "two" else None

    _query_hooks(monkeypatch, gate)
    view, actor, action = _view()
    assert [row.candidate_id for _, row in _ask(view, actor, action)] == ["one"]
    assert calls == ["one", "two"]


def test_projection_preserves_outer_engine_cache_and_cleans_up_on_failure(monkeypatch):
    calls = []
    def fail(engine, actor, candidate, action):
        calls.append(candidate.candidate_id)
        raise ext.CheckpointError("query failure")

    _query_hooks(monkeypatch, fail, key=lambda *args: "unchanged-query")
    view, actor, action = _view()
    outer, _, _ = _view()
    with read_queries.candidate_pass(outer):
        cache = read_queries.enumeration_cache(outer)
        cache["outer-only"] = object()
        before = dict(cache)
        with pytest.raises(ext.CheckpointError, match="query failure"):
            _ask(view, actor, action)
        with pytest.raises(ext.CheckpointError, match="query failure"):
            _ask(view, actor, action)
        assert calls == ["one", "one"]
        assert read_queries.enumeration_cache(outer) is cache
        assert cache == before
        assert read_queries.enumeration_cache(view) is None
    assert read_queries.enumeration_cache(outer) is None


def test_nested_projection_does_not_replace_same_engine_outer_frame(monkeypatch):
    def neutral(engine, actor, candidate, action):
        return None

    _query_hooks(monkeypatch, neutral)
    view, actor, action = _view()
    with read_queries.candidate_pass(view):
        outer = read_queries.enumeration_cache(view)
        outer["outer-only"] = object()
        before = dict(outer)
        assert len(_ask(view, actor, action)) == 2
        assert read_queries.enumeration_cache(view) is outer
        assert outer == before


def test_native_projected_candidates_equal_unshared_queries():
    from combat.candidate_knowledge import query
    from tests.h1_support import ME, duel

    engine = duel([])
    before = engine.state.model_dump(mode="json")
    view = flight_decision.query_copy(engine)
    own = view.state.actors[ME]
    attacks = flight_decision.attacks_of(view, own, own=True)
    assert attacks
    foes = tuple(a for a in view.state.actors.values() if a.entity_id != ME)
    results = []
    for position in (Position(x=3, y=6), Position(x=1, y=1), Position(x=4, y=5)):
        candidate = SimpleNamespace(destination=position, movement_cost_ft=5)
        projected, actor = flight_decision.project_at(view, ME, candidate)
        projected_before = projected.state.model_dump(mode="json")
        events_before = [row.model_dump(mode="json") for row in projected.events]
        rolls_before = [row.model_dump(mode="json") for row in projected.rolls]
        with query(projected):
            shared = flight_decision.native_attack_candidates(projected, actor, foes, attacks)
            with read_queries.sharing_off():
                unshared = flight_decision.native_attack_candidates(projected, actor, foes, attacks)
        dump = lambda rows: [(action.model_dump(mode="json"), choice.model_dump(mode="json"))
                             for action, choice in rows]
        assert dump(shared) == dump(unshared)
        assert projected.state.model_dump(mode="json") == projected_before
        assert [row.model_dump(mode="json") for row in projected.events] == events_before
        assert [row.model_dump(mode="json") for row in projected.rolls] == rolls_before
        results.append(shared)
    assert any(results)
    assert engine.state.model_dump(mode="json") == before
