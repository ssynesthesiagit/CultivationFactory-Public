"""Court's temporary Unarmed Strike reach applies to ordinary Attack choices."""

import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_lane2 as fist
from combat.gate4_adapters import ManualControllerAdapter
from tests.test_lock_choices import install
from tests.test_c17_bitter_final import OWNER, FOE
from tests.test_lock2_persistence import act

ROOT = fist.ROOT
REACH_ACTION = fist.STRIKE + " (extended reach)"
BRIAR = "tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation"


def _fight(tmp_path, control, *, foe_x=5, calamity=False):
    for project, owned in (("aaaaaaaa", True), ("bbbbbbbb", False)):
        sheet = fist.A._sheet(fist.IRON_FIST if owned else None, [fist.COURT] if owned else [], [], cl=12)
        if owned and calamity:
            sheet["identity"]["cultivation_level"] = 18
            sheet["spheres_and_talents"].setdefault("learned_talent_record_ids", []).append(BRIAR)
        sheet["identity"]["display_name"] = "Court user" if owned else "Practice rival"
        sheet["ability_scores_and_statistics"]["hit_points"] = {"maximum": 400}
        archive = tmp_path / "portable_characters" / project / "current.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Court yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[foe_x, 4]]}})
    match_id = service.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: control, FOE: "MANUAL"}, arena_id="battlefield:map.court-yard",
        match_seed="C17-COURT-REACH")["match_id"]
    return service, TabletopService(service, tmp_path), match_id


def _act(table, service, match_id, actor_id, name, control):
    target = FOE if actor_id == OWNER and name not in {"Court of One Hundred Forms", "Calamity Briar Incarnation"} else None
    if control == "LOCAL_AUTO":
        service.set_controller_mode(match_id, actor_id=actor_id, controller_mode="LOCAL_AUTO")
        engine = service._load_session(match_id).engine
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.actor_id == actor_id
                   and c.display_name == name and (target is None or c.target_ids == (target,)))
        real = service.controller
        class FixedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
            def __getattr__(self, key):
                return getattr(real, key)
        service.controller = FixedController()
        return table.auto_step(match_id, table.state(match_id)["last_sequence"])
    menu = table.state(match_id)["menu"]
    cid = next(option["candidate_id"] for group in menu["actions"] if name in group["label"]
               for option in group["options"] if target is None or target in option.get("target_ids", []))
    return table.act(match_id, cid, menu["decision_id"], menu["state_version"], table.state(match_id)["last_sequence"])


def _end_turn(table, match_id):
    menu = table.state(match_id)["menu"]
    result = table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"],
                       table.state(match_id)["last_sequence"])
    assert result["status"] == "COMMITTED", result


