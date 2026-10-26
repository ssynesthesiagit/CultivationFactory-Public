"""Synthetic object evidence and real table delivery; no owner data or model server."""
from copy import deepcopy

import pytest

from combat.ext.talismans import PREPARED, TALENT
from combat.information_results import for_observer
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn
from tests.test_auto2_talismans import execute, take

SCRIPT = "TALISMANS_BASE_READ_THE_SCRIPT"
EYE = TALENT + "seal_breaker_s_eye"
PURIFY = TALENT + "purifying_talisman"
WALL = TALENT + "talisman_wall"
OBJECT = "object:map.1"


def inscription(*, rank="common", x=4, dc=10):
    return {"id": 1, "x": x, "y": 5, "kind": "custom", "material": "paper", "size": "tiny",
            "properties": {"inspection": {"kind": "inscription", "dc": dc,
                           "facts": {"family": "Attack", "rank": rank, "activation": "touch",
                                     "integrity": "stable", "connection": "door", "safe_touch": 0},
                           "trigger_avoidance": "Do not touch the written face.",
                           "secrets": {"command_word": "private-command", "crafter": FOE}}}}


def arena_with(*rows):
    def transform(arena):
        from combat.tabletop import normalize_map, to_battlefield
        document = normalize_map({"width_squares": 24, "height_squares": 20, "objects": deepcopy(list(rows))})
        arena["map_objects"] = to_battlefield(document)["map_objects"]
    return transform


def read(tmp_path, monkeypatch, *, rank="common", die=15, facts=("its activation method", "its formula family"),
         mids=(SCRIPT, EYE), dc=10):
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(roller, sides):
        index = roller.counter
        roller.counter += 1
        return min(die, sides), index
    monkeypatch.setattr(DeterministicRollAuthority, "_die", fixed)
    combat, table, mid = fixture(tmp_path, list(mids), battlefield_transform=arena_with(inscription(rank=rank, dc=dc)))
    chosen = candidate(combat, mid, "Read the Script", target=OBJECT)
    prompts = settle(table, mid, chosen.candidate_id, choices={
        "choice:needle.read_script_skill": "Arcana",
        "choice:needle.read_script_fact": facts,
        "choice:needle.talisman_scribe_known_formula": "a formula I have not learned",
    })
    return combat, table, mid, reload(tmp_path, mid), prompts


@pytest.mark.parametrize("rank,mode", [("common", "ADVANTAGE"), ("uncommon", "ADVANTAGE"), ("rare", "NORMAL")])
def test_script_reads_actual_object_and_eye_reveals_safe_trigger_method(tmp_path, monkeypatch, rank, mode):
    combat, table, mid, engine, prompts = read(tmp_path, monkeypatch, rank=rank)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.source_definition_id.endswith(SCRIPT)]
    assert len(checks) == 1 and checks[0].payload["actor"]["mode"] == mode
    facts = for_observer(engine, engine.state.actors[OWNER])
    result = next(row for row in facts if row.get("object_id") == OBJECT)
    assert result["facts"] == {"activation": "touch", "family": "Attack",
                               "trigger_avoidance": inscription()["properties"]["inspection"]["trigger_avoidance"]}
    assert "private-command" not in str(facts) and FOE not in str(facts)
    assert not any(row.get("object_id") == OBJECT for row in for_observer(engine, engine.state.actors[ALLY]))
    assert not any(e.event_type == "GM_RIDER" and e.source_definition_id.endswith(SCRIPT) for e in engine.events)
    assert not engine.state.actors[OWNER].action_available


@pytest.mark.parametrize("die,dc,count", [(1, 20, 0), (10, 10, 1), (15, 10, 2)])
def test_script_failure_and_success_margin_control_actual_revelations(tmp_path, monkeypatch, die, dc, count):
    combat, table, mid, engine, prompts = read(tmp_path, monkeypatch, mids=(SCRIPT,), die=die, dc=dc)
    results = [row for row in for_observer(engine, engine.state.actors[OWNER]) if row.get("object_id") == OBJECT]
    assert sum(len(row["facts"]) for row in results) == count
    assert all("trigger_avoidance" not in row["facts"] for row in results)


def test_script_has_no_fictitious_self_target_or_out_of_range_writing(tmp_path):
    combat, table, mid = fixture(tmp_path, [SCRIPT], battlefield_transform=arena_with(inscription(x=17)))
    assert not any(c.display_name == "Read the Script" for c in combat._load_session(mid).engine.legal_candidates())


@pytest.mark.parametrize("kind", ["poison", "food", "water", "miasma", "corpse_odor"])
def test_purifying_object_removes_one_minor_contamination_and_replays(tmp_path, kind):
    row = inscription()
    row["properties"]["afflictions"] = {"minor": {"kind": kind, "grade": "minor"},
                          "major": {"kind": "poison", "grade": "major"}}
    combat, table, mid = fixture(tmp_path, [PURIFY], battlefield_transform=arena_with(row),
                                positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 5}})
    before = reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED]
    take(combat, table, mid, "Purifying Talisman", OBJECT)
    engine = reload(tmp_path, mid)
    assert engine.state.objects[OBJECT].component["afflictions"] == {"major": {"kind": "poison", "grade": "major"}}
    assert engine.state.actors[OWNER].resources[PREPARED] == before - 1
    assert not any(e.event_type == "GM_RIDER" and e.source_definition_id.endswith(PURIFY) for e in engine.events)


