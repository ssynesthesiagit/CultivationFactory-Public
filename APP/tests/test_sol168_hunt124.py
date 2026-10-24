"""HUNT124: printed Core Formation Charges, water routes and readable riders at the table."""
import pytest

from combat.typed_executor import mark_condition_id
from tests.auto_worker1_support import fight, LEFT, RIGHT, ALLY, action_sender, reload, act, turn

RETURN = "WATER_BASE_RETURN_THE_FLOW"
GATHER = "TAL_LIGHTNING_GATHER_CHARGE"
PASSAGE = "TAL_WATER_RIVER_PASSAGE"


def charge_count(engine, actor):
    # Lazy import lets baseline runs reach the table assertion before any new
    # helper is needed, rather than failing during collection on old sources.
    from combat.ext.charge_marks import charge_count as maintained
    return maintained(engine, actor)


def answer(result, option=None):
    prompt = result["reaction"]
    return {**prompt["context"], "selection": "USE" if option else "DECLINE",
            "option_ids": [option] if option else []}


def second(result, text):
    options = result["reaction"]["choice"]["options"]
    return next(o["id"] for o in options if text in str(o))


@pytest.mark.parametrize("cl", [4, 5, 9, 10, 11])
def test_gather_two_creatures_one_bonus_action_commit_reload_and_expire(tmp_path, cl):
    combat, table, mid = fight(tmp_path, [GATHER], cl=cl, ally=True)
    send = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT)
    result = send([])
    if cl >= 10:
        assert result["status"] == "REACTION_REQUIRED", result
        assert "Gather Charge" in str(result["reaction"]) and "no resource cost" in str(result["reaction"])
        result = send([answer(result, second(result, "Charge a Willing Creature"))])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == (2 if cl >= 10 else 1)
    assert any(c.condition_id == mark_condition_id("Charged", LEFT) for c in engine.state.actors[LEFT].conditions.values())
    benefit = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == "condition:typed.save_against")
    assert benefit.data["rule"]["save_against"]["next"] is True
    assert not engine.state.actors[LEFT].bonus_action_available
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 100
    assert combat.replay(mid)["status"] == "PASS"
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == 0


@pytest.mark.parametrize("ai", [False, True])
def test_gather_optional_second_charge_manual_decline_and_ai(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [GATHER], ally=True)
    send = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT, ai=ai)
    result = send([])
    if not ai:
        assert result["status"] == "REACTION_REQUIRED"
        result = send([answer(result)])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == (2 if ai else 1)


@pytest.mark.parametrize("extra", ["Charge a 5-foot Space", "Charge Your Weapon"])
def test_gather_second_space_or_weapon_shares_limit_and_persists(tmp_path, extra):
    combat, table, mid = fight(tmp_path, [GATHER], left_pb=2)
    send = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT)
    result = send([])
    answers = [answer(result, second(result, extra))]
    result = send(answers)
    if result["status"] == "REACTION_REQUIRED":
        answers.append(answer(result, result["reaction"]["choice"]["options"][0]["id"]))
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == 2
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == 0


def test_gather_at_cap_does_not_create_second_or_evict_first(tmp_path):
    combat, table, mid = fight(tmp_path, [GATHER], left_pb=1, ally=True)
    result = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT)([])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == 1
    assert not any(c.condition_id == mark_condition_id("Charged", LEFT) for c in engine.state.actors[ALLY].conditions.values())


def water_arena(rows):
    return lambda arena: arena.update(map_terrain=rows)


def passage_actions(combat, mid):
    engine = reload(combat, mid)
    return [c for c in engine.legal_candidates() if "River Passage" in c.display_name]


@pytest.mark.parametrize("ai", [False, True])
def test_river_passage_is_absent_in_dry_pillar_arena_for_manual_and_ai(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE])
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    assert not passage_actions(combat, mid)
    assert any(c.display_name.startswith("Return the Flow") for c in reload(combat, mid).legal_candidates())