def _take_owner_turn(table, match_id):
    while table.state(match_id)["menu"]["actor_id"] != OWNER:
        _end_turn(table, match_id)


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
def test_court_reach_attack_action_is_owned_temporary_and_replays(monkeypatch, tmp_path, control):
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:hit", "operation": "replace", "natural_result": 20})
    service, table, match_id = _fight(tmp_path, control)
    engine = service._load_session(match_id).engine
    from combat import typed_reactions
    # The compiled variant exists for this owner, but is not offered before activation.
    assert any(a.owner_id == OWNER and a.display_name == REACH_ACTION for a in engine.action_catalog.values())
    assert not any(a.owner_id == FOE and a.display_name == REACH_ACTION for a in engine.action_catalog.values())
    base_oa_reach = typed_reactions.opportunity_reach(engine, engine.state.actors[OWNER])
    assert base_oa_reach == 5
    initial = service._load_session(match_id)
    assert initial.verify()["status"] == initial.mechanical.replay()["status"] == "PASS"
    while table.state(match_id)["menu"]["actor_id"] != OWNER:
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    engine = service._load_session(match_id).engine
    assert not any(c.display_name == REACH_ACTION and FOE in c.target_ids for c in engine.legal_candidates())

    assert _act(table, service, match_id, OWNER, "Court of One Hundred Forms", control)["status"] == "COMMITTED"
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    engine = service._load_session(match_id).engine
    assert any(c.display_name == REACH_ACTION and FOE in c.target_ids for c in engine.legal_candidates())
    owner = engine.state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.state.court_one_hundred_forms"
               for c in owner.conditions.values())
    # The selected OA variant already represents the Court's reach increase.
    # The profile remains 10 feet, rather than adding the Court's 5 feet twice.
    assert typed_reactions.opportunity_reach(engine, owner) == 10
    sequence = engine.state.event_sequence

    result = _act(table, service, match_id, OWNER, REACH_ACTION, control)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    events = [event for event in loaded.engine.events if event.sequence > sequence]
    assert any(event.event_type == "ATTACK_ROLLED" and event.actor_id == OWNER and FOE in event.target_ids
               for event in events)
    assert loaded.engine.grid.distance_ft(loaded.engine.state.actors[OWNER].position,
        loaded.engine.state.actors[FOE].position) == 10
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert canonical_sha256(loaded.engine.state.model_dump(mode="json")) == canonical_sha256(
        service._load_session(match_id).engine.state.model_dump(mode="json"))
    # Let the one-minute Court expire through committed table turns.
    court_state = "condition:typed.state.court_one_hundred_forms"
    for actor_id in (OWNER, FOE):
        service.set_controller_mode(match_id, actor_id=actor_id, controller_mode="MANUAL")
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    loaded = service._load_session(match_id)
    while any(c.condition_id == court_state for c in loaded.engine.state.actors[OWNER].conditions.values()):
        state = table.state(match_id)
        result = table.act(match_id, state["menu"]["end_turn"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED", result
        loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    owner = loaded.engine.state.actors[OWNER]
    assert typed_reactions.opportunity_reach(loaded.engine, owner) == 5
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
def test_court_reach_triggers_opportunity_attack_from_table_move(monkeypatch, tmp_path, control):
    """The Court's extra reach applies to the native OA as well as its strike menu."""
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:hit", "operation": "replace", "natural_result": 20})
    service, table, match_id = _fight(tmp_path, "MANUAL")

    # Activate Court on the owner's turn, then give the opponent its normal turn.
    while table.state(match_id)["menu"]["actor_id"] != OWNER:
        state = table.state(match_id)
        assert table.act(match_id, state["menu"]["end_turn"], state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    assert _act(table, service, match_id, OWNER, "Court of One Hundred Forms", "MANUAL")["status"] == "COMMITTED"
    state = table.state(match_id)
    assert table.act(match_id, state["menu"]["end_turn"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    service.set_controller_mode(match_id, actor_id=OWNER, controller_mode=control)

    state = table.state(match_id)
    assert state["menu"]["actor_id"] == FOE
    engine = service._load_session(match_id).engine
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    assert engine.grid.distance_ft(owner.position, foe.position) == 10
    sequence = engine.state.event_sequence
    # The compiled base already has 5-foot reach; Court raises it once to 10.
    # The first 5-foot step leaves that reach and must trigger the OA.
    move = next(row for row in state["menu"]["moves"]
                if row["destination"] == {"x": foe.position.x + 1, "y": foe.position.y})
    result = table.act(match_id, move["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    events = [event for event in loaded.engine.events if event.sequence > sequence]
    assert any(event.event_type == "ATTACK_ROLLED" and event.actor_id == OWNER and FOE in event.target_ids
               for event in events)
    assert any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == FOE for event in events)
    assert not loaded.engine.state.actors[OWNER].reaction_available
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_court_and_calamity_briar_combine_for_20_foot_ordinary_attack(monkeypatch, tmp_path):
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:hit", "operation": "replace", "natural_result": 20})
    service, table, match_id = _fight(tmp_path, "MANUAL", foe_x=7, calamity=True)
    _take_owner_turn(table, match_id)
    assert _act(table, service, match_id, OWNER, "Calamity Briar Incarnation", "MANUAL")["status"] == "COMMITTED"
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    _end_turn(table, match_id)
    _take_owner_turn(table, match_id)
    assert _act(table, service, match_id, OWNER, "Court of One Hundred Forms", "MANUAL")["status"] == "COMMITTED"
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    engine = service._load_session(match_id).engine
    assert engine.grid.distance_ft(engine.state.actors[OWNER].position, engine.state.actors[FOE].position) == 20
    assert any(c.display_name == REACH_ACTION and FOE in c.target_ids for c in engine.legal_candidates())
    sequence = engine.state.event_sequence
    result = _act(table, service, match_id, OWNER, REACH_ACTION, "MANUAL")
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER and FOE in e.target_ids
               for e in loaded.engine.events if e.sequence > sequence)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_ordinary_attack_returns_to_5_feet_after_court_and_briar_expire(monkeypatch, tmp_path):
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:hit", "operation": "replace", "natural_result": 20})
    service, table, match_id = _fight(tmp_path, "MANUAL", foe_x=4, calamity=True)
    _take_owner_turn(table, match_id)
    assert _act(table, service, match_id, OWNER, "Calamity Briar Incarnation", "MANUAL")["status"] == "COMMITTED"
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    _end_turn(table, match_id)
    _take_owner_turn(table, match_id)
    assert _act(table, service, match_id, OWNER, "Court of One Hundred Forms", "MANUAL")["status"] == "COMMITTED"
    for actor_id in (OWNER, FOE):
        service.set_controller_mode(match_id, actor_id=actor_id, controller_mode="MANUAL")
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    loaded = service._load_session(match_id)
    states = {"condition:typed.state.court_one_hundred_forms", "condition:typed.state.calamity_briar_incarnation"}
    while any(c.condition_id in states for c in loaded.engine.state.actors[OWNER].conditions.values()):
        _end_turn(table, match_id)
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        loaded = service._load_session(match_id)
    assert loaded.engine.grid.distance_ft(loaded.engine.state.actors[OWNER].position,
                                          loaded.engine.state.actors[FOE].position) == 5
    assert not any(c.display_name == REACH_ACTION and FOE in c.target_ids for c in loaded.engine.legal_candidates())
    sequence = loaded.engine.state.event_sequence
    base_action = next(c for c in loaded.engine.legal_candidates()
                       if c.display_name == fist.STRIKE and FOE in c.target_ids)
    menu = table.state(match_id)["menu"]
    result = table.act(match_id, base_action.candidate_id, menu["decision_id"], menu["state_version"],
                       table.state(match_id)["last_sequence"])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER and FOE in e.target_ids
               for e in loaded.engine.events if e.sequence > sequence)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
