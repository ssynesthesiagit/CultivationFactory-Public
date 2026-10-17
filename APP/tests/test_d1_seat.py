"""d1 wire contract and persisted table decisions; fake HTTP only, no inference."""
import importlib.util
import json
import math
from http.server import HTTPServer
import os
import re
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from agent_seats import SeatRunner
from agent_seats.choices import build_prompt, decision_payload, turn_options
from agent_seats.providers import ProviderRegistry, complete
from combat.gate4_controller import LocalDeterministicController
from tests.h1_support import ROOT
from tests.test_agent_seats import raw_state
from tests.test_hunt5_player_choices import fixture, FOE
from tests.test_seat_compact import large_fight


def load_tool(name):
    spec = importlib.util.spec_from_file_location("d1_" + name, ROOT.parent / "tools" / "d1" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeModel:
    def __init__(self):
        self.calls = []
        self.mode = "ok"
        self.play_active_steps = False
        self.preferred_steps = {}
        self.preferred_follow_up = None

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.mode == "error":
            raise RuntimeError("offline")
        if self.mode == "timeout":
            time.sleep(.08)
        criteria = questions["action"]["criteria"]
        choice = "Z" if self.mode == "illegal" else next(iter(criteria))
        if (self.play_active_steps and self.mode == "ok"
                and state.startswith("Choose the next step of your plan;")):
            # Seek an Action rather than ending after a setup bonus/move. Then
            # explicitly commit it with End. Follow-ups have no End and must
            # choose B, never a rules/situation navigation control.
            fighter = next((fighter for fighter in self.preferred_steps
                            if f"Fighter: {fighter} ·" in state), None)
            script = self.preferred_steps.get(fighter)
            preferred = script[0] if isinstance(script, tuple) else script
            if preferred == "Blackwater Serpent Court at Lee Jia":
                position = re.search(r"Threat: Lee Jia at (\(\d+,\d+\))", state)
                if position:
                    preferred = "Blackwater Serpent Court to " + position[1]
            if (criteria.get("A") == "End turn here"
                    and ("Plan so far:" in state or preferred == "End turn here")):
                choice = "A"
                if isinstance(script, tuple) and len(script) > 1:
                    self.preferred_steps[fighter] = script[1:]
            elif ("A" not in criteria and "B" in criteria and "L" in criteria
                  and self.preferred_follow_up and self.preferred_follow_up not in criteria["B"]):
                choice = "L"
            elif ("A" in criteria and "B" in criteria and "L" in criteria
                  and ((preferred and not criteria["B"].startswith(preferred))
                       or "(Action" not in criteria["B"]
                       or criteria["B"].startswith(("Dodge", "Disengage", "Dash", "Hide", "Help", "Ready", "Search")))):
                choice = "L"
            elif "B" in criteria:
                choice = "B"
        return {"answers": {"action": {"choice": choice, "confidence": .75,
                "probabilities": {k: (1 if len(criteria) == 1 else .75) if k == choice
                                  else .25 / max(1, len(criteria) - 1) for k in criteria}}}}


@pytest.fixture
def endpoint(monkeypatch):
    """Fake endpoint at the HTTP dispatch boundary; needs no sandbox socket."""
    model = FakeModel()
    module = load_tool("d1_server")
    url = "http://127.0.0.1:11450"

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            return self.body[:size]

    def urlopen(request, timeout):
        assert request.full_url == url + "/decide"
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert timeout > 0
        payload = json.loads(request.data)
        try:
            reply = module.decide(model, payload)
        except RuntimeError:
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", None, None) from None
        return Response(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    yield model, url


@pytest.mark.skipif(os.environ.get("FACTORY_D1_HTTP_TEST") != "1",
                    reason="lead runs actual loopback HTTP outside sandbox")
def test_real_loopback_fake_model_http():
    model = FakeModel()
    server = HTTPServer(("127.0.0.1", 0), load_tool("d1_server").handler_for(model))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        view, legal = large_fight()
        prompt, offered = build_prompt(view, turn_options(view, legal, "hit"), "TURN", legal)
        choice, usage = complete({"kind": "d1", "base_url": f"http://127.0.0.1:{server.server_port}",
                                  "timeout_s": 1}, prompt)
        assert choice in offered and usage["decision"]["confidence"] == .75
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def runner_for_d1(tmp_path, table, url, timeout=1):
    path = tmp_path / "d1-providers.json"
    path.write_text(json.dumps({"providers": [{"id": "d1", "kind": "d1", "base_url": url,
                                             "timeout_s": timeout, "choices_bytes": 2400, "max_options": 12}]}))
    return SeatRunner(table, registry=ProviderRegistry(path), background=False)


def test_wire_uses_one_choice_question_and_keeps_shared_mechanics(endpoint):
    model, url = endpoint
    view, legal = large_fight()
    prompt, offered = build_prompt(view, turn_options(view, legal, "hit"), "TURN", legal)
    choice, usage = complete({"kind": "d1", "base_url": url, "timeout_s": 1}, prompt)
    state, questions = model.calls[0]
    assert set(questions) == {"action"}
    assert questions["action"]["type"] == "choice"
    assert questions["action"]["criteria"] == decision_payload(prompt)["options"]
    assert set(questions["action"]["criteria"]) == set(offered)
    assert choice in offered and usage["decision"]["confidence"] == .75
    assert "HP:" in state and "private-secret" not in state
    shared = decision_payload("Situation:\nHP: 10\nA) Strike\nB) Strike then move\nFor A, B: Deal 3 damage; costs 1 Stamina")
    assert all("costs 1 Stamina" in value for value in shared["options"].values())
    assert "For A" not in shared["state"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1, True, "0.7"])
def test_invalid_metrics_rejected(bad):
    from agent_seats.d1 import finite_number
    with pytest.raises(ValueError):
        finite_number(bad, 0, 1)


def test_table_commits_d1_choice_logs_metrics_and_reloads(endpoint, tmp_path):
    model, url = endpoint
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = runner_for_d1(tmp_path, table, url)
    # d1 keeps choices even if the UI sends the whole-turn style.
    runner.set_seat(mid, FOE, "MODEL", "d1", style="full")
    before = raw_state(runner, mid)["last_sequence"]
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[0]
    assert not row["fallback"] and row["chosen_menu"]
    assert row["decision"]["choice"] in row["decision_menu"]
    assert row["decision"]["confidence"] == .75 and row["decision"]["ms"] >= 0
    assert row["built_in_pick"] and row["latency_ms"] >= 0
    assert raw_state(runner, mid)["last_sequence"] > before
    assert combat._load_session(mid).verify()["status"] == "PASS"
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    reopened = runner_for_d1(tmp_path, TabletopService(CombatService(ROOT, tmp_path), tmp_path), url)
    assert reopened.decisions(mid)[0]["decision"] == row["decision"]
    assert reopened.seats(mid)[FOE]["provider_id"] == "d1"


@pytest.mark.parametrize("mode", ["error", "illegal", "timeout"])
def test_table_fallback_is_builtin_and_legal(endpoint, tmp_path, mode):
    model, url = endpoint
    model.mode = mode
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = runner_for_d1(tmp_path, table, url, timeout=.02 if mode == "timeout" else 1)
    runner.set_seat(mid, FOE, "MODEL", "d1")
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[0]
    assert row["fallback"] and row["chosen"] == [row["built_in_pick"]]
    assert row["fallback_error"]["stage"] == "provider"
    assert row["decision_menu"]
    assert "built-in AI chose" in row["text"]
    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_d1_uses_actual_combat_perception(endpoint, tmp_path):
    from tests.h49_fog_support import option
    from tests.r1i_service_support import OWNER, FOE as ENEMY, SECOND, fixture as team_fixture
    combat, table, mid, send, commit = team_fixture(tmp_path, ["DARK_BASE_DARKNESS"], allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, ENEMY: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}})
    commit(option(table, mid, "Darkness", {"x": 6, "y": 6})["candidate_id"])
    for _ in range(3):
        state = table.state(mid, fog=True)
        if state["menu"]["actor_id"] == SECOND:
            break
        commit(state["menu"]["end_turn"])
    assert state["menu"]["actor_id"] == SECOND
    session = combat._load_session(mid)
    from combat.senses import perception
    assert ENEMY not in perception(session.engine, session.engine.state.actors[SECOND])["creatures"]
    model, url = endpoint
    runner = runner_for_d1(tmp_path, table, url)
    combat.controller = LocalDeterministicController()
    runner.set_seat(mid, SECOND, "MODEL", "d1")
    assert runner.drive(mid, max_steps=1) == 1
    assert len(model.calls) == 1
    hidden_name = session.engine.state.actors[ENEMY].display_name
    payload = json.dumps(model.calls[0])
    assert ENEMY not in payload and hidden_name not in payload
    assert not runner.decisions(mid)[0]["fallback"]


