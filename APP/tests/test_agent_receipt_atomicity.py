"""An answered mailbox and its provider receipt have one transaction owner."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core import FoundryError
from test_provider_idempotency_race import service


PURPOSE = "synthetic_atomic_receipt"
KEY = "synthetic.atomic.step"


def call(provider, key=KEY):
    return provider.complete_json(prompt_text="Name a synthetic character.", system_message="Return JSON.",
                                  purpose=PURPOSE, idempotency_key=key)


def answered(provider, key=KEY):
    with pytest.raises(FoundryError) as parked:
        call(provider, key)
    assert parked.value.code == "AI_AGENT_AWAITING_RESPONSE"
    request_id = parked.value.details["request_id"]
    request = provider.agent_bridge.get(request_id)
    provider.agent_bridge.claim(request_id, agent_id="synthetic", lease_seconds=60)
    return provider.agent_bridge.answer(
        request_id, agent_id="synthetic", agent_model="local-probe",
        request_sha256=request["request_sha256"], response_text='{"name":"Synthetic"}',
        validator=lambda parsed: [],
    )


class CompletionStopped(BaseException):
    pass


@pytest.mark.parametrize("after_update", [False, True])
@pytest.mark.parametrize("failure_type", [RuntimeError, CompletionStopped])
def test_receipt_failure_rolls_back_consumption_and_retry_uses_same_answer(fresh_db, monkeypatch, after_update, failure_type):
    provider = service(fresh_db)
    request = answered(provider)
    update = provider._update_run

    def interrupted(*args, **kwargs):
        if after_update:
            update(*args, **kwargs)
        raise failure_type("synthetic completion interruption")

    monkeypatch.setattr(provider, "_update_run", interrupted)
    with pytest.raises(failure_type):
        call(provider)
    assert provider.agent_bridge.get(request["request_id"])["state"] == "ANSWERED"
    failed = provider.get_run(request["run_id"])
    assert failed["status"] == "started" and failed["provider_response_sha256"] is None
    monkeypatch.setattr(provider, "_update_run", update)
    result = call(provider)
    assert result["value"] == {"name": "Synthetic"}
    receipt = provider.get_run(request["run_id"])
    assert receipt["status"] == "validated"
    assert receipt["provider_response_sha256"] == result["response_sha256"]
    assert provider.agent_bridge.get(request["request_id"])["state"] == "CONSUMED"
    assert call(provider)["provider_response_sha256"] == receipt["provider_response_sha256"]
    assert provider.get_run(request["run_id"]) == receipt
    assert len(provider.agent_bridge.list_requests()["requests"]) == 1


def test_historical_consumed_answer_can_finish_its_exact_unfinished_run(fresh_db):
    provider = service(fresh_db)
    request = answered(provider)
    provider.agent_bridge.consume(request["request_id"], run_id=request["run_id"])
    assert provider.get_run(request["run_id"])["status"] == "started"
    result = call(provider)
    assert result["value"] == {"name": "Synthetic"}
    assert provider.get_run(request["run_id"])["status"] == "validated"
    assert len(provider.agent_bridge.list_requests()["requests"]) == 1


@pytest.mark.parametrize("consumed", [False, True])
def test_consumption_refuses_a_different_run_even_on_replay(fresh_db, consumed):
    provider = service(fresh_db)
    request = answered(provider)
    if consumed:
        provider.agent_bridge.consume(request["request_id"], run_id=request["run_id"])
    before = provider.agent_bridge.get(request["request_id"])
    with pytest.raises(FoundryError) as denied:
        provider.agent_bridge.consume(request["request_id"], run_id="another.run")
    assert denied.value.code == "AI_AGENT_REQUEST_NOT_CONSUMABLE"
    assert provider.agent_bridge.get(request["request_id"]) == before


@pytest.mark.parametrize("consumed", [False, True])
def test_same_bytes_in_a_different_request_cannot_complete_this_run(fresh_db, monkeypatch, consumed):
    provider = service(fresh_db)
    first = answered(provider)
    other = answered(provider, "synthetic.other.step")
    assert first["request_sha256"] == other["request_sha256"]
    if consumed:
        provider.agent_bridge.consume(other["request_id"], run_id=other["run_id"])
    unrelated = provider.agent_bridge.get(other["request_id"])
    monkeypatch.setattr(provider.agent_bridge, "find_latest", lambda **kwargs: unrelated)
    with pytest.raises(FoundryError) as denied:
        call(provider)
    assert denied.value.code == "AI_AGENT_REQUEST_NOT_CONSUMABLE"
    assert provider.get_run(first["run_id"])["status"] == "started"
    assert provider.get_run(other["run_id"])["status"] == "started"
    assert provider.agent_bridge.get(first["request_id"])["state"] == "ANSWERED"
    assert provider.agent_bridge.get(other["request_id"]) == unrelated


def test_changed_mailbox_request_hash_cannot_consume_or_record_receipt(fresh_db):
    provider = service(fresh_db)
    request = answered(provider)
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE ai_agent_requests SET request_sha256=? WHERE request_id=?", ("0" * 64, request["request_id"]))
    with pytest.raises(FoundryError) as denied:
        call(provider)
    assert denied.value.code == "AI_PROVIDER_REQUEST_CHANGED"
    assert provider.agent_bridge.get(request["request_id"])["state"] == "ANSWERED"
    assert provider.get_run(request["run_id"])["status"] == "started"


def test_competing_completions_write_one_receipt(fresh_db, monkeypatch):
    provider = service(fresh_db)
    request = answered(provider)
    barrier = threading.Barrier(2)
    complete = provider._complete_answered_request
    update = provider._update_run
    writes = []

    def aligned_completion(**kwargs):
        barrier.wait(timeout=10)
        return complete(**kwargs)

    def counted_update(*args, **kwargs):
        writes.append(args[0])
        return update(*args, **kwargs)

    monkeypatch.setattr(provider, "_complete_answered_request", aligned_completion)
    monkeypatch.setattr(provider, "_update_run", counted_update)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, provider) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert writes == [request["run_id"]]
    assert {result["run_id"] for result in results} == {request["run_id"]}
    receipt = provider.get_run(request["run_id"])
    assert receipt["status"] == "validated"
    assert provider.agent_bridge.get(request["request_id"])["state"] == "CONSUMED"
    replay = next(result for result in results if result.get("idempotent"))
    assert replay["provider_response_sha256"] == receipt["provider_response_sha256"]
    assert "value" not in replay  # preserve the existing terminal-receipt shape


def test_waiter_observes_an_answer_already_consumed_by_the_other_completion(fresh_db):
    provider = service(fresh_db)
    request = answered(provider)
    call(provider)
    observed = provider.agent_bridge.wait_for_answer(request["request_id"], wait_seconds=0)
    assert observed["state"] == "CONSUMED"
    assert observed["run_id"] == request["run_id"]


def test_helpers_leave_the_callers_connection_and_transaction_owned_by_the_caller(fresh_db):
    provider = service(fresh_db)
    request = answered(provider)
    with pytest.raises(RuntimeError, match="caller rollback"):
        with fresh_db.transaction() as conn:
            provider.agent_bridge.consume(request["request_id"], run_id=request["run_id"], conn=conn)
            provider._update_run(request["run_id"], status="validated", conn=conn)
            assert conn.in_transaction
            assert conn.execute("SELECT state FROM ai_agent_requests").fetchone()[0] == "CONSUMED"
            raise RuntimeError("caller rollback")
    assert provider.agent_bridge.get(request["request_id"])["state"] == "ANSWERED"
    assert provider.get_run(request["run_id"])["status"] == "started"


@pytest.mark.parametrize("field,value", [("response_text", '{"name":"Changed"}'), ("agent_model", "different-model")])
def test_stale_answer_snapshot_cannot_replace_the_stored_answer(fresh_db, monkeypatch, field, value):
    provider = service(fresh_db)
    request = answered(provider)
    original_wait = provider.agent_bridge.wait_for_answer

    def changed_snapshot(*args, **kwargs):
        return {**original_wait(*args, **kwargs), field: value}

    monkeypatch.setattr(provider.agent_bridge, "wait_for_answer", changed_snapshot)
    with pytest.raises(FoundryError) as denied:
        call(provider)
    assert denied.value.code == "AI_AGENT_REQUEST_NOT_CONSUMABLE"
    assert provider.agent_bridge.get(request["request_id"])["state"] == "ANSWERED"
    assert provider.get_run(request["run_id"])["status"] == "started"


def test_historical_consumed_answer_requires_its_exact_recorded_content_hash(fresh_db):
    provider = service(fresh_db)
    request = answered(provider)
    provider.agent_bridge.consume(request["request_id"], run_id=request["run_id"])
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE ai_agent_requests SET response_sha256=? WHERE request_id=?", ("0" * 64, request["request_id"]))
    with pytest.raises(FoundryError) as denied:
        call(provider)
    assert denied.value.code == "AI_AGENT_REQUEST_NOT_CONSUMABLE"
    assert provider.get_run(request["run_id"])["status"] == "started"
