"""Offline model seats exercised through the real persisted table transport."""
import json
import threading
import time

import pytest

from agent_seats import SeatRunner
from agent_seats.providers import ProviderRegistry
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER


class FakeProvider:
    def __init__(self, attack=False):
        self.prompts = []
        self.attack = attack

    def __call__(self, provider, prompt, png):
        self.prompts.append(prompt)
        frame = json.loads(prompt.split("\n", 1)[1])
        legal = frame["legal_menu"]
        if "ability" in legal:
            choice = legal.get("choice") or {}
            opts = choice.get("options", [])
            stay = next((o for o in opts if "Stay put" in o["label"]), opts[0] if opts else None)
            return json.dumps({"selection": "USE", "option_ids": [stay["id"]] if stay else [], "spend": 0}), {"total_tokens": 12}
        end = next(k for k, v in legal.items() if v["action"] == "End turn")
        plan = [end]
        if self.attack:
            strike = next((k for k, v in legal.items() if PLAYER in v["targets"] and "weapon" in v["source"]), None)
            if strike:
                plan.insert(0, strike)
        return json.dumps({"plan": plan}), {"total_tokens": 12}


def runner_for(tmp_path, table, provider=None, timeout=1, **kwargs):
    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"providers": [{"id": "fake", "kind": "local", "model": "offline",
        "base_url": "http://127.0.0.1:1/v1", "timeout_s": timeout}]}))
    fake = provider or FakeProvider()
    runner = SeatRunner(table, registry=ProviderRegistry(registry), provider=fake, background=False, **kwargs)
    return runner, fake


def raw_state(runner, mid):
    runner._local.active = True
    try:
        return runner.table.state(mid)
    finally:
        runner._local.active = False


def test_one_call_plans_and_plays_a_whole_turn(tmp_path):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    fake = FakeProvider(attack=True)
    runner, _ = runner_for(tmp_path, table, fake)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    initial = raw_state(runner, mid)
    assert table.state(mid)["menu"]["control_mode"] == "MODEL"
    # A browser's Auto Step must not silently substitute its own AI for a model.
    assert table.auto_step(mid, 0)["status"] == "MODEL_DECIDING"
    assert runner.drive(mid, max_steps=2) == 2
    final = raw_state(runner, mid)
    assert final["menu"]["actor_id"] == PLAYER
    assert final["last_sequence"] > initial["last_sequence"]
    assert len(fake.prompts) == 1
    assert runner.decisions(mid)[0]["tokens"] == {"total_tokens": 12}
    session = combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
@pytest.mark.parametrize("recording", [False, True])
def test_model_reaction_is_answered_on_opponents_turn_and_reload(tmp_path, automatic, profile, recording, monkeypatch):
    monkeypatch.setenv("FACTORY_SEAT_RECORDS", "1" if recording else "0")
    combat, table, mid, cid, _send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    fake = FakeProvider()
    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"providers": [{"id": "fake", "kind": "local", "model": "offline",
        "base_url": "http://127.0.0.1:1/v1", "timeout_s": 1, "prompt_profile": profile}]}))
    runner = SeatRunner(table, registry=ProviderRegistry(registry), provider=fake, background=False)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    if automatic:
        runner.set_seat(mid, FOE, "AI")
    before = combat._load_session(mid).engine.state.actors[PLAYER].position
    menu = table.state(mid)["menu"]
    out = table.auto_step(mid, 0) if automatic else table.act(mid, cid, menu["decision_id"], menu["state_version"], 0)
    assert out["status"] == "MODEL_DECIDING"
    assert "reaction" not in out
    assert table.state(mid)["pending_action"] is None
    # Full reaction context travels with the saved pending request.
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    runner, _ = runner_for(tmp_path, reopened, fake)
    assert runner.seats(mid)[PLAYER] == {"control": "MODEL", "provider_id": "fake"}
    assert runner.drive(mid, max_steps=1) == 1
    assert raw_state(runner, mid)["pending_action"] is None
    session = reopened.combat._load_session(mid)
    assert session.engine.state.actors[PLAYER].position == before
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    assert len(fake.prompts) == 1
    decision = runner.decisions(mid)[-1]
    assert decision["kind"] == "REACTION"
    assert decision["fallback"] is None
    assert decision["chosen"]["selection"] == "USE"
    records = tmp_path / "seat_decisions.jsonl"
    if recording:
        [record] = [json.loads(line) for line in records.read_text(encoding="utf-8").splitlines()]
        assert record["kind"] == "REACTION"
        assert isinstance(record["answers"]["reaction"]["ability"], str)
        assert record["answers"]["reaction"]["ability"]
        assert isinstance(record["answers"]["reaction"]["choice"], dict)
        assert record["answers"]["reaction"]["spend_options"]
    else:
        assert not records.exists()


