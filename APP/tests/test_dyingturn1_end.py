"""DYINGTURN1: a dying fighter whose only legal action is the automatic End Turn passes on its own."""
from combat import turn_decisions
from tests.test_auto_tabik import _engine, _turn, AN, ME
from tests.test_lock_choices import install


def _dying(e, monkeypatch):
    e.state.rules = {**e.state.rules, "zero_hp": "dying_2024"}
    install(monkeypatch, "zero_hp", lambda *a: "DYING")
    install(monkeypatch, "self_recovery", lambda engine, actor: True if actor.entity_id == AN else None)
    t = e.state.actors[AN]
    with e._transaction("test:damage", "test:drop", ME):
        e._commit_damage(t, t.current_hp + 5, "UNTYPED", "test:damage", ME, None, reaction_depth=0)
    assert t.life_state == "DYING" and t.active
    return t


def test_dying_fighter_with_only_end_turn_passes_without_a_decision(monkeypatch):
    e, _ = _engine([])
    _dying(e, monkeypatch)
    _turn(e, AN)
    assert e.state.current_actor_id == AN
    assert {c.kind for c in e.legal_candidates()} == {"END_TURN"}
    assert turn_decisions.passes_without_decision(e, AN) is True


def test_dying_fighter_keeps_a_decision_when_it_has_a_real_choice(monkeypatch):
    e, _ = _engine([])
    _dying(e, monkeypatch)
    _turn(e, AN)
    real = e._generate_legal_candidates
    move = type("C", (), {"kind": "MOVE"})()
    monkeypatch.setattr(e, "_generate_legal_candidates", lambda *a, **k: (move, *real(*a, **k)))
    assert turn_decisions.passes_without_decision(e, AN) is False
