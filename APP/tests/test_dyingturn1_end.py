"""DYINGTURN1: a downed fighter whose only legal action is the automatic End Turn passes on its own."""
from types import SimpleNamespace

from combat import turn_decisions
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, _turn, AN, ME
from tests.test_lock_choices import install


def _dying(e, monkeypatch, who):
    e.state.rules = {**e.state.rules, "zero_hp": "dying_2024"}
    install(monkeypatch, "zero_hp", lambda *a: "DYING")
    install(monkeypatch, "self_recovery", lambda engine, actor: True if actor.entity_id == who else None)
    t = e.state.actors[who]
    with e._transaction("test:damage", "test:drop", ME):
        e._commit_damage(t, t.current_hp + 5, "UNTYPED", "test:damage", ME, None, reaction_depth=0)
    assert t.life_state == "DYING" and t.active
    return t


def test_dying_fighter_with_only_end_turn_passes_without_a_decision(monkeypatch):
    e, _ = _engine([])
    _dying(e, monkeypatch, AN)
    _turn(e, AN)
    assert e.state.current_actor_id == AN
    assert {c.kind for c in e.legal_candidates()} == {"END_TURN"}
    assert turn_decisions.passes_without_decision(e, AN) is True


def test_legacy_zero_hp_defeat_still_passes_without_a_decision():
    e, _ = _engine([])
    t = e.state.actors[AN]
    with e._transaction("test:damage", "test:drop", ME):
        e._commit_damage(t, t.current_hp + 5, "UNTYPED", "test:damage", ME, None, reaction_depth=0)
    assert not t.active
    e.state.current_actor_id = AN
    assert turn_decisions.passes_without_decision(e, AN) is True


def test_conscious_fighter_keeps_its_decision(monkeypatch):
    e, _ = _engine([])
    t = e.state.actors[AN]
    t.life_state = "CONSCIOUS"
    e.state.current_actor_id = AN
    assert turn_decisions.passes_without_decision(e, AN) is False


def test_dying_player_seat_is_local_auto_without_an_ask(monkeypatch):
    e, _ = _engine([])
    _dying(e, monkeypatch, ME)
    _turn(e, ME)
    assert e.state.current_actor_id == ME
    assert turn_decisions.passes_without_decision(e, ME) is True
    service = CombatService.__new__(CombatService)
    session = SimpleNamespace(engine=e)
    metadata = {"participant_control_modes": {ME: "MANUAL"}}
    assert service._mode_for_actor(metadata, session, ME) == "LOCAL_AUTO"
