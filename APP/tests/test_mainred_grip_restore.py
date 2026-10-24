"""Stowed weapons return to hand from readiness state (synthetic engine, no saved fight).

typed_executor._restore_recovered_grip used to look for a GRIP condition that no
longer exists, so a picked-up or returned weapon stayed stowed. The readiness
record (equipment_readiness: weapon -> 0 stowed, 1 drawn) is the source of truth.
"""
from types import SimpleNamespace

from combat import typed_executor


class _Engine:
    def __init__(self):
        self.action_catalog = {"w": SimpleNamespace(display_name="Axe attack")}
        self.events = []

    def _append_event(self, event_type, source, **kwargs):
        self.events.append(event_type)


def _ctx(readiness):
    engine = _Engine()
    actor = SimpleNamespace(entity_id="a", display_name="Ann", equipment_readiness=dict(readiness))
    return SimpleNamespace(engine=engine, actor=actor, source="test"), engine


def test_stowed_weapon_is_drawn_back_when_picked_up():
    ctx, engine = _ctx({"w": 0})
    typed_executor._restore_recovered_grip(ctx, "w")
    assert ctx.actor.equipment_readiness["w"] == 1
    assert engine.events == ["EQUIPMENT_READINESS_SET"]


def test_drawn_weapon_is_left_alone():
    ctx, engine = _ctx({"w": 1})
    typed_executor._restore_recovered_grip(ctx, "w")
    assert ctx.actor.equipment_readiness == {"w": 1}
    assert engine.events == []


def test_legacy_weapon_without_readiness_record_stays_inert():
    ctx, engine = _ctx({})
    typed_executor._restore_recovered_grip(ctx, "w")
    assert ctx.actor.equipment_readiness == {}
    assert engine.events == []
