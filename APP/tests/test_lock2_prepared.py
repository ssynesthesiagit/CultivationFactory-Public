import pytest

from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.prepared_actions import CONDITION, SOURCE
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from tests.test_lock_choices import install
from tests.test_auto_tabik import _engine, _turn, ME, AN


def request(e, c):
    return ActionIntent(intent_id=f"test:{e.state.event_sequence}", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, option_ids=c.option_ids, destination=c.destination)


def setup(monkeypatch):
    e, _ = _engine([], foe_at=(4, 6))
    option = {"option_id": "counter", "source_id": "test:counterstrike", "label": "Counterstrike after a move",
              "trigger": "HOLD_POSITION_COMMITTED", "data": {"damage": 3}}
    install(monkeypatch, "prepare_options", lambda engine, actor: [option] if actor.entity_id == ME else [])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    def resolve(engine, actor, preparation, event, intent):
        assert not actor.reaction_available
        engine._grant_temp_hp(actor, 3, preparation["source_id"], actor.entity_id)
        return True
    install(monkeypatch, "prepared_action", resolve)
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.test_auto_tabik import ROOT
    context = build_decision_context(e, PolicyLibrary(ROOT).fallback())
    assert any(c.source_definition_id.startswith(SOURCE + ":") for c in context.legal_candidates)
    c = next(c for c in e.legal_candidates() if c.source_definition_id.startswith(SOURCE + ":"))
    before, n = e.state.model_copy(deep=True), len(e.events)
    e.execute_intent(request(e, c))
    assert not e.state.actors[ME].action_available
    assert not any(c.source_definition_id.startswith(SOURCE + ":") for c in e.legal_candidates())
    docs = enrich_committed_events(e.events[n:], post_engine=e)
    replayed = Gate3EventReducer().apply_events(before, docs)
    assert replayed.actors[ME].conditions == e.state.actors[ME].conditions
    return e


def trigger(e, selection="USE"):
    seen = []
    def provider(r):
        seen.append(r)
        return ReactionDecision(checkpoint=r["checkpoint"], reactor_id=r["reactor_id"],
            reaction_source_id=r["reaction_source_id"], selection=selection,
            option_ids=tuple(r["legal_option_ids"]) if selection == "USE" else ()), None
    e.set_reaction_provider(provider)
    c = next(c for c in e.legal_candidates() if c.kind == "HOLD_POSITION")
    e.execute_intent(request(e, c))
    return seen


def test_prepare_replay_offturn_table_choice_reaction_and_single_use(monkeypatch):
    e = setup(monkeypatch)
    assert trigger(e) == []  # cannot use on your own turn
    _turn(e, AN)
    seen = trigger(e)
    assert len(seen) == 1 and seen[0]["legal_option_ids"] == []
    actor = e.state.actors[ME]
    assert not actor.reaction_available and actor.temporary_hp == 3
    assert not any(c.condition_id == CONDITION for c in actor.conditions.values())
    assert trigger(e) == []


def test_decline_retains_then_expires_on_own_turn(monkeypatch):
    e = setup(monkeypatch)
    _turn(e, AN)
    assert trigger(e, "DECLINE")
    assert e.state.actors[ME].reaction_available
    assert any(c.condition_id == CONDITION for c in e.state.actors[ME].conditions.values())
    _turn(e, ME)
    assert not any(c.condition_id == CONDITION for c in e.state.actors[ME].conditions.values())


def test_no_reaction_and_provider_pause_rollback(monkeypatch):
    e = setup(monkeypatch)
    _turn(e, AN)
    e.state.actors[ME].reaction_available = False
    assert trigger(e) == []
    e.state.actors[ME].reaction_available = True
    def pause(r):
        raise RuntimeError("table pending")
    e.set_reaction_provider(pause)
    c = next(c for c in e.legal_candidates() if c.kind == "HOLD_POSITION")
    before, events = e.state.model_dump(), list(e.events)
    with pytest.raises(RuntimeError, match="table pending"):
        e.execute_intent(request(e, c))
    assert e.state.model_dump() == before and e.events == events


def test_unhandled_resolution_rolls_back_reaction_and_preparation(monkeypatch):
    e = setup(monkeypatch)
    _turn(e, AN)
    install(monkeypatch, "prepared_action", lambda *a: False)
    before = e.state.model_dump()
    with pytest.raises(ValueError, match="one plugin"):
        trigger(e)
    assert e.state.model_dump() == before
