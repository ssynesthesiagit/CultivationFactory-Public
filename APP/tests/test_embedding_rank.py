"""Embedding option ranking: order, cache, validation and fallback (fake transport only)."""

from __future__ import annotations

import json

import pytest

from combat import embedding_rank as er


def _vector(seed: int) -> list[float]:
    values = [0.0] * er.DIMENSION
    values[seed % er.DIMENSION] = 1.0
    values[(seed * 7 + 3) % er.DIMENSION] = 0.5
    return values


def _fake_transport(vector_for, calls):
    def transport(url, body, timeout):
        request = json.loads(body)
        calls.append(request["input"])
        data = [{"index": i, "embedding": vector_for(text)} for i, text in enumerate(request["input"])]
        return json.dumps({"data": data}).encode("utf-8")
    return transport


def _seeded(text: str) -> list[float]:
    return _vector(sum(map(ord, text)))


OPTIONS = [("A", "strike the nearest foe"), ("B", "raise a shield"), ("C", "climb the wall")]


def test_no_provider_orders_by_similarity_and_keeps_source_order_on_ties():
    client = er.EmbeddingClient(transport=_fake_transport(lambda t: [1.0] + [0.0] * (er.DIMENSION - 1), []))
    assert er.rank_options("q", OPTIONS, client=client) == ["A", "B", "C"]


def test_tactical_tier_decides_before_similarity():
    client = er.EmbeddingClient(transport=_fake_transport(_seeded, []))
    stub = lambda options: {"C": 2, "A": 0, "B": 1}
    assert er.rank_options("q", OPTIONS, client=client, tactical_provider=stub) == ["C", "B", "A"]


def test_cache_hit_avoids_network_and_repeats_identically():
    calls: list = []
    client = er.EmbeddingClient(transport=_fake_transport(_seeded, calls))
    first = er.rank_options("q", OPTIONS, client=client)
    second = er.rank_options("q", OPTIONS, client=client)
    assert first == second
    assert len(calls) == 1 and len(calls[0]) == 4


def test_service_down_returns_original_order():
    def down(url, body, timeout):
        raise OSError("connection refused")
    client = er.EmbeddingClient(transport=down)
    assert er.rank_options("q", OPTIONS, client=client) == ["A", "B", "C"]


def test_deadline_overrun_returns_original_order():
    clock = iter([0.0, 0.0, 0.0, 0.5])
    client = er.EmbeddingClient(transport=_fake_transport(_seeded, []), deadline_s=0.3, clock=lambda: next(clock))
    assert er.rank_options("q", OPTIONS, client=client) == ["A", "B", "C"]


@pytest.mark.parametrize("payload", [
    b"not json",
    json.dumps({"data": [{"index": 0, "embedding": _vector(1)}]}).encode(),
    json.dumps({"data": [{"index": 9, "embedding": _vector(1)}] * 4}).encode(),
    json.dumps({"data": [{"index": i, "embedding": [0.0] * er.DIMENSION} for i in range(4)]}).encode(),
    json.dumps({"data": [{"index": i, "embedding": [float("nan")] + [0.0] * (er.DIMENSION - 1)} for i in range(4)]}).encode(),
])
def test_malformed_response_returns_original_order(payload):
    client = er.EmbeddingClient(transport=lambda url, body, timeout: payload)
    assert er.rank_options("q", OPTIONS, client=client) == ["A", "B", "C"]


def test_response_is_bound_by_index_not_position():
    texts = ["x", "y"]
    reply = {"data": [{"index": 1, "embedding": _vector(5)}, {"index": 0, "embedding": _vector(9)}]}
    vectors = er.validate_response(texts, json.dumps(reply).encode())
    assert vectors[0] == [float(v) for v in _vector(9)]
    assert vectors[1] == [float(v) for v in _vector(5)]


def test_single_option_and_empty_menus_are_unchanged():
    client = er.EmbeddingClient(transport=lambda url, body, timeout: pytest.fail("no network"))
    assert er.rank_options("q", [("A", "only")], client=client) == ["A"]
    assert er.rank_options("q", [], client=client) == []


def test_perceived_text_is_the_only_payload_text():
    calls: list = []
    client = er.EmbeddingClient(transport=_fake_transport(_seeded, calls))
    er.rank_options("query", [("A", "perceived one"), ("B", "perceived two")], client=client)
    assert all(text.startswith("task: sentence similarity | query: ") for text in calls[0])
    assert "hidden" not in json.dumps(calls)


def test_batch_larger_than_cache_and_duplicate_inputs_are_safe():
    calls = []
    client = er.EmbeddingClient(transport=_fake_transport(_seeded, calls), cache_limit=1)
    vectors = client.embed(["x", "y", "x"])
    assert len(vectors) == 3 and vectors[0] == vectors[2]
    assert len(calls[0]) == 2 and len(client._cache) == 1


@pytest.mark.parametrize("args,expected", [
    (["-ngl", "0", "--device", "none"], 42),
    (["--n-gpu-layers=0", "--no-op-offload"], 42),
    (["-ngl", "0"], None),
    (["-ngl", "99", "--device", "none"], None),
])
def test_cpu_guard_requires_listener_ownership_and_disabled_offload(tmp_path, args, expected):
    (tmp_path / "net").mkdir()
    (tmp_path / "net/tcp").write_text("header\n0: 0100007F:2CB8 00000000:0000 0A 0 0 0 0 0 123\n")
    (tmp_path / "net/tcp6").write_text("header\n")
    process = tmp_path / "42"
    (process / "fd").mkdir(parents=True)
    (process / "cmdline").write_bytes("\0".join(["/usr/bin/llama-server", *args]).encode() + b"\0")
    (process / "fd/3").symlink_to("socket:[123]")
    assert er.cpu_server_pid(tmp_path) == expected
    (process / "fd/3").unlink()
    assert er.cpu_server_pid(tmp_path) is None


def test_request_safety_check_consumes_the_same_menu_budget():
    now = [0.0]
    calls = []
    def guard():
        now[0] = 0.12
        return True
    client = er.EmbeddingClient(deadline_s=0.15, clock=lambda: now[0], before_request=guard,
        transport=lambda url, body, timeout: calls.append(timeout) or
            _fake_transport(_seeded, [])(url, body, timeout))
    client.embed(["q", "strike"])
    assert calls == [pytest.approx(0.03)]


def test_invalid_response_counts_as_request_failure():
    results = []
    client = er.EmbeddingClient(transport=lambda *a: b"invalid", request_result=results.append)
    assert er.rank_options("q", OPTIONS, client=client) == ["A", "B", "C"]
    assert results == [False]


def test_trickling_transport_cannot_block_menu_or_start_overlapping_requests():
    import threading
    import time
    finish, exited = threading.Event(), threading.Event()
    calls = []
    def slow(*args):
        calls.append(args)
        try:
            finish.wait(2)
            return b"response"
        finally:
            exited.set()
    transport = er.BoundedTransport(slow)
    start = time.monotonic()
    try:
        with pytest.raises(er.EmbeddingError, match="budget"):
            transport("fake", b"body", 0.02)
        assert time.monotonic() - start < 0.5
        with pytest.raises(er.EmbeddingError, match="in flight"):
            transport("fake", b"body", 0.02)
        assert len(calls) == 1
    finally:
        finish.set()
        assert exited.wait(2)
