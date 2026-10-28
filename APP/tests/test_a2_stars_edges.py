"""Ownership, actual-roll consumption and AI choice controls for Stars Insights."""
import pytest

from combat.ext import stars_insights as si
from tests.test_a2_stars_insights import BOLT, SEVEN, MARK, fight, bonus_rolls
from tests.auto_worker1_support import LEFT, RIGHT, act, reload, resolve, action_sender, cell_send


@pytest.mark.parametrize("auto,accept", [(False, False), (False, True), (True, True)])
def test_comet_push_choice_is_owned_and_can_be_declined(tmp_path, auto, accept):
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=[MARK], left_attack_bonus=100,
                              positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    before = reload(combat, mid).state.actors[RIGHT].position
    picks = {"choice:needle.stars_comet": ["push"] if accept else []}
    _, prompts = resolve(action_sender(combat, table, mid, "Starbolt", ai=auto, target_id=RIGHT), picks)
    engine = reload(combat, mid)
    assert engine.grid.distance_ft(before, engine.state.actors[RIGHT].position) == (5 if accept else 0)
    assert bool([p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.stars_comet"]) == (not auto)


def test_battle_rhythm_is_spent_by_a_miss_not_lent_to_the_next_attack(tmp_path):
    hit = {"type": "attack", "attack_kind": "cultivation_ranged", "on_hit": [
        {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"]}]}
    combat, table, mid = fight(tmp_path, [si.RHYTHM, SEVEN, BOLT], prepare=[MARK, hit],
                              left_attack_bonus=-100, prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, "Seven-Star Step", a))
    resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT))
    assert not any(c.condition_id == si.READY for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    _, prompts = resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    engine = reload(combat, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["modifier"] == 100
    assert not any("Seven-Star Battle Rhythm" in str(p) for p in prompts)


def test_comet_area_uses_one_shared_bonus_roll_and_only_marked_targets_may_be_pushed(tmp_path):
    spark = "STARS_TAL_FALLING_SPARK"
    combat, table, mid = fight(tmp_path, [si.COMET, spark], prepare=[MARK], extra_witness=True,
                              positions={LEFT: {"x": 0, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    _, prompts = resolve(cell_send(table, mid, "Falling Spark", (4, 6)))
    engine = reload(combat, mid)
    assert len(bonus_rolls(engine)) == 1 and bonus_rolls(engine)[0].modifier == 4
    pushed = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.stars_comet"]
    assert len(pushed) == 1 and "Visitor" in str(pushed[0])
    events = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert len(events) == 2 and all(LEFT not in e.target_ids for e in events)


def test_comet_confirmed_native_damage_keeps_bonus_on_a_real_roll(tmp_path):
    hit = {"type": "attack", "attack_kind": "cultivation_ranged", "on_hit": [
        {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["cold"]}]}
    from tests.test_a2_stars_insights import setup_bundle

    combat, table, mid = fight(tmp_path, [si.COMET], prepare=[hit], bundle_edit=setup_bundle,
                              prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    assert bonus_rolls(reload(combat, mid))[-1].modifier == 4
