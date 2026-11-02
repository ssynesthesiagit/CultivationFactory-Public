"""A saved Ask-me pause can be recovered from a newly constructed table service."""
import json
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from combat.tabletop import TabletopError
from tests.test_hunt5_player_choices import fixture, FOE


def test_state_recovers_pending_request_and_answer_commits_replays(tmp_path):
    data = tmp_path / "actual"
    _service, table, match_id, character_id, _send = fixture(data, "TAL_FENCING_FOOTWORK")
    initial = table.state(match_id)
    menu = initial["menu"]
    args = (match_id, character_id, menu["decision_id"], menu["state_version"], initial["last_sequence"], [])
    response = table.act(*args)
    assert response["status"] == "REACTION_REQUIRED"

    reopened = TabletopService(CombatService(ROOT, data), data)
    pending = reopened.state(match_id)["pending_action"]
    assert pending["request"] == dict(candidate_id=character_id, decision_id=menu["decision_id"],
                                       state_version=menu["state_version"], after=initial["last_sequence"])
    assert pending["reaction"] == response["reaction"]
    assert pending["reactions"] == []

    prompt = pending["reaction"]
    stay = next(option["id"] for option in prompt["choice"]["options"] if "Stay put" in option["label"])
    answer = {**prompt["context"], "selection": "USE", "option_ids": [stay]}
    committed = reopened.act(*args[:-1], [answer])
    assert committed["status"] == "COMMITTED"
    assert committed["state"]["pending_action"] is None
    session = reopened.combat._load_session(match_id)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def reopen(table, data):
    combat = CombatService(ROOT, data)
    # Keep the fixture's deterministic AI policy; all transport/session state is new.
    combat.controller = table.combat.controller
    return TabletopService(combat, data)


def test_reopened_pending_choice_follows_defender_control_change(tmp_path):
    from tests.test_hunt5_player_choices import PLAYER
    combat, table, mid, cid, send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    paused = send(cid)
    assert paused["status"] == "REACTION_REQUIRED"
    pending = table.state(mid)["pending_action"]
    assert pending["reaction"]["context"]["reactor_id"] == PLAYER
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    table = reopen(table, tmp_path)
    result = resume(table, mid, pending, [])
    assert result["status"] == "COMMITTED"
    assert result["state"]["pending_action"] is None
    session = table.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def resume(table, mid, pending, answers):
    return getattr(table, pending["method"])(mid, **pending["request"], reactions=answers)


def commit_count(table, mid):
    return sum(json.loads(line).get("record_type") == "COMMIT"
               for line in (table._match_dir(mid) / "Journal.ndjson").read_text().splitlines() if line.strip())


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("mechanic", ["TAL_FENCING_FOOTWORK", "RETRIBUTION_BASE_COUNTERSTRIKE"])
def test_reopen_answer_duplicate_and_commit_before_unlink(tmp_path, automatic, mechanic, monkeypatch):
    combat, table, mid, cid, send = fixture(tmp_path, mechanic)
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    initial = table.state(mid)
    assert initial["pending_action"] is None  # old fights without a sidecar are unchanged
    first = table.auto_step(mid, 0) if automatic else send(cid)
    assert first["status"] == "REACTION_REQUIRED"
    table = reopen(table, tmp_path)
    pending = table.state(mid)["pending_action"]
    assert pending["request"]["decision_id"] == initial["menu"]["decision_id"]
    assert pending["request"]["state_version"] == initial["menu"]["state_version"]
    # Autoplay/repeated empty sends retain the original prompt and prior answers.
    assert resume(table, mid, pending, [])["reaction"] == pending["reaction"]
    if automatic:
        assert table.auto_step(mid, 0)["reaction"] == pending["reaction"]
    else:
        menu = initial["menu"]
        with pytest.raises(TabletopError, match="saved choice"):
            table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    prompt = pending["reaction"]
    answer = {**prompt["context"], "selection": "USE"}
    if prompt.get("choice"):
        answer["option_ids"] = [next(o["id"] for o in prompt["choice"]["options"] if "Stay put" in o["label"])]
    commits = commit_count(table, mid)
    # Simulate a crash between the combat journal commit and pending-file removal.
    save = table._save_pending_action
    monkeypatch.setattr(table, "_save_pending_action", lambda match, value: save(match, value) if value else None)
    result = resume(table, mid, pending, [answer])
    assert result["status"] == "COMMITTED"
    assert table._pending_action_path(mid).exists()
    assert result["state"]["pending_action"] is None
    table = reopen(table, tmp_path)
    assert table.state(mid)["pending_action"] is None
    with pytest.raises(TabletopError):
        resume(table, mid, pending, [answer])
    if automatic:
        with pytest.raises(TabletopError):
            table.auto_step(mid, 0, [answer])  # legacy duplicate is also fail-closed
    assert commit_count(table, mid) == commits + 1
    session = table.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_pending_publication_is_atomic_and_legacy_auto_is_not_guessed(tmp_path):
    combat, table, mid, cid, send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    send(cid)
    path = table._pending_action_path(mid)
    value = json.loads(path.read_text())
    assert not list(path.parent.glob(path.name + ".*.tmp"))
    # A partial interrupted temporary write cannot replace the complete record.
    interrupted = path.with_suffix(".tmp")
    interrupted.write_text('{"request":')
    assert reopen(table, tmp_path).state(mid)["pending_action"] == value
    interrupted.unlink()
    value["schema"] = "TabletopPendingAction.v1"
    table._save_pending_action(mid, value)
    assert table.state(mid)["pending_action"] == value  # bound manual v1 remains recoverable
    value.update(method="auto_step", request={"after": 0})
    table._save_pending_action(mid, value)
    assert table.state(mid)["pending_action"] is None


