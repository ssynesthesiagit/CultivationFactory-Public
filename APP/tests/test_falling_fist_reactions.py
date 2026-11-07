"""Table-level regressions for Falling Fist posture reactions and target choice."""
import json
import zipfile

import pytest

from combat import factory_compiler
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act
from tests.test_riders_c7 import ROOT, DRUNK, sheet

FIST = DRUNK + "falling_fist"
PLAYER_PROJECT = "61616161"
FOE_PROJECT = "61616162"
ME = FACTORY_ACTOR_PREFIX + PLAYER_PROJECT
FOE = FACTORY_ACTOR_PREFIX + FOE_PROJECT
SECOND_PROJECT = "61616163"
SECOND = FACTORY_ACTOR_PREFIX + SECOND_PROJECT
STOMP = "tianxia.path.body_refining.feature.stomping_step"
FALL = "Stomping Step + Swaying Step: Fall Prone and Move"


def test_optional_target_metadata_preserves_complete_owner_text_reviews():
    from tools.typed_mechanics_helpers import load_finals, _typed_for_text
    finals = load_finals()
    key = "ASH_BASE_CINDER_BRAND"
    assert _typed_for_text(key, finals[key]["text_sha256"], finals)


def setup(tmp_path, *, near=True, ward=False, two_targets=False, trip=False, denial=False):
    for project in (PLAYER_PROJECT, FOE_PROJECT, *([SECOND_PROJECT] if two_targets else [])):
        content = sheet([DRUNK + "swaying_step", STOMP, FIST] if project == PLAYER_PROJECT else [],
                        name="Posture student" if project == PLAYER_PROJECT else "Training enemy")
        if denial and project == FOE_PROJECT:
            content["spheres_and_talents"]["learned_talent_record_ids"] = ["SOL61_DENY"]
        if ward and project == PLAYER_PROJECT:
            content["spheres_and_talents"]["learned_talent_record_ids"] = ["SOL61_WARD"]
        if trip and project == FOE_PROJECT:
            content["spheres_and_talents"]["learned_talent_record_ids"] = ["SOL61_TRIP"]
        archive = tmp_path / "portable_characters" / project / "current.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(content))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PLAYER_PROJECT, {"mode": "ask"}, {FIST})
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "SOL61 yard", "width_squares": 20, "height_squares": 10,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4 if near else 18, 4], *([[3, 5]] if two_targets else [])]}})
    opponents = [FOE, *([SECOND] if two_targets else [])]
    view = service.create_factory_match(project_ids=[PLAYER_PROJECT], opponent_actor_ids=opponents,
        control_modes={a: "MANUAL" for a in [ME, *opponents]}, arena_id="battlefield:map.sol61-yard", match_seed="SOL61")
    mid, table = view["match_id"], TabletopService(service, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return service, table, mid


def fall(table, mid, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    if not menu["manual"]:
        return table.auto_step(mid, state["last_sequence"], list(answers))
    group = next(g for g in menu["actions"] if g["label"] == FALL)
    def submit(choices):
        return table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], choices)
    prior = ((state.get('pending_action') or {}).get('reactions') or [])
    choices = list(answers)
    if choices[:len(prior)] != prior:
        choices = [*prior, *choices]  # Reopen keeps earlier player answers bound to this action.
    result = submit(choices)
    if (result['status'] == 'REACTION_REQUIRED'
            and result['reaction']['context']['reaction_source_id'] == 'choice:needle.dash_or_disengage'):
        # H53 adds this earlier player-owned choice. Answer it explicitly so
        # these assertions still exercise Falling Fist's own posture window.
        prompt = result['reaction']
        assert {option['id'] for option in prompt['choice']['options']} == {'dash', 'disengage'}
        dash = {**prompt['context'], 'selection': 'USE', 'option_ids': ['dash']}
        result = submit([*prior, dash, *answers])
    return result


def make_auto(service, table, mid, *, actor=ME, label=FALL):
    from combat.gate4_adapters import ManualControllerAdapter
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    cid = group["options"][0]["candidate_id"]
    normal = service.controller

    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(normal, name)

    service.controller = Controller()
    service.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")