def test_purifying_object_does_not_remove_other_or_major_conditions(tmp_path):
    row = inscription()
    row["properties"]["afflictions"] = {"major": {"kind": "poison", "grade": "major"},
                          "curse": {"kind": "curse", "grade": "minor"}}
    combat, table, mid = fixture(tmp_path, [PURIFY], battlefield_transform=arena_with(row))
    assert not any(c.target_ids == (OBJECT,) and c.display_name == "Purifying Talisman"
                   for c in combat._load_session(mid).engine.legal_candidates())


def test_talisman_wall_is_finite_physical_cover(tmp_path):
    combat, table, mid = fixture(tmp_path, [WALL])
    take(combat, table, mid, "Talisman Wall", choices={"choice:needle.talisman_wall": "1"})
    engine = reload(tmp_path, mid)
    walls = [z for z in engine.state.zones.values() if z.source_definition_id.endswith(WALL)]
    assert walls and all(z.trigger_profile["wall"]["height_ft"] == 10 for z in walls)
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.source_definition_id.endswith(WALL))
    assert action.parameters["typed"]["riders"] == []
    assert all(z.trigger_profile["numbers"]["talismans"] == 1 for z in walls)


def test_second_wall_cannot_reprice_the_first_walls_hit_points(tmp_path):
    combat, table, mid = fixture(tmp_path, [WALL])
    take(combat, table, mid, "Talisman Wall", choices={"choice:needle.talisman_wall": "1"})
    engine = reload(tmp_path, mid)
    first = next(z.zone_id for z in engine.state.zones.values() if z.source_definition_id.endswith(WALL))
    execute(combat, mid, next(c for c in engine.legal_candidates() if c.display_name == "End turn"))
    turn(table, mid, OWNER)
    take(combat, table, mid, "Talisman Wall", choices={"choice:needle.talisman_wall": "2"})
    engine = reload(tmp_path, mid)
    walls = [z for z in engine.state.zones.values() if z.source_definition_id.endswith(WALL)]
    assert len(walls) == 2
    assert engine.state.zones[first].trigger_profile["numbers"]["talismans"] == 1
    assert next(z for z in walls if z.zone_id != first).trigger_profile["numbers"]["talismans"] == 2


def test_encounter_can_supply_another_relevant_proficiency_without_doubling_its_total(tmp_path, monkeypatch):
    from combat.factory_compiler import compile_character
    from combat.gate2_rolls import DeterministicRollAuthority
    from tests.h1_support import sheet
    def fixed(roller, sides):
        index = roller.counter
        roller.counter += 1
        return min(10, sides), index
    monkeypatch.setattr(DeterministicRollAuthority, "_die", fixed)
    document = sheet([SCRIPT])
    document["ability_scores_and_statistics"]["skills"] = [{"skill": "Religion", "bonus": 7}]
    bundle = compile_character(document, actor_id=OWNER)
    row = inscription()
    row["properties"]["inspection"]["proficiencies"] = ["Religion"]
    combat, table, mid = fixture(tmp_path, [SCRIPT], owner_bundle=bundle,
                                battlefield_transform=arena_with(row))
    take(combat, table, mid, "Read the Script", OBJECT, {
        "choice:needle.read_script_skill": "Religion",
        "choice:needle.talisman_scribe_known_formula": "a formula I have not learned"})
    engine = reload(tmp_path, mid)
    check = next(e for e in engine.events if e.event_type == "CHECK_ROLLED"
                 and e.source_definition_id.endswith(SCRIPT))
    assert check.payload["skill"] == "Religion"
    assert check.payload["actor"]["modifier"] == 7
    assert check.payload["actor"]["total"] == 17


def test_inscription_and_contamination_survive_native_map_save_load(tmp_path):
    from combat.tabletop import TabletopMapStore, to_battlefield
    row = inscription()
    row["properties"]["afflictions"] = {"stain": {"kind": "miasma", "grade": "minor"}}
    store = TabletopMapStore(tmp_path / "maps")
    saved = store.save({"map_id": "inscription-fixture", "objects": [row]})
    loaded = store.get(saved["map_id"])
    assert loaded["objects"][0]["properties"] == row["properties"]
    assert to_battlefield(loaded)["map_objects"][0]["properties"] == row["properties"]


def test_purifying_can_choose_any_creature_not_only_allies(tmp_path):
    combat, table, mid = fixture(tmp_path, [PURIFY], positions={
        OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 7}, FOE: {"x": 4, "y": 6}})
    chosen = candidate(combat, mid, "Purifying Talisman", target=FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED]
    settle(table, mid, chosen.candidate_id, choices={})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == before - 1
    assert not engine.state.actors[OWNER].action_available
