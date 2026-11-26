"""Replacing a Mantle removes its full effect bundle, including after reload."""
import pytest
from tests.hunt31_support import OWNER, fixture, pick, reload, send, owner_turn

MANTLE = 'HUNGER_BASE_DIGESTIVE_MANTLE'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('first', ['Predator Step', 'Beast Strength', 'Iron Stomach'])
def test_new_mantle_ends_previous_bundle(monkeypatch, tmp_path, auto, first):
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE], resources={'resource:named.satiety': 6})
    cid = pick(table, mid, 'Digestive Mantle: ' + first)
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    old_mods = {k for k, m in actor.modifiers.items() if 'digestive_mantle' in m.source_definition_id.lower()}
    old_conditions = {k for k, c in actor.conditions.items() if 'digestive_mantle' in c.source_definition_id.lower()}
    assert old_mods or old_conditions
    owner_turn(table, mid, next_turn=True)
    cid = pick(table, mid, 'Digestive Mantle: Thick Hide')
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    assert not old_mods.intersection(actor.modifiers)
    assert not old_conditions.intersection(actor.conditions)
    assert engine._effective_speed(actor) == actor.speed_ft
    trackers = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.digestive_mantle']
    assert len(trackers) == 1 and trackers[0].data['benefits'] == ['Thick Hide']
