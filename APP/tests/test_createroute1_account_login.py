"""Character creation through an installed account CLI, without a real login."""
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import provider_transport
from agent_seats.providers import complete as seat_complete
from ai_provider import service as creation
from ai_provider.secrets import InMemorySecretStore
from app.core import FoundryError, canonical_json, utcnow
from app.models import AIProviderConfigureRequest, CharacterCreationStartRequest
from character_creation import CharacterCreationExecutionService


ANSWER = {"name": "Sable Crane"}
SETTINGS = dict(
    provider_id="agent", enabled=True, model="agent-authored", thinking_mode="disabled",
    max_output_tokens=16384, timeout_seconds=120, data_sharing_acknowledged=True,
    acknowledged_by="Test owner",
)


@pytest.fixture
def account(fresh_db, tmp_path, monkeypatch):
    service = creation.AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.agent_wait_override = 3
    script = tmp_path / "fake_account.py"
    presets = {
        "fake": ("Fake account", [sys.executable, str(script)]),
        "missing": ("Not installed", [str(tmp_path / "missing")]),
        "credential": ("Unsafe preset", [sys.executable, str(script), "--token=never-pass-this"]),
    }
    monkeypatch.setattr(creation, "ACCOUNT_CLI_PRESETS", presets, raising=False)
    return service, script, presets


def complete(service, *, key="account-probe"):
    return service.complete_json(
        prompt_text="Name one character.", system_message="Return one JSON object.",
        purpose="account_login_test", substantive=True, idempotency_key=key,
        expected_provider_selection={"provider_id": "agent", "account_cli_preset_id": "fake"},
        response_schema_name="AccountLoginProbe",
        response_schema={"type": "object", "required": ["name"], "additionalProperties": False,
                         "properties": {"name": {"type": "string"}}},
        response_schema_max_output_tokens=64,
    )


def test_unrelated_authoring_does_not_launch_account(account, monkeypatch):
    service, script, _ = account
    service.configure(**SETTINGS, account_cli_preset_id="fake")
    monkeypatch.setattr(service, "_answer_via_account_cli", lambda *args: pytest.fail("unexpected account dispatch"))
    monkeypatch.setattr(service.agent_bridge, "wait_for_answer", lambda *args, **kwargs: None)
    with pytest.raises(FoundryError) as error:
        service.complete_json(prompt_text="Other task", system_message="JSON", purpose="other_authoring",
                              substantive=True, response_schema_name="OtherTask")
    assert error.value.code == "AI_AGENT_AWAITING_RESPONSE"


def test_account_answers_and_consumes_the_existing_mailbox_once(account, monkeypatch):
    service, script, presets = account
    script.write_text(
        'import os, sys\n'
        'from pathlib import Path\n'
        'prompt = sys.stdin.read()\n'
        'assert "Name one character." in prompt and "Return one JSON object." in prompt, prompt\n'
        'assert "AccountLoginProbe" in prompt and "required" in prompt, prompt\n'
        'assert not list(Path.cwd().iterdir()), str(Path.cwd())\n'
        'assert os.environ["CF_FAKE_LOGIN"] == "available"\n'
        f'print({json.dumps(ANSWER)!r})\n'
    )
    monkeypatch.setenv("CF_FAKE_LOGIN", "available")
    calls = []
    original = getattr(provider_transport, "cli_completion", None)

    def shared(argv, prompt, **kwargs):
        calls.append((argv, prompt))
        return original(argv, prompt, **kwargs)

    monkeypatch.setattr(provider_transport, "cli_completion", shared, raising=False)
    answered = []
    original_answer = service.agent_bridge.answer

    def record_answer(*args, **kwargs):
        result = original_answer(*args, **kwargs)
        answered.append(result)
        return result

    monkeypatch.setattr(service.agent_bridge, "answer", record_answer)
    service.configure(**SETTINGS, account_cli_preset_id="fake")
    result = complete(service)
    assert result["value"] == ANSWER, result
    assert [row["state"] for row in answered] == ["ANSWERED"], answered
    rows = service.agent_bridge.list_requests(state="CONSUMED")["requests"]
    assert len(rows) == 1 and rows[0]["run_id"] == result["run_id"], rows
    run = service.get_run(result["run_id"])
    assert run["status"] == "validated" and run["request_sha256"] == rows[0]["request_sha256"], run
    replay = complete(service)
    assert replay["run_id"] == result["run_id"] and replay["status"] == "validated", replay
    assert len(calls) == 1 and calls[0][0] == presets["fake"][1], calls

    # The seat still receives plain stdin/stdout, through that same transport.
    seat_script = script.with_name("fake_seat.py")
    seat_script.write_text("import sys\nprint(sys.stdin.read(), end='')\n")
    argv = [sys.executable, str(seat_script)]
    seat = seat_complete({"kind": "cli", "command": argv, "timeout_s": 3}, "observed actor view")
    assert seat == ("observed actor view", None), seat
    assert calls[1:] == [(argv, "observed actor view")], calls