@pytest.mark.parametrize("ai", [False, True])
def test_river_passage_connected_landings_exclude_other_pond_and_reload(tmp_path, ai):
    rows = [{"terrain": "river", "cells": [[x, 7] for x in range(3, 11)]},
            {"terrain": "pond", "cells": [[16, 11]]}]
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], cl=11, arena_edit=water_arena(rows))
    candidates = passage_actions(combat, mid)
    assert candidates
    source = next(c.source_definition_id for c in candidates if c.target_ids == (LEFT,))
    send = action_sender(combat, table, mid, source, ai=ai, target_id=LEFT)
    result = send([])
    if not ai:
        assert result["status"] == "REACTION_REQUIRED", result
        options = result["reaction"]["choice"]["options"]
        assert all("(16, 10)" not in str(o) and "(16, 12)" not in str(o) for o in options)
        chosen = next(o["id"] for o in options if "(10, 8)" in str(o))
        result = send([answer(result, chosen)])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].position != engine.state.actors[RIGHT].position
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) != (3, 6)
    if not ai:
        assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (10, 8)
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 100
    assert not any("place the creature on the map" in str(e.payload) for e in engine.events)


def test_river_passage_requires_origin_not_just_distant_water(tmp_path):
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE],
        arena_edit=water_arena([{"terrain": "pond", "cells": [[16, 11]]}]))
    assert not passage_actions(combat, mid)


@pytest.mark.parametrize("cl,far_allowed", [(10, False), (11, True)])
def test_river_passage_printed_range_at_cl11(tmp_path, cl, far_allowed):
    def arena_edit(arena):
        arena["width_squares"] = 80
        arena["terrain_regions"] = []
        arena["map_terrain"] = [{"terrain": "river", "cells": [[x, 7] for x in range(3, 75)]}]
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], cl=cl, arena_edit=arena_edit)
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (LEFT,))
    result = action_sender(combat, table, mid, source, target_id=LEFT)([])
    assert result["status"] == "REACTION_REQUIRED", result
    options = result["reaction"]["choice"]["options"]
    assert any("(40, 8)" in str(o) for o in options) == far_allowed
    assert not any("(74, 8)" in str(o) for o in options)


def test_river_passage_carries_willing_creature_and_preserves_caster(tmp_path):
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], ally=True,
        arena_edit=water_arena([{"terrain": "river", "cells": [[x, 7] for x in range(3, 11)]}]))
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (ALLY,))
    send = action_sender(combat, table, mid, source, target_id=ALLY)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    assert result["reaction"]["context"]["reactor_id"] == ALLY
    answers = [answer(result, "accept")]
    result = send(answers)
    assert result["status"] == "REACTION_REQUIRED", result
    chosen = second(result, "(10, 8)")
    assert send([*answers, answer(result, chosen)])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (10, 8)
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (3, 6)
    assert combat.replay(mid)["status"] == "PASS"


def test_own_disconnected_basin_is_valid_exit_and_survives_reload(tmp_path):
    shape = "WATER_BASE_SHAPE_CURRENT"
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE, shape],
        arena_edit=water_arena([{"terrain": "river", "cells": [[3, 7]]}]))
    from tests.auto_worker1_support import cell_send
    send = cell_send(table, mid, "Shape Current: Cleansing Basin", (10, 8))
    result = send([])
    assert result["status"] == "COMMITTED", result
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (LEFT,))
    send = action_sender(combat, table, mid, source, target_id=LEFT)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    picked = second(result, "(10, 8)")
    answers = [answer(result, picked)]
    result = send(answers)
    if result["status"] == "REACTION_REQUIRED":
        assert "Cleansing Basin" in str(result["reaction"])
        answers.append(answer(result, result["reaction"]["choice"]["options"][0]["id"]))
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    assert reload(combat, mid).state.actors[LEFT].position.x == 10


def test_actual_spirit_bow_seeking_rider_uses_printed_text(tmp_path):
    bow = "tianxia.subpath.qi.spirit_bow_cultivator.feature.spirit_bow"
    seeking = "tianxia.subpath.qi.spirit_bow_cultivator.feature.seeking_arrow"
    combat, table, mid = fight(tmp_path, [bow, seeking])
    result = action_sender(combat, table, mid, "Spirit Bow + Seeking Arrow: Far-Seeking Arrow")([])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    riders = [str(e.payload) for e in engine.events if e.event_type == "GM_RIDER"]
    assert any("Attacking at long range does not impose Disadvantage." in text for text in riders)
    assert not any("Advantage on None" in text for text in riders)