def test_deadline_uses_builtin_pick_without_waiting_for_provider(tmp_path):
    combat, table, mid, cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    release = threading.Event()
    def slow(provider, prompt, png):
        release.wait(5)
        return '{}', None
    runner, _ = runner_for(tmp_path, table, slow, timeout=0.03)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    start = time.monotonic()
    try:
        assert runner.drive(mid, max_steps=1) == 1
    finally:
        release.set()
    assert time.monotonic() - start < 3
    row = next(r for r in runner.decisions(mid) if r["kind"] == "TURN")
    assert row["fallback"] == "timeout"
    assert row["chosen"] == [row["built_in_pick"]]
    assert "built-in AI chose" in row["text"]
    assert row["latency_ms"] < 1000
    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_seat_modes_survive_service_reload_and_never_store_credentials(tmp_path, monkeypatch):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    monkeypatch.setenv("EXAMPLE_API_KEY", "not-a-real-secret")
    runner, _ = runner_for(tmp_path, table)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    runner.set_seat(mid, PLAYER, "AI")
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    runner2, _ = runner_for(tmp_path, reopened)
    assert runner2.seats(mid) == {FOE: {"control": "MODEL", "provider_id": "fake"}, PLAYER: {"control": "AI"}}
    assert reopened.combat.decision(mid)["control_mode"] == "MANUAL"
    runner2.set_seat(mid, FOE, "MANUAL")
    assert runner2.seats(mid)[FOE] == {"control": "MANUAL"}
    assert "not-a-real-secret" not in runner2._path(mid).read_text()


def test_prompt_and_renderer_use_only_actor_fog_view(tmp_path):
    from tests.r1i_service_support import OWNER, FOE as ENEMY, SECOND, fixture as team_fixture
    combat, table, mid, send, commit = team_fixture(tmp_path, ["DARK_BASE_DARKNESS"], allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, ENEMY: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}})
    # Stage the identical native square directly; the table now presents the
    # ability's placement as a second-stage picker rather than eager rows.
    engine = combat._load_session(mid).engine
    darkness = next(c for c in engine.legal_candidates()
                    if engine.action_catalog.get(c.source_definition_id)
                    and engine.action_catalog[c.source_definition_id].display_name == 'Darkness'
                    and c.destination is not None
                    and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0))
    commit(darkness.candidate_id)
    for _ in range(3):
        state = table.state(mid, fog=True)
        if state["menu"]["actor_id"] == SECOND:
            break
        commit(state["menu"]["end_turn"])
    assert state["menu"]["actor_id"] == SECOND
    assert ENEMY not in state["fog_perception"][SECOND]["creatures"]
    snapshots = []
    from agent_seats.snapshots import SnapshotRenderer
    renderer = SnapshotRenderer()
    def render(view):
        snapshots.append(view)
        png = renderer(view)
        assert png.startswith(b'\x89PNG\r\n\x1a\n')
        return png
    runner, fake = runner_for(tmp_path, table, render_png=render)
    registry = json.loads(runner.registry.path.read_text())
    registry["providers"][0]["vision"] = True
    runner.registry.path.write_text(json.dumps(registry))
    runner.set_seat(mid, SECOND, "MODEL", "fake")
    # Use the real shipped controller, including its actor-scoped recommendation.
    from combat.gate4_controller import LocalDeterministicController
    combat.controller = LocalDeterministicController()
    assert runner.drive(mid, max_steps=1) == 1
    assert len(fake.prompts) == len(snapshots) == 1
    assert ENEMY not in fake.prompts[0]
    assert ENEMY not in json.dumps(snapshots[0])
    assert "dao" in fake.prompts[0] and "built_in_reason" in fake.prompts[0]


@pytest.mark.parametrize("bad", ["not json", '{"plan":["invented"]}', '{"plan":[]}'])
def test_invalid_reply_falls_back_through_legality(tmp_path, bad):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table, lambda *args: (bad, None))
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert next(r for r in runner.decisions(mid) if r["kind"] == "TURN")["fallback"]
    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_registry_rejects_embedded_keys(tmp_path):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [{"id": "bad", "kind": "local", "api_key": "do-not-store"}]}))
    with pytest.raises(ValueError, match="never API keys"):
        ProviderRegistry(path).load()


