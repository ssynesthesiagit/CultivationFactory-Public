"""A concurrent unique-key winner must satisfy the same exact-request check."""
import json

import httpx
import pytest

from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AGENT_PROVIDER_ID, AIProviderService
from app.core import FoundryError, canonical_json, sha256_bytes, utcnow


def service(db):
    def no_network(request):
        pytest.fail("an agent idempotency check must not call a provider")

    obj = AIProviderService(db, secret_store=InMemorySecretStore(), transport=httpx.MockTransport(no_network))
    obj.configure(enabled=True, provider_id=AGENT_PROVIDER_ID, endpoint=None, model="agent-authored",
                  thinking_mode="disabled", max_output_tokens=16384, timeout_seconds=120,
                  data_sharing_acknowledged=True, acknowledged_by="synthetic test", agent_wait_seconds=30)
    obj.agent_wait_override = 0
    return obj


@pytest.mark.parametrize("different_bytes", [False, True])
@pytest.mark.parametrize("winner_status", ["validated", "started"])
def test_concurrent_run_winner_is_rechecked_before_resume(fresh_db, monkeypatch, different_bytes, winner_status):
    provider = service(fresh_db)
    reserve = provider._complete_json_via_agent
    winner = {}

    def another_request_wins(**kwargs):
        # complete_json has already observed no existing row, and this caller's
        # atomic run reservation has not opened yet: the window a real
        # concurrent caller commits in, on its own connection. This caller's
        # INSERT then reaches the actual SQLite unique-key conflict.
        assert not winner
        request = json.loads(kwargs["request_bytes"])
        if different_bytes:
            request["messages"][1]["content"] = "A different requested character."
        wire = canonical_json(request).encode()
        winner["id"] = provider._insert_json_run(
            prompt_id=kwargs["purpose"], idempotency_key=kwargs["caller_key"], settings=kwargs["settings"],
            request_bytes=wire, started_at=utcnow(), project_id=kwargs["project_id"])
        winner["hash"] = sha256_bytes(wire)
        provider._update_run(winner["id"], status=winner_status)
        return reserve(**kwargs)

    monkeypatch.setattr(provider, "_complete_json_via_agent", another_request_wins)
    kwargs = dict(prompt_text="The requested character.", system_message="Return JSON.",
                  purpose="audit_idempotency_boundary", idempotency_key="synthetic.shared.step")
    if different_bytes:
        with pytest.raises(FoundryError) as raised:
            provider.complete_json(**kwargs)
        assert raised.value.code == "AI_PROVIDER_REQUEST_CHANGED"
        assert raised.value.details["run_id"] == winner["id"]
        assert raised.value.details["recorded_request_sha256"] == winner["hash"]
        assert raised.value.details["actual_request_sha256"] != winner["hash"]
        assert raised.value.details["provider_called"] is False
    else:
        replay = provider.complete_json(**kwargs)
        assert replay["run_id"] == winner["id"]
        assert replay["request_sha256"] == winner["hash"]
        assert replay["status"] == winner_status
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_provider_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ai_agent_requests").fetchone()[0] == 0