def test_d1_reaction_on_ai_turn_commits_after_service_reload(endpoint, tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_hunt5_player_choices import PLAYER
    model, url = endpoint
    combat, table, mid, *_ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    runner = runner_for_d1(tmp_path, table, url)
    runner.set_seat(mid, PLAYER, "MODEL", "d1")
    runner.set_seat(mid, FOE, "AI")
    assert table.auto_step(mid, 0)["status"] == "MODEL_DECIDING"
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    runner = runner_for_d1(tmp_path, reopened, url)
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[-1]
    assert row["kind"] == "REACTION" and not row["fallback"]
    assert "Footwork" in json.dumps(model.calls)
    assert raw_state(runner, mid)["pending_action"] is None
    assert reopened.combat._load_session(mid).verify()["status"] == "PASS"


@pytest.mark.parametrize("extra", [{"prompt_profile": "full"}, {"vision": True}, {"request_options": {}}])
def test_registry_rejects_chat_settings_for_d1(tmp_path, extra):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"providers": [{"id": "d1", "kind": "d1", "base_url": "http://127.0.0.1:11450", **extra}]}))
    with pytest.raises(ValueError, match="d1 requires"):
        ProviderRegistry(path).load()


def test_server_rejects_malformed_request_before_inference():
    module = load_tool("d1_server")
    model = FakeModel()
    for payload in ({}, {"state": "x", "options": {}}, {"state": "x", "options": {"a": 1}}):
        with pytest.raises(ValueError):
            module.decide(model, payload)
    assert not model.calls