@pytest.mark.parametrize(("body", "reason"), [
    ("raise SystemExit(1)", "exited without an answer"),
    ("import time; time.sleep(10)", "deadline"),
    ("print('not JSON')", "not one JSON object"),
    ("print('[' * 1500)", "not one JSON object"),
    ("print('{}')", "failed the requested response schema"),
    ("print('x' * 5000000)", "too large"),
])
def test_account_failures_end_the_mailbox_request(account, body, reason):
    service, script, _ = account
    script.write_text(f"import sys\nsys.stdin.read()\n{body}\n")
    service.configure(**SETTINGS, account_cli_preset_id="fake")
    service.agent_wait_override = 1 if "sleep" in body else 3
    started = time.monotonic()
    with pytest.raises(FoundryError) as failure:
        complete(service)
    elapsed = time.monotonic() - started
    error = failure.value
    assert error.code == "AI_AGENT_REQUEST_REJECTED" and reason in error.message, error.to_dict()
    rows = service.agent_bridge.list_requests(state="REJECTED")["requests"]
    assert len(rows) == 1, rows
    rejected = service.agent_bridge.get(rows[0]["request_id"])
    assert reason in rejected["rejection"]["reason"], rejected
    if "sleep" in body:
        assert elapsed < 5, f"one-second CLI deadline took {elapsed:.2f}s"


def test_account_configure_accepts_only_preset_ids_and_advertises_only_installed(account):
    service, _, presets = account
    for field in ("command", "argv"):
        with pytest.raises(TypeError, match=field):
            service.configure(**SETTINGS, **{field: presets["fake"][1]})
        with pytest.raises(ValidationError, match=field):
            AIProviderConfigureRequest(**SETTINGS, **{field: presets["fake"][1]})
    for invalid, expected in (("unknown", "preset"), ("missing", "not installed"), ("credential", "credentials")):
        with pytest.raises(FoundryError) as failure:
            service.configure(**SETTINGS, account_cli_preset_id=invalid)
        assert expected in failure.value.message, failure.value.to_dict()

    request = AIProviderConfigureRequest(**SETTINGS, account_cli_preset_id="fake")
    status = service.configure(**request.model_dump())
    assert status["settings"]["account_cli_preset_id"] == "fake", status["settings"]
    assert status["account_cli_presets"] == [{"id": "fake", "display_name": "Fake account"}], status["account_cli_presets"]

    # An installed executable can disappear after configure (e.g. an upgrade).
    presets["fake"] = presets["missing"]
    with pytest.raises(FoundryError) as failure:
        complete(service)
    error = failure.value
    assert error.code == "AI_PROVIDER_NOT_READY" and error.details["provider_called"] is False, error.to_dict()
    assert "Install it or choose and save a different answer source" in error.message, error.to_dict()
    assert service.agent_bridge.list_requests()["requests"] == []