def test_generated_missing_roll_description_uses_printed_evidence_at_table(tmp_path):
    evidence = "Attacking at long range does not impose Disadvantage."
    combat, table, mid = fight(tmp_path, prepare=[{"type": "advantage", "applies_to": "self", "evidence": evidence}],
                              prepare_target="SELF")
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    riders = [str(e.payload) for e in engine.events if e.event_type == "GM_RIDER"]
    assert any(evidence in text for text in riders)
    assert not any("Advantage on None" in text for text in riders)


def test_later_lightning_charge_respects_weapon_and_space_capacity(tmp_path):
    combat, table, mid = fight(tmp_path, [GATHER, "TAL_LIGHTNING_LIGHTNING_LASH"], left_pb=2, left_attack_bonus=1000)
    send = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT)
    result = send([])
    assert send([answer(result, second(result, "Charge a 5-foot Space"))])["status"] == "COMMITTED"
    result = action_sender(combat, table, mid, "Lightning Lash: Charge", target_id=RIGHT)([])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert charge_count(engine, engine.state.actors[LEFT]) == 2
    cid = mark_condition_id("Charged", LEFT)
    assert any(c.condition_id == cid for c in engine.state.actors[RIGHT].conditions.values())
    assert not any(c.condition_id == cid for c in engine.state.actors[LEFT].conditions.values())
    assert combat.replay(mid)["status"] == "PASS"


def test_two_charged_spaces_have_distinct_persisted_locations(tmp_path):
    from tests.auto_worker1_support import cell_send
    combat, table, mid = fight(tmp_path, [GATHER], left_pb=2)
    send = cell_send(table, mid, "Gather Charge: Charge a 5-foot Space", (6, 6))
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    assert send([answer(result, second(result, "space (7, 6)"))])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    spaces = [z for z in engine.state.zones.values() if z.active and GATHER in z.source_definition_id]
    assert {(z.center.x, z.center.y) for z in spaces} == {(6, 6), (7, 6)}
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not any(z.active and GATHER in z.source_definition_id for z in reload(combat, mid).state.zones.values())
    assert combat.replay(mid)["status"] == "PASS"


def test_two_held_weapon_charges_remain_independent_on_a_hit(tmp_path):
    import copy
    from tests.test_carry import KIT
    from combat.ext.charge_marks import CHARGED_WEAPON

    kit = copy.deepcopy(KIT)
    kit["items"].append({"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1})
    combat, table, mid = fight(tmp_path, [GATHER], left_pb=2, left_kit=kit, left_score=30)
    send = action_sender(combat, table, mid, "Gather Charge: Charge Your Weapon", target_id=LEFT)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    answers = [answer(result, second(result, "Bi Shou"))]
    result = send(answers)
    assert result["status"] == "REACTION_REQUIRED", result
    answers.append(answer(result, second(result, "Fu (Short Axe)")))
    assert send(answers)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    held = [c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == CHARGED_WEAPON]
    assert len(held) == 2 and len({c.data["weapon"] for c in held}) == 2
    send = action_sender(combat, table, mid, "Bi Shou (Dagger) attack", target_id=RIGHT)
    result = send([])
    if result["status"] == "REACTION_REQUIRED":
        result = send([answer(result, result["reaction"]["choice"]["options"][0]["id"])])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    held = [c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == CHARGED_WEAPON]
    assert len(held) == 1 and "fu" in held[0].data["weapon"]


@pytest.mark.parametrize("cl,significant,far_allowed", [(14, True, False), (15, False, False), (15, True, True)])
def test_river_passage_mile_requires_cl15_and_significant_connected_water(tmp_path, cl, significant, far_allowed):
    def arena_edit(arena):
        arena["width_squares"] = 80
        arena["terrain_regions"] = []
        arena["map_terrain"] = [{"terrain": "river", "cells": [[x, 7] for x in range(3, 75)],
                                  "significant_water_source": significant}]
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], cl=cl, arena_edit=arena_edit)
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (LEFT,))
    result = action_sender(combat, table, mid, source, target_id=LEFT)([])
    assert result["status"] == "REACTION_REQUIRED", result
    assert any("(74, 8)" in str(o) for o in result["reaction"]["choice"]["options"]) == far_allowed


