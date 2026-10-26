"""Menu presentation ranking (EMBEDMENU, owner 2026-10-13): tactical tier,
then EmbeddingGemma fit; graceful fallback when the service is down or slow.
"""
import json
import socket
import time

import pytest

from combat import embedding_rank as er
from combat import menu_rank


def _fake_transport(vector_for):
    def transport(url, body, timeout):
        request = json.loads(body)
        data = [{"index": i, "embedding": vector_for(text)} for i, text in enumerate(request["input"])]
        return json.dumps({"data": data}).encode("utf-8")
    return transport


def _seeded_vector(text: str) -> list[float]:
    seed = sum(map(ord, text))
    values = [0.0] * er.DIMENSION
    values[seed % er.DIMENSION] = 1.0
    values[(seed * 7 + 3) % er.DIMENSION] = 0.5
    return values


def test_tier_from_hostile_effect_requires_damage_and_a_target():
    assert menu_rank.tier_from_hostile_effect(5, True) == 1
    assert menu_rank.tier_from_hostile_effect(5, False) == 0
    assert menu_rank.tier_from_hostile_effect(0, True) == 0
    assert menu_rank.tier_from_hostile_effect(None, True) == 0


def test_tier_from_hazard_exposure_prefers_the_safe_destination():
    assert menu_rank.tier_from_hazard_exposure(False) == 1
    assert menu_rank.tier_from_hazard_exposure(None) == 1
    assert menu_rank.tier_from_hazard_exposure(True) == 0


def test_situation_text_names_only_what_was_passed_in():
    text = menu_rank.situation_text(15, 40, ["a visible foe"])
    assert "bloodied" in text and "a visible foe" in text
    assert "an unseen" not in text and "hidden" not in text


def test_situation_text_handles_full_health_and_no_targets():
    text = menu_rank.situation_text(40, 40, [])
    assert text == "you are unhurt"


def test_rank_ids_orders_by_tier_before_similarity():
    client = er.EmbeddingClient(transport=_fake_transport(_seeded_vector))
    rows = [("A", "raise a shield and brace", 0), ("B", "leave the poison cloud", 1), ("C", "strike the foe", 0)]
    assert menu_rank.rank_ids("you are standing in a hazardous area", rows, client=client) == ["B", "A", "C"]


def test_rank_ids_falls_back_to_tier_and_original_order_when_service_is_down():
    down = er.EmbeddingClient(transport=lambda *a: (_ for _ in ()).throw(OSError("offline")))
    rows = [("A", "strike the foe", 0), ("B", "leave the poison cloud", 1), ("C", "brace", 0)]
    assert menu_rank.rank_ids("you are standing in a hazardous area", rows, client=down) == ["B", "A", "C"]


