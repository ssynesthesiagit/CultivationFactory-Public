import pytest

from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from tests.test_auto_tabik import _engine, _turn, ME, AN
from tests.test_lock_choices import install, intent


def damage(e, target):
    return e._commit_damage(target, target.current_hp + 5, "UNTYPED", "test:damage", ME, None, reaction_depth=0)


def test_default_defeat_and_legacy_serialization_unchanged():
    e, _ = _engine([])
    t = e.state.actors[AN]
    assert "life_state" not in t.model_dump(mode="json")
    damage(e, t)
    assert not t.active and t.current_hp == 0
    assert any(ev.event_type == "ENTITY_DEFEATED" for ev in e.events)
    assert not any(ev.event_type == "LIFE_STATE_CHANGED" for ev in e.events)


def test_dying_occupancy_turn_no_actions_and_reducer(monkeypatch):
    e, _ = _engine([])
    install(monkeypatch, "zero_hp", lambda *a: "DYING")
    # This one still has a way back, so its side is not defeated and the fight
    # stays open long enough to exercise the downed turn (owner 2026-10-21).
    install(monkeypatch, "self_recovery", lambda engine, actor: True if actor.entity_id == AN else None)
    t = e.state.actors[AN]
    before, n = e.state.model_copy(deep=True), len(e.events)
    with e._transaction("test:damage", "test:drop", ME):
        damage(e, t)
    assert t.active and t.current_hp == 0 and t.life_state == "DYING"
    assert (t.position.x, t.position.y) in e._occupied_cells_except(ME)
    assert e.state.terminal_result is None
    replayed = Gate3EventReducer().apply_events(before, enrich_committed_events(e.events[n:], post_engine=e))
    assert replayed.actors[AN].model_dump() == t.model_dump()
    _turn(e, AN)
    assert not t.action_available and not t.bonus_action_available and not t.reaction_available
    assert t.movement_remaining_ft == 0
    assert {c.kind for c in e.legal_candidates()} == {"END_TURN"}
    damage(e, t)
    assert t.life_state == "DYING" and t.active


def test_stabilise_heal_and_final_death(monkeypatch):
    e, _ = _engine([])
    install(monkeypatch, "zero_hp", lambda *a: "DYING")
    install(monkeypatch, "self_recovery", lambda engine, actor: True if actor.entity_id == AN else None)
    t = e.state.actors[AN]
    damage(e, t)
    e._set_life_state(t, "STABLE", "test:stabilise")
    assert t.life_state == "STABLE"
    from combat.typed_executor import Context, block_healing
    a = next(iter(e.action_catalog.values()))
    block_healing(Context(e, e.state.actors[ME], a, intent(e), {}, [t], t), {"flat": 4, "applies_to": "target"})
    assert t.current_hp == 4 and t.life_state is None and t.active
    assert not t.action_available  # no refund
    damage(e, t)
    e._defeat(t, "test:death", final=True)
    e._check_victory()
    assert not t.active and t.life_state is None and e.state.terminal_result is not None


def test_invalid_hook_rolls_back_damage(monkeypatch):
    e, _ = _engine([])
    install(monkeypatch, "zero_hp", lambda *a: "IMMORTAL")
    before = e.state.model_dump()
    with pytest.raises(ValueError, match="zero_hp"):
        with e._transaction("test:damage", "test:drop", ME):
            damage(e, e.state.actors[AN])
    assert e.state.model_dump() == before