def test_river_origin_uses_large_creatures_whole_footprint(tmp_path):
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE],
        prepare=[{"type": "size_change", "size": "Large", "duration": "until_removed"}], prepare_target="SELF",
        positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 15, "y": 11}},
        arena_edit=water_arena([{"terrain": "river", "cells": [[5, 7], [6, 7], [7, 7]]}]))
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    assert any(c.target_ids == (LEFT,) for c in passage_actions(combat, mid))


def test_gather_space_choices_exclude_all_occupied_squares(tmp_path):
    combat, table, mid = fight(tmp_path, [GATHER])
    engine = reload(combat, mid)
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith("Gather Charge: Charge a 5-foot Space")]
    assert candidates
    occupied = {(a.position.x, a.position.y) for a in engine.state.actors.values() if a.active}
    assert all((c.destination.x, c.destination.y) not in occupied for c in candidates)


def test_rider_text_preserves_once_per_turn_bookkeeping_after_reload(tmp_path):
    evidence = "Attacking at long range does not impose Disadvantage."
    combat, table, mid = fight(tmp_path, prepare=[{"type": "advantage", "applies_to": "self", "evidence": evidence,
        "modifier_once": "test:sol168.mode", "modifier_once_period": "turn"}], prepare_target="SELF")
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    assert act(table, mid, "Prepare")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get("typed_once_turn:modifier:test:sol168.mode")
    assert sum(evidence in str(e.payload) for e in engine.events if e.event_type == "GM_RIDER") == 1


@pytest.mark.parametrize("old_catalog", [False, True])
@pytest.mark.parametrize("caster_ai", [False, True])
@pytest.mark.parametrize("consenting", [False, True])
def test_river_passage_other_team_passenger_owns_accept_or_decline(tmp_path, old_catalog, caster_ai, consenting):
    def bundle_edit(bundle):
        if old_catalog:
            for action in bundle["action_catalog"]:
                if (action.get("parameters", {}).get("typed", {}).get("modifier") or {}).get("id") == PASSAGE:
                    action["target_kind"] = "HOSTILE_ENTITY_OR_SELF"
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE],
        bundle_edit=bundle_edit,
        arena_edit=water_arena([{"terrain": "river", "cells": [[x, 7] for x in range(3, 11)]}]))
    engine = reload(combat, mid)
    before = engine.state.actors[RIGHT].position
    candidate = next((c for c in passage_actions(combat, mid) if c.target_ids == (RIGHT,)), None)
    assert candidate is not None, "Willing creatures remain eligible regardless of team"
    state = table.state(mid)
    assert any(RIGHT in option.get("target_ids", [])
               for group in state["menu"]["actions"] if "River Passage" in group["label"]
               for option in group["options"])
    send = action_sender(combat, table, mid, candidate.source_definition_id, target_id=RIGHT, ai=caster_ai)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    assert result["reaction"]["context"]["reactor_id"] == RIGHT
    assert "River Passage" in str(result["reaction"]) and "Visitor" in str(result["reaction"])
    assert reload(combat, mid).state.actors[RIGHT].position == before
    answers = [answer(result, "accept" if consenting else None)]
    result = send(answers)
    if consenting and not caster_ai:
        assert result["status"] == "REACTION_REQUIRED", result
        assert result["reaction"]["context"]["reactor_id"] == LEFT
        answers.append(answer(result, second(result, "(10, 8)")))
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    after = engine.state.actors[RIGHT].position
    assert (after != before) == consenting
    if consenting and not caster_ai:
        assert (after.x, after.y) == (10, 8)
    assert engine.state.actors[LEFT].position.x == 3
    assert not engine.state.actors[LEFT].bonus_action_available
    assert combat.replay(mid)["status"] == "PASS"


@pytest.mark.parametrize("old_catalog", [False, True])
@pytest.mark.parametrize("caster_ai", [False, True])
def test_river_passage_other_team_ai_passenger_decides_automatically(tmp_path, old_catalog, caster_ai):
    def bundle_edit(bundle):
        if old_catalog:
            for action in bundle["action_catalog"]:
                if (action.get("parameters", {}).get("typed", {}).get("modifier") or {}).get("id") == PASSAGE:
                    action["target_kind"] = "HOSTILE_ENTITY_OR_SELF"
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], bundle_edit=bundle_edit,
        arena_edit=water_arena([{"terrain": "river", "cells": [[x, 7] for x in range(3, 11)]}]))
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    before = reload(combat, mid).state.actors[RIGHT].position
    candidate = next((c for c in passage_actions(combat, mid) if c.target_ids == (RIGHT,)), None)
    assert candidate is not None, "Other-team AI passengers are eligible"
    send = action_sender(combat, table, mid, candidate.source_definition_id, target_id=RIGHT, ai=caster_ai)
    result = send([])
    if not caster_ai:
        assert result["status"] == "REACTION_REQUIRED", result
        assert result["reaction"]["context"]["reactor_id"] == LEFT
        result = send([answer(result, second(result, "(10, 8)"))])
    assert result["status"] == "COMMITTED", result
    assert reload(combat, mid).state.actors[RIGHT].position != before
    assert combat.replay(mid)["status"] == "PASS"


