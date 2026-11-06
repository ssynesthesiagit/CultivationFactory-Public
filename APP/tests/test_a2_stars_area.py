"""Comet's shared roll stays bound to each recipient through table/reload.

Setup changes only unsealed synthetic bundles; execution uses CombatService,
TabletopService's session.execute_intent journal and a cold replay/reload.
"""
import pytest

from combat.ext import stars_insights as si
from tests.test_a2_stars_insights import fight, MARK, bonus_rolls
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, reload, resolve, cell_send

SPARK = "STARS_TAL_FALLING_SPARK"


def area_fight(tmp_path, *, immune=None, successful=None, extra_damage=False):
    def sealed_setup(bundle):
        aid = bundle["actor_id"]
        if aid == LEFT and extra_damage:
            action = next(a for a in bundle["action_catalog"] if a["display_name"] == "Falling Spark")
            save = next(e for e in action["parameters"]["typed"]["effects"] if e["type"] == "save")
            save["on_fail"].append({"type": "damage", "applies_to": "target",
                "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"]})
        if aid in (ALLY, RIGHT):
            bundle["actor_template"]["saving_throws"]["DEX"] = 1000 if aid == successful else -1000
        if aid == immune:
            bundle["typed_passives"].append({"block": "defense", "kind": "immunity",
                "feature_id": "test:sealed-starlight-immunity", "damage_types": ["RADIANT", "FORCE"]})
    combat, table, mid = fight(tmp_path, [si.COMET, SPARK], prepare=[MARK],
        prepare_target="ANY_CREATURE", ally=[], ally_team="team:opponents", bundle_edit=sealed_setup,
        positions={LEFT: {"x": 0, "y": 6}, ALLY: {"x": 3, "y": 5}, RIGHT: {"x": 4, "y": 6}})
    for target in (ALLY, RIGHT):
        resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=target))
    return combat, table, mid


def comet_prompts(prompts):
    return [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.stars_comet"]


@pytest.mark.parametrize("immune", [ALLY, RIGHT], ids=["immune-first", "immune-last"])
def test_comet_area_immunity_order_does_not_change_shared_bonus(tmp_path, immune):
    combat, table, mid = area_fight(tmp_path, immune=immune)
    before = reload(combat, mid)
    positions = {aid: before.state.actors[aid].position for aid in (ALLY, RIGHT)}
    _, prompts = resolve(cell_send(table, mid, "Falling Spark", (4, 6)))
    engine = reload(combat, mid)
    saves = [e.actor_id for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert saves == [ALLY, RIGHT]
    rolls = bonus_rolls(engine)
    assert len(rolls) == 1 and rolls[0].modifier == 4
    assert engine.state.actors[immune].current_hp == 1000
    damaged = RIGHT if immune == ALLY else ALLY
    assert engine.state.actors[damaged].current_hp == 1000 - rolls[0].total
    assert engine.grid.distance_ft(positions[damaged], engine.state.actors[damaged].position) == 5
    assert len(comet_prompts(prompts)) == 1
    assert engine.state.actors[LEFT].turn_flags[si.COMET_USED] == si.turn(engine)


def test_comet_half_save_does_not_lend_push_to_a_later_unboosted_roll(tmp_path):
    combat, table, mid = area_fight(tmp_path, successful=RIGHT, extra_damage=True)
    before = reload(combat, mid)
    positions = {aid: before.state.actors[aid].position for aid in (ALLY, RIGHT)}
    _, prompts = resolve(cell_send(table, mid, "Falling Spark", (4, 6)))
    engine = reload(combat, mid)
    assert [r.modifier for r in bonus_rolls(engine)] == [4, 0]
    assert len(comet_prompts(prompts)) == 2
    for aid in (ALLY, RIGHT):
        assert engine.grid.distance_ft(positions[aid], engine.state.actors[aid].position) == 5


@pytest.mark.parametrize("successful", [RIGHT, ALLY], ids=["half-last", "half-first"])
@pytest.mark.parametrize("decline", [False, True], ids=["push", "decline"])
def test_comet_mixed_area_saves_keep_both_marked_choices_after_reload(tmp_path, successful, decline):
    combat, table, mid = area_fight(tmp_path, successful=successful)
    before = reload(combat, mid)
    positions = {aid: before.state.actors[aid].position for aid in (ALLY, RIGHT)}
    picks = {"choice:needle.stars_comet": []} if decline else None
    _, prompts = resolve(cell_send(table, mid, "Falling Spark", (4, 6)), picks)
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert [e.actor_id for e in saves] == [ALLY, RIGHT]
    assert len(bonus_rolls(engine)) == 1 and bonus_rolls(engine)[0].modifier == 4
    total = bonus_rolls(engine)[0].total
    pushed = comet_prompts(prompts)
    assert len(pushed) == 2
    for aid in (ALLY, RIGHT):
        assert engine.state.actors[aid].current_hp == 1000 - (total // 2 if aid == successful else total)
        assert engine.grid.distance_ft(positions[aid], engine.state.actors[aid].position) == (0 if decline else 5)
    assert engine.state.actors[LEFT].turn_flags[si.COMET_USED] == si.turn(engine)
