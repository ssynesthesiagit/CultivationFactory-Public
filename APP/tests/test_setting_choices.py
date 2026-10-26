"""Setting buttons commit and reload without becoming combat triggers (P5)."""

import copy
import json
import zipfile
from pathlib import Path

import pytest

from combat import typed_executor, zones
from combat.ext.setting_choices import is_setting_action
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import ButtonStore, auto_buttons
from combat.tabletop_service import TabletopService
from tests.test_darkness_and_stealth import _sheet
from tests.test_tabletop import MAP

ROOT = Path(__file__).resolve().parents[1]
PLAYER, ENEMY = "00000000-0000-0000-0000-000000000005", "00000000-0000-0000-0000-000000000006"
PID, EID = FACTORY_ACTOR_PREFIX + PLAYER, FACTORY_ACTOR_PREFIX + ENEMY
SMOTHER = "TAL_SMOKE_SMOTHER_THE_BREATH"
HIDDEN = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"


def _install(userdata, project, sheet):
    folder = userdata / "portable_characters" / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def _table(tmp_path, ask, mounted=False, flowing=False):
    player = copy.deepcopy(_sheet())
    player["spheres_and_talents"]["learned_talent_record_ids"] += ["TAL_DARK_DIRECTIONAL_DARKNESS", HIDDEN]
    if flowing:
        player["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.flowing_river")
        player["spheres_and_talents"]["learned_talent_record_ids"] += [
            "TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_HAND_ON_THE_WRIST",
            "TAL_FLOWING_RIVER_EMPTY_STEP", "TAL_FLOWING_RIVER_TWO_CURRENTS_MEET"]
    if mounted:
        player["spheres_and_talents"]["sphere_record_ids"] += ["tianxia.sphere.beastmastery", "tianxia.sphere.barrage"]
        player["spheres_and_talents"]["automatic_sphere_component_record_ids"] = ["BEASTMASTERY_BASE_RIDER_PACKAGE"]
        player["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_BARRAGE_COURT_OF_FALLING_STARS")
    enemy = copy.deepcopy(player)
    enemy["ability_scores_and_statistics"]["technique_attack_bonus"] = 50
    enemy["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.smoke"],
                                   "learned_talent_record_ids": ["SMOKE_BASE_SMOKE_TRACE", "SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_CINDER_WISP", SMOTHER]}
    for project, sheet in ((PLAYER, player), (ENEMY, enemy)):
        _install(tmp_path, project, sheet)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(ENEMY, {"mode": "ask" if ask else "auto"}, {SMOTHER})
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({**MAP, "walls": [], "starts": {"team1": [[4, 4]], "team2": [[5, 4]]}})
    view = service.create_factory_match(project_ids=[PLAYER], opponent_actor_ids=[EID],
                                       control_modes={PID: "MANUAL", EID: "MANUAL"},
                                       arena_id="battlefield:map.courtyard", match_seed="P5-SETTINGS")
    return service, TabletopService(service, tmp_path), view["match_id"]


def _candidate(service, mid, name):
    engine = service._load_session(mid).engine
    ids = {a.source_definition_id for a in engine.action_catalog.values() if a.display_name == name}
    return next(c for c in service.decision(mid)["context"]["legal_candidates"] if c["source_definition_id"] in ids)


def _send(service, table, mid, candidate, reactions=()):
    context = service.decision(mid)["context"]
    after = table.state(mid)["last_sequence"]
    return table.act(mid, candidate["candidate_id"], context["decision_id"], context["state_version"], after, list(reactions))


def _end(service, table, mid):
    candidate = next(c for c in service.decision(mid)["context"]["legal_candidates"] if c["kind"] == "END_TURN")
    assert _send(service, table, mid, candidate)["status"] == "COMMITTED"


