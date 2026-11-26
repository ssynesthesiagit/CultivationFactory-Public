"""Character creation through an installed account CLI, without a real login."""
import json
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
from app.core import FoundryError, utcnow
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
    assert failure.value.code == "AI_AGENT_REQUEST_REJECTED" and "not installed" in failure.value.message, failure.value.to_dict()


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


@pytest.mark.parametrize(("chosen", "before", "after", "after_preset"), [
    ("local", None, "agent", "fake"),
    ("agent", "fake", "openai", None),
    ("agent", "fake", "agent", "other"),
    ("agent", "fake", "agent", None),
])
def test_creation_build_refuses_a_selection_change_after_preflight(
    account, creation_build, monkeypatch, chosen, before, after, after_preset,
):
    ai, _, presets = account
    build, project_id = creation_build
    presets["other"] = presets["fake"]
    ai.secrets.set("synthetic-key", "openai")
    ai.configure(
        **{**SETTINGS, "provider_id": chosen}, account_cli_preset_id=before,
        endpoint="http://127.0.0.1:8000/v1/chat/completions" if chosen == "local" else None,
    )
    ai._connection_test = {"status": "PASS"}
    preflight = ai.status()
    assert preflight["ready"] and preflight["provider_id"] == chosen, preflight

    def prepare_prompt(_run):
        # Here start() has checked readiness, but complete_json() has not
        # taken its dispatch snapshot. This simulates a save from another tab.
        ai.configure(**{**SETTINGS, "provider_id": after}, account_cli_preset_id=after_preset)
        return "This prompt must not reach a different route."

    def unexpected(*args, **kwargs):
        pytest.fail(f"Dispatched after the selected route changed: {after}/{after_preset}")

    monkeypatch.setattr(build, "_provider_prompt", prepare_prompt)
    monkeypatch.setattr(ai, "_provider_call", unexpected)
    monkeypatch.setattr(provider_transport, "cli_completion", unexpected)
    body = CharacterCreationStartRequest(
        execution_mode="STANDARD_API", idempotency_key="bound-route-probe",
        provider_selection={"provider_id": chosen, "account_cli_preset_id": before},
    )
    result = build.start(project_id, **body.model_dump())
    assert result["execution_mode"] == "MANUAL_CHAT" and result["status"] == "WAITING_FOR_RESPONSE", result
    assert result["transport"]["provider_called"] is False, result["transport"]
    assert result["transport"]["provider_error"]["code"] == "AI_PROVIDER_REQUEST_CHANGED", result["transport"]
    rows = ai.agent_bridge.list_requests()["requests"]
    assert rows == [], rows


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
