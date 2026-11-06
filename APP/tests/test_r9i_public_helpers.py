"""Death delay priority is explicit, stable and duplicate registration inert."""
from combat.ext import life_state


def test_public_death_handler_priority_and_registration_order(monkeypatch):
    monkeypatch.setattr(life_state, "_HANDLERS", [])
    calls = []

    def soul(*args):
        calls.append("soul")
        return True

    def delay(*args):
        calls.append("delay")
        return False

    def other(*args):
        calls.append("other")
        return False

    life_state.handler(soul)
    life_state.handler(delay, priority=-100)
    life_state.handler(other, priority=-100)
    life_state.handler(delay, priority=-100)
    from types import SimpleNamespace

    target = SimpleNamespace(active=True, conditions={}, life_state="ALIVE")
    life_state.die(None, target, "test", "source")
    assert calls == ["delay", "other", "soul"]


def test_public_auspice_cleanup_removes_only_the_released_grant():
    from combat.ext.d20_floor import end_auspice
    from combat.ext.fate_riders import AUSPICE
    from tests.test_riders_lane9 import _fate_fight, ME, ALLY, THEM

    engine = _fate_fight([])
    bearer = engine.state.actors[ALLY]
    engine._apply_condition(bearer, AUSPICE, "test:first", ME, expires_on="UNTIL_REMOVED")
    engine._apply_condition(bearer, AUSPICE, "test:second", THEM, expires_on="UNTIL_REMOVED")
    first, second = list(bearer.conditions.values())
    end_auspice(engine, bearer, first, "RELEASED")
    assert first.instance_id not in bearer.conditions
    assert second.instance_id in bearer.conditions