@pytest.mark.parametrize("ask", [True, False])
@pytest.mark.parametrize("first", [0, 1, 2], ids=["shape", "augment", "choice"])
def test_table_settings_do_not_trigger_but_real_cast_does(tmp_path, ask, first):
    service, table, mid = _table(tmp_path, ask)
    if service._load_session(mid).engine.state.current_actor_id != EID:
        _end(service, table, mid)
    trace = _candidate(service, mid, "Cinder Wisp")
    assert PID in trace["target_ids"]
    assert _send(service, table, mid, trace)["status"] == "COMMITTED"
    _end(service, table, mid)
    engine = service._load_session(mid).engine
    assert engine.state.current_actor_id == PID
    assert typed_executor.bears_mark(engine.state.actors[PID], EID, "Smoke Trace")

    names = ["Shape Darkness: Pure Darkness + Hungry Darkness", "Augment Darkness: Directional Darkness",
             "Hidden Strike: Misleading Impact"]
    names = names[first:] + names[:first]
    for name in names:
        before = service._load_session(mid).engine
        resources = {key: dict(a.resources) for key, a in before.state.actors.items()}
        rolls = len(before.rolls)
        result = _send(service, table, mid, _candidate(service, mid, name))
        assert result["status"] == "COMMITTED"  # Ask me never opens a prompt
        events = result["events"]["events"]
        assert {e["event_type"] for e in events} <= {"INTENT_ACCEPTED", "CONDITION_APPLIED", "CONDITION_REMOVED"}
        # Fresh service: check the actual saved commit, not an in-memory preview.
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        engine = service._load_session(mid).engine
        assert len(engine.rolls) == rolls
        assert {key: dict(a.resources) for key, a in engine.state.actors.items()} == resources
        assert engine.state.actors[EID].reaction_available
        assert engine.state.actors[PID].action_available
        assert typed_executor.bears_mark(engine.state.actors[PID], EID, "Smoke Trace")
    player = engine.state.actors[PID]
    assert any(c.condition_id == zones.SHAPING and c.data["talents"] == ["TAL_DARK_PURE_DARKNESS", "TAL_DARK_HUNGRY_DARKNESS"]
               for c in player.conditions.values())
    assert any(c.data.get("choice") == "mislead" for c in player.conditions.values())
    from combat import loadout
    family = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == "Darkness")
    assert "TAL_DARK_DIRECTIONAL_DARKNESS" in loadout.chosen(player, family)
    cast = _candidate(service, mid, "Darkness + Directional Darkness")
    result = _send(service, table, mid, cast)
    if ask:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "reaction:typed." + SMOTHER
        answer = prompt["context"]
        result = _send(service, table, mid, cast, [{**answer, "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert not engine.state.actors[EID].reaction_available
    assert not typed_executor.bears_mark(engine.state.actors[PID], EID, "Smoke Trace")
    assert any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == SMOTHER for e in engine.events)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == SMOTHER for e in engine.events)
    assert zones.typed_zones(engine)


def test_setting_classification_matches_table_choice_contract():
    sheet = _sheet()
    sheet["spheres_and_talents"]["learned_talent_record_ids"].append(HIDDEN)
    bundle = compile_character(sheet, actor_id=PID)
    choices = {b["combat"]["source_definition_id"] for b in auto_buttons(bundle, {}) if "choice" in b["tags"]}
    assert choices
    for action in bundle["action_catalog"]:
        if action["source_definition_id"] in choices or action["parameters"].get("zone_shape"):
            assert is_setting_action(action)
        elif action["display_name"] == "Darkness":
            assert not is_setting_action(action)


@pytest.mark.parametrize("ask", [True, False])
def test_flowing_response_settings_commit_without_reactions_and_reload(tmp_path, ask):
    from combat.ext.flowing_river import CHOICE, STEP

    service, table, mid = _table(tmp_path, ask, flowing=True)
    if service._load_session(mid).engine.state.current_actor_id != EID:
        _end(service, table, mid)
    assert _send(service, table, mid, _candidate(service, mid, "Cinder Wisp"))["status"] == "COMMITTED"
    _end(service, table, mid)
    engine = service._load_session(mid).engine
    choices = [a for a in engine.action_catalog.values()
               if a.owner_id == PID and a.display_name.startswith("Flowing Response:")]
    assert len(choices) == 5  # two talents, their pair, step away and hold ground
    for action in choices:
        assert is_setting_action(action)
        buttons = auto_buttons({"action_catalog": [action.model_dump(mode="json")]}, {})
        button = next(b for b in buttons if b["label"] == action.display_name)
        assert button["group"] == "reactions" and "choice" in button["tags"]
        resources = {key: dict(a.resources) for key, a in engine.state.actors.items()}
        rolls = len(engine.rolls)
        result = _send(service, table, mid, _candidate(service, mid, action.display_name))
        assert result["status"] == "COMMITTED"
        assert {e["event_type"] for e in result["events"]["events"]} <= {
            "INTENT_ACCEPTED", "CONDITION_APPLIED", "CONDITION_REMOVED"}
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        loaded = service._load_session(mid)
        engine = loaded.engine
        assert len(engine.rolls) == rolls
        assert {key: dict(a.resources) for key, a in engine.state.actors.items()} == resources
        assert engine.state.actors[EID].reaction_available
        assert engine.state.actors[PID].action_available
        assert typed_executor.bears_mark(engine.state.actors[PID], EID, "Smoke Trace")
        held = list(engine.state.actors[PID].conditions.values())
        effect = action.parameters["typed"]["effects"][0]
        if effect["type"] == "flowing_choice":
            selected = next(c for c in held if c.condition_id == CHOICE)
            assert selected.data.get("talents") == effect.get("talents")
            assert selected.data.get("talent") == effect.get("talent")
        else:
            assert any(c.condition_id == STEP for c in held) == effect["on"]
        assert loaded.mechanical.replay()["status"] == "PASS"


def test_setting_metadata_is_explicit_and_survives_serialization():
    bundle = compile_character(_sheet(), actor_id=PID)
    shapes = [a for a in bundle["action_catalog"] if a["parameters"].get("zone_shape")]
    assert shapes
    for action in shapes:
        assert action["parameters"]["setting_only"] is True
        assert is_setting_action(json.loads(json.dumps(action)))
        action["display_name"] = "Renamed without punctuation"
        assert is_setting_action(action)
        del action["parameters"]["setting_only"]
        assert not is_setting_action(action)  # old saved metadata never opts in implicitly


def test_unflagged_saved_shape_needs_explicit_free_activation():
    from combat.gate2_runtime_content import AN
    from tests.test_darkness_and_stealth import _fight, _do
    from tests.test_reaction_moments import _row
    engine = _fight(foe_at=(4, 6))
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Shape Darkness: Pure Darkness")
    del action.parameters["setting_only"]
    # NONE alone must not turn an old preference row into a combat activation.
    assert not engine._action_candidates(engine.state.actors[action.owner_id], action)
    # An explicitly declared free fixture still exercises the ordinary activity
    # hooks; removing setting metadata never silently suppresses those hooks.
    action.parameters["free_primary"] = True
    engine.typed_actor_ids = {*engine.typed_actor_ids, AN}
    engine.typed_reaction_rows[AN] = [_row("creature_acted", range_ft=60)]
    _do(engine, action.display_name)
    assert engine.state.actors[AN].temporary_hp == 3
    assert not engine.state.actors[AN].reaction_available


def test_immediate_mounted_actions_are_not_settings():
    from tests.test_mounts import rider_bundle, TALENTS
    bundle = rider_bundle([*TALENTS, "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST"])
    names = {a["display_name"]: a for a in bundle["action_catalog"]}
    for name in ("Mount: Dash", "Mount: Disengage", "Mount: Dodge",
                 "Shared Saddle Rhythm: regain Martial Focus", "Shared Saddle Rhythm: move 5 ft, no Opportunity Attacks",
                 "Shared Saddle Rhythm: mount gains Temporary HP", "One Rider, One Beast: the other moves 10 ft (Reaction)"):
        assert name in names
        assert not is_setting_action(names[name])


@pytest.mark.parametrize("name", ["Mount: Dash", "Mount: Disengage", "Mount: Dodge"])
def test_real_mount_action_still_opens_action_reaction_window(name):
    from tests.test_mounts import rider_bundle, fight, take, FOE
    from tests.test_reaction_moments import _row
    engine = fight(rider_bundle())
    engine.typed_actor_ids = {*engine.typed_actor_ids, FOE}
    engine.typed_reaction_rows[FOE] = [_row("creature_acted", range_ft=60)]
    take(engine, name)
    assert engine.state.actors[FOE].temporary_hp == 3
    assert not engine.state.actors[FOE].reaction_available
    assert any(e.event_type == "REACTION_RESOLVED" for e in engine.events)


def test_table_settings_preserve_court_window_but_mount_dash_closes_it(tmp_path):
    from combat.ext.barrage_hits import COURT_REMAINING
    service, table, mid = _table(tmp_path, False, mounted=True)
    if service._load_session(mid).engine.state.current_actor_id != PID:
        _end(service, table, mid)
    assert _send(service, table, mid, _candidate(service, mid, "Court of Falling Stars"))["status"] == "COMMITTED"
    remaining = service._load_session(mid).engine.state.actors[PID].turn_flags[COURT_REMAINING]
    assert remaining > 0
    for name in ("Shape Darkness: Pure Darkness + Hungry Darkness", "Augment Darkness: Directional Darkness",
                 "Hidden Strike: Misleading Impact"):
        assert _send(service, table, mid, _candidate(service, mid, name))["status"] == "COMMITTED"
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        assert service._load_session(mid).engine.state.actors[PID].turn_flags[COURT_REMAINING] == remaining
    result = _send(service, table, mid, _candidate(service, mid, "Mount: Dash"))
    assert result["status"] == "COMMITTED"
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[PID]
    assert COURT_REMAINING not in actor.turn_flags
    assert actor.turn_flags["dash_used"]


def test_settings_skip_action_triggers_and_activity_hooks(monkeypatch):
    from combat import ext
    from combat.gate2_runtime_content import AN
    from tests.test_darkness_and_stealth import ME, _fight, _do
    from tests.test_reaction_moments import _row

    engine = _fight(foe_at=(4, 6))
    engine.typed_actor_ids = {*engine.typed_actor_ids, AN}
    engine.typed_reaction_rows[AN] = [_row("creature_acted", range_ft=60)]
    ext._load()
    calls = []
    for point in ("technique_start", "technique_used", "action_completed"):
        def observe(*args, _point=point):
            calls.append(_point)
        monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), observe])

    def intent_observer(engine, kind, kwargs):
        if kind == "INTENT_ACCEPTED":
            calls.append(kind)
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), intent_observer])
    _do(engine, "Shape Darkness: Pure Darkness")
    assert calls == []
    assert engine.state.actors[AN].temporary_hp == 0
    assert engine.state.actors[AN].reaction_available
    _do(engine, "Darkness", at=(7, 6))
    assert set(calls) == {"INTENT_ACCEPTED", "technique_start", "technique_used", "action_completed"}
    assert engine.state.actors[AN].temporary_hp == 3
    assert not engine.state.actors[AN].reaction_available
    assert engine.state.actors[ME].action_available is False
