"""Empty Cup Stance's actual table standing transition respects its requirements."""
import pytest

from combat import posture
from combat.ext.drunken_style import EMPTY_CUP
from tests.auto_worker1_support import LEFT, act, fight, reload


@pytest.mark.parametrize("owns,focus,expected", [(True, True, 5), (True, False, 15), (False, True, 15)])
def test_empty_cup_stands_for_five_feet_only_with_owned_focused_stance(tmp_path, owns, focus, expected):
    effects = [{"type": "condition", "condition": "prone", "applies_to": "self", "duration": "until_removed"}]
    if not focus:
        effects.append({"type": "spend_resource", "resource_id": "resource:core.martial_focus", "flat": 1, "applies_to": "self"})
    combat, table, mid = fight(tmp_path, [EMPTY_CUP] if owns else [], prepare=effects, prepare_target="SELF")
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert posture.prone_conditions(actor)
    assert posture.standing_cost(engine, actor) == expected
    before = actor.movement_remaining_ft
    assert act(table, mid, posture.SOURCE)["status"] == "COMMITTED"
    actor = reload(combat, mid).state.actors[LEFT]
    assert not posture.prone_conditions(actor)
    assert actor.movement_remaining_ft == before - expected
    assert actor.action_available and actor.bonus_action_available


def test_empty_cup_does_not_bypass_heavy_armor(tmp_path):
    kit = {"items": [{"item_id": "tianxia.mortal.armor.imperial_plate_battle_dress",
                      "name": "Imperial Plate Battle Dress", "quantity": 1}]}
    combat, table, mid = fight(tmp_path, [EMPTY_CUP], left_kit=kit,
        prepare=[{"type": "condition", "condition": "prone", "applies_to": "self", "duration": "until_removed"}],
        prepare_target="SELF")
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    rows = [r for r in engine.typed_passive_rows[LEFT] if r.get("block") == "drunken_empty_cup"]
    assert rows[0]["armor"] == "heavy"
    cost = engine._effective_speed(actor) // 2
    assert posture.standing_cost(engine, actor) == cost
    before = actor.movement_remaining_ft
    assert act(table, mid, posture.SOURCE)["status"] == "COMMITTED"
    actor = reload(combat, mid).state.actors[LEFT]
    assert actor.movement_remaining_ft == before - cost
