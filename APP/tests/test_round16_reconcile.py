"""Older-base reviews must retain branch choices without losing corrected zone timing."""

import pytest

from combat import typed_executor, zones
from combat.gate2_runtime_content import AN
from tests.test_auto_support import ME, _bundle, _do, _engine
from tests.test_choose_one_branch import NINTH_GRAVE, TEN_THOUSAND_MASKS, THOUSAND_MONKEY, _authority, _delivery


@pytest.mark.parametrize("key", [NINTH_GRAVE, TEN_THOUSAND_MASKS])
def test_reviewed_branch_options_trigger_only_their_own_save_and_never_on_cast(key):
    mechanic = _authority()[key]
    assert mechanic["typing_status"] == "reviewed_final"
    for option in mechanic["options"]:
        e = _engine(_bundle([key], mechanic["sphere_id"]))
        foe = e.state.actors[AN]
        save = _delivery(option["effects"])
        assert save["deferred"]  # the review corrected creation-time damage/saves
        name = f"{mechanic['name']}: {option['label']}"
        action = next(a for a in e.action_catalog.values() if a.display_name == name)
        triggers = action.parameters["typed"]["zone_spec"]["triggers"]
        assert len(triggers) == 1
        active_save = _delivery(triggers[0]["effects"])
        assert not active_save.get("deferred")
        # Lane 3 types the No Bonus Actions branch on its explicit zone trigger;
        # the older deferred creation-time save is retained as inactive metadata.
        zone = next(row for row in option["effects"] if row["type"] == "zone")
        source_save = _delivery(zone["triggers"][0]["effects"])
        assert active_save["on_fail"] == source_save["on_fail"]
        assert active_save["on_success"] == source_save["on_success"]
        if key == TEN_THOUSAND_MASKS and option["label"] == "No Bonus Actions":
            assert len(active_save["on_fail"]) == 1
            assert active_save["on_fail"][0]["condition"] == "no_bonus_actions"
            assert active_save["on_fail"][0]["duration"] == "until_start_of_next_turn"
        else:
            assert active_save["on_fail"] == save["on_fail"]
        assert active_save["on_success"] == save["on_success"]
        assert triggers[0]["on"] == (["start"] if key == NINTH_GRAVE else ["enter", "start"])
        hp = foe.current_hp
        n = len(e.events)
        _do(e, name)
        assert foe.current_hp == hp
        assert not any(event.event_type == "SAVE_ROLLED" for event in e.events[n:])
        zones.on_turn_start(e, foe)
        assert sum(event.event_type == "SAVE_ROLLED" for event in e.events[n:]) == 1
        zones.on_turn_start(e, foe)
        assert sum(event.event_type == "SAVE_ROLLED" for event in e.events[n:]) == 1


def test_monkey_options_keep_the_reviewed_spatial_denial_and_deferred_activity_save():
    mechanic = _authority()[THOUSAND_MONKEY]
    assert mechanic["typing_status"] == "reviewed_final"
    # Rider lane 10: one action; the failed-save consequence is a standing menu pick (combat/ext/monkey.py).
    e = _engine(_bundle([THOUSAND_MONKEY], mechanic["sphere_id"]))
    foe = e.state.actors[AN]
    assert _delivery(mechanic["effects"])["deferred"]
    hp = foe.current_hp
    n = len(e.events)
    _do(e, mechanic["name"])
    assert foe.current_hp == hp and not any(event.event_type == "SAVE_ROLLED" for event in e.events[n:])
    assert any(rule.get("no_reactions") for rule in typed_executor.condition_rules(foe))
    foe.position = foe.position.model_copy(update={"x": 30})
    zones.sync_inside(e)
    assert not any(rule.get("no_reactions") for rule in typed_executor.condition_rules(foe))


@pytest.mark.parametrize("dc,marks", [(30, 1), (-5, 0)])
def test_poison_domain_places_exactly_one_dose_mark_on_a_failed_triggered_save(dc, marks):
    key = "tianxia.talent.poison.poison_domain"
    b = _bundle([key], "tianxia.sphere.poison")
    # Both the zone and its save consume the compiled save DC.
    for row in b["action_catalog"]:
        if row["display_name"] == "Poison Domain":
            row["parameters"]["typed"]["numbers"]["save_dc"] = dc
    e = _engine(b)
    foe = e.state.actors[AN]
    n = len(e.events)
    _do(e, "Poison Domain")
    assert not typed_executor.bears_mark(foe, ME, "Dose Mark")
    assert not any(event.event_type == "SAVE_ROLLED" for event in e.events[n:])
    zones.on_turn_start(e, foe)
    held = [c for c in foe.conditions.values() if c.condition_id == typed_executor.mark_condition_id("Dose Mark", ME)]
    assert len(held) == marks
    assert sum(event.event_type == "SAVE_ROLLED" for event in e.events[n:]) == 1
    assert not typed_executor.bears_mark(e.state.actors[ME], ME, "Dose Mark")