@pytest.mark.parametrize("automatic", [False, True])
def test_reopened_space_choice_moves_to_selected_square(tmp_path, automatic):
    from tests.test_hunt5_player_choices import PLAYER
    combat, table, mid, cid, send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0) if automatic else send(cid)
    table = reopen(table, tmp_path)
    pending = table.state(mid)["pending_action"]
    option = next(o["id"] for o in pending["reaction"]["choice"]["options"] if o["id"].startswith("cell:"))
    answer = {**pending["reaction"]["context"], "selection": "USE", "option_ids": [option]}
    count = commit_count(table, mid)
    assert resume(table, mid, pending, [answer])["status"] == "COMMITTED"
    assert commit_count(table, mid) == count + 1
    session = table.combat._load_session(mid)
    x, y = map(int, option.removeprefix("cell:").split(","))
    assert session.engine.state.actors[PLAYER].position.model_dump(mode="json") == {"x": x, "y": y}
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("automatic", [False, True])
def test_multiple_choice_reopens_for_player_and_ai_decides_automatically(tmp_path, automatic):
    from tests.r1i_service_support import fixture as team_fixture, OWNER, FOE as ENEMY, SECOND, force_ai_candidate
    from tests.test_carry import KIT
    def enough_focus(bundles):
        # Synthetic starting pool pays both Exploits plus Skewer; this transport
        # test is not a character-build legality test.
        resource = next(r for r in bundles[0]["actor_template"]["resources"] if r["resource_id"] == "resource:core.martial_focus")
        resource.update(initial=3, maximum=3)
    combat, table, mid, send, _ = team_fixture(tmp_path,
        ["TAL_FENCING_FACE_STRIKE", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SKEWER"],
        foe_ac=0, owner_kit={"starting_kit": KIT}, allies=(SECOND,), seed="L53-MULTI-2", bundle_transform=enough_focus)
    state = table.state(mid)
    cid = next(o["candidate_id"] for g in state["menu"]["actions"] if ".weapon." in g["source_definition_id"]
               and "#" not in g["source_definition_id"] for o in g["options"] if ENEMY in o["target_ids"])
    if automatic:
        force_ai_candidate(combat, mid, OWNER, cid)
    count = commit_count(table, mid)
    result = send(cid, auto=automatic)
    if automatic:
        # An AI-owned chooser must decide automatically, including on reopen.
        assert result["status"] == "COMMITTED"
        table = reopen(table, tmp_path)
        assert table.state(mid)["pending_action"] is None
        assert commit_count(table, mid) == count + 1
        session = table.combat._load_session(mid)
        assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
        return
    seen, answers = False, []
    for _ in range(12):
        if result["status"] == "COMMITTED":
            break
        table = reopen(table, tmp_path)
        pending = table.state(mid)["pending_action"]
        prompt = pending["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            maximum = prompt["choice"]["maximum"]
            answer["option_ids"] = [o["id"] for o in prompt["choice"]["options"][:maximum]]
            if maximum == 2:
                seen = True
                assert len(answer["option_ids"]) == 2
        answers.append(answer)
        result = resume(table, mid, pending, answers)
    assert seen and result["status"] == "COMMITTED"
    assert commit_count(table, mid) == count + 1
    session = table.combat._load_session(mid)
    # Face Strike costs 1 Focus; Arm Strike is free; Skewer costs 1 Focus.
    assert session.engine.state.actors[OWNER].resources["resource:core.martial_focus"] == 1
    assert any("Face Strike" in str(e.payload) and "Arm Strike" in str(e.payload) for e in session.engine.events)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_auto_recovery_reserves_against_another_table_writer(tmp_path, monkeypatch):
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0)
    pending = result["state"]["pending_action"]
    prompt = pending["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [
        next(o["id"] for o in prompt["choice"]["options"] if "Stay put" in o["label"])]}
    count = commit_count(table, mid)
    other = reopen(table, tmp_path)
    original = combat.local_step
    def raced(match, reactions, *, session):
        # Same process uses a reentrant Python lock; the separate OS lock must
        # reject another table writer before it can load or commit this decision.
        with pytest.raises(TabletopError, match="Another action on this table is still finishing") as busy:
            resume(other, mid, pending, [answer])
        assert busy.value.code == 'TABLETOP_BUSY'
        assert busy.value.status_code == 409
        assert commit_count(other, mid) == count
        return original(match, reactions, session=session)
    monkeypatch.setattr(combat, "local_step", raced)
    assert resume(table, mid, pending, [answer])["status"] == "COMMITTED"
    assert commit_count(table, mid) == count + 1
    loaded = other.combat._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_step_api_model_preserves_binding_and_partial_binding_is_rejected(tmp_path):
    from app.models import TabletopStepRequest
    combat, table, mid, _, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    menu = table.state(mid)["menu"]
    body = TabletopStepRequest(decision_id=menu["decision_id"], state_version=menu["state_version"])
    assert body.model_dump()["decision_id"] == menu["decision_id"]
    count = commit_count(table, mid)
    with pytest.raises(TabletopError):
        table.auto_step(mid, 0, [], body.decision_id, None)
    assert commit_count(table, mid) == count
