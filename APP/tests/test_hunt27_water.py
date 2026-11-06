"""Returning Streams healing requires two real ended effects."""
import pytest

from tests.test_hunt27_table import ME, WATER, action, arena, commit, owner_turn

# Explicit dynamic compiler input for the public-safe exporter; these native
# scenarios maintain Court plus independently created Water effects.
CONCENTRATION_RESOURCE = 'combat/rules/concentration.json'


@pytest.mark.parametrize(("manual", "end_count"), [(True, 1), (True, 2), (False, 2)])
def test_repeated_water_lash_activations_count_only_chosen_endings(tmp_path, manual, end_count):
    from tests.test_hunt27_table import FOE, FOE2
    from combat.ext.water_return import _effects

    combat, table, mid = arena(tmp_path, WATER, "water-repeat", manual=True, foe_ac=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    engine = combat._load_session(mid).engine
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    for target in (FOE, FOE2):
        commit(combat, table, mid, tmp_path, action(combat, mid, "Water Lash", target))
        if target == FOE:
            engine = combat._load_session(mid).engine
            commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
            owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    rows = {key: row for key, row in _effects(engine, engine.state.actors[ME]).items() if "Water Lash" in row["label"]}
    assert len(rows) == 2
    assert {holder.entity_id for row in rows.values() for holder, *_ in row["instances"]} == {FOE, FOE2}
    assert len({item.source_definition_id for row in rows.values() for *_, item in row["instances"]}) == 1
    if not manual:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    start = len(engine.events)

    def choose(prompt):
        if prompt["context"]["reaction_source_id"].endswith("returning_streams_end"):
            return list(rows)[:end_count]
        return [ME]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: End It Early + Ten Thousand Returning Streams (free)"), choose=choose)
    engine = combat._load_session(mid).engine
    remaining = [c for aid in (FOE, FOE2) for c in engine.state.actors[aid].conditions.values() if "soaked" in c.condition_id]
    assert len(remaining) == 2 - end_count
    heals = [e for e in engine.events[start:] if e.event_type == "HEALING_APPLIED"]
    assert bool(heals) == (end_count == 2)
    if heals:
        assert heals[0].payload["offered"] == 6


@pytest.mark.parametrize("manual", [True, False])
def test_repeated_water_lash_returns_choose_operations_separately_and_reload(tmp_path, manual):
    """End/convert separate casts without consuming the new converted mark."""
    from tests.test_hunt27_table import FOE, FOE2
    from combat.ext.water_return import _effects

    combat, table, mid = arena(tmp_path, WATER, "water-repeat", manual=True, foe_ac=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    engine = combat._load_session(mid).engine
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    for target in (FOE, FOE2):
        commit(combat, table, mid, tmp_path, action(combat, mid, "Water Lash", target))
        if target == FOE:
            engine = combat._load_session(mid).engine
            commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
            owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    rows = {key: row for key, row in _effects(engine, engine.state.actors[ME]).items() if "Water Lash" in row["label"]}
    assert len(rows) == 2
    originals = [(holder.entity_id, instance) for row in rows.values() for holder, _, instance, _ in row["instances"]]
    first = next(key for key, row in rows.items() if row["instances"][0][0].entity_id == FOE)
    if not manual:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    start = len(engine.events)
    operations = []

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind.endswith("returning_streams_select"):
            return list(rows)
        if kind.endswith("returning_streams_operation"):
            operation = "end" if first in prompt["context"]["checkpoint"] else "soak"
            operations.append(operation)
            return [operation]
        if kind.endswith("returning_streams_target"):
            return [FOE2]
        return [ME]

    answers = commit(combat, table, mid, tmp_path,
                     action(combat, mid, "Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    events = engine.events[start:]
    assert all(instance not in engine.state.actors[aid].conditions for aid, instance in originals)
    removals = {e.payload.get("instance_id"): e.sequence for e in events if e.event_type == "CONDITION_REMOVED"}
    assert all(instance in removals for _, instance in originals)
    converted = [e for e in events if e.event_type == "CONDITION_APPLIED" and "soaked" in e.payload["condition_id"]]
    assert len(converted) == (1 if manual else 2)
    # Conversion creates a new Return activation, never a stale second choice.
    assert all(e.payload["instance_id"] not in {instance for _, instance in originals} for e in converted)
    assert max(removals[instance] for _, instance in originals) < next(e.sequence for e in events if e.event_type == "HEALING_APPLIED")
    heal = next(e for e in events if e.event_type == "HEALING_APPLIED")
    assert heal.payload["offered"] == 6
    if manual:
        assert sorted(operations) == ["end", "soak"]
        mark = next(c for c in engine.state.actors[FOE2].conditions.values() if "soaked" in c.condition_id)
        assert mark.instance_id == converted[0].payload["instance_id"]
        assert answers
    else:
        assert not answers


def minor_arena(tmp_path, manual, count=2):
    combat, table, mid = arena(tmp_path, WATER, "water-minor", manual=True)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    for name in ("Mist Basin", "Cleansing Basin")[:count]:
        end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
        commit(combat, table, mid, tmp_path, end)
        owner_turn(combat, table, mid, tmp_path, idle=True)
        engine = combat._load_session(mid).engine
        cid = next(c.candidate_id for c in engine.legal_candidates()
                   if c.display_name.startswith("Shape Current: " + name)
                   and c.destination == engine.state.actors[ME].position)
        commit(combat, table, mid, tmp_path, cid)
    if not manual:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    return combat, table, mid


@pytest.mark.parametrize("decline_at", ["operation", "target", "ally_destination"])
def test_minor_return_declined_conversion_does_not_count_as_ending_reload(tmp_path, decline_at):
    """Selecting two effects is insufficient when the second is never ended."""
    combat, table, mid = minor_arena(tmp_path, True)
    engine = combat._load_session(mid).engine
    areas = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current"]
    assert len(areas) == 2
    preserved = areas[1].model_dump(mode="json")
    positions = {aid: actor.position for aid, actor in engine.state.actors.items()}
    start = len(engine.events)
    declined = []

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind.endswith("returning_streams_select"):
            return [z.zone_id for z in areas]
        if kind.endswith("returning_streams_" + decline_at):
            # Decline only the second effect; the first is actually ended.
            if areas[1].zone_id in prompt["context"]["checkpoint"]:
                assert prompt["choice"]["allow_decline"]
                declined.append(kind)
                return None
        if kind.endswith("returning_streams_operation"):
            return ["end" if areas[0].zone_id in prompt["context"]["checkpoint"] else "ally"]
        return [ME]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Move an Ally + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    assert len(declined) == 1
    assert not engine.state.zones[areas[0].zone_id].active
    assert engine.state.zones[areas[1].zone_id].model_dump(mode="json") == preserved
    assert {aid: actor.position for aid, actor in engine.state.actors.items()} == positions
    assert not any(e.event_type == "HEALING_APPLIED" for e in engine.events[start:])
    assert not any(e.payload.get("returning_streams_moved") for e in engine.events[start:])


@pytest.mark.parametrize(("manual", "mixed"), [(True, False), (False, False), (True, True)])
def test_returning_streams_move_preserves_attached_effects_reload(tmp_path, manual, mixed):
    """Independent-area movement must not detach an Emanation or self-benefit."""
    combat, table, mid = arena(tmp_path, WATER + ["TAL_WATER_OCEAN_SOVEREIGN_INCARNATION"],
                               "water-attached", manual=manual)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
    commit(combat, table, mid, tmp_path, end)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Ocean-Sovereign Incarnation"))
    engine = combat._load_session(mid).engine
    from combat.ext.water_return import _effects

    effects = _effects(engine, engine.state.actors[ME])
    court = next(row["zone"] for row in effects.values() if row.get("zone"))
    incarnation = next(row for row in effects.values() if "Incarnation" in row["label"])
    assert incarnation["instances"]
    original = court.model_dump(mode="json")
    instances = [(holder.entity_id, kind, key, item.model_dump(mode="json"))
                 for holder, kind, key, item in incarnation["instances"]]
    positions = {aid: actor.position for aid, actor in engine.state.actors.items()}
    start = len(engine.events)
    operations = []

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind == "choice:free_uses.funding":
            options = prompt["choice"]["options"]
            assert len(options) == 2
            assert any("Court" in option["label"] for option in options)
            assert any("Incarnation" in option["label"] for option in options)
            return [options[0]["id"]]
        if kind.endswith("returning_streams_select"):
            return list(effects)
        assert kind.endswith("returning_streams_operation")
        assert "move" not in {option["id"] for option in prompt["choice"]["options"]}
        operations.append(kind)
        return None

    name = "Soak a Creature" if mixed else "Move Water Effect"
    answers = commit(combat, table, mid, tmp_path,
                     action(combat, mid, f"Return the Flow: {name} + Ten Thousand Returning Streams (free)",
                            target=None if mixed else ME), choose=choose)
    engine = combat._load_session(mid).engine
    # Both active states grant a free Return. Main now asks a manual player
    # which grant to spend, even when no independent area can be moved.
    assert sum(a["reaction_source_id"] == "choice:free_uses.funding" for a in answers) == int(manual)
    assert len(answers) == int(manual) + 3 * int(mixed)
    assert len(operations) == (2 if mixed else 0)
    assert engine.state.zones[court.zone_id].model_dump(mode="json") == original
    for aid, kind, key, item in instances:
        stored = engine.state.actors[aid].conditions if kind == "condition" else engine.state.actors[aid].modifiers
        assert stored[key].model_dump(mode="json") == item
    assert {aid: actor.position for aid, actor in engine.state.actors.items()} == positions
    assert not any(e.event_type in ("ZONE_CREATED", "HEALING_APPLIED", "CONDITION_REMOVED", "MODIFIER_REMOVED")
                   for e in engine.events[start:])


@pytest.mark.parametrize(("manual", "count"), [(True, 1), (True, 2), (False, 2)])
def test_minor_return_consumes_selected_areas_and_reloads(tmp_path, manual, count):
    combat, table, mid = minor_arena(tmp_path, manual, count)
    engine = combat._load_session(mid).engine
    areas = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current"]
    start = len(engine.events)

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind.endswith("returning_streams_select"):
            return [z.zone_id for z in areas]
        if kind.endswith("returning_streams_operation"):
            # Mixed choices within one activation: end the first, convert the second.
            return ["end" if count == 2 and areas[0].zone_id in prompt["context"]["checkpoint"] else "soak"]
        return [ME]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    assert all(not engine.state.zones[z.zone_id].active for z in areas)
    affected = [engine.state.actors[ME]] if manual else list(engine.state.actors.values())
    assert any("soaked" in c.condition_id for a in affected for c in a.conditions.values())
    assert bool([e for e in engine.events[start:] if e.event_type == "HEALING_APPLIED"]) == (count == 2)
    # Conversion ends the original area, but never ends the Court automatically.
    assert any(z.active and "Court" in z.trigger_profile.get("name", "") for z in engine.state.zones.values())


@pytest.mark.parametrize("manual", [True, False])
def test_minor_return_moves_allies_once_per_turn_and_reloads(tmp_path, manual):
    from tests.test_hunt27_table import ALLY

    combat, table, mid = minor_arena(tmp_path, manual)
    engine = combat._load_session(mid).engine
    before = {aid: engine.state.actors[aid].position for aid in (ME, ALLY)}
    areas = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current"]
    start = len(engine.events)
    target_prompts = []

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        options = prompt["choice"]["options"]
        if kind.endswith("returning_streams_select"):
            return [z.zone_id for z in areas]
        if kind.endswith("returning_streams_operation"):
            return ["ally"]
        if kind.endswith("returning_streams_target"):
            target_prompts.append([o["id"] for o in options])
            if len(target_prompts) == 1:
                return [ME]
            assert ME not in target_prompts[-1]
            return [ALLY]
        if kind.endswith("returning_streams_ally_destination"):
            return [options[0]["id"]]
        return [ME]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Move an Ally + Ten Thousand Returning Streams (free)"), choose=choose)
    engine = combat._load_session(mid).engine
    movements = [e for e in engine.events[start:] if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("returning_streams_moved")]
    assert len(movements) == 2
    assert len({e.payload["returning_streams_moved"] for e in movements}) == 2
    for aid in (ME, ALLY):
        assert engine.grid.distance_ft(before[aid], engine.state.actors[aid].position) == 5
    assert all(not engine.state.zones[z.zone_id].active for z in areas)
    assert not any(e.event_type == "REACTION_DECLARED" and "opportunity" in e.source_definition_id.lower()
                   for e in engine.events[start:])
    assert any(e.event_type == "HEALING_APPLIED" for e in engine.events[start:])


def test_minor_return_mixes_movement_and_conversion_without_healing(tmp_path):
    combat, table, mid = minor_arena(tmp_path, True)
    engine = combat._load_session(mid).engine
    areas = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current"]
    start = len(engine.events)

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind.endswith("returning_streams_select"):
            return [z.zone_id for z in areas]
        if kind.endswith("returning_streams_operation"):
            return ["move" if areas[0].zone_id in prompt["context"]["checkpoint"] else "soak"]
        if kind.endswith("returning_streams_destination"):
            return [prompt["choice"]["options"][0]["id"]]
        return [ME]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    assert engine.state.zones[areas[0].zone_id].active
    assert engine.state.zones[areas[0].zone_id].center != areas[0].center
    assert not engine.state.zones[areas[1].zone_id].active
    assert not any(e.event_type == "HEALING_APPLIED" for e in engine.events[start:])
    end = next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN")
    commit(combat, table, mid, tmp_path, end)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    assert any("soaked" in c.condition_id for c in combat._load_session(mid).engine.state.actors[ME].conditions.values())
    end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
    commit(combat, table, mid, tmp_path, end)
    assert not any("soaked" in c.condition_id for c in combat._load_session(mid).engine.state.actors[ME].conditions.values())


@pytest.mark.parametrize("manual", [True, False])
def test_minor_return_consumes_non_zone_effect_and_reloads(tmp_path, manual):
    talents = WATER + ["TAL_WATER_OCEAN_SOVEREIGN_INCARNATION"]
    combat, table, mid = arena(tmp_path, talents, "water-minor-condition", manual=manual)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
    commit(combat, table, mid, tmp_path, end)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Ocean-Sovereign Incarnation"))
    engine = combat._load_session(mid).engine
    from combat.ext.water_return import _effects

    # Read-only discovery for assertions; setup still uses real table casts.
    selected = [key for key, row in _effects(engine, engine.state.actors[ME]).items() if "Incarnation" in row["label"]]
    assert len(selected) == 1
    source = _effects(engine, engine.state.actors[ME])[selected[0]]["instances"][0][3].source_definition_id

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind.endswith("returning_streams_select"):
            return selected
        if kind.endswith("returning_streams_operation"):
            return ["soak"]
        return [ME]

    start = len(engine.events)
    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[ME]
    assert not any(c.source_definition_id == source for c in actor.conditions.values())
    assert not any(m.source_definition_id == source and not m.consumed for m in actor.modifiers.values())
    assert any("soaked" in c.condition_id for a in engine.state.actors.values() for c in a.conditions.values())
    assert not any(e.event_type == "HEALING_APPLIED" for e in engine.events[start:])


def test_minor_return_compilation_and_descriptions_are_owner_gated():
    from combat.factory_compiler import compile_character
    from combat.ext.water_return import returning_streams_minor_description
    from tests.h1_support import sheet

    for talents, expected in ((WATER[:1], False), (WATER, True)):
        actions = compile_character(sheet(talents, cl=20), actor_id=ME)["action_catalog"]
        minor = [a for a in actions if any(e.get("type") == "water_returning_streams_minor"
                                         for e in a["parameters"].get("typed", {}).get("effects", []))]
        assert bool(minor) == expected
        if expected:
            assert len(minor) == 4  # two preferred operations, ordinary/free timing
            for row in minor:
                assert row["target_kind"] == "SELF"
                text = returning_streams_minor_description(row)
                assert "consume" in text and "5 feet" in text and "GM resolves" in text
                assert "no Cultivation Point cost" in text and "remaining duration" in text
                assert ("no Action or Bonus Action" if row["economy"] == "NONE" else "Bonus Action") in text


@pytest.mark.parametrize("operation", ["flame", "source"])
def test_minor_return_records_conversion_for_gm_resolution(tmp_path, operation):
    combat, table, mid = minor_arena(tmp_path, True, count=1)
    engine = combat._load_session(mid).engine
    area = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current")
    start = len(engine.events)

    def choose(prompt):
        if prompt["context"]["reaction_source_id"].endswith("returning_streams_select"):
            return [area.zone_id]
        return [operation]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)", target=None), choose=choose)
    engine = combat._load_session(mid).engine
    assert not engine.state.zones[area.zone_id].active
    riders = [e.payload["rider"] for e in engine.events[start:] if e.event_type == "GM_RIDER"]
    assert any("The GM resolves" in text and ("ordinary flame" if operation == "flame" else "Water Source") in text for text in riders)
    assert not any(e.event_type == "HEALING_APPLIED" for e in engine.events[start:])


@pytest.mark.parametrize(("manual", "count"), [(True, 1), (False, 1), (True, 2), (False, 2)])
def test_returning_streams_moves_water_area_and_reloads(tmp_path, manual, count):
    # The AI's representative catalog omits secondary Shape Current forms.
    # Set up both areas through manual table casts, then use the public mode
    # switch so the operation under test is still a genuine AI transaction.
    combat, table, mid = arena(tmp_path, WATER, "water-move", manual=manual or count == 2)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
    commit(combat, table, mid, tmp_path, end)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Shape Current: Mist Basin", target=None))
    if count == 2:
        end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
        commit(combat, table, mid, tmp_path, end)
        owner_turn(combat, table, mid, tmp_path, idle=True)
        commit(combat, table, mid, tmp_path, action(combat, mid, "Shape Current: Cleansing Basin", target=None))
        if not manual:
            combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    areas = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Shape Current"]
    assert len(areas) == count
    zone = areas[0]
    original = zone.model_dump(mode="json")
    start = len(engine.events)

    def choose(prompt):
        options = prompt["choice"]["options"]
        if prompt["context"]["reaction_source_id"].endswith("returning_streams_move"):
            assert prompt["choice"]["maximum"] <= 3
            return [z.zone_id for z in areas]
        # The printed talent permits 20 feet, beyond the base 10-foot move.
        import re
        assert all(0 < int(re.search(r" (\d+) feet to square", o["label"])[1]) <= 20 for o in options)
        return [next(o["id"] for o in options if "20 feet" in o["label"])]

    answers = commit(combat, table, mid, tmp_path,
                     action(combat, mid, "Return the Flow: Move Water Effect + Ten Thousand Returning Streams (free)"), choose=choose)
    engine = combat._load_session(mid).engine
    moved = engine.state.zones[zone.zone_id]
    assert moved.center != zone.center
    assert engine.grid.distance_ft(moved.center, zone.center) <= 20
    if manual:
        assert engine.grid.distance_ft(moved.center, zone.center) == 20
        assert len(answers) == count + 1
    for area in areas:
        new = engine.state.zones[area.zone_id]
        assert 0 < engine.grid.distance_ft(new.center, area.center) <= 20
        assert new.affected_cells != area.affected_cells
    assert moved.affected_cells != zone.affected_cells
    for key in ("created_round", "duration_rounds", "concentration_link", "source_definition_id", "trigger_profile"):
        assert moved.model_dump(mode="json")[key] == original[key]
    events = engine.events[start:]
    updates = [e for e in events if e.event_type == "ZONE_CREATED" and e.payload["zone"]["zone_id"] == zone.zone_id]
    assert len(updates) == 1
    assert updates[0].payload["retained_instance_update"] == 1
    assert not any(e.event_type == "HEALING_APPLIED" for e in events)


def test_returning_streams_move_is_owner_gated():
    from combat.factory_compiler import compile_character
    from combat.ext.water_return import returning_streams_move_description
    from tests.h1_support import sheet

    for talents, expected in ((WATER[:1], False), (WATER, True)):
        bundle = compile_character(sheet(talents, cl=20), actor_id=ME)
        moves = [a for a in bundle["action_catalog"] if any(
            e.get("type") == "water_returning_streams_move" for e in a["parameters"].get("typed", {}).get("effects", []))]
        assert bool(moves) == expected
        if expected:
            assert len(moves) == 2  # ordinary and the Court's free use
            assert all("up to 20 feet" in returning_streams_move_description(a) for a in moves)
            assert all(("no Action or Bonus Action" if a["economy"] == "NONE" else "Bonus Action")
                       in returning_streams_move_description(a) for a in moves)


@pytest.mark.parametrize("manual", [True, False])
def test_returning_streams_does_not_heal_without_ending_effects(tmp_path, manual):
    combat, table, mid = arena(tmp_path, WATER, "water", manual=manual)
    owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    engine = combat._load_session(mid).engine
    start = len(engine.events)
    name = "Return the Flow: Move Water Effect + Ten Thousand Returning Streams (free)"
    commit(combat, table, mid, tmp_path, action(combat, mid, name))
    assert not any(e.event_type == "HEALING_APPLIED" for e in combat._load_session(mid).engine.events[start:])


@pytest.mark.parametrize(("manual", "count"), [(True, 1), (True, 2), (False, 2)])
def test_returning_streams_ends_selected_effects_before_optional_heal(tmp_path, count, manual):
    talents = WATER + ["TAL_WATER_OCEAN_SOVEREIGN_INCARNATION"]
    combat, table, mid = arena(tmp_path, talents, "water", manual=manual)
    owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Court of the Endless Tide"))
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Shape Current: Mist Basin", target=None))
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Ocean-Sovereign Incarnation"))
    engine = combat._load_session(mid).engine
    start = len(engine.events)

    def choose(prompt):
        if prompt["context"]["reaction_source_id"].endswith("returning_streams_end"):
            options = [o["id"] for o in prompt["choice"]["options"] if "Court of the Endless Tide" not in o["label"]]
            assert len(options) >= 2
            return options[:count]
        return [ME]

    answers = commit(combat, table, mid, tmp_path,
                     action(combat, mid, "Return the Flow: End It Early + Ten Thousand Returning Streams (free)"), choose=choose)
    engine = combat._load_session(mid).engine
    events = engine.events[start:]
    heals = [e for e in events if e.event_type == "HEALING_APPLIED"]
    assert bool(heals) == (count == 2)
    assert any(e.event_type in ("CONDITION_REMOVED", "MODIFIER_REMOVED") for e in events)
    if heals:
        assert heals[0].payload["offered"] == 6
        assert heals[0].sequence > max(e.sequence for e in events if e.event_type in ("CONDITION_REMOVED", "MODIFIER_REMOVED"))
        assert len(answers) == (2 if manual else 0)
