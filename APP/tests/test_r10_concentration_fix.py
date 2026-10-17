"""Clinging Anchor lifetime through actual Impact, table commit and reload."""
import pytest
from combat import concentration
from combat.ext import force
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, table_fight, on_hold
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import fixed_dice, cast_sender, commit


@pytest.mark.parametrize("held_first", [False, True])
def test_actual_clinging_cast_ends_only_with_its_cast_across_reload(monkeypatch, tmp_path, held_first):
    combat, table, mid = table_fight(tmp_path, [force.IMPACT, "TAL_FORCE_CLINGING_ANCHOR"], cl=20, ally_talents=[])
    fixed_dice(monkeypatch, [15, 15] + [1] * 40)
    commit(cast_sender(combat, table, mid, "Impact", contains="Clinging", target=RIGHT))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, owner, target = loaded.engine, loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]
    conditions = [c for c in target.conditions.values() if c.condition_id == force.CLUNG]
    assert conditions, [(e.event_type, e.source_definition_id, e.payload) for e in engine.events[-15:]]
    condition = conditions[0]
    assert condition.data["cast_sequence"] == owner.concentration.started_sequence
    original_cast = condition.data["cast_sequence"]
    finish = []
    def end_one(e):
        me = e.state.actors[LEFT]
        if finish:
            e._end_concentration(me, "VOLUNTARY")
            return
        e._start_concentration(me, "test:unrelated")
        if held_first:
            iid = next(iid for iid, c in concentration.held(me) if c.started_sequence == original_cast)
            concentration.end_held(e, me, iid, "VOLUNTARY")
        else:
            e._end_concentration(me, "VOLUNTARY")
    on_hold(monkeypatch, end_one)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target, owner = loaded.engine.state.actors[RIGHT], loaded.engine.state.actors[LEFT]
    assert bool([c for c in target.conditions.values() if c.condition_id == force.CLUNG]) == (not held_first)
    assert bool(force.external(loaded.engine, owner)) == (not held_first)
    assert loaded.mechanical.replay()["status"] == "PASS"
    if not held_first:
        # The unrelated current cast ended; the original anchor cast resumed.
        assert owner.concentration.started_sequence == original_cast
        finish.append(True)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert not force.external(loaded.engine, loaded.engine.state.actors[LEFT])
        assert not any(c.condition_id == force.CLUNG for c in loaded.engine.state.actors[RIGHT].conditions.values())


def test_actual_clinging_failed_save_has_a_ten_round_deadline():
    from tests import test_riders_lane10 as lane
    _, engine, owner, target = lane.SWF.fight(force.IMPACT, extras=("TAL_FORCE_CLINGING_ANCHOR",))
    lane.SWF.cast(engine, "Impact", contains="Clinging", target=lane.FOE)
    zone = force.external(engine, owner)[0]
    from combat.ext import placed
    assert placed.data(zone)["until"].startswith("START_OF_SLOT_AT:")
    engine.state.round_number += 10
    engine._system_start_turn()
    assert not force.external(engine, owner)
    assert not any(c.condition_id == force.CLUNG for c in target.conditions.values())
