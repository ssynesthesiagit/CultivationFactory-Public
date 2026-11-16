"""Immediate, recorded falls and source-independent falling protections."""
import pytest

from combat import falling
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel, script
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.test_lock2_persistence import act


def prone(actor):
    return any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())


@pytest.mark.parametrize("height,dice", [(1, 0), (2, 1), (6, 3), (50, 20)])
def test_launch_falls_immediately_and_damage_has_twenty_die_cap(height, dice):
    e = duel([])
    actor = e.state.actors[ME]
    actor.maximum_hp = 1000
    actor.current_hp = 1000
    script(e, [1] * 20)
    hp = actor.current_hp
    assert falling.displace(e, actor, height, "test:launch") == height * 5
    assert actor.position.z == 0 and actor.current_hp == hp - dice and prone(actor) == bool(dice)
    rolls = [r for r in e.rolls if r.reason == "FALLING_DAMAGE"]
    assert len(rolls) == int(bool(dice))
    assert any(ev.payload.get("fall_distance_ft") == height * 5 for ev in e.events)


@pytest.mark.parametrize("condition", ["prone", "grappled", "incapacitated"])
@pytest.mark.parametrize("hover", [False, True])
def test_prone_speed_zero_and_incapacity_fall_unless_hovering(condition, hover):
    e = duel([])
    actor = e.state.actors[ME]
    actor.fly_speed_ft, actor.hover = 30, hover
    actor.position = actor.position.model_copy(update={"z": 2})
    e._apply_condition(actor, "condition:typed." + condition, "test:control", FOE, expires_on=None)
    assert actor.position.z == (2 if hover else 0)


def test_falling_damage_checkpoint_runs_after_defenses_before_temporary_hp(monkeypatch):
    e = duel([])
    actor = e.state.actors[ME]
    e._grant_temp_hp(actor, 5, "test:ward", ME)
    hp = actor.current_hp
    script(e, [6])
    install(monkeypatch, "final_damage", lambda *a: {"amount": 3})
    seen = []
    def reduce(engine, target, amount, context, intent):
        seen.append((amount, context.actor_id, context.distance_ft, context.cause))
        return {"amount": 1, "land_prone": False}
    install(monkeypatch, "falling_damage", reduce)
    falling.displace(e, actor, 2, "test:launch")
    assert seen == [(3, ME, 10, "test:launch")]
    assert actor.current_hp == hp and actor.temporary_hp == 4 and not prone(actor)
    assert e._fall_packet is None


def test_grounding_forbids_upward_displacement_but_not_a_forced_descent():
    e = duel([])
    actor = e.state.actors[ME]
    actor.fly_speed_ft = 30
    actor.position = actor.position.model_copy(update={"z":3})
    e._apply_condition(actor, "condition:typed.test_grounding", "test:ground", FOE, expires_on=None,
                       data={"cannot_gain_altitude":1})
    assert falling.displace(e, actor, 2, "test:launch") == 0
    assert actor.position.z == 3
    assert falling.displace(e, actor, -2, "test:ground") == 10
    assert actor.position.z == 1


def test_slow_protected_fall_is_limited_per_round_and_lands_upright():
    e = duel([])
    actor = e.state.actors[ME]
    e._apply_condition(actor, "condition:typed.test_featherfall", "test:featherfall", ME, expires_on=None,
        data={"fall_speed_ft": 60, "fall_damage_immune": 1, "fall_lands_upright": 1})
    hp = actor.current_hp
    falling.displace(e, actor, 16, "test:launch")
    assert actor.position.z == 4 and actor.current_hp == hp
    falling.settle(e)
    assert actor.position.z == 4
    e.state.round_number += 1
    falling.settle(e)
    assert actor.position.z == 0 and actor.current_hp == hp and not prone(actor)


def test_occupied_landing_uses_nearest_legal_footprint():
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    original = target.position
    actor.position = original.model_copy(update={"z": 2})
    falling.settle(e)
    assert actor.position.z == 0 and actor.position != original
    assert e.grid.distance_ft(actor.position, original) == 5
    assert target.position == original
    e._assert_invariants()


def test_fall_lands_on_finite_solid_surface_instead_of_falling_through_it():
    e = duel([])
    actor = e.state.actors[ME]
    cell = (actor.position.x, actor.position.y)
    e.grid.blocked.add(cell)
    e.grid.terrain_heights.setdefault("BLOCKED", {})[cell] = 10
    e.grid.finite_heights = True
    actor.position = actor.position.model_copy(update={"z": 4})
    script(e, [2])
    hp = actor.current_hp
    falling.settle(e)
    assert actor.position.z == 2 and actor.current_hp == hp - 2 and prone(actor)
    assert not falling.required(e, actor)
    e._assert_invariants()


@pytest.mark.parametrize("point", ["falling", "falling_damage"])
def test_fall_choice_or_invalid_reply_rolls_back_launch(monkeypatch, point):
    e = duel([])
    before = e.state.model_dump(mode="json")
    class NeedsChoice(Exception):
        pass
    def pause(*args):
        raise NeedsChoice()
    install(monkeypatch, point, pause if point == "falling" else lambda *a: {"amount": -1})
    with pytest.raises(NeedsChoice if point == "falling" else ValueError):
        with e._transaction("test:launch", "test:launch", FOE):
            falling.displace(e, e.state.actors[ME], 2, "test:launch")
    assert e.state.model_dump(mode="json") == before and not e._settling_falls


def test_launch_fall_damage_and_prone_reload_and_replay(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def launch(engine):
        script(engine, [3])
        falling.displace(engine, engine.state.actors[LEFT], 2, "test:launch", intent=engine._active_intent)
    on_hold(monkeypatch, launch)
    hp = combat._load_session(mid).engine.state.actors[LEFT].current_hp
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.current_hp == hp - 3 and actor.position.z == 0 and prone(actor)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
