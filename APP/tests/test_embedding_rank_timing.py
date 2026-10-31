"""Timing-tool safety only: all transport, CPU detection and time are faked."""
import json
import pytest

from tools import embedding_rank_timing as timing


def test_timing_transport_caps_batches_and_rate_without_live_requests(monkeypatch):
    now, starts = [0.0], []
    monkeypatch.setattr(timing.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(timing.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    def post(url, body, timeout):
        starts.append(now[0])
        texts = json.loads(body)["input"]
        return json.dumps({"data": [{"index": i, "embedding": [1] + [0] * 767}
                                   for i in range(len(texts))]}).encode()
    monkeypatch.setattr(timing.er, "_post", post)
    transport = timing.CappedTransport(2)
    body = json.dumps({"input": ["one", "two"]}).encode()
    transport("fake", body, 0.15)
    transport("fake", body, 0.15)
    with pytest.raises(timing.er.EmbeddingError, match="cap"):
        transport("fake", body, 0.15)
    assert starts == [0, pytest.approx(0.2)]
    assert transport.requests == transport.successes == 2
    assert timing.CappedTransport(1000).cap == 200


def test_timing_transport_stops_after_first_invalid_response(monkeypatch):
    calls = []
    monkeypatch.setattr(timing.er, "_post", lambda *a: calls.append(a) or b"invalid")
    transport = timing.CappedTransport(10)
    body = json.dumps({"input": ["one"]}).encode()
    with pytest.raises(timing.er.EmbeddingError):
        transport("fake", body, 0.15)
    with pytest.raises(timing.er.EmbeddingError):
        transport("fake", body, 0.15)
    assert len(calls) == 1 and transport.requests == 1 and transport.successes == 0


def test_timing_tool_refuses_unverified_cpu_before_any_request(monkeypatch, capsys):
    monkeypatch.setattr(timing.sys, "argv", ["timing", "--allow-live"])
    monkeypatch.setattr(timing.er, "cpu_server_pid", lambda: None)
    monkeypatch.setattr(timing.er, "_post", lambda *a: pytest.fail("no live request permitted"))
    with pytest.raises(SystemExit) as error:
        timing.main()
    assert error.value.code == 2
    assert "requests=0" in capsys.readouterr().out
