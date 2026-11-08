"""Synthetic transport boundaries; no sockets, model clients or real CLIs."""
import io
import json
import urllib.error
import urllib.request

import httpx
import pytest

from agent_seats import d1
from agent_seats.providers import complete
from ai_provider.service import AIProviderService, MAX_PROVIDER_RESPONSE_BYTES
from app.core import FoundryError


@pytest.mark.parametrize("excess", [-1, 0, 1])
def test_creation_stream_limit_stops_early_and_closes(fresh_db, excess):
    class Stream(httpx.SyncByteStream):
        def __init__(self):
            self.reads = 0
            self.closed = False

        def __iter__(self):
            for chunk in (b"x" * (MAX_PROVIDER_RESPONSE_BYTES - 2), b"x" * (2 + excess)):
                self.reads += 1
                yield chunk
            if excess > 0:
                pytest.fail("The transport consumed another chunk after overflowing.")

        def close(self):
            self.closed = True

    stream = Stream()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)

    service = AIProviderService(fresh_db, transport=httpx.MockTransport(handler))
    arguments = dict(endpoint="https://unit.test/completion", key=None,
                     request_bytes=b"{}", timeout_seconds=3)
    if excess > 0:
        with pytest.raises(FoundryError) as error:
            service._provider_call(**arguments)
        assert error.value.to_dict() == {"error": {
            "code": "AI_PROVIDER_RESPONSE_TOO_LARGE",
            "message": "The provider response exceeded the 4 MiB audit limit.",
            "details": None,
        }}
    else:
        status, body = service._provider_call(**arguments)
        assert status == 200
        assert body == b"x" * (MAX_PROVIDER_RESPONSE_BYTES + excess)
    assert len(calls) == 1
    assert stream.reads == 2 and stream.closed


@pytest.mark.parametrize("protocol", ["chat", "d1"])
@pytest.mark.parametrize("case", ["exact-limit", "oversize", "malformed"])
def test_seat_json_bounds_and_decode_errors_close_before_return(monkeypatch, protocol, case):
    expected = {"choices": [{"message": {"content": "A"}}], "usage": {"total_tokens": 7}}
    encoded = json.dumps(expected).encode()
    limit = 1024 * 1024
    raw = b"not json" if case == "malformed" else encoded + b" " * (
        limit - len(encoded) + (case == "oversize")
    )
    reads, calls = [], []

    class Response(io.BytesIO):
        def read(self, size):
            reads.append(size)
            return super().read(size)

    response = Response(raw)

    def open_response(request, timeout):
        calls.append((request, timeout))
        return response

    monkeypatch.setattr(urllib.request, "urlopen", open_response)

    def invoke():
        if protocol == "d1":
            return d1._read(urllib.request.Request("http://unit.test/decide"), 2)
        return complete({"kind": "openai_compatible", "base_url": "http://unit.test",
                         "model": "fake", "timeout_s": 2}, "prompt")

    if case == "oversize":
        with pytest.raises(ValueError) as error:
            invoke()
        assert str(error.value) == (
            "Decision reply is too large." if protocol == "d1" else "Provider reply is too large."
        )
    elif case == "malformed":
        with pytest.raises(json.JSONDecodeError):
            invoke()
    else:
        result = invoke()
        assert result == (expected if protocol == "d1" else ("A", {"total_tokens": 7}))
    assert response.closed
    assert reads == [limit + 1]
    assert len(calls) == 1 and calls[0][1] == 2


@pytest.mark.parametrize("protocol", ["chat", "d1"])
@pytest.mark.parametrize("failure", [
    TimeoutError("synthetic deadline"),
    urllib.error.URLError("synthetic connection failure"),
    urllib.error.HTTPError("http://unit.test", 403, "Forbidden", {}, None),
])
def test_seat_transport_errors_propagate_without_retry(monkeypatch, protocol, failure):
    calls = []

    def fail(request, timeout):
        calls.append((request, timeout))
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(type(failure)) as error:
        if protocol == "d1":
            d1._read(urllib.request.Request("http://unit.test/decide"), 2)
        else:
            complete({"kind": "openai_compatible", "base_url": "http://unit.test",
                      "model": "fake", "timeout_s": 2}, "prompt")
    assert error.value is failure
    assert len(calls) == 1 and calls[0][1] == 2


@pytest.mark.parametrize("failure_type", [None, httpx.ReadTimeout, httpx.ConnectError])
def test_creation_egress_deadline_and_redacted_network_error(fresh_db, monkeypatch, failure_type):
    client_options, requests = [], []
    real_client = httpx.Client
    failure = failure_type("synthetic-private-diagnostic") if failure_type else None

    def client(**kwargs):
        client_options.append(kwargs)
        return real_client(**kwargs)

    def handler(request):
        requests.append(request)
        if failure:
            raise failure
        return httpx.Response(307, headers={"Location": "https://other.test/completion"},
                              content=b"redirect body")

    # Invalid environment proxies must not replace creation's explicit transport.
    monkeypatch.setenv("HTTPS_PROXY", "http://unused-proxy.test:9999")
    monkeypatch.setattr(httpx, "Client", client)
    transport = httpx.MockTransport(handler)
    service = AIProviderService(fresh_db, transport=transport)
    arguments = dict(endpoint="https://unit.test/completion", key="synthetic-secret",
                     request_bytes=b'{"request":true}', timeout_seconds=3)
    if failure:
        with pytest.raises(FoundryError) as error:
            service._provider_call(**arguments)
        assert error.value.code == "AI_PROVIDER_NETWORK_ERROR"
        assert error.value.status_code == 502
        assert error.value.details == {"exception_type": failure_type.__name__}
        assert error.value.__cause__ is failure
        assert "synthetic" not in json.dumps(error.value.to_dict())
    else:
        assert service._provider_call(**arguments) == (307, b"redirect body")
    assert len(requests) == 1
    assert str(requests[0].url) == arguments["endpoint"]
    assert requests[0].content == arguments["request_bytes"]
    assert requests[0].headers["Authorization"] == "Bearer synthetic-secret"
    assert requests[0].extensions["timeout"] == {
        "connect": 3, "read": 3, "write": 3, "pool": 3,
    }
    assert len(client_options) == 1
    assert client_options[0]["transport"] is transport
    assert client_options[0]["follow_redirects"] is False
    assert client_options[0]["trust_env"] is False
