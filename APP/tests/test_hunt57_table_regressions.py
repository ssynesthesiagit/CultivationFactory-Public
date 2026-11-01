"""Hunt 57 regressions through committed TabletopService actions and saved fights."""
import json
import zipfile
import pytest
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from combat import concentration, zones
from combat.ext.persistent_areas import PERSISTENT_AREA
from combat import ext
from tests.h1_support import sheet


APP = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.57570001"
FORCE = "TAL_FORCE_FORCE_MANTLE"
MUSIC = "tianxia.talent.music.court_of_resonant_measure"
DARK = "DARK_BASE_DARKNESS"


def setup(user, label, talents, *, qi=30):
    ids = ["57570001", "57570002", "57570003", "57570004"]
    for index, pid in enumerate(ids):
        data = sheet(talents if index == 0 else [], cl=10)
        data["identity"]["display_name"] = ["You", "Ally", "Foe", "Second Foe"][index]
        data["ability_scores_and_statistics"]["hit_points"]["maximum"] = 900
        data["ability_scores_and_statistics"]["primary_resource"]["maximum"] = qi
        folder = user / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(data))
    ButtonStore(user / "tabletop_buttons").save_reactions(ids[0], {"mode": "ask"}, set())
    service = CombatService(APP, user)
    arena = service.tabletop_maps.save({"display_name": "Duration wall", "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "rect", "points": [[6, 0], [6, 7]], "filled": True}],
        "starts": {"team1": [[2, 3], [2, 4]], "team2": [[9, 3], [9, 4]]}})
    match = service.create_factory_match(project_ids=ids[:2], opponent_actor_ids=["actor:factory." + p for p in ids[2:]],
        control_modes={"actor:factory." + p: "MANUAL" for p in ids}, arena_id="battlefield:map." + arena["map_id"],
        match_seed=label, maximum_rounds=14, prefight={p: [] for p in ids})["match_id"]
    return service, TabletopService(service, user), match


def take(service, table, match, *, source=None, augmented=False):
    state = table.state(match)
    menu = state["menu"]
    if source:
        engine = service._load_session(match).engine
        groups = [g for g in menu["actions"] if (engine.action_catalog.get(g["source_definition_id"]) and
            engine.action_catalog[g["source_definition_id"]].parameters.get("typed", {}).get("source") == source and
            not engine.action_catalog[g["source_definition_id"]].parameters.get("augment_toggle") and
            (augmented or "+" not in g["label"]))]
        options = [o for g in groups for o in g["options"]]
        option = options[0]
        candidate = option["candidate_id"]
    else:
        candidate = menu["end_turn"]
    return commit_option(table, match, state, candidate)


def commit_option(table, match, state, candidate):
    """Drive native placement and willing-ally choices without swallowing other prompts."""
    menu = state["menu"]
    answers, prompts = [], []
    for _ in range(8):
        result = table.act(match, candidate, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        if source == "choice:placement_menu.square":
            # The old eager menu used its first legal square. Choose that same
            # native option in the deferred picker; never invent a legal cell.
            picked = prompt["choice"]["options"][0]["id"]
        else:
            assert source == "choice:willing.consent", prompt
            picked = "accept"  # These fixtures cast their Aegis on a willing ally.
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [picked]})
    raise AssertionError("too many prompts")


def owner_turn(service, table, match):
    for _ in range(100):
        if service._load_session(match).engine.state.current_actor_id == OWNER:
            return
        take(service, table, match)
    raise AssertionError("owner turn unavailable")


def recovered(service, match, user):
    before = service._load_session(match).engine.state.model_dump(mode="json")
    session = CombatService(APP, user)._load_session(match)
    assert session.engine.state.model_dump(mode="json") == before
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def select(table, match, label, target=None):
    state = table.state(match)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    option = next(o for o in group["options"] if target is None or target in o["target_ids"])
    return commit_option(table, match, state, option["candidate_id"])


@pytest.mark.parametrize("qi", [1, 30])
def test_darkness_driver_commits_native_square_choice_and_reloads(tmp_path, qi):
    """Both reviewed resource branches must complete the real deferred placement."""
    service, table, match = setup(tmp_path, "H57-placement", [DARK], qi=qi)
    owner_turn(service, table, match)
    prompts = take(service, table, match, source=DARK)
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:placement_menu.square"]
    square = prompts[0]["choice"]["options"][0]["id"]
    engine = recovered(service, match, tmp_path)
    zone = zones.typed_zones(engine)[0]
    assert square == f"cell:{zone.center.x},{zone.center.y},{zone.center.z}"
    assert engine.state.actors[OWNER].concentration is not None
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == qi


