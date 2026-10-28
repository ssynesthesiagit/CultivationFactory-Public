"""Recovered weapons return to their journaled grip (equipment_readiness), not a retired GRIP condition."""
from types import SimpleNamespace

from combat.typed_executor import _restore_recovered_grip
from combat.ext.equipment_hands import has_managed_grip

WEAPON = 'actor:owner.weapon.sword'


class _Engine:
    def __init__(self):
        self.action_catalog = {WEAPON: SimpleNamespace(display_name='Sword attack')}
        self.events = []

    def _append_event(self, event_type, source, **kwargs):
        self.events.append((event_type, source, kwargs))


def _ctx(readiness):
    actor = SimpleNamespace(entity_id='actor:owner', display_name='Owner', conditions={},
                            equipment_readiness=dict(readiness))
    engine = _Engine()
    return SimpleNamespace(actor=actor, engine=engine, source='system:test'), actor, engine


def test_recovered_stowed_weapon_is_drawn_back_into_its_grip():
    ctx, actor, engine = _ctx({WEAPON: 0})
    assert has_managed_grip(actor, WEAPON)
    _restore_recovered_grip(ctx, WEAPON)
    assert actor.equipment_readiness[WEAPON] == 1
    assert [event[0] for event in engine.events] == ['EQUIPMENT_READINESS_SET']


def test_recovered_weapon_already_drawn_is_left_alone():
    ctx, actor, engine = _ctx({WEAPON: 1})
    _restore_recovered_grip(ctx, WEAPON)
    assert actor.equipment_readiness[WEAPON] == 1
    assert engine.events == []


def test_legacy_bundle_without_managed_grip_stays_inert():
    ctx, actor, engine = _ctx({})
    assert not has_managed_grip(actor, WEAPON)
    _restore_recovered_grip(ctx, WEAPON)
    assert actor.equipment_readiness == {}
    assert engine.events == []