def test_rank_ids_is_unchanged_for_fewer_than_two_rows():
    client = er.EmbeddingClient(transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network for one row")))
    assert menu_rank.rank_ids("q", [("A", "only", 0)], client=client) == ["A"]
    assert menu_rank.rank_ids("q", [], client=client) == []


def test_guard_blocks_real_sockets_to_the_live_embedding_port():
    """Safety (owner 2026-10-13): tests/conftest.py's session-wide block must
    actually be active -- a real socket to the live EmbeddingGemma port must
    never succeed during the suite, regardless of which module tries it."""
    with pytest.raises(OSError, match="tests must never reach"):
        # Exercise the installed class method before any syscall. Creating an
        # AF_INET socket itself is forbidden in the HeavyQ sandbox; the guard
        # must reject the address before inspecting/using the socket object.
        socket.socket.connect(None, ("127.0.0.1", 11448))


def test_default_client_requests_are_rate_limited(monkeypatch):
    monkeypatch.setattr(menu_rank, "_next_allowed_at", 0.0)
    monkeypatch.setattr(menu_rank, "_breaker_open_until", 0.0)
    monkeypatch.setattr(menu_rank, "_consecutive_failures", 0)
    clock = iter([0.0, 0.0, 0.05])  # two attempts within one interval
    assert menu_rank._default_client_request_allowed(lambda: next(clock)) is True
    assert menu_rank._default_client_request_allowed(lambda: next(clock)) is False


def test_default_client_breaker_opens_after_repeated_failures_then_cools_down(monkeypatch):
    monkeypatch.setattr(menu_rank, "_next_allowed_at", 0.0)
    monkeypatch.setattr(menu_rank, "_breaker_open_until", 0.0)
    monkeypatch.setattr(menu_rank, "_consecutive_failures", 0)
    clock = lambda: 0.0
    for _ in range(menu_rank._FAILURE_THRESHOLD):
        menu_rank._record_default_client_result(False, clock)
    assert menu_rank._default_client_request_allowed(lambda: 1.0) is False  # breaker open
    assert menu_rank._default_client_request_allowed(lambda: 1.0 + menu_rank._COOLDOWN_S) is True


def test_rank_ids_never_calls_the_default_client_while_the_breaker_is_open(monkeypatch):
    monkeypatch.setattr(menu_rank, "_breaker_open_until", time.monotonic() + 60)
    calls = []
    monkeypatch.setattr(menu_rank, "_CLIENT", er.EmbeddingClient(
        transport=lambda *a: calls.append(a),
        before_request=lambda: menu_rank._default_client_request_allowed(time.monotonic)))
    rows = [("A", "strike the foe", 0), ("B", "leave the poison cloud", 1)]
    assert menu_rank.rank_ids("you are standing in a hazardous area", rows) == ["B", "A"]
    assert calls == []


def test_network_failure_opens_breaker_even_when_ranking_falls_back(monkeypatch):
    monkeypatch.setattr(menu_rank, "_next_allowed_at", 0.0)
    monkeypatch.setattr(menu_rank, "_breaker_open_until", 0.0)
    monkeypatch.setattr(menu_rank, "_consecutive_failures", 0)
    now = [1.0]
    calls = []
    def down(*args):
        calls.append(args)
        raise OSError("offline")
    client = er.EmbeddingClient(transport=down, clock=lambda: now[0],
        before_request=lambda: menu_rank._default_client_request_allowed(lambda: now[0]),
        request_result=lambda ok: menu_rank._record_default_client_result(ok, lambda: now[0]))
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    rows = [("A", "brace", 0), ("B", "strike", 1)]
    for _ in range(5):
        assert menu_rank.rank_ids("q", rows) == ["B", "A"]
        now[0] += 1
    assert len(calls) == 3
    assert menu_rank._breaker_open_until > now[0]


def test_warm_cache_is_not_rejected_by_rate_limit():
    calls = []
    def transport(*args):
        calls.append(args)
        return _fake_transport(_seeded_vector)(*args)
    permits = iter([True, False])
    client = er.EmbeddingClient(transport=transport, before_request=lambda: next(permits))
    rows = [("A", "brace", 0), ("B", "strike", 0)]
    first = menu_rank.rank_ids("q", rows, client=client)
    assert menu_rank.rank_ids("q", rows, client=client) == first
    assert len(calls) == 1


def test_native_effectiveness_dominates_semantic_fit():
    client = er.EmbeddingClient(transport=_fake_transport(_seeded_vector))
    rows = [("A", "brace", 0), ("B", "strike", 1)]
    assert menu_rank.rank_ids("q", rows, client=client, scores={"A": 100, "B": 5}) == ["A", "B"]


def test_shortlist_reserves_space_for_each_slot_and_batches_once():
    calls = []
    def transport(*args):
        calls.append(json.loads(args[1])["input"])
        return _fake_transport(_seeded_vector)(*args)
    rows = [(f"a{i}", f"strike {i}", 1) for i in range(100)] + [("bonus", "heal", 0)]
    slots = {key: "Action" for key, _, _ in rows}
    slots["bonus"] = "Bonus action"
    result = menu_rank.rank_ids("q", rows, slots=slots, client=er.EmbeddingClient(transport=transport))
    assert len(calls) == 1 and len(calls[0]) == 17
    assert any("heal" in text for text in calls[0])
    assert set(result) == {row[0] for row in rows}


def test_unembedded_tail_keeps_native_preference_over_lower_scored_other_slot():
    client = er.EmbeddingClient(transport=_fake_transport(_seeded_vector))
    rows = [(f"a{i}", f"strike {i}", 1) for i in range(20)] + [("bonus", "heal", 0)]
    slots = {key: "Action" for key, _, _ in rows}
    slots["bonus"] = "Bonus action"
    result = menu_rank.rank_ids("q", rows, slots=slots, client=client)
    assert result.index("a19") < result.index("bonus")


def test_goal_uses_sheet_dao_and_iching_but_never_playbooks():
    sheet = {"character_dao": {"primary_sphere": "Water", "dao_verbs": ["adapt"],
              "layers": [{"name": "Water", "reality_principle": "flow"}],
              "hexagram": {"name": "The Well"}, "posture": {"natural": {"meaning": "respond with patience"}}},
             "dao_iching": {"dao": {"core_theme": "restore"}, "i_ching": {"change_rule": "yield under pressure"}},
             "composite_playbooks": {"secret": "never include this"}}
    text = menu_rank.goal_text(sheet)
    for value in ("Water", "adapt", "The Well", "restore", "yield under pressure"):
        assert value in text
    assert "never include this" not in text


def test_destination_hook_reorders_without_dropping_candidates():
    moves = [{"candidate_id": "a"}, {"candidate_id": "b"}]
    assert menu_rank.destination_order(moves, lambda rows: {"b": 10}) == [moves[1], moves[0]]


def test_goal_reads_existing_sheet_surface_and_nested_iching_document():
    data = {"dao_i_ching": {"dao": {"display_name": "Flow", "core_theme": "adapt"},
                            "i_ching": {"tactical_expression": "yield under pressure"}}}
    sheet = {"surfaces": {"dao_i_ching": {"data": data}}}
    assert "yield under pressure" in menu_rank.goal_text(sheet)
    assert "Flow" in menu_rank.goal_text(sheet)


def test_socket_connect_ex_is_also_guarded():
    with pytest.raises(OSError, match="tests must never reach"):
        socket.socket.connect_ex(None, ("127.0.0.1", 11448))


def test_seat_keys_reuse_exact_table_slots_and_preserve_native_expanded_variant():
    from agent_seats.menu_pages import slot_candidate_keys
    options = {key: {"candidate_id": candidate} for key, candidate in
               [("move-key", "move"), ("variant-1", "strike"), ("native", "strike"), ("bonus-key", "heal")]}
    slots = {"Movement": ["move"], "Action": ["strike"], "Bonus action": ["heal"]}
    assert slot_candidate_keys(slots, options, "native") == ["move-key", "native", "bonus-key"]


def test_late_cpu_batch_warms_cache_without_blocking_or_overlapping(monkeypatch):
    import threading
    entered, finish = threading.Event(), threading.Event()
    calls, outcomes, now = [], [], [0.0]
    def slow(url, body, timeout):
        calls.append((json.loads(body)["input"], timeout))
        entered.set()
        assert finish.wait(2)
        now[0] = 0.158  # measured CPU batch exceeds the old 150-ms allowance
        return _fake_transport(_seeded_vector)(url, body, timeout)
    client = er.EmbeddingClient(transport=slow, background=True, deadline_s=0.01,
                                clock=lambda: now[0], request_result=outcomes.append)
    rows = [("A", "brace", 0), ("B", "strike", 1)]
    start = time.monotonic()
    assert menu_rank.rank_ids("q", rows, client=client) == ["B", "A"]
    assert time.monotonic() - start < 0.1
    assert entered.wait(1)
    for _ in range(20):
        assert menu_rank.rank_ids("q", rows, client=client) == ["B", "A"]
    assert len(calls) == 1
    finish.set()
    assert client._lock.acquire(timeout=2)
    client._lock.release()
    assert len(client.embed(["q", "strike", "brace"])) == 3
    assert outcomes == [True] and len(calls) == 1
    assert calls[0][1] >= 0.3
    assert client.acceptance_budget(31) > client.acceptance_budget(6)
    assert client.acceptance_budget(10000) == 3.0


def test_next_actor_observed_menu_prefetch_is_bounded_and_rate_limited(monkeypatch):
    import threading
    from types import SimpleNamespace
    class Engine:
        state = SimpleNamespace(initiative_order=["a", "b"])
    engine = Engine()
    calls, done = [], threading.Event()
    monkeypatch.setattr(menu_rank, "_next_allowed_at", 0.0)
    monkeypatch.setattr(menu_rank, "_breaker_open_until", 0.0)
    def fake(url, body, timeout):
        calls.append((time.monotonic(), json.loads(body)["input"]))
        if len(calls) == 2:
            done.set()
        return _fake_transport(_seeded_vector)(url, body, timeout)
    client = er.EmbeddingClient(transport=fake, background=True,
        before_request=lambda: menu_rank._default_client_request_allowed(time.monotonic))
    menu_rank.prefetch_next_actor(engine, "b", ["b own view", "b own action"], client=client)
    with pytest.raises(er.EmbeddingError):
        client.embed(["a own view", "a own action"])
    menu_rank.prefetch_next_actor(engine, "a", ["a own view", "a own action"], client=client)
    assert done.wait(2)
    assert client._lock.acquire(timeout=2)
    client._lock.release()
    assert len(calls) == 2
    assert calls[1][0] - calls[0][0] >= 0.2
    assert "b own action" in calls[1][1][1]