def next_owner_turn(service, table, match):
    take(service, table, match)
    owner_turn(service, table, match)


def test_court_of_resonant_measure_expires_through_table_commit_and_reload(tmp_path):
    service, table, match = setup(tmp_path, "H57-court", [MUSIC, FORCE])
    owner_turn(service, table, match)
    start_round = service._load_session(match).engine.state.round_number
    take(service, table, match, source=MUSIC)
    source = service._load_session(match).engine.state.actors[OWNER].concentration.source_definition_id
    for _ in range(300):
        engine = service._load_session(match).engine
        if engine.state.current_actor_id == OWNER and engine.state.round_number >= start_round + 10:
            break
        take(service, table, match)
    else:
        raise AssertionError("one-minute expiry edge not reached")
    engine = recovered(service, match, tmp_path)
    assert not concentration.concentrating_on(engine.state.actors[OWNER], source)
    assert not [zone for zone in zones.typed_zones(engine) if zone.source_definition_id == source]


@pytest.mark.parametrize("held", [False, True])
def test_persistent_darkness_converts_existing_zone_and_keeps_deadline(tmp_path, held):
    service, table, match = setup(tmp_path, "H57-persistent", [DARK, FORCE])
    owner_turn(service, table, match)
    take(service, table, match, source=DARK)
    if held:
        take(service, table, match, source=FORCE)
    engine = service._load_session(match).engine
    zone = zones.typed_zones(engine)[0]
    zone_id = zone.zone_id
    started = engine.state.round_number
    qi_before = engine.state.actors[OWNER].resources["resource:core.qi"]
    state = table.state(match)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == "Make existing Darkness Persistent")
    action = engine.action_catalog[group["source_definition_id"]]
    assert "2 cultivation points" in action.parameters["description"]
    result = table.act(match, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    engine = recovered(service, match, tmp_path)
    zone = engine.state.zones[zone_id]
    assert zone.active
    # Check the actual table projection after the committed action and a fresh
    # service reload, including both the map area's detail and actor pill.
    reloaded = CombatService(APP, tmp_path)
    presentation = TabletopService(reloaded, tmp_path).state(match)["presentation"]
    zone_row = next(row for row in presentation["zones"] if row.get("zone_id") == zone_id)
    assert "10 rounds" in zone_row["duration"]
    assert "without Concentration" in zone_row["detail"]
    pill = next(row for actor_row in presentation["actors"] for row in actor_row["conditions"]
                if row.get("condition_id") == PERSISTENT_AREA)
    assert "10 rounds" in pill["duration"]
    assert "without Concentration" in pill["detail"]
    from tests.test_status_text import _rows
    described = [row for row in _rows(TabletopService(reloaded, tmp_path), reloaded, match)
                 if row.get("condition_id") == PERSISTENT_AREA]
    assert len(described) >= 2  # live pill plus historical event with no stored data
    assert all("without Concentration" in row["rule_text"] and "10 rounds" in row["duration"]
               for row in described)
    if held:
        assert engine.state.actors[OWNER].concentration is not None
        assert engine.action_catalog[engine.state.actors[OWNER].concentration.source_definition_id].parameters["typed"]["source"] == FORCE
        assert not concentration.held(engine.state.actors[OWNER])
    else:
        assert engine.state.actors[OWNER].concentration is None
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == qi_before - 2
    marker = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PERSISTENT_AREA)
    assert marker.data["expires_round"] == started + 10
    for _ in range(500):
        engine = service._load_session(match).engine
        if engine.state.current_actor_id == OWNER and engine.state.round_number >= started + 10:
            break
        take(service, table, match)
    else:
        raise AssertionError("persistent area's original expiry edge not reached")
    engine = recovered(service, match, tmp_path)
    assert not engine.state.zones[zone_id].active
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PERSISTENT_AREA]