def assert_order_and_reload(service, tmp_path, mid, *, target=FOE):
    events = service._load_session(mid).engine.events
    prone = next(e for e in events if e.event_type == "CONDITION_APPLIED" and ME in e.target_ids
                 and e.payload["condition_id"] == "condition:typed.prone")
    strike = next(e for e in events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == FIST)
    assert prone.sequence < strike.sequence
    assert strike.actor_id == ME and strike.target_ids == (target,)
    assert any(e.source_definition_id == FIST and e.event_type == "REACTION_RESOLVED"
               and e.payload["checkpoint"] == "CONDITION_APPLIED" for e in events)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert any(c.condition_id == "condition:typed.prone" for c in loaded.engine.state.actors[ME].conditions.values())
    assert canonical_state_sha256(loaded.engine.state) == canonical_state_sha256(service._load_session(mid).engine.state)


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_ask_me_selects_enemy_after_prone_and_rolls_back_preview(tmp_path, selection):
    service, table, mid = setup(tmp_path)
    before = canonical_state_sha256(service._load_session(mid).engine.state)
    first = fall(table, mid)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["reaction"] == "Falling Fist"
    assert [o["id"] for o in prompt["choice"]["options"]] == [FOE]
    assert "Swaying Step" in json.dumps(prompt) and "Prone" in json.dumps(prompt)
    assert canonical_state_sha256(service._load_session(mid).engine.state) == before
    answer = {**prompt["context"], "selection": selection, "option_ids": [FOE] if selection == "USE" else []}
    assert fall(table, mid, [answer])["status"] == "COMMITTED"
    if selection == "USE":
        assert_order_and_reload(service, tmp_path, mid)
    else:
        engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
        assert engine.state.actors[ME].reaction_available
        assert not any(e.source_definition_id == FIST and e.event_type == "ATTACK_ROLLED" for e in engine.events)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_no_creature_in_reach_means_no_offer_or_spending(tmp_path, mode):
    service, table, mid = setup(tmp_path, near=False)
    # Submit the real table candidate with the actor's normal controller mode.
    if mode != "MANUAL":
        make_auto(service, table, mid)
    assert fall(table, mid)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].reaction_available
    assert not any(e.source_definition_id == FIST and e.event_type in ("REACTION_WINDOW_OPENED", "ATTACK_ROLLED")
                   for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"


def test_ai_controller_selects_legal_enemy_after_prone(tmp_path):
    service, table, mid = setup(tmp_path)
    make_auto(service, table, mid)
    assert fall(table, mid)["status"] == "COMMITTED"
    assert_order_and_reload(service, tmp_path, mid)


def test_player_can_choose_between_two_legal_creatures(tmp_path):
    service, table, mid = setup(tmp_path, two_targets=True)
    first = fall(table, mid)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {FOE, SECOND}
    answer = {**prompt["context"], "selection": "USE", "option_ids": [SECOND]}
    assert fall(table, mid, [answer])["status"] == "COMMITTED"
    assert_order_and_reload(service, tmp_path, mid, target=SECOND)


def test_player_is_asked_on_enemy_ai_turn(monkeypatch, tmp_path):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())
    authority["mechanics"]["SOL61_TRIP"] = {
        "mechanic_id": "SOL61_TRIP", "name": "Practice knockdown", "kind": "talent", "sphere_id": None,
        "activation": {"economy": "action"}, "effects": [{"type": "condition", "condition": "prone", "applies_to": "target"}],
        "cost": [], "riders": [], "range": {"kind": "feet", "distance_ft": 5}, "duration": {"kind": "instant"}}
    path = tmp_path / "test-authority.json"
    path.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    service, table, mid = setup(tmp_path, trip=True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == FOE
    make_auto(service, table, mid, actor=FOE, label="Practice knockdown")
    state = table.state(mid)
    first = table.auto_step(mid, state["last_sequence"])
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["context"]["reactor_id"] == ME
    assert "Practice knockdown" in json.dumps(first["reaction"])
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": [FOE]}
    assert table.auto_step(mid, state["last_sequence"], [answer])["status"] == "COMMITTED"
    assert_order_and_reload(service, tmp_path, mid)


def test_condition_prevention_stays_before_application(monkeypatch, tmp_path):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())
    authority["mechanics"]["SOL61_WARD"] = {
        "mechanic_id": "SOL61_WARD", "name": "Posture Ward", "kind": "talent", "sphere_id": None,
        "activation": {"economy": "reaction", "trigger": "You would gain the prone condition"},
        "effects": [{"type": "prevent_condition"}], "cost": [], "riders": [], "range": None,
        "duration": {"kind": "instant"}, "after": "condition_applied"}
    path = tmp_path / "test-authority.json"
    path.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    service, table, mid = setup(tmp_path, ward=True)
    first = fall(table, mid)
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["reaction"] == "Posture Ward"
    assert "CONDITION_ABOUT_TO_APPLY" in first["reaction"]["context"]["checkpoint"]
    answer = {**first["reaction"]["context"], "selection": "USE"}
    assert fall(table, mid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == "condition:typed.prone" for c in loaded.engine.state.actors[ME].conditions.values())
    assert not any(e.source_definition_id == FIST and e.event_type == "ATTACK_ROLLED" for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"


def _install_target_prohibition(monkeypatch, service, source, blocked):
    if source == "hook":
        from combat import ext

        def deny_selected_target(engine, reactor, other):
            return False if other is not None and other.entity_id == blocked else None
        monkeypatch.setitem(ext._HOOKS, "reaction_allowed", [*ext._HOOKS.get("reaction_allowed", []), deny_selected_target])


@pytest.mark.parametrize("source", ["unmaking", "hook"])
@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("alternative", [False, True])
def test_prohibited_reaction_target_is_never_offered_or_used(monkeypatch, tmp_path, source, mode, alternative):
    if source == "unmaking":
        authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())
        authority["mechanics"]["SOL61_DENY"] = {
            "mechanic_id": "SOL61_DENY", "name": "Practice Denial", "kind": "talent", "sphere_id": None,
            "activation": {"economy": "action"},
            "effects": [{"type": "reaction_denied", "evidence": "cannot take Reactions against you",
                         "applies_to": "target"}],
            "cost": [], "riders": [], "range": {"kind": "feet", "distance_ft": 5},
            "duration": {"kind": "instant"}}
        path = tmp_path / "test-authority.json"
        path.write_text(json.dumps(authority))
        monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    service, table, mid = setup(tmp_path, two_targets=alternative, denial=source == "unmaking")
    blocked = FOE
    allowed = SECOND if alternative else None
    _install_target_prohibition(monkeypatch, service, source, blocked)
    if source == "unmaking":
        while table.state(mid)["menu"]["actor_id"] != FOE:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        denial_menu = table.state(mid)["menu"]
        assert denial_menu["actor_id"] == FOE
        denial_group = next(g for g in denial_menu["actions"] if g["label"] == "Practice Denial")
        denial_state = table.state(mid)
        assert table.act(mid, denial_group["options"][0]["candidate_id"], denial_menu["decision_id"],
                         denial_menu["state_version"], denial_state["last_sequence"])["status"] == "COMMITTED"
        while table.state(mid)["menu"]["actor_id"] != ME:
            assert act(table, mid, "end")["status"] == "COMMITTED"
    if mode == "LOCAL_AUTO":
        make_auto(service, table, mid)

    first = fall(table, mid)
    if allowed is None:
        assert first["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.actors[ME].reaction_available
        assert not any(e.source_definition_id == FIST and e.event_type in ("REACTION_WINDOW_OPENED", "ATTACK_ROLLED")
                       for e in loaded.engine.events)
    elif mode == "MANUAL":
        assert first["status"] == "REACTION_REQUIRED"
        assert [o["id"] for o in first["reaction"]["choice"]["options"]] == [allowed]
        answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": [allowed]}
        assert fall(table, mid, [answer])["status"] == "COMMITTED"
        assert_order_and_reload(service, tmp_path, mid, target=allowed)
    else:
        assert first["status"] == "COMMITTED"
        assert_order_and_reload(service, tmp_path, mid, target=allowed)