def test_background_provider_never_blocks_refresh_or_runs_on_request_thread(tmp_path):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    entered, release = threading.Event(), threading.Event()
    fake = FakeProvider()
    main_thread = threading.get_ident()
    def waiting(provider, prompt, png):
        assert threading.get_ident() != main_thread
        entered.set()
        release.wait(5)
        return fake(provider, prompt, png)
    runner, _ = runner_for(tmp_path, table, waiting, timeout=5)
    runner.background = True
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert entered.wait(10)
    worker = runner._running[mid]
    try:
        state = table.state(mid)
        assert state["menu"]["control_mode"] == "MODEL"
        assert runner.status(mid)["status"] == "DECIDING"
        assert "is deciding" in runner.status(mid)["text"]
        assert worker.is_alive() and not release.is_set()
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_unassigned_driver_is_byte_identical_and_does_not_schedule(tmp_path):
    _combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    before = json.dumps(table.state(mid), sort_keys=True)
    runner, fake = runner_for(tmp_path, table)
    runner.background = True
    after = json.dumps(table.state(mid), sort_keys=True)
    assert after == before
    assert runner._running == {} and fake.prompts == []


def test_reply_cannot_commit_after_seat_is_returned_to_human(tmp_path):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    fake = FakeProvider()
    def cancel(provider, prompt, png):
        runner.set_seat(mid, FOE, "MANUAL")
        return fake(provider, prompt, png)
    runner, _ = runner_for(tmp_path, table, cancel)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    before = combat._load_session(mid).engine.state.state_version
    assert runner.drive(mid, max_steps=1) == 0
    assert combat._load_session(mid).engine.state.state_version == before
    assert runner.seats(mid)[FOE] == {"control": "MANUAL"}


def test_writer_guard_checks_seat_change_after_early_check(tmp_path):
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    session = combat._load_session(mid)
    decision = combat.decision(mid, session=session)
    runner._local.active = True
    runner._local.expected_seats = runner.seats(mid)
    try:
        runner.set_seat(mid, FOE, "MANUAL")
        from combat.tabletop import TabletopError
        with pytest.raises(TabletopError, match="control changed"):
            table.act(mid, decision["context"]["legal_candidates"][0]["candidate_id"],
                      decision["context"]["decision_id"], decision["context"]["state_version"], 0)
    finally:
        runner._local.active = False
        runner._local.expected_seats = None


def test_reaction_timeout_falls_back_to_real_ai(tmp_path):
    combat, table, mid, cid, _send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    def timeout(*args):
        raise TimeoutError()
    runner, _ = runner_for(tmp_path, table, timeout)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    menu = table.state(mid)["menu"]
    assert table.act(mid, cid, menu["decision_id"], menu["state_version"], 0)["status"] == "MODEL_DECIDING"
    assert runner.drive(mid, max_steps=1) == 1
    assert raw_state(runner, mid)["pending_action"] is None
    row = runner.decisions(mid)[-1]
    assert row["fallback"] == "timeout" and row["chosen"] == row["built_in_pick"]
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("automatic", [False, True])
def test_old_pending_reaction_can_be_adopted_by_model(tmp_path, automatic):
    combat, table, mid, cid, _send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    menu = table.state(mid)["menu"]
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
        table.auto_step(mid, 0)
    else:
        table.act(mid, cid, menu["decision_id"], menu["state_version"], 0)
    pending = table.state(mid)["pending_action"]
    pending.pop("reaction_context")
    table._save_pending_action(mid, pending)
    runner, _ = runner_for(tmp_path, table)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert raw_state(runner, mid)["pending_action"] is None


