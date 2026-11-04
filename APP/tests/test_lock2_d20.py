import pytest

from combat.gate3_reducer import Gate3EventReducer
from tests.test_lock_choices import install, intent
from tests.test_auto_tabik import _engine, ME, AN


@pytest.mark.parametrize("reason", ["ATTACK:test:1", "SAVE:test:DEX", "CHECK:test"])
def test_replace_before_consumption_and_event_replay(monkeypatch, reason):
    e, _ = _engine([])
    before = e.state.model_copy(deep=True)
    n = len(e.events)
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:fate", "operation": "replace", "natural_result": 20})
    r = e.roller.d20(modifier=3, actor_id=ME, reason=reason)
    e._record_roll(r)
    assert (r.natural_result, r.total) == (20, 23)
    ev = e.events[-1]
    assert ev.event_type == "D20_REWRITTEN" and ev.payload["result"] == r.model_dump(mode="json")
    for ev in e.events[n:]:
        Gate3EventReducer().apply_event(before, ev)
    # Transaction commits carry the roll counter separately from non-mutating roll events.
    assert before.actors == e.state.actors


@pytest.mark.parametrize("mode,draws", [("NORMAL", 1), ("ADVANTAGE", 2), ("DISADVANTAGE", 2)])
def test_reroll_uses_stream_once_and_retains_original(monkeypatch, mode, draws):
    e, _ = _engine([])
    start = e.roller.counter
    calls = []
    def rewrite(engine, roll, request):
        calls.append(roll)
        return {"source_id": "test:reroll", "operation": "reroll"}
    install(monkeypatch, "d20_result", rewrite)
    r = e.roller.d20(modifier=2, actor_id=ME, reason="CHECK:test", mode=mode)
    assert len(calls) == 1 and e.roller.counter == start + 2 * draws
    assert (r.counter_start, r.counter_end, r.mode) == (start, start + 2 * draws, mode)
    assert r.total == r.natural_result + 2
    assert e.events[-1].payload["original"] == calls[0].model_dump(mode="json")


def test_replacement_changes_actual_attack_and_save(monkeypatch):
    e, _ = _engine([], foe_at=(4, 6))
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:fate", "operation": "replace", "natural_result": 20})
    assert e._resolve_attack_spec(e.state.actors[ME], e.state.actors[AN], {"attack_bonus": -100},
                                  intent(e), source_definition_id="test:attack")
    assert e._roll_save(e.state.actors[ME], "DEX", 1, "test:save")


@pytest.mark.parametrize("value", [0, 21, True, "20"])
def test_invalid_rewrite_rolls_back_rng_state_and_events(monkeypatch, value):
    e, _ = _engine([])
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:fate", "operation": "replace", "natural_result": value})
    before, events, counter = e.state.model_dump(), list(e.events), e.roller.counter
    with pytest.raises(ValueError, match="1..20"):
        with e._transaction("test:check", "test:invalid", ME):
            e._record_roll(e.roller.d20(modifier=0, actor_id=ME, reason="CHECK:test"))
    assert e.state.model_dump() == before and e.events == events and e.roller.counter == counter


def test_no_answer_identical_and_pause_propagates(monkeypatch):
    e, _ = _engine([])
    from combat.gate2_rolls import DeterministicRollAuthority
    baseline = DeterministicRollAuthority(e.roller.seed, e.roller.counter)
    install(monkeypatch, "d20_result", lambda *a: None)
    n = len(e.events)
    assert e.roller.d20(modifier=5, actor_id=ME, reason="CHECK:test") == baseline.d20(modifier=5, actor_id=ME, reason="CHECK:test")
    assert len(e.events) == n
    def pause(*args):
        raise RuntimeError("table choice")
    install(monkeypatch, "d20_result", pause)
    with pytest.raises(RuntimeError, match="table choice"):
        with e._transaction("test:check", "test:pause", ME):
            e.roller.d20(modifier=0, actor_id=ME, reason="CHECK:test")
    assert not e._rewriting_d20