def test_follow_up_menu_requires_one_current_choice_without_ending_turn():
    from agent_seats.protocol import validate_answer
    view, legal = large_fight()
    legal = {"hit": legal["hit"], "skip": {"action": "Skip the follow-up", "targets": [], "options": []}}
    options = turn_options(view, legal, "hit")
    prompt, offered = build_prompt(view, options, "TURN", legal)
    assert "resolve the current action" in prompt and "Plans end your turn" not in prompt
    assert all(len(answer["plan"]) == 1 for answer in offered.values())
    assert validate_answer({"plan": ["hit"]}, legal, "TURN") == {"plan": ["hit"]}
    with pytest.raises(ValueError, match="exactly one"):
        validate_answer({"plan": ["hit", "skip"]}, legal, "TURN")


def test_table_option_seam_rejects_unoffered_or_malformed_selections(tmp_path):
    from combat.gate5_service import CombatServiceError
    from combat.tabletop import TabletopError
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    state = table.state(mid)
    menu = state["menu"]
    args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    with pytest.raises(TabletopError) as malformed:
        table.act(*args, option_ids="unoffered")
    assert malformed.value.code == "TABLETOP_OPTION_INVALID"
    with pytest.raises(CombatServiceError) as illegal:
        table.act(*args, option_ids=["unoffered"])
    assert illegal.value.diagnostic.code == "COMBAT_AI_INTENT_INVALID"
    assert combat._load_session(mid).engine.state.state_version == menu["state_version"]