def test_seat_endpoints_use_existing_session_authorization(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator
    from app.api import create_app
    from app.core import Settings
    combat, table, mid, _cid, _send = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    monkeypatch.setenv("FACTORY_SEAT_PROVIDERS", str(runner.registry.path))
    # Match the existing API fixture's external schema-validation context.
    monkeypatch.setattr(Draft202012Validator, "check_schema", classmethod(lambda cls, schema, format_checker=None: None))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    app.state.agent_seats.provider = fake
    app.state.combat.controller = combat.controller
    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        providers = client.get("/api/tabletop/providers").json()["providers"]
        assert providers == [{"id": "fake", "kind": "local", "model": "offline", "prompt_profile": "full"}]
        body = {"actor_id": FOE, "control": "MODEL", "provider_id": "fake"}
        url = f"/api/tabletop/matches/{mid}"
        assert client.post(url + "/seat", json=body).status_code == 403
        assert client.post(url + "/seat", json=body, headers=headers).status_code == 200
        assert client.get(url + "/seat-status").json()["seats"][FOE] == {"control": "MODEL", "provider_id": "fake"}
        assert client.get(url + "/seat-decisions").json()["decisions"] == []
        assert client.post(url + "/playback", json={"paused": True}).status_code == 403
        assert client.post(url + "/playback", json={"paused": "false"}, headers=headers).status_code == 422
        paused = client.post(url + "/playback", json={"paused": True}, headers=headers)
        assert paused.status_code == 200 and paused.json()["paused"] is True
        assert client.get(url + "/seat-status").json()["paused"] is True
        before = app.state.agent_seats.table.state(mid)["last_sequence"]
        assert app.state.agent_seats.drive(mid, max_steps=1) == 0
        assert app.state.agent_seats.table.state(mid)["last_sequence"] == before
        assert client.post(url + "/playback", json={"paused": False}, headers=headers).json()["paused"] is False
        assert app.state.agent_seats.drive(mid, max_steps=1) == 1
        decisions = client.get(url + "/seat-decisions").json()["decisions"]
        assert decisions[0]["provider_id"] == "fake"
        assert client.post(url + "/seat", json={**body, "provider_id": "missing"}, headers=headers).status_code == 422
        assert client.post(url + "/seat", json={**body, "style": "choices"}, headers=headers).status_code == 200
        assert client.get(url + "/seat-status").json()["seats"][FOE] == {"control": "MODEL", "provider_id": "fake", "style": "choices"}
        assert client.post(url + "/seat", json={**body, "style": "tiny"}, headers=headers).status_code == 422
        assert client.post(url + "/seat", json={"actor_id": FOE, "control": "AI", "style": "full"}, headers=headers).status_code == 422


@pytest.mark.parametrize("public", [False, True])
def test_inactive_model_slot_advances_after_reload_without_changing_seat(tmp_path, public):
    from combat.canonical import canonical_sha256
    from tests.r1i_service_support import OWNER, SECOND, fixture as team_fixture, candidate

    def lethal_backlash(bundles):
        # A synthetic self-damage effect creates a defeated CURRENT slot via
        # a real action commit. Already-defeated future slots are auto-skipped.
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        for action in owner["action_catalog"]:
            if action["display_name"].startswith("Gather Current:"):
                action["parameters"]["typed"]["effects"].append(
                    {"type": "damage", "applies_to": "self", "damage_types": ["FORCE"], "flat": 2000})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = team_fixture(tmp_path, ["AIR_BASE_GATHER_CURRENT"],
        allies=(SECOND,), bundle_transform=lethal_backlash)
    commit(candidate(table, mid, "Gather Current"))
    defeated = combat._load_session(mid).engine.state.actors[OWNER]
    assert not defeated.active
    runner, fake = runner_for(tmp_path, table)
    runner.set_seat(mid, OWNER, "MODEL", "fake")
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    runner, _ = runner_for(tmp_path, reopened, fake)
    before = raw_state(runner, mid)
    assert before["menu"]["actor_id"] == OWNER and not before["presentation"]["terminal"]
    assert runner.before_action(mid) is None
    decision = reopened.combat.decision(mid)
    assert not runner.guard_action(mid, decision, reopened.combat._load_session(mid).engine)
    if public:
        assert reopened.auto_step(mid, before["last_sequence"])["status"] == "COMMITTED"
    else:
        assert runner.drive(mid, max_steps=1) == 1
    after = reopened.state(mid)
    assert after["menu"]["actor_id"] != OWNER
    assert runner.seats(mid)[OWNER] == {"control": "MODEL", "provider_id": "fake"}
    assert not fake.prompts
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_own_turn_model_choice_refresh_and_reload_while_provider_is_blocked(tmp_path):
    from tests.r1i_service_support import OWNER, fixture as team_fixture, candidate
    combat, table, mid, send, _commit = team_fixture(tmp_path, ["RETRIBUTION_BASE_COUNTERSTRIKE"])
    cid = candidate(table, mid, "Counterstrike")
    assert send(cid)["status"] == "REACTION_REQUIRED"
    pending = table.state(mid)["pending_action"]
    assert pending["reaction"]["context"]["reactor_id"] == OWNER
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    entered, release = threading.Event(), threading.Event()
    fake = FakeProvider()
    def waiting(provider, prompt, png):
        entered.set()
        assert release.wait(10)
        return fake(provider, prompt, png)
    runner, _ = runner_for(tmp_path, table, waiting, timeout=10)
    runner.set_seat(mid, OWNER, "MODEL", "fake")
    results = []
    worker = threading.Thread(target=lambda: results.append(runner.drive(mid, max_steps=1)))
    worker.start()
    try:
        assert entered.wait(10)
        for source in (table, TabletopService(CombatService(ROOT, tmp_path), tmp_path)):
            if source is not table:
                runner_for(tmp_path, source, fake)
            state = source.state(mid)
            assert state["pending_action"] is None
            assert state["menu"]["control_mode"] == "MODEL"
            assert worker.is_alive() and not release.is_set()
        assert raw_state(runner, mid)["pending_action"] == pending
    finally:
        release.set()
        worker.join(15)
    assert not worker.is_alive() and results == [1]
    assert raw_state(runner, mid)["pending_action"] is None
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"



def test_model_owner_answers_stamina_guard_amount_reaction(tmp_path):
    """MODELAMOUNT1: a model owner must answer the Stamina Guard amount prompt, not stall the attack."""
    from tests.hunt14_support import ME, FOE, advance, fight
    from tests.iron_fist_support import IRON_FIST_DAMAGE_TYPE, automatic_answer
    combat, table, mid = fight(tmp_path, cl=12, offturn=True)
    advance(table, mid, FOE)
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "natural.iron_fist" in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if ME in o["target_ids"])
    answers, prompt = [], None
    for _ in range(20):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], table.state(mid)["last_sequence"], answers)
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt["context"]["reaction_source_id"] == IRON_FIST_DAMAGE_TYPE:
            answers.append(automatic_answer(prompt))
            continue
        break
    assert prompt["reaction"] == "Stamina Guard", prompt["reaction"]
    seen = []
    def provider(_provider, prompt_text, _png):
        legal = json.loads(prompt_text.split("\n", 1)[1])["legal_menu"]
        seen.append(legal)
        options = (legal.get("choice") or {}).get("options", [])
        return json.dumps({"selection": "USE", "option_ids": [options[0]["id"]], "spend": 0}), {"total_tokens": 1}
    runner, _ = runner_for(tmp_path, table, provider)
    runner.set_seat(mid, ME, "MODEL", "fake")
    from pydantic import ValidationError
    try:
        driven = runner.drive(mid, max_steps=1)
    except ValidationError as error:
        raise AssertionError("; ".join(f"{'.'.join(map(str, e['loc']))}|{e['type']}|{str(e.get('input'))[:80]}" for e in error.errors())) from None
    assert driven == 1
    assert any(l.get("ability") == "Stamina Guard" for l in seen)
    assert table.state(mid)["pending_action"] is None


def test_invalid_model_amount_answer_falls_back_and_resolves(tmp_path):
    """MODELAMOUNT1: an unusable model answer must fall back to the built-in pick, not stall the attack."""
    from tests.hunt14_support import ME, FOE, advance, fight
    from tests.iron_fist_support import IRON_FIST_DAMAGE_TYPE, automatic_answer
    combat, table, mid = fight(tmp_path, cl=12, offturn=True)
    advance(table, mid, FOE)
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "natural.iron_fist" in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if ME in o["target_ids"])
    answers = []
    for _ in range(20):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], table.state(mid)["last_sequence"], answers)
        assert result["status"] == "REACTION_REQUIRED", result
        if result["reaction"]["context"]["reaction_source_id"] == IRON_FIST_DAMAGE_TYPE:
            answers.append(automatic_answer(result["reaction"]))
            continue
        break
    assert result["reaction"]["reaction"] == "Stamina Guard"
    def provider(_provider, prompt_text, _png):
        return "I would rather not choose a number.", {"total_tokens": 1}
    runner, _ = runner_for(tmp_path, table, provider)
    runner.set_seat(mid, ME, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert table.state(mid)["pending_action"] is None