def test_aegis_creator_can_end_selected_aegis_for_free_after_spending_action(tmp_path):
    talents = ["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS", FORCE]
    service, table, match = setup(tmp_path, "H57-aegis", talents)
    owner_turn(service, table, match)
    state = table.state(match)
    menu = state["menu"]
    cast = next(group for group in menu["actions"] if group["label"] == "Aegis: Armored Aegis")
    target = next(option for option in cast["options"] if OWNER in option["target_ids"])
    result = table.act(match, target["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    engine = recovered(service, match, tmp_path)
    actor = engine.state.actors[OWNER]
    assert actor.concentration is not None
    assert not actor.action_available
    select(table, match, "End an Aegis you made", OWNER)
    actor = recovered(service, match, tmp_path).state.actors[OWNER]
    assert not any(c.source_actor_id == OWNER and (c.data or {}).get("aegis_talent") for c in actor.conditions.values())
    assert actor.concentration is None
    assert not actor.action_available


@pytest.mark.parametrize("other_aegis", [None, "Armored Aegis", "Shielded"])
def test_aegis_dismisses_selected_ally_copy_without_ending_other_copies(tmp_path, other_aegis):
    service, table, match = setup(tmp_path, "H57-ally", ["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS", "tianxia.talent.protection.shielded", FORCE])
    ally = "actor:factory.57570002"
    owner_turn(service, table, match)
    select(table, match, "Aegis: Armored Aegis", ally)
    engine = recovered(service, match, tmp_path)
    ally_copy = engine.state.actors[OWNER].concentration.started_sequence
    if other_aegis:
        next_owner_turn(service, table, match)
        select(table, match, "Aegis: " + other_aegis, OWNER)
        take(service, table, match, source=FORCE)
    qi_before = service._load_session(match).engine.state.actors[OWNER].resources["resource:core.qi"]
    select(table, match, "End an Aegis you made", ally)
    engine = recovered(service, match, tmp_path)
    actor = engine.state.actors[OWNER]
    assert not any((c.data or {}).get("aegis_talent") for c in engine.state.actors[ally].conditions.values())
    assert actor.resources["resource:core.qi"] == qi_before
    assert not actor.action_available
    assert all(c.started_sequence != ally_copy for _iid, c in concentration.held(actor))
    if not other_aegis:
        assert actor.concentration is None
        return
    assert actor.concentration is not None
    assert engine.action_catalog[actor.concentration.source_definition_id].parameters["typed"]["source"] == FORCE
    assert any((c.data or {}).get("aegis_talent") for c in actor.conditions.values())
    assert len(concentration.held(actor)) == 1
    force_round = engine.state.round_number
    # Force Mantle's natural expiry ends the current copy and resumes only the
    # caster's Aegis. The dismissed ally copy must never resume afterward.
    for _ in range(12):
        if service._load_session(match).engine.state.round_number >= force_round + 10:
            break
        next_owner_turn(service, table, match)
    engine = recovered(service, match, tmp_path)
    actor = engine.state.actors[OWNER]
    assert actor.concentration is not None
    assert actor.concentration.started_sequence != ally_copy
    assert not concentration.held(actor)
    select(table, match, "End an Aegis you made", OWNER)
    actor = recovered(service, match, tmp_path).state.actors[OWNER]
    assert actor.concentration is None
    assert not concentration.held(actor)


@pytest.mark.parametrize("qi", [1, 30])
def test_darkness_future_setting_is_free_and_conversion_is_affordable(tmp_path, qi):
    service, table, match = setup(tmp_path, "H57-free-setting", [DARK], qi=qi)
    owner_turn(service, table, match)
    take(service, table, match, source=DARK)
    engine = recovered(service, match, tmp_path)
    before = engine.state.actors[OWNER].concentration.model_dump(mode="json")
    resource = engine.state.actors[OWNER].resources["resource:core.qi"]
    select(table, match, "Augment Darkness: Persistent Darkness")
    engine = recovered(service, match, tmp_path)
    actor = engine.state.actors[OWNER]
    assert actor.resources["resource:core.qi"] == resource
    assert actor.concentration.model_dump(mode="json") == before
    assert not any(c.condition_id == PERSISTENT_AREA for c in actor.conditions.values())
    offered = {g["label"] for g in table.state(match)["menu"]["actions"]}
    assert ("Make existing Darkness Persistent" in offered) == (resource >= 2)
    if resource >= 2:
        select(table, match, "Make existing Darkness Persistent")
        actor = recovered(service, match, tmp_path).state.actors[OWNER]
        assert actor.resources["resource:core.qi"] == resource - 2
        assert actor.concentration is None
        assert any(c.condition_id == PERSISTENT_AREA for c in actor.conditions.values())
        next_owner_turn(service, table, match)
        assert "Make existing Darkness Persistent" not in {g["label"] for g in table.state(match)["menu"]["actions"]}
        take(service, table, match, source=DARK, augmented=True)
        engine = recovered(service, match, tmp_path)
        actor = engine.state.actors[OWNER]
        assert actor.resources["resource:core.qi"] == resource - 4
        assert actor.concentration is None
        assert len(zones.typed_zones(engine)) == 2