def test_large_candidate_choice_pool_uses_legal_bounded_default():
    from agent_seats.action_options import expand_menu
    offered = tuple(f"MODE_{i}" for i in range(40))
    domain = SimpleNamespace(option_ids=offered, default_option_ids=(offered[0],),
        selection_rule="ZERO_OR_ONE", minimum_selections=0, maximum_selections=1,
        domain_id="mode", display_name="Mode", option_costs={})
    candidate = SimpleNamespace(candidate_id="candidate", source_definition_id="source",
        option_ids=offered, choice_domains=(domain,), choice_authority_status="COMPLETE")
    engine = SimpleNamespace(legal_candidates=lambda: (candidate,), action_catalog={},
                             state=SimpleNamespace(actors={}))
    view = {"actors": [], "objects": []}
    menu = {"key": {"candidate_id": "candidate", "description": {"action": "Use an effect",
        "source": "source", "targets": [], "destination": None, "options": list(offered)}}}
    result = expand_menu(menu, engine, view)
    assert len(result) == 1 and next(iter(result.values()))["description"]["options"] == [offered[0]]
    assert "Mode 0" in next(iter(result.values()))["description"]["action"]


def test_selected_options_survive_pending_reaction_reload_and_cannot_be_omitted(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop import TabletopError
    from combat.tabletop_service import TabletopService
    combat, table, mid, cid, *_ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    menu = table.state(mid)["menu"]
    args = (mid, cid, menu["decision_id"], menu["state_version"], 0)
    result = table.act(*args, option_ids=[])
    assert result["status"] == "REACTION_REQUIRED"
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    pending = json.loads(reopened._pending_action_path(mid).read_text())
    assert pending["request"]["option_ids"] == []
    with pytest.raises(TabletopError) as omitted:
        reopened.act(*args)
    assert omitted.value.code == "TABLETOP_PENDING"
    answer = {**result["reaction"]["context"], "selection": "DECLINE", "option_ids": [], "spend": 0}
    assert reopened.act(*args, reactions=[answer], option_ids=[])["status"] == "COMMITTED"
    assert reopened.combat._load_session(mid).verify()["status"] == "PASS"


def test_harness_reports_caps_draws_and_fallbacks_separately():
    module = load_tool("fight_harness")
    row = {"kind": "TURN", "chosen": ["a"], "built_in_pick": "a", "latency_ms": 9,
           "fallback": None, "decision": {"ms": 2}}
    fights = [{"d1_team": "a", "terminal": {"winning_team_id": "a"}, "decisions": [row]},
              {"d1_team": "a", "terminal": None, "decisions": [dict(row, fallback="timeout")]},
              {"d1_team": "b", "terminal": {"winning_team_id": None}, "decisions": []}]
    summary = module.summarize(fights)
    assert summary["win_rate"] == .5 and summary["unfinished"] == 1 and summary["draws"] == 1
    assert summary["fallback_count"] == 1 and summary["agreement_rate"] == 1
    assert summary["average_model_ms"] == 2


def test_harness_plays_stock_fixture_through_endpoint(endpoint, tmp_path):
    _, url = endpoint
    module = load_tool("fight_harness")
    result = module.run_fight(tmp_path, "GATE4-TEST", 0, url, max_steps=2)
    assert result["steps"] == 2
    # A short cap is explicitly unfinished; it is never counted as a loss.
    assert result["terminal"] is None
    assert module.summarize([result])["win_rate"] is None


def test_harness_completes_paired_swapped_stock_fights(endpoint, tmp_path, monkeypatch):
    model, url = endpoint
    # Keep this fixture exercising combat under the explicit-End protocol.
    model.play_active_steps = True
    # This offered area covers Lee Jia after the stock AI's approach. Keep it
    # active into the next round so a zone trigger supplies Moon-Sea Radiance
    # before Bai Meizhen's next area attack opens the native follow-up. The
    # later areas follow Lee Jia's position supplied in the own-view frame.
    model.preferred_steps = {
        "Bai Meizhen": ("Blackwater Serpent Court to (9,3)", "Blackwater Serpent Court at Lee Jia"),
        # Preserve the native follow-up target rather than defeating him first.
        "Ling Qi": ("Music Resonant Note", "End turn here"),
    }
    model.preferred_follow_up = "Moon"
    module = load_tool("fight_harness")
    # Reserve the test's Moon resource for the native damage-type follow-up,
    # rather than the automatic damage-reduction reaction. This controller is
    # confined to this fixture; every other reaction uses the stock policy.
    class FollowUpController(LocalDeterministicController):
        def choose_reaction(self, context):
            if context.reaction_source_id == "reaction:bai_meizhen.sea_moon_interposition":
                policy = context.policy.model_copy(update={"reaction_rules": {
                    **context.policy.reaction_rules,
                    context.reaction_source_id: {"minimum_packet": 10000},
                }})
                context = context.model_copy(update={"policy": policy})
            return super().choose_reaction(context)

    class FollowUpService(module.CombatService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.controller = FollowUpController()

    monkeypatch.setattr(module, "CombatService", FollowUpService)
    fights = []
    for team in (0, 1):
        data = tmp_path / str(team)
        data.mkdir()
        fights.append(module.run_fight(data, "GATE4-TEST", team, url, maximum_rounds=3))
    assert fights[0]["d1_team"] != fights[1]["d1_team"]
    assert all(f["terminal"] is not None and f["decisions"] for f in fights)
    summary = module.summarize(fights)
    assert summary["completed"] == 2 and summary["fallback_count"] == 0
    followups = [r for f in fights for r in f["decisions"] if r["kind"] == "TURN"
                 and any("Moon" in option["action"] for option in r["chosen_menu"])]
    assert followups, "The stock pair must exercise native damage-type follow-ups"
    assert all(len(option["options"]) <= 1 for r in followups for option in r["chosen_menu"])


@pytest.mark.parametrize("phase", ["active", "staged", "follow_up", "setup", "defensive", "preferred", "cost_action", "script_end"])
def test_harness_fake_handles_ranked_active_steps_and_explicit_end(phase):
    """Exercise the actual packed d1 frame, including navigation before B."""
    from agent_seats.menu_pages import RankedPages, choice_frame
    view, legal = large_fight()
    legal = {"hit": legal["hit"]}
    if phase == "cost_action":
        legal["hit"] = {**legal["hit"], "action_type": "ACTION", "cost_label": "Action, 4 Stamina"}
        legal["other"] = {"action": "Other attack", "targets": [], "options": []}
    if phase in {"setup", "defensive", "preferred"}:
        legal = {"setup": {"action": "Dodge" if phase == "defensive" else "Water Lash" if phase == "preferred" else "Gather Charge",
                           "action_type": "BONUS_ACTION" if phase == "setup" else "ACTION",
                           "targets": [], "options": []}, **legal}
    if phase != "follow_up":
        legal["end"] = {"action": "End turn", "targets": [], "options": []}
    first = "setup" if phase in {"setup", "defensive", "preferred"} else "hit"
    pages = RankedPages(legal, [first], first, 1)
    prompt, offered, _ = choice_frame(view, pages, 2400,
                                     selected=("hit",) if phase == "staged" else ())
    model = FakeModel()
    model.play_active_steps = True
    if phase in {"preferred", "script_end"}:
        own = next(actor for actor in view["actors"] if actor["entity_id"] == view["fighter"])
        model.preferred_steps = {own["display_name"]: "End turn here" if phase == "script_end" else "Blackwater Serpent Court"}
    reply = load_tool("d1_server").decide(model, decision_payload(prompt))
    expected = "__menu_more__" if phase in {"setup", "defensive", "preferred"} else "end" if phase in {"staged", "script_end"} else "hit"
    assert offered[reply["choice"]] == {"plan": [expected]}


@pytest.mark.parametrize("seed", ["LOCK5-A", "LOCK5-B", "LOCK5-C", "GATE4-TEST", "GATE4-AN-1", "GATE4-LEE"])
def test_builtin_stock_replays_unchanged(tmp_path, monkeypatch, seed):
    """Stock captures match this branch's fork point on main (tests/replay_base.py)."""
    from tests import test_wall_height_replays as stock
    monkeypatch.setenv("WALLHEIGHT_REPLAY_EVIDENCE", str(tmp_path / "evidence"))
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)


def test_local_app_protocol_uses_session_token_and_named_question(monkeypatch):
    """Owner's local AI app (2026-10-11): GET /session token, POST /decide with questions."""
    from agent_seats import d1 as d1_client
    model, url, tokens, calls = FakeModel(), "http://127.0.0.1:11452", ["t1"], []
    d1_client._tokens.clear()

    class Response:
        def __init__(self, body):
            self.body = json.dumps(body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            return self.body[:size]

    def urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url == url + "/session":
            return Response({"token": tokens[0]})
        assert request.full_url == url + "/decide"
        if request.get_header("X-d1-token") != tokens[0]:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)
        body = json.loads(request.data)
        assert set(body) == {"state", "questions"}
        assert body["questions"]["action"]["type"] == "choice"
        return Response(model.system_one(body["state"], body["questions"]))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    view, legal = large_fight()
    prompt, offered = build_prompt(view, turn_options(view, legal, "hit"), "TURN", legal)
    provider = {"kind": "d1", "protocol": "local-app", "base_url": url, "timeout_s": 1}
    choice, usage = complete(provider, prompt)
    assert choice in offered and usage["decision"]["confidence"] == .75 and usage["decision"]["ms"] >= 0
    tokens[0] = "t2"  # app reloaded: one retry with a fresh token
    choice, _ = complete(provider, prompt)
    assert choice in offered
    assert calls.count(url + "/session") == 2


def test_registry_allows_local_app_protocol_only_for_d1(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"providers": [{"id": "d1cpu", "kind": "d1", "protocol": "local-app",
                                               "base_url": "http://127.0.0.1:11452", "timeout_s": 10}]}))
    assert ProviderRegistry(path).load()["d1cpu"]["protocol"] == "local-app"
    path.write_text(json.dumps({"providers": [{"id": "x", "kind": "local", "model": "m", "protocol": "local-app",
                                               "base_url": "http://127.0.0.1:1"}]}))
    with pytest.raises(ValueError):
        ProviderRegistry(path).load()


def test_local_app_oversized_frame_falls_back_without_any_request(monkeypatch):
    """Over the app's 6,000-character CPU preset: reject before HTTP so the seat falls back."""
    from agent_seats import d1 as d1_client
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a) or None)
    provider = {"kind": "d1", "protocol": "local-app", "base_url": "http://127.0.0.1:11452", "timeout_s": 1}
    small = {"state": "x", "options": {"A": "Strike"}}
    questions = {"action": {"type": "choice", "instructions": d1_client.INSTRUCTIONS, "criteria": small["options"]}}
    room = d1_client.APP_LIMIT - len(json.dumps(["", questions]))
    with pytest.raises(ValueError):
        d1_client._app_reply(provider, {"state": "x" * (room + 1), "options": small["options"]})
    assert calls == []
    assert len(json.dumps(["x" * room, questions])) == d1_client.APP_LIMIT