@pytest.fixture
def creation_build(account, monkeypatch):
    ai, _, _ = account
    project_id = "account-route-project"
    now = utcnow()
    with ai.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               quality_target,project_json,compatibility_projection_status,
               compile_status,consumer_verification_status,contract_status)
               VALUES(?, 'Account probe', 'draft', 0, ?, ?, 'x', 'x', 'x', 'x', '{}', 'x', 'x', 'x', 'x')""",
            (project_id, now, now),
        )
    build = CharacterCreationExecutionService(
        ai.db, stage1=None, provider=ai,
        project_store=SimpleNamespace(get_project=lambda _: {"project_id": project_id, "revision": 0}),
    )

    def synthetic_request(project, revision_request, *, execution_mode, controller_route,
                          combat_ready, provider_selection=None, **kwargs):
        request = {
            "project_id": project, "project_revision": 0, "content_lock_hash": "",
            "execution_mode": execution_mode, "controller_route": controller_route,
            "revision_request": revision_request, "combat_ready": combat_ready,
        }
        if provider_selection is not None:
            request["provider_selection"] = provider_selection
        return {**request, "request_sha256": build.request_payload_sha256(request)}

    monkeypatch.setattr(build, "_complete_request", synthetic_request)
    monkeypatch.setattr(build, "_provider_prompt", lambda run: "Return one JSON object.")
    return build, project_id


@pytest.fixture
def connection_probe(account, monkeypatch):
    ai, _, _ = account
    probes = []
    on_probe = {}

    def provider_call(*, endpoint, request_bytes, **kwargs):
        prompt = json.loads(request_bytes)["messages"][-1]["content"]
        assert prompt == 'Return exactly {"connection":"ok"}.', f"Build dispatched to {endpoint}: {prompt}"
        probes.append(endpoint)
        if endpoint in on_probe:
            on_probe[endpoint]()
        content = json.dumps({"connection": "ok"})
        return 200, json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()

    monkeypatch.setattr(ai, "_provider_call", provider_call)
    return probes, on_probe


@pytest.mark.parametrize(("chosen", "before", "after", "after_preset"), [
    ("local", None, "agent", "fake"),
    ("agent", "fake", "openai", None),
    ("agent", "fake", "agent", "other"),
    ("agent", "fake", "agent", None),
    ("custom", None, "custom", None),
])
def test_creation_build_refuses_a_selection_change_after_preflight(
    account, creation_build, connection_probe, monkeypatch, chosen, before, after, after_preset,
):
    ai, _, presets = account
    build, project_id = creation_build
    presets["other"] = presets["fake"]
    ai.secrets.set("synthetic-key", "openai")
    ai.secrets.set("synthetic-key", "custom")
    first_endpoint = "https://first.example.test/v1/chat/completions"
    second_endpoint = "https://second.example.test/v1/chat/completions"
    ai.configure(
        **{**SETTINGS, "provider_id": chosen}, account_cli_preset_id=before,
        endpoint=("http://127.0.0.1:8000/v1/chat/completions" if chosen == "local"
                  else first_endpoint if chosen == "custom" else None),
    )
    assert ai.test_connection()["status"] == "PASS"
    preflight = ai.status()
    assert preflight["ready"] and preflight["provider_id"] == chosen, preflight

    def prepare_prompt(_run):
        # Here start() has checked readiness, but complete_json() has not
        # taken its dispatch snapshot. This simulates a save from another tab.
        ai.configure(**{**SETTINGS, "provider_id": after}, account_cli_preset_id=after_preset,
                     endpoint=second_endpoint if after == "custom" else None)
        return "This prompt must not reach a different route."

    def unexpected(*args, **kwargs):
        pytest.fail(f"Dispatched after the selected route changed: {after}/{after_preset}")

    monkeypatch.setattr(build, "_provider_prompt", prepare_prompt)
    monkeypatch.setattr(ai, "_provider_call", unexpected)
    monkeypatch.setattr(provider_transport, "cli_completion", unexpected)
    selection = {"provider_id": chosen, "account_cli_preset_id": before}
    if chosen == "custom":
        selection["endpoint"] = preflight["settings"]["endpoint"]
        assert selection["endpoint"] == first_endpoint
    body = CharacterCreationStartRequest(
        execution_mode="STANDARD_API", idempotency_key="bound-route-probe",
        provider_selection=selection,
    )
    result = build.start(project_id, **body.model_dump())
    assert result["execution_mode"] == "MANUAL_CHAT" and result["status"] == "WAITING_FOR_RESPONSE", result
    assert result["transport"]["provider_called"] is False, result["transport"]
    assert result["transport"]["provider_error"]["code"] == "AI_PROVIDER_REQUEST_CHANGED", result["transport"]
    rows = ai.agent_bridge.list_requests()["requests"]
    assert rows == [], rows


@pytest.mark.parametrize("late_probe", [False, True])
def test_creation_refuses_a_restored_custom_endpoint_without_its_own_test(
    account, creation_build, connection_probe, monkeypatch, late_probe,
):
    ai, _, _ = account
    build, project_id = creation_build
    probes, on_probe = connection_probe
    first = "https://first.example.test/v1/chat/completions"
    second = "https://second.example.test/v1/chat/completions"

    def save(endpoint):
        return ai.configure(**{**SETTINGS, "provider_id": "custom"}, endpoint=endpoint)

    ai.secrets.set("synthetic-key", "custom")
    save(first)
    assert ai.test_connection()["status"] == "PASS"
    preflight = ai.status()
    assert preflight["ready"], preflight

    def prepare_prompt(_run):
        save(second)
        if late_probe:
            # B's probe starts on B, but A is restored before B can publish PASS.
            on_probe[second] = lambda: save(first)
            assert ai.test_connection()["status"] == "PASS"
        else:
            save(first)
        return "Do not send this build to an untested endpoint."

    monkeypatch.setattr(build, "_provider_prompt", prepare_prompt)
    result = build.start(
        project_id, execution_mode="STANDARD_API", idempotency_key="restored-custom-probe",
        provider_selection={"provider_id": "custom", "endpoint": preflight["settings"]["endpoint"]},
    )
    assert result["execution_mode"] == "MANUAL_CHAT" and result["status"] == "WAITING_FOR_RESPONSE", result
    assert result["transport"]["provider_called"] is False, result["transport"]
    assert result["transport"]["provider_error"]["code"] == "AI_PROVIDER_NOT_READY", result["transport"]
    current = ai.status()
    assert current["settings"]["endpoint"] == first and not current["ready"], current
    assert probes == ([first, second] if late_probe else [first]), probes
    assert ai.agent_bridge.list_requests()["requests"] == []


@pytest.mark.parametrize("redrive_while_live", [False, True])
def test_creation_redrive_settles_an_interrupted_account_claim(
    account, creation_build, monkeypatch, redrive_while_live,
):
    ai, _, _ = account
    build, project_id = creation_build
    ai.configure(**SETTINGS, account_cli_preset_id="fake")
    args = {"execution_mode": "STANDARD_API", "idempotency_key": "interrupted-account-probe"}

    def stopped_before_dispatch(*args, **kwargs):
        raise KeyboardInterrupt("Factory stopped after reserving the mailbox")

    # Interrupt after the durable reservation, before any reply or status update.
    with monkeypatch.context() as patch:
        patch.setattr(provider_transport, "cli_completion", stopped_before_dispatch)
        with pytest.raises(KeyboardInterrupt, match="after reserving"):
            build.start(project_id, provider_selection={"provider_id": "agent", "account_cli_preset_id": "fake"}, **args)
    with ai.db.connection() as conn:
        run_id = conn.execute("SELECT run_id FROM character_creation_runs").fetchone()["run_id"]
    rows = ai.agent_bridge.list_requests()["requests"]
    assert len(rows) == 1 and rows[0]["state"] == "CLAIMED", rows
    request_id = rows[0]["request_id"]

    def no_redispatch(*args, **kwargs):
        pytest.fail(f"An interrupted request must not dispatch again: {request_id}")

    monkeypatch.setattr(provider_transport, "cli_completion", no_redispatch)
    ai.agent_wait_override = 0
    if redrive_while_live:
        waiting = build.start(project_id, **args)
        assert waiting["status"] == "AWAITING_AGENT_RESPONSE", waiting
        row = ai.agent_bridge.get(request_id)
        assert row["state"] == "CLAIMED" and row["claimed_until"] == rows[0]["claimed_until"], row

    with ai.db.transaction() as conn:
        conn.execute(
            "UPDATE ai_agent_requests SET claimed_until=? WHERE request_id=?",
            ("2000-01-01T00:00:00Z", request_id),
        )
    result = build.start(project_id, **args)
    assert result["run_id"] == run_id and result["execution_mode"] == "MANUAL_CHAT", result
    assert result["status"] == "WAITING_FOR_RESPONSE", result
    assert "interrupted" in result["transport"]["provider_error"]["message"], result["transport"]
    rows = ai.agent_bridge.list_requests()["requests"]
    assert len(rows) == 1 and rows[0]["request_id"] == request_id and rows[0]["state"] == "REJECTED", rows


@pytest.mark.parametrize("interrupt_at,preset", [
    ("provider", "fake"), ("enqueue", "fake"), ("orphan", "fake"), ("enqueue", None),
])
def test_creation_continues_account_build_interrupted_before_enqueue(
    account, creation_build, monkeypatch, interrupt_at, preset,
):
    ai, _, _ = account
    build, project_id = creation_build
    ai.configure(**SETTINGS, account_cli_preset_id=preset)
    if preset is None:
        ai.agent_wait_override = 0
    args = {"execution_mode": "STANDARD_API", "idempotency_key": "before-mailbox-probe"}
    selection = {"provider_id": "agent", "account_cli_preset_id": preset}

    saved_enqueue = {}
    def interrupted(*args, **kwargs):
        saved_enqueue.update(kwargs)
        raise KeyboardInterrupt("Factory stopped before enqueue")

    with monkeypatch.context() as patch:
        target, method = (ai, "complete_json") if interrupt_at == "provider" else (ai.agent_bridge, "enqueue")
        patch.setattr(target, method, interrupted)
        with pytest.raises(KeyboardInterrupt, match="before enqueue"):
            build.start(project_id, provider_selection=selection, **args)

    with ai.db.connection() as conn:
        old = conn.execute("SELECT run_id, status FROM character_creation_runs").fetchone()
        provider_rows = conn.execute("SELECT run_id FROM ai_provider_runs").fetchall()
    assert old["status"] == "PREPARING_REQUEST"
    assert ai.agent_bridge.list_requests()["requests"] == []
    if interrupt_at == "enqueue":
        # A new interruption cannot leave a half-recorded provider run.
        assert provider_rows == []
    if interrupt_at == "orphan" and not provider_rows:
        # Represent the already-recorded orphan left by the old code.
        ai._insert_json_run(
            prompt_id=saved_enqueue["prompt_id"], idempotency_key=saved_enqueue["idempotency_key"],
            settings=ai._settings(), request_bytes=canonical_json(saved_enqueue["request_payload"]).encode(),
            started_at=utcnow(), project_id=saved_enqueue["project_id"] or None,
        )
        with ai.db.connection() as conn:
            provider_rows = conn.execute("SELECT run_id FROM ai_provider_runs").fetchall()
    assert len(provider_rows) == (interrupt_at == "orphan")

    calls = []
    def answer(argv, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(ANSWER)

    monkeypatch.setattr(provider_transport, "cli_completion", answer)
    parsed = CharacterCreationStartRequest(provider_selection=selection, **args).model_dump()
    continued = build.start(project_id, **parsed)
    assert continued["run_id"] == old["run_id"]
    assert continued["status"] == ("AWAITING_AGENT_RESPONSE" if preset is None else "NEEDS_REVIEW"), continued
    assert continued["transport"]["provider_called"] is (preset is not None), continued
    rows = ai.agent_bridge.list_requests()["requests"]
    assert len(rows) == 1 and rows[0]["state"] == ("PENDING" if preset is None else "CONSUMED"), rows
    if saved_enqueue.get("idempotency_key"):
        assert rows[0]["idempotency_key"] == saved_enqueue["idempotency_key"], rows
    assert len(calls) == (0 if preset is None else 1), calls
    if provider_rows:
        assert rows[0]["run_id"] == provider_rows[0]["run_id"]
    again = build.start(project_id, **parsed)
    assert again["run_id"] == old["run_id"]
    assert again["status"] == continued["status"], again
    repeated_rows = ai.agent_bridge.list_requests()["requests"]
    assert [row["request_id"] for row in repeated_rows] == [rows[0]["request_id"]], repeated_rows
    assert len(calls) == (0 if preset is None else 1), calls


def test_creation_continues_an_account_answer_without_its_executable(
    account, creation_build, monkeypatch,
):
    ai, _, presets = account
    build, project_id = creation_build
    ai.configure(**SETTINGS, account_cli_preset_id="fake")
    args = {"execution_mode": "STANDARD_API", "idempotency_key": "answer-saved-probe"}
    selection = {"provider_id": "agent", "account_cli_preset_id": "fake"}

    def no_launch(*args, **kwargs):
        pytest.fail("Continue tried to launch a new CLI for an answer already on disk.")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("Factory stopped before applying the answer")

    with monkeypatch.context() as patch:
        patch.setattr(provider_transport, "cli_completion", lambda *args, **kwargs: json.dumps(ANSWER))
        patch.setattr(ai, "_complete_answered_request", interrupted)
        with pytest.raises(KeyboardInterrupt, match="before applying"):
            build.start(project_id, provider_selection=selection, **args)

    with ai.db.connection() as conn:
        old = conn.execute("SELECT run_id, status FROM character_creation_runs").fetchone()
    assert old["status"] == "PREPARING_REQUEST", dict(old)
    rows = ai.agent_bridge.list_requests()["requests"]
    assert len(rows) == 1 and rows[0]["state"] == "ANSWERED", rows
    request_id = rows[0]["request_id"]
    presets["fake"] = presets["missing"]
    assert ai.status()["readiness_state"] == "ACCOUNT_CLI_UNAVAILABLE"
    monkeypatch.setattr(provider_transport, "cli_completion", no_launch)

    for _ in range(2):
        continued = build.start(project_id, provider_selection=selection, **args)
        assert continued["run_id"] == old["run_id"] and continued["status"] == "NEEDS_REVIEW", continued
        assert continued["execution_mode"] == "STANDARD_API" and continued["transport"]["provider_called"] is True, continued
        rows = ai.agent_bridge.list_requests()["requests"]
        assert len(rows) == 1 and rows[0]["request_id"] == request_id and rows[0]["state"] == "CONSUMED", rows


@pytest.mark.skipif(os.environ.get("CF_CREATEROUTE_BROWSER") != "1", reason="opt-in browser check")
def test_browser_snapshots_custom_endpoint_before_catalog_lock():
    from playwright.sync_api import sync_playwright

    source = (Path(__file__).resolve().parents[1] / "static/app.js").read_text()
    start = source.index("async function startGuidedCompleteBuild()")
    end = source.index("\ndocument.querySelectorAll('input[name=\"guidedExecutionMode\"]')", start)
    function = source[start:end]
    script = """async () => {
      let guidedProjectId = "project", guidedSelectedRoute = "STANDARD_API", guidedRun = null;
      let guidedResponseSubmissionAction, captured;
      const provider = {provider_id: "custom", ready: true,
                        settings: {endpoint: "https://first.example.test/v1/chat/completions"}};
      const resumableGuidedAccountBuild = () => null;
      const guidedExecutionMode = () => "STANDARD_API", guidedUsesController = () => false;
      const guidedProviderProfile = () => "custom", setGuidedStatus = () => {};
      const startGuidedAIWorking = () => {}, stopGuidedAIWorking = () => {};
      const plainAPIError = () => "stopped";
      const api = async (url, options) => {
        if (url === "/api/ai-provider") return provider;
        if (url.endsWith("normal-first-cycle-catalog-choice-lock")) {
          provider.settings.endpoint = "https://second.example.test/v1/chat/completions";
          return {};
        }
        captured = JSON.parse(options.body);
        throw new Error("stop after observing the build request");
      };
      """ + function + """
      await startGuidedCompleteBuild();
      return captured;
    }"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.set_content('<button id="guidedStartBuild"></button>')
            result = page.evaluate(script)
        finally:
            browser.close()
    assert result["provider_selection"]["endpoint"] == "https://first.example.test/v1/chat/completions"


def test_api_setup_is_not_inside_advanced_disclosure():
    html = (Path(__file__).resolve().parents[1] / "static/index.html").read_text()
    setup = html.index("<section id=\"guidedProviderSetup\"")
    advanced = html.index("<details id=\"guidedAdvancedAIOptions\"")
    assert setup < advanced, f"API setup at {setup}, advanced disclosure at {advanced}"


def test_three_creation_ai_routes_are_peers_and_agent_is_not_an_api_profile():
    html = (Path(__file__).resolve().parents[1] / "static/index.html").read_text()
    tabs = re.search(r'id="guidedModeChoices"[^>]*>(.*?)</div>', html, re.S)
    assert tabs is not None, "No guided route tab list found"
    labels = re.findall(r'role="tab"[^>]*><strong>(.*?)</strong>', tabs[1])
    assert labels == ["Local models", "API key", "Account login (OAuth)", "Manual Chat"], labels
    profile = re.search(r'<select id="guidedProviderProfile">(.*?)</select>', html, re.S)
    assert profile is not None and 'value="agent"' not in profile[1], profile[1] if profile else "No API profile select"