def test_second_charge_picker_excludes_occupied_space_and_commits_legal_zone(tmp_path):
    combat, table, mid = fight(tmp_path, [GATHER])
    send = action_sender(combat, table, mid, "Gather Charge: Charge Yourself", target_id=LEFT)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    options = result["reaction"]["choice"]["options"]
    assert not any("space (4, 6)" in str(o) for o in options)
    picked = second(result, "space (5, 6)")
    assert send([answer(result, picked)])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    spaces = [z for z in engine.state.zones.values() if z.active and GATHER in z.source_definition_id]
    assert {(z.center.x, z.center.y) for z in spaces} == {(5, 6)}
    assert combat.replay(mid)["status"] == "PASS"


@pytest.mark.parametrize("connected_source", [True, False])
def test_mile_route_connects_ordinary_river_to_small_significant_source(tmp_path, connected_source):
    def arena_edit(arena):
        arena["width_squares"] = 80
        arena["terrain_regions"] = []
        arena["map_terrain"] = [
            {"terrain": "water source", "cells": [[20, 7] if connected_source else [3, 5]],
             "significant_water_source": True},
            {"terrain": "river", "cells": [[x, 7] for x in range(3, 75)]},
            {"terrain": "pond", "cells": [[74, 12]], "significant_water_source": True}]
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], arena_edit=arena_edit)
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (LEFT,))
    send = action_sender(combat, table, mid, source, target_id=LEFT)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    assert not any("(74, 13)" in str(o) for o in result["reaction"]["choice"]["options"])
    assert any("(74, 8)" in str(o) for o in result["reaction"]["choice"]["options"]) == connected_source
    if not connected_source:
        assert send([answer(result)])["status"] == "COMMITTED"
        assert reload(combat, mid).state.actors[LEFT].position.x == 3
        return
    picked = second(result, "(74, 8)")
    assert send([answer(result, picked)])["status"] == "COMMITTED"
    assert reload(combat, mid).state.actors[LEFT].position.x == 74
    assert combat.replay(mid)["status"] == "PASS"


@pytest.mark.parametrize("caster_ai,passenger_ai", [(False, False), (True, False), (False, True), (True, True)])
def test_passenger_owns_consent_on_manual_and_ai_caster_turns(tmp_path, caster_ai, passenger_ai):
    combat, table, mid = fight(tmp_path, [RETURN, PASSAGE], ally=True,
        arena_edit=water_arena([{"terrain": "river", "cells": [[x, 7] for x in range(3, 11)]}]))
    if passenger_ai:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
    source = next(c.source_definition_id for c in passage_actions(combat, mid) if c.target_ids == (ALLY,))
    send = action_sender(combat, table, mid, source, target_id=ALLY, ai=caster_ai)
    result = send([])
    if not passenger_ai:
        assert result["status"] == "REACTION_REQUIRED", result
        assert result["reaction"]["context"]["reactor_id"] == ALLY
        assert "River Passage" in str(result["reaction"]) and "Visitor" in str(result["reaction"])
        assert send([answer(result)])["status"] == "COMMITTED"
        assert reload(combat, mid).state.actors[ALLY].position.x == 3
    elif not caster_ai:
        assert result["status"] == "REACTION_REQUIRED", result
        assert send([answer(result, second(result, "(10, 8)"))])["status"] == "COMMITTED"
        assert reload(combat, mid).state.actors[ALLY].position.x == 10
    else:
        assert result["status"] == "COMMITTED", result
        assert reload(combat, mid).state.actors[ALLY].position.y != 5
    assert combat.replay(mid)["status"] == "PASS"
